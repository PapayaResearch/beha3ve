import os
import pytest
from hydra import compose, initialize_config_dir
from omegaconf import OmegaConf
from types import SimpleNamespace
from pathlib import Path
from harness.agents import AgentSpec, build_agent
from harness.schema import Observation, VisualObservation
from harness.design import materialize_design


CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "conf"))


def test_default_composition_uses_live_browser_task() -> None:
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(config_name="config")

    assert config.task.id == "live_wikipedia_research"
    assert config.agent.id == "openai/gpt-5.6-luna"
    assert config.agent.spec.scaffold._target_ == "harness.agents.LiteLLMAgent"
    assert config.environment.id == "browser"
    assert config.task.intervention.id == "mitm_html_banner"
    assert config.design.id == "paired"


@pytest.mark.parametrize(
    "task,environment",
    [
        ("form_attention", "browser_memory"),
        ("live_wikipedia_research", "browser"),
        ("delegation_messages", "structured"),
        ("shared_workspace", "structured"),
        ("policy_boundary", "structured"),
        ("observer_handoff", "computer_use")
    ]
)
def test_example_tasks_compose_with_adapter(task: str, environment: str) -> None:
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(
            config_name="config",
            overrides=[
                "task=examples/%s" % (task,),
                "environment=%s" % (environment,)
            ]
        )

    assert config.task.id == task
    assert config.environment.id == environment
    assert set(config.task.required_capabilities) <= set(config.environment.capabilities)
    assert config.task.fixture_version
    assert config.task.outcomes
    assert "paper_id" not in config.task
    assert "tracks" not in config.task


@pytest.mark.parametrize(
    "environment,target,snapshot_restore",
    [
        ("structured", "harness.environments.structured.StructuredEnvironment", True),
        ("browser", "harness.environments.browser.BrowserEnvironment", False),
        ("browser_memory", "harness.environments.browser.BrowserEnvironment", True),
        ("computer_use", "harness.environments.computer_use.ComputerUseEnvironment", True)
    ]
)
def test_environment_profiles_use_sibling_adapters(
    environment: str,
    target: str,
    snapshot_restore: bool
) -> None:
    profile = load_profile("environment", environment)

    assert profile.id == environment
    assert profile.adapter._target_ == target
    assert ("snapshot_restore" in profile.capabilities) is snapshot_restore


def test_live_browser_experiment_is_hydra_composed() -> None:
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(
            config_name="config",
            overrides=["task=examples/live_wikipedia_research"]
        )

    assert config.experiment_id == "live_wikipedia_research"
    assert config.task.id == "live_wikipedia_research"
    assert config.environment.adapter.backend._target_ == "harness.environments.browser.PlaywrightBrowserBackend"
    assert config.task.intervention.id == "mitm_html_banner"
    assert config.task.intervention.specs[0].hook == "navigation_response"
    assert config.design.kind == "paired"
    assert config.max_steps == 10


def test_factorial_design_reads_task_factors_and_requires_bindings() -> None:
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(
            config_name="config",
            overrides=["design=factorial"]
        )

    assert config.design.cross_factors == config.task.factors
    assert config.design.require_factor_bindings is True


def load_profile(group: str, profile: str):
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        return compose(
            config_name="config",
            overrides=["%s=%s" % (group, profile)]
        )[group]


@pytest.mark.parametrize("profile", [
    "openai/gpt-5.6-luna",
    "openai/gpt-5.6-terra",
    "openai/gpt-5.6-sol",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-5",
    "google/gemini-3.8-flash",
    "bedrock/qwen3-vl-235b"
])
@pytest.mark.parametrize("task", [str(path.relative_to(Path(CONFIG_DIR) / "task")).removesuffix(".yaml") for path in (Path(CONFIG_DIR) / "task").rglob("*.yaml")])
def test_model_profiles_build_and_preserve_provider_settings(
    profile: str,
    task: str,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []

    def completion(**arguments: object) -> SimpleNamespace:
        requests.append(arguments)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{\"kind\":\"DONE\",\"arguments\":{},\"text\":null}"))])

    monkeypatch.setattr("litellm.completion", completion)
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(config_name="config", overrides=["agent=%s" % (profile,), "task=%s" % (task,)])
    assert config.agent.id == profile
    spec = AgentSpec.model_validate(OmegaConf.to_container(config.agent.spec, resolve=True))
    spec.tools = [{"kind": "DONE", "arguments": {}}]
    agent = build_agent(spec)
    agent.reset(seed=7)
    action = agent.act(Observation(
        step=0,
        text="Finish",
        structured={"body": "<p>Finish</p>", "accessibility": {"tree": "- text: Finish"}},
        visual=VisualObservation(data=b"png", media_type="image/png")
    ))
    assert requests[0]["model"] == config.agent.chat_model_args.model
    assert "temperature" not in requests[0]
    assert "max_tokens" not in requests[0]
    assert "max_completion_tokens" not in requests[0]
    assert "api_key" not in requests[0]
    assert "seed" not in requests[0]
    assert action.metadata["llm"]["seed"] is None
    assert requests[0]["num_retries"] == 3
    assert requests[0]["timeout"] == 120
    assert ("response_format" in requests[0]) is (not profile.startswith("bedrock/"))


def test_task_budget_and_optional_experiment_overrides(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "experiment"
    experiment_dir.mkdir()
    (experiment_dir / "longer.yaml").write_text("# @package _global_\nmax_steps: 40\n", encoding="utf-8")
    (experiment_dir / "task_budget.yaml").write_text("# @package _global_\ntask:\n  max_steps: 35\n", encoding="utf-8")
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        default = compose(config_name="config")
        native = compose(config_name="config", overrides=["task=osworld/native_default"])
        changed_task = compose(config_name="config", overrides=["task.max_steps=23"])
        overrides = ["hydra.searchpath=[file://%s]" % (tmp_path,), "task=osworld/native_default"]
        experiment = compose(config_name="config", overrides=[*overrides, "experiment=longer"])
        experiment_task = compose(config_name="config", overrides=[*overrides, "experiment=task_budget"])
        cli = compose(config_name="config", overrides=[*overrides, "experiment=longer", "max_steps=50"])
    assert default.max_steps == default.task.max_steps == 10
    assert native.max_steps == native.task.max_steps == 18
    assert changed_task.max_steps == 23
    assert experiment.max_steps == 40 and experiment.task.max_steps == 18
    assert experiment_task.max_steps == experiment_task.task.max_steps == 35
    assert cli.max_steps == 50


@pytest.mark.parametrize("control_only", [False, True])
def test_task_runs_control_or_treatment_without_experiment(control_only: bool) -> None:
    overrides = ["task=abxlab/abx_social_proof", "design=single"]
    if control_only:
        overrides.append("design.conditions=[control]")
    with initialize_config_dir(version_base=None, config_dir=CONFIG_DIR):
        config = compose(config_name="config", overrides=overrides)
    conditions = materialize_design(
        kind=config.design.kind,
        intervention_id=config.task.intervention.id,
        explicit_conditions=list(config.design.conditions)
    )
    assert len(conditions) == 1
    assert conditions[0].intervention_id == ("control" if control_only else "abx_social_proof")
