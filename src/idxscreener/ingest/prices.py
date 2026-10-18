from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def _index_to_trade_dates(index: pd.Index) -> list[str]:
    return [pd.Timestamp(value).date().isoformat() for value in index]


def _universe_path(path: str | Path | None) -> Path:
    if path is None:
        return Path(__file__).resolve().parents[1] / "data" / "idx_universe.csv"
    return Path(path)


def load_idx_universe(path: str | Path | None = None) -> list[str]:
    """Return list of ticker strings from the IDX universe CSV."""
    file_path = _universe_path(path)
    if not file_path.exists():
        return ["BBCA", "TLKM", "BMRI", "ASII", "UNVR"]
    df = pd.read_csv(file_path)
    return [str(r["ticker"]).strip() for _, r in df.iterrows() if str(r["ticker"]).strip()]


def load_idx_universe_df(path: str | Path | None = None) -> pd.DataFrame:
    """Return the full IDX universe as a DataFrame with ticker/name/sector/board/status."""
    file_path = _universe_path(path)
    if not file_path.exists():
        return pd.DataFrame({"ticker": ["BBCA", "TLKM", "BMRI", "ASII", "UNVR"]})
    df = pd.read_csv(file_path)
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df[df["ticker"].str.len() > 0].reset_index(drop=True)


def load_sample_prices(path: str | Path | None = None) -> pd.DataFrame:
    file_path = Path(path) if path else Path(__file__).resolve().parents[1] / "data" / "sample_prices.csv"
    return pd.read_csv(file_path)


def fetch_yahoo_prices(tickers: list[str], period: str = "5d", interval: str = "1d") -> pd.DataFrame:
    """Fetch Yahoo Finance OHLCV data for a list of stock tickers and normalize it to the project schema."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"])

    yahoo_tickers = [f"{ticker}.JK" if not ticker.upper().endswith(".JK") else ticker for ticker in tickers]
    raw = yf.download(yahoo_tickers, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)

    if isinstance(raw, pd.Series):
        raw = raw.to_frame().T

    if raw.empty:
        return pd.DataFrame(columns=["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"])

    if len(yahoo_tickers) == 1 and isinstance(raw.columns, pd.MultiIndex):
        raw = raw.droplevel(0, axis=1)

    records: list[dict[str, object]] = []

    if isinstance(raw.columns, pd.MultiIndex):
        for ticker in yahoo_tickers:
            if ticker not in raw.columns.get_level_values(0):
                continue
            ticker_df = raw[ticker].copy()
            ticker_df = ticker_df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            })
            ticker_df["ticker"] = ticker.replace(".JK", "")
            ticker_df["trade_date"] = _index_to_trade_dates(ticker_df.index)
            records.extend(ticker_df[["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]].to_dict(orient="records"))
    else:
        normalized = raw.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }).copy()
        normalized["ticker"] = tickers[0]
        normalized["trade_date"] = _index_to_trade_dates(normalized.index)
        records.extend(normalized[["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]].to_dict(orient="records"))

    output = pd.DataFrame(records, columns=["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"])
    return output.dropna(subset=["trade_date"]).reset_index(drop=True)


def ingest_sample_prices(db: StockDatabase, df: pd.DataFrame) -> dict[str, int]:
    """Persist sample price rows to SQLite in an idempotent way."""
    repo = StockRepository(db)
    rows_inserted = 0
    rows_updated = 0

    for row in df.to_dict(orient="records"):
        ticker = str(row["ticker"]).strip()
        trade_date = row["trade_date"]
        before = repo.get_prices_for_ticker(ticker, trade_date)

        repo.upsert_prices_daily(
            ticker=ticker,
            trade_date=trade_date,
            open=float(row.get("open", 0.0) or 0.0),
            high=float(row.get("high", 0.0) or 0.0),
            low=float(row.get("low", 0.0) or 0.0),
            close=float(row.get("close", 0.0) or 0.0),
            adj_close=float(row.get("close", 0.0) or 0.0),
            volume=int(row.get("volume", 0) or 0),
            source="sample",
            fetched_at=trade_date,
        )

        after = repo.get_prices_for_ticker(ticker, trade_date)
        if not before and after:
            rows_inserted += 1
        elif before and after:
            rows_updated += 1

    return {
        "rows_total": len(df),
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
    }


def update_idx_prices_from_yahoo(db: StockDatabase, tickers: list[str], period: str = "5d", interval: str = "1d") -> dict[str, int]:
    """Fetch and persist the latest Yahoo OHLCV data for IDX-listed symbols into the project database."""
    rows = fetch_yahoo_prices(tickers, period=period, interval=interval)
    if rows.empty:
        return {"rows_total": 0, "rows_inserted": 0, "rows_updated": 0}

    repo = StockRepository(db)
    rows_inserted = 0
    rows_updated = 0

    for row in rows.to_dict(orient="records"):
        ticker = str(row["ticker"]).strip()
        trade_date = row["trade_date"]
        before = repo.get_prices_for_ticker(ticker, trade_date)

        repo.upsert_prices_daily(
            ticker=ticker,
            trade_date=trade_date,
            open=float(row.get("open") or 0.0),
            high=float(row.get("high") or 0.0),
            low=float(row.get("low") or 0.0),
            close=float(row.get("close") or 0.0),
            adj_close=float(row.get("adj_close") or 0.0),
            volume=int(row.get("volume") or 0),
            source="yahoo",
            fetched_at=trade_date,
        )

        after = repo.get_prices_for_ticker(ticker, trade_date)
        if not before and after:
            rows_inserted += 1
        elif before and after:
            rows_updated += 1

    return {
        "rows_total": len(rows),
        "rows_inserted": rows_inserted,
        "rows_updated": rows_updated,
    }


def refresh_all_idx_prices(db: StockDatabase, universe: list[str] | None = None, period: str = "5d", interval: str = "1d") -> dict[str, int]:
    """Refresh OHLCV for all listed IDX tickers using a single bulk update call."""
    ticker_list = universe if universe is not None else load_idx_universe()
    return update_idx_prices_from_yahoo(db, ticker_list, period=period, interval=interval)
