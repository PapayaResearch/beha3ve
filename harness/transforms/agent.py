from typing import Any
from collections.abc import Mapping, Sequence
from harness.interventions import InterventionContext, InterventionResult
from harness.transforms.specification import edit_by_specification


ALLOWED_AGENT_PATHS = (
    "instructions",
    "system_prompt",
    "memory_policy",
    "scaffold",
    "config",
    "tools"
)


def agent_edit(
    value: Any,
    context: InterventionContext,
    operations: Sequence[Mapping[str, Any]],
    allowed_paths: Sequence[str] = ALLOWED_AGENT_PATHS
) -> InterventionResult:
    for operation in operations:
        root = operation["path"].split(".", maxsplit=1)[0]
        assert root in allowed_paths
    return edit_by_specification(value, context, operations)
