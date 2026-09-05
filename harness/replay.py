import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from pydantic import BaseModel, Field
from tqdm import tqdm
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionHook
from harness.schema import InterventionApplication, Observation, Snapshot, Transition
from harness.serialization import content_hash


class ObserverView(BaseModel):
    parent_episode_id: str
    pause_step: int
    transitions: list[Transition]
    snapshot: Snapshot
    pause_position: str = "after"
    metadata: dict[str, Any] = Field(default_factory=dict)
    interventions: list[InterventionApplication] = Field(default_factory=list)


class HandoffLineage(BaseModel):
    parent_episode_id: str
    parent_pause_step: int
    parent_snapshot_hash: str
    child_episode_id: str


class HandoffBranch(BaseModel):
    observation: Observation
    lineage: HandoffLineage


class PauseSpec(BaseModel):
    id: str
    kind: str
    step: int | None = None
    progress: float | None = None


class TrajectoryReplay:
    def __init__(
        self,
        episode_id: str,
        trajectory: Sequence[Transition],
        runtime: CounterfactualRuntime | None = None
    ) -> None:
        self.episode_id = episode_id
        self.trajectory = list(trajectory)
        self.runtime = runtime or CounterfactualRuntime()
        self._handoff_snapshots: dict[tuple[int, str], Snapshot] = {}

    @classmethod
    def from_event_log(
        cls,
        path: str | Path,
        runtime: CounterfactualRuntime | None = None,
        episode_id: str | None = None,
        progress: bool = False
    ) -> "TrajectoryReplay":
        event_path = Path(path)
        records = []
        for line in tqdm(
            event_path.read_text(encoding="utf-8").splitlines(),
            desc="load replay",
            disable=not progress
        ):
            if line.strip():
                records.append(json.loads(line))
        transition_records = [
            record
            for record in records
            if record["type"] == "transition"
        ]
        assert transition_records
        available_episode_ids = {
            record["episode_id"]
            for record in transition_records
        }
        if episode_id is None:
            assert len(available_episode_ids) == 1
            selected_episode_id = next(iter(available_episode_ids))
        else:
            assert episode_id in available_episode_ids
            selected_episode_id = episode_id
        transitions = [
            Transition.model_validate(
                restore_portable(
                    record["transition"],
                    event_path.parent
                )
            )
            for record in transition_records
            if record["episode_id"] == selected_episode_id
        ]
        return cls(
            episode_id=selected_episode_id,
            trajectory=transitions,
            runtime=runtime
        )

    def pause(
        self,
        step: int,
        metadata: Mapping[str, Any] | None = None
    ) -> ObserverView:
        selected = [transition for transition in self.trajectory if transition.step <= step]
        assert selected
        assert selected[-1].step == step
        canonical_snapshot = selected[-1].after_snapshot
        return self._build_view(
            step=step,
            pause_position="after",
            transitions=selected,
            canonical_snapshot=canonical_snapshot,
            metadata=metadata
        )

    def pause_before_action(
        self,
        step: int,
        metadata: Mapping[str, Any] | None = None
    ) -> ObserverView:
        selected = [transition for transition in self.trajectory if transition.step < step]
        targets = [transition for transition in self.trajectory if transition.step == step]
        assert len(targets) == 1
        return self._build_view(
            step=step,
            pause_position="before",
            transitions=selected,
            canonical_snapshot=targets[0].before_snapshot,
            metadata=metadata
        )

    def _build_view(
        self,
        step: int,
        pause_position: str,
        transitions: Sequence[Transition],
        canonical_snapshot: Snapshot,
        metadata: Mapping[str, Any] | None
    ) -> ObserverView:
        view = ObserverView(
            parent_episode_id=self.episode_id,
            pause_step=step,
            pause_position=pause_position,
            transitions=[mask_transition(transition) for transition in transitions],
            snapshot=mask_snapshot(canonical_snapshot),
            metadata=dict(metadata or {})
        )
        edited, applications = self.runtime.apply(
            hook=InterventionHook.OBSERVER_PAUSE,
            value=view,
            context=InterventionContext(
                episode_id=self.episode_id,
                step=step,
                environment="replay",
                agent="observer",
                metadata=dict(metadata or {})
            )
        )
        final_view = ObserverView.model_validate(edited).model_copy(
            update={
                "parent_episode_id": self.episode_id,
                "pause_step": step,
                "pause_position": pause_position,
                "interventions": applications
            }
        )
        self._handoff_snapshots[(step, pause_position)] = canonical_snapshot
        return final_view

    def materialize_pauses(
        self,
        specs: Sequence[PauseSpec | Mapping[str, Any]]
    ) -> list[ObserverView]:
        pause_specs = [
            spec if isinstance(spec, PauseSpec) else PauseSpec.model_validate(spec)
            for spec in specs
        ]
        views = []
        for spec in pause_specs:
            step = resolve_pause_step(spec, self.trajectory)
            metadata = {"pause_id": spec.id, "pause_kind": spec.kind}
            if spec.kind == "before_commitment":
                views.append(
                    self.pause_before_action(
                        step=step,
                        metadata=metadata
                    )
                )
            else:
                views.append(self.pause(step=step, metadata=metadata))
        return views

    def validate_factor_applications(
        self,
        views: Sequence[ObserverView],
        assignments: Mapping[str, str]
    ) -> None:
        observed = {
            application.factor: application.level
            for view in views
            for application in view.interventions
            if application.factor in assignments
        }
        assert observed == dict(assignments)

    def restore_handoff(
        self,
        view: ObserverView,
        environment: Any,
        child_episode_id: str
    ) -> HandoffBranch:
        assert view.parent_episode_id == self.episode_id
        key = (view.pause_step, view.pause_position)
        if key in self._handoff_snapshots:
            canonical_snapshot = self._handoff_snapshots[key]
        else:
            transitions = [
                transition
                for transition in self.trajectory
                if transition.step == view.pause_step
            ]
            assert len(transitions) == 1
            canonical_snapshot = (
                transitions[0].before_snapshot
                if view.pause_position == "before"
                else transitions[0].after_snapshot
            )
        environment_backend = environment.snapshot().metadata.get("backend")
        snapshot_backend = canonical_snapshot.metadata.get("backend")
        assert environment_backend == snapshot_backend
        observation = environment.restore(canonical_snapshot)
        return HandoffBranch(
            observation=observation,
            lineage=HandoffLineage(
                parent_episode_id=self.episode_id,
                parent_pause_step=view.pause_step,
                parent_snapshot_hash=content_hash(canonical_snapshot),
                child_episode_id=child_episode_id
            )
        )


def mask_transition(transition: Transition) -> Transition:
    return transition.model_copy(
        deep=True,
        update={
            "before_snapshot": mask_snapshot(transition.before_snapshot),
            "after_snapshot": mask_snapshot(transition.after_snapshot),
            "info": {}
        }
    )


def resolve_pause_step(
    spec: PauseSpec,
    trajectory: Sequence[Transition]
) -> int:
    assert trajectory
    if spec.kind == "step":
        assert spec.step is not None
        return spec.step
    if spec.kind == "progress":
        assert spec.progress is not None
        assert 0.0 <= spec.progress <= 1.0
        index = round(spec.progress * (len(trajectory) - 1))
        return trajectory[index].step
    if spec.kind == "before_commitment":
        commitments = [
            transition.step
            for transition in trajectory
            if transition.action.kind in ("commit", "finish")
        ]
        assert commitments
        return commitments[0]
    raise ValueError("Unknown pause kind %s" % (spec.kind,))


def mask_snapshot(snapshot: Snapshot) -> Snapshot:
    observation = (
        None
        if snapshot.observation is None
        else snapshot.observation.model_copy(deep=True)
    )
    return Snapshot(
        step=snapshot.step,
        state={},
        observation=observation,
        metadata={"canonical_state_masked": True}
    )


def restore_portable(value: Any, artifact_root: Path) -> Any:
    if isinstance(value, list):
        return [restore_portable(item, artifact_root) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("encoding") == "base64" and set(value) == {"data", "encoding"}:
        return base64.b64decode(value["data"])
    if "artifact" in value and "media_type" in value:
        data = (artifact_root / value["artifact"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == value["sha256"]
        restored = {
            key: restore_portable(item, artifact_root)
            for key, item in value.items()
            if key not in ("artifact", "sha256")
        }
        restored["data"] = data
        return restored
    return {
        key: restore_portable(item, artifact_root)
        for key, item in value.items()
    }
