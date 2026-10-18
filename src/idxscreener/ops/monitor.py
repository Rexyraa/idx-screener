"""FR-OPS-04/05: heartbeat and data-freshness checks.

Deterministic, no network I/O. Reads from the database only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def check_freshness(
    db: StockDatabase,
    run_date: str | date,
    max_price_age_days: int = 1,
    max_fundamental_quarters: int = 2,
) -> dict[str, Any]:
    """FR-OPS-05: check data freshness against thresholds.

    Returns a summary dict; 'healthy' is False if any threshold is breached.
    """
    repo = StockRepository(db)
    if isinstance(run_date, str):
        run_dt = date.fromisoformat(run_date)
    else:
        run_dt = run_date

    issues: list[str] = []

    # Latest price bar across all tickers
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(trade_date) AS latest FROM prices_daily"
        ).fetchone()
        latest_price = row["latest"] if row else None

    if latest_price is None:
        issues.append("no price data found")
        price_age_days = None
    else:
        latest_dt = date.fromisoformat(latest_price)
        price_age_days = (run_dt - latest_dt).days
        if price_age_days > max_price_age_days:
            issues.append(
                f"price data stale: latest={latest_price}, age={price_age_days}d > {max_price_age_days}d"
            )

    # Latest fundamental
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(period_end) AS latest FROM fundamentals"
        ).fetchone()
        latest_fund = row["latest"] if row else None

    if latest_fund is not None:
        latest_fund_dt = date.fromisoformat(latest_fund)
        fund_age_quarters = (run_dt - latest_fund_dt).days / 91.25
        if fund_age_quarters > max_fundamental_quarters:
            issues.append(
                f"fundamental data stale: latest={latest_fund}, age={fund_age_quarters:.1f}q > {max_fundamental_quarters}q"
            )
    else:
        fund_age_quarters = None

    return {
        "healthy": len(issues) == 0,
        "run_date": run_dt.isoformat(),
        "latest_price_date": latest_price,
        "price_age_days": price_age_days,
        "latest_fundamental_date": latest_fund,
        "fund_age_quarters": fund_age_quarters,
        "issues": issues,
    }


def check_heartbeat(
    db: StockDatabase,
    run_date: str | date,
    deadline_hour_utc: int = 10,  # 17:00 WIB = 10:00 UTC
) -> dict[str, Any]:
    """FR-OPS-04: dead-man's switch — was the daily report sent on time?

    Returns {'fired': True} if the deadline has passed without a report.
    """
    repo = StockRepository(db)
    if isinstance(run_date, str):
        run_dt = date.fromisoformat(run_date)
    else:
        run_dt = run_date

    now_utc = datetime.now(timezone.utc)
    deadline = datetime(run_dt.year, run_dt.month, run_dt.day, deadline_hour_utc, 0, 0, tzinfo=timezone.utc)
    past_deadline = now_utc >= deadline

    if not past_deadline:
        return {"fired": False, "reason": "deadline not yet reached", "deadline_utc": deadline.isoformat()}

    # Check notifications_log for a daily_report sent on run_date
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM notifications_log
            WHERE kind = 'daily_report'
              AND sent_at >= ?
              AND sent_at < ?
              AND status = 'sent'
            """,
            (run_dt.isoformat(), (run_dt + timedelta(days=1)).isoformat()),
        ).fetchone()
        sent_count = row["cnt"] if row else 0

    fired = sent_count == 0
    return {
        "fired": fired,
        "run_date": run_dt.isoformat(),
        "deadline_utc": deadline.isoformat(),
        "sent_count": sent_count,
        "reason": "report not sent before deadline" if fired else "report confirmed sent",
    }
