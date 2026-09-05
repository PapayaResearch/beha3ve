import base64
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from pydantic import BaseModel


def canonicalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii")
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [canonicalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    before_value = before.model_dump(mode="python") if isinstance(before, BaseModel) else before
    after_value = after.model_dump(mode="python") if isinstance(after, BaseModel) else after
    if isinstance(before_value, Mapping) and isinstance(after_value, Mapping):
        paths = []
        keys = set(before_value) | set(after_value)
        for key in sorted(keys, key=str):
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            if key not in before_value or key not in after_value:
                paths.append(path)
            else:
                paths.extend(
                    changed_paths(
                        before=before_value[key],
                        after=after_value[key],
                        prefix=path
                    )
                )
        return paths
    if (
        isinstance(before_value, Sequence)
        and isinstance(after_value, Sequence)
        and not isinstance(before_value, str | bytes)
        and not isinstance(after_value, str | bytes)
    ):
        if len(before_value) != len(after_value):
            return [prefix]
        paths = []
        for index, (before_item, after_item) in enumerate(
            zip(before_value, after_value, strict=True)
        ):
            path = "%s.%s" % (prefix, index) if prefix else str(index)
            paths.extend(
                changed_paths(
                    before=before_item,
                    after=after_item,
                    prefix=path
                )
            )
        return paths
    if before_value != after_value:
        return [prefix]
    return []


def project_fields(value: Any, fields: Sequence[str]) -> dict[str, Any]:
    canonical = canonicalize(value)
    return {field: get_path(canonical, field) for field in fields}


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current
