from pathlib import Path
from hydra import compose, initialize_config_dir
from run import archive_existing_output, run_condition
from harness.design import Condition


def test_scripted_run_writes_artifacts_with_simplified_settings(tmp_path: Path) -> None:
    config_root = Path(__file__).resolve().parents[1] / "conf"
    with initialize_config_dir(version_base="1.3", config_dir=str(config_root)):
        config = compose(
            config_name="config",
            overrides=[
                "task=examples/form_attention",
                "environment=browser_memory",
                "agent=scripted",
                "output_dir=%s" % (tmp_path,)
            ]
        )
    assert "observer" not in config and "logging" not in config
    _, evaluation, manifest = run_condition(
        config=config,
        condition=Condition(id="control", intervention_id="control"),
        condition_count=1,
        progress=False
    )
    assert manifest.schema_version == config.schema_version
    assert evaluation.outcomes
    assert (tmp_path / "trajectory.jsonl").exists()


def test_existing_output_is_archived_before_rerun(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text("{}\n", encoding="utf-8")

    archived_output = archive_existing_output(output_dir)

    assert archived_output == tmp_path / "run.previous-1"
    assert (archived_output / "manifest.json").exists()
    assert not output_dir.exists()
