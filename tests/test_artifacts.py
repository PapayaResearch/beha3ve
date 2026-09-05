import json
from pathlib import Path
from omegaconf import OmegaConf
from run import write_pair_effects
from harness.artifacts import ArtifactWriter, RunManifest
from harness.evaluators import EvaluationResult, Outcome
from harness.runner import EpisodeResult
from harness.schema import Action, Observation, Snapshot, Transition, VisualObservation


def test_pair_effects_are_keyed_by_pair_and_condition(tmp_path: Path) -> None:
    config = OmegaConf.create(
        {
            "output_dir": str(tmp_path),
            "design": {
                "conditions": ["control", "treatment"],
                "repetitions": 1,
                "require_held_fixed_hash_match": True
            }
        }
    )
    control = make_manifest("control", "state")
    treatment = make_manifest("treatment", "state")
    results = [
        (
            EvaluationResult(
                outcomes=[Outcome(id="score", value=1.0, direction="maximize")]
            ),
            control
        ),
        (
            EvaluationResult(
                outcomes=[Outcome(id="score", value=3.0, direction="maximize")]
            ),
            treatment
        )
    ]

    path = write_pair_effects(config=config, condition_results=results)
    records = json.loads(path.read_text())

    assert records["pair-id"]["control_condition_id"] == "control"
    assert records["pair-id"]["treatment_condition_id"] == "treatment"
    assert records["pair-id"]["effects"]["score"] == 2.0


def make_manifest(condition_id: str, state_hash: str) -> RunManifest:
    return RunManifest(
        run_id="run",
        episode_id=condition_id,
        task_id="task",
        fixture_version="1",
        fixture_hash="fixture",
        canonical_initial_state_hash=state_hash,
        final_state_hash=state_hash,
        seed=0,
        condition_id=condition_id,
        pair_id="pair-id",
        environment_id="browser",
        agent_id="agent",
        evaluator_id="outcomes",
        metadata={
            "pair_key": {"task.id": "task", "seed": 0},
            "held_fixed": ["fixture"]
        }
    )


def test_writer_separates_interventions_and_trajectory(tmp_path: Path) -> None:
    observation = Observation(step=0, text="example")
    snapshot = Snapshot(step=0, state={"terminated": True}, observation=observation)
    transition = Transition(
        step=0,
        observation=observation,
        action=Action(kind="finish"),
        next_observation=observation,
        before_snapshot=snapshot,
        after_snapshot=snapshot,
        terminated=True
    )
    result = EpisodeResult(
        episode_id="episode",
        seed=0,
        initial_snapshot=snapshot,
        final_snapshot=snapshot,
        trajectory=[transition],
        evaluation=EvaluationResult(outcomes=[])
    )

    ArtifactWriter(tmp_path).write(
        config={},
        manifest=make_manifest("control", "state"),
        result=result
    )

    assert (tmp_path / "interventions.json").exists()
    assert (tmp_path / "trajectory.jsonl").exists()
    assert (tmp_path / "blobs").is_dir()


def test_writer_does_not_create_empty_image_artifact(tmp_path: Path) -> None:
    observation = Observation(
        step=0,
        visual=VisualObservation(data=b"", width=1280, height=720)
    )
    snapshot = Snapshot(step=0, state={"terminated": True}, observation=observation)
    transition = Transition(
        step=0,
        observation=observation,
        action=Action(kind="finish"),
        next_observation=observation,
        before_snapshot=snapshot,
        after_snapshot=snapshot,
        terminated=True
    )
    result = EpisodeResult(
        episode_id="episode",
        seed=0,
        initial_snapshot=snapshot,
        final_snapshot=snapshot,
        trajectory=[transition],
        evaluation=EvaluationResult(outcomes=[])
    )

    ArtifactWriter(tmp_path).write(
        config={},
        manifest=make_manifest("control", "state"),
        result=result
    )

    assert not list((tmp_path / "blobs").iterdir())
    transition_record = json.loads((tmp_path / "trajectory.jsonl").read_text().splitlines()[1])
    assert transition_record["transition"]["observation"]["visual"]["artifact"] is None
