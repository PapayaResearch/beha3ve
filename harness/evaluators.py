import importlib
from typing import Any
from collections.abc import Callable, Mapping, Sequence
from pydantic import BaseModel, Field
from harness.schema import Transition


class OutcomeSpec(BaseModel):
    id: str
    direction: str = "report"
    function: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class Outcome(BaseModel):
    id: str
    value: Any = None
    direction: str = "report"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    outcomes: list[Outcome]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def by_id(self) -> dict[str, Outcome]:
        return {outcome.id: outcome for outcome in self.outcomes}


class FactorialContrast(BaseModel):
    factor: str
    low_level: str
    high_level: str
    outcome_id: str
    low_mean: float
    high_mean: float
    difference: float
    direction: str
    expected_relation: str


OutcomeFunction = Callable[..., Outcome | Any]


class OutcomeEvaluator:
    def __init__(
        self,
        outcomes: Sequence[OutcomeSpec | Mapping[str, Any]]
    ) -> None:
        self.outcome_specs = [
            outcome if isinstance(outcome, OutcomeSpec) else OutcomeSpec.model_validate(outcome)
            for outcome in outcomes
        ]

    def evaluate(
        self,
        trajectory: Sequence[Transition],
        state: Mapping[str, Any]
    ) -> EvaluationResult:
        state_outcomes = state.get("outcomes", {})
        outcomes = []
        for spec in self.outcome_specs:
            value = state_outcomes.get(spec.id)
            if spec.function is not None:
                function = resolve_outcome_function(spec.function)
                value = function(trajectory, state, **spec.arguments)
            if isinstance(value, Outcome):
                outcome = value
            else:
                outcome = Outcome(
                    id=spec.id,
                    value=value,
                    direction=spec.direction
                )
            outcomes.append(outcome)
        return EvaluationResult(
            outcomes=outcomes,
            metadata={"transition_count": len(trajectory)}
        )


def resolve_outcome_function(function: str) -> OutcomeFunction:
    module_name, function_name = function.rsplit(".", maxsplit=1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def paired_effects(
    control: EvaluationResult,
    treatment: EvaluationResult
) -> dict[str, float]:
    control_by_id = control.by_id()
    treatment_by_id = treatment.by_id()
    effects = {}
    for outcome_id in control_by_id.keys() & treatment_by_id.keys():
        control_value = control_by_id[outcome_id].value
        treatment_value = treatment_by_id[outcome_id].value
        if isinstance(control_value, int | float) and isinstance(treatment_value, int | float):
            effects[outcome_id] = treatment_value - control_value
    return effects


def factorial_main_effects(
    evaluations: Sequence[tuple[Mapping[str, str], EvaluationResult]],
    factors: Sequence[Mapping[str, Any]]
) -> list[FactorialContrast]:
    assert evaluations
    contrasts = []
    for factor in factors:
        assert len(factor["levels"]) == 2
        low_level, high_level = factor["levels"]
        outcome_ids = set.intersection(
            *(set(evaluation.by_id()) for _, evaluation in evaluations)
        )
        for outcome_id in sorted(outcome_ids):
            low_values = numeric_factor_values(
                evaluations=evaluations,
                factor=factor["id"],
                level=low_level,
                outcome_id=outcome_id
            )
            high_values = numeric_factor_values(
                evaluations=evaluations,
                factor=factor["id"],
                level=high_level,
                outcome_id=outcome_id
            )
            if low_values and high_values:
                low_mean = sum(low_values) / len(low_values)
                high_mean = sum(high_values) / len(high_values)
                direction = evaluations[0][1].by_id()[outcome_id].direction
                contrasts.append(
                    FactorialContrast(
                        factor=factor["id"],
                        low_level=low_level,
                        high_level=high_level,
                        outcome_id=outcome_id,
                        low_mean=low_mean,
                        high_mean=high_mean,
                        difference=high_mean - low_mean,
                        direction=direction,
                        expected_relation=factor.get(
                            "expected_relation",
                            "descriptive"
                        )
                    )
                )
    return contrasts


def numeric_factor_values(
    evaluations: Sequence[tuple[Mapping[str, str], EvaluationResult]],
    factor: str,
    level: str,
    outcome_id: str
) -> list[float]:
    values = []
    for assignments, evaluation in evaluations:
        if assignments[factor] == level:
            values.append(evaluation.by_id()[outcome_id].value)
    return [float(value) for value in values if isinstance(value, int | float)]
