from copy import deepcopy
from typing import Any
from collections.abc import Mapping, Sequence
from pydantic import BaseModel
from harness.interventions import InterventionContext, InterventionResult


def edit_by_specification(
    value: Any,
    context: InterventionContext,
    operations: Sequence[Mapping[str, Any]]
) -> InterventionResult:
    del context
    model_type = type(value) if isinstance(value, BaseModel) else None
    edited = deepcopy(
        value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    )
    changed_fields = []
    for operation in operations:
        path = operation["path"]
        edited = apply_operation(edited, operation)
        changed_fields.append(path)
    if model_type is not None:
        edited = model_type.model_validate(edited)
    return InterventionResult(
        value=edited,
        changed_fields=changed_fields,
        metadata={"operation_count": len(operations)}
    )


def apply_operation(value: Any, operation: Mapping[str, Any]) -> Any:
    path = operation["path"]
    if path == "":
        return edit_value(value, operation)
    parent, key = resolve_parent(value, path)
    if operation["op"] == "delete":
        if isinstance(parent, list):
            del parent[int(key)]
        else:
            del parent[key]
        return value
    if operation["op"] == "set":
        if isinstance(parent, list):
            parent[int(key)] = deepcopy(operation["value"])
        else:
            parent[key] = deepcopy(operation["value"])
        return value
    current = parent[int(key)] if isinstance(parent, list) else parent[key]
    edited = edit_value(current, operation)
    if isinstance(parent, list):
        parent[int(key)] = edited
    else:
        parent[key] = edited
    return value


def resolve_parent(value: Any, path: str) -> tuple[Any, str]:
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current, parts[-1]


def edit_value(value: Any, operation: Mapping[str, Any]) -> Any:
    name = operation["op"]
    if name == "set":
        return deepcopy(operation["value"])
    if name == "replace":
        return value.replace(operation["old"], operation["new"])
    if name == "append":
        return value + operation["value"]
    raise ValueError("Unknown edit operation %s" % (name,))
