from typing import Any
from collections.abc import Mapping, Sequence
from harness.interventions import InterventionContext, InterventionResult, is_visual_path
from harness.transforms.specification import edit_by_specification


def language_edit(
    value: Any,
    context: InterventionContext,
    operations: Sequence[Mapping[str, Any]]
) -> InterventionResult:
    for operation in operations:
        assert not is_visual_path(operation["path"])
    return edit_by_specification(value, context, operations)
