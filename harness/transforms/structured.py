from typing import Any
from collections.abc import Mapping, Sequence
from harness.interventions import InterventionContext, InterventionResult
from harness.transforms.specification import edit_by_specification


def structured_edit(
    value: Any,
    context: InterventionContext,
    operations: Sequence[Mapping[str, Any]]
) -> InterventionResult:
    return edit_by_specification(value, context, operations)
