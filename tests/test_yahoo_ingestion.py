from datetime import date

import pandas as pd

from idxscreener.ingest.prices import fetch_yahoo_prices, load_idx_universe, update_idx_prices_from_yahoo
from idxscreener.store.database import StockDatabase


def test_load_idx_universe_supports_all_mode(tmp_path):
    csv_path = tmp_path / "idx_universe.csv"
    csv_path.write_text("ticker\nBBCA\nTLKM\n", encoding="utf-8")

    universe = load_idx_universe(csv_path)
    assert universe == ["BBCA", "TLKM"]


def test_fetch_yahoo_prices_adds_yahoo_suffix_and_filters_columns(monkeypatch):
    frames = {
        "BBCA.JK": pd.DataFrame(
            {
                "Open": [7000.0],
                "High": [7100.0],
                "Low": [6900.0],
                "Close": [7050.0],
                "Adj Close": [7050.0],
                "Volume": [1200],
            },
            index=pd.Index([pd.Timestamp("2026-09-20")], name="Date"),
        )
    }

    def fake_download(tickers, *args, **kwargs):
        return frames[tickers[0]]

    monkeypatch.setattr("yfinance.download", fake_download)

    df = fetch_yahoo_prices(["BBCA"], period="1d")
    assert list(df.columns) == ["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]
    assert df.iloc[0]["ticker"] == "BBCA"
    assert df.iloc[0]["close"] == 7050.0


def test_update_idx_prices_from_yahoo_persists_rows(tmp_path, monkeypatch):
    db = StockDatabase(database_url=f"sqlite:///{tmp_path / 'idx.db'}")
    db.initialize()

    data = pd.DataFrame(
        {
            "Open": [7200.0],
            "High": [7300.0],
            "Low": [7150.0],
            "Close": [7250.0],
            "Adj Close": [7250.0],
            "Volume": [1000],
        },
        index=pd.Index([pd.Timestamp("2026-09-21")], name="Date"),
    )

    monkeypatch.setattr("yfinance.download", lambda tickers, *args, **kwargs: data)

    summary = update_idx_prices_from_yahoo(db, ["BBCA"])

    assert summary["rows_total"] == 1
    assert summary["rows_inserted"] == 1
    assert summary["rows_updated"] == 0
