from typing import Any
from collections.abc import Mapping, Sequence
from harness.agents import AgentSpec
from harness.schema import Action, Observation


class ScriptedAgent:
    def __init__(
        self,
        spec: AgentSpec | None = None,
        actions: Sequence[Action | Mapping[str, Any]] = (),
        default_action: Action | Mapping[str, Any] | None = None
    ) -> None:
        self.spec = spec
        self.actions = [
            action if isinstance(action, Action) else Action.model_validate(action)
            for action in actions
        ]
        self.default_action = (
            default_action
            if isinstance(default_action, Action)
            else Action.model_validate(default_action or {"kind": "finish"})
        )
        self.index = 0

    def reset(self, seed: int | None = None) -> None:
        del seed
        self.index = 0

    def act(self, observation: Observation) -> Action:
        del observation
        if self.index >= len(self.actions):
            return self.default_action
        action = self.actions[self.index]
        self.index += 1
        return action
