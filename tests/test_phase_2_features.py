from __future__ import annotations

import math

import pandas as pd

from idxscreener.features.engine import (
    FEATURE_VERSION,
    calculate_feature_rows,
    calculate_fundamental_features,
    calculate_technical_features,
    validate_feature_rows,
)
from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def _make_price_frame() -> pd.DataFrame:
    values = [
        95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0,
        105.0, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0, 114.0,
        115.0, 116.0, 117.0, 118.0, 119.0, 120.0, 121.0, 122.0, 123.0, 124.0,
        125.0, 126.0, 127.0, 128.0, 129.0, 130.0, 131.0, 132.0, 133.0, 134.0,
        135.0, 136.0, 137.0, 138.0, 139.0, 140.0, 141.0, 142.0, 143.0, 144.0,
        145.0, 146.0, 147.0, 148.0, 149.0, 150.0, 151.0, 152.0, 153.0, 154.0,
        155.0, 156.0, 157.0, 158.0, 159.0, 160.0, 161.0, 162.0, 163.0, 164.0,
        165.0, 166.0, 167.0, 168.0, 169.0, 170.0, 171.0, 172.0, 173.0, 174.0,
        175.0, 176.0, 177.0, 178.0, 179.0, 180.0, 181.0, 182.0, 183.0, 184.0,
        185.0, 186.0, 187.0, 188.0, 189.0, 190.0, 191.0, 192.0, 193.0, 194.0,
        195.0, 196.0, 197.0, 198.0, 199.0, 200.0, 201.0, 202.0, 203.0, 204.0,
        205.0, 206.0, 207.0, 208.0, 209.0, 210.0, 211.0, 212.0, 213.0, 214.0,
        215.0, 216.0, 217.0, 218.0, 219.0, 220.0, 221.0, 222.0, 223.0, 224.0,
        225.0, 226.0, 227.0, 228.0, 229.0, 230.0, 231.0, 232.0, 233.0, 234.0,
        235.0, 236.0, 237.0, 238.0, 239.0, 240.0, 241.0, 242.0, 243.0, 244.0,
        245.0, 246.0, 247.0, 248.0, 249.0, 250.0, 251.0, 252.0, 253.0, 254.0,
        255.0, 256.0, 257.0, 258.0, 259.0, 260.0,
    ]
    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    df = pd.DataFrame({"ticker": "BBCA", "trade_date": dates, "open": values, "high": [v + 2 for v in values], "low": [v - 2 for v in values], "close": values, "adj_close": values, "volume": 1000 + pd.Series(range(len(values))) * 10})
    return df


def test_fundamental_features_compute_expected_values():
    features = calculate_fundamental_features(
        ticker="BBCA",
        price=7200.0,
        fundamentals={
            "eps_ttm": 1000.0,
            "bvps": 1500.0,
            "dps_12m": 250.0,
            "net_income_ttm": 30000.0,
            "average_equity": 200000.0,
            "gross_profit": 40000.0,
            "revenue": 100000.0,
            "operating_income": 25000.0,
            "net_income": 15000.0,
            "current_assets": 50000.0,
            "current_liabilities": 20000.0,
            "quick_assets": 30000.0,
            "interest_expense": 5000.0,
            "ebit": 22000.0,
            "total_debt": 10000.0,
            "total_assets": 50000.0,
            "total_equity": 20000.0,
            "total_liabilities": 15000.0,
            "gross_margin": 0.40,
            "operating_margin": 0.25,
            "net_margin": 0.15,
            "current_ratio": 2.5,
            "quick_ratio": 1.5,
            "interest_coverage": 4.4,
            "der": 0.5,
        },
        calculation_date="2026-09-21",
    )

    assert abs(features["per"] - 7.2) < 1e-9
    assert abs(features["pbv"] - 4.8) < 1e-9
    assert abs(features["dividend_yield"] - 0.034722222222222224) < 1e-9
    assert abs(features["earnings_yield"] - 0.1388888888888889) < 1e-9
    assert abs(features["roe"] - 0.15) < 1e-9
    assert abs(features["roa"] - 0.3) < 1e-9
    assert abs(features["gross_margin"] - 0.4) < 1e-9
    assert abs(features["operating_margin"] - 0.25) < 1e-9
    assert abs(features["net_margin"] - 0.15) < 1e-9
    assert abs(features["current_ratio"] - 2.5) < 1e-9
    assert abs(features["quick_ratio"] - 1.5) < 1e-9
    assert abs(features["interest_coverage"] - 4.4) < 1e-9
    assert abs(features["der"] - 0.5) < 1e-9


def test_technical_features_compute_and_validate():
    prices = _make_price_frame()
    features = calculate_technical_features(prices, calculation_date="2026-03-31")

    assert "sma_20" in features
    assert "ema_20" in features
    assert "rsi_14" in features
    assert "macd" in features
    assert "macd_signal" in features
    assert "bb_upper_20" in features
    assert "bb_lower_20" in features
    assert "adv_20" in features
    assert "obv" in features
    assert "distance_52w_high" in features
    assert "distance_52w_low" in features
    assert 0 <= features["rsi_14"] <= 100
    assert features["sma_20"] > 0
    assert features["ema_20"] > 0
    assert features["distance_52w_high"] is not None
    assert features["distance_52w_low"] is not None
    assert math.isfinite(features["distance_52w_high"])
    assert math.isfinite(features["distance_52w_low"])


def test_feature_rows_validate_and_persist_idempotently(tmp_path):
    prices = _make_price_frame()
    feature_rows = calculate_feature_rows(
        price_df=prices,
        fundamental_df=pd.DataFrame([
            {
                "ticker": "BBCA",
                "trade_date": "2026-03-31",
                "eps_ttm": 1000.0,
                "bvps": 1500.0,
                "dps_12m": 250.0,
                "net_income_ttm": 30000.0,
                "average_equity": 200000.0,
                "gross_profit": 40000.0,
                "revenue": 100000.0,
                "operating_income": 25000.0,
                "net_income": 15000.0,
                "current_assets": 50000.0,
                "current_liabilities": 20000.0,
                "quick_assets": 30000.0,
                "interest_expense": 5000.0,
                "ebit": 22000.0,
                "total_debt": 10000.0,
                "total_assets": 50000.0,
                "total_equity": 20000.0,
                "total_liabilities": 15000.0,
                "gross_margin": 0.40,
                "operating_margin": 0.25,
                "net_margin": 0.15,
                "current_ratio": 2.5,
                "quick_ratio": 1.5,
                "interest_coverage": 4.4,
                "der": 0.5,
            }
        ]),
        calculation_date="2026-03-31",
        feature_version=FEATURE_VERSION,
    )

    validation = validate_feature_rows(feature_rows)
    assert validation["valid"] is True
    db = StockDatabase(database_url=f"sqlite:///{tmp_path / 'features.db'}")
    db.initialize()
    repo = StockRepository(db)

    before = len(repo.list_features_for_ticker("BBCA", "2026-03-31"))
    repo.persist_feature_rows(feature_rows)
    after = len(repo.list_features_for_ticker("BBCA", "2026-03-31"))
    repo.persist_feature_rows(feature_rows)
    final = len(repo.list_features_for_ticker("BBCA", "2026-03-31"))

    assert before == 0
    assert after > 0
    assert final == after


def test_feature_validation_rejects_invalid_rsi():
    invalid = [{
        "ticker": "BBCA",
        "trade_date": "2026-09-21",
        "feature_name": "rsi_14",
        "value": 150.0,
        "feature_version": FEATURE_VERSION,
    }]
    result = validate_feature_rows(invalid)
    assert result["valid"] is False
    assert any("rsi_14" in issue["message"].lower() or "rsi" in issue["message"].lower() for issue in result["issues"])
