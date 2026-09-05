import fnmatch
import importlib
from copy import deepcopy
from enum import StrEnum
from typing import Any
from collections.abc import Callable, Mapping, Sequence
from pydantic import BaseModel, Field
from harness.schema import InterventionApplication
from harness.serialization import changed_paths, content_hash, project_fields


AGENT_EDITABLE_ROOTS = frozenset(
    {
        "config",
        "instructions",
        "memory_policy",
        "scaffold",
        "system_prompt",
        "tools"
    }
)


class InterventionScope(StrEnum):
    ENVIRONMENT = "environment"
    AGENT = "agent"
    OBSERVER = "observer"


class InterventionTarget(StrEnum):
    OBSERVATION = "observation"
    STATE = "state"
    MESSAGE = "message"
    AFFORDANCE = "affordance"
    OBSERVER_VIEW = "observer_view"
    AGENT = "agent"


class InterventionModality(StrEnum):
    LANGUAGE = "language"
    VISUAL = "visual"
    STRUCTURED = "structured"


class InterventionHook(StrEnum):
    RESET = "episode_start"
    AGENT_BUILD = "agent_build"
    BEFORE_TURN = "before_turn"
    MESSAGE = "message_before_delivery"
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    ACTION = "action"
    BEFORE_ENVIRONMENT = "before_environment"
    AFTER_ENVIRONMENT = "after_action"
    TOOL_RESULT = "tool_result"
    NAVIGATION_RESPONSE = "navigation_response"
    OBSERVATION = "observation"
    SNAPSHOT = "snapshot"
    BEFORE_COMMITMENT = "before_commitment"
    OBSERVER_PAUSE = "observer_pause"


class InterventionContext(BaseModel):
    episode_id: str = ""
    step: int = 0
    environment: str = ""
    agent: str = ""
    task_id: str = ""
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterventionResult(BaseModel):
    value: Any
    changed_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterventionSpec(BaseModel):
    id: str
    factor: str
    level: str
    scope: InterventionScope
    target: InterventionTarget
    modality: InterventionModality
    hook: InterventionHook
    function: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    selector: dict[str, Any] = Field(default_factory=dict)
    order: int = 0
    changed_fields: list[str] = Field(default_factory=list)
    held_fixed_fields: list[str] = Field(default_factory=list)
    max_applications: int | None = None
    expected_relation: str | None = None
    held_fixed_digest: str | None = None


InterventionFunction = Callable[..., InterventionResult]


class CounterfactualRuntime:
    def __init__(
        self,
        specs: Sequence[InterventionSpec | Mapping[str, Any]] = (),
        registry: Mapping[str, InterventionFunction] | None = None
    ) -> None:
        self.specs = sorted(
            [
                spec if isinstance(spec, InterventionSpec) else InterventionSpec.model_validate(spec)
                for spec in specs
            ],
            key=lambda spec: spec.order
        )
        self.registry = dict(registry or {})
        assert len({spec.id for spec in self.specs}) == len(self.specs)
        for spec in self.specs:
            if spec.scope == InterventionScope.AGENT:
                assert spec.target == InterventionTarget.AGENT
                assert spec.hook == InterventionHook.AGENT_BUILD
                assert spec.modality == InterventionModality.STRUCTURED
            if spec.scope == InterventionScope.OBSERVER:
                assert spec.target == InterventionTarget.OBSERVER_VIEW
                assert spec.hook == InterventionHook.OBSERVER_PAUSE
            if spec.scope == InterventionScope.ENVIRONMENT:
                assert spec.target not in (
                    InterventionTarget.AGENT,
                    InterventionTarget.OBSERVER_VIEW
                )
            if spec.hook == InterventionHook.NAVIGATION_RESPONSE:
                assert spec.target in (
                    InterventionTarget.OBSERVATION,
                    InterventionTarget.AFFORDANCE
                )
        self.functions = {
            spec.id: self._resolve(spec.function)
            for spec in self.specs
        }
        self.application_counts = {spec.id: 0 for spec in self.specs}

    def apply(
        self,
        hook: InterventionHook | str,
        value: Any,
        context: InterventionContext
    ) -> tuple[Any, list[InterventionApplication]]:
        selected_hook = InterventionHook(hook)
        transformed = value
        applications = []
        for spec in self.specs:
            if spec.hook != selected_hook:
                continue
            if not self._matches(spec, context):
                continue
            if spec.max_applications is not None and self.application_counts[spec.id] >= spec.max_applications:
                continue
            before = deepcopy(transformed)
            before_hash = content_hash(before)
            held_fixed_hash = None
            if spec.held_fixed_fields:
                held_fixed_hash = content_hash(
                    project_fields(before, spec.held_fixed_fields)
                )
                if spec.held_fixed_digest is not None:
                    assert held_fixed_hash == spec.held_fixed_digest
            result = InterventionResult.model_validate(
                self.functions[spec.id](
                    transformed,
                    context,
                    **spec.arguments
                )
            )
            transformed = result.value
            actual_changed_fields = changed_paths(before, transformed)
            validate_application(
                spec=spec,
                before=before,
                after=transformed,
                actual_changed_fields=actual_changed_fields,
                reported_changed_fields=result.changed_fields
            )
            if spec.held_fixed_fields:
                assert held_fixed_hash == content_hash(
                    project_fields(transformed, spec.held_fixed_fields)
                )
            applications.append(
                InterventionApplication(
                    intervention_id=spec.id,
                    factor=spec.factor,
                    level=spec.level,
                    scope=spec.scope.value,
                    target=spec.target.value,
                    modality=spec.modality.value,
                    hook=spec.hook.value,
                    seed=context.seed,
                    order=spec.order,
                    function=spec.function,
                    arguments=spec.arguments,
                    selector=spec.selector,
                    changed_fields=actual_changed_fields,
                    before_hash=before_hash,
                    after_hash=content_hash(transformed),
                    held_fixed_hash=held_fixed_hash,
                    expected_relation=spec.expected_relation,
                    metadata={
                        **result.metadata,
                        "reported_changed_fields": result.changed_fields
                    }
                )
            )
            self.application_counts[spec.id] += 1
        return transformed, applications

    def reset(self) -> None:
        self.application_counts = {spec.id: 0 for spec in self.specs}

    def _resolve(self, function: str) -> InterventionFunction:
        if function in self.registry:
            return self.registry[function]
        module_name, function_name = function.rsplit(".", maxsplit=1)
        module = importlib.import_module(module_name)
        return getattr(module, function_name)

    def _matches(
        self,
        spec: InterventionSpec,
        context: InterventionContext
    ) -> bool:
        available = {
            "episode_id": context.episode_id,
            "step": context.step,
            "environment": context.environment,
            "agent": context.agent,
            "task_id": context.task_id,
            **context.metadata
        }
        return all(
            selector_matches(available.get(key), expected)
            for key, expected in spec.selector.items()
        )


def selector_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str) and any(character in expected for character in "*?["):
        return fnmatch.fnmatch(str(actual), expected)
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def validate_application(
    spec: InterventionSpec,
    before: Any,
    after: Any,
    actual_changed_fields: Sequence[str],
    reported_changed_fields: Sequence[str]
) -> None:
    if reported_changed_fields:
        if reported_changed_fields == [""]:
            reported_changed_fields = actual_changed_fields
        assert all(
            any(path_within(path, reported) for reported in reported_changed_fields)
            for path in actual_changed_fields
        )
        assert all(
            any(path_within(path, reported) for path in actual_changed_fields)
            for reported in reported_changed_fields
        )
    if spec.changed_fields:
        assert all(
            any(path_within(path, declared) for declared in spec.changed_fields)
            for path in actual_changed_fields
        )
    if spec.scope == InterventionScope.AGENT:
        assert all(path.split(".", maxsplit=1)[0] in AGENT_EDITABLE_ROOTS for path in actual_changed_fields)
    if spec.scope == InterventionScope.ENVIRONMENT and spec.modality == InterventionModality.LANGUAGE:
        assert not any(is_visual_path(path) for path in actual_changed_fields)
    if spec.scope == InterventionScope.ENVIRONMENT and spec.modality == InterventionModality.VISUAL:
        assert all(is_visual_path(path) for path in actual_changed_fields)
    if spec.target == InterventionTarget.OBSERVATION:
        assert observation_like(before)
        assert observation_like(after)
    if spec.target == InterventionTarget.MESSAGE:
        assert message_like(before)
        assert message_like(after)
    if spec.target == InterventionTarget.AGENT:
        assert agent_like(before)
        assert agent_like(after)


def path_within(path: str, declared: str) -> bool:
    return path == declared or path.startswith("%s." % (declared,))


def is_visual_path(path: str) -> bool:
    return path in (
        "data",
        "height",
        "media_type",
        "metadata",
        "width"
    ) or path.startswith("metadata.") or path in (
        "screenshot",
        "visual"
    ) or path.startswith("screenshot.") or path.startswith("visual.")


def observation_like(value: Any) -> bool:
    if isinstance(value, BaseModel):
        return value.__class__.__name__ in ("Observation", "VisualObservation")
    return isinstance(value, str | Mapping)


def message_like(value: Any) -> bool:
    return isinstance(value, Mapping) and "text" in value


def agent_like(value: Any) -> bool:
    return isinstance(value, BaseModel) and value.__class__.__name__ == "AgentSpec"
