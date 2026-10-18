"""Tests for the prediction engine."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from idxscreener.prediction.engine import (
    _build_prediction_features,
    _ridge_fit_predict,
    _standardize,
    predict_next_day,
    walk_forward_predict,
)


def _make_prices(n: int = 120, ticker: str = "BBCA", seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for a GBM-like price path."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n)
    log_returns = rng.normal(0.0002, 0.015, n)
    prices = 7000.0 * np.exp(np.cumsum(log_returns))
    noise = rng.uniform(-0.005, 0.005, n)
    high = prices * (1 + abs(noise))
    low = prices * (1 - abs(noise))
    volume = rng.integers(1_000_000, 10_000_000, n).astype(float)
    return pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates,
        "open": prices * (1 + rng.normal(0, 0.003, n)),
        "high": high,
        "low": low,
        "close": prices,
        "adj_close": prices,
        "volume": volume,
    })


# ── feature building ────────────────────────────────────────────────────────

def test_build_features_shape():
    prices = _make_prices(120)
    features = _build_prediction_features(prices)
    assert len(features) > 60
    assert "ret_lag1" in features.columns
    assert "rsi_14" in features.columns
    assert "target" in features.columns


def test_build_features_no_lookahead():
    """Changing future prices must not alter past feature rows."""
    prices = _make_prices(100)
    features_before = _build_prediction_features(prices).copy()

    prices_modified = prices.copy()
    prices_modified.loc[prices_modified.index[-5:], "close"] *= 1.5
    prices_modified.loc[prices_modified.index[-5:], "adj_close"] *= 1.5
    features_after = _build_prediction_features(prices_modified)

    n = min(len(features_before), len(features_after)) - 10
    assert n > 0
    pd.testing.assert_series_equal(
        features_before["ret_lag1"].iloc[:n].reset_index(drop=True),
        features_after["ret_lag1"].iloc[:n].reset_index(drop=True),
        check_names=False,
    )


def test_features_no_nan_in_output():
    from idxscreener.prediction.engine import PREDICTION_FEATURES
    prices = _make_prices(150)
    features = _build_prediction_features(prices)
    for col in PREDICTION_FEATURES:
        assert features[col].isna().sum() == 0, f"{col} has NaN values"


# ── Ridge regression ────────────────────────────────────────────────────────

def test_ridge_recovers_linear():
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (200, 5))
    true_w = np.array([0.5, -0.3, 0.1, 0.0, 0.2])
    y = X @ true_w + rng.normal(0, 0.01, 200)
    X_s, mean, std = _standardize(X)
    y_pred = _ridge_fit_predict(X_s, y, X_s, alpha=0.001)
    # Should recover the signal well with tiny alpha
    corr = np.corrcoef(y, y_pred)[0, 1]
    assert corr > 0.99


def test_standardize_zero_mean_unit_std():
    rng = np.random.default_rng(1)
    X = rng.normal(5, 3, (100, 4))
    X_s, mean, std = _standardize(X)
    assert abs(X_s.mean()) < 1e-10
    assert abs(X_s.std() - 1.0) < 0.01


# ── predict_next_day ─────────────────────────────────────────────────────────

def test_predict_next_day_returns_result():
    prices = _make_prices(150)
    result = predict_next_day(prices, "BBCA")
    assert result.ticker == "BBCA"
    assert result.last_price > 0
    assert result.predicted_price > 0
    assert result.direction in {"up", "down", "flat"}
    assert 0.0 <= result.confidence <= 1.0


def test_predict_next_day_price_consistency():
    """predicted_price must equal last_price * exp(predicted_return)."""
    prices = _make_prices(150)
    result = predict_next_day(prices, "BBCA")
    expected = result.last_price * math.exp(result.predicted_return)
    assert abs(result.predicted_price - expected) < 0.1


def test_predict_next_day_insufficient_data_returns_flat():
    prices = _make_prices(20)  # too little
    result = predict_next_day(prices, "BBCA")
    assert result.direction == "flat"
    assert result.confidence == 0.0


def test_predict_multiple_tickers_independent():
    p1 = _make_prices(150, ticker="BBCA", seed=1)
    p2 = _make_prices(150, ticker="TLKM", seed=2)
    r1 = predict_next_day(p1, "BBCA")
    r2 = predict_next_day(p2, "TLKM")
    assert r1.ticker == "BBCA"
    assert r2.ticker == "TLKM"
    # Should differ since different price paths
    assert r1.predicted_return != r2.predicted_return


# ── walk_forward_predict ─────────────────────────────────────────────────────

def test_walk_forward_returns_result():
    prices = _make_prices(200)
    wf = walk_forward_predict(prices, "BBCA")
    assert wf.ticker == "BBCA"
    assert wf.n_predictions > 0
    assert 0.0 <= wf.direction_accuracy <= 1.0
    assert wf.price_rmse >= 0.0


def test_walk_forward_no_lookahead_contract():
    """Each prediction row must reference a date within the test window."""
    prices = _make_prices(200)
    wf = walk_forward_predict(prices, "BBCA", test_start="2025-07-01")
    for p in wf.predictions:
        assert p["date"] >= "2025-07-01", f"prediction {p['date']} leaks before test_start"


def test_walk_forward_direction_fields():
    prices = _make_prices(200)
    wf = walk_forward_predict(prices, "BBCA")
    for p in wf.predictions:
        assert p["direction"] in {"up", "down", "flat"}
        assert isinstance(p["correct"], bool)


def test_walk_forward_insufficient_data():
    prices = _make_prices(30)
    wf = walk_forward_predict(prices, "BBCA")
    assert wf.n_predictions == 0
