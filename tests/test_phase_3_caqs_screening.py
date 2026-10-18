from __future__ import annotations

from idxscreener.scoring.caqs import score_company
from idxscreener.screening.engine import run_screen


def test_score_company_uses_weighted_pillars_and_labels():
    result = score_company("BBCA", {"f_score": 0.8, "q_score": 0.7, "t_score": 0.9})

    assert abs(result.caqs - 80.0) < 1e-9
    assert result.label == "Kandidat Kuat"


def test_run_screen_applies_filters_from_screen_config():
    screen_spec = {
        "name": "quality_value_idx",
        "filters": [
            {"metric": "pbv", "op": "<", "value": 2.0},
            {"metric": "roe", "op": ">", "value": 12},
            {"metric": "der", "op": "<", "value": 1.5},
            {"metric": "rsi14", "op": "between", "value": [35, 70]},
        ],
    }
    scores = [
        {"ticker": "AA", "caqs": 82.0, "pbv": 1.8, "roe": 15.0, "der": 1.2, "rsi14": 55.0},
        {"ticker": "BB", "caqs": 74.0, "pbv": 2.5, "roe": 14.0, "der": 1.3, "rsi14": 52.0},
        {"ticker": "CC", "caqs": 68.0, "pbv": 1.9, "roe": 10.0, "der": 1.4, "rsi14": 40.0},
    ]

    results = run_screen("quality_value_idx", scores, screen_spec=screen_spec)

    assert [item["ticker"] for item in results] == ["AA"]
    assert results[0]["pass"] is True
