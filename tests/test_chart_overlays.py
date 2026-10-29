"""/api/ai/chart/overlays: read-only, honest per-layer status, execution_permission none."""
from __future__ import annotations

import math
from types import SimpleNamespace

from fastapi.testclient import TestClient

from atlas.api import chart_overlays as co
from atlas.api.app import app


def _rows(n=900, step=3600, provider="binance", **extra):
    t0 = 1_700_000_000 - 1_700_000_000 % 86400
    out = []
    for i in range(n):
        c = 100 + 5 * math.sin(i / 25) + i * 0.01
        out.append(SimpleNamespace(event_time=t0 + i * step, open=c - 0.2, high=c + 0.6, low=c - 0.7, close=c, volume=10 + i % 7,
                                   provider=provider, **extra))
    return out


class FakeFeed:
    def __init__(self, **extra):
        self.extra = extra

    def bars(self, sym, iv):
        if sym != "BTCUSDT":
            return []
        return _rows(400, 86400, **self.extra) if iv == "1d" else _rows(900, {"1h": 3600, "15m": 900}.get(iv, 3600), **self.extra) if iv in ("1h", "15m") else []


def test_no_feed_is_graceful(monkeypatch):
    monkeypatch.setattr(co, "_feed", lambda: None)
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTC-USD&interval=1h").json()
    assert d["status"] == "no_data" and d["bars"] == [] and d["execution_permission"] == "none"
    assert d["symbol"] == "BTCUSDT"


def test_bad_params():
    c = TestClient(app)
    assert c.get("/api/ai/chart/overlays?interval=7m").status_code == 400
    assert c.get("/api/ai/chart/overlays?bar_type=bogus").status_code == 400


def test_layers_from_real_shaped_feed(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: FakeFeed())
    c = TestClient(app)
    d = c.get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=1h&bar_type=heikin_ashi&limit=300").json()
    assert d["status"] == "ok" and len(d["bars"]) == 300
    assert d["provider"]["provider"] == "binance" and d["provider"]["delay_label"] == "not tagged"
    assert d["display"]["kind"] == "heikin_ashi" and d["display"]["bars"]
    L = d["layers"]
    assert set(co.LAYERS) <= set(L)
    assert L["vwap"]["status"] == "ok" and L["volume_profile"]["status"] == "ok"
    assert L["regimes"]["status"] == "ok"
    # evo-10: session VWAP resets per session, anchored VWAP from a confirmed swing pivot, session spans, model read
    assert L["vwap"]["session_kind"] == "utc_day" and L["vwap"]["sessions"]["status"] == "ok" and L["vwap"]["sessions"]["spans"]
    an = L["vwap"]["anchored"]
    assert an["status"] == "ok" and an["anchor"]["confirmed_at"] > an["anchor"]["time"] and an["points"][0]["time"] == an["anchor"]["time"]
    assert L["model_prediction"]["status"] == "no_model" and L["model_prediction"]["execution_permission"] == "none"
    assert "probability" not in L["model_prediction"]
    # no evolution run in the empty registry: ML layers say so, nothing invented
    assert L["ml_markers"]["items"] == [] and L["predictions"]["status"] == "unavailable"
    assert d["ml_panel"]["evolution"] is None and d["ml_panel"]["execution_permission"] == "none"
    assert "order" not in str(sorted(L)).lower()


def test_4h_resampled_and_provider_tag(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: FakeFeed(realtime=False, delay_s=900))
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=4h").json()
    assert d["provider"]["built"] == "resampled from 1h feed bars"
    assert d["provider"]["delay_label"] == "delayed 900s"
    assert all(b["time"] % 14400 == 0 for b in d["bars"])
    d2 = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=1h&bar_type=tick").json()
    assert d2["display"]["status"] == "unavailable"


class AltFeed:
    """An alt with only 15m stored (like the evo7 alts): 1h must be resampled from complete 15m hours."""

    def bars(self, sym, iv):
        if sym != "SOLUSDT" or iv != "15m":
            return []
        rows = _rows(900, 900)
        return rows[:5] + rows[6:]  # one gap: that hour must be dropped, not invented


def test_1h_resampled_from_15m_when_no_stored_1h(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: AltFeed())
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=SOLUSDT&interval=1h").json()
    assert d["status"] == "ok"
    assert d["provider"]["built"].startswith("resampled from 15m")
    assert all(b["time"] % 3600 == 0 for b in d["bars"])
    assert len(d["bars"]) == 900 // 4 - 1  # the hour with a missing 15m bar is dropped


class MinuteTail:
    """Stored 15m stops, and the following minutes are already in the store."""

    def bars(self, sym, iv, start=None, end=None):
        if sym != "BTCUSDT":
            return []
        if iv == "15m":
            return _rows(10, 900)
        if iv != "1m":
            return []
        last = _rows(10, 900)[-1].event_time
        mins = []
        for i in range(30):
            t = last + 900 + i * 60
            if start is not None and t < start:
                continue
            c = 50 + i
            mins.append(SimpleNamespace(event_time=t, open=c, high=c + 1, low=c - 1, close=c + 0.4, volume=4, provider="binance", confirmed=True, receipt_time=t + 60))
        return mins


def test_15m_chart_extends_through_newer_one_minute_bars(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: MinuteTail())
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=15m&limit=50").json()
    last_stored = 1_700_000_000 - 1_700_000_000 % 86400 + 9 * 900
    assert d["status"] == "ok"
    assert d["bars"][-1]["time"] == last_stored + 1800
    assert "extended from 1m" in d["provider"]["built"]
    assert len(d["bars"]) == 12


def test_1h_prefers_stored_1h(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: FakeFeed())
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=1h").json()
    assert d["provider"]["built"] == "feed bars"


def test_live_walk_forward_ml_probability_and_predictions_with_evolution_run(monkeypatch):
    """When an evolution run exists, walk-forward OOS ML probability, predictions, and EV_R work on 15m/1h across symbols."""
    monkeypatch.setattr(co, "_feed", lambda: FakeFeed())
    c = TestClient(app)
    d = c.get("/api/ai/chart/overlays?symbol=BTC-USD&interval=15m&limit=400").json()
    assert d["status"] == "ok"
    assert d["execution_permission"] == "none"
    assert d["market_session"]["venue_id"] == "CRYPTO_24_7"
    assert d["market_session"]["is_open"] is True
    L = d["layers"]
    assert L["ml_probability"]["status"] == "ok"
    assert len(L["ml_probability"]["points"]) > 0
    assert L["predictions"]["status"] == "ok"
    assert len(L["predictions"]["items"]) > 0
    cal = L["predictions"]["calibration"]
    assert cal is not None
    assert "ev_r_per_opportunity" in cal and "take_all_ev" in cal and "brier_skill" in cal and "fitness" in cal
    ev_metrics = d["ml_panel"]["evolution"]["metrics"]
    assert "ev_r_per_opportunity" in ev_metrics and "fitness" in ev_metrics


def test_market_sessions_endpoint():
    c = TestClient(app)
    res = c.get("/api/market/sessions?symbols=BTC-USD,GC,SI,SPY,GLD,EUR_USD").json()
    assert res["execution_permission"] == "none"
    venue_ids = {v["venue_id"] for v in res["venues"]}
    assert {"US_EQUITIES_ETFS", "CANADA_TSX", "CME_COMEX_FUTURES", "GLOBAL_FX", "CRYPTO_24_7"} <= venue_ids
    by_sym = res["by_symbol"]
    assert by_sym["BTC-USD"]["venue_id"] == "CRYPTO_24_7" and by_sym["BTC-USD"]["is_open"] is True
    assert by_sym["GC"]["venue_id"] == "CME_COMEX_FUTURES"
    assert by_sym["SPY"]["venue_id"] == "US_EQUITIES_ETFS"
    assert by_sym["EUR_USD"]["venue_id"] == "GLOBAL_FX"
