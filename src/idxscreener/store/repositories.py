from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from .database import StockDatabase


class StockRepository:
    def __init__(self, database: StockDatabase):
        self.database = database

    def _normalize_date(self, value: date | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return value

    def _json_dumps(self, payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        return json.dumps(payload)

    def _json_loads(self, value: str | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return json.loads(value)

    def count_instruments(self) -> int:
        with self.database.get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM instruments").fetchone()
            return int(row["count"]) if row else 0

    def upsert_instrument(
        self,
        ticker: str,
        name: str | None = None,
        yf_symbol: str | None = None,
        sector_idxic: str | None = None,
        board: str | None = None,
        listing_date: date | str | None = None,
        delisting_date: date | str | None = None,
        status: str = "active",
    ) -> int:
        with self.database.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO instruments (
                    ticker, yf_symbol, name, sector_idxic, board,
                    listing_date, delisting_date, status, valid_from, valid_to
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    yf_symbol = excluded.yf_symbol,
                    name = excluded.name,
                    sector_idxic = excluded.sector_idxic,
                    board = excluded.board,
                    listing_date = excluded.listing_date,
                    delisting_date = excluded.delisting_date,
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    ticker,
                    yf_symbol,
                    name,
                    sector_idxic,
                    board,
                    self._normalize_date(listing_date),
                    self._normalize_date(delisting_date),
                    status,
                    self._normalize_date(listing_date),
                    None,
                ),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute("SELECT instrument_id FROM instruments WHERE ticker = ?", (ticker,)).fetchone()
            return int(row["instrument_id"]) if row else 0

    def get_instrument_id(self, ticker: str) -> int | None:
        with self.database.get_connection() as conn:
            row = conn.execute("SELECT instrument_id FROM instruments WHERE ticker = ?", (ticker,)).fetchone()
            return int(row["instrument_id"]) if row else None

    def upsert_trading_calendar(
        self,
        trade_date: date | str,
        is_trading_day: bool,
        session_note: str | None = None,
        source: str = "manual",
    ) -> None:
        date_text = self._normalize_date(trade_date)
        with self.database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO trading_calendar (trade_date, is_trading_day, session_note, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    is_trading_day = excluded.is_trading_day,
                    session_note = excluded.session_note,
                    source = excluded.source
                """,
                (date_text, 1 if is_trading_day else 0, session_note, source),
            )
            conn.commit()

    def is_trading_day(self, trade_date: date | str) -> bool:
        date_text = self._normalize_date(trade_date)
        with self.database.get_connection() as conn:
            row = conn.execute(
                "SELECT is_trading_day FROM trading_calendar WHERE trade_date = ?",
                (date_text,),
            ).fetchone()
            return bool(row["is_trading_day"]) if row else False

    def get_previous_trading_day(self, trade_date: date | str) -> str | None:
        date_text = self._normalize_date(trade_date)
        with self.database.get_connection() as conn:
            row = conn.execute(
                "SELECT trade_date FROM trading_calendar WHERE is_trading_day = 1 AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
                (date_text,),
            ).fetchone()
            return row["trade_date"] if row else None

    def get_next_trading_day(self, trade_date: date | str) -> str | None:
        date_text = self._normalize_date(trade_date)
        with self.database.get_connection() as conn:
            row = conn.execute(
                "SELECT trade_date FROM trading_calendar WHERE is_trading_day = 1 AND trade_date > ? ORDER BY trade_date ASC LIMIT 1",
                (date_text,),
            ).fetchone()
            return row["trade_date"] if row else None

    def upsert_market_param(
        self,
        param_key: str,
        value: float,
        effective_from: date | str,
        effective_to: date | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO market_params (param_key, value, effective_from, effective_to, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(param_key, effective_from) DO UPDATE SET
                    value = excluded.value,
                    effective_to = excluded.effective_to,
                    metadata = excluded.metadata
                """,
                (
                    param_key,
                    float(value),
                    self._normalize_date(effective_from),
                    self._normalize_date(effective_to),
                    self._json_dumps(metadata),
                ),
            )
            conn.commit()

    def get_market_param(self, param_key: str, as_of: date | str) -> dict[str, Any] | None:
        as_of_text = self._normalize_date(as_of)
        with self.database.get_connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM market_params
                WHERE param_key = ? AND effective_from <= ?
                  AND (effective_to IS NULL OR ? < effective_to)
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (param_key, as_of_text, as_of_text),
            ).fetchone()
            if not row:
                return None
            payload = dict(row)
            payload["metadata"] = self._json_loads(payload.get("metadata"))
            return payload

    def upsert_prices_daily(
        self,
        ticker: str,
        trade_date: date | str,
        open: float | None = None,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        adj_close: float | None = None,
        volume: int | None = None,
        value_idr: float | None = None,
        source: str | None = None,
        fetched_at: date | str | None = None,
        quality_flag: int = 0,
    ) -> None:
        with self.database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO prices_daily (
                    ticker, trade_date, open, high, low, close, adj_close, volume, value_idr,
                    source, fetched_at, quality_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, trade_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    adj_close = excluded.adj_close,
                    volume = excluded.volume,
                    value_idr = excluded.value_idr,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    quality_flag = excluded.quality_flag
                """,
                (
                    ticker,
                    self._normalize_date(trade_date),
                    open,
                    high,
                    low,
                    close,
                    adj_close,
                    volume,
                    value_idr,
                    source,
                    self._normalize_date(fetched_at),
                    quality_flag,
                ),
            )
            conn.commit()

    def get_prices_for_ticker(self, ticker: str, trade_date: date | str) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM prices_daily WHERE ticker = ? AND trade_date = ? ORDER BY trade_date DESC",
                (ticker, self._normalize_date(trade_date)),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_fundamental(
        self,
        ticker: str,
        period_end: date | str,
        period_type: str,
        statement: str,
        item: str,
        value: float,
        publish_date: date | str | None = None,
        source: str | None = None,
        version: str = "v1",
        currency_orig: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fundamentals (
                    ticker, period_end, period_type, statement, item, value,
                    currency_orig, publish_date, source, version, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, period_end, period_type, statement, item, version) DO UPDATE SET
                    value = excluded.value,
                    currency_orig = excluded.currency_orig,
                    publish_date = excluded.publish_date,
                    source = excluded.source,
                    metadata = excluded.metadata
                """,
                (
                    ticker,
                    self._normalize_date(period_end),
                    period_type,
                    statement,
                    item,
                    value,
                    currency_orig,
                    self._normalize_date(publish_date),
                    source,
                    version,
                    self._json_dumps(metadata),
                ),
            )
            conn.commit()

    def list_fundamentals_for_ticker(self, ticker: str, period_end: date | str | None = None) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            if period_end is None:
                rows = conn.execute(
                    "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY period_end DESC, version DESC",
                    (ticker,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fundamentals WHERE ticker = ? AND period_end = ? ORDER BY version DESC",
                    (ticker, self._normalize_date(period_end)),
                ).fetchall()
            output = [dict(row) for row in rows]
            for item in output:
                item["metadata"] = self._json_loads(item.get("metadata"))
            return output

    def upsert_job_run(
        self,
        job_name: str,
        status: str,
        started_at: datetime | str | None = None,
        finished_at: datetime | str | None = None,
        rows_processed: int | None = None,
        source: str | None = None,
        run_date: date | str | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if isinstance(started_at, datetime):
            started_at_value = started_at.isoformat(timespec="seconds")
        else:
            started_at_value = started_at
        if isinstance(finished_at, datetime):
            finished_at_value = finished_at.isoformat(timespec="seconds")
        else:
            finished_at_value = finished_at
        if run_date is None:
            if isinstance(started_at, datetime):
                run_date = started_at.date().isoformat()
            else:
                run_date = date.today().isoformat()
        run_date_text = self._normalize_date(run_date)
        duration_s = None
        if started_at_value and finished_at_value:
            start_dt = datetime.fromisoformat(started_at_value)
            end_dt = datetime.fromisoformat(finished_at_value)
            duration_s = max(0.0, (end_dt - start_dt).total_seconds())
        with self.database.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_runs (
                    job_name, run_date, status, started_at, finished_at, duration_s,
                    rows_processed, source, error_code, error_summary, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_name, run_date, source) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    duration_s = excluded.duration_s,
                    rows_processed = excluded.rows_processed,
                    error_code = excluded.error_code,
                    error_summary = excluded.error_summary,
                    metadata = excluded.metadata
                """,
                (
                    job_name,
                    run_date_text,
                    status,
                    started_at_value,
                    finished_at_value,
                    duration_s,
                    rows_processed,
                    source,
                    error_code,
                    error_summary,
                    self._json_dumps(metadata),
                ),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT run_id FROM job_runs WHERE job_name = ? AND run_date = ? AND source IS ?",
                (job_name, run_date_text, source),
            ).fetchone()
            return int(row["run_id"]) if row else 0

    def list_job_runs(self) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            rows = conn.execute("SELECT * FROM job_runs ORDER BY started_at DESC").fetchall()
            output = [dict(row) for row in rows]
            for item in output:
                item["metadata"] = self._json_loads(item.get("metadata"))
            return output

    def record_data_quality_issue(
        self,
        instrument_ticker: str | None,
        dataset: str,
        issue_type: str,
        severity: str,
        message: str,
        status: str = "unresolved",
        detected_at: date | str | datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if detected_at is None:
            detected_at_value = datetime.now().isoformat(timespec="seconds")
        elif isinstance(detected_at, datetime):
            detected_at_value = detected_at.isoformat(timespec="seconds")
        else:
            detected_at_value = str(detected_at)
        with self.database.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO data_quality_issues (
                    ticker, dataset, issue_type, severity, message, detected_at, status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, dataset, issue_type, message, detected_at) DO UPDATE SET
                    status = excluded.status,
                    metadata = excluded.metadata
                """,
                (
                    instrument_ticker,
                    dataset,
                    issue_type,
                    severity,
                    message,
                    detected_at_value,
                    status,
                    self._json_dumps(metadata),
                ),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT issue_id FROM data_quality_issues WHERE ticker IS ? AND dataset = ? AND issue_type = ? AND message = ? AND detected_at = ?",
                (instrument_ticker, dataset, issue_type, message, detected_at_value),
            ).fetchone()
            return int(row["issue_id"]) if row else 0

    def list_data_quality_issues(self) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            rows = conn.execute("SELECT * FROM data_quality_issues ORDER BY detected_at DESC").fetchall()
            output = [dict(row) for row in rows]
            for item in output:
                item["metadata"] = self._json_loads(item.get("metadata"))
            return output

    def persist_feature_rows(self, feature_rows: list[dict[str, Any]]) -> int:
        inserted = 0
        for row in feature_rows or []:
            ticker = str(row.get("ticker") or "").strip().upper()
            trade_date = row.get("trade_date")
            feature_name = str(row.get("feature_name") or "").strip()
            value = row.get("value")
            feature_version = str(row.get("feature_version") or "unknown")
            if not ticker or not feature_name:
                continue
            with self.database.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO features_daily (ticker, trade_date, feature_name, value, feature_version)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, trade_date, feature_name, feature_version) DO UPDATE SET
                        value = excluded.value
                    """,
                    (ticker, self._normalize_date(trade_date), feature_name, value, feature_version),
                )
                conn.commit()
                inserted += 1
        return inserted

    def list_features_for_ticker(self, ticker: str, trade_date: date | str | None = None) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            if trade_date is None:
                rows = conn.execute(
                    "SELECT * FROM features_daily WHERE ticker = ? ORDER BY trade_date DESC, feature_name ASC",
                    (str(ticker).strip().upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM features_daily WHERE ticker = ? AND trade_date = ? ORDER BY feature_name ASC",
                    (str(ticker).strip().upper(), self._normalize_date(trade_date)),
                ).fetchall()
            return [dict(row) for row in rows]

    def upsert_screen_result(
        self,
        screen_id: str,
        run_date: date | str,
        ticker: str,
        rank: int | None = None,
        pass_detail_json: dict[str, Any] | str | None = None,
        entered: int = 0,
        exited: int = 0,
    ) -> None:
        payload = pass_detail_json if isinstance(pass_detail_json, str) else self._json_dumps(pass_detail_json)
        with self.database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO screen_results (screen_id, run_date, ticker, rank, pass_detail_json, entered, exited)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(screen_id, run_date, ticker) DO UPDATE SET
                    rank = excluded.rank,
                    pass_detail_json = excluded.pass_detail_json,
                    entered = excluded.entered,
                    exited = excluded.exited
                """,
                (screen_id, self._normalize_date(run_date), ticker, rank, payload, entered, exited),
            )
            conn.commit()

    def record_notification(
        self,
        kind: str,
        status: str,
        sent_at: date | str | datetime | None = None,
        chat_id: str | None = None,
        telegram_msg_id: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if sent_at is None:
            sent_at_value = datetime.now().isoformat(timespec="seconds")
        elif isinstance(sent_at, datetime):
            sent_at_value = sent_at.isoformat(timespec="seconds")
        else:
            sent_at_value = str(sent_at)
        with self.database.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notifications_log (kind, chat_id, sent_at, telegram_msg_id, status, error, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, chat_id, sent_at) DO UPDATE SET
                    telegram_msg_id = excluded.telegram_msg_id,
                    status = excluded.status,
                    error = excluded.error,
                    metadata = excluded.metadata
                """,
                (
                    kind,
                    chat_id,
                    sent_at_value,
                    telegram_msg_id,
                    status,
                    error,
                    self._json_dumps(metadata),
                ),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                "SELECT notif_id FROM notifications_log WHERE kind = ? AND chat_id IS ? AND sent_at = ?",
                (kind, chat_id, sent_at_value),
            ).fetchone()
            return int(row["notif_id"]) if row else 0

    def list_notifications(self) -> list[dict[str, Any]]:
        with self.database.get_connection() as conn:
            rows = conn.execute("SELECT * FROM notifications_log ORDER BY sent_at DESC").fetchall()
            output = [dict(row) for row in rows]
            for item in output:
                item["metadata"] = self._json_loads(item.get("metadata"))
            return output
