# IDX Screener

Personal research project: real Indonesian stock prices, a momentum screener,
and a FastAPI dashboard with cyan/azure light and dark themes.

## Run locally

Install Python 3.10+ and uv. In this directory, run `uv sync`, then
`uv run python run.py`. Open http://127.0.0.1:8000 and select **Jalankan Screening**.
The refresh downloads six months of Yahoo daily prices in the background.
`uv run python screen_real.py` uses exactly the same screening service from the CLI.

## What the numbers mean

- Scores are equal-weight percentile ranks of 21/60-session adjusted returns,
  **not full CAQS**, predictions, confidence probabilities, or investment advice.
- Only the latest available session with positive volume and 20-session average
  traded value >= IDR 1 billion qualifies. Raw price histories and failures are retained.
- The bundled list is a **227-ticker subset**, not the complete/current IDX universe.
  Names, sectors, boards, and listing status require authoritative verification.
- No synthetic fallback. Missing fundamentals and backtests are not fabricated.
- Data comes from Yahoo via yfinance, may be delayed or inaccurate, and is subject
  to the provider's usage terms. This is not a licensed market-data feed.
- Legacy CLI CAQS/prediction experiments are separate from the real web screener.

## Structure

| Path | Purpose |
| --- | --- |
| `src/idxscreener/screening/real.py` | Download, validate, rank, atomically save snapshots |
| `src/idxscreener/web/` | FastAPI routes, templates and browser assets |
| `src/idxscreener/` | Existing CLI, ingestion, features and research modules |
| `configs/` | Local research configuration |
| `tests/` | Offline unit/regression checks |
| `reference/` | Product requirements and development notes |
| `output/real_screen/` | Ignored generated snapshots and local watchlist |

Old `idxscreener.db` data is not consumed by the real website and is not published.
Snapshots are saved atomically: a failed refresh preserves the last successful run.
One worker/instance is supported; refresh progress is in memory and is lost on restart.

## Verify

`uv run --with pytest python -m pytest -q` runs offline checks.
`node --check src/idxscreener/web/static/app.js` validates browser JavaScript syntax.
Network access is needed only for a real refresh, not for the tests.

## GitHub Pages (free static demo)

The `Deploy GitHub Pages` workflow downloads real Yahoo prices and renders the
existing read-only UI as HTML/JSON. Enable **Settings → Pages → GitHub Actions**.
The target URL is https://rexyraa.github.io/idx-screener/ .
Filtering, sorting, charts, theme switching, and snapshot CSV download run in the
browser. CSV exports the complete snapshot. Refresh, persistent watchlists, and
Python APIs require the local app; Pages cannot run FastAPI.
Data updates on pushes or manually via Actions, not on visitor requests.
Failed downloads fail the build and leave the previous deployment intact.
`uv run python build_pages.py` builds locally into the ignored `dist/` directory.

## Railway (optional Python hosting)

Deploy this repository using the included Dockerfile and `railway.json`.
Create a persistent volume mounted at `/data`; set `DATA_DIR=/data` and
`PUBLIC_DEMO=true`. Generate a public domain after `/healthz` passes.
Railway provides `PORT`; the container binds `0.0.0.0` and uses one worker.
The local launcher remains bound to loopback.

Public demo mode rejects **all write APIs**, including refresh/watchlist/settings.
To populate the Railway volume, run the administrative shell command
`python -c "from idxscreener.screening.real import screen_real; screen_real()"`
inside the deployed container, or upload a locally generated `snapshot.json` to
`/data`. Do not expose an unauthenticated live-refresh endpoint publicly.
Without a snapshot, the UI honestly displays an empty state.
Hosting costs, account access, market-data redistribution terms, and volume setup
must be reviewed before deployment. Never commit tokens, `.env`, or personal databases.