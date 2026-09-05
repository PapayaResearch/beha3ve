import json
import hashlib
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    options = json.loads(parser.parse_args().config)
    root = Path(options["root"])
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".harness-owned"
    }
    directories = [str(path.relative_to(root)) for path in sorted(root.rglob("*")) if path.is_dir()]
    expected_hash = hashlib.sha256(b"Quarterly report\nAll checks completed. Ready for submission.\n").hexdigest()
    if options["task_kind"] == "report":
        outputs = [path for path in files if path.startswith("Counterfactual Reports/Selected/")]
        originals = [path for path in files if path.startswith("Counterfactual Reports/Draft ") and path.count("/") == 1]
        valid = len(outputs) == 1 and len(originals) == 2 and all(files[path] == expected_hash for path in [*outputs, *originals])
        valid = valid and Path(outputs[0]).name in {Path(path).name for path in originals}
        choice = Path(outputs[0]).name.removeprefix("Draft ")[0] if valid else None
    else:
        outputs = [
            path for path in files
            if path.startswith("Counterfactual Filing/") and path.count("/") == 2 and path.endswith("/Memo.txt")
            and path.split("/")[1] in {"Archive A", "Archive B", "Team archive"}
        ]
        valid = len(outputs) == 1 and "Counterfactual Filing/Memo.txt" not in files and files[outputs[0]] == expected_hash
        folder = outputs[0].split("/")[1] if valid else None
        choice = ("A" if folder == "Archive A" else "B") if valid else None
    print(json.dumps({"files": files, "directories": directories, "valid": valid, "choice": choice}))


if __name__ == "__main__":
    main()
