"""VWAP regime features: causal, session-aware, honest about missing volume, registered through the AI node."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from atlas.ai.ml.features import BAR_FEATURES, bar_features
from atlas.ai.ml.vwap_features import (VWAP_FEATURES, anchored_vwap, session_key, session_kind_for, vwap_regime_features)
from atlas.features.price_action.bars import Bar

NY = ZoneInfo("America/New_York")


def ts(y, mo, d, h, mi, tz=timezone.utc):
    return int(datetime(y, mo, d, h, mi, tzinfo=tz).timestamp())


def series(start: int, n: int, dur: int = 900, vol: float = 100.0, seed: int = 3) -> list[Bar]:
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    for i in range(n):
        o = px
        px = max(1.0, px * (1 + rng.normal(0, 0.003)))
        out.append(Bar(start + i * dur, dur, o, max(o, px) * 1.001, min(o, px) * 0.999, px, vol * (1 + rng.random())))
    return out


def test_features_are_in_bar_features_and_in_order():
    assert set(VWAP_FEATURES) <= set(BAR_FEATURES)
    f = bar_features(series(1_700_000_000, 300))
    assert list(f.columns) == list(BAR_FEATURES)


def test_session_vwap_matches_hand_computation_and_resets_at_utc_midnight():
    start = ts(2026, 3, 2, 22, 0)             # crosses UTC midnight after 8 x 15m bars
    bars = series(start, 16)
    v = vwap_regime_features(bars, "crypto", "BTCUSDT")
    first = [b for b in bars if b.start // 86400 == bars[0].start // 86400]
    tp = [(b.high + b.low + b.close) / 3 for b in first]
    vol = [b.volume for b in first]
    want = sum(t * w for t, w in zip(tp, vol)) / sum(vol)
    last_before = len(first) - 1
    got_dist = v["vwap_dist_bps"].iloc[last_before]
    assert got_dist == pytest.approx((first[-1].close - want) / first[-1].close * 1e4, rel=1e-9)
    assert v["vwap_sess_frac"].iloc[last_before] == pytest.approx(len(first) / 100)
    assert v["vwap_sess_frac"].iloc[last_before + 1] == pytest.approx(1 / 100)      # new session restarts
    # slope never straddles a session break
    assert v["vwap_slope_atr"].iloc[last_before + 1: last_before + 1 + 5].isna().all()


def test_vwap_features_are_causal():
    bars = series(1_700_000_000, 500)
    k = 300
    base = vwap_regime_features(bars, "crypto", "BTCUSDT")
    changed = bars[:k + 1] + [Bar(b.start, b.duration, b.open * 3, b.high * 3, b.low * 3, b.close * 3, b.volume * 7) for b in bars[k + 1:]]
    pert = vwap_regime_features(changed, "crypto", "BTCUSDT")
    pd.testing.assert_frame_equal(base.iloc[:k + 1], pert.iloc[:k + 1])
    f1, f2 = bar_features(bars, "crypto", "BTCUSDT"), bar_features(changed, "crypto", "BTCUSDT")
    pd.testing.assert_frame_equal(f1.iloc[:k + 1][list(VWAP_FEATURES)], f2.iloc[:k + 1][list(VWAP_FEATURES)])


def test_zero_volume_gives_nan_not_made_up_values():
    bars = [Bar(b.start, b.duration, b.open, b.high, b.low, b.close, 0.0) for b in series(1_700_000_000, 200)]
    v = vwap_regime_features(bars, "crypto", "BTCUSDT")
    assert v[["vwap_dist_atr", "vwap_dist_bps", "vwap_slope_atr", "vwap_band_z"]].isna().all().all()


def test_us_equity_session_only_rth_and_resets_per_day():
    day1 = ts(2026, 3, 3, 9, 0, NY)          # 09:00 ET: pre-market bars are outside the session
    bars = series(day1, 40, dur=900)
    v = vwap_regime_features(bars, "equity", "SPY")
    assert v["vwap_dist_atr"].iloc[:2].isna().all()           # 09:00 and 09:15 ET
    assert v["vwap_dist_atr"].iloc[2:28].notna().all()        # 09:30-16:00 ET is the session (26 x 15m)
    assert v["vwap_dist_atr"].iloc[28:].isna().all()          # after the close: no VWAP
    assert session_key(ts(2026, 3, 7, 10, 0, NY), "us_rth") is None      # Saturday
    assert session_key(ts(2026, 3, 3, 16, 0, NY), "us_rth") is None      # closed at 16:00


def test_gold_futures_use_the_globex_day_rolling_at_1800_et():
    a, b = ts(2026, 3, 3, 17, 45, NY), ts(2026, 3, 3, 18, 0, NY)
    assert session_kind_for("equity", "GC") == "cme_globex" and session_kind_for("equity", "MGC") == "cme_globex"
    assert session_key(a, "cme_globex") != session_key(b, "cme_globex")
    assert session_kind_for("equity", "GLD") == "us_rth" and session_kind_for("crypto", "BTCUSDT") == "utc_day"


def test_daily_bars_have_no_intraday_session():
    v = vwap_regime_features(series(1_700_000_000, 100, dur=86400), "equity", "SPY")
    assert v.isna().all().all()


def test_anchored_vwap_is_causal_and_never_reaches_before_the_anchor():
    bars = series(1_700_000_000, 60)
    anchor = bars[20].start
    av = anchored_vwap(bars, [anchor])
    assert np.isnan(av[:20]).all()
    tp = [(b.high + b.low + b.close) / 3 for b in bars[20:31]]
    w = [b.volume for b in bars[20:31]]
    assert av[30] == pytest.approx(sum(t * x for t, x in zip(tp, w)) / sum(w))
    bars2 = bars[:31] + [Bar(b.start, b.duration, 500, 600, 400, 550, 9999) for b in bars[31:]]
    assert anchored_vwap(bars2, [anchor])[:31] == pytest.approx(av[:31], nan_ok=True)
    av2 = anchored_vwap(bars, [anchor, bars[40].start])           # a later anchor restarts accumulation
    assert av2[40] == pytest.approx((bars[40].high + bars[40].low + bars[40].close) / 3)
    assert anchored_vwap(bars, []).tolist() != [] and np.isnan(anchored_vwap(bars, [])).all()


def test_registered_through_the_ai_node():
    from atlas.ai.node import EXECUTION_PERMISSION, REGISTRY, component_status
    owners = {m: c.name for c in REGISTRY for m in c.modules}
    assert owners["atlas.ai.ml.vwap_features"] == "ml_pipeline"
    assert owners["atlas.ai.ml.chart_prediction"] == "evolution"
    assert EXECUTION_PERMISSION == "none"
    st = component_status(next(c for c in REGISTRY if c.name == "ml_pipeline"))
    assert "atlas.ai.ml.vwap_features" in str(st)
