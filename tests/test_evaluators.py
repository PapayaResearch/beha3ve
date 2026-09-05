import pytest
from harness.evaluators import EvaluationResult, Outcome, factorial_main_effects


def test_factorial_main_effects_aggregate_binary_levels() -> None:
    evaluations = [
        (
            {"pressure": "low"},
            EvaluationResult(
                outcomes=[Outcome(id="success", value=0.2, direction="maximize")]
            )
        ),
        (
            {"pressure": "high"},
            EvaluationResult(
                outcomes=[Outcome(id="success", value=0.8, direction="maximize")]
            )
        )
    ]

    contrasts = factorial_main_effects(
        evaluations=evaluations,
        factors=[{"id": "pressure", "levels": ["low", "high"]}]
    )

    assert len(contrasts) == 1
    assert contrasts[0].factor == "pressure"
    assert contrasts[0].difference == pytest.approx(0.6)
