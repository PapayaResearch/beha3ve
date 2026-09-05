import hydra
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from tqdm import tqdm
from dotenv import load_dotenv
from omegaconf import DictConfig, OmegaConf
from harness.agents import AgentSpec, build_agent, edit_agent_spec
from harness.artifacts import ArtifactWriter, PairManifest, RunManifest
from harness.design import Condition, materialize_design
from harness.environments.base import EnvironmentCapability
from harness.evaluators import OutcomeEvaluator, EvaluationResult, factorial_main_effects, paired_effects
from harness.interventions import CounterfactualRuntime
from harness.runner import EpisodeResult, EpisodeRunner
from harness.serialization import canonical_json, content_hash


load_dotenv(Path(__file__).with_name(".env"))


@hydra.main(version_base="1.3", config_path="conf", config_name="config")
def main(config: DictConfig):
    config.output_dir = str(Path(config.output_dir).expanduser().resolve())
    print_run_plan(config)
    archived_output = archive_existing_output(Path(config.output_dir))
    if archived_output is not None:
        print("Archived existing output to %s" % (archived_output,))
    factors = to_plain(config.design.get("cross_factors", []))
    conditions = materialize_design(
        kind=config.design.kind,
        intervention_id=config.task.intervention.id,
        factors=factors,
        explicit_conditions=to_plain(config.design.conditions),
        repetitions=config.design.repetitions,
        shuffle=config.design.shuffle,
        seed=config.seed
    )
    run_root = Path(config.output_dir)
    if len(conditions) > 1:
        assert not run_root.exists() or not any(run_root.iterdir())
    outputs = [
        run_condition(
            config=config,
            condition=condition,
            condition_count=len(conditions),
            progress=bool(config.progress)
        )
        for condition in tqdm(conditions, desc="Conditions", disable=not config.progress)
    ]
    condition_results: list[tuple[EvaluationResult, RunManifest]] = []
    for output_dir, evaluation, manifest in outputs:
        condition_results.append((evaluation, manifest))
        print("Wrote episode artifacts to %s" % (output_dir,))
    if config.design.kind == "paired":
        effect_path = write_pair_effects(
            config=config,
            condition_results=condition_results
        )
        print("Wrote paired effects to %s" % (effect_path,))
    if config.design.kind == "factorial":
        contrast_path = write_factorial_contrasts(
            config=config,
            condition_results=condition_results
        )
        print("Wrote factorial contrasts to %s" % (contrast_path,))
    print("View trajectories: uv run view %s" % (run_root,))


def archive_existing_output(output_dir: Path) -> Path | None:
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return None
    index = 1
    archived_output = output_dir.parent / (
        "%s.previous-%d" % (
            output_dir.name,
            index
        )
    )
    while archived_output.exists():
        index += 1
        archived_output = output_dir.parent / (
            "%s.previous-%d" % (
                output_dir.name,
                index
            )
        )
    output_dir.rename(archived_output)
    return archived_output


def print_run_plan(config: DictConfig) -> None:
    specs = to_plain(config.task.intervention.specs)
    print("Task: %s" % (config.task.id,))
    print("Experiment: %s" % (config.experiment_id,))
    print("Agent: %s" % (config.agent.id,))
    if "chat_model_args" in config.agent.spec.config:
        print("Model: %s" % (config.agent.spec.config.chat_model_args.model,))
    print("Environment: %s" % (config.environment.id,))
    print("Design: %s" % (config.design.kind,))
    print("Output: %s" % (config.output_dir,))
    if not specs:
        print("Interventions: none")
        return
    print("Interventions:")
    for spec in specs:
        print(
            "  %s | %s | %s | %s" % (
                spec["id"],
                spec["scope"],
                spec["hook"],
                spec["function"]
            )
        )


def run_condition(
    config: DictConfig,
    condition: Condition,
    condition_count: int,
    progress: bool
) -> tuple[str, EvaluationResult, RunManifest]:
    condition_config = OmegaConf.create(
        OmegaConf.to_container(config, resolve=True)
    )
    condition_config.seed = int(condition_config.seed) + condition.repetition
    base_output_dir = Path(condition_config.output_dir)
    if condition.intervention_id == "control":
        selected_specs: list[dict[str, Any]] = []
    else:
        selected_specs = select_intervention_specs(
            specs=to_plain(condition_config.task.intervention.specs),
            assignments=condition.assignments,
            factors=to_plain(condition_config.task.factors)
        )
    validate_factor_bindings(
        specs=selected_specs,
        assignments=condition.assignments,
        required=bool(condition_config.design.get("require_factor_bindings", False))
    )
    condition_config.task.intervention.specs = selected_specs
    OmegaConf.update(
        condition_config,
        "condition",
        condition.model_dump(mode="python"),
        force_add=True
    )
    if condition_count > 1:
        condition_label = condition.id
        if int(condition_config.design.repetitions) > 1:
            condition_label = "%s__rep-%d" % (
                condition_label,
                condition.repetition
            )
        condition_config.episode_id = "%s-%s" % (
            condition_config.episode_id,
            condition_label
        )
        condition_config.output_dir = str(base_output_dir / condition_label)
    pair_key = (
        {}
        if condition_config.design.kind == "single"
        else build_pair_key(
            config=condition_config,
            fields=to_plain(condition_config.design.pair_on)
        )
    )
    pair_id = None if not pair_key else "pair-%s" % (content_hash(pair_key)[:16],)
    runtime = CounterfactualRuntime(specs=selected_specs)
    runtime.reset()
    agent_spec, agent_applications = edit_agent_spec(
        spec=AgentSpec.model_validate(
            OmegaConf.to_container(condition_config.agent.spec, resolve=True)
        ),
        runtime=runtime,
        episode_id=condition_config.episode_id,
        task_id=condition_config.task.id,
        seed=condition_config.seed,
        condition=condition.assignments
    )
    agent = build_agent(agent_spec)
    adapter_arguments: dict[str, Any] = {
        "runtime": runtime,
        "episode_id": condition_config.episode_id,
        "task_id": condition_config.task.id,
        "condition": condition.assignments
    }
    if condition_config.environment.id == "structured":
        adapter_arguments["actor_id"] = agent_spec.id
    else:
        adapter_arguments["agent"] = agent_spec.id
    environment = hydra.utils.instantiate(
        condition_config.environment.adapter,
        **adapter_arguments
    )
    environment.require_capabilities(
        [
            EnvironmentCapability(value)
            for value in condition_config.task.required_capabilities
        ]
    )
    evaluator = OutcomeEvaluator(outcomes=to_plain(condition_config.task.outcomes))
    runner = EpisodeRunner(
        environment=environment,
        agent=agent,
        evaluator=evaluator,
        max_steps=condition_config.max_steps,
        progress=progress
    )
    try:
        result = runner.run(
            episode_id=condition_config.episode_id,
            seed=condition_config.seed,
            options={
                **OmegaConf.to_container(
                    condition_config.task.fixture,
                    resolve=True
                ),
                "condition": condition.assignments
            }
        )
    finally:
        environment.close()
    validate_observed_factor_levels(
        result=result,
        agent_applications=agent_applications,
        assignments=condition.assignments,
        required=bool(condition_config.design.get("require_factor_bindings", False))
    )
    if condition_config.design.get("require_intervention_application", False):
        applied = {
            application.intervention_id
            for transition in result.trajectory
            for application in transition.interventions
            if application.changed_fields
        } | {application.intervention_id for application in agent_applications if application.changed_fields}
        assert {spec["id"] for spec in selected_specs} <= applied, "Some configured interventions never changed their target"
    manifest = RunManifest(
        schema_version=condition_config.schema_version,
        run_id=condition_config.run_id,
        episode_id=condition_config.episode_id,
        task_id=condition_config.task.id,
        fixture_version=condition_config.task.fixture_version,
        fixture_hash=content_hash(
            OmegaConf.to_container(condition_config.task.fixture, resolve=True)
        ),
        canonical_initial_state_hash=content_hash(result.initial_snapshot.state),
        final_state_hash=content_hash(result.final_snapshot.state),
        seed=condition_config.seed,
        condition_id=condition.id,
        pair_id=pair_id,
        environment_id=condition_config.environment.id,
        agent_id=condition_config.agent.id,
        evaluator_id="outcomes",
        interventions=selected_specs,
        metadata={
            "assignments": condition.assignments,
            "expected_relations": condition.expected_relations,
            "held_fixed": list(condition_config.task.held_fixed),
            "repetition": condition.repetition,
            "pair_key": pair_key,
            "agent_profile": condition_config.agent.id,
            "modality": condition_config.task.modality,
            "model": agent_spec.config.get("chat_model_args", {}).get("model"),
            "experiment_id": condition_config.experiment_id,
            "agent_interventions": [
                application.model_dump(mode="json")
                for application in agent_applications
            ],
            "applications": [
                application.model_dump(mode="json")
                for transition in result.trajectory
                for application in transition.interventions
            ]
        }
    )
    output_dir = Path(condition_config.output_dir)
    assert output_dir.is_relative_to(base_output_dir)
    writer = ArtifactWriter(output_dir)
    writer.write(config=condition_config, manifest=manifest, result=result)
    return str(output_dir), result.evaluation, manifest


def select_intervention_specs(
    specs: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    factors: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    expected_relations = {
        factor["id"]: factor.get("expected_relation", "descriptive")
        for factor in factors
    }
    selected = [
        {
            **dict(spec),
            "selector": {
                **dict(spec.get("selector", {})),
                **{
                    factor: level
                    for factor, level in assignments.items()
                    if factor != spec["factor"]
                }
            },
            "expected_relation": spec.get("expected_relation") or expected_relations.get(spec["factor"])
        }
        for spec in specs
        if spec["factor"] not in assignments
        or spec["level"] == assignments[spec["factor"]]
    ]
    selected_factors = [
        spec["factor"]
        for spec in selected
        if spec["factor"] in assignments
    ]
    assert len(selected_factors) == len(set(selected_factors))
    return selected


def validate_factor_bindings(
    specs: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    required: bool
) -> None:
    available_factors = {spec["factor"] for spec in specs}
    bound = {
        spec["factor"]: spec["level"]
        for spec in specs
        if spec["factor"] in assignments
    }
    assert all(
        factor not in available_factors or bound.get(factor) == level
        for factor, level in assignments.items()
    )
    if required:
        assert bound == dict(assignments)


def build_pair_key(config: DictConfig, fields: Sequence[str]) -> dict[str, Any]:
    values = {
        field: select_pair_value(config, field)
        for field in fields
    }
    assert all(value is not None for value in values.values())
    return values


def select_pair_value(config: DictConfig, field: str) -> Any:
    if field == "seed":
        return config.seed
    if field == "task.id":
        return config.task.id
    return to_plain(OmegaConf.select(config, field))


def validate_observed_factor_levels(
    result: EpisodeResult,
    agent_applications: Sequence[Any],
    assignments: Mapping[str, str],
    required: bool
) -> None:
    if not required:
        return
    observed = {
        application.factor: application.level
        for transition in result.trajectory
        for application in transition.interventions
        if application.factor in assignments
        and application.changed_fields
    }
    observed.update(
        {
            application.factor: application.level
            for application in agent_applications
            if application.factor in assignments
            and application.changed_fields
        }
    )
    assert observed == dict(assignments)


def write_pair_effects(
    config: DictConfig,
    condition_results: Sequence[tuple[EvaluationResult, RunManifest]]
) -> Path:
    condition_ids = list(to_plain(config.design.conditions))
    assert len(condition_ids) == 2
    grouped: dict[str, list[tuple[EvaluationResult, RunManifest]]] = {}
    for evaluation, manifest in condition_results:
        assert manifest.pair_id is not None
        grouped.setdefault(manifest.pair_id, []).append((evaluation, manifest))
    assert len(grouped) == int(config.design.repetitions)

    pair_records = {}
    for pair_id, pair in grouped.items():
        assert len(pair) == 2
        by_condition = {
            manifest.condition_id: (evaluation, manifest)
            for evaluation, manifest in pair
        }
        assert set(by_condition) == set(condition_ids)
        control_evaluation, control_manifest = by_condition[condition_ids[0]]
        treatment_evaluation, treatment_manifest = by_condition[condition_ids[1]]
        assert control_manifest.pair_id == treatment_manifest.pair_id
        assert control_manifest.task_id == treatment_manifest.task_id
        assert control_manifest.fixture_hash == treatment_manifest.fixture_hash
        assert control_manifest.seed == treatment_manifest.seed
        assert control_manifest.metadata["pair_key"] == treatment_manifest.metadata["pair_key"]
        treatment_changes_start = any(
            spec["hook"] == "episode_start"
            for spec in treatment_manifest.interventions
        )
        if config.design.require_held_fixed_hash_match and not treatment_changes_start:
            assert control_manifest.canonical_initial_state_hash == treatment_manifest.canonical_initial_state_hash
        pair_manifest = PairManifest(
            schema_version=control_manifest.schema_version,
            pair_id=pair_id,
            task_id=control_manifest.task_id,
            fixture_hash=control_manifest.fixture_hash,
            seed=control_manifest.seed,
            control_condition_id=control_manifest.condition_id,
            treatment_condition_id=treatment_manifest.condition_id,
            control_initial_state_hash=control_manifest.canonical_initial_state_hash,
            treatment_initial_state_hash=treatment_manifest.canonical_initial_state_hash,
            control_intervention_hash=content_hash(control_manifest.interventions),
            treatment_intervention_hash=content_hash(treatment_manifest.interventions),
            held_fixed_fields=control_manifest.metadata["held_fixed"],
            effects=paired_effects(control_evaluation, treatment_evaluation),
            outcome_directions={
                outcome.id: outcome.direction
                for outcome in control_evaluation.outcomes
            },
            outcome_evidence={
                outcome.id: {
                    "control": outcome.evidence,
                    "treatment": treatment_evaluation.by_id()[outcome.id].evidence
                }
                for outcome in control_evaluation.outcomes
                if outcome.id in treatment_evaluation.by_id()
            }
        )
        pair_records[pair_id] = {
            "pair_key": control_manifest.metadata["pair_key"],
            **pair_manifest.model_dump(mode="json")
        }
    effect_path = Path(config.output_dir) / "paired_effects.json"
    effect_path.parent.mkdir(parents=True, exist_ok=True)
    effect_path.write_text(
        "%s\n" % (canonical_json(pair_records),),
        encoding="utf-8"
    )
    return effect_path


def write_factorial_contrasts(
    config: DictConfig,
    condition_results: Sequence[tuple[EvaluationResult, RunManifest]]
) -> Path:
    evaluations = [
        (manifest.metadata["assignments"], evaluation)
        for evaluation, manifest in condition_results
    ]
    factors = [
        factor
        for factor in to_plain(config.design.cross_factors)
        if len(factor["levels"]) == 2
    ]
    contrasts = factorial_main_effects(evaluations, factors)
    contrast_path = Path(config.output_dir) / "factorial_contrasts.json"
    contrast_path.parent.mkdir(parents=True, exist_ok=True)
    contrast_path.write_text(
        "%s\n" % (canonical_json(contrasts),),
        encoding="utf-8"
    )
    return contrast_path


def to_plain(value: Any) -> Any:
    if OmegaConf.is_config(value):
        return OmegaConf.to_container(value, resolve=True)
    return value


if __name__ == "__main__":
    main()
