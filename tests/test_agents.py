import json
from types import SimpleNamespace
from typing import Any
from harness.agents import AgentSpec, LiteLLMAgent
from harness.environments.browser import BrowserEnvironment, MemoryBrowserBackend
from harness.evaluators import OutcomeEvaluator
from harness.interventions import CounterfactualRuntime, InterventionSpec
from harness.runner import EpisodeRunner
from harness.schema import Event, Observation, VisualObservation


def test_structured_actions_constrain_targets_and_keep_bounded_text_memory() -> None:
    requests: list[dict[str, Any]] = []

    def completion(**arguments: Any) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{\"kind\":\"click\",\"arguments\":{\"target\":\"3\"},\"text\":null}"))]
        )

    agent = LiteLLMAgent(
        spec=AgentSpec(
            id="agent",
            tools=[{"kind": "click", "arguments": {"target": "<bid>"}}],
            memory_policy={"retain_observations": 1}
        ),
        modality="text",
        chat_model_args={"model": "test"},
        structured_actions=True,
        completion=completion
    )
    agent.reset()
    observation = Observation(
        step=0,
        text="Product A costs $50",
        structured={"accessibility": {"interactive_elements": [{"bid": "3", "name": "Add to Cart"}]}}
    )
    agent.act(observation)
    agent.act(observation.model_copy(update={"step": 1, "text": "Product B costs $70"}))
    agent.act(observation.model_copy(update={"step": 2, "text": "Product C costs $80"}))
    schema = requests[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["arguments"]["anyOf"][0]["properties"]["target"]["enum"] == ["3"]
    assert len(requests[2]["messages"]) == 4
    assert "Product B costs $70" in requests[2]["messages"][1]["content"]
    assert "Product A costs $50" not in requests[2]["messages"][1]["content"]
    assert "Recent actions" not in requests[2]["messages"][1]["content"]
    agent.reset()
    assert len(agent.messages) == 1


def test_litellm_agent_calls_model_with_intervened_observation() -> None:
    requests: list[dict[str, Any]] = []

    def completion(**arguments: Any) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(
            id="response-1",
            model="openai/test-model",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 3}},
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        reasoning_content="Returned reasoning summary",
                        content=json.dumps(
                            {
                                "kind": "finish",
                                "arguments": {},
                                "text": None
                            }
                        )
                    )
                )
            ]
        )

    agent = LiteLLMAgent(
        spec=AgentSpec(
            id="agent",
            instructions="Read the page and finish.",
            tools=[{"kind": "finish"}],
            memory_policy={"retain_turns": 2}
        ),
        modality="text",
        chat_model_args={"model": "openai/test-model", "num_retries": 3},
        send_seed=True,
        completion=completion
    )
    agent.reset(seed=7)

    action = agent.act(Observation(step=0, text="counterfactual notice"))

    assert action.kind == "finish"
    assert action.metadata["llm"]["model"] == "openai/test-model"
    assert action.metadata["llm"]["usage"]["prompt_tokens"] == 10
    assert action.metadata["llm"]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3
    assert action.metadata["llm"]["reasoning_content"] == "Returned reasoning summary"
    assert action.metadata["llm"]["seed"] == 7
    assert action.metadata["llm"]["messages"][-1]["role"] == "user"
    assert action.metadata["llm"]["assistant_content"] == (
        "{\"kind\": \"finish\", \"arguments\": {}, \"text\": null}"
    )
    assert "counterfactual notice" in requests[0]["messages"][-1]["content"]
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["seed"] == 7
    assert requests[0]["num_retries"] == 3


def test_litellm_agent_sends_visual_observation_as_image() -> None:
    requests: list[dict[str, Any]] = []

    def completion(**arguments: Any) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(
            id="response-visual",
            model="openai/test-model",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "{\"kind\": \"finish\", \"arguments\": {}, \"text\": null}"
                        )
                    )
                )
            ]
        )

    agent = LiteLLMAgent(
        spec=AgentSpec(id="agent", instructions="Inspect the screenshot."),
        modality=["text", "screenshot"],
        chat_model_args={"model": "openai/test-model"},
        completion=completion
    )
    agent.reset()

    action = agent.act(
        Observation(
            step=0,
            visual=VisualObservation(data=b"png", media_type="image/png")
        )
    )

    content = requests[0]["messages"][-1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "data:image/png;base64,cG5n"
    assert content[1]["image_url"]["detail"] == "auto"
    traced_content = action.metadata["llm"]["messages"][-1]["content"]
    assert traced_content[1]["image_url"] == {"artifact": "observation.visual"}


def test_litellm_agent_sends_bounded_bid_observation_without_recursive_history() -> None:
    requests: list[dict[str, Any]] = []

    def completion(**arguments: Any) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(
            id="response-compact",
            model="openai/test-model",
            usage={"prompt_tokens": 100},
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "{\"kind\": \"click\", \"arguments\": "
                            "{\"target\": \"BID7\"}, \"text\": null}"
                        )
                    )
                )
            ]
        )

    agent = LiteLLMAgent(
        spec=AgentSpec(
            id="agent",
            instructions="Use the page.",
            tools=[
                {
                    "kind": "click",
                    "description": "Click a BID.",
                    "arguments": {"target": "BID<number>"}
                }
            ],
            memory_policy={"retain_turns": 2}
        ),
        modality=["text", "screenshot"],
        chat_model_args={"model": "openai/test-model"},
        max_observation_chars=500,
        completion=completion
    )
    agent.reset()
    observation = Observation(
        step=0,
        text="Visible page text",
        structured={
            "url": "https://example.test",
            "title": "Example",
            "body": "RAW-DOM-MARKER" * 100,
            "geometry": {"BID7": {"x": 1, "y": 2}},
            "accessibility": {
                "interactive_elements": [
                    {
                        "bid": "BID7",
                        "role": "button",
                        "name": "Continue",
                        "value": None
                    }
                ]
            }
        },
        visual=VisualObservation(data=b"png", media_type="image/png"),
        events=[
            Event(
                sequence=0,
                step=0,
                kind="click",
                payload={"recursive": "DO-NOT-SEND" * 100}
            )
        ]
    )

    agent.act(observation)
    agent.act(observation.model_copy(update={"step": 1}))

    first_text = requests[0]["messages"][-1]["content"][0]["text"]
    second_text = requests[1]["messages"][-1]["content"][0]["text"]
    assert len(first_text) <= 500
    assert "[bid=BID7] button \"Continue\"" in first_text
    assert "RAW-DOM-MARKER" not in first_text
    assert "DO-NOT-SEND" not in first_text
    assert len(requests[1]["messages"]) == 2
    assert "Recent actions" in second_text
    assert second_text.count("Current observation") == 1


def test_episode_runner_sends_mitm_observation_to_litellm_agent() -> None:
    requests: list[dict[str, Any]] = []

    def completion(**arguments: Any) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(
            id="response-integration",
            model="openai/test-model",
            usage={"total_tokens": 12},
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            "{\"kind\": \"finish\", \"arguments\": {}, \"text\": null}"
                        )
                    )
                )
            ]
        )

    runtime = CounterfactualRuntime(
        specs=[
            InterventionSpec(
                id="notice",
                factor="language",
                level="treatment",
                scope="environment",
                target="observation",
                modality="language",
                hook="observation",
                function="harness.transforms.language_edit",
                arguments={
                    "operations": [
                        {
                            "op": "append",
                            "path": "text",
                            "value": " counterfactual"
                        }
                    ]
                },
                max_applications=1
            )
        ]
    )
    environment = BrowserEnvironment(
        backend=MemoryBrowserBackend(),
        runtime=runtime,
        episode_id="episode",
        task_id="task"
    )
    agent = LiteLLMAgent(
        spec=AgentSpec(
            id="agent",
            instructions="Read and finish.",
            tools=[{"kind": "finish"}]
        ),
        modality="text",
        chat_model_args={"model": "openai/test-model", "num_retries": 3},
        send_seed=True,
        completion=completion
    )
    runner = EpisodeRunner(
        environment=environment,
        agent=agent,
        evaluator=OutcomeEvaluator(outcomes=[]),
        progress=False
    )

    result = runner.run(
        episode_id="episode",
        options={
            "url": "https://example.test",
            "pages": {
                "https://example.test": {
                    "text": "control",
                    "body": "<p>control</p>"
                }
            }
        }
    )

    assert "control counterfactual" in requests[0]["messages"][-1]["content"]
    assert result.trajectory[0].action.metadata["llm"]["response_id"] == "response-integration"
    assert result.trajectory[0].interventions[0].intervention_id == "notice"
