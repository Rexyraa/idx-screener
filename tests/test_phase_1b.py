from datetime import date

import pandas as pd

from idxscreener.quality.validation import (
    QualitySummary,
    summarize_quality_issues,
    validate_ohlcv_rows,
    validate_universe_dataframe,
)
from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def test_validate_universe_accepts_valid_rows():
    df = pd.DataFrame(
        [
            {"ticker": "BBCA", "name": "Bank Central Asia", "sector": "Financials", "board": "Utama", "status": "active"},
            {"ticker": "TLKM", "name": "Telkom Indonesia", "sector": "Telecom", "board": "Utama", "status": "active"},
        ]
    )
    result = validate_universe_dataframe(df)
    assert result["valid"] is True
    assert result["issues"] == []


def test_validate_universe_rejects_duplicates_and_bad_ticker():
    df = pd.DataFrame(
        [
            {"ticker": "BBCA", "name": "Bank Central Asia", "sector": "Financials", "board": "Utama", "status": "active"},
            {"ticker": "BBCA", "name": "Duplicate", "sector": "Financials", "board": "Utama", "status": "active"},
            {"ticker": "bbca!", "name": "Bad", "sector": "Financials", "board": "Utama", "status": "active"},
        ]
    )
    result = validate_universe_dataframe(df)
    assert result["valid"] is False
    assert any("duplicate ticker" in issue["message"].lower() for issue in result["issues"])
    assert any("malformed ticker" in issue["message"].lower() for issue in result["issues"])


def test_validate_ohlcv_accepts_valid_bar():
    frame = pd.DataFrame(
        [{
            "ticker": "BBCA",
            "trade_date": "2026-09-21",
            "open": 7200.0,
            "high": 7300.0,
            "low": 7150.0,
            "close": 7250.0,
            "adj_close": 7250.0,
            "volume": 1000,
        }]
    )
    result = validate_ohlcv_rows(frame, trading_days={"2026-09-21"}, stale_threshold=3)
    assert result["valid"] is True
    assert result["issues"] == []


def test_validate_ohlcv_flags_invalid_price_and_negative_volume():
    frame = pd.DataFrame(
        [{
            "ticker": "BBCA",
            "trade_date": "2026-09-21",
            "open": 100.0,
            "high": 90.0,
            "low": 80.0,
            "close": 95.0,
            "adj_close": 95.0,
            "volume": -1,
        }]
    )
    result = validate_ohlcv_rows(frame, trading_days={"2026-09-21"}, stale_threshold=3)
    assert result["valid"] is False
    assert any("low <= open" in issue["message"].lower() or "volume" in issue["message"].lower() for issue in result["issues"])


def test_validate_ohlcv_detects_missing_trading_day_and_stale_price():
    frame = pd.DataFrame(
        [
            {"ticker": "BBCA", "trade_date": "2026-09-20", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "adj_close": 100.0, "volume": 1000},
            {"ticker": "BBCA", "trade_date": "2026-09-21", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "adj_close": 100.0, "volume": 1000},
            {"ticker": "BBCA", "trade_date": "2026-09-22", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "adj_close": 100.0, "volume": 1000},
        ]
    )
    result = validate_ohlcv_rows(frame, trading_days={"2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23"}, stale_threshold=2)
    assert result["valid"] is False
    assert any("missing trading day" in issue["message"].lower() for issue in result["issues"])
    assert any("stale price" in issue["message"].lower() for issue in result["issues"])


def test_quality_summary_counts_issues():
    issues = [
        {"severity": "error", "issue_type": "invalid_ohlc"},
        {"severity": "warn", "issue_type": "stale_price"},
        {"severity": "warn", "issue_type": "missing_bar"},
        {"severity": "info", "issue_type": "metadata"},
    ]
    summary = summarize_quality_issues(issues)
    assert summary["errors"] == 1
    assert summary["warnings"] == 2
    assert summary["info"] == 1


def test_quality_issues_are_recorded_and_error_rows_are_quarantined(tmp_path):
    db = StockDatabase(database_url=f"sqlite:///{tmp_path / 'quality.db'}")
    db.initialize()
    repo = StockRepository(db)

    repo.record_data_quality_issue("BBCA", "prices_daily", "invalid_ohlc", "error", "low > open", detected_at=date(2026, 9, 21))
    repo.record_data_quality_issue("BBCA", "prices_daily", "stale_price", "warn", "repeated close", detected_at=date(2026, 9, 21))

    issues = repo.list_data_quality_issues()
    assert len(issues) == 2
    assert issues[0]["severity"] in {"error", "warn"}
    summary = QualitySummary.from_issues(issues)
    assert summary.errors >= 1
    assert summary.warnings >= 1
