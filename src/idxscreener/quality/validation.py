from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd


def _issue(
    severity: str,
    issue_type: str,
    message: str,
    *,
    ticker: str | None = None,
    row: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "severity": severity,
        "issue_type": issue_type,
        "message": message,
    }
    if ticker is not None:
        issue["ticker"] = ticker
    if row is not None:
        issue["row"] = row
    for key, value in extra.items():
        if value is not None:
            issue[key] = value
    return issue


def validate_universe_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    """Validate a canonical IDX universe CSV payload."""
    issues: list[dict[str, Any]] = []

    if df is None or df.empty:
        return {
            "valid": False,
            "issues": [_issue("error", "empty_universe", "Universe dataframe is empty.")],
            "row_count": 0,
        }

    required_columns = ["ticker", "name", "sector", "board", "status"]
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        issues.append(
            _issue(
                "error",
                "missing_columns",
                f"Universe is missing required columns: {', '.join(missing)}.",
            )
        )

    normalized = df.copy()
    normalized["ticker"] = normalized.get("ticker", pd.Series(dtype="object")).fillna("").astype(str).str.strip().str.upper()
    seen: set[str] = set()

    for row_index, row in normalized.iterrows():
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            issues.append(
                _issue("error", "missing_ticker", "Universe row is missing a ticker.", row=int(row_index))
            )
            continue
        if not re.fullmatch(r"[A-Z0-9]+", ticker):
            issues.append(
                _issue(
                    "error",
                    "malformed_ticker",
                    f"Malformed ticker '{ticker}' in universe row {row_index}.",
                    ticker=ticker,
                    row=int(row_index),
                )
            )
        if ticker in seen:
            issues.append(
                _issue(
                    "error",
                    "duplicate_ticker",
                    f"Duplicate ticker '{ticker}' found in the universe.",
                    ticker=ticker,
                    row=int(row_index),
                )
            )
        else:
            seen.add(ticker)

    return {
        "valid": not issues,
        "issues": issues,
        "row_count": len(df),
    }


def _coerce_numeric(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return pd.to_datetime(text).date().isoformat()
        except (TypeError, ValueError):
            return text
    try:
        return pd.to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def validate_ohlcv_rows(
    df: pd.DataFrame,
    trading_days: Iterable[str] | set[str] | None = None,
    stale_threshold: int = 3,
) -> dict[str, Any]:
    """Validate OHLCV rows and detect stale or missing recent bars."""
    issues: list[dict[str, Any]] = []

    if df is None or df.empty:
        return {
            "valid": False,
            "issues": [_issue("error", "empty_ohlcv", "No OHLCV rows available for validation.")],
            "row_count": 0,
        }

    required_columns = ["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        issues.append(
            _issue(
                "error",
                "missing_ohlcv_columns",
                f"OHLCV payload is missing required columns: {', '.join(missing_columns)}.",
            )
        )
        return {"valid": False, "issues": issues, "row_count": len(df)}

    trades_by_ticker: dict[str, set[str]] = {}
    expected_days = {str(day).strip() for day in trading_days or []}

    for row_index, row in df.iterrows():
        ticker = str(row.get("ticker") or "").strip().upper()
        trade_date = _iso_date(row.get("trade_date"))
        if not ticker:
            issues.append(_issue("error", "missing_ticker", "OHLCV row is missing a ticker.", row=int(row_index)))
            continue
        if not trade_date:
            issues.append(
                _issue("error", "missing_trade_date", f"OHLCV row {row_index} is missing a valid trade_date.", ticker=ticker, row=int(row_index))
            )
            continue

        trades_by_ticker.setdefault(ticker, set()).add(trade_date)

        values = {
            "open": _coerce_numeric(row.get("open")),
            "high": _coerce_numeric(row.get("high")),
            "low": _coerce_numeric(row.get("low")),
            "close": _coerce_numeric(row.get("close")),
            "adj_close": _coerce_numeric(row.get("adj_close")),
            "volume": _coerce_numeric(row.get("volume")),
        }

        if any(value is None for value in values.values()):
            issues.append(
                _issue(
                    "error",
                    "invalid_numeric_price",
                    f"Row {row_index} for {ticker} contains invalid OHLCV values.",
                    ticker=ticker,
                    row=int(row_index),
                )
            )
            continue

        open_value, high_value, low_value, close_value, adj_close_value, volume_value = (
            values["open"],
            values["high"],
            values["low"],
            values["close"],
            values["adj_close"],
            values["volume"],
        )

        if low_value <= 0 or open_value <= 0 or high_value <= 0 or close_value <= 0 or adj_close_value <= 0:
            issues.append(
                _issue(
                    "error",
                    "invalid_price",
                    f"Row {row_index} for {ticker} has non-positive OHLC values.",
                    ticker=ticker,
                    row=int(row_index),
                )
            )

        if low_value > open_value or low_value > close_value or high_value < open_value or high_value < close_value:
            issues.append(
                _issue(
                    "error",
                    "invalid_ohlc",
                    f"Row {row_index} for {ticker} violates OHLC constraints: low <= open/close <= high.",
                    ticker=ticker,
                    row=int(row_index),
                )
            )

        if volume_value < 0:
            issues.append(
                _issue(
                    "error",
                    "negative_volume",
                    f"Row {row_index} for {ticker} has negative volume ({volume_value}).",
                    ticker=ticker,
                    row=int(row_index),
                )
            )

    if expected_days:
        sorted_days = sorted(expected_days)
        latest_expected = max(sorted_days)
        for ticker, observed_days in trades_by_ticker.items():
            missing_days = [day for day in sorted_days if day not in observed_days]
            for day in missing_days:
                if latest_expected and (pd.Timestamp(latest_expected) - pd.Timestamp(day)).days <= stale_threshold:
                    issues.append(
                        _issue(
                            "warn",
                            "missing_trading_day",
                            f"Missing trading day {day} for {ticker} in the recent window.",
                            ticker=ticker,
                            trade_date=day,
                        )
                    )
                    issues.append(
                        _issue(
                            "warn",
                            "stale_price",
                            f"Stale price data for {ticker}: recent trading day {day} is missing.",
                            ticker=ticker,
                            trade_date=day,
                        )
                    )

    return {
        "valid": not issues,
        "issues": issues,
        "row_count": len(df),
    }


@dataclass
class QualitySummary:
    errors: int = 0
    warnings: int = 0
    info: int = 0

    @classmethod
    def from_issues(cls, issues: list[dict[str, Any]] | Any) -> "QualitySummary":
        summary = cls()
        for issue in issues or []:
            severity = str(issue.get("severity", "info")).lower()
            if severity == "error":
                summary.errors += 1
            elif severity == "warn":
                summary.warnings += 1
            elif severity == "info":
                summary.info += 1
        return summary


def summarize_quality_issues(issues: list[dict[str, Any]] | Any) -> dict[str, int]:
    summary = QualitySummary.from_issues(issues)
    return {
        "errors": summary.errors,
        "warnings": summary.warnings,
        "info": summary.info,
    }
