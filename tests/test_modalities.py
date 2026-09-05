import pytest
from types import SimpleNamespace
from harness.agents import AgentSpec, LiteLLMAgent
from harness.html import prune_html
from harness.schema import Observation, VisualObservation
from harness.trace_viewer import compact_llm_messages


@pytest.mark.parametrize("modality", ["pruned_html", "accessibility_tree", "text", "screenshot", ["pruned_html", "screenshot"]])
def test_requested_modalities_are_exactly_the_observations_sent(modality: str | list[str]) -> None:
    requests = []

    def completion(**arguments: object) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{\"kind\":\"finish\",\"arguments\":{},\"text\":null}"))])

    agent = LiteLLMAgent(
        spec=AgentSpec(id="test"),
        chat_model_args={"model": "test"},
        modality=modality,
        completion=completion
    )
    agent.reset()
    action = agent.act(Observation(
        step=0,
        text="TEXT_MARKER",
        structured={
            "body": "<script>RAW_SCRIPT</script><button data-harness-bid=\"0\">HTML_MARKER</button>",
            "accessibility": {"tree": "- button TREE_MARKER"},
            "private_state": "STATE_MARKER"
        },
        visual=VisualObservation(data=b"png", media_type="image/png")
    ))
    modalities = [modality] if isinstance(modality, str) else modality
    content = requests[0]["messages"][-1]["content"]
    text = content[0]["text"] if isinstance(content, list) else content
    assert ("HTML_MARKER" in text) == ("pruned_html" in modalities)
    assert ("TREE_MARKER" in text) == ("accessibility_tree" in modalities)
    assert ("TEXT_MARKER" in text) == ("text" in modalities)
    assert ("STATE_MARKER" in text) == ("text" in modalities)
    assert isinstance(content, list) == ("screenshot" in modalities)
    assert "RAW_SCRIPT" not in text
    assert action.metadata["llm"]["observation_modalities"] == modalities


def test_pruning_preserves_controls_and_removes_markup_noise() -> None:
    html = """<html><body><!-- comment --><style>CSS_MARKER</style><script>JS_MARKER</script>
    <div class="layout"><button data-harness-bid="2" onclick="JS_MARKER" aria-label="Buy">Buy</button>
    <input data-harness-bid="3" value="current value" checked disabled>
    <p hidden>HIDDEN_MARKER</p><pre>  keep\n whitespace</pre></div></body></html>"""
    result = prune_html(html)
    assert all(noise not in result for noise in ["comment", "CSS_MARKER", "JS_MARKER", "HIDDEN_MARKER", "onclick", "class="])
    assert 'bid="2"' in result and 'aria-label="Buy"' in result
    assert 'value="current value"' in result and "checked" in result and "disabled" in result
    assert "  keep\n whitespace" in result


@pytest.mark.parametrize("modality", ["pruned_html", "accessibility_tree", "screenshot"])
def test_missing_requested_observation_is_not_silently_replaced(modality: str) -> None:
    agent = LiteLLMAgent(spec=AgentSpec(id="test"), chat_model_args={"model": "test"}, modality=modality)
    with pytest.raises(AssertionError, match="requires"):
        agent._observation_content(Observation(step=0, text="Some other representation"))


def test_new_trace_model_input_is_not_shortened_by_viewer() -> None:
    messages = [{"role": "user", "content": "a" * 9000} for _ in range(7)]
    llm = {"observation_modalities": ["text"], "messages": messages}
    compact_llm_messages(llm)
    assert len(llm["messages"]) == 7
    assert len(llm["messages"][0]["content"]) == 9000
