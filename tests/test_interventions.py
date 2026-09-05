import pytest
from harness.agents import AgentSpec, build_agent, edit_agent_spec
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionResult, InterventionSpec
from harness.schema import Observation, VisualObservation
from harness.serialization import content_hash
from harness.testing import ScriptedAgent
from harness.transforms.agent import agent_edit
from harness.transforms.language import language_edit
from harness.transforms.visual import visual_edit


def test_runtime_applies_matching_functions_in_order() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            make_spec("second", 2),
            make_spec("first", 1)
        ],
        registry={"append": append_value}
    )

    value, applications = runtime.apply(
        hook="observation",
        value="start",
        context=InterventionContext(environment="browser", seed=17)
    )

    assert value == "start-first-second"
    assert [application.intervention_id for application in applications] == [
        "first",
        "second"
    ]
    assert applications[0].before_hash != applications[0].after_hash
    assert applications[0].seed == 17


def test_control_runtime_is_identity() -> None:
    value = {"text": "control", "state": {"fixed": True}}
    runtime = CounterfactualRuntime()

    edited, applications = runtime.apply(
        hook="observation",
        value=value,
        context=InterventionContext()
    )

    assert edited == value
    assert applications == []


def test_runtime_records_and_enforces_held_fixed_fields() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="content",
                factor="wording",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="replace-content",
                held_fixed_fields=["geometry"]
            )
        ],
        registry={"replace-content": replace_content}
    )

    value, applications = runtime.apply(
        hook="observation",
        value={"content": "old", "geometry": {"width": 10, "height": 20}},
        context=InterventionContext()
    )

    assert value["content"] == "new"
    assert applications[0].held_fixed_hash is not None


def test_runtime_accepts_precomputed_held_fixed_digest() -> None:
    baseline = {"content": "old", "geometry": {"width": 10, "height": 20}}
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="content",
                factor="wording",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="replace-content",
                held_fixed_fields=["geometry"],
                held_fixed_digest=content_hash({"geometry": baseline["geometry"]})
            )
        ],
        registry={"replace-content": replace_content}
    )

    value, applications = runtime.apply(
        hook="observation",
        value=baseline,
        context=InterventionContext()
    )

    assert value["content"] == "new"
    assert applications[0].held_fixed_hash is not None


def test_selector_supports_route_patterns_and_application_limits() -> None:
    spec = make_spec("route", 0).model_copy(
        update={
            "selector": {"url": "https://example.test/*"},
            "max_applications": 1
        }
    )
    runtime = CounterfactualRuntime(
        specs=[spec],
        registry={"append": append_value}
    )
    context = InterventionContext(
        environment="browser",
        metadata={"url": "https://example.test/page"}
    )

    first, _ = runtime.apply("observation", "start", context)
    second, applications = runtime.apply("observation", "start", context)

    assert first == "start-route"
    assert second == "start"
    assert applications == []


def test_language_visual_and_agent_specifications_stay_separate() -> None:
    observation = Observation(
        step=0,
        text="ordinary copy",
        visual=VisualObservation(data=b"original", width=10, height=20)
    )
    language_result = language_edit(
        observation,
        InterventionContext(),
        operations=[
            {
                "op": "replace",
                "path": "text",
                "old": "ordinary",
                "new": "revised"
            }
        ]
    )
    visual_result = visual_edit(
        observation,
        InterventionContext(),
        operations=[
            {
                "op": "set",
                "path": "visual.data",
                "value": b"edited"
            }
        ]
    )
    agent_result = agent_edit(
        AgentSpec(id="agent", system_prompt="control"),
        InterventionContext(),
        operations=[
            {
                "op": "set",
                "path": "system_prompt",
                "value": "treatment"
            }
        ]
    )

    assert language_result.value.text == "revised copy"
    assert language_result.value.visual.data == b"original"
    assert visual_result.value.text == "ordinary copy"
    assert visual_result.value.visual.data == b"edited"
    assert agent_result.value.system_prompt == "treatment"


def test_visual_specification_can_add_metadata_without_removing_existing_fields() -> None:
    observation = Observation(
        step=0,
        visual=VisualObservation(
            data=b"original",
            width=10,
            height=20,
            metadata={"url": "https://example.test"}
        )
    )

    result = visual_edit(
        observation,
        InterventionContext(),
        operations=[
            {
                "op": "set",
                "path": "visual.metadata.counterfactual_overlay",
                "value": "attention cue"
            }
        ]
    )

    assert result.value.visual.metadata == {
        "url": "https://example.test",
        "counterfactual_overlay": "attention cue"
    }


def test_runtime_rejects_callable_that_crosses_declared_modality() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="language",
                factor="wording",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="edit-visual"
            )
        ],
        registry={"edit-visual": edit_visual_from_language}
    )
    observation = Observation(
        step=0,
        text="copy",
        visual=VisualObservation(data=b"control", width=10, height=20)
    )

    with pytest.raises(AssertionError):
        runtime.apply("observation", observation, InterventionContext())


def test_runtime_uses_computed_changed_fields() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="content",
                factor="wording",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="replace-unreported"
            )
        ],
        registry={"replace-unreported": replace_content_without_report}
    )

    _, applications = runtime.apply(
        "observation",
        {"content": "old"},
        InterventionContext()
    )

    assert applications[0].changed_fields == ["content"]


def test_agent_callable_cannot_edit_outside_allowlist() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="agent",
                factor="scaffold",
                level="treatment",
                scope="agent",
                target="agent",
                modality="structured",
                hook="agent_build",
                function="edit-id"
            )
        ],
        registry={"edit-id": edit_agent_id}
    )

    with pytest.raises(AssertionError):
        runtime.apply(
            "agent_build",
            AgentSpec(id="control"),
            InterventionContext()
        )


def test_agent_edit_reaches_constructed_scaffold() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="prompt",
                factor="prompt",
                level="treatment",
                scope="agent",
                target="agent",
                modality="structured",
                hook="agent_build",
                function="prompt-edit"
            )
        ],
        registry={"prompt-edit": edit_agent_prompt}
    )
    spec = AgentSpec(
        id="agent",
        system_prompt="control",
        scaffold={
            "_target_": "harness.testing.ScriptedAgent",
            "accepts_spec": True
        }
    )

    edited, _ = edit_agent_spec(
        spec=spec,
        runtime=runtime,
        episode_id="episode",
        task_id="task"
    )
    agent = build_agent(edited)

    assert isinstance(agent, ScriptedAgent)
    assert agent.spec.system_prompt == "treatment"


def make_spec(intervention_id: str, order: int) -> InterventionSpec:
    return InterventionSpec(
        id=intervention_id,
        factor="order",
        level=intervention_id,
        scope="environment",
        target="observation",
        modality="language",
        hook="observation",
        function="append",
        arguments={"suffix": intervention_id},
        order=order
    )


def append_value(
    value: str,
    context: InterventionContext,
    suffix: str
) -> InterventionResult:
    del context
    return InterventionResult(
        value="%s-%s" % (value, suffix),
        changed_fields=[""]
    )


def replace_content(
    value: dict,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(
        value={**value, "content": "new"},
        changed_fields=["content"]
    )


def edit_visual_from_language(
    value: Observation,
    context: InterventionContext
) -> InterventionResult:
    del context
    visual = value.visual.model_copy(update={"data": b"treatment"})
    return InterventionResult(
        value=value.model_copy(update={"visual": visual}),
        changed_fields=["visual.data"]
    )


def replace_content_without_report(
    value: dict,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(value={**value, "content": "new"})


def edit_agent_id(
    value: AgentSpec,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(
        value=value.model_copy(update={"id": "treatment"}),
        changed_fields=["id"]
    )


def edit_agent_prompt(
    value: AgentSpec,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(
        value=value.model_copy(update={"system_prompt": "treatment"}),
        changed_fields=["system_prompt"]
    )
