"""Render the existing read-only UI for GitHub Pages (no Python server required)."""

import asyncio
import csv
import json
import os
import re
import shutil
from pathlib import Path

os.environ["PUBLIC_DEMO"] = "true"

from starlette.requests import Request
from idxscreener.screening.real import load_snapshot, screen_real
from idxscreener.web import app as web

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dist"
BASE = "/idx-screener"


async def build():
    snapshot = load_snapshot()
    if not snapshot["results"] or os.environ.get("REFRESH_DATA") == "true":
        snapshot = screen_real()
    OUTPUT.mkdir(exist_ok=True)
    shutil.copytree(web.BASE_DIR / "static", OUTPUT / "static", dirs_exist_ok=True)
    web.load_snapshot = lambda: snapshot  # Reuse one consistent snapshot throughout the build.
    web._get_watchlist = lambda: []  # Never publish the owner's watchlist.
    pages = {"": web.dashboard, "screener": web.screener,
             "watchlist": web.watchlist_page, "backtest": web.backtest_page,
             "settings": web.settings_page, "data-status": web.data_status_page}
    for ticker in snapshot["prices"]:
        pages[f"stocks/{ticker}"] = None
    for path, route in pages.items():
        request = Request({"type": "http", "method": "GET", "path": "/" + path,
                           "headers": [], "query_string": b""})
        response = await route(request) if route else await web.stock_detail(request, path.split("/")[1])
        html = response.body.decode("utf-8")
        html = re.sub(r'(href|src)="/([^"?#]*)"',
                      lambda m: f'{m[1]}="{BASE}/{m[2]}' + ('/' if m[1] == 'href' and m[2] and not Path(m[2]).suffix else '') + '"', html)
        html = html.replace('<script src=', '<script>window.STATIC_SITE=true;window.SITE_BASE=' + json.dumps(BASE) + ';</script><script src=', 1)
        target = OUTPUT / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    (OUTPUT / "results.json").write_text(json.dumps(snapshot["results"], allow_nan=False), encoding="utf-8")
    with (OUTPUT / "screening.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(snapshot["results"][0]))
        writer.writeheader()
        writer.writerows(snapshot["results"])
    (OUTPUT / ".nojekyll").touch()
    assert (OUTPUT / "screener/index.html").exists()
    assert 'window.STATIC_SITE=true' in (OUTPUT / "index.html").read_text(encoding="utf-8")
    for page in OUTPUT.rglob("*.html"):
        for url in re.findall(r'(?:href|src)="([^"?#]+)"', page.read_text(encoding="utf-8")):
            if url.startswith(BASE + "/"):
                assert (OUTPUT / url.removeprefix(BASE + "/")).exists(), url
    print(f"Built {len(pages)} pages, {len(snapshot['results'])} screened stocks at {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(build())