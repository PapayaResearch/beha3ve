from typing import Any
from collections.abc import Mapping, Sequence
from harness.interventions import InterventionContext, InterventionResult
from harness.schema import Observation, VisualObservation
from harness.transforms.specification import edit_by_specification


def visual_edit(
    value: Any,
    context: InterventionContext,
    operations: Sequence[Mapping[str, Any]],
    preserve_geometry: bool = True
) -> InterventionResult:
    for operation in operations:
        assert is_visual_operation(operation["path"])
    before = get_visual(value)
    result = edit_by_specification(value, context, operations)
    after = get_visual(result.value)
    assert after.media_type.startswith("image/")
    assert isinstance(after.data, bytes)
    if preserve_geometry:
        assert before.width == after.width
        assert before.height == after.height
    return result


def get_visual(value: Any) -> VisualObservation:
    if isinstance(value, Observation):
        assert value.visual is not None
        return value.visual
    assert isinstance(value, VisualObservation)
    return value


def is_visual_operation(path: str) -> bool:
    return path in (
        "data",
        "media_type",
        "metadata"
    ) or path.startswith("metadata.") or path in (
        "visual.data",
        "visual.media_type",
        "visual.metadata"
    ) or path.startswith("visual.metadata.")
