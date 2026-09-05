import struct
import pytest
from typing import Any
from collections.abc import Mapping
from harness.environments.base import BaseEnvironmentAdapter
from harness.environments.driver import DriverBackend
from harness.environments.osworld_server import OSWorldServerDriver, desktop_action
from harness.interventions import CounterfactualRuntime
from harness.schema import Action


class ClientFixture:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.commands: list[list[str]] = []

    def execute(self, command: list[str]) -> dict[str, Any]:
        self.events.append("execute")
        self.commands.append(command)
        return {"returncode": 0, "output": ""}

    def screenshot(self) -> bytes:
        self.events.append("screenshot")
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1920, 1080)


def prepare_fixture(client: ClientFixture, options: Mapping[str, Any]) -> None:
    client.events.append("setup:%s" % (options["nudge"],))


def state_fixture(client: ClientFixture, options: Mapping[str, Any]) -> Mapping[str, Any]:
    client.events.append("state")
    return {"choice": None}


def test_native_nudge_is_applied_before_setup_and_screenshot() -> None:
    driver = OSWorldServerDriver("http://unused", prepare_fixture, state_fixture, max_steps=2)
    client = ClientFixture()
    driver.client = client
    runtime = CounterfactualRuntime(specs=[{
        "id": "nudge", "factor": "nudge", "level": "authority", "scope": "environment",
        "target": "state", "modality": "structured", "hook": "episode_start",
        "function": "integrations.native_desktop.set_nudge", "arguments": {"nudge": "authority"}
    }])
    environment = BaseEnvironmentAdapter(DriverBackend(driver, action_kinds=["DONE"]), runtime=runtime)
    observation, snapshot = environment.reset(options={"nudge": "none"})
    assert client.events == ["setup:authority", "state", "screenshot"]
    assert observation.text == "" and observation.structured == {}
    assert snapshot.state == {"choice": None}
    transition = environment.step(Action(kind="DONE"))
    assert transition.terminated and not transition.truncated
    assert transition.interventions[0].changed_fields == ["nudge"]
    before_close = list(client.events)
    environment.close()
    assert client.events == before_close


def test_action_budget_and_quoted_typing() -> None:
    driver = OSWorldServerDriver("http://unused", prepare_fixture, state_fixture, max_steps=1)
    driver.client = ClientFixture()
    driver.reset(0, {"nudge": "none"})
    frame = driver.step(Action(kind="TYPING", text="Draft \"B\".txt"))
    assert frame.truncated and not frame.terminated
    assert "Draft \\\"B\\\".txt" in driver.client.commands[0][2]
    assert desktop_action(Action(kind="HOTKEY", arguments={"keys": "ctrl+c"})) == "pyautogui.hotkey(\"ctrl\", \"c\")"
    with pytest.raises(AssertionError, match="Unsupported action"):
        desktop_action(Action(kind="execute_shell"))
