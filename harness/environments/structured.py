from copy import deepcopy
from typing import Any, Protocol, runtime_checkable
from collections.abc import Callable, Mapping
from harness.interventions import CounterfactualRuntime
from harness.environments.base import (
    BackendHook,
    BackendHookPoint,
    BackendHookRegistry,
    BaseEnvironmentAdapter,
    EnvironmentCapability,
    RendererNeutralBackend
)
from harness.schema import Action, Event, Observation, PolicyDecision, Snapshot, Transition


@runtime_checkable
class StructuredBackendProtocol(RendererNeutralBackend, Protocol):
    def observe(self, actor_id: str) -> Observation:
        ...

    def actor_state(self, actor_id: str) -> Mapping[str, Any]:
        ...

    def register_message_editor(self, hook: BackendHook) -> None:
        ...

    def register_state_editor(self, hook: BackendHook) -> None:
        ...


class MemoryStructuredBackend:
    base_capabilities = frozenset(
        {
            EnvironmentCapability.STRUCTURED_OBSERVATION,
            EnvironmentCapability.TEXT_OBSERVATION,
            EnvironmentCapability.ACTOR_SPECIFIC_OBSERVATION,
            EnvironmentCapability.OBSERVATION_INTERCEPTION,
            EnvironmentCapability.MESSAGE_INTERCEPTION,
            EnvironmentCapability.STATE_INSPECTION,
            EnvironmentCapability.SNAPSHOT_RESTORE,
            EnvironmentCapability.MESSAGES,
            EnvironmentCapability.MULTI_ACTOR,
            EnvironmentCapability.PERSISTENT_STATE,
            EnvironmentCapability.PROVENANCE
        }
    )

    def __init__(
        self,
        initial_state: Mapping[str, Any] | None = None,
        actor_id: str = "agent",
        policy_oracle: Callable[[Action, Mapping[str, Any]], Mapping[str, Any]] | None = None
    ) -> None:
        self._initial_state = deepcopy(initial_state) if initial_state is not None else {
            "actors": {
                actor_id: {
                    "state": {},
                    "messages": []
                }
            },
            "shared": {},
            "provenance": [],
            "terminated": False,
            "truncated": False
        }
        self._actor_id = actor_id
        self._policy_oracle = policy_oracle or allow_all_policy
        self.capabilities = self.base_capabilities
        if policy_oracle is not None:
            self.capabilities = frozenset(
                {*self.capabilities, EnvironmentCapability.POLICY_ORACLE}
            )
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
        self._actor_id = reset_options.get("actor_id", self._actor_id)
        if "denied_action_kinds" in reset_options:
            self._policy_oracle = RulePolicyOracle(
                denied_action_kinds=reset_options["denied_action_kinds"]
            )
        fixture = reset_options.get("state", self._initial_state)
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.RESET,
            value=deepcopy(fixture),
            step=0,
            metadata={"seed": seed}
        )
        self._step = 0
        self._observation = self._make_observation(self._actor_id)
        return self._observation, self.snapshot()

    def step(self, action: Action) -> Transition:
        action_step = self._step
        before_snapshot = self.snapshot()
        scheduled_actor_id = action.metadata.get("actor_id", self._actor_id)
        assert scheduled_actor_id in self._state["actors"]
        self._actor_id = scheduled_actor_id
        policy_decision = PolicyDecision.model_validate(
            self._policy_oracle(action, deepcopy(self._state))
        )
        self._state["last_policy_decision"] = policy_decision.model_dump(mode="python")
        provenance_record = {
            "step": action_step,
            "actor_id": self._actor_id,
            "action": action.model_dump(mode="python"),
            "policy": policy_decision.model_dump(mode="python"),
            "attempted": True,
            "blocked": not policy_decision.allowed,
            "realized": policy_decision.allowed
        }
        self._state.setdefault("provenance", []).append(provenance_record)
        if not policy_decision.allowed:
            self._state["last_blocked_action"] = action.model_dump(mode="python")
        elif action.kind == "message":
            self._apply_message(action)
        elif action.kind == "set_actor_state":
            target_actor_id = action.arguments.get("actor_id", self._actor_id)
            self._state["actors"][target_actor_id]["state"].update(action.arguments["values"])
        elif action.kind == "set_shared_state":
            self._state["shared"].update(action.arguments["values"])
        elif action.kind == "finish":
            self._state["terminated"] = True
        else:
            self._state["last_action"] = action.model_dump(mode="python")
        self._state = self._hooks.apply_hooks(
            point=BackendHookPoint.STATE,
            value=self._state,
            step=action_step,
            metadata={"action_kind": action.kind}
        )
        self._step += 1
        self._observation = self._make_observation(self._actor_id)
        event = Event(
            sequence=action_step,
            step=action_step,
            kind=action.kind,
            actor_id=self._actor_id,
            payload=action.model_dump(mode="python"),
            metadata={"policy": policy_decision.model_dump(mode="python")}
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
            info={"backend": "structured", "actor_id": self._actor_id},
            interventions=[]
        )

    def observe(self, actor_id: str) -> Observation:
        return self._make_observation(actor_id)

    def actor_state(self, actor_id: str) -> Mapping[str, Any]:
        return deepcopy(self._state["actors"][actor_id]["state"])

    def inspect(self) -> Mapping[str, Any]:
        return deepcopy(self._state)

    def snapshot(self) -> Snapshot:
        return Snapshot(
            step=self._step,
            state=deepcopy(self._state),
            observation=deepcopy(self._observation),
            metadata={"backend": "structured", "actor_id": self._actor_id}
        )

    def restore(self, snapshot: Snapshot) -> Observation:
        self._step = snapshot.step
        self._state = deepcopy(snapshot.state)
        self._actor_id = snapshot.metadata.get("actor_id", self._actor_id)
        self._observation = deepcopy(snapshot.observation)
        return self._observation

    def register_hook(self, point: BackendHookPoint, hook: BackendHook) -> None:
        self._hooks.register_hook(point, hook)

    def register_message_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.MESSAGE, hook)

    def register_state_editor(self, hook: BackendHook) -> None:
        self.register_hook(BackendHookPoint.STATE, hook)

    def close(self) -> None:
        return None

    def _apply_message(self, action: Action) -> None:
        recipient = action.arguments.get("recipient", self._actor_id)
        sender = action.metadata.get("actor_id", self._actor_id)
        message = {
            "sender": sender,
            "recipient": recipient,
            "text": action.text or action.arguments.get("text", ""),
            "metadata": deepcopy(action.metadata)
        }
        message = self._hooks.apply_hooks(
            point=BackendHookPoint.MESSAGE,
            value=message,
            step=self._step,
            metadata={"sender": sender, "recipient": recipient}
        )
        self._state["actors"][recipient]["messages"].append(message)
        if sender != recipient:
            self._state["actors"][sender]["messages"].append(message)

    def _make_observation(self, actor_id: str) -> Observation:
        actor = self._state["actors"][actor_id]
        messages = deepcopy(actor["messages"])
        text = messages[-1]["text"] if messages else None
        observation = Observation(
            step=self._step,
            text=text,
            structured={
                "actor_id": actor_id,
                "actor_state": deepcopy(actor["state"]),
                "messages": messages,
                "shared": deepcopy(self._state["shared"])
            },
            visual=None,
            events=[],
            metadata={"backend": "structured", "actor_id": actor_id}
        )
        return self._hooks.apply_hooks(
            point=BackendHookPoint.OBSERVATION,
            value=observation,
            step=self._step,
            metadata={"actor_id": actor_id}
        )


def allow_all_policy(
    action: Action,
    state: Mapping[str, Any]
) -> Mapping[str, Any]:
    del action
    del state
    return {
        "allowed": True,
        "rule_id": "scaffold-default",
        "reason": "No case policy oracle configured"
    }


class RulePolicyOracle:
    def __init__(self, denied_action_kinds: list[str] | None = None) -> None:
        self.denied_action_kinds = frozenset(denied_action_kinds or [])

    def __call__(
        self,
        action: Action,
        state: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        del state
        allowed = action.kind not in self.denied_action_kinds
        return {
            "allowed": allowed,
            "rule_id": "deny-action-kind",
            "reason": "Allowed" if allowed else "Action kind denied"
        }


class StructuredEnvironment(BaseEnvironmentAdapter):
    def __init__(
        self,
        backend: StructuredBackendProtocol | None = None,
        runtime: CounterfactualRuntime | None = None,
        actor_id: str = "agent",
        agent: str | None = None,
        episode_id: str = "",
        task_id: str = "",
        condition: Mapping[str, Any] | None = None
    ) -> None:
        if agent is not None:
            actor_id = agent
        structured_backend = backend or MemoryStructuredBackend(actor_id=actor_id)
        self.structured_backend = structured_backend
        super().__init__(
            backend=structured_backend,
            runtime=runtime,
            environment="structured",
            episode_id=episode_id,
            task_id=task_id,
            agent=actor_id,
            condition=condition
        )

    def reset(
        self,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None
    ) -> tuple[Observation, Snapshot]:
        reset_options = dict(options or {})
        reset_options.setdefault("actor_id", self.agent)
        return super().reset(seed=seed, options=reset_options)

    def observe(self, actor_id: str) -> Observation:
        observation = self.structured_backend.observe(actor_id)
        self._last_observation = observation
        snapshot = self.structured_backend.snapshot()
        self._last_snapshot = snapshot.model_copy(
            update={
                "observation": observation,
                "metadata": {**snapshot.metadata, "actor_id": actor_id}
            }
        )
        return observation
