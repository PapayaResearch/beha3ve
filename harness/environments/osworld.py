import struct
from typing import Any
from collections.abc import Callable, Mapping
from harness.environments.driver import Frame
from harness.schema import Action
from harness.serialization import content_hash


class OSWorldDriver:
    def __init__(
        self,
        environment_factory: Callable[..., Any],
        max_steps: int,
        pause: float = 2.0,
        state_reader: Callable[[Any], Mapping[str, Any]] | None = None
    ) -> None:
        self.environment_factory = environment_factory
        self.max_steps = max_steps
        self.pause = pause
        self.state_reader = state_reader
        self.environment: Any = None
        self.steps = 0
        self.task_hash = ""
        self.score: float | None = None

    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        self.close()
        task_config = dict(options["task_config"])
        self.task_hash = content_hash(task_config)
        self.steps = 0
        self.score = None
        self.environment = self.environment_factory()
        assert self.environment.action_space == "computer_13"
        observation = self.environment.reset(task_config=task_config, seed=seed)
        frame = self._frame(observation)
        if "expected_state" in options:
            assert frame.state["task"] == options["expected_state"], "OSWorld task did not reset to the expected state"
        return frame

    def step(self, action: Action) -> Frame:
        parameters = dict(action.arguments)
        if action.kind == "TYPING":
            parameters["text"] = action.text
        if action.kind == "HOTKEY":
            parameters["keys"] = parameters["keys"].split("+")
        observation, reward, done, info = self.environment.step(
            {"action_type": action.kind, "parameters": parameters},
            pause=self.pause
        )
        self.steps += 1
        truncated = self.steps >= self.max_steps and not done
        frame = self._frame(
            observation,
            terminated=done,
            truncated=truncated,
            reward=reward,
            info=info
        )
        # Preserve the final screen and task state before evaluator post-setup actions.
        if done or truncated:
            self.score = float(self.environment.evaluate())
            frame.state["outcomes"]["osworld_score"] = self.score
        return frame

    def close(self) -> None:
        if self.environment is not None:
            self.environment.close()
            self.environment = None

    def _frame(
        self,
        observation: Mapping[str, Any],
        terminated: bool = False,
        truncated: bool = False,
        reward: float | None = None,
        info: Mapping[str, Any] | None = None
    ) -> Frame:
        screenshot = observation["screenshot"]
        assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", screenshot[16:24])
        task_state = dict(self.state_reader(self.environment)) if self.state_reader is not None else {}
        return Frame(
            screenshot=screenshot,
            width=width,
            height=height,
            state={
                "task_config_hash": self.task_hash,
                "task": task_state,
                "outcomes": {"osworld_score": self.score}
            },
            terminated=terminated,
            truncated=truncated,
            reward=reward,
            info=dict(info or {})
        )
