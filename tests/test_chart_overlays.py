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
