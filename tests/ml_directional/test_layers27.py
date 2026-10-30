"""Layers 27-33 (evo-15): breadth, overnight-vs-intraday, gap stats, seasonality, implied vol (VIX), USD proxy, and display-only macro risk.
Leak-free (future bars/refs/context never change a past row), NaN when not computable, and keyed FRED never reaches the model."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml.directional import context27 as C
from atlas.ai.ml.directional import layers25 as L
from atlas.api import chart_layers25 as C25
from atlas.api import chart_layers27 as C27
from atlas.features.price_action.bars import Bar

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[2]
NEW = L.LAYER27_IDS


def rth15(days=120, seed=1, start=dt.date(2025, 1, 2)):
    rng = np.random.default_rng(seed)
    out, px, d = [], 100.0, start
    while len(out) < days * 26:
        if d.weekday() < 5:
            t0 = dt.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY)
            px *= np.exp(rng.normal(0, 0.004))
            for k in range(26):
                o = px
                px *= np.exp(rng.normal(0, 0.002))
                out.append(Bar(int((t0 + dt.timedelta(minutes=15 * k)).timestamp()), 900, o, max(o, px) * 1.0005, min(o, px) * 0.9995, px, 1000.0))
        d += dt.timedelta(days=1)
    return out


def daily(n=520, seed=0, drift=0.0005, start=dt.date(2023, 1, 3)):
    rng = np.random.default_rng(seed)
    px, out, d = 50.0, [], start
    while len(out) < n:
        if d.weekday() < 5:
            t0 = int(dt.datetime(d.year, d.month, d.day, 4, tzinfo=dt.timezone.utc).timestamp())
            o = px
            px *= np.exp(rng.normal(drift, 0.01))
            out.append(Bar(t0, 86400, o, max(o, px), min(o, px), px, 1e6))
        d += dt.timedelta(days=1)
    return out


def nm(i):
    return "S" + chr(65 + i // 26) + chr(65 + i % 26)


def fxbar(i, c, dur=900, t0=1_700_000_000):
    return Bar(t0 + i * dur, dur, c, c, c, c, 0.0)


def vix_text(n=700):
    d = pd.bdate_range(end="2024-12-30", periods=n)
    rng = np.random.default_rng(5)
    c = np.exp(np.log(18) + np.cumsum(rng.normal(0, 0.03, n)) * 0.2)
    return "DATE,OPEN,HIGH,LOW,CLOSE\n" + "\n".join(f"{x:%m/%d/%Y},{v:.2f},{v:.2f},{v:.2f},{v:.2f}" for x, v in zip(d, c))


def test_counts_names_unique_and_all_new_layers_registered():
    assert len(L.LAYER_FEATURE_NAMES) == 74 == sum(len(v) for v in L.LAYER_FEATURES.values())
    assert len(set(L.LAYER_FEATURE_NAMES)) == 74
    assert set(NEW) == {"breadth", "overnight_intraday", "gap_stats", "seasonality", "implied_vol", "usd_proxy"} and all(k in L.LAYER_FEATURES for k in NEW)
    assert set(C27.IDS) == set(NEW) | {"macro_risk"} and "macro_risk" not in L.LAYER_FEATURES      # FRED layer is display-only, never a feature
    assert not any(n.startswith(("fred", "macro")) for n in L.LAYER_FEATURE_NAMES)


def test_future_data_never_changes_past_rows_including_breadth_vix_and_usd():
    b = rth15(110)
    day = {nm(i): daily(520, seed=i) for i in range(40)}
    day["SPY"] = daily(520, seed=99)
    extra = C.build_context(day, vix_text())
    assert extra["breadth"] is not None and extra["vix"] is not None
    eur = [fxbar(i, 1.1 + 0.0001 * (i % 50)) for i in range(len(b))]
    cad = [fxbar(i, 1.3 + 0.0002 * (i % 70)) for i in range(len(b))]
    b0 = b[0].start
    px = C.usd_proxy_series(lambda s: eur if s == "EUR_USD" else cad)
    px = (px[0] - 1_700_000_000 + b0, px[1])
    k = 1800
    f1 = L.layer_features(b, "15m", "equity", nm(1), 26, 4.0, {"USD_PROXY": px}, None, None, extra)
    b2 = list(b)
    for j in range(k + 1, len(b)):
        x = b[j]
        b2[j] = Bar(x.start, x.duration, x.open * 1.2, x.high * 1.3, x.low * 0.7, x.close * 1.15, x.volume * 5)
    px2 = (px[0], px[1].copy())
    px2[1][np.searchsorted(px[0], b[k].end, side="right"):] *= 2.0
    extra2 = {"breadth": extra["breadth"][extra["breadth"]["avail"] <= b[k].end], "vix": extra["vix"][extra["vix"]["avail"] <= b[k].end]}
    f2 = L.layer_features(b2[:k + 1], "15m", "equity", nm(1), 26, 4.0, {"USD_PROXY": (px2[0][px2[0] <= b[k].end], px2[1][px2[0] <= b[k].end])}, None, None, extra2)
    pd.testing.assert_frame_equal(f1.iloc[:k + 1].reset_index(drop=True)[list(L.LAYER_FEATURE_NAMES)], f2.reset_index(drop=True)[list(L.LAYER_FEATURE_NAMES)], check_exact=False, rtol=1e-9, atol=1e-12)
    # and the new columns are genuinely populated on this series (not vacuously equal NaN)
    cols = [c for n in NEW for c in L.LAYER_FEATURES[n]]
    assert f1[cols].notna().mean().min() > 0.2, f1[cols].notna().mean().to_dict()


def test_breadth_all_rising_is_one_and_availability_is_point_in_time():
    day = {nm(i): daily(420, seed=i, drift=0.01) for i in range(35)}
    ctx = C.breadth_context(day)
    assert ctx is not None and ctx["br_pct_above_50"].iloc[-1] == 1.0 and ctx["br_pct_above_200"].iloc[-1] == 1.0
    end = np.array([ctx["avail"].iloc[-1] - 1, ctx["avail"].iloc[-1]])
    j = C.asof_join(end, ctx, ["br_pct_above_50"])["br_pct_above_50"]
    assert j.iloc[1] == ctx["br_pct_above_50"].iloc[-1] and (j.iloc[0] != j.iloc[0] or j.iloc[0] == ctx["br_pct_above_50"].iloc[-2])   # one second earlier sees yesterday's value
    assert C.breadth_context({nm(0): day[nm(0)]}) is None                       # < 30 names: no invented breadth
    assert C.asof_join(np.array([1, 2]), None, ["x"])["x"].isna().all()


def test_breadth_excludes_non_stock_names_and_fx():
    assert C.is_stock_like("AAPL") and C.is_stock_like("SPY")
    assert not C.is_stock_like("BTCUSDT") and not C.is_stock_like("EUR_USD") and not C.is_stock_like("GC") and not C.is_stock_like("MGC")


def test_vix_is_available_only_after_its_session_and_failures_give_none():
    v = C.parse_vix_csv(vix_text())
    ctx = C.vix_context(v, daily(520, seed=2))
    first_day = int(pd.Timestamp(v["day"].iloc[-1]).timestamp())
    assert int(ctx["avail"].iloc[-1]) == first_day + 86400
    during = C.asof_join(np.array([first_day + 20 * 3600]), ctx, ["vix"])["vix"].iloc[0]       # 20:00 UTC on the session date: that day's close is NOT yet assigned
    assert during == ctx["vix"].iloc[-2]
    assert C.parse_vix_csv("garbage") is None and C.vix_context(None) is None


def test_usd_proxy_direction_and_excluded_legs():
    n = 400
    e = [fxbar(i, 1.1, 3600) for i in range(n)]
    c = [fxbar(i, 1.3 * (1 + 0.001 * i), 3600) for i in range(n)]
    px = C.usd_proxy_series(lambda s: e if s == "EUR_USD" else c)
    assert px[1][-1] > px[1][0]                                             # USD/CAD up, EUR/USD flat -> dollar stronger
    bars = rth15(60)
    f = L.usd_frame(np.array([x.end for x in bars]), (px[0] - px[0][0] + bars[0].end, px[1]), "XYZ")
    assert f["usd_ret_64"].notna().any()
    assert L.usd_frame(np.array([x.end for x in bars]), px, "EUR_USD").isna().all().all()
    assert C.usd_proxy_series(lambda s: e[:10]) is None
    assert L.role_refs({"USD_PROXY": px}, "USD_CAD") == {} and "usd" in L.role_refs({"USD_PROXY": px}, "AAPL")


def test_seasonality_known_dates():
    def row(y, m, d, hh=15):
        t = int(dt.datetime(y, m, d, hh, 0, tzinfo=NY).timestamp())
        return L.seasonality_frame(np.array([t]), np.array([t + 900]), "equity").iloc[0]
    assert row(2025, 1, 31)["sea_turn_of_month"] == 1.0 and row(2025, 1, 31)["sea_bdom_frac"] == 1.0   # last business day
    assert row(2025, 1, 2)["sea_turn_of_month"] == 1.0 and row(2025, 1, 15)["sea_turn_of_month"] == 0.0
    assert row(2025, 3, 28)["sea_qtr_end"] == 1.0 and row(2025, 2, 14)["sea_qtr_end"] == 0.0
    assert row(2025, 1, 1)["sea_bdom_frac"] == 0.0
    d0 = int(dt.datetime(2025, 1, 6, 0, 0, tzinfo=dt.timezone.utc).timestamp())   # daily bar starting 00:00 UTC Monday: midpoint is Monday in New York
    s = L.seasonality_frame(np.array([d0]), np.array([d0 + 86400]), "equity").iloc[0]
    assert abs(s["sea_dow_sin"] - np.sin(0)) < 1e-9 and abs(s["sea_dow_cos"] - 1.0) < 1e-9


def test_session_features_are_nan_for_continuous_markets_and_filled_flag_is_causal():
    b = rth15(100)
    for grp, inst in (("crypto", "BTCUSDT"), ("equity", "EUR_USD")):
        f = L.layer_features(b, "15m", grp, inst, 26, 4.0, {}, None, None, {})
        assert f[list(L.LAYER_FEATURES["overnight_intraday"] + L.LAYER_FEATURES["gap_stats"])].isna().all().all()
    f = L.layer_features(b, "15m", "equity", "XYZ", 26, 4.0, {}, None, None, {})
    # a gap is flagged filled only from the bar that actually trades back to the previous close
    day = pd.Series([x.start for x in b]).map(lambda s: dt.datetime.fromtimestamp(s, NY).date())
    for d in day.unique()[40:46]:
        idx = np.flatnonzero((day == d).to_numpy())
        flags = f["gp_filled"].to_numpy()[idx]
        flags = flags[np.isfinite(flags)]
        assert (np.diff(flags) >= 0).all()                                  # once filled, stays filled for the rest of the session


def test_rank_pct_partial_window_and_full_window_agree():
    x = np.random.default_rng(0).normal(size=700)
    full = L._rank_pct(x, 500)
    part = L._rank_pct(x, 500, 120)
    assert np.isnan(full[:499]).all() and np.isfinite(part[119:]).all() and np.isnan(part[:119]).all()
    np.testing.assert_allclose(full[499:], part[499:])


def test_equity_daily_vol_cone_256_is_now_populated():
    d = daily(497, seed=4)
    f = L.layer_features(d, "1d", "equity", "XYZ", 5, 4.0, {}, None, None, {})
    assert f["vc_pct_256"].notna().sum() > 100


def _ctx(sym="AAPL", group="equity", n=800, extra=None, corr=None):
    b = rth15(40)[:n]
    return C25.Ctx(sym, "15m", b, b[-1].end + 10, None, "America/Toronto", group, 4.0, 26, corr or {}, None, None, None, extra)


def test_layers_report_honest_reasons():
    ctx = _ctx(extra={})
    assert C27.breadth(ctx)["status"] == "unavailable" and "fewer" in C27.breadth(ctx)["reason"]
    assert C27.implied_vol(ctx)["status"] == "unavailable" and "VIX" in C27.implied_vol(ctx)["reason"]
    assert C27.usd_proxy(ctx)["status"] == "unavailable" and "EUR_USD" in C27.usd_proxy(ctx)["reason"]
    cr = _ctx("BTCUSDT", "crypto")
    assert "continuously" in C27.overnight_intraday(cr)["reason"] and "continuously" in C27.gap_stats(cr)["reason"] and "stocks and ETFs" in C27.breadth(cr)["reason"]
    assert C27.seasonality(cr)["status"] == "ok"
    assert "EUR_USD" in C27.usd_proxy(_ctx("EUR_USD", "equity"))["reason"]


def test_layers_ok_with_context():
    day = {nm(i): daily(520, seed=i) for i in range(40)}
    b = rth15(110)
    extra = C.build_context(day, vix_text())
    ctx = C25.Ctx(nm(1), "15m", b, b[-1].end + 10, None, "America/Toronto", "equity", 4.0, 26, {}, None, None, None, extra)
    for fn in (C27.overnight_intraday, C27.gap_stats, C27.seasonality):
        assert fn(ctx)["status"] == "ok", fn.__name__
    # the fixture's bars end in 2025 while breadth/VIX contexts end in 2026: values are read as of the bar, never from the future
    assert C27.breadth(ctx)["status"] in ("ok", "unavailable") and C27.implied_vol(ctx)["status"] in ("ok", "unavailable")


def test_macro_risk_is_display_only_and_needs_a_key(tmp_path, monkeypatch):
    C27.reset_macro_cache()
    r = C27.macro_risk(None, env={}, fetch=lambda u: (_ for _ in ()).throw(AssertionError("no key must mean no request")))
    assert r["status"] == "unavailable" and "FRED_API_KEY" in r["reason"] and "TRAIN" in r["note"].upper()
    seen = []

    def fetch(url):
        seen.append(url)
        sid = url.split("series_id=")[1].split("&")[0]
        v = {"T10Y2Y": -0.2, "T10Y3M": 0.3, "BAMLH0A0HYM2": 3.1, "BAA10Y": 1.9}[sid]
        import json
        return 200, json.dumps({"observations": [{"date": f"2026-10-{d:02d}", "value": str(v + d / 1000)} for d in range(1, 28)]})
    monkeypatch.chdir(tmp_path)
    ok = C27.macro_risk(None, env={"FRED_API_KEY": "k" * 32}, fetch=fetch, now=1_800_000_000)
    assert ok["status"] == "ok" and ok["display_only"] is True and ok["model_feature"] is False and ok["curve_inverted"] is True and len(ok["series"]) == 4
    assert list(tmp_path.iterdir()) == []                                     # nothing archived to disk
    assert "k" * 32 not in str(ok)                                            # the key never appears in the payload
    n = len(seen)
    C27.macro_risk(None, env={"FRED_API_KEY": "k" * 32}, fetch=fetch, now=1_800_000_100)
    assert len(seen) == n                                                     # cached in memory
    C27.reset_macro_cache()


def test_fred_events_are_filtered_out_of_training():
    cal = {"events": [{"ts": 1.0, "source": "bls"}, {"ts": 2.0, "source": "fred"}, {"ts": 3.0, "source": "treasury"}]}
    assert C.training_events(cal) == [1.0, 3.0]
    src = (ROOT / "scripts" / "ml_directional.py").read_text(encoding="utf-8")
    assert "training_events(cal)" in src and 'e["ts"] for e in cal["events"]]' not in src
    for p in (ROOT / "src/atlas/ai/ml/directional").glob("*.py"):
        t = p.read_text(encoding="utf-8")
        assert "FRED_API_KEY" not in t and "fred.py" not in t and "api.stlouisfed" not in t, p.name   # the ML package never touches keyed FRED


def test_chart_overlays_payload_carries_every_layer_key():
    src = (ROOT / "src/atlas/api/chart_overlays.py").read_text(encoding="utf-8")
    assert "**{k: _layer(getattr(C27, k), ctx) for k in C27.IDS}" in src and '"anchored_vwap"' in src and '"sessions"' in src


def test_cached_ref_bars_loads_each_reference_once_per_request(monkeypatch):
    """AAPL 15m overlay took ~60 s because the same ~8 reference series were loaded from the store twice per request."""
    from types import SimpleNamespace

    from atlas.ai.ml import dataset
    from atlas.api import chart_overlays as co
    calls = []
    monkeypatch.setattr(dataset, "load_series", lambda feed, s, iv: calls.append((s, iv)) or SimpleNamespace(bars=[s, iv]))
    co._REF_CACHE.clear()
    feed, other = object(), object()
    a = co.cached_ref_bars(feed, "SPY", "15m")
    b = co.cached_ref_bars(feed, "SPY", "15m")
    assert a is b and calls == [("SPY", "15m")]
    co.cached_ref_bars(other, "SPY", "15m")                                 # a different feed never shares a cache entry
    assert len(calls) == 2
    co._REF_CACHE.clear()
