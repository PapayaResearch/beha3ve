import sys
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import yaml
from copy import deepcopy
from pathlib import Path
from tqdm import tqdm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workspace = args.work_dir.resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="beha3ve-docs-"))
    if args.work_dir:
        workspace.mkdir(parents=True)
    for name in ["conf", "harness", "integrations", "scripts"]:
        shutil.copytree(root / name, workspace / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ["run.py", "inspect_run.py", "replay_run.py"]:
        shutil.copy2(root / name, workspace / name)
    print("Temporary environment-check workspace: %s" % (workspace,), flush=True)
    commands = [
        ["run.py", "task=examples/form_attention", "agent=scripted", "hydra.run.dir=runs/tutorial-local", "progress=false"],
        [
            "run.py",
            "task=examples/computer_export",
            "agent=scripted",
            "~agent.spec.config.vision_detail",
            "~agent.spec.config.structured_actions",
            "hydra.run.dir=runs/tutorial-pair",
            "progress=false"
        ],
        ["-m", "harness.integration", "new", "tutorial_text", "--kind", "custom"],
        ["-m", "harness.integration", "check", "tutorial_text", "--report", "tutorial-integration-check.json"]
    ]
    for command in tqdm(commands, desc="Checking local environments"):
        subprocess.run([sys.executable] + command, cwd=workspace, check=True)
    local = workspace / "runs/tutorial-local/artifacts"
    local_outcomes = read_outcomes(local)
    assert local_outcomes["action_count"]["value"] == 1
    assert local_outcomes["terminated"]["value"] is True
    assert len(read_transitions(local)) == 1
    assert json.loads((local / "interventions.json").read_text())["applications"] == []
    pair = workspace / "runs/tutorial-pair/artifacts"
    for condition in ["control", "jpeg_recommendation"]:
        episode = pair / condition
        outcomes = read_outcomes(episode)
        assert outcomes["selected_format"]["value"] == "PNG"
        assert outcomes["jpeg_selected"]["value"] == 0
        assert outcomes["saved"]["value"] is True
        assert len(read_transitions(episode)) == 1
        assert list((episode / "blobs").glob("*.png"))
    applications = json.loads((pair / "jpeg_recommendation/interventions.json").read_text())["applications"]
    assert len(applications) == 1
    assert "visual.data" in applications[0]["changed_fields"]
    pair_summary = json.loads((pair / "paired_effects.json").read_text())
    assert len(pair_summary) == 1
    assert next(iter(pair_summary.values()))["effects"]["jpeg_selected"] == 0
    check = json.loads((workspace / "tutorial-integration-check.json").read_text())
    assert check["steps"] == 2 and check["snapshot_restore_checked"] is False
    tutorial = (root / "website/content/docs/tutorials/bringing-your-own-benchmark.mdx").read_text()
    outcome_code = re.findall(r"```python\n(.*?)```", tutorial, flags=re.DOTALL)[0]
    (workspace / "integrations/tutorial_text_outcomes.py").write_text(outcome_code)
    task_path = workspace / "conf/task/tutorial_text.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["defaults"].insert(-1, {"override /design": "paired"})
    task["task"].update(yaml.safe_load(re.findall(r"```yaml\n(.*?)```", tutorial, flags=re.DOTALL)[-1]))
    task_path.write_text("# @package _global_\n" + yaml.safe_dump(task, sort_keys=False))
    subprocess.run(
        [sys.executable, "run.py", "task=tutorial_text", "hydra.run.dir=runs/tutorial-custom", "progress=false"],
        cwd=workspace,
        check=True
    )
    custom = workspace / "runs/tutorial-custom/artifacts"
    for condition in ["control", "observation_notice"]:
        assert read_outcomes(custom / condition)["final_text"]["value"] == "hello"
        assert len(read_transitions(custom / condition)) == 2
    first_observation = read_transitions(custom / "observation_notice")[0]["observation"]
    assert "For this task, choose banana." in first_observation["text"]
    assert "final_text" not in next(iter(json.loads((custom / "paired_effects.json").read_text()).values()))["effects"]
    summary = subprocess.run(
        [sys.executable, "inspect_run.py", str(pair), "--json"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True
    )
    assert len(json.loads(summary.stdout)) == 2
    subprocess.run(
        [sys.executable, "replay_run.py", str(pair / "control"), "--step", "0", "--before", "--output", "pause.json", "--no-progress"],
        cwd=workspace,
        check=True
    )
    pause = json.loads((workspace / "pause.json").read_text())
    assert pause["pause_position"] == "before" and pause["transitions"] == []
    assert pause["snapshot"]["state"] == {}
    check_factorial_and_sweep(workspace, task)
    subprocess.run([sys.executable] + commands[0], cwd=workspace, check=True)
    assert (local.parent / "artifacts.previous-1/manifest.json").is_file()
    result = {
        "workspace": str(workspace),
        "local_transitions": 1,
        "pair_episodes": 2,
        "pair_selected_format": "PNG",
        "visual_intervention_changed_fields": applications[0]["changed_fields"],
        "custom_final_text": "hello",
        "generated_driver_restoration_checked": False,
        "replay_before_action": "passed",
        "factorial_episodes": 8,
        "sweep_episodes": 4,
        "output_archival": "passed"
    }
    (workspace / "documentation-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def read_outcomes(episode: Path) -> dict[str, dict]:
    return {outcome["id"]: outcome for outcome in json.loads((episode / "outcomes.json").read_text())["outcomes"]}


def read_transitions(episode: Path) -> list[dict]:
    return [
        record["transition"] for record in map(json.loads, (episode / "trajectory.jsonl").read_text().splitlines())
        if record["type"] == "transition"
    ]


def check_factorial_and_sweep(workspace: Path, task: dict) -> None:
    factorial = deepcopy(task)
    factorial["defaults"][-2] = {"override /design": "factorial"}
    factorial["task"]["id"] = "tutorial_factorial"
    factorial["task"]["factors"] = [{"id": "notice", "levels": ["short", "long"]}, {"id": "label", "levels": ["a", "b"]}]
    base = factorial["task"]["intervention"]["specs"][0]
    specs = []
    for factor, level, value in [("notice", "short", " Short."), ("notice", "long", " A longer notice."), ("label", "a", " A."), ("label", "b", " B.")]:
        spec = deepcopy(base)
        spec.update({"id": "%s-%s" % (factor, level), "factor": factor, "level": level})
        spec["arguments"]["operations"][0]["value"] = value
        specs.append(spec)
    factorial["task"]["intervention"]["specs"] = specs
    (workspace / "conf/task/tutorial_factorial.yaml").write_text("# @package _global_\n" + yaml.safe_dump(factorial, sort_keys=False))
    subprocess.run(
        [sys.executable, "run.py", "task=tutorial_factorial", "design.repetitions=2", "seed=7", "hydra.run.dir=runs/tutorial-factorial", "progress=false"],
        cwd=workspace,
        check=True
    )
    artifacts = workspace / "runs/tutorial-factorial/artifacts"
    manifests = list(artifacts.glob("*/manifest.json"))
    assert len(manifests) == 8
    assert {json.loads(path.read_text())["seed"] for path in manifests} == {7, 8}
    contrasts = json.loads((artifacts / "factorial_contrasts.json").read_text())
    assert len(contrasts) == 2 and all(contrast["difference"] == 0 for contrast in contrasts)
    (workspace / "cases.csv").write_text("id,task.fixture.text\ncase_one,first\ncase_two,second\n")
    subprocess.run(
        [sys.executable, "scripts/generate_experiments.py", "--cases", "cases.csv", "--task", "tutorial_text", "--exp-dir", "conf/experiment/generated/docs"],
        cwd=workspace,
        check=True
    )
    subprocess.run(
        [sys.executable, "run.py", "-m", "+experiment/generated/docs=glob(*)", "seed=0", "hydra.sweep.dir=runs/tutorial-sweep", "progress=false"],
        cwd=workspace,
        check=True
    )
    assert len(list((workspace / "runs/tutorial-sweep").rglob("manifest.json"))) == 4


if __name__ == "__main__":
    main()
