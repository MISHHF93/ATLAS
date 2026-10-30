"""evo-16 M1: every catalog asset gets a prediction or an explicit reason; the health rows carry last real data, last prediction, model version."""
from __future__ import annotations

import json
import pickle
import time

import pytest

from atlas.ai.ml.directional import live as LV
from atlas.ai.prediction import log as PL
from atlas.ai.prediction import service as S
from atlas.ai.prediction.pools import pool_of
from atlas.feeds.core import FeedBar
from atlas.feeds.feed import AtlasFeed
from atlas.feeds.store import FeedStore

NOW = 1_800_000_000.0   # fixed "now" so ages are deterministic


def _bars(inst, iv, n, last_end):
    d = S.DUR[iv]
    return [FeedBar(inst, iv, int(last_end - (n - k) * d), 100.0, 101.0, 99.0, 100.5, 10.0, "massive", NOW, True) for k in range(n)]


@pytest.fixture()
def world(tmp_path):
    store = FeedStore(":memory:")
    store.ingest(_bars("SPY", "1d", 400, NOW - 3600) + _bars("AAPL", "1d", 120, NOW - 3600) + _bars("EUR_USD", "1d", 400, NOW - 3600)
                 + _bars("BTCUSDT", "15m", 500, NOW - 30))
    feed = AtlasFeed(store)
    root = tmp_path / "dir"
    for g, insts in (("equity-1d", ["SPY"]), ("crypto-15m", ["BTCUSDT"])):
        d = root / g
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"group": g, "label": "research / below gate", "instruments": insts, "data_digest": "abcdef0123456789"}))
        (d / "model.pkl").write_bytes(pickle.dumps({"stub": True}))
    LV._CACHE.clear()
    PL.reset()
    return feed, root, str(tmp_path / "log.sqlite")


def test_pool_of_classes():
    assert pool_of("BTCUSDT", "crypto") == "crypto" and pool_of("AAPL", "equity") == "equity" and pool_of("SPY", "etf") == "equity"
    assert pool_of("EUR_USD", "fx") == "fx" and pool_of("GLD", "etf") == "metal" and pool_of("GC", "future") == "metal"
    assert pool_of("ES", "future") == "index" and pool_of("CL", "future") == "other"


def test_every_catalog_asset_has_prediction_or_reason(world):
    feed, root, lp = world
    rep = S.coverage(feed, now=NOW, root=root, log_path=lp)
    assert rep["n_assets"] == len(feed.instruments.all()) >= 200
    assert rep["execution_permission"] == "none"
    for r in rep["assets"]:
        assert r["status"] == "predicted" or r["reason"], r["instrument"]
        assert set(r["intervals"]) == set(S.INTERVALS)
    by = {r["instrument"]: r for r in rep["assets"]}
    assert by["SPY"]["status"] == "not_yet_run" and by["SPY"]["model_version"] == "equity-1d@abcdef01"
    assert "no prediction has been computed" in by["SPY"]["reason"] and by["SPY"]["last_prediction_at"] is None
    assert by["AAPL"]["status"] == "not_in_pool" and "AAPL" in by["AAPL"]["reason"]
    assert by["EUR_USD"]["status"] == "no_model" and by["EUR_USD"]["pool"] == "fx"
    assert by["MSFT"]["status"] == "no_data" and "No stored bars" in by["MSFT"]["reason"]
    assert by["SPY"]["eod_only"] is True and by["BTCUSDT"]["eod_only"] is False
    assert by["BTCUSDT"]["last_real_age"] == "30s" and by["BTCUSDT"]["intervals"]["15m"]["stale"] is False and by["SPY"]["intervals"]["1d"]["last_real_age"] == "60m"


def test_sweep_logs_predictions_and_health_shows_them(world):
    feed, root, lp = world
    calls = []

    def stub(feed_, sym, iv, now=None, root=None, log_path=None):
        calls.append((sym, iv))
        res = {"status": "ok", "symbol": sym, "interval": iv, "computed_at": NOW, "label": "research / below gate", "direction": "up", "probability": 0.55}
        PL.record(res, S.model_version(sym, iv, root), log_path)
        return res

    out = S.sweep(feed, now=NOW, root=root, log_path=lp, predictor=stub)
    assert sorted(calls) == [("BTCUSDT", "15m"), ("SPY", "1d")]      # AAPL (not in pool) and EUR_USD (no model) are skipped, not guessed
    assert out["ok"] == 2 and out["skipped"] >= 2
    rep = S.coverage(feed, now=NOW + 60, root=root, log_path=lp)
    spy = {r["instrument"]: r for r in rep["assets"]}["SPY"]
    assert spy["status"] == "predicted" and spy["last_prediction_at"] == NOW and spy["reason"] == "" and spy["label"] == "research / below gate"
    assert rep["status_counts"]["predicted"] == 2


def test_predict_asset_never_raises_and_logs_error(world):
    feed, root, lp = world
    res = S.predict_asset(feed, "NOPE", "1d", now=NOW, root=root, log_path=lp)
    assert res["status"] in ("error", "no_model", "insufficient_history")
    assert PL.latest(lp)[("NOPE", "1d")]["last_ok_at"] is None


def test_prediction_log_is_separate_from_bar_store(world):
    feed, root, lp = world
    before = feed.store._fetchone("SELECT COUNT(*) FROM bar_revisions")[0]
    S.sweep(feed, now=NOW, root=root, log_path=lp, predictor=lambda *a, **k: {"status": "ok", "symbol": "SPY", "interval": "1d", "computed_at": NOW})
    assert feed.store._fetchone("SELECT COUNT(*) FROM bar_revisions")[0] == before


def test_coverage_endpoint_and_sweep_endpoint(world, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from atlas.api import prediction_api as A
    feed, root, lp = world
    monkeypatch.setattr(A, "_feed", lambda: feed)
    monkeypatch.setenv("ATLAS_PREDICTION_LOG", lp)
    monkeypatch.setenv("ATLAS_ML_DIRECTIONAL", str(root))
    app = FastAPI()
    app.include_router(A.router)
    c = TestClient(app)
    body = c.get("/api/ai/predictions/coverage?fresh=true").json()
    assert body["n_assets"] >= 200 and body["store_present"] and "pools" in body
    assert {p["pool"] for p in body["pools"]} >= {"equity", "crypto", "fx", "metal", "index"}
    assert c.get("/api/ai/predictions/coverage?symbols=SPY").json()["n_assets"] == 1
    assert c.post("/api/ai/predictions/sweep?intervals=5m").status_code == 400
    assert c.get("/api/ai/predictions/sweep").json()["running"] in (True, False)
