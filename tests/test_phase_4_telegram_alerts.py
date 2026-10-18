from __future__ import annotations

from idxscreener.alerts.engine import evaluate_alerts
from idxscreener.notify.telegram import build_daily_report


def test_build_daily_report_includes_summary_and_alerts():
    message = build_daily_report(
        run_date="2026-09-20",
        top_candidates=[
            {"ticker": "BBCA", "caqs": 86.2, "score": "Kandidat Kuat"},
            {"ticker": "TLKM", "caqs": 82.4, "score": "Kandidat"},
        ],
        alerts=[
            {"id": "score_jump", "ticker": "BBCA", "severity": "medium", "message": "CAQS naik 10 poin"},
        ],
    )

    assert "2026-09-20" in message
    assert "BBCA" in message
    assert "CAQS naik 10 poin" in message


def test_evaluate_alerts_accepts_yaml_style_rules():
    alerts = [
        {
            "id": "score_jump",
            "category": "score_change",
            "scope": "watchlist",
            "condition": "delta(caqs, 5d) >= 8",
            "severity": "medium",
            "cooldown_hours": 48,
        },
        {
            "id": "golden_cross",
            "category": "signal",
            "scope": ["watchlist", "top_n:20"],
            "condition": "crosses_above(sma20, sma50) and volume_ratio > 1.2",
            "cooldown_hours": 72,
        },
    ]
    watchlist = [
        {"ticker": "BBCA", "caqs": 86.2, "previous_caqs": 75.0, "sma20": 101.0, "sma50": 99.0, "volume_ratio": 1.3},
        {"ticker": "BMRI", "caqs": 72.0, "previous_caqs": 70.0, "sma20": 100.0, "sma50": 110.0, "volume_ratio": 1.0},
    ]

    events = evaluate_alerts(alerts, watchlist)

    assert any(event["id"] == "score_jump" and event["ticker"] == "BBCA" for event in events)
    assert any(event["id"] == "golden_cross" and event["ticker"] == "BBCA" for event in events)
