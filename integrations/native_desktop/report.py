import json
import shutil
import argparse
from pathlib import Path
from typing import Any
from tqdm import tqdm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("runs/osworld-native-realistic")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/osworld-native.json")
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = summarize(args.root, args.output.parent)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Native OSWorld counterfactual runs",
        "",
        "These runs use the actual Nautilus file manager on the supplied OSWorld-V2 Ubuntu VM. "
        "Task setup changes file names, folder names, or selection before the desktop screenshot is captured. "
        "The vision model receives screenshots and operates the mouse and keyboard; outcomes come from guest filesystem checks.",
        "",
        "Recorded model: %s. These pairs use one episode per arm with configured seed 0." % (report["pairs"][0]["control"]["model"],),
        "",
        "| Pair | Control choice | Treatment choice | Control success | Treatment success | Actions (control / treatment) |",
        "|---|---|---|---|---|---|"
    ]
    for pair in report["pairs"]:
        control, treatment = pair["control"], pair["treatment"]
        lines.append("| %s | %s | %s | %s | %s | %s / %s |" % (
            pair["experiment"],
            control["choice"],
            treatment["choice"],
            control["success"],
            treatment["success"],
            control["steps"],
            treatment["steps"]
        ))
    lines.extend([
        "",
        "Model calls: %s. Input tokens: %s. Output tokens: %s." % (
            report["model_calls"],
            report["prompt_tokens"],
            report["completion_tokens"]
        ),
        "",
        "Each pair has one seed and one episode per arm. These are task fixtures in a benchmark desktop environment, "
        "not official OSWorld-V2 task scores or estimates of population effects. A file or folder label can also communicate "
        "task-relevant information; these examples do not separate that interpretation from a preference effect.",
        "",
        "The treatments are a reviewed filename, preselection of Draft B, and a Team archive folder name. "
        "Renaming the archive also changes its alphabetical position relative to the memo. "
        "Preselection leaves names and layout unchanged and is the simplest pair to reuse.",
        "",
        "File contents and candidate counts match within each pair. The fixture directory is recreated between episodes; "
        "the VM is reused without a disk snapshot reset. The initial screenshots and filesystem records are retained.",
        "",
        "## Initial screenshots"
    ])
    for pair in report["pairs"]:
        lines.extend(["", "### %s" % (pair["experiment"],)])
        for condition in ["control", "treatment"]:
            episode = pair[condition]
            lines.extend([
                "",
                "%s:" % (condition.capitalize(),),
                "",
                "![%s](%s)" % (condition, episode["screenshot"])
            ])
    lines.extend([
        "",
        "Run commands: [desktop examples](../EXAMPLES.md#native-desktop-cues).",
        "Detailed measurements: [JSON report](%s)." % (args.output.name,),
        "",
        "Development attempts are preserved under `runs/osworld-native/` and `runs/osworld-native-grounding/`. "
        "They include superseded wording, GPT-4.1 click failures, and a window-focus bug fixed before this batch."
    ])
    args.output.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, indent=2))


def summarize(root: Path, images: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"pairs": [], "model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    pairs = sorted(root.glob("*/artifacts/paired_effects.json"))
    assert pairs, "No completed pairs in %s" % (root,)
    for pair_file in tqdm(pairs, desc="Reading desktop pairs"):
        pair: dict[str, Any] = {"experiment": pair_file.parent.parent.name}
        initial_states = []
        for directory in sorted(pair_file.parent.iterdir()):
            if not (directory / "manifest.json").exists():
                continue
            manifest = json.loads((directory / "manifest.json").read_text())
            rows = [json.loads(line) for line in (directory / "trajectory.jsonl").read_text().splitlines()]
            initial = rows[0]["initial_snapshot"]
            final = rows[-1]["final_snapshot"]
            transitions = [row["transition"] for row in rows if row["type"] == "transition"]
            initial_states.append(initial["state"])
            condition = "control" if manifest["condition_id"] == "control" else "treatment"
            screenshot = "%s-%s.png" % (pair["experiment"], condition)
            shutil.copyfile(directory / initial["observation"]["visual"]["artifact"], images / screenshot)
            scores = {outcome["id"]: outcome["value"] for outcome in rows[-1]["evaluation"]["outcomes"]}
            assert scores["success"] == final["state"]["valid"]
            assert not initial["state"]["valid"]
            applications = [application for step in transitions for application in step["interventions"]]
            assert condition == "control" or any(application["changed_fields"] == ["nudge"] for application in applications)
            pair[condition] = {
                "directory": str(directory),
                "screenshot": screenshot,
                "seed": manifest["seed"],
                "model": manifest["metadata"]["model"],
                "choice": final["state"]["choice"],
                "success": scores["success"],
                "steps": len(transitions),
                "terminated": transitions[-1]["terminated"],
                "truncated": transitions[-1]["truncated"],
                "final_files": final["state"]["files"],
                "intervention_applications": len(applications)
            }
            for step in transitions:
                call = step["action"]["metadata"]["llm"]
                report["model_calls"] += 1
                report["prompt_tokens"] += call["usage"]["prompt_tokens"]
                report["completion_tokens"] += call["usage"]["completion_tokens"]
        assert len(initial_states) == 2
        assert sorted(initial_states[0]["files"].values()) == sorted(initial_states[1]["files"].values())
        assert len(initial_states[0]["directories"]) == len(initial_states[1]["directories"])
        pair["matching_initial_contents"] = True
        pair["matching_candidate_counts"] = True
        report["pairs"].append(pair)
    return report


if __name__ == "__main__":
    main()
