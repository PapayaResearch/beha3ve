import argparse
from pathlib import Path
from harness.replay import TrajectoryReplay
from harness.serialization import canonical_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?", default="runs/run")
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument("--before", action="store_true")
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    replay = TrajectoryReplay.from_event_log(
        path=run_dir / "trajectory.jsonl",
        progress=not args.no_progress
    )
    step = args.step if args.step is not None else replay.trajectory[-1].step
    view = (
        replay.pause_before_action(step)
        if args.before
        else replay.pause(step)
    )
    text = "%s\n" % (canonical_json(view),)
    if args.output is None:
        print(text, end="")
        return
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    print("Wrote replay view to %s" % (output_path,))


if __name__ == "__main__":
    main()
