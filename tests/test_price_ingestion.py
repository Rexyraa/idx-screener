from datetime import date

from idxscreener.ingest.prices import ingest_sample_prices, load_sample_prices
from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def _make_db(tmp_path):
    db_path = tmp_path / "idxscreener.db"
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    return db


def test_ingest_sample_prices_persists_and_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)
    rows = load_sample_prices()

    result = ingest_sample_prices(db, rows)

    assert result["rows_total"] == 3
    assert result["rows_inserted"] == 3
    assert repo.get_prices_for_ticker("BBCA", date(2026, 9, 20))[0]["close"] == 7180

    rerun = ingest_sample_prices(db, rows)
    assert rerun["rows_inserted"] == 0
    assert rerun["rows_updated"] == 3
    assert len(repo.get_prices_for_ticker("BBCA", date(2026, 9, 20))) == 1
