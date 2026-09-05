import hashlib
import json
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from omegaconf import DictConfig, OmegaConf
from pydantic import BaseModel, Field
from harness.runner import EpisodeResult
from harness.serialization import canonical_json, canonicalize


class RunManifest(BaseModel):
    schema_version: str = "1"
    run_id: str
    episode_id: str
    task_id: str
    fixture_version: str
    fixture_hash: str
    canonical_initial_state_hash: str
    final_state_hash: str
    seed: int
    condition_id: str
    pair_id: str | None = None
    environment_id: str
    agent_id: str
    evaluator_id: str
    interventions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PairManifest(BaseModel):
    schema_version: str = "1"
    pair_id: str
    task_id: str
    fixture_hash: str
    seed: int
    control_condition_id: str
    treatment_condition_id: str
    control_initial_state_hash: str
    treatment_initial_state_hash: str
    control_intervention_hash: str
    treatment_intervention_hash: str
    held_fixed_fields: list[str] = Field(default_factory=list)
    effects: dict[str, float] = Field(default_factory=dict)
    outcome_directions: dict[str, str] = Field(default_factory=dict)
    outcome_evidence: dict[str, dict[str, list[dict[str, Any]]]] = Field(default_factory=dict)


class ArtifactWriter:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.artifact_dir = self.output_dir / "blobs"

    def write(
        self,
        config: DictConfig | Mapping[str, Any],
        manifest: RunManifest,
        result: EpisodeResult
    ) -> None:
        assert not self.output_dir.exists() or not any(self.output_dir.iterdir())
        assert manifest.fixture_hash
        assert manifest.canonical_initial_state_hash
        assert manifest.final_state_hash
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(config, DictConfig):
            OmegaConf.save(config, self.output_dir / "config.yaml", resolve=True)
        else:
            OmegaConf.save(OmegaConf.create(config), self.output_dir / "config.yaml", resolve=True)
        self._write_json("manifest.json", manifest)
        self._write_json(
            "interventions.json",
            {
                "configured": manifest.interventions,
                "applications": [
                    *manifest.metadata.get("agent_interventions", []),
                    *[
                        application.model_dump(mode="json")
                        for transition in result.trajectory
                        for application in transition.interventions
                    ],
                    *result.initial_snapshot.metadata.get("interventions", []),
                    *result.final_snapshot.metadata.get("interventions", [])
                ]
            }
        )
        self._write_trajectory(result, manifest)
        self._write_json("outcomes.json", result.evaluation)
        self._write_json("snapshots.json", {
            "initial": result.initial_snapshot,
            "final": result.final_snapshot
        })

    def store_blob(self, data: bytes, extension: str) -> str:
        digest = hashlib.sha256(data).hexdigest()
        suffix = extension.lstrip(".")
        assert suffix.replace("+", "").isalnum()
        path = self.artifact_dir / ("%s.%s" % (digest, suffix))
        path.write_bytes(data)
        return str(path.relative_to(self.output_dir))

    def _write_json(self, name: str, value: Any) -> None:
        (self.output_dir / name).write_text(
            "%s\n" % (canonical_json(self._portable(value))),
            encoding="utf-8"
        )

    def _write_trajectory(
        self,
        result: EpisodeResult,
        manifest: RunManifest
    ) -> None:
        records = [
            {
                "type": "episode",
                "episode_id": result.episode_id,
                "seed": result.seed,
                "initial_snapshot": self._portable(result.initial_snapshot)
            }
        ]
        records.extend(
            {
                "type": "intervention",
                "episode_id": result.episode_id,
                "step": 0,
                "application": self._portable(application)
            }
            for application in manifest.metadata.get("agent_interventions", [])
        )
        for transition in result.trajectory:
            records.append({
                "type": "transition",
                "episode_id": result.episode_id,
                "transition": self._portable(transition)
            })
            records.extend(
                {
                    "type": "intervention",
                    "episode_id": result.episode_id,
                    "step": transition.step,
                    "application": self._portable(application)
                }
                for application in transition.interventions
            )
        records.append({
            "type": "evaluation",
            "episode_id": result.episode_id,
            "evaluation": self._portable(result.evaluation),
            "final_snapshot": self._portable(result.final_snapshot)
        })
        text = "".join(
            "%s\n" % (json.dumps(record, sort_keys=True))
            for record in records
        )
        (self.output_dir / "trajectory.jsonl").write_text(text, encoding="utf-8")

    def _portable(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return self._portable(value.model_dump(mode="python"))
        if isinstance(value, Mapping):
            if isinstance(value.get("data"), bytes) and "media_type" in value:
                media_type = value["media_type"]
                extension = media_type.split("/", maxsplit=1)[-1]
                extension = "jpg" if extension == "jpeg" else extension
                assert extension.replace("+", "").isalnum()
                data = value["data"]
                portable = {
                    key: self._portable(item)
                    for key, item in value.items()
                    if key != "data"
                }
                if not data:
                    portable["artifact"] = None
                    portable["sha256"] = None
                    return portable
                portable["artifact"] = self.store_blob(data, extension)
                portable["sha256"] = hashlib.sha256(data).hexdigest()
                return portable
            return {key: self._portable(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return [self._portable(item) for item in value]
        return canonicalize(value)
