import sys
import argparse
import json
import importlib.resources
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence
from hydra import compose, initialize_config_dir
from hydra.utils import instantiate
from omegaconf import OmegaConf
from tqdm import tqdm
from dotenv import load_dotenv, set_key
from harness.environments.base import EnvironmentCapability
from harness.interventions import CounterfactualRuntime
from harness.schema import Action
from harness.serialization import canonical_json, content_hash


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    scaffold = commands.add_parser("new")
    scaffold.add_argument("name")
    scaffold.add_argument("--kind", choices=["browser", "computer", "custom"], default="browser")
    scaffold.add_argument("--root", type=Path, default=Path.cwd())
    scaffold.add_argument("--url", default="https://example.com")
    scaffold.add_argument("--endpoint", default="http://127.0.0.1:8000")
    check = commands.add_parser("check")
    check.add_argument("task")
    check.add_argument("--config-root", type=Path, default=Path.cwd() / "conf")
    check.add_argument("--seed", type=int, default=0)
    check.add_argument("--report", type=Path, default=Path("integration-check.json"))
    args = parser.parse_args()
    if args.command == "new":
        paths = scaffold_integration(
            name=args.name,
            kind=args.kind,
            root=args.root,
            url=args.url,
            endpoint=args.endpoint
        )
        print("Created %s" % (", ".join(str(path) for path in paths),))
        return
    load_dotenv(args.config_root.resolve().parent / ".env")
    with initialize_config_dir(version_base="1.3", config_dir=str(args.config_root.resolve())):
        config = compose(config_name="config", overrides=["task=%s" % (args.task,)])
    sys.path.insert(0, str(args.config_root.resolve().parent))
    environment = instantiate(
        config.environment.adapter,
        runtime=CounterfactualRuntime(OmegaConf.to_container(config.task.intervention.specs, resolve=True)),
        task_id=config.task.id,
        episode_id="integration-check"
    )
    actions = [Action.model_validate(action) for action in OmegaConf.to_container(config.task.actions, resolve=True)]
    report = check_environment(
        environment=environment,
        options=OmegaConf.to_container(config.task.fixture, resolve=True),
        actions=actions,
        seed=args.seed,
        required=config.task.required_capabilities
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Check passed. Report: %s" % (args.report,))


def check_environment(
    environment: Any,
    options: Mapping[str, Any],
    actions: Sequence[Action],
    seed: int = 0,
    required: Sequence[str] = ()
) -> dict[str, Any]:
    try:
        environment.require_capabilities([EnvironmentCapability(value) for value in required])
        observation, initial = environment.reset(seed=seed, options=options)
        assert initial.step == observation.step == 0
        assert content_hash(initial.state) == content_hash(environment.inspect())
        applications = []
        for index, action in enumerate(tqdm(actions, desc="Trying actions")):
            previous = environment.snapshot()
            transition = environment.step(action)
            assert transition.step == index
            assert transition.next_observation.step == transition.after_snapshot.step == index + 1
            assert content_hash(transition.before_snapshot.state) == content_hash(previous.state)
            assert content_hash(transition.observation) == content_hash(observation)
            canonical_json(transition)
            observation = transition.next_observation
            if observation.visual is not None:
                assert observation.visual.data.startswith(b"\x89PNG\r\n\x1a\n")
            applications.extend(transition.interventions)
            if transition.terminated or transition.truncated:
                assert index == len(actions) - 1, "Action list continues after the episode ends"
        restorable = EnvironmentCapability.SNAPSHOT_RESTORE in environment.capabilities
        if restorable:
            environment.restore(initial)
            assert content_hash(environment.inspect()) == content_hash(initial.state)
        return {
            "capabilities": sorted(environment.capabilities),
            "steps": len(actions),
            "snapshot_restore_checked": restorable,
            "initial_state_hash": content_hash(initial.state),
            "intervention_applications": [application.model_dump(mode="json") for application in applications]
        }
    finally:
        environment.close()


def scaffold_integration(
    name: str,
    kind: str,
    root: Path,
    url: str,
    endpoint: str
) -> list[Path]:
    assert name.isidentifier() and not name.startswith("_"), "Use a Python identifier for the integration name"
    assert kind in {"browser", "computer", "custom"}
    files: dict[Path, str] = {}
    actions = [{"kind": "finish"}]
    capabilities = ["text_observation", "state_inspection"]
    fixture: dict[str, Any] = {}
    if kind == "browser":
        capabilities = ["html_observation", "browser_action", "state_inspection"]
        environment = {"defaults": ["browser", "_self_"], "id": name}
        fixture = {"url": "${oc.env:%s_URL}" % (name.upper(),)}
    else:
        driver = {"_target_": "integrations.%s.Driver" % (name,)}
        action_kinds = ["set_text", "finish"]
        actions = [{"kind": "set_text", "text": "hello"}, {"kind": "finish"}]
        if kind == "computer":
            driver = {"_target_": "harness.environments.driver.HTTPDriver", "endpoint": "${oc.env:%s_ENDPOINT}" % (name.upper(),)}
            capabilities += ["computer_action", "visual_observation", "pointer_action", "keyboard_action"]
            action_kinds = ["click", "type", "key", "scroll", "finish"]
            actions = [{"kind": "finish"}]
        else:
            fixture = {"text": ""}
            source = importlib.resources.files("harness").joinpath("templates/driver.py.txt").read_text(encoding="utf-8")
            files[root / "integrations" / (name + ".py")] = source
        environment = {
            "id": name,
            "adapter": {
                "_target_": "harness.environments.base.BaseEnvironmentAdapter",
                "environment": name,
                "backend": {
                    "_target_": "harness.environments.driver.DriverBackend",
                    "driver": driver,
                    "capabilities": capabilities,
                    "action_kinds": action_kinds
                }
            },
            "capabilities": capabilities + ["observation_interception"]
        }
    task = {
        "id": name,
        "fixture_version": "1",
        "max_steps": 10,
        "modality": "pruned_html" if kind == "browser" else "screenshot" if kind == "computer" else "text",
        "instruction": "Inspect the environment, then finish.",
        "required_capabilities": capabilities,
        "fixture": fixture,
        "available_actions": [{"kind": "finish", "description": "Finish the task", "arguments": {}}],
        "actions": actions,
        "default_action": {"kind": "finish"},
        "factors": [],
        "intervention": {"id": "control", "specs": []},
        "held_fixed": ["fixture", "seed"],
        "outcomes": [{"id": "action_count", "direction": "report", "function": "integrations.outcomes.action_count"}]
    }
    task_config = {
        "defaults": [
            {"override /environment": "browser" if kind == "browser" else None},
            {"override /agent": "scripted"},
            "_self_"
        ],
        "task": task,
        "environment": {key: value for key, value in environment.items() if key != "defaults"},
    }
    files[root / "conf" / "task" / (name + ".yaml")] = "# @package _global_\n" + OmegaConf.to_yaml(OmegaConf.create(task_config))
    assert not any(path.exists() for path in files), "Choose a new name; the scaffold never overwrites files"
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if kind != "custom":
        set_key(str(root / ".env"), "%s_%s" % (name.upper(), "URL" if kind == "browser" else "ENDPOINT"), url if kind == "browser" else endpoint)
    return list(files)


if __name__ == "__main__":
    main()
