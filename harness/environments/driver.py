import json
import base64
from copy import deepcopy
from typing import Any, Protocol
from collections.abc import Mapping, Sequence
from urllib.request import Request, urlopen
from pydantic import BaseModel, Field
from harness.environments.base import BackendHook, BackendHookPoint, BackendHookRegistry, EnvironmentCapability, require_capabilities
from harness.schema import Action, Observation, Snapshot, Transition, VisualObservation


class Frame(BaseModel):
    text: str = ""
    structured: dict[str, Any] = Field(default_factory=dict)
    screenshot: bytes | None = None
    width: int | None = None
    height: int | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    reward: float | None = None
    terminated: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)


class EnvironmentDriver(Protocol):
    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        ...

    def step(self, action: Action) -> Frame:
        ...

    def close(self) -> None:
        ...


class DriverBackend:
    """Adapt a three-method driver into the harness lifecycle and observation hooks."""

    def __init__(
        self,
        driver: EnvironmentDriver,
        capabilities: Sequence[str] = ("text_observation", "state_inspection"),
        action_kinds: Sequence[str] = ("finish",)
    ) -> None:
        self.driver = driver
        self.capabilities = frozenset(EnvironmentCapability(value) for value in capabilities) | {
            EnvironmentCapability.OBSERVATION_INTERCEPTION
        }
        unsupported = self.capabilities & {
            EnvironmentCapability.RESPONSE_INTERCEPTION,
            EnvironmentCapability.NAVIGATION_RESPONSE,
            EnvironmentCapability.MESSAGE_INTERCEPTION
        }
        assert not unsupported, "Use a native backend for transport-level hooks: %s" % (unsupported,)
        self.action_kinds = frozenset(action_kinds)
        self._hooks = BackendHookRegistry()
        self._step = 0
        self._frame: Frame | None = None
        self._observation: Observation | None = None

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        self._step = 0
        reset_options = self._hooks.apply_hooks(
            point=BackendHookPoint.RESET,
            value=deepcopy(dict(options or {})),
            step=0,
            metadata={"seed": seed}
        )
        self._accept_frame(self.driver.reset(seed, reset_options))
        return self._observation, self.snapshot()

    def step(self, action: Action) -> Transition:
        assert action.kind in self.action_kinds, "Unsupported action: %s" % (action.kind,)
        assert self._frame is not None and not (self._frame.terminated or self._frame.truncated)
        before = self.snapshot()
        frame = self.driver.step(action)
        self._step += 1
        self._accept_frame(frame)
        return Transition(
            step=before.step,
            observation=before.observation,
            action=action,
            next_observation=self._observation,
            before_snapshot=before,
            after_snapshot=self.snapshot(),
            reward=self._frame.reward,
            terminated=self._frame.terminated,
            truncated=self._frame.truncated,
            info=deepcopy(self._frame.info)
        )

    def inspect(self) -> Mapping[str, Any]:
        assert self._frame is not None
        return deepcopy(self._frame.state)

    def snapshot(self) -> Snapshot:
        metadata: dict[str, Any] = {"backend": "driver", "restorable": False}
        if EnvironmentCapability.SNAPSHOT_RESTORE in self.capabilities:
            metadata.update(checkpoint=self.driver.checkpoint(), restorable=True)
        return Snapshot(
            step=self._step,
            state=dict(self.inspect()),
            observation=deepcopy(self._observation),
            metadata=metadata
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        require_capabilities(self.capabilities, [EnvironmentCapability.SNAPSHOT_RESTORE])
        self._step = snapshot.step
        self._accept_frame(self.driver.restore(snapshot.metadata["checkpoint"]), apply_hooks=False)
        return self._observation

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks.register_hook(point, hook)

    def close(self) -> None:
        self.driver.close()

    def _accept_frame(self, frame: Frame, apply_hooks: bool = True) -> None:
        self._frame = Frame.model_validate(frame).model_copy(deep=True)
        visual = None
        if frame.screenshot is not None:
            assert frame.screenshot.startswith(b"\x89PNG\r\n\x1a\n"), "Frame.screenshot must contain PNG bytes"
            visual = VisualObservation(data=frame.screenshot, width=frame.width, height=frame.height)
        observation = Observation(
            step=self._step,
            text=frame.text,
            structured=deepcopy(frame.structured),
            visual=visual,
            metadata={"backend": "driver"}
        )
        self._observation = self._hooks.apply_hooks(
            point=BackendHookPoint.OBSERVATION,
            value=observation,
            step=self._step,
            metadata=frame.info
        ) if apply_hooks else observation


class HTTPDriver:
    """JSON bridge to an author-owned web, VM, or desktop service."""

    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.session_id: str | None = None

    def reset(self, seed: int | None, options: Mapping[str, Any]) -> Frame:
        self.close()
        result = self._request("reset", {"seed": seed, "options": dict(options)})
        self.session_id = result["session_id"]
        return self._frame(result["frame"])

    def step(self, action: Action) -> Frame:
        result = self._request("step", {"session_id": self.session_id, "action": action.model_dump(mode="json")})
        return self._frame(result["frame"])

    def checkpoint(self) -> Any:
        return self._request("checkpoint", {"session_id": self.session_id})["checkpoint"]

    def restore(self, checkpoint: Any) -> Frame:
        result = self._request("restore", {"session_id": self.session_id, "checkpoint": checkpoint})
        return self._frame(result["frame"])

    def close(self) -> None:
        if self.session_id is not None:
            self._request("close", {"session_id": self.session_id})
            self.session_id = None

    def _request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = Request(
            "%s/%s" % (self.endpoint, operation),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def _frame(self, value: Mapping[str, Any]) -> Frame:
        fields = dict(value)
        encoded = fields.pop("screenshot_base64", None)
        if encoded is not None:
            fields["screenshot"] = base64.b64decode(encoded, validate=True)
        return Frame.model_validate(fields)
