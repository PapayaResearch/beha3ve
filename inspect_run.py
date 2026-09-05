import argparse
import json
from pathlib import Path
from typing import Any
from harness.serialization import canonical_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?", default="runs/run")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    episode_dirs = find_episode_dirs(run_dir)
    summaries = [summarize_episode(path) for path in episode_dirs]
    if args.json:
        print(canonical_json(summaries))
        return
    for summary in summaries:
        print_summary(summary)


def find_episode_dirs(run_dir: Path) -> list[Path]:
    if (run_dir / "manifest.json").exists():
        return [run_dir]
    episode_dirs = sorted(path.parent for path in run_dir.glob("*/manifest.json"))
    assert episode_dirs, "No manifest.json found under %s" % (run_dir,)
    return episode_dirs


def summarize_episode(run_dir: Path) -> dict[str, Any]:
    manifest = read_json(run_dir / "manifest.json")
    intervention_manifest = read_json(run_dir / "interventions.json")
    outcomes = read_json(run_dir / "outcomes.json")
    records = [
        json.loads(line)
        for line in (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    transitions = [record for record in records if record["type"] == "transition"]
    return {
        "run_dir": str(run_dir),
        "episode_id": manifest["episode_id"],
        "task_id": manifest["task_id"],
        "condition_id": manifest["condition_id"],
        "environment_id": manifest["environment_id"],
        "seed": manifest["seed"],
        "transition_count": len(transitions),
        "configured_interventions": intervention_manifest["configured"],
        "applied_interventions": intervention_manifest["applications"],
        "outcomes": outcomes["outcomes"]
    }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def print_summary(summary: dict[str, Any]) -> None:
    print("Episode: %s" % (summary["episode_id"],))
    print("  directory: %s" % (summary["run_dir"],))
    print("  task: %s" % (summary["task_id"],))
    print("  condition: %s" % (summary["condition_id"],))
    print("  environment: %s" % (summary["environment_id"],))
    print("  seed: %s" % (summary["seed"],))
    print("  transitions: %d" % (summary["transition_count"],))
    configured = summary["configured_interventions"]
    applied = summary["applied_interventions"]
    print("  configured interventions: %d" % (len(configured),))
    for spec in configured:
        print(
            "    %s | %s | %s | order=%d" % (
                spec["id"],
                spec["scope"],
                spec["hook"],
                spec["order"]
            )
        )
    print("  applied interventions: %d" % (len(applied),))
    for application in applied:
        print(
            "    %s | step fields=%s | %s -> %s" % (
                application["intervention_id"],
                ", ".join(application["changed_fields"]),
                application["before_hash"][:12],
                application["after_hash"][:12]
            )
        )
    print("  outcomes:")
    for outcome in summary["outcomes"]:
        print(
            "    %s=%s (%s)" % (
                outcome["id"],
                outcome["value"],
                outcome["direction"]
            )
        )


if __name__ == "__main__":
    main()
