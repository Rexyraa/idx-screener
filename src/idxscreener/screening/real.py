"""Real Yahoo prices and an atomic, database-independent momentum snapshot."""

import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from idxscreener.ingest.prices import load_idx_universe_df

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parents[3] / "output" / "real_screen")
METHOD = "Momentum percentile: equal-weight ranks of adjusted 21/60-session returns; latest session, positive volume, 20-session average traded value >= IDR 1bn. Not CAQS or investment advice."


def valid_prices(prices):
    prices = prices.sort_index().copy()
    required = ["Close", "Adj Close", "Volume"]
    values = prices[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, :2] <= 0).any() or (values[:, 2] < 0).any():
        raise ValueError("Prices must be finite and positive; volume finite and nonnegative")
    if prices.index.has_duplicates or prices.index.hasnans:
        raise ValueError("Invalid or duplicate price dates")
    if len(prices) < 61:
        raise ValueError(f"History needs at least 61 sessions: {len(prices)}")
    for column in ("Open", "High", "Low"):
        if column in prices:
            values = prices[column].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise ValueError(f"Invalid {column} prices")
    return prices


def price_metrics(prices):
    prices = valid_prices(prices)
    close = prices["Adj Close"]
    metrics = {
        "data_date": prices.index[-1].date().isoformat(),
        "price": float(prices["Close"].iloc[-1]),
        "return_1m_pct": float((close.iloc[-1] / close.iloc[-22] - 1) * 100),
        "return_3m_pct": float((close.iloc[-1] / close.iloc[-61] - 1) * 100),
        "volatility_pct": float(close.pct_change().dropna().tail(60).std() * np.sqrt(252) * 100),
        "avg_value_20_idr": float((prices["Close"] * prices["Volume"]).tail(20).mean()),
        "last_volume": float(prices["Volume"].iloc[-1]),
    }
    if not all(np.isfinite(v) for k, v in metrics.items() if k != "data_date"):
        raise ValueError("Nonfinite price metrics")
    return metrics


def write_snapshot(snapshot, data_dir=DATA_DIR):
    """Serialize before replacing: failed downloads/writes leave the last good file."""
    content = json.dumps(snapshot, allow_nan=False, ensure_ascii=False)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=data_dir, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, data_dir / "snapshot.json")
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_snapshot(data_dir=DATA_DIR):
    # ponytail: no legacy CSV import; refresh once to obtain validated price histories.
    try:
        snapshot = json.loads((Path(data_dir) / "snapshot.json").read_text(encoding="utf-8"))
        if not isinstance(snapshot.get("results"), list) or not isinstance(snapshot.get("prices"), dict) or not isinstance(snapshot.get("summary"), dict):
            raise ValueError("Invalid snapshot")
        return snapshot
    except (OSError, ValueError, TypeError, AttributeError):
        return {"results": [], "summary": {}, "prices": {}, "metrics": {}}


def snapshot_summary(snapshot):
    summary = {**snapshot["summary"], "method": METHOD, "score_kind": "momentum_percentile"}
    latest = summary.get("latest_data_date")
    try:
        age = (date.today() - date.fromisoformat(latest)).days
        summary["status"] = "stale" if age > 7 or age < 0 else "success"
    except (TypeError, ValueError):
        summary["status"] = "empty"
    summary["stale"] = summary["status"] == "stale"
    return summary


def screen_real(run_date=None, progress=None, data_dir=DATA_DIR, universe=None):
    requested = date.fromisoformat(run_date) if run_date else date.today()
    if requested > date.today():
        raise ValueError("Future run dates are not supported")
    universe = (load_idx_universe_df() if universe is None else universe).drop_duplicates("ticker")
    symbols = [f"{ticker}.JK" for ticker in universe["ticker"]]
    if not symbols:
        raise ValueError("Empty universe")
    raw = yf.download(symbols, period="6mo", auto_adjust=False, progress=False,
                      threads=False, timeout=10, group_by="ticker")
    if raw.empty:
        raise RuntimeError("No market prices; last good snapshot preserved")
    rows, failures, histories, metrics_by_ticker = [], [], {}, {}
    for index, item in enumerate(universe.to_dict("records"), 1):
        ticker = item["ticker"]
        try:
            prices = raw[f"{ticker}.JK"] if isinstance(raw.columns, pd.MultiIndex) else raw
            if not isinstance(raw.columns, pd.MultiIndex) and len(symbols) != 1:
                raise ValueError("Missing ticker columns")
            prices = prices.loc[prices.index.date <= requested].dropna(how="all")
            prices = valid_prices(prices)
            metrics = price_metrics(prices)
            history = []
            for timestamp, row in prices.iterrows():
                record = {"trade_date": timestamp.date().isoformat()}
                for source, field in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Adj Close", "adj_close"), ("Volume", "volume")):
                    record[field] = float(row[source]) if source in prices else None
                history.append(record)
            histories[ticker] = history
            metrics_by_ticker[ticker] = metrics
            rows.append({"ticker": ticker, "name": str(item.get("name") or ""),
                         "sector": str(item.get("sector") or ""), **metrics})
        except (KeyError, ValueError, TypeError, IndexError, OverflowError) as exc:
            failures.append({"ticker": ticker, "reason": str(exc)})
        if progress:
            progress(index, len(symbols))
    if not rows:
        raise RuntimeError("No valid market prices; last good snapshot preserved")
    frame = pd.DataFrame(rows)
    latest = frame["data_date"].max()
    eligible = frame[(frame["data_date"] == latest) & (frame["avg_value_20_idr"] >= 1_000_000_000) & (frame["last_volume"] > 0)].copy()
    # ponytail: price-only ranking; add validated fundamentals before implementing CAQS.
    eligible["score"] = (eligible["return_1m_pct"].rank(pct=True) + eligible["return_3m_pct"].rank(pct=True)) * 50
    eligible["change_1m"] = eligible["return_1m_pct"]
    eligible["label"] = "Momentum percentile (not CAQS)"
    eligible["score_kind"] = "momentum_percentile"
    summary = {
        "source": "Yahoo Finance via yfinance; no synthetic fallback",
        "method": METHOD, "score_kind": "momentum_percentile",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "run_date": requested.isoformat(),
        "latest_data_date": latest, "universe_count": len(symbols),
        "valid_count": len(rows), "failed_count": len(failures), "eligible_count": len(eligible),
        "latest_count": int((frame["data_date"] == latest).sum()),
        "coverage": len(rows) / len(symbols), "failures": failures,
    }
    snapshot = {"results": eligible.sort_values("score", ascending=False).to_dict("records"),
                "summary": summary, "prices": histories, "metrics": metrics_by_ticker}
    write_snapshot(snapshot, data_dir)
    return snapshot