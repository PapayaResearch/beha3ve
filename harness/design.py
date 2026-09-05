import itertools
import random
import re
from typing import Any
from collections.abc import Mapping, Sequence
from pydantic import BaseModel, Field


class Factor(BaseModel):
    id: str
    levels: list[str]
    expected_relation: str = "descriptive"


class Condition(BaseModel):
    id: str
    intervention_id: str
    assignments: dict[str, str] = Field(default_factory=dict)
    expected_relations: dict[str, str] = Field(default_factory=dict)
    repetition: int = 0


def materialize_design(
    kind: str,
    intervention_id: str,
    factors: Sequence[Factor | Mapping[str, Any]] = (),
    explicit_conditions: Sequence[str] = (),
    repetitions: int = 1,
    shuffle: bool = False,
    seed: int = 0
) -> list[Condition]:
    assert repetitions > 0
    assert safe_condition_id(intervention_id)
    if kind == "single":
        condition_id = explicit_conditions[0] if explicit_conditions else intervention_id
        assert len(explicit_conditions) <= 1 and safe_condition_id(condition_id)
        base_conditions = [
            Condition(
                id=condition_id,
                intervention_id=condition_id
            )
        ]
    elif kind == "paired":
        condition_ids = list(explicit_conditions or ["control", intervention_id])
        assert all(safe_condition_id(condition_id) for condition_id in condition_ids)
        assert len(set(condition_ids)) == len(condition_ids)
        base_conditions = [
            Condition(id=condition_id, intervention_id=condition_id)
            for condition_id in condition_ids
        ]
    else:
        assert kind == "factorial"
        factor_specs = [
            factor if isinstance(factor, Factor) else Factor.model_validate(factor)
            for factor in factors
        ]
        assert factor_specs
        base_conditions = []
        for levels in itertools.product(*(factor.levels for factor in factor_specs)):
            assignments = {
                factor.id: level
                for factor, level in zip(factor_specs, levels, strict=True)
            }
            condition_id = "__".join(
                "%s-%s" % (slug(key), slug(value))
                for key, value in assignments.items()
            )
            base_conditions.append(
                Condition(
                    id=condition_id,
                    intervention_id=intervention_id,
                    assignments=assignments,
                    expected_relations={
                        factor.id: factor.expected_relation
                        for factor in factor_specs
                    }
                )
            )
        assert len({condition.id for condition in base_conditions}) == len(base_conditions)
    conditions = []
    for repetition in range(repetitions):
        conditions.extend(
            condition.model_copy(update={"repetition": repetition})
            for condition in base_conditions
        )
    if shuffle:
        random.Random(seed).shuffle(conditions)
    return conditions


def slug(value: str) -> str:
    return re.sub("[^a-z0-9]+", "-", value.lower()).strip("-")


def safe_condition_id(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and value not in (".", "..")
