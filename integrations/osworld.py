import json
from typing import Any
from collections.abc import Mapping, Sequence
from harness.schema import Transition


def rename_state(environment: Any) -> Mapping[str, bool]:
    result = environment.controller.execute_python_command(
        "import json; from pathlib import Path; "
        "desktop = Path.home() / \"Desktop\"; "
        "print(json.dumps({\"old_exists\": (desktop / \"todo_list_Jan_1\").is_dir(), "
        "\"new_exists\": (desktop / \"todo_list_Jan_2\").is_dir()}))"
    )
    assert result["returncode"] == 0, result["error"]
    return json.loads(result["output"])


def rename_completed(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> bool:
    return state["task"]["new_exists"] and not state["task"]["old_exists"]


def used_f2(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> bool:
    return any(
        step.action.kind == "PRESS" and step.action.arguments["key"].lower() == "f2"
        for step in trajectory
    )
