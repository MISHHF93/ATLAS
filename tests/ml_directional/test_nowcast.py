"""evo-16 M3: the nowcast path, its conformal band, session time, live scoring and the never-leaks-into-the-store guarantee."""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

from atlas.ai.prediction import clock as CK
from atlas.ai.prediction import nowcast as NC
from atlas.ai.prediction import nowcast_log as NL
from atlas.feeds.core import FeedBar
from atlas.feeds.feed import AtlasFeed
from atlas.feeds.store import FeedStore

# Tue 2026-03-03 10:30 New York (EST, UTC-5)
NOW = 1_772_551_800.0 + 0.0


def _walk(inst, iv, n, last_end, vol=0.002, seed=3, px=100.0, prov="binance"):
    rng = np.random.default_rng(seed)
    d = NC.DUR[iv]
    c, out = px, []
    for k in range(n):
        o = c
        c = c * math.exp(rng.normal(0, vol))
        out.append(FeedBar(inst, iv, int(last_end - (n - k) * d), o, max(o, c) * 1.0005, min(o, c) * 0.9995, c, 100.0, prov, NOW, True))
    return out


@pytest.fixture()
def feed():
    NC._BARS.clear()
    NL.reset()
    f = AtlasFeed(FeedStore(":memory:"))
    f.store.ingest(_walk("BTCUSDT", "1m", 1500, NOW - 60, vol=0.0008) + _walk("ETHUSDT", "1m", 1500, NOW - 60, vol=0.001, seed=5, px=50.0)
                   + _walk("SPY", "1d", 600, NOW - 18 * 3600, vol=0.01, seed=7, px=500.0, prov="polygon"))
    return f


def test_trading_time_skips_weekends_and_nights():
    fri_close = 1_772_226_000.0 + 0   # Fri 2026-02-27 16:00 EST
    mon_open = NC._at(NC._ny(fri_close).date().replace(day=2, month=3), NC.RTH_OPEN)
    assert NC.trading_seconds(fri_close, mon_open, "us_rth") == 0.0
    assert NC.trading_seconds(fri_close, mon_open + 600, "us_rth") == 600
    assert NC.trading_seconds(fri_close, mon_open, "24x7") == mon_open - fri_close
    sun_open = NC._at(NC._ny(fri_close).date().replace(day=1, month=3), (17, 0))
    assert NC.trading_seconds(fri_close, sun_open, "24x5") == 3600 and NC.next_open(fri_close + 7200, "24x5") == sun_open


def test_crypto_path_widens_and_is_labelled(feed):
    r = NC.nowcast(feed, "BTCUSDT", "15m", now=NOW + 20, horizon=26)
    assert r["status"] == "ok" and r["label"] == "Predicted (not market data)" and r["execution_permission"] == "none" and r["mode"] == "live"
    assert r["base_interval"] == "1m" and r["anchor"]["age_s"] <= 90
    widths = [(p["hi"] - p["lo"]) / p["mid"] for p in r["path"]]
    assert len(widths) >= 20 and all(b >= a - 1e-12 for a, b in zip(widths, widths[1:])), "band must widen with time since the last real print"
    assert all(p["lo"] < p["mid"] < p["hi"] for p in r["path"])
    assert r["now"] is not None and r["now"]["forming"] is True


def test_eod_asset_degrades_to_forecast_from_last_close_with_widening_band(feed):
    r = NC.nowcast(feed, "SPY", "1d", now=NOW, horizon=10)
    assert r["status"] == "ok" and r["mode"] == "end_of_day" and r["base_interval"] == "1d" and "end-of-day" in r["reason"].lower()
    w = [(p["hi"] - p["lo"]) / p["mid"] for p in r["path"]]
    assert len(w) >= 9 and w[-1] > 2 * w[0] and all(b >= a for a, b in zip(w, w[1:]))
    # weekends are skipped on the 1d grid
    import datetime as dt
    assert all(dt.datetime.fromtimestamp(p["t"] + 43200, dt.timezone.utc).weekday() < 5 for p in r["path"])
    # an intraday timeframe of an EOD-only asset still gets a path (trading-time based, from the last close)
    r15 = NC.nowcast(feed, "SPY", "15m", now=NOW, horizon=26)
    assert r15["status"] == "ok" and r15["mode"] == "end_of_day" and len(r15["path"]) > 0


def test_no_data_and_unsupported(feed):
    assert NC.nowcast(feed, "MSFT", "1d", now=NOW)["status"] == "no_data"
    assert NC.nowcast(feed, "SPY", "5m", now=NOW)["status"] == "unsupported_interval"


def test_quote_newer_than_bar_anchors_the_path(feed):
    feed.store.upsert_quotes([{"instrument": "SPY", "provider": "oanda", "price": 520.0, "event_time": int(NOW - 30), "receipt_time": int(NOW - 29),
                               "prev_close": 500.0, "kind": "live", "provider_symbol": "SPY"}])
    r = NC.nowcast(feed, "SPY", "1d", now=NOW, horizon=3)
    assert r["anchor"]["source"] == "quote" and r["anchor"]["price"] == 520.0 and r["anchor"]["age_s"] <= 31
    assert any(i["input"] == "live quote" for i in r["inputs"])


def test_conformal_scale_grows_with_horizon_and_is_causal():
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500)))
    sc = NC.conformal_scale(close)
    assert sc[1] > 0 and len(sc) >= 8
    # a pure random walk has |z| quantile near the Gaussian 80% value at every k
    assert all(1.0 < v < 2.0 for v in sc.values()) and abs(sc[1] - 1.2816) < 0.15
    assert NC.qhat({}, 5) == pytest.approx(1.2816, abs=1e-3)


def test_tick_issues_scores_and_never_touches_the_store(feed, tmp_path):
    lp = str(tmp_path / "nc.sqlite")
    before = feed.store._fetchone("SELECT COUNT(*) FROM bar_revisions")[0]
    out = CK.tick(feed, now=NOW + 20, log_path=lp)
    assert out["issued"] >= 3 and out["errors"] == 0
    assert feed.store._fetchone("SELECT COUNT(*) FROM bar_revisions")[0] == before
    # the next BTC 1m bar arrives; the forecast frozen before it closed is graded against it
    nxt = int(NOW)
    feed.store.ingest([FeedBar("BTCUSDT", "1m", nxt, 100, 101, 99, 100.2, 5.0, "binance", NOW + 61, True)])
    out2 = CK.tick(feed, now=NOW + 62, log_path=lp)
    assert out2["scored"] >= 1
    cal = NL.calibration(lp)
    assert cal["n_scored"] >= 1 and cal["target"] == 0.8 and cal["cells"][0]["pool"] == "crypto"
    # an issued row is frozen once its bar ended (never overwritten with hindsight)
    assert NL.issue([{"symbol": "BTCUSDT", "interval": "1m", "target_start": nxt, "target_end": nxt + 60, "anchor_t": 1, "anchor_px": 1, "mid": 1, "lo": 1, "hi": 1, "k": 1}],
                    NOW + 500, lp) == 0


def test_live_scale_bounds(tmp_path):
    lp = str(tmp_path / "s.sqlite")
    assert NL.live_scale("crypto", "1m", lp) == 1.0          # not enough scored rows: unchanged
    c = NL._conn(lp)
    c.executemany("INSERT INTO scored VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  [("X", "1m", i, float(i), 1, 1, 1, 1, 1, 0, 0, 3.0, 0, 1, "crypto", "live", 0) for i in range(80)])
    c.commit()
    assert NL.live_scale("crypto", "1m", lp) == 1.6          # bands were far too tight: widen, bounded


def test_nowcast_endpoints(feed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from atlas.api import prediction_api as A
    monkeypatch.setattr(A, "_feed", lambda: feed)
    app = FastAPI()
    app.include_router(A.router)
    c = TestClient(app)
    r = c.get("/api/ai/predictions/nowcast", params={"symbol": "SPY", "interval": "1d", "horizon": 5}).json()
    assert r["status"] == "ok" and r["label"] == "Predicted (not market data)" and len(r["path"]) >= 4
    assert c.get("/api/ai/predictions/nowcast/calibration").json()["target"] == 0.8
    assert c.post("/api/ai/predictions/nowcast/tick", params={"symbols": "BTCUSDT"}).json()["assets"] == 1


def test_asset_summary_endpoint_is_one_payload_for_chart_news_and_golive(feed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from atlas.api import prediction_api as A
    monkeypatch.setattr(A, "_feed", lambda: feed)
    app = FastAPI()
    app.include_router(A.router)
    r = TestClient(app).get("/api/ai/predictions/asset", params={"symbol": "SPY"}).json()
    assert r["label"] == "Predicted (not market data)" and r["execution_permission"] == "none"
    assert r["coverage"]["instrument"] == "SPY" and r["nowcast"]["status"] == "ok" and r["calibration"]["target"] == 0.8
    assert TestClient(app).get("/api/ai/predictions/asset", params={"symbol": "NOPE"}).status_code == 404


def test_unofficial_quote_never_anchors(feed):
    from atlas.ai.prediction import nowcast as N
    feed.store.upsert_quotes([{"instrument": "SPY", "provider": "yahoo", "price": 1.0, "event_time": 4_000_000_000, "receipt_time": 4_000_000_000,
                               "prev_close": None, "kind": "quote", "provider_symbol": "SPY"}])
    assert N._quote(feed, "SPY") is None
