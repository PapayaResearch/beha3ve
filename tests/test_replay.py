from pathlib import Path
from harness.artifacts import ArtifactWriter, RunManifest
from harness.environments.computer_use import ComputerUseEnvironment, MemoryComputerUseBackend
from harness.evaluators import EvaluationResult
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionResult, InterventionSpec
from harness.replay import TrajectoryReplay
from harness.runner import EpisodeResult
from harness.schema import Action


def test_observer_view_uses_frozen_trace_and_restorable_snapshot() -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    environment.reset(seed=7)
    transition = environment.step(
        Action(kind="move_pointer", arguments={"x": 4, "y": 8})
    )
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="observer",
                factor="view",
                level="minimal",
                scope="observer",
                target="observer_view",
                modality="structured",
                hook="observer_pause",
                function="observer-edit"
            )
        ],
        registry={"observer-edit": edit_observer_view}
    )
    replay = TrajectoryReplay(
        episode_id="episode",
        trajectory=[transition],
        runtime=runtime
    )

    view = replay.pause(step=0)
    environment.step(Action(kind="move_pointer", arguments={"x": 9, "y": 9}))
    branch = replay.restore_handoff(
        view,
        environment,
        child_episode_id="child"
    )

    assert view.metadata["view"] == "minimal"
    assert view.interventions[0].scope == "observer"
    assert view.snapshot.state == {}
    assert view.snapshot.metadata["canonical_state_masked"]
    assert view.transitions[0].before_snapshot.state == {}
    assert view.transitions[0].after_snapshot.state == {}
    assert transition.after_snapshot.state["cursor"] == {"x": 4, "y": 8}
    assert environment.inspect()["cursor"] == {"x": 4, "y": 8}
    assert branch.observation.structured["cursor"] == {"x": 4, "y": 8}
    assert branch.lineage.parent_episode_id == "episode"
    assert branch.lineage.parent_pause_step == 0
    assert branch.lineage.parent_snapshot_hash
    assert branch.lineage.child_episode_id == "child"


def test_observer_edits_cannot_change_canonical_handoff_state() -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    environment.reset(seed=9)
    transition = environment.step(
        Action(kind="move_pointer", arguments={"x": 4, "y": 8})
    )
    replay = TrajectoryReplay(episode_id="episode", trajectory=[transition])
    view = replay.pause(step=0)
    view.snapshot = transition.before_snapshot

    replay.restore_handoff(view, environment, child_episode_id="child")

    assert environment.inspect()["cursor"] == {"x": 4, "y": 8}


def test_replay_loads_saved_renderer_neutral_event_log(tmp_path: Path) -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    _, initial_snapshot = environment.reset(seed=11)
    transition = environment.step(
        Action(kind="move_pointer", arguments={"x": 3, "y": 5})
    )
    result = EpisodeResult(
        episode_id="saved-episode",
        seed=11,
        initial_snapshot=initial_snapshot,
        final_snapshot=transition.after_snapshot,
        trajectory=[transition],
        evaluation=EvaluationResult(outcomes=[])
    )
    writer = ArtifactWriter(tmp_path)
    writer.write(
        config={},
        manifest=RunManifest(
            run_id="saved-run",
            episode_id="saved-episode",
            task_id="observer-handoff",
            fixture_version="1",
            fixture_hash="fixture",
            canonical_initial_state_hash="initial",
            final_state_hash="final",
            seed=11,
            condition_id="control",
            environment_id="computer_use",
            agent_id="agent",
            evaluator_id="outcomes"
        ),
        result=result
    )

    replay = TrajectoryReplay.from_event_log(tmp_path / "trajectory.jsonl")

    assert replay.episode_id == "saved-episode"
    assert len(replay.trajectory) == 1
    assert replay.trajectory[0].next_observation.visual is not None
    assert replay.trajectory[0].next_observation.visual.data == b"screen"
    assert replay.trajectory[0].after_snapshot.state["screenshot"] == b"screen"


def test_replay_materializes_prespecified_progress_pause() -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    environment.reset(seed=12)
    transitions = [
        environment.step(
            Action(kind="move_pointer", arguments={"x": index, "y": index})
        )
        for index in range(3)
    ]
    replay = TrajectoryReplay(episode_id="episode", trajectory=transitions)

    views = replay.materialize_pauses(
        [{"id": "midpoint", "kind": "progress", "progress": 0.5}]
    )

    assert views[0].pause_step == 1
    assert views[0].metadata["pause_id"] == "midpoint"


def test_before_commitment_pause_uses_pre_action_snapshot() -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    environment.reset(seed=13)
    transition = environment.step(Action(kind="finish"))
    replay = TrajectoryReplay(episode_id="episode", trajectory=[transition])

    views = replay.materialize_pauses(
        [{"id": "commitment", "kind": "before_commitment"}]
    )

    assert views[0].transitions == []
    assert views[0].snapshot.step == 0
    assert views[0].metadata["pause_kind"] == "before_commitment"


def test_replay_validates_observer_factor_application() -> None:
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"screen")
    )
    environment.reset(seed=14)
    transition = environment.step(Action(kind="finish"))
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="observer",
                factor="observer_view",
                level="minimal",
                scope="observer",
                target="observer_view",
                modality="structured",
                hook="observer_pause",
                function="observer-edit"
            )
        ],
        registry={"observer-edit": edit_observer_view}
    )
    replay = TrajectoryReplay(
        episode_id="episode",
        trajectory=[transition],
        runtime=runtime
    )
    views = replay.materialize_pauses(
        [{"id": "pause", "kind": "before_commitment"}]
    )

    replay.validate_factor_applications(
        views=views,
        assignments={"observer_view": "minimal"}
    )


def edit_observer_view(
    value: object,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(
        value=value.model_copy(
            update={
                "metadata": {
                    **value.metadata,
                    "view": "minimal"
                }
            }
        ),
        changed_fields=["metadata.view"]
    )
