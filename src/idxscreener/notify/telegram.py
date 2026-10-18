from __future__ import annotations

from typing import Any


def build_daily_report(
    run_date: str,
    top_candidates: list[dict[str, Any]],
    alerts: list[dict[str, Any]] | None = None,
) -> str:
    """Build a compact daily report message for Telegram or CLI output."""
    lines = [
        f"Daily Stock Screener Report — {run_date}",
        "Top candidates:",
    ]

    if not top_candidates:
        lines.append("- none")
    else:
        for item in top_candidates:
            ticker = item.get("ticker", "N/A")
            caqs = item.get("caqs", 0)
            score = item.get("score", "")
            lines.append(f"- {ticker}: CAQS {caqs} ({score})")

    lines.append("Alerts:")
    if not alerts:
        lines.append("- none")
    else:
        for alert in alerts:
            ticker = alert.get("ticker", "Market")
            severity = alert.get("severity", "info")
            message = alert.get("message", "alert")
            lines.append(f"- {ticker} [{severity}] {message}")

    return "\n".join(lines)
