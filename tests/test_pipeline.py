from pathlib import Path

from idxscreener.config.loader import load_yaml
from idxscreener.ops.pipeline import run_daily_pipeline


def test_load_yaml_model():
    config = load_yaml(Path(__file__).resolve().parents[1] / "configs" / "model.yaml")
    assert "model_version" in config
    assert "weights" in config


def test_daily_pipeline_dry_run():
    result = run_daily_pipeline("2026-09-20", dry_run=True)
    assert result["status"] in {"success", "degraded"}
    assert result["summary"]["top_candidates"]
