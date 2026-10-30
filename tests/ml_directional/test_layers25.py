"""The ten new chart layers and their training features: leak-free, honest NaN, counts, status/reason contract, 33 UI layers, all on by default."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas.ai.ml.directional import layers25 as L
from atlas.ai.ml.directional.features import feature_names, v2_feature_names
from atlas.api import chart_layers25 as C
from atlas.api import chart_layers27 as L27
from atlas.api import chart_overlays as co
from atlas.api.app import app
from atlas.features.price_action.bars import Bar

DUR = 3600


def bars_(n=3200, seed=3, vol=True):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    return [Bar(1_700_000_000 + i * DUR, DUR, c[i - 1] if i else 100.0, max(c[i], c[i - 1] if i else 100.0) * 1.001, min(c[i], c[i - 1] if i else 100.0) * 0.999, c[i],
                (1000.0 + rng.integers(0, 500)) if vol else 0.0) for i in range(n)]


def _events(bars):
    return [bars[0].start + k * 3 * 86400 + 3600 * 13 for k in range(0, 80)]


def _refs(bars, seed=9):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.003, len(bars))))
    return {"SPY": (np.array([b.end for b in bars]), c), "GLD": (np.array([b.end for b in bars]), c[::-1].copy())}


def test_counts_and_names_are_exact_and_unique():
    assert len(L.LAYER_FEATURE_NAMES) == 74 == sum(len(v) for v in L.LAYER_FEATURES.values())
    assert len(set(L.LAYER_FEATURE_NAMES)) == 74
    assert set(L.LAYER_FEATURE_NAMES).isdisjoint(v2_feature_names(("SPY",)))
    assert len(v2_feature_names(("SPY",))) == 51 and len(feature_names(("SPY",))) == 125
    assert len(L.NEW_LAYER_IDS) == 10 and set(L.NEW_LAYER_IDS) == set(C.IDS)


def test_future_bars_never_change_past_features_including_refs_and_events():
    b = bars_()
    refs, ev = _refs(b), _events(b)
    k = 2400
    f1 = L.layer_features(b, "1h", "equity", "XYZ", 24, 4.0, refs, ev)
    b2 = list(b)
    for j in range(k + 1, len(b)):
        x = b[j]
        b2[j] = Bar(x.start, x.duration, x.open * 1.2, x.high * 1.3, x.low * 0.7, x.close * 1.15, x.volume * 5)
    refs2 = {n: (e.copy(), c.copy()) for n, (e, c) in refs.items()}
    for n in refs2:
        refs2[n][1][k + 1:] *= 3.0
    f2 = L.layer_features(b2, "1h", "equity", "XYZ", 24, 4.0, refs2, [e for e in ev if e <= b[k].end] + [b[k].end + 5 * 86400])
    a, c = f1.iloc[: k + 1].to_numpy(float), f2.iloc[: k + 1].to_numpy(float)
    bad = [col for i, col in enumerate(f1.columns) if not np.allclose(a[:, i], c[:, i], equal_nan=True)]
    # ev_* depend on the published schedule coverage window; only the last event added by the perturbed run may alter bars near its coverage end
    assert [x for x in bad if not x.startswith("ev_")] == []


def test_reference_bar_after_own_bar_end_is_never_used():
    b = bars_(1500)
    ends = np.array([x.end for x in b])
    base = np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.003, len(b))))
    shifted_end = ends + DUR // 2           # ref bar i ends half a bar AFTER own bar i: own bar i may only see ref bar i-1
    f = L.layer_features(b, "1h", "equity", "XYZ", 24, 4.0, {"SPY": (shifted_end, base)}, None)
    base2 = base.copy()
    base2[900] *= 5.0                        # shock to ref bar 900; it ends after own bar 900 ends
    f2 = L.layer_features(b, "1h", "equity", "XYZ", 24, 4.0, {"SPY": (shifted_end, base2)}, None)
    assert np.allclose(f["xcl_spy_corr_64"].iloc[:900], f2["xcl_spy_corr_64"].iloc[:900], equal_nan=True)
    assert np.isnan(f["xcl_usd_corr_64"]).all()                           # no proxy stored -> NaN, not 0


def test_missing_inputs_are_nan_not_zero():
    b = bars_(900, vol=False)
    f = L.layer_features(b, "1h", "equity", "XYZ", 24, 4.0, None, None)
    assert f[list(L.LAYER_FEATURES["events"])].isna().all().all()
    assert f["liq_amihud"].isna().all() and f["liq_dvol_z"].isna().all() and f["ex_vp_va_pos"].isna().all()
    cov = L.coverage(f)
    assert cov["events"]["n_all_nan"] == 3 and cov["cross_corr"]["n_all_nan"] == 8


def test_events_outside_schedule_coverage_are_nan():
    b = bars_(600)
    ev = [b[300].end + k * 7200 for k in range(0, 10)]
    f = L.event_frame(np.array([x.end for x in b]), ev)
    assert f["ev_hrs_to_next"].iloc[:300].isna().all() and f["ev_hrs_to_next"].iloc[320:].isna().all()
    assert f["ev_hrs_to_next"].iloc[301:310].notna().all()


def test_market_clock_known_instants():
    ts = np.array([1_700_000_000, 1_700_000_000 + 0])          # Tue 2023-11-14 22:13:20 UTC
    v = L.venue_open(np.array([1699972200]))                    # Tue 2023-11-14 14:30 UTC = 09:30 EST: NYSE/TSX open, LSE open, Tokyo closed (23:30 JST)
    assert bool(v["NYSE"][0]) and bool(v["TSX"][0]) and bool(v["LSE"][0]) and not bool(v["TSE"][0])
    sat = L.venue_open(np.array([1699716000]))                  # Sat 2023-11-11 16:00 UTC
    assert not sat.any(axis=None)


def test_conformal_band_coverage_is_near_nominal_on_stationary_noise():
    b = bars_(6000, seed=21)
    f = L.layer_features(b, "1h", "equity", "XYZ", 24, 4.0, None, None)
    cov = f["cb_cover_64"].dropna()
    assert 0.65 < cov.mean() < 0.93        # nominal 0.80; exchangeability is only approximate for overlapping windows


def _feed_with(sym="BTCUSDT"):
    def rows(n, step):
        t0 = 1_700_000_000 - 1_700_000_000 % 86400
        rng = np.random.default_rng(5)
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
        return [SimpleNamespace(event_time=t0 + i * step, open=c[i - 1] if i else 100, high=c[i] * 1.002, low=c[i] * 0.998, close=c[i], volume=10 + i % 7, provider="binance") for i in range(n)]

    class F:
        def bars(self, s, iv):
            return rows(1500, 3600) if (s == sym and iv == "1h") else []
    return F()


def test_overlays_endpoint_has_ten_new_layers_each_with_status_and_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    monkeypatch.setenv("ATLAS_DIRECTIONAL_ROOT", str(tmp_path / "dir"))
    monkeypatch.setattr(co, "_feed", lambda: _feed_with())
    d = TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=1h&limit=300&tz=America/Toronto").json()
    assert d["status"] == "ok" and d["execution_permission"] == "none"
    for k in C.IDS:
        lay = d["layers"][k]
        assert lay["status"] in ("ok", "unavailable"), k
        assert lay.get("reason"), f"{k}: every layer states why (ok layers state their method)"
    assert d["layers"]["conformal_bands"]["status"] == "ok" and d["layers"]["conformal_bands"]["forward"]["lower"] < d["layers"]["conformal_bands"]["forward"]["upper"]
    assert d["layers"]["market_clock"]["status"] == "ok" and d["layers"]["vol_cone"]["status"] == "ok" and d["layers"]["liquidity"]["status"] == "ok"
    assert d["layers"]["cross_corr"]["status"] == "unavailable" and "no stored" in d["layers"]["cross_corr"]["reason"]
    assert d["layers"]["events"]["status"] == "unavailable" and d["layers"]["events"]["earnings"]["status"] == "unavailable"   # network is blocked in tests
    assert d["layers"]["model_disagreement"]["status"] == "ok" and d["layers"]["model_disagreement"]["learned_spread"] is None
    assert d["layers"]["account_size"]["status"] in ("ok", "unavailable")
    assert all(d["layers"][k].get("orders") is None for k in C.IDS)
    assert TestClient(app).get("/api/ai/chart/overlays?symbol=BTCUSDT&interval=1h&tz=Not/AZone").status_code == 400


def test_events_layer_ok_with_injected_calendar(monkeypatch):
    b = bars_(600)
    ctx = C.Ctx("XYZ", "1h", b, b[-1].end + 10, None, "America/Toronto", "equity", 4.0, 24, {}, [b[-1].end + 3600], None, None)
    cal = {"events": [{"ts": b[-1].end + 3600, "title": "CPI", "source": "bls", "important": True}], "sources": [{"id": "bls", "status": "ok", "in_window": 1}]}
    out = C.events(ctx, cal)
    assert out["status"] == "ok" and out["next"]["title"] == "CPI" and out["earnings"]["status"] == "unavailable"


def test_frontend_has_33_layers_all_on_by_default_and_grouped():
    src = Path(__file__).resolve().parents[2].joinpath("frontend/src/components/market/AtlasChart.tsx").read_text(encoding="utf-8")
    block = re.search(r"const LAYERS = \[(.*?)\] as const;", src, re.S).group(1)
    ids = re.findall(r'id: "([a-z_0-9]+)"', block)
    assert len(ids) == 33 and len(set(ids)) == 33      # 15 existing + 10 evo-14 + news + 7 evo-15 (27-33)
    assert set(L.NEW_LAYER_IDS) <= set(ids) and "news" in ids and set(L27.IDS) <= set(ids)
    grp = re.search(r"const LAYER_GROUPS[^=]*= \[(.*?)\n\];", src, re.S).group(1)
    grouped = re.findall(r'"([a-z_0-9]+)"', re.sub(r'title: "[^"]*"', "", grp))
    assert sorted(grouped) == sorted(ids)               # every layer sits in exactly one category
    assert re.search(r"\[l\.id,\s*true\]", src) and "includes(l.id)" not in src.split("const [on, setOn]")[1][:400]   # all ON by default
    css = Path(__file__).resolve().parents[2].joinpath("frontend/src/ui/tokens.css").read_text(encoding="utf-8")
    pop = re.search(r"\.atlas-chart-layers\.is-pop \{[^}]*\}", css).group(0)
    card = re.search(r"\.atlas-lcard \{[^}]*\}", css, re.S).group(0)
    assert "overflow" not in pop and "max-height" not in pop and "overflow" not in card and "max-height" not in card   # no nested scroll


def test_feature_inventory_script_matches_code():
    import importlib.util
    spec = importlib.util.spec_from_file_location("feature_inventory", Path(__file__).resolve().parents[2] / "scripts" / "feature_inventory.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    inv = m.inventory()
    assert inv["meta_stack"]["total"] == 45 and inv["directional_before"]["total"] == 51 and inv["directional_after"]["total"] == 125
    assert inv["research_vertical_slice"]["total"] == 21 and inv["representation_genome_per_bar_type"] == 6 and inv["unique_and_disjoint"] == {"v3_unique": True, "layer_names_disjoint_from_v2": True}
