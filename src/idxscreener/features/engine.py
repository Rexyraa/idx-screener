from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

FEATURE_VERSION = "mvp-v1"


def _safe_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_trade_date(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if value is None:
        return pd.Timestamp.utcnow().date().isoformat()
    return pd.to_datetime(value).date().isoformat()


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0 or (not math.isfinite(denominator)):
        return None
    value = numerator / denominator
    if not math.isfinite(value):
        return None
    return float(value)


def calculate_fundamental_features(
    ticker: str,
    price: float | None,
    fundamentals: dict[str, Any],
    calculation_date: str | pd.Timestamp,
) -> dict[str, float | None]:
    """Compute the MVP valuation, profitability, leverage, and growth features.

    All formulas use the PRD conventions and return None for invalid domains.
    """
    features: dict[str, float | None] = {}
    price_value = _safe_float(price)

    eps_ttm = _safe_float(fundamentals.get("eps_ttm"))
    bvps = _safe_float(fundamentals.get("bvps"))
    dps_12m = _safe_float(fundamentals.get("dps_12m"))
    net_income_ttm = _safe_float(fundamentals.get("net_income_ttm"))
    average_equity = _safe_float(fundamentals.get("average_equity"))
    gross_profit = _safe_float(fundamentals.get("gross_profit"))
    revenue = _safe_float(fundamentals.get("revenue"))
    operating_income = _safe_float(fundamentals.get("operating_income"))
    net_income = _safe_float(fundamentals.get("net_income"))
    current_assets = _safe_float(fundamentals.get("current_assets"))
    current_liabilities = _safe_float(fundamentals.get("current_liabilities"))
    quick_assets = _safe_float(fundamentals.get("quick_assets"))
    interest_expense = _safe_float(fundamentals.get("interest_expense"))
    ebit = _safe_float(fundamentals.get("ebit"))
    total_debt = _safe_float(fundamentals.get("total_debt"))
    total_assets = _safe_float(fundamentals.get("total_assets"))
    total_equity = _safe_float(fundamentals.get("total_equity"))
    total_liabilities = _safe_float(fundamentals.get("total_liabilities"))
    gross_margin = _safe_float(fundamentals.get("gross_margin"))
    operating_margin = _safe_float(fundamentals.get("operating_margin"))
    net_margin = _safe_float(fundamentals.get("net_margin"))
    earnings_yield_raw = _safe_float(fundamentals.get("earnings_yield"))

    features["per"] = None if eps_ttm is None or eps_ttm <= 0 or price_value is None else price_value / eps_ttm
    features["pbv"] = None if bvps is None or bvps <= 0 or price_value is None else price_value / bvps
    features["dividend_yield"] = None if dps_12m is None or price_value is None or price_value <= 0 else dps_12m / price_value
    features["earnings_yield"] = None
    if earnings_yield_raw is not None:
        features["earnings_yield"] = earnings_yield_raw
    elif eps_ttm is not None and price_value is not None and price_value > 0:
        features["earnings_yield"] = eps_ttm / price_value

    features["roe"] = None
    if net_income_ttm is not None and average_equity is not None and average_equity > 0:
        features["roe"] = net_income_ttm / average_equity

    features["roa"] = None
    if net_income is not None and total_assets is not None and total_assets > 0:
        features["roa"] = net_income / total_assets

    features["gross_margin"] = gross_margin
    features["operating_margin"] = operating_margin
    features["net_margin"] = net_margin

    features["current_ratio"] = _safe_divide(current_assets, current_liabilities)
    features["quick_ratio"] = _safe_divide(quick_assets, current_liabilities)

    features["interest_coverage"] = None
    if interest_expense is not None and interest_expense > 0 and ebit is not None:
        features["interest_coverage"] = ebit / interest_expense

    features["der"] = None
    if total_debt is not None and total_equity is not None and total_equity > 0:
        features["der"] = total_debt / total_equity

    features["revenue_growth_yoy"] = None
    if fundamentals.get("revenue_yoy") is not None:
        features["revenue_growth_yoy"] = _safe_float(fundamentals.get("revenue_yoy"))
    features["net_income_growth_yoy"] = None
    if fundamentals.get("net_income_yoy") is not None:
        features["net_income_growth_yoy"] = _safe_float(fundamentals.get("net_income_yoy"))
    features["eps_growth_yoy"] = None
    if fundamentals.get("eps_yoy") is not None:
        features["eps_growth_yoy"] = _safe_float(fundamentals.get("eps_yoy"))

    features["gross_profit_margin"] = _safe_divide(gross_profit, revenue) if revenue and revenue > 0 else None
    features["operating_profit_margin"] = _safe_divide(operating_income, revenue) if revenue and revenue > 0 else None
    features["net_profit_margin"] = _safe_divide(net_income, revenue) if revenue and revenue > 0 else None

    if total_liabilities is not None and total_assets is not None and total_assets > 0:
        features["debt_ratio"] = total_liabilities / total_assets
    else:
        features["debt_ratio"] = None

    return features


def _prepare_price_frame(price_df: pd.DataFrame) -> pd.DataFrame:
    if price_df.empty:
        return price_df.copy()

    frame = price_df.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
    for column in ["open", "high", "low", "close", "adj_close", "volume"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "close" not in frame.columns:
        frame["close"] = frame["adj_close"]
    return frame


def _sma(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    return float(series.tail(window).mean())


def _ema(series: pd.Series, span: int) -> float | None:
    if len(series) < span:
        return None
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(series: pd.Series, window: int = 14) -> float | None:
    if len(series) < window + 1:
        return None
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.rolling(window=window, min_periods=window).mean().iloc[-1]
    avg_loss = losses.rolling(window=window, min_periods=window).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi_value = 100.0 - (100.0 / (1.0 + rs))
    if not math.isfinite(rsi_value):
        return None
    return float(rsi_value)


def _roc(series: pd.Series, window: int) -> float | None:
    if len(series) < window + 1:
        return None
    current = series.iloc[-1]
    prior = series.iloc[-len(series) + window if len(series) > window else 0]
    if prior == 0:
        return None
    return float((current / prior) - 1.0)


def _macd_and_signal(series: pd.Series) -> tuple[float | None, float | None]:
    if len(series) < 26:
        return None, None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1]), float(signal.iloc[-1])


def _bbands(series: pd.Series, window: int = 20, std_dev: float = 2.0) -> tuple[float | None, float | None, float | None]:
    if len(series) < window:
        return None, None, None
    rolling = series.rolling(window=window)
    mean = rolling.mean().iloc[-1]
    std = rolling.std(ddof=0).iloc[-1]
    upper = mean + (std_dev * std)
    lower = mean - (std_dev * std)
    return float(mean), float(upper), float(lower)


def _adv(series: pd.Series, volume: pd.Series, window: int = 20) -> float | None:
    if len(series) < window:
        return None
    prices_times_volume = (series * volume)
    return float(prices_times_volume.tail(window).mean())


def _obv(close: pd.Series, volume: pd.Series) -> float | None:
    if close.empty or volume.empty:
        return None
    delta = close.diff().fillna(0)
    obv = (np.sign(delta) * volume).fillna(0).cumsum()
    return float(obv.iloc[-1])


def _distance_to_window(series: pd.Series, window: int = 252) -> tuple[float | None, float | None]:
    if series.empty:
        return None, None
    recent = series.tail(min(window, len(series)))
    high = float(recent.max())
    low = float(recent.min())
    last = float(series.iloc[-1])
    distance_high = None if high == 0 else ((last / high) - 1.0)
    distance_low = None if low == 0 else ((last / low) - 1.0)
    return distance_high, distance_low


def _drawdown(series: pd.Series) -> float | None:
    if series.empty:
        return None
    running_max = series.cummax()
    return float((series.iloc[-1] / running_max.iloc[-1]) - 1.0) if running_max.iloc[-1] else None


def calculate_technical_features(price_df: pd.DataFrame, calculation_date: str | pd.Timestamp) -> dict[str, float | None]:
    frame = _prepare_price_frame(price_df)
    if frame.empty:
        return {}

    ticker = str(frame["ticker"].iloc[0]).strip().upper()
    series = frame.sort_values("trade_date").copy()
    close = series["close"].astype(float)
    volume = series["volume"].astype(float)
    low = series["low"].astype(float)
    high = series["high"].astype(float)

    features: dict[str, float | None] = {
        "sma_5": _sma(close, 5),
        "sma_10": _sma(close, 10),
        "sma_20": _sma(close, 20),
        "sma_50": _sma(close, 50),
        "sma_100": _sma(close, 100),
        "sma_200": _sma(close, 200),
        "ema_20": _ema(close, 20),
        "rsi_14": _rsi(close, 14),
        "roc_5": _roc(close, 5),
        "roc_20": _roc(close, 20),
        "roc_60": _roc(close, 60),
        "roc_120": _roc(close, 120),
        "adv_20": _adv(close, volume, 20),
        "obv": _obv(close, volume),
        "distance_52w_high": _distance_to_window(close, 252)[0],
        "distance_52w_low": _distance_to_window(close, 252)[1],
        "drawdown": _drawdown(close),
    }

    macd_value, signal_value = _macd_and_signal(close)
    features["macd"] = macd_value
    features["macd_signal"] = signal_value
    bb_mean, bb_upper, bb_lower = _bbands(close, 20, 2.0)
    features["bb_mid_20"] = bb_mean
    features["bb_upper_20"] = bb_upper
    features["bb_lower_20"] = bb_lower

    features["golden_cross"] = None
    features["death_cross"] = None
    if "sma_20" in features and "sma_50" in features and features["sma_20"] is not None and features["sma_50"] is not None:
        features["golden_cross"] = 1.0 if features["sma_20"] > features["sma_50"] else 0.0
        features["death_cross"] = 1.0 if features["sma_20"] < features["sma_50"] else 0.0

    features["rsi_overbought"] = 1.0 if features["rsi_14"] is not None and features["rsi_14"] > 70 else 0.0
    features["rsi_oversold"] = 1.0 if features["rsi_14"] is not None and features["rsi_14"] < 30 else 0.0
    features["macd_cross"] = None
    if macd_value is not None and signal_value is not None:
        features["macd_cross"] = 1.0 if macd_value > signal_value else 0.0

    if "ticker" not in features:
        features["ticker"] = ticker
    features["ticker"] = ticker
    features["trade_date"] = _as_trade_date(calculation_date)
    return features


def _feature_record(ticker: str, trade_date: str, feature_name: str, value: Any, feature_version: str) -> dict[str, Any]:
    record = {
        "ticker": str(ticker).strip().upper(),
        "trade_date": str(trade_date),
        "feature_name": feature_name,
        "value": value,
        "feature_version": feature_version,
    }
    return record


def calculate_feature_rows(
    price_df: pd.DataFrame,
    fundamental_df: pd.DataFrame | None = None,
    calculation_date: str | pd.Timestamp | None = None,
    feature_version: str = FEATURE_VERSION,
) -> list[dict[str, Any]]:
    if price_df is None or price_df.empty:
        return []

    date_value = _as_trade_date(calculation_date or pd.Timestamp.utcnow())
    frame = _prepare_price_frame(price_df)
    rows: list[dict[str, Any]] = []

    for ticker, ticker_df in frame.groupby("ticker"):
        technical = calculate_technical_features(ticker_df, date_value)
        base = {
            "ticker": ticker,
            "trade_date": date_value,
            "feature_version": feature_version,
        }
        for name, value in technical.items():
            if name in {"ticker", "trade_date"}:
                continue
            rows.append(_feature_record(ticker, date_value, name, value, feature_version))

        if fundamental_df is not None and not fundamental_df.empty:
            match = fundamental_df[fundamental_df["ticker"].astype(str).str.upper() == ticker]
            if not match.empty:
                row = match.iloc[-1].to_dict()
                price_value = float(ticker_df["close"].iloc[-1])
                fundamentals = {
                    "eps_ttm": row.get("eps_ttm"),
                    "bvps": row.get("bvps"),
                    "dps_12m": row.get("dps_12m"),
                    "net_income_ttm": row.get("net_income_ttm"),
                    "average_equity": row.get("average_equity"),
                    "gross_profit": row.get("gross_profit"),
                    "revenue": row.get("revenue"),
                    "operating_income": row.get("operating_income"),
                    "net_income": row.get("net_income"),
                    "current_assets": row.get("current_assets"),
                    "current_liabilities": row.get("current_liabilities"),
                    "quick_assets": row.get("quick_assets"),
                    "interest_expense": row.get("interest_expense"),
                    "ebit": row.get("ebit"),
                    "total_debt": row.get("total_debt"),
                    "total_assets": row.get("total_assets"),
                    "total_equity": row.get("total_equity"),
                    "total_liabilities": row.get("total_liabilities"),
                    "gross_margin": row.get("gross_margin"),
                    "operating_margin": row.get("operating_margin"),
                    "net_margin": row.get("net_margin"),
                    "revenue_yoy": row.get("revenue_yoy"),
                    "net_income_yoy": row.get("net_income_yoy"),
                    "eps_yoy": row.get("eps_yoy"),
                }
                fundamental_features = calculate_fundamental_features(ticker, price_value, fundamentals, date_value)
                for name, value in fundamental_features.items():
                    rows.append(_feature_record(ticker, date_value, name, value, feature_version))

    return rows


def validate_feature_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate feature values and reject impossible domains."""
    issues: list[dict[str, Any]] = []
    for idx, row in enumerate(rows or []):
        ticker = str(row.get("ticker") or "").strip().upper()
        feature_name = str(row.get("feature_name") or "").strip()
        value = row.get("value")
        if not ticker:
            issues.append({"severity": "error", "message": f"Row {idx} has no ticker."})
            continue
        if not feature_name:
            issues.append({"severity": "error", "message": f"Row {idx} for {ticker} has no feature name."})
            continue
        if value is None:
            continue
        numeric = _safe_float(value)
        if numeric is None:
            issues.append({"severity": "error", "message": f"feature {feature_name} for {ticker} has a non-numeric value."})
            continue
        if feature_name.startswith("rsi") and not (0.0 <= numeric <= 100.0):
            issues.append({"severity": "error", "message": f"RSI feature {feature_name} for {ticker} is out of bounds: {numeric}."})
        if feature_name.startswith("per") and numeric < 0:
            issues.append({"severity": "error", "message": f"PER feature {feature_name} for {ticker} cannot be negative."})
        if feature_name.startswith("pbv") and numeric < 0:
            issues.append({"severity": "error", "message": f"PBV feature {feature_name} for {ticker} cannot be negative."})
        if feature_name.startswith("der") and numeric < 0:
            issues.append({"severity": "error", "message": f"DER feature {feature_name} for {ticker} cannot be negative."})

    return {"valid": not issues, "issues": issues, "row_count": len(rows or [])}
