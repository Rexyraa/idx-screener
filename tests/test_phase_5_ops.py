"""Phase 5: FR-OPS operational hardening tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from idxscreener.config.schema import (
    validate_alerts_config,
    validate_model_config,
    validate_screens_config,
)
from idxscreener.ops.logging import get_run_logger
from idxscreener.ops.monitor import check_freshness, check_heartbeat
from idxscreener.ops.pipeline import run_daily_pipeline
from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


# ── helpers ────────────────────────────────────────────────────────────────

def _db(tmp_path: Path) -> StockDatabase:
    db = StockDatabase(database_url=f"sqlite:///{tmp_path}/test.db")
    db.initialize()
    return db


# ── FR-CFG-02: config schema validation ───────────────────────────────────

def test_valid_model_config():
    raw = {
        "model_version": "caqs_1.0.0",
        "weights": {"F": 0.4, "Q": 0.3, "T": 0.3},
    }
    cfg = validate_model_config(raw)
    assert cfg.model_version == "caqs_1.0.0"
    assert abs(cfg.weights.F + cfg.weights.Q + cfg.weights.T - 1.0) < 1e-6


def test_invalid_weights_sum_raises():
    raw = {
        "model_version": "caqs_test",
        "weights": {"F": 0.5, "Q": 0.5, "T": 0.5},  # sum = 1.5
    }
    with pytest.raises(Exception, match="weights"):
        validate_model_config(raw)


def test_missing_model_version_raises():
    raw = {"weights": {"F": 0.4, "Q": 0.3, "T": 0.3}}
    with pytest.raises(Exception):
        validate_model_config(raw)


def test_valid_screens_config():
    raw = {"screens": [{"name": "quality_value", "universe": "idx80"}]}
    cfg = validate_screens_config(raw)
    assert cfg.screens[0].name == "quality_value"


def test_valid_alerts_config():
    raw = {"alerts": [{"id": "score_jump", "category": "score_change",
                        "scope": "watchlist", "condition": "delta(caqs,5d)>=8"}]}
    cfg = validate_alerts_config(raw)
    assert cfg.alerts[0].id == "score_jump"


def test_project_configs_all_valid():
    """Smoke test: the real config files must all pass validation."""
    from idxscreener.config.loader import get_config_path, load_yaml
    validate_model_config(load_yaml(get_config_path("model.yaml")))
    validate_screens_config(load_yaml(get_config_path("screens.yaml")))
    validate_alerts_config(load_yaml(get_config_path("alerts.yaml")))


# ── FR-OPS-06: structured logging ─────────────────────────────────────────

def test_logger_returns_logger():
    log = get_run_logger("test", run_id="abc-123")
    assert log is not None
    assert log.name.startswith("test.")


def test_logger_same_run_id_same_instance():
    log1 = get_run_logger("idxscreener", run_id="fixed-id-x")
    log2 = get_run_logger("idxscreener", run_id="fixed-id-x")
    assert log1 is log2


# ── FR-OPS-05: freshness check ─────────────────────────────────────────────

def test_freshness_no_data_is_unhealthy(tmp_path):
    db = _db(tmp_path)
    result = check_freshness(db, "2026-09-25")
    assert result["healthy"] is False
    assert result["latest_price_date"] is None
    assert len(result["issues"]) > 0


def test_freshness_fresh_price_is_healthy(tmp_path):
    db = _db(tmp_path)
    repo = StockRepository(db)
    repo.upsert_prices_daily("BBCA", date(2026, 9, 25), close=7250, source="test")
    result = check_freshness(db, "2026-09-25", max_price_age_days=1)
    assert result["healthy"] is True
    assert result["price_age_days"] == 0


def test_freshness_stale_price_is_unhealthy(tmp_path):
    db = _db(tmp_path)
    repo = StockRepository(db)
    repo.upsert_prices_daily("BBCA", date(2026, 9, 20), close=7100, source="test")
    result = check_freshness(db, "2026-09-25", max_price_age_days=1)
    assert result["healthy"] is False
    assert result["price_age_days"] == 5


# ── FR-OPS-04: heartbeat ──────────────────────────────────────────────────

def test_heartbeat_before_deadline_does_not_fire(tmp_path, monkeypatch):
    db = _db(tmp_path)
    # Patch now to before deadline (09:00 UTC, deadline is 10:00 UTC)
    fake_now = datetime(2026, 9, 25, 9, 0, 0, tzinfo=timezone.utc)
    import idxscreener.ops.monitor as mon
    monkeypatch.setattr(mon, "datetime", type("dt", (), {
        "now": staticmethod(lambda tz=None: fake_now),
        "fromisoformat": datetime.fromisoformat,
        "__init__": datetime.__init__,
    })())
    # Need the real datetime constructor for the deadline calc
    monkeypatch.setattr(mon, "datetime", _PatchedDatetime(fake_now))
    result = check_heartbeat(db, "2026-09-25", deadline_hour_utc=10)
    assert result["fired"] is False


def test_heartbeat_fires_when_no_report(tmp_path, monkeypatch):
    db = _db(tmp_path)
    fake_now = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone.utc)
    import idxscreener.ops.monitor as mon
    monkeypatch.setattr(mon, "datetime", _PatchedDatetime(fake_now))
    result = check_heartbeat(db, "2026-09-25", deadline_hour_utc=10)
    assert result["fired"] is True


def test_heartbeat_ok_when_report_logged(tmp_path, monkeypatch):
    db = _db(tmp_path)
    repo = StockRepository(db)
    repo.record_notification(
        kind="daily_report",
        status="sent",
        sent_at=datetime(2026, 9, 25, 9, 30, 0),
    )
    fake_now = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone.utc)
    import idxscreener.ops.monitor as mon
    monkeypatch.setattr(mon, "datetime", _PatchedDatetime(fake_now))
    result = check_heartbeat(db, "2026-09-25", deadline_hour_utc=10)
    assert result["fired"] is False
    assert result["sent_count"] == 1


# ── FR-OPS-01: pipeline timing + run_id ───────────────────────────────────

def test_pipeline_returns_run_id():
    result = run_daily_pipeline("2026-09-25", dry_run=True)
    assert "run_id" in result
    assert len(result["run_id"]) == 36  # uuid4


def test_pipeline_duration_recorded():
    result = run_daily_pipeline("2026-09-25", dry_run=True)
    assert "duration_s" in result
    assert result["duration_s"] >= 0


def test_pipeline_invalid_config_raises(monkeypatch):
    """FR-CFG-02: pipeline must fail-fast when config is invalid."""
    import idxscreener.ops.pipeline as pipe_mod
    monkeypatch.setattr(pipe_mod, "load_yaml", lambda _: {
        "model_version": "bad",
        "weights": {"F": 0.9, "Q": 0.9, "T": 0.9},  # sum = 2.7
    })
    with pytest.raises(ValueError, match="model.yaml invalid"):
        run_daily_pipeline("2026-09-25", dry_run=True)


# ── helper: datetime monkeypatch shim ─────────────────────────────────────

class _PatchedDatetime:
    """Minimal shim so monkeypatching datetime.now still allows datetime(...) calls."""
    def __init__(self, fake_now: datetime) -> None:
        self._now = fake_now

    def now(self, tz=None) -> datetime:
        return self._now

    def __call__(self, *args, **kwargs) -> datetime:
        return datetime(*args, **kwargs)

    def fromisoformat(self, s: str) -> datetime:  # type: ignore[override]
        return datetime.fromisoformat(s)

    @staticmethod
    def fromisoformat(s: str) -> datetime:
        return datetime.fromisoformat(s)
