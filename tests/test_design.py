import pytest
from omegaconf import OmegaConf
from run import build_pair_key
from harness.design import materialize_design


def test_single_and_paired_designs_keep_conditions_attributable() -> None:
    single = materialize_design(kind="single", intervention_id="treatment")
    paired = materialize_design(
        kind="paired",
        intervention_id="treatment",
        explicit_conditions=["control", "treatment"]
    )

    assert [condition.id for condition in single] == ["treatment"]
    assert [condition.id for condition in paired] == ["control", "treatment"]


def test_factorial_design_crosses_declared_levels() -> None:
    conditions = materialize_design(
        kind="factorial",
        intervention_id="factorial",
        factors=[
            {
                "id": "pressure",
                "levels": ["low", "high"],
                "expected_relation": "invariant"
            },
            {
                "id": "authority",
                "levels": ["peer", "manager"],
                "expected_relation": "switch"
            }
        ]
    )

    assert len(conditions) == 4
    assert conditions[0].assignments == {
        "pressure": "low",
        "authority": "peer"
    }
    assert conditions[0].expected_relations == {
        "pressure": "invariant",
        "authority": "switch"
    }


def test_repetitions_preserve_condition_identity_and_increment_repetition() -> None:
    conditions = materialize_design(
        kind="paired",
        intervention_id="treatment",
        explicit_conditions=["control", "treatment"],
        repetitions=2
    )

    assert [
        (condition.id, condition.repetition)
        for condition in conditions
    ] == [
        ("control", 0),
        ("treatment", 0),
        ("control", 1),
        ("treatment", 1)
    ]


def test_shuffle_is_deterministic_for_the_design_seed() -> None:
    arguments = {
        "kind": "factorial",
        "intervention_id": "treatment",
        "factors": [
            {"id": "pressure", "levels": ["low", "high"]},
            {"id": "authority", "levels": ["peer", "manager"]}
        ],
        "repetitions": 2,
        "shuffle": True,
        "seed": 9
    }

    first = materialize_design(**arguments)
    second = materialize_design(**arguments)

    assert first == second
    assert {
        (condition.id, condition.repetition)
        for condition in first
    } == {
        (condition.id, repetition)
        for condition in materialize_design(
            kind="factorial",
            intervention_id="treatment",
            factors=arguments["factors"]
        )
        for repetition in range(2)
    }


def test_factorial_design_rejects_empty_track() -> None:
    with pytest.raises(AssertionError):
        materialize_design(
            kind="factorial",
            intervention_id="treatment",
            factors=[]
        )


def test_pair_key_resolves_task_field() -> None:
    config = OmegaConf.create({"seed": 3, "task": {"id": "task"}})

    pair_key = build_pair_key(config, ["task.id", "seed"])

    assert pair_key == {"task.id": "task", "seed": 3}
