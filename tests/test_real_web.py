"""Offline checks: python -m unittest discover -s tests -p test_real_web.py."""
import asyncio
import importlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import numpy as np
import pandas as pd

from idxscreener.screening import real

web = importlib.import_module("idxscreener.web.app")


async def request(method, path, body=None):
    try:
        import httpx
    except ImportError:
        messages = []
        finished = asyncio.Event()
        sent = False
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps(body or {}).encode()}
            await finished.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                finished.set()
        await web.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                       "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                       "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")],
                       "client": ("127.0.0.1", 1), "server": ("test", 80)}, receive, send)
        return messages[0]["status"], b"".join(m.get("body", b"") for m in messages).decode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url="http://test") as client:
        response = await client.request(method, path, json=body)
        return response.status_code, response.text


class RealScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.prices = pd.DataFrame({"Close": np.arange(1000., 1062.), "Adj Close": np.arange(1000., 1062.),
                                    "Volume": 2_000_000.}, index=pd.date_range(end=date.today(), periods=62))
        self.universe = pd.DataFrame([{"ticker": "BBCA", "name": "Bank", "sector": "Finance"},
                                      {"ticker": "BAD", "name": "Bad", "sector": "Other"}])

    def snapshot(self):
        raw = pd.concat({"BBCA.JK": self.prices, "BAD.JK": self.prices * np.nan}, axis=1)
        updates = []
        with patch.object(real.yf, "download", return_value=raw) as download:
            snapshot = real.screen_real(data_dir=self.directory, universe=self.universe,
                                        progress=lambda *args: updates.append(args))
        self.assertEqual(download.call_args.kwargs["timeout"], 10)
        self.assertFalse(download.call_args.kwargs["threads"])
        self.assertEqual(download.call_args.kwargs["group_by"], "ticker")
        self.assertEqual(download.call_args.kwargs["period"], "6mo")
        self.assertEqual(updates, [(1, 2), (2, 2)])
        return snapshot

    def test_price_validation(self):
        self.assertAlmostEqual(real.price_metrics(self.prices)["return_1m_pct"], (1061 / 1040 - 1) * 100)
        for column, value in [("Close", 0), ("Close", -1), ("Adj Close", np.inf), ("Close", np.nan), ("Volume", -1)]:
            bad = self.prices.copy()
            bad.loc[bad.index[-1], column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                real.price_metrics(bad)
        with self.assertRaises(ValueError):
            real.price_metrics(self.prices.iloc[:60])

    def test_snapshot_and_preservation(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["summary"]["coverage"], .5)
        self.assertEqual(snapshot["summary"]["latest_data_date"], date.today().isoformat())
        self.assertEqual(len(snapshot["prices"]["BBCA"]), 62)
        self.assertEqual(snapshot["results"][0]["score_kind"], "momentum_percentile")
        original = (self.directory / "snapshot.json").read_bytes()
        with patch.object(real.yf, "download", side_effect=RuntimeError("offline")), self.assertRaises(RuntimeError):
            real.screen_real(data_dir=self.directory, universe=self.universe)
        with patch.object(real.yf, "download", return_value=pd.DataFrame()), self.assertRaises(RuntimeError):
            real.screen_real(data_dir=self.directory, universe=self.universe)
        with patch.object(real.os, "replace", side_effect=OSError("disk")), self.assertRaises(OSError):
            real.write_snapshot(snapshot, self.directory)
        with self.assertRaises(ValueError):
            real.write_snapshot({"bad": float("nan")}, self.directory)
        self.assertEqual((self.directory / "snapshot.json").read_bytes(), original)
        self.assertEqual(real.load_snapshot(self.directory), snapshot)
        snapshot["summary"]["latest_data_date"] = "2000-01-01"
        self.assertEqual(real.snapshot_summary(snapshot)["status"], "stale")

    def test_web_endpoints(self):
        snapshot = self.snapshot()
        with patch.object(web, "load_snapshot", return_value=snapshot), patch.object(web, "DATA_DIR", self.directory), patch.object(web, "PUBLIC_DEMO", False):
            for path in ["/healthz", "/", "/stocks/BBCA", "/api/runs/latest/results"]:
                self.assertEqual(asyncio.run(request("GET", path))[0], 200, path)
            with patch.dict("sys.modules", {"httpx": None}):
                self.assertEqual(asyncio.run(request("GET", "/healthz"))[0], 200)
            status, body = asyncio.run(request("GET", "/api/stocks/BBCA"))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["scores"], [])
            self.assertEqual(len(json.loads(body)["prices"]), 62)
            self.assertEqual(asyncio.run(request("POST", "/api/watchlist", {"ticker": "INVALID"}))[0], 400)
            self.assertEqual(asyncio.run(request("POST", "/api/watchlist", {"ticker": "bbca"}))[0], 200)
            self.assertEqual(asyncio.run(request("PUT", "/api/weights", {}))[0], 409)
            for rd in ["invalid", (date.today() + timedelta(days=1)).isoformat()]:
                self.assertEqual(asyncio.run(request("POST", "/api/runs", {"run_date": rd}))[0], 422)
            with patch.object(web.threading.Thread, "start"):
                status, body = asyncio.run(request("POST", "/api/runs", {}))
                self.assertEqual(status, 200)
                run_id = json.loads(body)["run_id"]
                UUID(run_id)
                try:
                    self.assertEqual(asyncio.run(request("POST", "/api/runs", {}))[0], 409)
                finally:
                    with patch.object(web, "screen_real", side_effect=RuntimeError("offline")):
                        web._run_screening_bg(run_id, date.today().isoformat())
                self.assertEqual(web._bg_jobs[run_id]["status"], "failed")
                self.assertFalse(web._refresh_lock.locked())
        with patch.object(web, "PUBLIC_DEMO", True):
            for method in ["POST", "PUT", "DELETE", "PATCH"]:
                self.assertEqual(asyncio.run(request(method, "/api/watchlist", {}))[0], 403)


if __name__ == "__main__":
    unittest.main()