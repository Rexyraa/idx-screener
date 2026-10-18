from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Instrument:
    ticker: str
    name: str | None = None
    yf_symbol: str | None = None
    sector_idxic: str | None = None
    board: str | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    status: str = "active"


@dataclass
class JobRun:
    job_name: str
    status: str
    run_date: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    rows_processed: int | None = None
    source: str | None = None
    error_code: str | None = None
    error_summary: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class QualityIssue:
    ticker: str | None
    dataset: str
    issue_type: str
    severity: str
    message: str
    status: str = "unresolved"
    detected_at: str | None = None


@dataclass
class MarketParam:
    param_key: str
    value: float
    effective_from: date
    effective_to: date | None = None
    metadata: dict[str, Any] | None = None
