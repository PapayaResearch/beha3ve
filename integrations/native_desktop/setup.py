import json
import time
import shutil
import argparse
import subprocess
import pyautogui
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    options = json.loads(parser.parse_args().config)
    root = Path(options["root"])
    assert root.name == "Counterfactual"
    windows = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, check=True).stdout.splitlines()
    for line in windows:
        fields = line.split(maxsplit=3)
        if len(fields) == 4 and "Counterfactual " in fields[3]:
            subprocess.run(["wmctrl", "-ic", fields[0]], check=True)
    time.sleep(0.5)
    if root.exists():
        assert (root / ".harness-owned").read_text() == "native-desktop-pairs-v1"
        shutil.rmtree(root)
    root.mkdir()
    (root / ".harness-owned").write_text("native-desktop-pairs-v1")
    content = "Quarterly report\nAll checks completed. Ready for submission.\n"
    if options["task_kind"] == "report":
        directory = root / "Counterfactual Reports"
        directory.mkdir()
        (directory / "Selected").mkdir()
        (directory / "Draft A.txt").write_text(content)
        target_name = "Draft B - reviewed.txt" if options["nudge"] == "authority" else "Draft B.txt"
        target = directory / target_name
        target.write_text(content)
    else:
        assert options["task_kind"] == "archive"
        directory = root / "Counterfactual Filing"
        directory.mkdir()
        (directory / "Archive A").mkdir()
        target_name = "Team archive" if options["nudge"] == "social" else "Archive B"
        target = directory / target_name
        target.mkdir()
        (directory / "Memo.txt").write_text(content)
    subprocess.Popen(["nautilus", "--new-window", str(directory)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    windows = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, check=True).stdout.splitlines()
    matches = [line.split(maxsplit=3)[0] for line in windows if line.split(maxsplit=3)[-1] == directory.name]
    assert len(matches) == 1, windows
    window_id = matches[0]
    subprocess.run(["wmctrl", "-ir", window_id, "-b", "add,maximized_vert,maximized_horz"], check=True)
    subprocess.run(["wmctrl", "-ia", window_id], check=True)
    time.sleep(0.5)
    pyautogui.hotkey("ctrl", "2")
    time.sleep(0.5)
    pyautogui.click(1500, 850)
    if options["nudge"] == "default":
        subprocess.run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.freedesktop.FileManager1",
                "--object-path",
                "/org/freedesktop/FileManager1",
                "--method",
                "org.freedesktop.FileManager1.ShowItems",
                json.dumps([target.as_uri()]),
                ""
            ],
            capture_output=True,
            check=True
        )
    time.sleep(1)
    active = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, check=True).stdout
    assert int(active.split()[-1], 16) == int(window_id, 16), active


if __name__ == "__main__":
    main()
