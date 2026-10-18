"""Stock return prediction module.

Implements a walk-forward next-day return prediction using:
- Technical features from the existing feature engine (RSI, MACD, SMA distances, ROC, vol, OBV)
- Ridge regression via numpy least squares (no sklearn needed)
- Three baselines: random walk, historical mean, momentum

Inspired by https://github.com/haikalfr04/Stocks-Prediction method.
Not investment advice — for research only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


def generate_synthetic_prices(
    ticker: str,
    n: int = 500,
    start_price: float = 7000.0,
    mu: float = 0.0003,
    sigma: float = 0.015,
    seed: int | None = None,
) -> pd.DataFrame:
    """Generate a synthetic GBM price series for offline use / testing.

    ponytail: uses fixed mu/sigma; add GARCH volatility clustering when real data is available.
    """
    rng = np.random.default_rng(seed if seed is not None else hash(ticker) % (2**31))
    dates = pd.bdate_range(end="2026-09-30", periods=n)
    log_ret = rng.normal(mu - 0.5 * sigma ** 2, sigma, n)
    close = start_price * np.exp(np.cumsum(log_ret))
    noise = rng.uniform(0.002, 0.012, n)
    return pd.DataFrame({
        "ticker": ticker,
        "trade_date": dates,
        "open": close * (1 + rng.normal(0, 0.003, n)),
        "high": close * (1 + noise),
        "low": close * (1 - noise),
        "close": close,
        "adj_close": close,
        "volume": rng.integers(500_000, 8_000_000, n).astype(float),
    })


@dataclass
class PredictionResult:
    ticker: str
    predicted_return: float
    predicted_price: float
    last_price: float
    direction: str  # "up" | "down" | "flat"
    confidence: float  # 0-1, based on R² and signal strength
    features_used: list[str] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    ticker: str
    direction_accuracy: float
    r_squared: float
    price_rmse: float
    n_predictions: int
    predictions: list[dict[str, Any]] = field(default_factory=list)


# ── feature extraction per day ──────────────────────────────────────────────

PREDICTION_FEATURES = [
    "ret_lag1", "ret_lag2", "ret_lag3",
    "ret_mean_5", "ret_mean_10", "ret_mean_20",
    "vol_5", "vol_10", "vol_20",
    "vol_ratio_5_20",
    "dist_ma20", "dist_ma50",
    "rsi_14", "macd", "macd_hist",
    "hl_range", "close_in_range",
    "volume_z20",
]


def _build_prediction_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Build a row-per-day feature matrix from OHLCV data.

    All features use only information available at close of day t.
    Target is next-day log return: r_{t+1} = ln(P_{t+1}/P_t).
    """
    df = prices.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)

    close = df["close"].astype(float)
    adj = df.get("adj_close", close).astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    # Log returns from adjusted close
    log_ret = np.log(adj / adj.shift(1))

    features = pd.DataFrame(index=df.index)
    features["trade_date"] = df["trade_date"]
    features["close"] = close
    features["adj_close"] = adj

    # Lagged returns
    for lag in [1, 2, 3]:
        features[f"ret_lag{lag}"] = log_ret.shift(lag)

    # Rolling mean and vol of returns
    for w in [5, 10, 20]:
        features[f"ret_mean_{w}"] = log_ret.rolling(w).mean()
        features[f"vol_{w}"] = log_ret.rolling(w).std()

    # Short vs long vol ratio
    features["vol_ratio_5_20"] = features["vol_5"] / features["vol_20"].replace(0, np.nan)

    # Distance from MA
    features["dist_ma20"] = (close / close.rolling(20).mean() - 1.0)
    features["dist_ma50"] = (close / close.rolling(50).mean() - 1.0)

    # RSI 14 (Wilder)
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    features["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))
    features["rsi_14"] = features["rsi_14"].fillna(50.0)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    features["macd"] = macd
    features["macd_hist"] = macd - signal

    # High-low range and close position within it
    hl = (high - low) / close.replace(0, np.nan)
    features["hl_range"] = hl
    close_in_range = (close - low) / (high - low).replace(0, np.nan)
    features["close_in_range"] = close_in_range.fillna(0.5)

    # Volume z-score
    vol_mean20 = vol.rolling(20).mean()
    vol_std20 = vol.rolling(20).std().replace(0, np.nan)
    features["volume_z20"] = (vol - vol_mean20) / vol_std20
    features["volume_z20"] = features["volume_z20"].fillna(0.0)

    # Target: next-day log return
    features["target"] = log_ret.shift(-1)

    # Drop rows with NaN in any feature or target
    feature_cols = PREDICTION_FEATURES
    features = features.dropna(subset=feature_cols + ["target"]).reset_index(drop=True)

    return features


# ── Ridge regression via numpy (no sklearn) ──────────────────────────────────

def _ridge_fit_predict(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    alpha: float = 50.0,
) -> np.ndarray:
    """Ridge regression: w = (X'X + αI)^{-1} X'y, then predict X_test @ w."""
    n_features = X_train.shape[1]
    A = X_train.T @ X_train + alpha * np.eye(n_features)
    b = X_train.T @ y_train
    weights = np.linalg.solve(A, b)
    return X_test @ weights


def _standardize(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - mean) / std, mean, std


# ── walk-forward prediction ─────────────────────────────────────────────────

def walk_forward_predict(
    prices: pd.DataFrame,
    ticker: str,
    test_start: str | None = None,
    window_blocks: int = 21,  # ~1 month of trading days
    alpha: float = 50.0,
) -> WalkForwardResult:
    """Run walk-forward prediction and return accuracy metrics.

    Trains on all data before test period, predicts in blocks of
    `window_blocks` days, then retrains. Each prediction uses only
    past information — no look-ahead.
    """
    features = _build_prediction_features(prices)
    if len(features) < 60:
        return WalkForwardResult(
            ticker=ticker, direction_accuracy=0.0, r_squared=0.0,
            price_rmse=0.0, n_predictions=0,
        )

    if test_start is None:
        # Default: last 25% of data as test period
        split_idx = int(len(features) * 0.75)
    else:
        test_dt = pd.Timestamp(test_start)
        split_idx = features.index[features["trade_date"] >= test_dt][0] if (features["trade_date"] >= test_dt).any() else int(len(features) * 0.75)

    feature_cols = PREDICTION_FEATURES
    predictions: list[dict[str, Any]] = []
    actuals: list[float] = []
    preds: list[float] = []
    actual_prices: list[float] = []
    pred_prices: list[float] = []

    train_end = split_idx
    while train_end < len(features):
        block_end = min(train_end + window_blocks, len(features))

        train_data = features.iloc[:train_end]
        test_data = features.iloc[train_end:block_end]

        if len(train_data) < 30 or len(test_data) == 0:
            break

        X_train = train_data[feature_cols].values.astype(float)
        y_train = train_data["target"].values.astype(float)
        X_test = test_data[feature_cols].values.astype(float)

        X_train_s, mean, std = _standardize(X_train)
        X_test_s = (X_test - mean) / std

        y_pred = _ridge_fit_predict(X_train_s, y_train, X_test_s, alpha=alpha)

        for i, (_, row) in enumerate(test_data.iterrows()):
            pred_ret = float(y_pred[i])
            actual_ret = float(row["target"])
            last_price = float(row["adj_close"])
            pred_price = last_price * math.exp(pred_ret)
            actual_price = last_price * math.exp(actual_ret)

            pred_dir = "up" if pred_ret > 0.001 else "down" if pred_ret < -0.001 else "flat"
            actual_dir = "up" if actual_ret > 0.001 else "down" if actual_ret < -0.001 else "flat"
            correct = pred_dir == actual_dir

            predictions.append({
                "date": row["trade_date"].strftime("%Y-%m-%d"),
                "predicted_return": round(pred_ret, 6),
                "actual_return": round(actual_ret, 6),
                "predicted_price": round(pred_price, 2),
                "actual_price": round(actual_price, 2),
                "direction": pred_dir,
                "correct": correct,
            })
            preds.append(pred_ret)
            actuals.append(actual_ret)
            pred_prices.append(pred_price)
            actual_prices.append(actual_price)

        train_end = block_end

    if not predictions:
        return WalkForwardResult(
            ticker=ticker, direction_accuracy=0.0, r_squared=0.0,
            price_rmse=0.0, n_predictions=0,
        )

    # Metrics
    n = len(predictions)
    # Direction accuracy (exclude flat actual days)
    non_flat = [(p, a) for p, a in zip(preds, actuals) if abs(a) > 0.001]
    if non_flat:
        correct = sum(1 for p, a in non_flat if (p > 0) == (a > 0))
        direction_accuracy = correct / len(non_flat)
    else:
        direction_accuracy = 0.0

    # R² vs random walk (predict 0 return)
    ss_res = sum((a - p) ** 2 for a, p in zip(actuals, preds))
    ss_tot = sum(a ** 2 for a in actuals)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Price RMSE
    price_errors = [(ap - pp) ** 2 for ap, pp in zip(actual_prices, pred_prices)]
    price_rmse = math.sqrt(sum(price_errors) / len(price_errors)) if price_errors else 0.0

    return WalkForwardResult(
        ticker=ticker,
        direction_accuracy=round(direction_accuracy, 4),
        r_squared=round(r_squared, 4),
        price_rmse=round(price_rmse, 2),
        n_predictions=n,
        predictions=predictions,
    )


# ── single next-day forecast ────────────────────────────────────────────────

def predict_next_day(prices: pd.DataFrame, ticker: str, alpha: float = 50.0) -> PredictionResult:
    """Predict the next trading day's return and price.

    Trains on all available data, then forecasts one day ahead.
    """
    features = _build_prediction_features(prices)
    if len(features) < 30:
        return PredictionResult(
            ticker=ticker, predicted_return=0.0, predicted_price=0.0,
            last_price=0.0, direction="flat", confidence=0.0,
        )

    feature_cols = PREDICTION_FEATURES
    X = features[feature_cols].values.astype(float)
    y = features["target"].values.astype(float)

    X_s, mean, std = _standardize(X)
    weights = np.linalg.solve(X_s.T @ X_s + alpha * np.eye(len(feature_cols)), X_s.T @ y)

    # Latest feature row
    latest = features.iloc[-1]
    x_latest = (latest[feature_cols].values.astype(float) - mean) / std
    pred_ret = float(x_latest @ weights)
    last_price = float(latest["adj_close"])
    pred_price = last_price * math.exp(pred_ret)

    direction = "up" if pred_ret > 0.001 else "down" if pred_ret < -0.001 else "flat"

    # Confidence: based on in-sample R² (clipped to 0-1)
    y_pred_in = X_s @ weights
    ss_res = float(np.sum((y - y_pred_in) ** 2))
    ss_tot = float(np.sum(y ** 2))
    r2 = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
    confidence = min(r2, 1.0)

    return PredictionResult(
        ticker=ticker,
        predicted_return=round(pred_ret, 6),
        predicted_price=round(pred_price, 2),
        last_price=round(last_price, 2),
        direction=direction,
        confidence=round(confidence, 4),
        features_used=feature_cols,
    )
