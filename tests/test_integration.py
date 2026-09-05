import json
import base64
import io
import pytest
from pathlib import Path
from typing import Any
from collections.abc import Mapping
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from dotenv import dotenv_values
from harness.environments.base import BaseEnvironmentAdapter, EnvironmentCapabilityError
from harness.environments.driver import DriverBackend, Frame, HTTPDriver
from harness.integration import check_environment, scaffold_integration
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionResult
from harness.schema import Action, Observation


class CounterDriver:
    def __init__(self) -> None:
        self.count = 0
        self.closed = False

    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        self.count = options["count"]
        return Frame(text=str(self.count), state={"count": self.count})

    def step(self, action: Action) -> Frame:
        self.count += action.arguments["increment"]
        return Frame(text=str(self.count), state={"count": self.count}, reward=2.0)

    def checkpoint(self) -> int:
        return self.count

    def restore(self, checkpoint: int) -> Frame:
        self.count = checkpoint
        return Frame(text=str(self.count), state={"count": self.count})

    def close(self) -> None:
        self.closed = True


def add_notice(value: Observation, context: InterventionContext) -> InterventionResult:
    del context
    return InterventionResult(value=value.model_copy(update={"text": value.text + " notice"}), changed_fields=["text"])


def test_driver_records_delivered_observations_without_mutating_canonical_state() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            {
                "id": "notice",
                "factor": "notice",
                "level": "on",
                "scope": "environment",
                "target": "observation",
                "modality": "language",
                "hook": "observation",
                "function": "add_notice"
            }
        ],
        registry={"add_notice": add_notice}
    )
    environment = BaseEnvironmentAdapter(
        DriverBackend(CounterDriver(), capabilities=["snapshot_restore"], action_kinds=["increment"]),
        runtime=runtime
    )
    observation, snapshot = environment.reset(seed=3, options={"count": 2})
    assert observation.text == "2 notice"
    transition = environment.step(Action(kind="increment", arguments={"increment": 3}))
    assert snapshot.state == {"count": 2}
    assert transition.before_snapshot.state == {"count": 2}
    assert transition.after_snapshot.state == {"count": 5}
    assert transition.observation.text == "2 notice"
    assert transition.next_observation.text == "5 notice"
    assert transition.reward == 2.0
    assert len(transition.interventions) == 2
    assert environment.restore(snapshot).text == "2 notice"


def test_check_closes_driver_and_checks_real_restore() -> None:
    driver = CounterDriver()
    report = check_environment(
        environment=BaseEnvironmentAdapter(DriverBackend(driver, capabilities=["snapshot_restore"], action_kinds=["increment"])),
        options={"count": 0},
        actions=[Action(kind="increment", arguments={"increment": 1})]
    )
    assert report["snapshot_restore_checked"]
    assert driver.closed
    assert driver.count == 0


def test_check_closes_on_error_and_rejects_fake_restore() -> None:
    driver = CounterDriver()
    environment = BaseEnvironmentAdapter(DriverBackend(driver))
    with pytest.raises(EnvironmentCapabilityError):
        check_environment(environment, {}, [], required=["snapshot_restore"])
    assert driver.closed
    _, snapshot = environment.reset(options={"count": 1})
    with pytest.raises(EnvironmentCapabilityError):
        environment.restore(snapshot)


def test_http_driver_requests_and_session_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    png = b"\x89PNG\r\n\x1a\n"

    def request(request: Any, timeout: float) -> io.BytesIO:
        calls.append((request.full_url, json.loads(request.data)))
        frame = {"text": "desktop", "screenshot_base64": base64.b64encode(png).decode("ascii"), "state": {"cursor": [2, 3]}}
        return io.BytesIO(json.dumps({"session_id": "isolated", "frame": frame}).encode("utf-8"))

    monkeypatch.setattr("harness.environments.driver.urlopen", request)
    driver = HTTPDriver("http://test/service")
    assert driver.reset(3, {"vm": "snapshot-1"}).screenshot == png
    assert driver.step(Action(kind="click", arguments={"x": 2, "y": 3})).state == {"cursor": [2, 3]}
    driver.close()
    driver.close()
    assert len(calls) == 3
    assert calls[0] == ("http://test/service/reset", {"seed": 3, "options": {"vm": "snapshot-1"}})
    assert calls[1][1]["session_id"] == "isolated"
    assert calls[1][1]["action"]["arguments"] == {"x": 2, "y": 3}
    assert calls[2] == ("http://test/service/close", {"session_id": "isolated"})


@pytest.mark.parametrize("kind", ["browser", "computer", "custom"])
def test_scaffold_composes_without_overwriting(tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config_root = Path(__file__).resolve().parents[1] / "conf"
    files = scaffold_integration("new_env", kind, tmp_path, "https://example.com", "http://localhost:8000")
    assert len(files) == (2 if kind == "custom" else 1)
    assert not (tmp_path / "integrations" / "new_env.md").exists()
    with initialize_config_dir(version_base="1.3", config_dir=str(config_root)):
        config = compose(
            config_name="config",
            overrides=["hydra.searchpath=[file://%s]" % (tmp_path / "conf",), "task=new_env"]
        )
    if kind != "custom":
        for key, value in dotenv_values(tmp_path / ".env").items():
            monkeypatch.setenv(key, value)
        assert all("https://example.com" not in path.read_text() and "http://localhost:8000" not in path.read_text() for path in files)
    OmegaConf.to_container(config.task, resolve=True)
    assert config.environment.id == "new_env"
    assert config.agent.id == "scripted"
    assert "contract_actions" not in config.task
    with pytest.raises(AssertionError, match="overwrites"):
        scaffold_integration("new_env", kind, tmp_path, "https://example.com", "http://localhost:8000")
