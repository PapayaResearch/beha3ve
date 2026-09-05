import json
import itertools
import mimetypes
import webbrowser
from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from harness.serialization import canonical_json


def main():
    parser = ArgumentParser()
    parser.add_argument("run_dir", nargs="?", default="runs/run")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    bundle = load_trace_bundle(run_dir)
    TraceRequestHandler.bundle = bundle
    TraceRequestHandler.episode_dirs = [
        Path(episode["run_dir"])
        for episode in bundle["episodes"]
    ]
    server = ThreadingHTTPServer((args.host, args.port), TraceRequestHandler)
    url = "http://%s:%d" % (args.host, server.server_port)
    print("Trace Viewer: %s" % (url,))
    print("Run: %s" % (run_dir,))
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()


def load_trace_bundle(run_dir: Path) -> dict[str, Any]:
    episode_dirs = find_episode_dirs(run_dir)
    paired_effects_paths = sorted(run_dir.rglob("paired_effects.json"))
    episodes = [
        load_episode(episode_dir, index, run_dir)
        for index, episode_dir in enumerate(episode_dirs)
    ]
    return {
        "run_dir": str(run_dir),
        "episodes": episodes,
        "comparisons": build_comparisons(episodes),
        "paired_effects": {
            str(path.parent.relative_to(run_dir)): read_json(path)
            for path in paired_effects_paths
        }
    }


def build_comparisons(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for episode in episodes:
        manifest = episode["manifest"]
        experiment = manifest.get("metadata", {}).get("experiment_id")
        if experiment is None:
            parts = Path(episode["relative_dir"]).parts
            experiment = parts[0] if len(parts) > 1 else manifest.get("task_id", "run")
        pair_id = manifest.get("pair_id") or manifest.get("episode_id")
        groups.setdefault((experiment, pair_id), []).append(episode)
    comparisons = []
    for (experiment, pair_id), group in sorted(groups.items()):
        factorial = bool(group[0]["manifest"].get("metadata", {}).get("assignments"))
        if factorial:
            candidates = [
                (left, right)
                for left, right in itertools.combinations(group, 2)
                if sum(
                    level != right["manifest"]["metadata"]["assignments"][factor]
                    for factor, level in left["manifest"]["metadata"]["assignments"].items()
                ) == 1
            ]
        else:
            control = next(
                (episode for episode in group if episode["manifest"].get("condition_id") == "control"),
                group[0]
            )
            candidates = [(control, episode) for episode in group if episode is not control] or [(control, control)]
        for control, treatment in candidates:
            manifest = control["manifest"]
            comparisons.append(
                {
                    "id": "%s:%s:%d:%d" % (experiment, pair_id, control["index"], treatment["index"]),
                    "kind": "factorial" if factorial else "single" if control is treatment else "paired",
                    "experiment": experiment,
                    "pair_id": pair_id,
                    "task_id": manifest.get("task_id", "task"),
                    "seed": manifest.get("seed", 0),
                    "control_index": control["index"],
                    "treatment_index": treatment["index"],
                    "control_condition": control["manifest"].get("condition_id", "control"),
                    "treatment_condition": treatment["manifest"].get("condition_id", "treatment")
                }
            )
    return comparisons


def find_episode_dirs(run_dir: Path) -> list[Path]:
    if (run_dir / "manifest.json").exists():
        return [run_dir]
    episode_dirs = sorted(path.parent for path in run_dir.rglob("manifest.json"))
    assert episode_dirs, "No manifest.json found under %s" % (run_dir,)
    return episode_dirs


def load_episode(run_dir: Path, index: int, suite_dir: Path) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    episode_record = next(record for record in records if record["type"] == "episode")
    evaluation_record = next(record for record in records if record["type"] == "evaluation")
    return {
        "index": index,
        "run_dir": str(run_dir),
        "relative_dir": str(run_dir.relative_to(suite_dir)),
        "manifest": read_json(run_dir / "manifest.json"),
        "interventions": read_json(run_dir / "interventions.json"),
        "outcomes": read_json(run_dir / "outcomes.json"),
        "initial_snapshot": compact_snapshot(episode_record["initial_snapshot"]),
        "final_snapshot": compact_snapshot(evaluation_record["final_snapshot"]),
        "transitions": [
            compact_transition(record["transition"])
            for record in records
            if record["type"] == "transition"
        ]
    }


def compact_transition(value: dict[str, Any]) -> dict[str, Any]:
    transition = deepcopy(value)
    for observation_name in ["observation", "next_observation"]:
        observation = transition.get(observation_name)
        if observation is not None:
            observation["events"] = [
                {
                    "step": event.get("step"),
                    "kind": event.get("kind"),
                    "actor_id": event.get("actor_id"),
                    "metadata": event.get("metadata", {})
                }
                for event in observation.get("events", [])
            ]
    for snapshot_name in ["before_snapshot", "after_snapshot"]:
        snapshot = transition.get(snapshot_name)
        if snapshot is not None:
            transition[snapshot_name] = compact_snapshot(snapshot)
    compact_llm_messages(
        transition.get("action", {}).get("metadata", {}).get("llm", {})
    )
    return transition


def compact_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(value)
    snapshot.pop("observation", None)
    compact_last_action(snapshot.get("state", {}))
    return snapshot


def compact_last_action(state: dict[str, Any]) -> None:
    action = state.get("last_action")
    if isinstance(action, dict):
        state["last_action"] = {
            "kind": action.get("kind"),
            "arguments": action.get("arguments", {}),
            "text": action.get("text")
        }


def compact_llm_messages(llm: dict[str, Any]) -> None:
    if "observation_modalities" in llm:
        return
    messages = llm.get("messages", [])
    if len(messages) > 4:
        llm["viewer_omitted_messages"] = len(messages) - 4
        messages = [messages[0], *messages[-3:]]
        llm["messages"] = messages
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = truncate_viewer_text(content)
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    item["text"] = truncate_viewer_text(item.get("text", ""))


def truncate_viewer_text(value: str) -> str:
    limit = 8000
    if len(value) <= limit:
        return value
    return "%s\n\n[Viewer truncated %s characters; the trajectory JSONL retains the full request.]" % (
        value[:limit],
        len(value) - limit
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class TraceRequestHandler(BaseHTTPRequestHandler):
    bundle: dict[str, Any] = {}
    episode_dirs: list[Path] = []
    static_dir = Path(__file__).parent / "viewer"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/run":
            self.send_content(
                canonical_json(self.bundle).encode("utf-8"),
                "application/json"
            )
            return
        if path.startswith("/artifact/"):
            self.send_artifact(path)
            return
        static_name = "index.html" if path == "/" else path.removeprefix("/")
        static_path = (self.static_dir / static_name).resolve()
        assert static_path.is_relative_to(self.static_dir.resolve())
        assert static_path.exists(), "Unknown viewer path %s" % (path,)
        media_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        self.send_content(static_path.read_bytes(), media_type)

    def send_artifact(self, request_path: str) -> None:
        _, _, episode_index, artifact_name = request_path.split("/", maxsplit=3)
        episode_dir = self.episode_dirs[int(episode_index)]
        artifact_path = (episode_dir / unquote(artifact_name)).resolve()
        assert artifact_path.is_relative_to(episode_dir.resolve())
        media_type = mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream"
        self.send_content(artifact_path.read_bytes(), media_type)

    def send_content(self, content: bytes, media_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    main()
