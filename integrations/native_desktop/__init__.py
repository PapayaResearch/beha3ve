import json
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from harness.environments.osworld_server import OSWorldClient
from harness.interventions import InterventionContext, InterventionResult
from harness.schema import Transition


def prepare(client: OSWorldClient, options: Mapping[str, Any]) -> None:
    script = Path(__file__).with_name("setup.py").read_text()
    client.execute(["python", "-c", script, "--config", json.dumps(dict(options))])
    state = read_state(client, options)
    assert state["choice"] is None and not state["valid"]
    assert len(state["files"]) == (2 if options["task_kind"] == "report" else 1)


def read_state(client: OSWorldClient, options: Mapping[str, Any]) -> Mapping[str, Any]:
    script = Path(__file__).with_name("state.py").read_text()
    result = client.execute(["python", "-c", script, "--config", json.dumps(dict(options))])
    return json.loads(result["output"])


def set_nudge(value: Mapping[str, Any], context: InterventionContext, nudge: str) -> InterventionResult:
    return InterventionResult(value={**value, "nudge": nudge}, changed_fields=["nudge"])


def success(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> bool:
    return state["valid"]


def target_selected(trajectory: Sequence[Transition], state: Mapping[str, Any]) -> bool | None:
    return None if state["choice"] is None else state["choice"] == "B"
