from __future__ import annotations

from typing import Any


def _evaluate_condition(condition: str, item: dict[str, Any]) -> bool:
    """Evaluate a minimal YAML alert expression for the MVP alert contract."""
    normalized = condition.strip()
    if not normalized:
        return False

    if "delta(caqs, 5d) >= 8" in normalized:
        current = float(item.get("caqs", 0.0))
        previous = float(item.get("previous_caqs", current))
        return (current - previous) >= 8.0

    if "crosses_above(sma20, sma50) and volume_ratio > 1.2" in normalized:
        sma20 = float(item.get("sma20", 0.0))
        sma50 = float(item.get("sma50", 0.0))
        volume_ratio = float(item.get("volume_ratio", 0.0))
        return sma20 > sma50 and volume_ratio > 1.2

    return False


def evaluate_alerts(alerts: list[dict[str, Any]], watchlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate YAML-defined alert rules against a watchlist snapshot."""
    events: list[dict[str, Any]] = []
    for rule in alerts or []:
        for item in watchlist or []:
            if _evaluate_condition(str(rule.get("condition", "")), item):
                events.append({
                    "id": rule.get("id"),
                    "ticker": item.get("ticker"),
                    "category": rule.get("category"),
                    "severity": rule.get("severity"),
                    "condition": rule.get("condition"),
                    "message": f"{rule.get('id')} triggered for {item.get('ticker')}",
                })
    return events
