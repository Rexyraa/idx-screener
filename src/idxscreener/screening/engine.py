from __future__ import annotations

from typing import Any


def _matches_filter(item: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
    metric = filter_spec.get("metric")
    if metric is None:
        return True
    value = item.get(metric)
    if value is None:
        return False

    op = str(filter_spec.get("op", "==")).strip().lower()
    target = filter_spec.get("value")

    if op == "<":
        return float(value) < float(target)
    if op == "<=":
        return float(value) <= float(target)
    if op == ">":
        return float(value) > float(target)
    if op == ">=":
        return float(value) >= float(target)
    if op == "==":
        return float(value) == float(target)
    if op == "!=":
        return float(value) != float(target)
    if op == "between":
        if not isinstance(target, (list, tuple)) or len(target) != 2:
            return False
        lower, upper = target
        return float(lower) <= float(value) <= float(upper)
    if op == "in":
        return value in target if isinstance(target, (list, tuple, set)) else value == target
    return False


def run_screen(
    screen_name: str,
    scores: list[dict[str, Any]],
    screen_spec: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a simple screen based on a score threshold or structured filter rules."""
    results: list[dict[str, Any]] = []
    filters = []
    if screen_spec is not None:
        filters = screen_spec.get("filters", [])

    for item in scores:
        ticker = item["ticker"]
        caqs = float(item.get("caqs", 0.0))
        passes = caqs >= 70
        if filters:
            passes = all(_matches_filter(item, spec) for spec in filters)

        if passes:
            result = {"ticker": ticker, "caqs": caqs, "pass": True}
            result.update({key: value for key, value in item.items() if key not in {"ticker", "caqs"}})
            results.append(result)

    return sorted(results, key=lambda x: float(x["caqs"]), reverse=True)
