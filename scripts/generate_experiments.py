import argparse
import re
import yaml
import pandas as pd
from pathlib import Path
from urllib.parse import urlparse
from tqdm import tqdm
from omegaconf import OmegaConf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--products",
        "--cases",
        default="https://raw.githubusercontent.com/PapayaResearch/abxlab/main/tasks/product_pairs-matched-ratings.csv"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--task", default="abxlab/abx_social_proof")
    parser.add_argument("--exp-dir", type=Path, default=Path("conf/experiment/generated/abxlab"))
    args = parser.parse_args()
    # Pandas reads the URL directly; no local CSV copy is created.
    frame = pd.read_csv(args.products, keep_default_na=False)
    if args.limit is not None:
        assert args.limit > 0
        frame = frame.head(args.limit)
    rows = frame.to_dict(orient="records")
    if {"product1_url", "product2_url"} <= set(frame.columns):
        rows = [
            {
                "id": "pair%03d" % (index,),
                "task.fixture.start_urls": [
                    "${environment.base_url}/" + urlparse(str(row[key]).removeprefix("${env.abxlab_url}")).path.lstrip("/")
                    for key in ("product1_url", "product2_url")
                ]
            }
            for index, row in enumerate(rows)
        ]
    assert rows and all("id" in row for row in rows), "CSV needs an id column and at least one case"
    ids = [row["id"] for row in rows]
    assert len(set(ids)) == len(ids), "Case IDs must be unique"
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]+", name) for name in ids), "Use letters, digits, underscores or hyphens in case IDs"
    paths = [args.exp_dir / (name + ".yaml") for name in ids]
    assert not any(path.exists() for path in paths), "Output exists; choose a fresh directory"
    args.exp_dir.mkdir(parents=True, exist_ok=True)
    for row, path in tqdm(list(zip(rows, paths, strict=True)), desc="Writing configs"):
        config = OmegaConf.create({
            "defaults": [{"override /task": args.task}, "_self_"],
            "experiment_id": row["id"]
        })
        for key, value in row.items():
            if key != "id" and value != "":
                parsed = yaml.safe_load(value) if isinstance(value, str) else value
                OmegaConf.update(config, key, parsed, force_add=True)
        path.write_text(
            "# @package _global_\n# Generated case overrides; shared settings stay in the task.\n" + OmegaConf.to_yaml(config),
            encoding="utf-8"
        )
    print("Wrote %d configs to %s" % (len(paths), args.exp_dir))


if __name__ == "__main__":
    main()
