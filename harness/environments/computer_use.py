from copy import deepcopy
from typing import Any, Protocol, runtime_checkable
from collections.abc import Mapping
from harness.interventions import CounterfactualRuntime
from harness.environments.base import (
    BackendHook,
    BackendHookPoint,
    BackendHookRegistry,
    BaseEnvironmentAdapter,
    EnvironmentCapability,
    RendererNeutralBackend
)
from harness.schema import Action, Event, Observation, Snapshot, Transition, VisualObservation


@runtime_checkable
class ComputerUseBackendProtocol(RendererNeutralBackend, Protocol):
    def register_text_editor(self, hook: BackendHook) -> None:
        ...

    def register_screenshot_editor(self, hook: BackendHook) -> None:
        ...

    def register_observation_editor(self, hook: BackendHook) -> None:
        ...


class MemoryComputerUseBackend:
    capabilities = frozenset(
        {
            EnvironmentCapability.STRUCTURED_OBSERVATION,
            EnvironmentCapability.TEXT_OBSERVATION,
            EnvironmentCapability.VISUAL_OBSERVATION,
            EnvironmentCapability.OBSERVATION_INTERCEPTION,
            EnvironmentCapability.SCREENSHOT_INTERCEPTION,
            EnvironmentCapability.STATE_INSPECTION,
            EnvironmentCapability.SNAPSHOT_RESTORE,
            EnvironmentCapability.COMPUTER_ACTION,
            EnvironmentCapability.POINTER_ACTION,
            EnvironmentCapability.KEYBOARD_ACTION
        }
    )

    def __init__(
        self,
        initial_text: str = "",
        initial_screenshot: bytes = b"",
        viewport: Mapping[str, int] | None = None
    ) -> None:
        self._initial_state = {
            "text": initial_text,
            "screenshot": initial_screenshot,
            "cursor": {"x": 0, "y": 0},
            "windows": [],
            "last_action": None,
            "last_tool_result": None,
            "terminated": False,
            "truncated": False
        }
        self._viewport = dict(viewport or {"width": 1280, "height": 720})
        self._step = 0
        self._state = deepcopy(self._initial_state)
        self._observation: Observation | None = None
        self._hooks = BackendHookRegistry()

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        reset_options = dict(options or {})
        fixture = reset_options.get("state", self._initial_state)
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.RESET,
            value=deepcopy(fixture),
            step=0,
            metadata={"seed": seed}
        )
        self._step = 0
        self._observation = self._make_observation()
        return self._observation, self.snapshot()

    def step(self, action: Action) -> Transition:
        action_step = self._step
        before_snapshot = self.snapshot()
        if action.kind == "set_text":
            self._state["text"] = action.text or action.arguments.get("text", "")
        elif action.kind == "set_screenshot":
            self._state["screenshot"] = action.arguments["data"]
        elif action.kind == "move_pointer":
            self._state["cursor"] = {
                "x": action.arguments["x"],
                "y": action.arguments["y"]
            }
        elif action.kind == "open_window":
            self._state["windows"].append(action.arguments["window"])
        elif action.kind == "close_window":
            self._state["windows"].remove(action.arguments["window"])
        elif action.kind == "tool":
            self._state["last_tool_result"] = self._hooks.apply_hooks(
                point=BackendHookPoint.TOOL_RESULT,
                value=action.arguments["result"],
                step=action_step,
                metadata={"tool": action.arguments.get("tool", "")}
            )
        elif action.kind == "finish":
            self._state["terminated"] = True
        self._state["last_action"] = action.model_dump(mode="python")
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.STATE,
            value=self._state,
            step=action_step,
            metadata={"action_kind": action.kind}
        )
        self._step += 1
        self._observation = self._make_observation()
        event = Event(
            sequence=action_step,
            step=action_step,
            kind=action.kind,
            actor_id="agent",
            payload=action.model_dump(mode="python")
        )
        self._observation = self._observation.model_copy(update={"events": [event]})
        after_snapshot = self.snapshot()
        return Transition(
            step=action_step,
            observation=before_snapshot.observation,
            action=action,
            next_observation=self._observation,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            reward=None,
            terminated=self._state["terminated"],
            truncated=self._state["truncated"],
            info={"backend": "computer_use"},
            interventions=[]
        )

    def inspect(self) -> Mapping[str, Any]:
        return deepcopy(self._state)

    def snapshot(self) -> Snapshot:
        return Snapshot(
            step=self._step,
            state=deepcopy(self._state),
            observation=deepcopy(self._observation),
            metadata={"backend": "computer_use", "viewport": deepcopy(self._viewport)}
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        self._step = snapshot.step
        self._state = deepcopy(snapshot.state)
        self._viewport = deepcopy(snapshot.metadata.get("viewport", self._viewport))
        self._observation = deepcopy(snapshot.observation)
        return self._observation

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks.register_hook(point, hook)

    def register_text_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.TEXT_OBSERVATION, hook)

    def register_screenshot_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.SCREENSHOT_OBSERVATION, hook)

    def register_observation_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.OBSERVATION, hook)

    def close(self) -> None:
        return None

    def _make_observation(self) -> Observation:
        text = self._hooks.apply_hooks(
            point=BackendHookPoint.TEXT_OBSERVATION,
            value=self._state["text"],
            step=self._step,
            metadata={}
        )
        visual = VisualObservation(
            data=self._state["screenshot"],
            media_type="image/png",
            width=self._viewport["width"],
            height=self._viewport["height"],
            metadata={}
        )
        visual = self._hooks.apply_hooks(
            point=BackendHookPoint.SCREENSHOT_OBSERVATION,
            value=visual,
            step=self._step,
            metadata={}
        )
        observation = Observation(
            step=self._step,
            text=text,
            structured={
                "cursor": deepcopy(self._state["cursor"]),
                "windows": deepcopy(self._state["windows"]),
                "tool_result": deepcopy(self._state["last_tool_result"])
            },
            visual=visual,
            events=[],
            metadata={"backend": "computer_use"}
        )
        return self._hooks.apply_hooks(
            point=BackendHookPoint.OBSERVATION,
            value=observation,
            step=self._step,
            metadata={}
        )


class ComputerUseEnvironment(BaseEnvironmentAdapter):
    def __init__(
        self,
        backend: ComputerUseBackendProtocol | None = None,
        runtime: CounterfactualRuntime | None = None,
        episode_id: str = "",
        task_id: str = "",
        agent: str = "agent",
        condition: Mapping[str, Any] | None = None
    ) -> None:
        computer_use_backend = backend or MemoryComputerUseBackend()
        super().__init__(
            backend=computer_use_backend,
            runtime=runtime,
            environment="computer_use",
            episode_id=episode_id,
            task_id=task_id,
            agent=agent,
            condition=condition
        )
