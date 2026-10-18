from __future__ import annotations

import sqlite3
from pathlib import Path


INITIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    yf_symbol TEXT,
    name TEXT,
    sector_idxic TEXT,
    board TEXT,
    listing_date TEXT,
    delisting_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trading_day INTEGER NOT NULL CHECK (is_trading_day IN (0, 1)),
    session_note TEXT,
    source TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_params (
    param_key TEXT NOT NULL,
    value REAL NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (param_key, effective_from)
);

CREATE TABLE IF NOT EXISTS prices_daily (
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    instrument_id INTEGER,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adj_close REAL,
    volume INTEGER,
    value_idr REAL,
    source TEXT,
    fetched_at TEXT,
    quality_flag INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, trade_date),
    FOREIGN KEY (instrument_id) REFERENCES instruments (instrument_id)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    fundamental_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    instrument_id INTEGER,
    period_end TEXT NOT NULL,
    period_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    item TEXT NOT NULL,
    value REAL,
    currency_orig TEXT,
    publish_date TEXT,
    source TEXT,
    version TEXT NOT NULL,
    fetched_at TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, period_end, period_type, statement, item, version),
    FOREIGN KEY (instrument_id) REFERENCES instruments (instrument_id)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    instrument_id INTEGER,
    action_type TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    ratio REAL,
    amount REAL,
    source TEXT,
    version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, action_type, ex_date, version),
    FOREIGN KEY (instrument_id) REFERENCES instruments (instrument_id)
);

CREATE TABLE IF NOT EXISTS features_daily (
    feature_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    value REAL,
    feature_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, trade_date, feature_name, feature_version)
);

CREATE TABLE IF NOT EXISTS scores_daily (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    caqs REAL,
    s_f REAL,
    s_q REAL,
    s_t REAL,
    s_fm REAL,
    s_sr REAL,
    s_ac REAL,
    data_confidence REAL,
    label TEXT,
    rank_overall INTEGER,
    rank_sector INTEGER,
    gate_passed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, trade_date, model_version)
);

CREATE TABLE IF NOT EXISTS score_components (
    component_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    model_version TEXT NOT NULL,
    pillar TEXT NOT NULL,
    metric TEXT NOT NULL,
    raw_value REAL,
    percentile REAL,
    contribution REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, trade_date, model_version, pillar, metric)
);

CREATE TABLE IF NOT EXISTS job_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    run_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    started_at TEXT,
    finished_at TEXT,
    duration_s REAL,
    rows_processed INTEGER,
    source TEXT,
    error_code TEXT,
    error_summary TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (job_name, run_date, source)
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    dataset TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
    message TEXT NOT NULL,
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'unresolved' CHECK (status IN ('unresolved', 'resolved')),
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (ticker, dataset, issue_type, message, detected_at)
);

CREATE TABLE IF NOT EXISTS screen_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_id TEXT NOT NULL,
    run_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    rank INTEGER,
    pass_detail_json TEXT,
    entered INTEGER NOT NULL DEFAULT 0,
    exited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (screen_id, run_date, ticker)
);

CREATE TABLE IF NOT EXISTS notifications_log (
    notif_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    chat_id TEXT,
    sent_at TEXT NOT NULL,
    telegram_msg_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (kind, chat_id, sent_at)
);
"""

MIGRATIONS = [
    ("001_initial_schema", INITIAL_SCHEMA),
    ("002_web_tables", """
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weight_profiles (
    name TEXT PRIMARY KEY,
    weights_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""),
]


class MigrationManager:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def apply_all(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for name, sql in MIGRATIONS:
                applied = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?",
                    (name,),
                ).fetchone()
                if applied:
                    continue
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)",
                    (name,),
                )
            conn.commit()
