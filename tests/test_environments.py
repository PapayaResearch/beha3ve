import pytest
from harness.testing import ScriptedAgent
from harness.environments.base import EnvironmentCapability
from harness.environments.browser import BrowserEnvironment, MemoryBrowserBackend
from harness.environments.computer_use import ComputerUseEnvironment, MemoryComputerUseBackend
from harness.environments.structured import MemoryStructuredBackend, RulePolicyOracle, StructuredEnvironment
from harness.evaluators import OutcomeEvaluator
from harness.interventions import CounterfactualRuntime, InterventionContext, InterventionResult, InterventionSpec
from harness.runner import ScheduledEpisodeRunner
from harness.schema import Action


@pytest.mark.parametrize(
    "environment,required",
    [
        (
            BrowserEnvironment(MemoryBrowserBackend()),
            EnvironmentCapability.NAVIGATION_RESPONSE
        ),
        (
            ComputerUseEnvironment(MemoryComputerUseBackend()),
            EnvironmentCapability.VISUAL_OBSERVATION
        ),
        (
            StructuredEnvironment(MemoryStructuredBackend()),
            EnvironmentCapability.ACTOR_SPECIFIC_OBSERVATION
        )
    ]
)
def test_adapters_expose_separate_capabilities(
    environment: object,
    required: EnvironmentCapability
) -> None:
    assert required in environment.capabilities
    assert EnvironmentCapability.SNAPSHOT_RESTORE in environment.capabilities


def test_browser_intercepts_response_before_render_and_restores() -> None:
    backend = MemoryBrowserBackend(
        pages={
            "https://example.test": {
                "body": "<h1>Visible</h1>",
                "text": "Visible",
                "screenshot": b"pixels"
            }
        },
        initial_url="https://example.test"
    )
    backend.register_response_interceptor(rewrite_response)
    environment = BrowserEnvironment(backend=backend)

    observation, snapshot = environment.reset(seed=3)
    environment.step(Action(kind="type", arguments={"target": "answer"}, text="x"))
    restored = environment.restore(snapshot)

    assert observation.text == "Edited"
    assert observation.structured["body"] == "<h1>Edited</h1>"
    assert observation.visual.data == b"pixels"
    assert restored.step == 0


def test_runtime_language_edit_changes_browser_observation() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="copy",
                factor="copy",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="harness.transforms.language_edit",
                arguments={
                    "operations": [
                        {
                            "op": "replace",
                            "path": "text",
                            "old": "Visible",
                            "new": "Edited"
                        }
                    ]
                }
            )
        ]
    )
    environment = BrowserEnvironment(
        backend=MemoryBrowserBackend(
            pages={
                "https://example.test": {
                    "body": "Visible",
                    "text": "Visible",
                    "screenshot": b"pixels"
                }
            },
            initial_url="https://example.test"
        ),
        runtime=runtime
    )

    observation, _ = environment.reset(seed=3)

    assert observation.text == "Edited"
    assert observation.structured["body"] == "Visible"


def test_computer_use_edits_screenshot_without_browser_state() -> None:
    backend = MemoryComputerUseBackend(
        initial_text="Desktop",
        initial_screenshot=b"control"
    )
    backend.register_screenshot_editor(rewrite_screenshot)
    environment = ComputerUseEnvironment(backend=backend)

    observation, _ = environment.reset(seed=4)

    assert observation.text == "Desktop"
    assert observation.visual.data == b"treatment"
    assert "url" not in observation.structured


def test_runtime_visual_edit_leaves_computer_state_canonical() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="pixels",
                factor="pixels",
                level="treatment",
                scope="environment",
                target="observation",
                modality="visual",
                hook="observation",
                function="harness.transforms.visual_edit",
                arguments={
                    "operations": [
                        {
                            "op": "set",
                            "path": "visual.data",
                            "value": b"treatment"
                        }
                    ]
                }
            )
        ]
    )
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(initial_screenshot=b"control"),
        runtime=runtime
    )

    observation, _ = environment.reset(seed=4)

    assert observation.visual.data == b"treatment"
    assert environment.inspect()["screenshot"] == b"control"


def test_structured_environment_has_actor_specific_observations() -> None:
    backend = MemoryStructuredBackend(
        initial_state={
            "actors": {
                "agent": {"state": {"private": "a"}, "messages": []},
                "partner": {"state": {"private": "b"}, "messages": []}
            },
            "shared": {},
            "terminated": False,
            "truncated": False
        }
    )
    environment = StructuredEnvironment(backend=backend)
    environment.reset(seed=5)

    agent_observation = environment.observe("agent")
    partner_observation = environment.observe("partner")

    assert agent_observation.structured["actor_state"]["private"] == "a"
    assert partner_observation.structured["actor_state"]["private"] == "b"


def test_scheduled_episode_binds_sender_identity_to_actor() -> None:
    backend = MemoryStructuredBackend(
        initial_state={
            "actors": {
                "agent": {"state": {}, "messages": []},
                "partner": {"state": {}, "messages": []}
            },
            "shared": {},
            "provenance": [],
            "terminated": False,
            "truncated": False
        }
    )
    environment = StructuredEnvironment(backend=backend)
    runner = ScheduledEpisodeRunner(
        environment=environment,
        participants={
            "partner-script": ScriptedAgent(
                actions=[
                    Action(
                        kind="message",
                        arguments={"recipient": "agent", "sender": "spoofed"},
                        text="hello"
                    )
                ]
            )
        },
        turns=[{"actor_id": "partner", "participant_id": "partner-script"}],
        evaluator=OutcomeEvaluator(outcomes=[]),
        progress=False
    )

    result = runner.run(episode_id="scheduled", seed=6)

    assert result.final_snapshot.state["actors"]["agent"]["messages"][0]["sender"] == "partner"
    assert result.final_snapshot.state["provenance"][0]["actor_id"] == "partner"


def test_structured_policy_records_and_blocks_denied_action() -> None:
    backend = MemoryStructuredBackend(
        policy_oracle=RulePolicyOracle(denied_action_kinds=["set_shared_state"])
    )
    environment = StructuredEnvironment(backend=backend)
    environment.reset(seed=8)

    transition = environment.step(
        Action(kind="set_shared_state", arguments={"values": {"secret": True}})
    )

    assert transition.info["backend"] == "structured"
    assert environment.inspect()["last_policy_decision"]["allowed"] is False
    assert "secret" not in environment.inspect()["shared"]
    assert environment.inspect()["last_blocked_action"]["kind"] == "set_shared_state"
    assert environment.inspect()["provenance"][0]["attempted"] is True
    assert environment.inspect()["provenance"][0]["blocked"] is True
    assert environment.inspect()["provenance"][0]["realized"] is False


def test_snapshot_hook_is_recorded_in_snapshot_metadata() -> None:
    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="snapshot",
                factor="snapshot",
                level="treatment",
                scope="environment",
                target="state",
                modality="structured",
                hook="snapshot",
                function="snapshot-edit"
            )
        ],
        registry={"snapshot-edit": edit_snapshot}
    )
    environment = ComputerUseEnvironment(
        backend=MemoryComputerUseBackend(),
        runtime=runtime
    )
    environment.reset(seed=9)

    snapshot = environment.snapshot()

    assert snapshot.metadata["marker"] == "treatment"
    assert snapshot.metadata["interventions"][0]["intervention_id"] == "snapshot"


def rewrite_response(value: dict, event: object) -> dict:
    del event
    return {**value, "body": "<h1>Edited</h1>", "text": "Edited"}


def rewrite_screenshot(value: object, event: object) -> object:
    del event
    return value.model_copy(update={"data": b"treatment"})


def edit_snapshot(
    value: object,
    context: InterventionContext
) -> InterventionResult:
    del context
    return InterventionResult(
        value=value.model_copy(
            update={"metadata": {**value.metadata, "marker": "treatment"}}
        ),
        changed_fields=["metadata.marker"]
    )
