import struct
import pytest
from pathlib import Path
from typing import Any
from collections.abc import Mapping
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from harness.agents import AgentSpec, edit_agent_spec
from harness.environments.driver import DriverBackend
from harness.environments.osworld import OSWorldDriver
from harness.interventions import CounterfactualRuntime
from harness.schema import Action


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1920, 1080)


class DesktopFixture:
    action_space = "computer_13"

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.evaluations = 0
        self.closed = False
        self.task_config: dict[str, Any] = {}
        self.seed: int | None = None

    def reset(self, task_config: dict[str, Any], seed: int | None) -> dict[str, Any]:
        self.task_config = task_config
        self.seed = seed
        return {"screenshot": PNG, "accessibility_tree": "private tree", "terminal": "private terminal"}

    def step(self, action: dict[str, Any], pause: float) -> tuple[dict[str, Any], int, bool, dict[str, Any]]:
        self.actions.append(action)
        return {"screenshot": PNG}, 0, action["action_type"] in {"DONE", "FAIL"}, {}

    def evaluate(self) -> float:
        self.evaluations += 1
        return 1.0

    def close(self) -> None:
        self.closed = True


def test_osworld_actions_screenshots_and_budget_evaluation() -> None:
    driver = OSWorldDriver(DesktopFixture, max_steps=2, pause=0)
    backend = DriverBackend(driver, action_kinds=["TYPING", "HOTKEY"])
    observation, _ = backend.reset(seed=7, options={"task_config": {"id": "rename"}})
    desktop = driver.environment
    assert desktop.seed == 7
    assert desktop.task_config == {"id": "rename"}
    assert observation.text == "" and observation.structured == {}
    assert (observation.visual.width, observation.visual.height) == (1920, 1080)
    first = backend.step(Action(kind="HOTKEY", arguments={"keys": "ctrl+a"}))
    assert not first.terminated and not first.truncated
    assert desktop.evaluations == 0
    final = backend.step(Action(kind="TYPING", text="todo_list_Jan_2"))
    assert final.truncated and not final.terminated
    assert desktop.actions == [
        {"action_type": "HOTKEY", "parameters": {"keys": ["ctrl", "a"]}},
        {"action_type": "TYPING", "parameters": {"text": "todo_list_Jan_2"}}
    ]
    assert backend.inspect()["outcomes"]["osworld_score"] == 1.0
    assert desktop.evaluations == 1
    backend.close()
    backend.close()
    assert desktop.closed


def test_osworld_done_scores_and_reset_replaces_session() -> None:
    driver = OSWorldDriver(DesktopFixture, max_steps=5, pause=0)
    driver.reset(1, {"task_config": {"id": "rename"}})
    desktop = driver.environment
    frame = driver.step(Action(kind="DONE"))
    assert frame.terminated and not frame.truncated
    assert desktop.evaluations == 1
    driver.reset(1, {"task_config": {"id": "rename"}})
    assert desktop.closed and driver.environment is not desktop
    assert driver.score is None and driver.steps == 0
    driver.close()


def incorrect_state(environment: Any) -> Mapping[str, bool]:
    return {"old_exists": False, "new_exists": True}


def test_osworld_refuses_stale_task_state() -> None:
    driver = OSWorldDriver(DesktopFixture, max_steps=2, state_reader=incorrect_state)
    with pytest.raises(AssertionError, match="did not reset"):
        driver.reset(
            0,
            {"task_config": {"id": "rename"}, "expected_state": {"old_exists": True, "new_exists": False}}
        )
    driver.close()


def test_rename_pair_composes_and_hint_preserves_model_and_actions() -> None:
    root = Path(__file__).resolve().parents[1]
    with initialize_config_dir(config_dir=str(root / "conf"), version_base=None):
        config = compose(config_name="config", overrides=["task=osworld/osworld_rename_pair"])
    assert config.environment.adapter.backend.driver.max_steps == config.max_steps
    assert config.agent.spec.config.modality == "screenshot"
    task = OmegaConf.to_container(config.task.fixture.task_config, resolve=True)
    assert task["id"] == "e0df059f-28a6-4169-924f-b9623e7184cc"
    assert task["evaluator"]["func"] == "exact_match"
    spec = AgentSpec.model_validate(OmegaConf.to_container(config.agent.spec, resolve=True))
    runtime = CounterfactualRuntime(specs=OmegaConf.to_container(config.task.intervention.specs, resolve=True))
    edited, applications = edit_agent_spec(spec, runtime, "episode", config.task.id, 0, {})
    assert edited.instructions.startswith(task["instruction"])
    assert "press F2" in edited.instructions
    assert edited.config == spec.config and edited.tools == spec.tools
    assert len(applications) == 1
