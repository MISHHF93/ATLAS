"""chart-2: rich marker payload, causal (no-lookahead) indicator snapshots, outcome labels, prediction zone."""
from __future__ import annotations

import math

from fastapi.testclient import TestClient

from atlas.api import chart_overlays as co
from atlas.api.app import app
from atlas.features.price_action.bars import Bar
from atlas.intel import marker_context as mc
from tests.test_chart_overlays import FakeFeed


def _bars(n=400, dur=900):
    t0 = 1_700_000_000 - 1_700_000_000 % 86400
    out = []
    for i in range(n):
        c = 100 + 4 * math.sin(i / 17) + 0.02 * i
        out.append(Bar(t0 + i * dur, dur, c - 0.1, c + 0.5 + (i % 5) * 0.1, c - 0.6, c, 5 + i % 9))
    return out


def test_snapshots_have_no_lookahead():
    bars = _bars()
    full = mc.snapshots(bars)
    for i in (59, 120, 250, 399):
        assert mc.snapshots(bars[: i + 1])[-1] == full[i]
    # changing a FUTURE bar never changes a past snapshot
    mod = list(bars)
    b = mod[300]
    mod[300] = Bar(b.start, b.duration, b.open, b.high * 3, b.low, b.close * 2, b.volume * 50)
    assert mc.snapshots(mod)[299] == full[299]
    s = full[200]
    for k in ("rsi", "adx", "macd_hist", "vwap_dist_atr", "atr", "regime"):
        assert s[k] is not None, k
    assert 0 <= s["rsi"] <= 100 and 0 <= s["adx"] <= 100


def test_outcome_labels():
    assert mc.outcome_label("target") == "hit_target"
    assert mc.outcome_label("stop") == "stopped_out"
    assert mc.outcome_label("open") == "open"
    assert mc.outcome_label("timeout") == "timed_out"
    assert mc.outcome_label(None) == "not_filled" and mc.outcome_label("unfilled") == "not_filled"


def _m(bars, i, **kw):
    b = bars[i]
    base = {"id": f"c{i}", "source": "candidate_engine", "strategy": "sfp_reversal", "direction": "long", "time": b.start,
            "detected_at": b.start + b.duration, "price": b.close, "stop": b.close - 2, "target": b.close + 4,
            "probability": None, "class": "rule_only", "outcome": "target", "r": 2.0}
    return {**base, **kw}


def test_enrich_payload_fields_and_path():
    bars = _bars()
    mk = [_m(bars, 150), _m(bars, 200, outcome="not_filled", r=None, **{"class": "risk_rejected", "gate_reasons": ["RR_TOO_LOW"]}),
          _m(bars, 210, probability=0.61, source="evolution_oos", **{"class": "ml_suggested"})]
    mc.enrich(mk, bars)
    snaps = mc.snapshots(bars)
    for m in mk:
        for k in ("indicators", "threshold", "outcome_label", "why", "setup", "resolution_path"):
            assert k in m
        assert m["indicators"] == snaps[[b.start for b in bars].index(m["time"])]
    assert mk[0]["threshold"] == round(1 / 3, 4)
    assert mk[0]["outcome_label"] == "hit_target" and mk[0]["resolution_path"] and mk[0]["resolution_path"][-1].get("exit")
    assert mk[1]["resolution_path"] == [] and "RR_TOO_LOW" in mk[1]["why"]
    assert "0.61" in mk[2]["why"] and "threshold" in mk[2]["why"]


def test_forward_zone_and_calibration():
    bars = _bars()
    snaps = mc.snapshots(bars)
    z = mc.forward_zone(bars, snaps, [])
    assert z["status"] == "ok" and z["label"] == mc.PREDICTION_LABEL and z["no_active_candidate"]
    assert z["band"]["p10"] <= z["band"]["p50"] <= z["band"]["p90"] and z["as_of_bar"] == bars[-1].start
    last = _m(bars, len(bars) - 1, outcome="open", r=None)
    z = mc.forward_zone(bars, snaps, [last])
    assert z["active_candidates"] and z["no_active_candidate"] is None and z["active_candidates"][0]["calibrated"] is False
    c = mc.calibration([{"p": 0.7, "outcome": "target", "r": 2, "take": True}, {"p": 0.4, "outcome": "stop", "r": -1, "take": False},
                        {"p": 0.5, "outcome": "open", "r": None}])
    assert c["status"] == "ok" and c["n"] == 2 and c["hit_rate"] == 0.5 and abs(c["brier"] - (0.09 + 0.16) / 2) < 1e-9
    assert mc.calibration([])["status"] == "unavailable"


def test_overlay_api_returns_new_layers(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setattr(co, "_feed", lambda: FakeFeed())
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=15m&limit=300").json()
    L = d["layers"]
    assert L["marker_details"]["status"] == "ok"
    assert L["forward"]["status"] == "ok" and L["forward"]["label"] == mc.PREDICTION_LABEL
    assert "running_calibration" in L["predictions"]
    for m in L["setups"]["items"]:
        assert "indicators" in m and "outcome_label" in m and "why" in m
    assert d["execution_permission"] == "none"
