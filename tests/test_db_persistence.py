from datetime import date, datetime

from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


def _make_db(tmp_path):
    db_path = tmp_path / "idxscreener.db"
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    return db


def test_database_migration_creates_schema(tmp_path):
    db = _make_db(tmp_path)
    assert db.engine is not None
    with db.get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    names = {row[0] for row in tables}
    assert {"instruments", "trading_calendar", "market_params", "prices_daily", "job_runs", "data_quality_issues"}.issubset(names)


def test_upsert_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)

    repo.upsert_instrument(ticker="BBCA", name="Bank Central Asia", sector_idxic="Financials", board="Utama")
    repo.upsert_instrument(ticker="BBCA", name="Bank Central Asia", sector_idxic="Financials", board="Utama")

    count = repo.count_instruments()
    assert count == 1


def test_trading_calendar_and_market_params(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)

    repo.upsert_trading_calendar(date(2026, 9, 21), True, "regular")
    assert repo.is_trading_day(date(2026, 9, 21)) is True
    assert repo.is_trading_day(date(2026, 9, 20)) is False

    repo.upsert_market_param("tick_size", 5, effective_from=date(2026, 1, 1), effective_to=None, metadata={"min": 5000, "max": None})
    record = repo.get_market_param("tick_size", date(2026, 6, 1))
    assert record is not None
    assert record["value"] == 5


def test_job_runs_and_data_quality_issues(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)

    job_id = repo.upsert_job_run("daily_ingest", "success", started_at=datetime(2026, 9, 20, 8, 0, 0), finished_at=datetime(2026, 9, 20, 8, 5, 0), rows_processed=120, source="fixture")
    assert job_id

    repo.record_data_quality_issue(
        instrument_ticker="BBCA",
        dataset="prices_daily",
        issue_type="validation",
        severity="error",
        message="close price invalid",
        status="unresolved",
    )
    issues = repo.list_data_quality_issues()
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"


def test_fundamentals_support_point_in_time_versioning(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)
    repo.upsert_instrument(ticker="BBCA", name="Bank Central Asia", sector_idxic="Financials", board="Utama")

    repo.upsert_fundamental(
        ticker="BBCA",
        period_end=date(2026, 6, 30),
        period_type="FY",
        statement="bs",
        item="total_equity",
        value=1500000000000,
        publish_date=date(2026, 8, 15),
        source="idx",
        version="v1",
    )
    repo.upsert_fundamental(
        ticker="BBCA",
        period_end=date(2026, 6, 30),
        period_type="FY",
        statement="bs",
        item="total_equity",
        value=1515000000000,
        publish_date=date(2026, 8, 20),
        source="idx",
        version="v2",
    )

    versions = repo.list_fundamentals_for_ticker("BBCA", period_end=date(2026, 6, 30))
    assert len(versions) == 2


def test_e2e_persistence_workflow_is_idempotent(tmp_path):
    db = _make_db(tmp_path)
    repo = StockRepository(db)

    repo.upsert_instrument(ticker="BBCA", name="Bank Central Asia", sector_idxic="Financials", board="Utama")
    repo.upsert_trading_calendar(date(2026, 9, 21), True, "regular")
    repo.upsert_prices_daily(ticker="BBCA", trade_date=date(2026, 9, 21), open=7200, high=7300, low=7150, close=7250, adj_close=7250, volume=1000, source="fixture")
    repo.upsert_prices_daily(ticker="BBCA", trade_date=date(2026, 9, 21), open=7200, high=7300, low=7150, close=7250, adj_close=7250, volume=1000, source="fixture")
    repo.upsert_job_run("daily_ingest", "success", started_at=datetime(2026, 9, 20, 8, 0, 0), finished_at=datetime(2026, 9, 20, 8, 3, 0), rows_processed=1, source="fixture")
    repo.record_data_quality_issue("BBCA", "prices_daily", "validation", "warn", "price movement large", "unresolved")

    assert repo.count_instruments() == 1
    assert repo.get_prices_for_ticker("BBCA", date(2026, 9, 21))[0]["close"] == 7250
    assert len(repo.list_job_runs()) == 1
    assert len(repo.list_data_quality_issues()) == 1
