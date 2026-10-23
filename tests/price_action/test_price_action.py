"""Price-action engine tests. All bars here are hand-built or SYNTHETIC fixtures (random walk with a
fixed seed); they are not market data and say nothing about strategy profitability."""
from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from atlas.features.price_action import (Bar, DualBandConfig, DualBollingerDetector, EconomicEvent, EngineConfig,
                                         ORBRetestConfig, ORBRetestDetector, PriceActionEngine, WickConfig,
                                         WickReversalDetector, Zone, candle_geometry, event_zone)
from atlas.features.price_action import indicators as ind
from atlas.features.price_action.features import StreamingFeatures, batch_features
from atlas.features.price_action.proposals import candidate_to_signal
from atlas.features.price_action.sessions import LONDON_CASH, US_EQUITY_RTH
from atlas.features.price_action.store import TransitionStore


def ts(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


def B(t, o, h, l, c, v=1.0, d=3600):
    return Bar(t, d, o, h, l, c, v)


# ---------- indicators (hand-computed) ----------

def test_ema_sma_seed():
    assert ind.ema_batch([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    e = ind.EMA(3)
    assert [e.update(x) for x in [1, 2, 3, 4, 5]] == [None, None, 2.0, 3.0, 4.0]


@pytest.mark.parametrize("xs,exp", [([1, 2, 3], 100.0), ([3, 2, 1], 0.0), ([1, 1, 1], 50.0), ([1, 2, 1], 50.0)])
def test_rsi_zero_cases(xs, exp):
    assert ind.rsi_batch(xs, 2)[-1] == exp
    r = ind.WilderRSI(2)
    assert [r.update(x) for x in xs][-1] == exp


def test_rsi_wilder_value():
    assert ind.rsi_batch([1, 2, 1, 3], 2)[-1] == pytest.approx(100 - 100 / 6)


def test_atr_wilder():
    h, l, c = [10, 12, 11], [8, 9, 10], [9, 11, 10.5]
    assert ind.atr_batch(h, l, c, 2) == [None, 2.5, 1.75]
    a = ind.WilderATR(2)
    assert [a.update(*x) for x in zip(h, l, c)] == [None, 2.5, 1.75]


def test_bollinger_population_std():
    lo, mid, up = ind.bollinger_batch([1, 2, 3, 4], 4, 1)[-1]
    assert mid == 2.5 and up == pytest.approx(2.5 + 1.25 ** 0.5) and lo == pytest.approx(2.5 - 1.25 ** 0.5)
    assert ind.Bollinger(4, 1.0).update(1) is None


def test_vwap_bar_approx_resets_per_session():
    out = ind.vwap_batch([3, 6, 9], [1, 2, 3], [2, 4, 6], [1, 1, 2], ["a", "a", "b"])
    assert out == [2.0, 3.0, 6.0]
    v = ind.BarVWAP()
    assert [v.update(*x) for x in zip([3, 6, 9], [1, 2, 3], [2, 4, 6], [1, 1, 2], ["a", "a", "b"])] == out
    assert ind.BarVWAP().update(1, 1, 1, 0.0) is None


def test_candle_geometry():
    g = candle_geometry(B(0, 10, 12, 9, 11))
    assert (g["body"], g["upper_wick"], g["lower_wick"], g["range"]) == (1, 1, 1, 3)
    assert candle_geometry(B(0, 5, 5, 5, 5))["body_ratio"] == 0.0  # zero range uses epsilon


# ---------- zone ----------

def test_zone_distance_and_lifecycle():
    z = Zone("X", 3600, "t", "bullish", 10, 12, formed_at=0, confirmed_at=3600, max_age_seconds=10 * 3600)
    assert z.normalized_distance(11, 2.0) == 0.0 and z.normalized_distance(13, 2.0) == 0.5
    assert z.normalized_distance(9, 0.0) > 1e9 and z.normalized_distance(9, None) is None
    assert z.update(B(3600, 13, 14, 12.5, 13.5)) == []
    assert z.update(B(7200, 13, 13, 11.5, 12.5)) == ["touch", "retest"]
    assert z.update(B(10800, 12, 12.5, 11, 12)) == []  # still inside: not a new touch
    assert z.update(B(14400, 11, 11, 9, 9.5)) == ["invalidated"]
    assert z.status == "invalidated" and z.touch_count == 1 and z.first_retest_at == 10800
    with pytest.raises(ValueError):
        Zone("X", 1, "t", "neutral", 2, 1, 0)


def test_zone_expiry():
    z = Zone("X", 3600, "t", "bearish", 10, 12, 0, confirmed_at=3600, max_age_seconds=3600)
    assert z.update(B(3600, 9, 9.5, 8, 9)) == []
    assert z.update(B(7200, 9, 9.5, 8, 9)) == ["expired"]


# ---------- sessions ----------

def test_session_dst_explicit():
    assert US_EQUITY_RTH.window_for(ts(2026, 3, 6, 14, 30))[1] == ts(2026, 3, 6, 14, 30)  # EST
    assert US_EQUITY_RTH.window_for(ts(2026, 3, 9, 13, 30))[1] == ts(2026, 3, 9, 13, 30)  # EDT
    assert US_EQUITY_RTH.window_for(ts(2026, 3, 9, 13, 0)) is None
    assert US_EQUITY_RTH.window_for(ts(2026, 3, 7, 15, 0)) is None  # Saturday
    assert LONDON_CASH.window_for(ts(2026, 3, 30, 7, 0))[1] == ts(2026, 3, 30, 7, 0)  # BST


# ---------- opening range breakout-retest-continuation ----------

O = ts(2026, 1, 5, 14, 30)  # Monday 09:30 New York


def _orb_long_bars():
    return [B(O, 100, 102, 99, 101), B(O + 3600, 101, 104, 101, 103.5), B(O + 7200, 103.5, 104, 101.8, 103)]


def test_orb_long_happy_path():
    d = ORBRetestDetector("X", 3600, US_EQUITY_RTH)
    for b in _orb_long_bars():
        d.step(b, {"atr": None})
    states = [t.to_state for t in d.transitions]
    assert states == ["RANGE_FORMING", "RANGE_CONFIRMED", "AWAITING_BREAKOUT", "BREAKOUT_CONFIRMED", "AWAITING_RETEST",
                      "RETEST_OBSERVED", "CONTINUATION_CONFIRMED", "CANDIDATE_EVALUATED", "COMPLETED"]
    (c,) = d.candidates
    assert c.direction == "long" and c.entry_reference == 103 and c.proposed_stop == 101 and c.proposed_target == 107
    assert c.features["breakout_strength"] == pytest.approx(0.5)
    assert c.features["retest_depth"] == pytest.approx(1 / 3)
    assert c.features["time_to_retest"] == 3600 and c.execution_permission == "none" and c.probability is None
    assert d.zones[0].lower_bound == 99 and d.zones[0].upper_bound == 102  # wicks included


def test_orb_buffer_blocks_marginal_breakout():
    d = ORBRetestDetector("X", 3600, US_EQUITY_RTH, ORBRetestConfig(breakout_buffer=2.0))
    for b in _orb_long_bars():
        d.step(b, {})
    assert d.s["state"] == "AWAITING_BREAKOUT" and not d.candidates


def test_orb_short_and_failure_rearm():
    bars = [B(O, 100, 102, 99, 101), B(O + 3600, 101, 104, 101, 103), B(O + 7200, 103, 103, 97, 98),
            B(O + 10800, 98, 98.5, 97, 97.5), B(O + 14400, 97.5, 99.2, 97, 98)]
    d = ORBRetestDetector("X", 3600, US_EQUITY_RTH)
    for b in bars:
        d.step(b, {})
    states = [t.to_state for t in d.transitions]
    assert "INVALIDATED" in states and d.s["failed"] == 1
    # re-armed setup: bar 4 is a bearish breakout, bar 5 retests (high>=99) and closes < 99
    (c,) = d.candidates
    assert c.direction == "short" and c.features["prior_failed_breakouts"] == 1


def test_orb_range_from_subhour_bars_and_missing_bar():
    q = [B(O + i * 900, 100, 101 + (i == 2), 99 - (i == 1), 100, d=900) for i in range(4)]
    d = ORBRetestDetector("X", 900, US_EQUITY_RTH)
    for b in q:
        d.step(b, {})
    assert (d.s["oh"], d.s["ol"], d.s["state"]) == (102, 98, "AWAITING_BREAKOUT")
    d2 = ORBRetestDetector("X", 900, US_EQUITY_RTH)
    for b in q[:1] + q[2:]:
        d2.step(b, {})
    assert d2.transitions[-1].reason == "missing_bars_in_range_window"


def test_orb_session_end_expires():
    d = ORBRetestDetector("X", 3600, US_EQUITY_RTH)
    d.step(B(O, 100, 102, 99, 101), {})
    d.step(B(O + 86400, 100, 102, 99, 101), {})
    assert [t.to_state for t in d.transitions if t.to_state == "EXPIRED"] == ["EXPIRED"]


# ---------- dual bollinger ----------

CTX = {"band_a": (90, 95, 100), "band_b": (92, 96, 101), "prev_band_a": (90, 95, 105), "prev_band_b": (92, 96, 101), "atr": 2.0}


def test_dual_band_variants_differ():
    close_bar, pierce_only = B(0, 99.5, 103, 99, 102), B(0, 99.5, 103, 99, 100.5)
    cb = DualBollingerDetector("X", 3600, DualBandConfig("close_beyond"))
    rp = DualBollingerDetector("X", 3600, DualBandConfig("range_pierce"))
    assert len(cb.step(close_bar, CTX)) == 1 and cb.step(pierce_only, CTX) == []
    assert len(rp.step(B(0, 99.5, 103, 99, 100.5), CTX)) == 1
    z = cb.zones[0]
    assert (z.lower_bound, z.upper_bound, z.direction) == (99, 103, "bullish")
    prior = DualBollingerDetector("X", 3600, DualBandConfig("close_beyond", "prior"))
    assert prior.step(close_bar, CTX) == []  # prior-bar upper A = 105 not exceeded
    assert DualBollingerDetector("X", 3600).step(close_bar, {"band_a": None, "band_b": None}) == []


def test_dual_band_bearish():
    d = DualBollingerDetector("X", 3600)
    assert d.step(B(0, 91, 91, 88, 89), CTX)[0].direction == "bearish"


# ---------- wick reversal ----------

def test_wick_reversal_bullish():
    d = WickReversalDetector("X", 3600, WickConfig(lookback=3))
    for i in range(3):
        d.step(B(i * 3600, 10.5, 11, 10, 10.5), {})
    d.step(B(3 * 3600, 10.5, 10.7, 9, 10.6), {})
    out = d.step(B(4 * 3600, 10.6, 11, 10.5, 10.8), {})
    (z,) = [o for o in out if isinstance(o, Zone)]
    assert (z.direction, z.lower_bound, z.upper_bound, z.confirmed_at) == ("bullish", 9, 10.5, 5 * 3600)


def test_wick_reversal_unconfirmed_and_small_wick():
    d = WickReversalDetector("X", 3600, WickConfig(lookback=3))
    for i in range(3):
        d.step(B(i * 3600, 10.5, 11, 10, 10.5), {})
    d.step(B(3 * 3600, 10.5, 10.7, 9, 10.6), {})
    d.step(B(4 * 3600, 10.6, 10.6, 10.0, 10.1), {})  # no confirmation within 1 bar
    assert d.zones == [] and d.pending == []
    d2 = WickReversalDetector("X", 3600, WickConfig(lookback=3))
    for i in range(3):
        d2.step(B(i * 3600, 10.5, 11, 10, 10.5), {})
    d2.step(B(3 * 3600, 10.9, 11, 9.8, 9.9), {})  # bearish body, small lower wick
    assert d2.pending == []


# ---------- events (interface) ----------

def test_event_point_in_time():
    e = EconomicEvent("cpi", "CPI", 1000, actual_release_time=1000, reported_value=3.1,
                      consensus_value=3.0, consensus_available_at=500)
    assert e.as_of(999).reported_value is None and e.as_of(999).consensus_value == 3.0
    assert e.raw_surprise(999) is None and e.raw_surprise(1000) == pytest.approx(0.1)
    bars = [Bar(0, 3600, 1, 2, 0.5, 1.5)]
    assert event_zone(e, bars, "X", now=3599) is None
    assert event_zone(e, bars, "X", now=3600).upper_bound == 2


# ---------- causality / parity (synthetic fixture) ----------

def synthetic_bars(n=600, seed=7, d=900, start=ts(2026, 1, 5, 13, 0)):
    rnd, px, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = px
        c = o + rnd.gauss(0, 0.4)
        h, l = max(o, c) + abs(rnd.gauss(0, 0.3)), min(o, c) - abs(rnd.gauss(0, 0.3))
        out.append(Bar(start + i * d, d, o, h, l, c, rnd.uniform(1, 10)))
        px = c
    return out


def _sig(eng):
    s = eng.summary()
    for z in s["zones"]:
        z["feature_snapshot"] = {k: (round(v, 9) if isinstance(v, float) else v) for k, v in z["feature_snapshot"].items()
                                 if not isinstance(v, tuple)}
    return s


def _cfg():
    return EngineConfig(session=US_EQUITY_RTH, orb=ORBRetestConfig(breakout_buffer_atr=0.1, max_bars_after_breakout=12))


def test_indicator_stream_batch_parity():
    bars = synthetic_bars()
    sf = StreamingFeatures()
    for s_, b_ in zip([sf.update(b) for b in bars], batch_features(bars)):
        for k in ("atr", "band_a", "band_b"):
            assert (s_[k] is None) == (b_[k] is None)
            if s_[k] is not None:
                assert s_[k] == pytest.approx(b_[k], rel=1e-9, abs=1e-9)


def test_engine_stream_vs_batch_parity_all_detectors():
    bars = synthetic_bars()
    a, b = PriceActionEngine("SYN", 900, _cfg()), PriceActionEngine("SYN", 900, _cfg())
    for bar in bars:
        a.update(bar)
    b.run_batch(bars)
    sa, sb = _sig(a), _sig(b)
    assert sa["transitions"] == sb["transitions"] and sa["candidates"] == sb["candidates"]
    assert [z["zone_id"] for z in sa["zones"]] == [z["zone_id"] for z in sb["zones"]]
    assert sa["zones"] == sb["zones"]
    kinds = {z["zone_type"] for z in sa["zones"]}
    assert {"opening_range", "dual_band_breakout", "wick_reversal"} <= kinds
    assert len(sa["candidates"]) >= 1


def test_prefix_invariance_no_retroactive_signals():
    bars = synthetic_bars()
    full = PriceActionEngine("SYN", 900, _cfg())
    full.run_batch(bars)
    part = PriceActionEngine("SYN", 900, _cfg())
    part.run_batch(bars[:300])
    cut = bars[299].end
    assert [c.candidate_id for c in part.candidates] == [c.candidate_id for c in full.candidates if c.detected_at <= cut]
    assert [t for t in part.transitions] == [t for t in full.transitions if t.at <= cut]


def test_unconfirmed_duplicate_out_of_order_refused():
    bars = synthetic_bars(5)
    e = PriceActionEngine("SYN", 900)
    assert e.update(bars[0], now=bars[0].end - 1) == [] and e.refused[-1][1] == "bar_not_confirmed"
    e.update(bars[0])
    e.update(bars[0])
    assert e.refused[-1][1] == "duplicate_or_out_of_order"
    unverified = Bar(bars[1].start, 900, 1, 1, 1, 1, provider_completion_verified=False)
    e.update(unverified, now=10**12)
    assert e.refused[-1][1] == "bar_not_confirmed"


def test_orb_snapshot_restore_and_persisted_transitions(tmp_path):
    bars = synthetic_bars()
    ref = ORBRetestDetector("SYN", 900, US_EQUITY_RTH)
    feats = batch_features(bars)
    for b, c in zip(bars, feats):
        ref.step(b, c)
    first = ORBRetestDetector("SYN", 900, US_EQUITY_RTH)
    for b, c in zip(bars[:250], feats[:250]):
        first.step(b, c)
    second = ORBRetestDetector("SYN", 900, US_EQUITY_RTH)
    second.restore(first.snapshot())
    for b, c in zip(bars[250:], feats[250:]):
        second.step(b, c)
    assert first.transitions + second.transitions == ref.transitions
    store = TransitionStore(tmp_path / "pa.sqlite")
    n = store.record(ref.transitions + ref.candidates)
    assert n == len(ref.transitions) + len(ref.candidates)
    assert store.record(ref.transitions + ref.candidates) == 0  # duplicates refused
    assert store.candidate_count() == len(ref.candidates)


# ---------- control plane: proposals only ----------

def test_candidate_goes_through_control_plane_as_proposal():
    from atlas.control.engine import ActionableControlPlaneEngine

    d = ORBRetestDetector("SPY", 3600, US_EQUITY_RTH)
    for b in _orb_long_bars():
        d.step(b, {})
    from atlas.features.price_action.proposals import Abstained, evaluate
    from tests.price_action.test_predict import synthetic_setup_registry

    c = d.candidates[0]
    _, ev0 = evaluate(c)                       # no validated model registered -> abstain, no proposal
    assert ev0.abstained and "no_validated_model" in ev0.abstention_reason
    with pytest.raises(Abstained):
        candidate_to_signal(c, ev0)
    pred, ev = evaluate(c, model_version="synthetic-setup-v1", registry=synthetic_setup_registry(p=0.6))
    assert not ev.abstained, ev.abstention_reason
    sig = candidate_to_signal(c, ev)
    assert sig.execution_permission == "none" and sig.direction == "BUY" and sig.telemetry["probability_calibrated"] is True
    assert sig.conviction == pytest.approx(pred.probability_positive)
    report = ActionableControlPlaneEngine().ingest_whale_policy_signal(sig, track="open_market")
    assert report.execution_permission == "none"
    assert report.connector_receipt is None  # no connector: nothing dispatched


def test_quant_api_endpoints():
    from fastapi.testclient import TestClient

    from atlas.api.app import app

    client = TestClient(app)
    rows = [[b.start, b.open, b.high, b.low, b.close, b.volume] for b in _orb_long_bars()]
    r = client.post("/api/quant/analyze", json={"instrument": "SPY", "timeframe": 3600, "rows": rows,
                                                "session": "us_equity_rth", "data_label": "synthetic_fixture"})
    assert r.status_code == 200
    body = r.json()
    assert body["execution_permission"] == "none" and body["feed_origin"] == "synthetic_fixture"
    assert body["proposals"] == []          # no validated setup model: abstain rather than propose
    assert body["evaluations"][0]["evaluation"]["abstention_reason"] == ["no_validated_model"]
    rp = client.get("/api/quant/replay", params={"symbol": "SPY", "resolution": "60"})
    assert rp.status_code == 200 and rp.json()["execution_permission"] == "none"
    assert client.post("/api/quant/analyze", json={"instrument": "X", "timeframe": 3600, "rows": rows, "session": "mars"}).status_code == 400
    bad = [[0, 10, 9, 8, 9.5, 1]]
    assert client.post("/api/quant/analyze", json={"instrument": "X", "timeframe": 3600, "rows": bad}).status_code == 422
    g = client.get("/api/quant/zones", params={"symbol": "SPY", "resolution": "60"})
    assert g.status_code == 200 and g.json()["execution_permission"] == "none"
    assert client.get("/api/quant/setups", params={"symbol": "SPY", "resolution": "7"}).status_code == 400
