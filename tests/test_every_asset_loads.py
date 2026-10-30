"""Every catalog asset loads on every chart timeframe: bars, the labelled predicted line, or a stated cause. Never an error, never blank.

Mirrors what the chart asks (/api/ai/chart/overlays + /api/ai/predictions/nowcast) over the whole catalog (10k+ rows).  The overlay route is
exercised for every real asset and a stride of the placeholder ids; the nowcast and the cause classifier for every row."""
from __future__ import annotations

import math
import threading
import time

import pytest
from fastapi.testclient import TestClient

from atlas.ai.prediction import nowcast as NC, service as S
from atlas.api import chart_overlays as co
from atlas.api.app import app
from atlas.feeds.core import FeedBar
from atlas.feeds.feed import AtlasFeed
from atlas.feeds.store import FeedStore
from atlas.marketdata.catalog import GLOBAL_ASSET_CATALOG, classify_catalog_category

IVS = ("1m", "5m", "15m", "1h", "4h", "1d")
NOW = time.time()


def chart_symbol(s: str) -> str:
    u = s.upper()
    if u.endswith("-USD"):
        return u[:-4] + "USDT"
    if ":" in u and u.split(":", 1)[0].isalpha():
        return u.split(":", 1)[1]
    return u


def cat(r) -> str:
    return classify_catalog_category(r["symbol"], r.get("asset_class", ""), r.get("exchange", ""))[0]


def _all_rows():
    out, off = [], 0
    while True:
        r = GLOBAL_ASSET_CATALOG.search(query="", limit=250, offset=off, include_placeholders=True)
        rows = r.get("results") or []
        if not rows:
            break
        out.extend(rows)
        off += len(rows)
        if off >= r.get("total_matching", 0):
            break
    return out


def _bars(inst, iv, n, last_end, prov, px=100.0):
    d = {"1m": 60, "15m": 900, "1h": 3600, "1d": 86400}[iv]
    out, c = [], px
    for k in range(n):
        o = c
        c = c * (1 + 0.002 * math.sin(k / 7.0))
        out.append(FeedBar(inst, iv, int(last_end - (n - k) * d), o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, 100.0, prov, NOW, True))
    return out


@pytest.fixture()
def feed(monkeypatch):
    NC._BARS.clear()
    f = AtlasFeed(FeedStore(":memory:"))
    f.store.ingest(_bars("BTCUSDT", "1m", 600, NOW - 60, "binance") + _bars("BTCUSDT", "1d", 400, NOW - 3600, "binance")
                   + _bars("SPY", "1d", 600, NOW - 18 * 3600, "polygon", 500.0))
    monkeypatch.setattr(co, "_feed", lambda: f)
    monkeypatch.setattr("atlas.api.feeds_api._feed", lambda: f)
    monkeypatch.setattr(co, "_ENSURE_WAIT_S", 0.05)
    return f


def test_catalog_is_swept_in_full():
    rows = _all_rows()
    assert len(rows) >= 10_000
    cats = {cat(r) for r in rows}
    assert "placeholder" in cats          # the placeholder ids are part of the catalog and are covered below


def test_every_catalog_row_has_a_renderable_state(feed):
    rows = _all_rows()
    seen_cause = {}
    for r in rows:
        sym = chart_symbol(r["symbol"])
        for iv in ("1m", "1d"):
            nc = NC.nowcast(feed, sym, iv)
            assert nc["status"] in ("ok", "no_data", "placeholder"), (sym, iv, nc["status"])
            if nc["status"] != "ok":
                assert nc.get("cause") and nc.get("reason"), (sym, iv, nc)
                seen_cause[nc["cause"]] = seen_cause.get(nc["cause"], 0) + 1
        if cat(r) == "placeholder":
            assert S.is_placeholder(sym), sym
    assert seen_cause.get("placeholder", 0) > 9000


def test_overlays_never_error_for_real_assets_and_a_placeholder_stride(feed):
    rows = _all_rows()
    pick = [r for r in rows if cat(r) != "placeholder"] + [r for r in rows if cat(r) == "placeholder"][::97]
    c = TestClient(app)
    bad = []
    for r in pick:
        sym = chart_symbol(r["symbol"])
        for iv in IVS:
            res = c.get("/api/ai/chart/overlays", params={"symbol": sym, "interval": iv, "bar_type": "time", "limit": 600})
            if res.status_code != 200:
                bad.append((sym, iv, res.status_code))
                continue
            d = res.json()
            if d.get("status") == "ok" and d.get("bars"):
                continue
            nc = NC.nowcast(feed, sym, iv)
            labelled = bool(d.get("cause") and d.get("reason"))
            if not ((nc["status"] == "ok" and nc.get("path")) or labelled):
                bad.append((sym, iv, "blank"))
    assert not bad, bad[:20]


def test_seeded_assets_draw_bars_or_the_predicted_line(feed):
    c = TestClient(app)
    d = c.get("/api/ai/chart/overlays", params={"symbol": "BTCUSDT", "interval": "1m", "limit": 300}).json()
    assert d["status"] == "ok" and d["bars"]
    d = c.get("/api/ai/chart/overlays", params={"symbol": "SPY", "interval": "1m", "limit": 300}).json()
    nc = NC.nowcast(feed, "SPY", "1m")
    assert not d.get("bars") and nc["status"] == "ok" and nc["path"] and nc["mode"] == "end_of_day"


def test_placeholder_and_unmapped_are_labelled_not_blank(feed):
    d = TestClient(app).get("/api/ai/chart/overlays", params={"symbol": "EQ0042", "interval": "1h"}).json()
    assert d["status"] == "no_data" and d["cause"] == "placeholder" and "placeholder" in d["reason"].lower()
    nc = NC.nowcast(feed, "PERP011USDT", "5m")
    assert nc["status"] == "placeholder" and nc["cause"] == "placeholder"


def test_slow_provider_refresh_never_holds_the_request(feed):
    """A rate-limited free plan used to sleep inside the request until the gateway answered 504 at 60 s."""
    gate = threading.Event()
    calls = []

    class Slow:
        def ensure_recent(self, sym, iv):
            calls.append((sym, iv))
            gate.wait(5)
            return True

    t0 = time.monotonic()
    done = co.ensure_bounded(Slow(), "ABBV", "15m", wait=0.1)
    assert not done and time.monotonic() - t0 < 1.0
    again = co.ensure_bounded(Slow(), "ABBV", "15m", wait=0.1)       # still in flight: no second fetch, no wait
    assert again is False and len(calls) == 1
    gate.set()
    time.sleep(0.3)
    assert co.ensure_bounded(Slow(), "ABBV", "15m", wait=1.0) is True
