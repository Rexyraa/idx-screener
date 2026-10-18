"""FastAPI web layer for the IDX screener — earthtone themed local UI."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from idxscreener.config.loader import get_config_path, load_yaml
from idxscreener.config.schema import validate_model_config
from idxscreener.ingest.prices import load_idx_universe_df
from idxscreener.screening.real import DATA_DIR, load_snapshot, screen_real, snapshot_summary

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="IDX Screener", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "false").lower() in {"true", "1", "yes"}
_bg_jobs: dict[str, dict[str, Any]] = {}
_watchlist_lock = threading.Lock()
_refresh_lock = threading.Lock()


@app.middleware("http")
async def read_only_demo(request: Request, call_next):
    if PUBLIC_DEMO and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        return JSONResponse({"error": "Public demo is read-only"}, status_code=403)
    return await call_next(request)


def real_summary():
    summary = snapshot_summary(load_snapshot())
    if _bg_jobs:
        summary["refresh"] = dict(next(reversed(_bg_jobs.values())))
    return summary


TEMPLATES.env.globals["real_summary"] = real_summary
TEMPLATES.context_processors.append(
    lambda request: {"real_metadata": real_summary(), "public_demo": PUBLIC_DEMO}
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "public_demo": PUBLIC_DEMO, "screening": real_summary()}


# ── helpers ──────────────────────────────────────────────────────────────────

def _db_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / "web.sqlite3")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS watchlist "
        "(ticker TEXT PRIMARY KEY, added_at TEXT NOT NULL)"
    )
    return conn


def _get_watchlist() -> list[dict]:
    conn = _db_conn()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _add_watchlist(ticker: str) -> dict:
    with _watchlist_lock:
        conn = _db_conn()
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, added_at) VALUES (?, ?)",
            (ticker, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    return {"ticker": ticker, "added_at": datetime.now().isoformat()}


def _remove_watchlist(ticker: str) -> None:
    with _watchlist_lock:
        conn = _db_conn()
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
        conn.commit()
        conn.close()


def _get_weights() -> dict:
    raw = load_yaml(get_config_path("model.yaml"))
    cfg = validate_model_config(raw)
    return cfg.weights.model_dump()


def _get_data_status() -> list[dict]:
    summary = real_summary()
    return [{
        "source": "Yahoo Finance (real prices)",
        "status": summary["status"],
        "note": summary["method"],
        "last_success": summary.get("fetched_at"),
        "jobs": [],
    }]


def _get_latest_results(
    sort_by: str = "score",
    sort_dir: str = "desc",
    min_score: float = 0,
    sector: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Only validated real snapshot rows; score means momentum percentile, not CAQS."""
    results = load_snapshot()["results"]

    # Apply filters
    if min_score:
        results = [r for r in results if r["score"] >= min_score]
    if sector:
        results = [r for r in results if sector.lower() in r.get("sector", "").lower()]
    if search:
        s = search.lower()
        results = [r for r in results if s in r["ticker"].lower() or s in r.get("name", "").lower()]

    # Sort
    reverse = sort_dir == "desc"
    if sort_by not in {"ticker", "name", "sector", "label", "price", "score", "change_1m"}:
        sort_by = "score"
    if sort_by in ("ticker", "name", "sector", "label"):
        results.sort(key=lambda r: r.get(sort_by, "") or "", reverse=reverse)
    else:
        results.sort(key=lambda r: r.get(sort_by) or 0, reverse=reverse)

    return results


def _get_stock_detail(ticker: str) -> dict:
    """Get full detail for a single stock."""
    universe = load_idx_universe_df()
    uni = universe[universe["ticker"] == ticker.upper()]
    if uni.empty:
        return {"found": False}

    row = uni.iloc[0]
    snapshot = load_snapshot()

    return {
        "found": True,
        "ticker": ticker.upper(),
        "name": row.get("name", ""),
        "sector": row.get("sector", ""),
        "board": row.get("board", ""),
        "prices": list(reversed(snapshot["prices"].get(ticker.upper(), []))),
        "features": snapshot.get("metrics", {}).get(ticker.upper(), {}),
        "scores": [],
        "real_summary": snapshot_summary(snapshot),
    }


# ── background run ────────────────────────────────────────────────────────────

def _run_screening_bg(run_id: str, run_date: str):
    job = _bg_jobs[run_id]
    try:
        job["status"] = "running"
        def progress(done, total):
            job.update(progress=done, total=total)
        snapshot = screen_real(run_date=run_date, progress=progress)
        job.update(status="success", summary=snapshot_summary(snapshot))
    except Exception as e:
        job.update(status="failed", error=str(e))
    finally:
        job["finished_at"] = time.time()
        _refresh_lock.release()


# ── page routes ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    summary = real_summary()
    pipeline = {"status": summary["status"], "run_date": summary.get("latest_data_date", "—"),
                "duration_s": None, "summary": summary}
    results = _get_latest_results()
    watchlist = _get_watchlist()
    data_status = _get_data_status()
    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "pipeline": pipeline,
        "results": results,
        "watchlist": watchlist,
        "data_status": data_status,
    })


@app.get("/screener", response_class=HTMLResponse)
async def screener(request: Request):
    universe = load_idx_universe_df()
    sectors = sorted(universe["sector"].dropna().unique().tolist())
    return TEMPLATES.TemplateResponse(request, "screener.html", {
        "sectors": sectors,
    })


@app.get("/stocks/{ticker}", response_class=HTMLResponse)
async def stock_detail(request: Request, ticker: str):
    detail = _get_stock_detail(ticker)
    if not detail.get("found"):
        return TEMPLATES.TemplateResponse(request, "not_found.html", {"ticker": ticker})
    watchlist = _get_watchlist()
    in_watchlist = any(w["ticker"] == ticker.upper() for w in watchlist)
    return TEMPLATES.TemplateResponse(request, "stock_detail.html", {
        "stock": detail,
        "in_watchlist": in_watchlist,
    })


@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request):
    wl = _get_watchlist()
    universe = load_idx_universe_df()
    uni_map = universe.set_index("ticker")
    items = []
    for w in wl:
        t = w["ticker"]
        info = uni_map.loc[t] if t in uni_map.index else pd.Series()
        items.append({
            "ticker": t,
            "name": str(info.get("name", "")),
            "sector": str(info.get("sector", "")),
            "added_at": w.get("added_at", ""),
        })
    return TEMPLATES.TemplateResponse(request, "watchlist.html", {"items": items})


@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "backtest.html", {})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    weights = _get_weights()
    return TEMPLATES.TemplateResponse(request, "settings.html", {"weights": weights})


@app.get("/data-status", response_class=HTMLResponse)
async def data_status_page(request: Request):
    sources = _get_data_status()
    return TEMPLATES.TemplateResponse(request, "data_status.html", {"sources": sources})


# ── API endpoints ─────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    run_date: date | None = None


@app.post("/api/runs")
async def start_run(req: RunRequest):
    rd = req.run_date or date.today()
    if rd > date.today():
        return JSONResponse({"error": "Future run date"}, status_code=422)
    if not _refresh_lock.acquire(blocking=False):
        return JSONResponse({"error": "Refresh already running"}, status_code=409)
    run_id = str(uuid4())
    _bg_jobs[run_id] = {"status": "queued", "progress": 0, "total": 0, "started_at": time.time()}
    try:
        threading.Thread(target=_run_screening_bg, args=(run_id, rd.isoformat()), daemon=True).start()
    except Exception as exc:
        _bg_jobs[run_id].update(status="failed", error=str(exc), finished_at=time.time())
        _refresh_lock.release()
        return JSONResponse({"error": "Could not start refresh", "run_id": run_id}, status_code=503)
    return {"run_id": run_id, "status": "started"}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    if run_id not in _bg_jobs:
        return JSONResponse({"error": "not found"}, status_code=404)
    return _bg_jobs[run_id]


@app.get("/api/runs/latest/results")
async def latest_results(
    sort_by: str = "score",
    sort_dir: str = "desc",
    min_score: float = 0,
    sector: str | None = None,
    search: str | None = None,
    format: str | None = None,
):
    results = _get_latest_results(sort_by, sort_dir, min_score, sector, search)
    if format == "csv":
        import io, csv
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["ticker", "name", "sector", "price", "score", "label", "change_1m", "score_kind"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
        return Response(content=buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=screener_results.csv"})
    return results


@app.get("/api/stocks/{ticker}")
async def api_stock_detail(ticker: str):
    detail = _get_stock_detail(ticker)
    if not detail.get("found"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return detail


@app.get("/api/watchlist")
async def api_watchlist():
    return _get_watchlist()


@app.post("/api/watchlist")
async def api_add_watchlist(request: Request):
    ticker = await _validated_ticker(request)
    if ticker is None:
        return JSONResponse({"error": "Valid universe ticker required"}, status_code=400)
    return _add_watchlist(ticker)


@app.delete("/api/watchlist")
async def api_remove_watchlist(request: Request):
    ticker = await _validated_ticker(request)
    if ticker is None:
        return JSONResponse({"error": "Valid universe ticker required"}, status_code=400)
    _remove_watchlist(ticker)
    return {"ok": True}


@app.get("/api/weights")
async def api_get_weights():
    return _get_weights()


@app.put("/api/weights")
async def api_save_weights(request: Request):
    return JSONResponse({"error": "Weight saving disabled: momentum percentile does not use CAQS weights"}, status_code=409)


@app.post("/api/backtests")
async def run_backtest(request: Request):
    return JSONResponse({"error": "Real backtest unavailable"}, status_code=501)


@app.get("/api/data-status")
async def api_data_status():
    return _get_data_status()


@app.get("/api/universe")
async def api_universe(sector: str | None = None):
    df = load_idx_universe_df()
    if sector:
        df = df[df["sector"].str.contains(sector, case=False, na=False, regex=False)]
    return df.to_dict(orient="records")


async def _validated_ticker(request):
    try:
        body = await request.json()
        ticker = body.get("ticker", "").strip().upper()
        return ticker if ticker in set(load_idx_universe_df()["ticker"]) else None
    except (ValueError, TypeError, AttributeError):
        return None
