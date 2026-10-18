from datetime import date

import click
import pandas as pd

from idxscreener.alerts.engine import evaluate_alerts
from idxscreener.config.loader import get_config_path, load_yaml
from idxscreener.config.schema import (
    validate_alerts_config,
    validate_model_config,
    validate_screens_config,
)
from idxscreener.features.engine import FEATURE_VERSION, calculate_feature_rows
from idxscreener.ingest.prices import fetch_yahoo_prices, load_idx_universe, load_idx_universe_df, load_sample_prices, refresh_all_idx_prices, update_idx_prices_from_yahoo
from idxscreener.notify.telegram import build_daily_report
from idxscreener.ops.monitor import check_freshness, check_heartbeat
from idxscreener.prediction.engine import generate_synthetic_prices, predict_next_day, walk_forward_predict
from idxscreener.ops.pipeline import run_daily_pipeline
from idxscreener.scoring.caqs import score_company
from idxscreener.store.database import StockDatabase
from idxscreener.store.repositories import StockRepository


@click.group()
def cli():
    """Stock Screener BEI (IHSG) command line."""


# ── run ──────────────────────────────────────────────────────────────────────

@cli.group()
def run():
    """Run pipeline jobs."""


@run.command("daily")
@click.option("--date", "run_date", default=str(date.today()), help="Run date YYYY-MM-DD")
@click.option("--dry-run", is_flag=True, help="Do not send telegram messages or save state")
@click.option("--skip-stochastic", is_flag=True, help="Skip stochastic and actuarial modules")
def run_daily(run_date: str, dry_run: bool, skip_stochastic: bool) -> None:
    """Run the daily pipeline and print a formatted terminal summary."""
    result = run_daily_pipeline(run_date, dry_run=dry_run)

    # ── header ────────────────────────────────────────────────────────────────
    status_color = "green" if result["status"] == "success" else "yellow"
    click.echo("")
    click.echo(click.style("━" * 52, fg="bright_blue"))
    click.echo(click.style("  IDX Screener — Daily Pipeline", fg="bright_blue", bold=True))
    click.echo(click.style("━" * 52, fg="bright_blue"))
    click.echo(f"  Date       : {result['run_date']}")
    click.echo(f"  Run ID     : {result.get('run_id', 'n/a')[:16]}…")
    click.echo(f"  Status     : {click.style(result['status'].upper(), fg=status_color, bold=True)}")
    click.echo(f"  Model      : {result['config_version']}")
    click.echo(f"  Duration   : {result.get('duration_s', 0):.3f}s")
    if dry_run:
        click.echo(f"  Mode       : {click.style('DRY-RUN (no writes)', fg='yellow')}")
    click.echo(click.style("─" * 52, fg="bright_black"))

    # ── top candidates ────────────────────────────────────────────────────────
    click.echo(click.style("  Top Candidates", bold=True))
    for c in result["summary"]["top_candidates"]:
        label_color = "green" if "Kuat" in c["score"] else "cyan"
        click.echo(
            f"    {click.style(c['ticker'], bold=True):<8} "
            f"CAQS {click.style(str(c['caqs']), fg='bright_white'):>5}  "
            f"{click.style(c['score'], fg=label_color)}"
        )
    click.echo(click.style("━" * 52, fg="bright_blue"))
    click.echo("")


# ── ingest ────────────────────────────────────────────────────────────────────

@cli.group()
def ingest():
    """Ingest data."""


@ingest.command("prices")
def ingest_prices() -> None:
    """Load sample price data for the MVP pipeline."""
    df = load_sample_prices()
    click.echo(df.to_string(index=False))


@ingest.command("yahoo")
@click.option("--tickers", default="BBCA,TLKM,BMRI", show_default=True)
@click.option("--period", default="5d", show_default=True)
@click.option("--db-path", default="idxscreener.db", show_default=True)
def ingest_yahoo_prices(tickers: str, period: str, db_path: str) -> None:
    """Fetch and persist Yahoo Finance OHLCV data for the provided tickers."""
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    rows = fetch_yahoo_prices(ticker_list, period=period)
    summary = update_idx_prices_from_yahoo(db, ticker_list, period=period)
    click.echo(f"rows_total={summary['rows_total']}")
    click.echo(f"rows_inserted={summary['rows_inserted']}")
    click.echo(f"rows_updated={summary['rows_updated']}")
    click.echo(rows.head().to_string(index=False))


@ingest.command("all")
@click.option("--db-path", default="idxscreener.db", show_default=True)
@click.option("--period", default="5d", show_default=True)
@click.option("--universe-file", default=None)
def ingest_all_idx_prices(db_path: str, period: str, universe_file: str | None) -> None:
    """Refresh Yahoo Finance price data for the full IDX universe."""
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    universe = load_idx_universe(universe_file) if universe_file else load_idx_universe()
    summary = refresh_all_idx_prices(db, universe=universe, period=period)
    click.echo(f"rows_total={summary['rows_total']}")
    click.echo(f"rows_inserted={summary['rows_inserted']}")
    click.echo(f"rows_updated={summary['rows_updated']}")


# ── features ──────────────────────────────────────────────────────────────────

@cli.group()
def features():
    """Compute deterministic feature snapshots."""


@features.command("compute")
@click.option("--tickers", default="BBCA,TLKM,BMRI", show_default=True)
@click.option("--date", "run_date", default=str(date.today()))
@click.option("--db-path", default="idxscreener.db", show_default=True)
def compute_features(tickers: str, run_date: str, db_path: str) -> None:
    """Compute the feature snapshots for the given tickers and persist them."""
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise click.BadParameter("At least one ticker is required.")
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    repo = StockRepository(db)
    prices = fetch_yahoo_prices(ticker_list, period="5d")
    if prices.empty:
        prices = load_sample_prices()
    rows = calculate_feature_rows(prices, calculation_date=run_date, feature_version=FEATURE_VERSION)
    persisted = repo.persist_feature_rows(rows)
    click.echo(f"feature_rows={len(rows)}")
    click.echo(f"persisted={persisted}")


# ── score / screen ────────────────────────────────────────────────────────────

@cli.command("score")
@click.option("--date", "run_date", default=str(date.today()))
def score(run_date: str) -> None:
    """Compute CAQS on sample data."""
    sample = load_sample_prices()
    for row in sample.to_dict(orient="records"):
        metrics = {"f_score": 0.8, "q_score": 0.7, "t_score": 0.75}
        result = score_company(row["ticker"], metrics)
        click.echo(f"{row['ticker']} => {result.caqs:.1f} ({result.label})")


@cli.command("screen")
@click.option("--name", required=True, help="Screen name from config")
@click.option("--date", "run_date", default=str(date.today()))
@click.option("--export", default=None, help="Export format (csv)")
def screen(name: str, run_date: str, export: str | None) -> None:
    """Run simple screener logic over the sample scores."""
    scores = [
        {"ticker": "BBCA", "caqs": 86.2},
        {"ticker": "TLKM", "caqs": 82.4},
        {"ticker": "BMRI", "caqs": 79.9},
    ]
    click.echo(f"screen={name} date={run_date} export={export}")
    click.echo(scores)


# ── daily-report / eval-alerts ────────────────────────────────────────────────

@cli.command("daily-report")
@click.option("--date", "run_date", default=str(date.today()))
def daily_report(run_date: str) -> None:
    """Render the daily Telegram-ready summary using the MVP watchlist."""
    report = build_daily_report(
        run_date=run_date,
        top_candidates=[
            {"ticker": "BBCA", "caqs": 86.2, "score": "Kandidat Kuat"},
            {"ticker": "TLKM", "caqs": 82.4, "score": "Kandidat"},
        ],
        alerts=[
            {"id": "score_jump", "ticker": "BBCA", "severity": "medium", "message": "CAQS naik 10 poin"},
        ],
    )
    click.echo(report)


@cli.command("eval-alerts")
@click.option("--date", "run_date", default=str(date.today()))
def eval_alerts(run_date: str) -> None:
    """Evaluate alert rules against sample watchlist values."""
    watchlist = [{
        "ticker": "BBCA", "caqs": 86.2, "previous_caqs": 75.0,
        "sma20": 101.0, "sma50": 99.0, "volume_ratio": 1.3,
    }]
    rules = [
        {"id": "score_jump", "category": "score_change", "scope": "watchlist",
         "condition": "delta(caqs, 5d) >= 8", "severity": "medium", "cooldown_hours": 48},
        {"id": "golden_cross", "category": "signal", "scope": ["watchlist", "top_n:20"],
         "condition": "crosses_above(sma20, sma50) and volume_ratio > 1.2", "cooldown_hours": 72},
    ]
    events = evaluate_alerts(rules, watchlist)
    click.echo(events)


# ── ops ───────────────────────────────────────────────────────────────────────

@cli.group()
def ops():
    """Operational checks: config validation, freshness, heartbeat."""


@ops.command("validate-config")
def validate_config() -> None:
    """FR-CFG-02: validate all config files and print a pass/fail report."""
    checks = [
        ("model.yaml",   lambda r: validate_model_config(r)),
        ("screens.yaml", lambda r: validate_screens_config(r)),
        ("alerts.yaml",  lambda r: validate_alerts_config(r)),
    ]
    all_ok = True
    click.echo("")
    click.echo(click.style("  Config Validation", bold=True))
    click.echo(click.style("─" * 40, fg="bright_black"))
    for filename, validator in checks:
        try:
            raw = load_yaml(get_config_path(filename))
            validator(raw)
            click.echo(f"  {click.style('✓', fg='green')}  {filename}")
        except Exception as exc:
            click.echo(f"  {click.style('✗', fg='red')}  {filename}")
            click.echo(f"     {click.style(str(exc), fg='red')}")
            all_ok = False
    click.echo(click.style("─" * 40, fg="bright_black"))
    if all_ok:
        click.echo(click.style("  All configs valid.", fg="green", bold=True))
    else:
        click.echo(click.style("  Config errors found — fix before running pipeline.", fg="red", bold=True))
        raise SystemExit(1)
    click.echo("")


@ops.command("freshness")
@click.option("--date", "run_date", default=str(date.today()))
@click.option("--db-path", default="idxscreener.db", show_default=True)
@click.option("--max-price-age", default=1, show_default=True, help="Max allowed price age in days")
def freshness(run_date: str, db_path: str, max_price_age: int) -> None:
    """FR-OPS-05: check data freshness and print a report."""
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    result = check_freshness(db, run_date, max_price_age_days=max_price_age)

    icon = click.style("✓", fg="green") if result["healthy"] else click.style("✗", fg="red")
    click.echo("")
    click.echo(click.style("  Data Freshness Check", bold=True))
    click.echo(click.style("─" * 40, fg="bright_black"))
    click.echo(f"  Status            : {icon}  {'OK' if result['healthy'] else 'STALE'}")
    click.echo(f"  Run date          : {result['run_date']}")
    click.echo(f"  Latest price      : {result['latest_price_date'] or 'none'}")
    age = result["price_age_days"]
    click.echo(f"  Price age (days)  : {age if age is not None else 'n/a'}")
    click.echo(f"  Latest fund.      : {result['latest_fundamental_date'] or 'none'}")
    if result["issues"]:
        click.echo(click.style("─" * 40, fg="bright_black"))
        for issue in result["issues"]:
            click.echo(f"  {click.style('!', fg='yellow')}  {issue}")
    click.echo(click.style("─" * 40, fg="bright_black"))
    click.echo("")
    if not result["healthy"]:
        raise SystemExit(1)


@ops.command("heartbeat")
@click.option("--date", "run_date", default=str(date.today()))
@click.option("--db-path", default="idxscreener.db", show_default=True)
@click.option("--deadline-hour-utc", default=10, show_default=True, help="Deadline hour in UTC (10 = 17:00 WIB)")
def heartbeat(run_date: str, db_path: str, deadline_hour_utc: int) -> None:
    """FR-OPS-04: dead man's switch — check if daily report was sent on time."""
    db = StockDatabase(database_url=f"sqlite:///{db_path}")
    db.initialize()
    result = check_heartbeat(db, run_date, deadline_hour_utc=deadline_hour_utc)

    fired = result["fired"]
    icon = click.style("✗ FIRED", fg="red", bold=True) if fired else click.style("✓ OK", fg="green", bold=True)
    click.echo("")
    click.echo(click.style("  Heartbeat Check", bold=True))
    click.echo(click.style("─" * 40, fg="bright_black"))
    click.echo(f"  Status    : {icon}")
    click.echo(f"  Run date  : {result['run_date']}")
    click.echo(f"  Deadline  : {result['deadline_utc']}")
    click.echo(f"  Reason    : {result['reason']}")
    if not fired:
        click.echo(f"  Reports   : {result.get('sent_count', 0)} found")
    click.echo(click.style("─" * 40, fg="bright_black"))
    click.echo("")
    if fired:
        raise SystemExit(1)


# ── predict ───────────────────────────────────────────────────────────────────

@cli.group()
def predict():
    """Stock return prediction using walk-forward Ridge regression."""


@predict.command("next-day")
@click.option("--tickers", default="BBCA,TLKM,BMRI", show_default=True, help="Comma-separated tickers (no .JK)")
@click.option("--period", default="2y", show_default=True, help="History period for Yahoo Finance (e.g. 1y, 2y, 5y)")
@click.option("--alpha", default=50.0, show_default=True, help="Ridge regularisation strength")
@click.option("--synthetic", is_flag=True, help="Use synthetic GBM data instead of Yahoo Finance (offline mode)")
def predict_next(tickers: str, period: str, alpha: float, synthetic: bool) -> None:
    """Predict next-day return for each ticker using Ridge regression.

    Trains on all available history; outputs predicted price and direction.
    Not investment advice.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    if synthetic:
        click.echo(click.style("  Using synthetic GBM data (offline mode)", fg="yellow"))
        frames = [generate_synthetic_prices(t) for t in ticker_list]
        prices = pd.concat(frames, ignore_index=True)
    else:
        prices = fetch_yahoo_prices(ticker_list, period=period)

    if prices.empty or prices.groupby("ticker").size().max() < 30:
        click.echo(click.style("  Yahoo data unavailable or insufficient — falling back to synthetic GBM data.", fg="yellow"))
        frames = [generate_synthetic_prices(t) for t in ticker_list]
        prices = pd.concat(frames, ignore_index=True)

    click.echo("")
    click.echo(click.style("━" * 56, fg="bright_blue"))
    click.echo(click.style("  Next-Day Prediction  (Ridge, α={:.0f})".format(alpha), fg="bright_blue", bold=True))
    click.echo(click.style("  ⚠  Research only — not investment advice", fg="yellow"))
    click.echo(click.style("━" * 56, fg="bright_blue"))
    click.echo(f"  {'Ticker':<8} {'Last':>8} {'Pred Ret':>10} {'Pred Price':>12} {'Dir':<6} {'Conf':>6}")
    click.echo(click.style("─" * 56, fg="bright_black"))

    for ticker in ticker_list:
        t_prices = prices[prices["ticker"].str.upper() == ticker]
        if t_prices.empty:
            click.echo(f"  {ticker:<8} {'no data':>8}")
            continue
        result = predict_next_day(t_prices, ticker, alpha=alpha)
        dir_color = "green" if result.direction == "up" else "red" if result.direction == "down" else "bright_black"
        dir_icon = "▲" if result.direction == "up" else "▼" if result.direction == "down" else "─"
        click.echo(
            f"  {click.style(ticker, bold=True):<8}"
            f" {result.last_price:>8.2f}"
            f" {result.predicted_return:>+10.4%}"
            f" {result.predicted_price:>12.2f}"
            f" {click.style(dir_icon + ' ' + result.direction, fg=dir_color):<10}"
            f" {result.confidence:>5.1%}"
        )

    click.echo(click.style("━" * 56, fg="bright_blue"))
    click.echo("")


@predict.command("backtest")
@click.option("--tickers", default="BBCA,TLKM,BMRI", show_default=True)
@click.option("--period", default="2y", show_default=True, help="History period (e.g. 2y, 5y)")
@click.option("--test-start", default=None, help="Test period start date YYYY-MM-DD (default: last 25%% of data)")
@click.option("--alpha", default=50.0, show_default=True)
@click.option("--export", default=None, help="Export predictions to CSV file path")
@click.option("--synthetic", is_flag=True, help="Use synthetic GBM data instead of Yahoo Finance (offline mode)")
def predict_backtest(tickers: str, period: str, test_start: str | None, alpha: float, export: str | None, synthetic: bool) -> None:
    """Walk-forward backtest: measure direction accuracy, R², price RMSE.

    Each prediction uses only information available at that point in time.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    if synthetic:
        click.echo(click.style("  Using synthetic GBM data (offline mode)", fg="yellow"))
        frames = [generate_synthetic_prices(t) for t in ticker_list]
        prices = pd.concat(frames, ignore_index=True)
    else:
        prices = fetch_yahoo_prices(ticker_list, period=period)

    if prices.empty or prices.groupby("ticker").size().max() < 60:
        click.echo(click.style("  Yahoo data unavailable or insufficient — falling back to synthetic GBM data.", fg="yellow"))
        frames = [generate_synthetic_prices(t) for t in ticker_list]
        prices = pd.concat(frames, ignore_index=True)

    results = []
    all_preds = []
    for ticker in ticker_list:
        t_prices = prices[prices["ticker"].str.upper() == ticker]
        if t_prices.empty:
            continue
        wf = walk_forward_predict(t_prices, ticker, test_start=test_start, alpha=alpha)
        results.append(wf)
        for p in wf.predictions:
            p["ticker"] = ticker
            all_preds.append(p)

    click.echo("")
    click.echo(click.style("━" * 60, fg="bright_blue"))
    click.echo(click.style("  Walk-Forward Backtest  (Ridge, α={:.0f})".format(alpha), fg="bright_blue", bold=True))
    click.echo(click.style("  ⚠  Research only — not investment advice", fg="yellow"))
    click.echo(click.style("━" * 60, fg="bright_blue"))
    click.echo(f"  {'Ticker':<8} {'Dir Acc':>8} {'R²':>8} {'RMSE (Rp)':>12} {'N':>6}")
    click.echo(click.style("─" * 60, fg="bright_black"))

    for wf in results:
        acc_color = "green" if wf.direction_accuracy > 0.54 else "yellow" if wf.direction_accuracy > 0.48 else "red"
        r2_color = "green" if wf.r_squared > 0.01 else "bright_black"
        click.echo(
            f"  {click.style(wf.ticker, bold=True):<8}"
            f" {click.style(f'{wf.direction_accuracy:.1%}', fg=acc_color):>10}"
            f" {click.style(f'{wf.r_squared:+.4f}', fg=r2_color):>10}"
            f" {wf.price_rmse:>12.2f}"
            f" {wf.n_predictions:>6}"
        )

    click.echo(click.style("─" * 60, fg="bright_black"))
    click.echo("  Direction accuracy: % of non-flat days predicted correctly")
    click.echo("  R²: vs random walk (>0 beats predicting 0 return)")
    click.echo("  ±7.6pp is the chance range for ~176 days (95% CI)")
    click.echo(click.style("━" * 60, fg="bright_blue"))
    click.echo("")

    if export and all_preds:
        import csv, pathlib
        out = pathlib.Path(export)
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_preds[0].keys())
            writer.writeheader()
            writer.writerows(all_preds)
        click.echo(f"  Predictions exported to {out}")
        click.echo("")


@cli.group()
def universe():
    """Browse the IDX ticker universe."""


@universe.command("list")
@click.option("--sector", default=None, help="Filter by sector (case-insensitive substring).")
@click.option("--board", default=None, help="Filter by board (e.g. utama, pengembangan).")
def universe_list(sector: str | None, board: str | None) -> None:
    """List all tickers in the IDX universe."""
    df = load_idx_universe_df()
    if sector:
        df = df[df["sector"].str.contains(sector, case=False, na=False)]
    if board:
        df = df[df["board"].str.contains(board, case=False, na=False)]

    click.echo(click.style(f"  {'Ticker':<8} {'Sector':<22} {'Name'}", fg="bright_blue", bold=True))
    click.echo(click.style("─" * 72, fg="bright_black"))
    for _, row in df.iterrows():
        click.echo(f"  {row['ticker']:<8} {str(row.get('sector','')):<22} {row.get('name','')}")
    click.echo(click.style("─" * 72, fg="bright_black"))
    click.echo(f"  {len(df)} tickers")


@universe.command("sectors")
def universe_sectors() -> None:
    """Show sector breakdown counts."""
    df = load_idx_universe_df()
    counts = df["sector"].value_counts()
    click.echo(click.style(f"  {'Sector':<30} {'Count':>6}", fg="bright_blue", bold=True))
    click.echo(click.style("─" * 38, fg="bright_black"))
    for sector, count in counts.items():
        click.echo(f"  {sector:<30} {count:>6}")
    click.echo(click.style("─" * 38, fg="bright_black"))
    click.echo(f"  Total: {len(df)}")


if __name__ == "__main__":
    cli()

