from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from collections.abc import Mapping, Sequence
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionHook
from harness.schema import Action, InterventionApplication, Observation, Snapshot, Transition


class EnvironmentCapability(StrEnum):
    STRUCTURED_OBSERVATION = "structured_observation"
    TEXT_OBSERVATION = "text_observation"
    VISUAL_OBSERVATION = "visual_observation"
    ACTOR_SPECIFIC_OBSERVATION = "actor_specific_observation"
    RESPONSE_INTERCEPTION = "response_interception"
    OBSERVATION_INTERCEPTION = "observation_interception"
    SCREENSHOT_INTERCEPTION = "screenshot_interception"
    MESSAGE_INTERCEPTION = "message_interception"
    STATE_INSPECTION = "state_inspection"
    SNAPSHOT_RESTORE = "snapshot_restore"
    BROWSER_ACTION = "browser_action"
    NAVIGATION_RESPONSE = "navigation_response"
    COMPUTER_ACTION = "computer_action"
    HTML_OBSERVATION = "html_observation"
    ACCESSIBILITY_OBSERVATION = "accessibility_observation"
    GEOMETRY_OBSERVATION = "geometry_observation"
    POINTER_ACTION = "pointer_action"
    KEYBOARD_ACTION = "keyboard_action"
    MESSAGES = "messages"
    MULTI_ACTOR = "multi_actor"
    PERSISTENT_STATE = "persistent_state"
    PROVENANCE = "provenance"
    POLICY_ORACLE = "policy_oracle"


class BackendHookPoint(StrEnum):
    RESET = "reset"
    MESSAGE = "message"
    STATE = "state"
    TOOL_RESULT = "tool_result"
    NAVIGATION_RESPONSE = "navigation_response"
    TEXT_OBSERVATION = "text_observation"
    SCREENSHOT_OBSERVATION = "screenshot_observation"
    OBSERVATION = "observation"


@dataclass(frozen=True)
class BackendHookEvent:
    point: BackendHookPoint
    step: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class BackendHook(Protocol):
    def __call__(self, value: Any, event: BackendHookEvent) -> Any:
        ...


@runtime_checkable
class RendererNeutralBackend(Protocol):
    capabilities: frozenset[EnvironmentCapability]

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        ...

    def step(self, action: Action) -> Transition:
        ...

    def inspect(self) -> Mapping[str, Any]:
        ...

    def snapshot(self) -> Snapshot:
        ...

    def restore(self, snapshot: Snapshot) -> Observation:
        ...

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        ...

    def close(self) -> None:
        ...


class EnvironmentCapabilityError(ValueError):
    pass


def missing_capabilities(
    available: Sequence[EnvironmentCapability],
    required: Sequence[EnvironmentCapability]
) -> frozenset[EnvironmentCapability]:
    return frozenset(required) - frozenset(available)


def require_capabilities(
    available: Sequence[EnvironmentCapability],
    required: Sequence[EnvironmentCapability]
) -> None:
    missing = missing_capabilities(available, required)
    if missing:
        names = ", ".join(sorted(capability.value for capability in missing))
        raise EnvironmentCapabilityError("Missing environment capabilities: %s" % (names,))


class BackendHookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[BackendHookPoint, list[BackendHook]] = {
            point: [] for point in BackendHookPoint
        }

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks[point].append(hook)

    def apply_hooks(
        self,
        point: BackendHookPoint,
        value: Any,
        step: int,
        metadata: Mapping[str, Any] | None = None
    ) -> Any:
        event = BackendHookEvent(
            point=point,
            step=step,
            metadata=dict(metadata or {})
        )
        transformed = value
        for hook in self._hooks[point]:
            transformed = hook(transformed, event)
        return transformed


class BaseEnvironmentAdapter:
    def __init__(
        self,
        backend: RendererNeutralBackend,
        runtime: CounterfactualRuntime | None = None,
        environment: str = "base",
        episode_id: str = "",
        task_id: str = "",
        agent: str = "agent",
        condition: Mapping[str, Any] | None = None
    ) -> None:
        self.backend = backend
        self.runtime = runtime or CounterfactualRuntime(specs=())
        self.environment = environment
        self.episode_id = episode_id
        self.task_id = task_id
        self.agent = agent
        self.condition = dict(condition or {})
        self.seed: int | None = None
        self._applications: list[InterventionApplication] = []
        self._pending_applications: list[InterventionApplication] = []
        self._last_observation: Observation | None = None
        self._last_snapshot: Snapshot | None = None
        self._register_runtime_hooks()

    @property
    def capabilities(self) -> frozenset[EnvironmentCapability]:
        return self.backend.capabilities

    def require_capabilities(self, required: Sequence[EnvironmentCapability]) -> None:
        require_capabilities(self.capabilities, required)

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        self._applications = []
        self._pending_applications = []
        self.seed = seed
        observation, snapshot = self.backend.reset(seed=seed, options=options)
        self._last_observation = observation
        self._last_snapshot = snapshot.model_copy(update={"observation": observation})
        self._pending_applications = self._applications
        self._applications = []
        return observation, self._last_snapshot

    def step(self, action: Action) -> Transition:
        step = self._last_snapshot.step if self._last_snapshot is not None else 0
        actor_id = action.metadata.get("actor_id", self.agent)
        previous_agent = self.agent
        self.agent = actor_id
        if action.kind in ("commit", "finish"):
            action = self._apply_runtime(
                hook=InterventionHook.BEFORE_COMMITMENT,
                value=action,
                step=step
            )
        transformed_action = self._apply_runtime(
            hook=InterventionHook.AFTER_AGENT,
            value=action,
            step=step
        )
        transformed_action = self._apply_runtime(
            hook=InterventionHook.ACTION,
            value=transformed_action,
            step=step
        )
        transformed_action = self._apply_runtime(
            hook=InterventionHook.BEFORE_ENVIRONMENT,
            value=transformed_action,
            step=step
        )
        transformed_action = transformed_action.model_copy(
            update={
                "metadata": {
                    **transformed_action.metadata,
                    "actor_id": actor_id
                }
            }
        )
        transition = self.backend.step(transformed_action)
        self._last_observation = transition.next_observation
        before_snapshot = self._last_snapshot or transition.before_snapshot
        after_snapshot = transition.after_snapshot.model_copy(
            update={"observation": transition.next_observation}
        )
        self._last_snapshot = after_snapshot
        transition = transition.model_copy(
            update={
                "observation": before_snapshot.observation,
                "before_snapshot": before_snapshot,
                "after_snapshot": after_snapshot
            }
        )
        applications = [
            *transition.interventions,
            *self._pending_applications,
            *self._applications
        ]
        self._pending_applications = []
        self._applications = []
        self.agent = previous_agent
        return transition.model_copy(update={"interventions": applications})

    def inspect(self) -> Mapping[str, Any]:
        return self.backend.inspect()

    def observe(self, actor_id: str = "agent") -> Observation:
        assert actor_id == self.agent
        observation = self._last_observation
        assert observation is not None
        return observation

    def observe_for_actor(self, actor_id: str) -> Observation:
        previous_agent = self.agent
        self.agent = actor_id
        observation = self.observe(actor_id)
        self.agent = previous_agent
        return observation

    def snapshot(self) -> Snapshot:
        snapshot = self.backend.snapshot()
        if self._last_observation is not None:
            snapshot = snapshot.model_copy(update={"observation": self._last_observation})
        application_count = len(self._applications)
        edited = self._apply_runtime(
            hook=InterventionHook.SNAPSHOT,
            value=snapshot,
            step=snapshot.step
        )
        snapshot = Snapshot.model_validate(edited)
        snapshot_applications = self._applications[application_count:]
        if snapshot_applications:
            snapshot = snapshot.model_copy(
                update={
                    "metadata": {
                        **snapshot.metadata,
                        "interventions": [
                            application.model_dump(mode="json")
                            for application in snapshot_applications
                        ]
                    }
                }
            )
            del self._applications[application_count:]
        self._last_snapshot = snapshot
        return snapshot

    def restore(self, snapshot: Snapshot) -> Observation:
        observation = self.backend.restore(snapshot)
        edited = self._apply_runtime(
            hook=InterventionHook.OBSERVATION,
            value=observation,
            step=observation.step,
            metadata={"restored": True}
        )
        self._last_observation = edited
        self._last_snapshot = snapshot.model_copy(update={"observation": edited})
        return edited

    def close(self) -> None:
        self.backend.close()

    def _register_runtime_hooks(self) -> None:
        points = (
            BackendHookPoint.RESET,
            BackendHookPoint.MESSAGE,
            BackendHookPoint.STATE,
            BackendHookPoint.TOOL_RESULT,
            BackendHookPoint.NAVIGATION_RESPONSE,
            BackendHookPoint.OBSERVATION
        )
        for point in points:
            self.backend.register_hook(point, self._runtime_backend_hook)

    def _runtime_backend_hook(self, value: Any, event: BackendHookEvent) -> Any:
        hook = {
            BackendHookPoint.RESET: InterventionHook.RESET,
            BackendHookPoint.MESSAGE: InterventionHook.MESSAGE,
            BackendHookPoint.STATE: InterventionHook.AFTER_ENVIRONMENT,
            BackendHookPoint.TOOL_RESULT: InterventionHook.TOOL_RESULT,
            BackendHookPoint.NAVIGATION_RESPONSE: InterventionHook.NAVIGATION_RESPONSE,
            BackendHookPoint.OBSERVATION: InterventionHook.OBSERVATION
        }[event.point]
        transformed = self._apply_runtime(
            hook=hook,
            value=value,
            step=event.step,
            metadata=event.metadata
        )
        if event.point == BackendHookPoint.OBSERVATION:
            transformed = self._apply_runtime(
                hook=InterventionHook.BEFORE_TURN,
                value=transformed,
                step=event.step,
                metadata=event.metadata
            )
            transformed = self._apply_runtime(
                hook=InterventionHook.BEFORE_AGENT,
                value=transformed,
                step=event.step,
                metadata=event.metadata
            )
        return transformed

    def _apply_runtime(
        self,
        hook: InterventionHook,
        value: Any,
        step: int,
        metadata: Mapping[str, Any] | None = None
    ) -> Any:
        context = InterventionContext(
            episode_id=self.episode_id,
            step=step,
            environment=self.environment,
            agent=self.agent,
            task_id=self.task_id,
            seed=self.seed,
            metadata={**self.condition, **dict(metadata or {})}
        )
        transformed, applications = self.runtime.apply(
            hook=hook,
            value=value,
            context=context
        )
        self._applications.extend(applications)
        return transformed
