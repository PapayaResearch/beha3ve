import json
from pathlib import Path
from harness.trace_viewer import TraceRequestHandler, compact_transition, load_trace_bundle


def test_trace_viewer_loads_paired_episode_artifacts(tmp_path: Path) -> None:
    write_episode(tmp_path / "control", "control")
    write_episode(tmp_path / "treatment", "treatment")
    (tmp_path / "paired_effects.json").write_text(
        json.dumps({"pair": {"effects": {"success": 1}}}),
        encoding="utf-8"
    )

    bundle = load_trace_bundle(tmp_path)

    assert [episode["manifest"]["condition_id"] for episode in bundle["episodes"]] == [
        "control",
        "treatment"
    ]
    assert bundle["episodes"][1]["transitions"][0]["action"]["kind"] == "finish"
    assert bundle["paired_effects"]["."]["pair"]["effects"]["success"] == 1
    assert bundle["comparisons"][0]["control_index"] == 0
    assert bundle["comparisons"][0]["treatment_index"] == 1
    assert bundle["comparisons"][0]["control_condition"] == "control"
    assert bundle["comparisons"][0]["treatment_condition"] == "treatment"


def test_trace_viewer_static_assets_exist() -> None:
    assert (TraceRequestHandler.static_dir / "index.html").exists()
    assert (TraceRequestHandler.static_dir / "style.css").exists()
    assert (TraceRequestHandler.static_dir / "app.js").exists()


def test_trace_viewer_compacts_recursive_prompt_copies() -> None:
    recursive_text = "recursive-prompt" * 1000
    transition = {
        "observation": {
            "events": [
                {
                    "step": 0,
                    "kind": "click",
                    "actor_id": "agent",
                    "payload": {"metadata": {"llm": {"messages": recursive_text}}},
                    "metadata": {}
                }
            ]
        },
        "next_observation": {"events": []},
        "before_snapshot": {
            "state": {
                "last_action": {
                    "kind": "click",
                    "arguments": {"target": "BID1"},
                    "text": None,
                    "metadata": {"llm": {"messages": recursive_text}}
                }
            },
            "observation": {"text": recursive_text}
        },
        "after_snapshot": {"state": {}, "observation": {"text": recursive_text}},
        "action": {
            "metadata": {
                "llm": {
                    "messages": [
                        {"role": "system", "content": recursive_text},
                        {"role": "user", "content": recursive_text}
                    ]
                }
            }
        }
    }

    compacted = compact_transition(transition)

    assert "payload" not in compacted["observation"]["events"][0]
    assert "observation" not in compacted["before_snapshot"]
    assert "metadata" not in compacted["before_snapshot"]["state"]["last_action"]
    assert len(compacted["action"]["metadata"]["llm"]["messages"][0]["content"]) < len(recursive_text)


def write_episode(run_dir: Path, condition: str) -> None:
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "episode_id": "%s-episode" % (condition,),
                "condition_id": condition,
                "task_id": "task",
                "pair_id": "pair",
                "seed": 0,
                "metadata": {"experiment_id": "experiment"}
            }
        ),
        encoding="utf-8"
    )
    (run_dir / "interventions.json").write_text(
        json.dumps({"configured": [], "applications": []}),
        encoding="utf-8"
    )
    (run_dir / "outcomes.json").write_text(
        json.dumps({"outcomes": [{"id": "success", "value": True}]}),
        encoding="utf-8"
    )
    records = [
        {
            "type": "episode",
            "initial_snapshot": {"step": 0, "state": {}}
        },
        {
            "type": "transition",
            "transition": {
                "step": 0,
                "observation": {"text": condition},
                "action": {"kind": "finish", "arguments": {}, "metadata": {}},
                "interventions": []
            }
        },
        {
            "type": "evaluation",
            "final_snapshot": {"step": 1, "state": {}}
        }
    ]
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8"
    )


def test_factorial_viewer_exposes_every_one_factor_comparison(tmp_path: Path) -> None:
    for price, cue in (("regular", "neutral"), ("regular", "authority"), ("reduced", "neutral"), ("reduced", "authority")):
        directory = tmp_path / ("%s-%s" % (price, cue))
        write_episode(directory, directory.name)
        path = directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["metadata"]["assignments"] = {"price": price, "cue": cue}
        path.write_text(json.dumps(manifest))
    bundle = load_trace_bundle(tmp_path)
    assert len(bundle["comparisons"]) == 4
    covered = set()
    for comparison in bundle["comparisons"]:
        assert comparison["kind"] == "factorial"
        left, right = comparison["control_index"], comparison["treatment_index"]
        covered.update((left, right))
        assignments = [bundle["episodes"][index]["manifest"]["metadata"]["assignments"] for index in (left, right)]
        assert sum(assignments[0][key] != assignments[1][key] for key in assignments[0]) == 1
    assert covered == {0, 1, 2, 3}


def test_single_viewer_marks_episode_without_a_comparison(tmp_path: Path) -> None:
    write_episode(tmp_path / "single", "authority")
    comparison = load_trace_bundle(tmp_path)["comparisons"][0]
    assert comparison["kind"] == "single"
    assert comparison["control_index"] == comparison["treatment_index"]
