from datetime import datetime, time, timezone

import pytest

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.calendar import TradingCalendar
from atlas.features.price_action.contracts import NoTradeReason, resolve, unify
from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.htf import DailyBias
from atlas.features.price_action.levels import (InteractionConfig, LevelInteractionEngine, LiquidityLevelRegistry,
                                                PriceLevel, RegistryConfig)
from atlas.features.price_action.reentry import ReentryConfig, ReentryGovernor
from atlas.features.price_action.strategies import StrategyRegistry
from atlas.features.price_action.suite import GoldBox, GoldConfig, StrategyToggles, SuiteConfig, is_gold
from atlas.ml.selector import context, session_bucket


def ts(y, m, d, hh, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp())


def lvl(price, kind="high", avail=0, st="prev_day"):
    return PriceLevel(f"X:{st}:{kind}:{price}", "X", "v", st, kind, price, 0, avail, "s", 900)


def B(t, o, h, l, c, d=900):
    return Bar(t, d, o, h, l, c, 1.0)


# ---------- calendar / sessions ----------
def test_comex_calendar_dst_holiday_and_weekend():
    cal = TradingCalendar("COMEX")
    assert cal.session_of(ts(2026, 10, 24, 15)) is None                      # Saturday
    s = cal.session_of(ts(2026, 9, 7, 15))                                    # Labor Day: early close
    assert s is not None and s[2] == ts(2026, 9, 7, 17)
    a = cal.session_of(ts(2026, 10, 20, 15))
    b = cal.session_of(ts(2026, 11, 10, 15))                                  # after US DST end
    assert a[2] % 3600 == 0 and b[2] % 3600 == 0 and a[2] - a[1] == b[2] - b[1]


def test_session_bucket_uses_new_york_time_across_dst():
    assert session_bucket(ts(2026, 10, 20, 12, 30)) == "ny_am"                # 08:30 EDT
    assert session_bucket(ts(2026, 11, 10, 13, 30)) == "ny_am"                # 08:30 EST
    assert session_bucket(ts(2026, 11, 10, 12, 30)) == "london"               # 07:30 EST


# ---------- interaction engine ----------
def run_levels(level, bars, **kw):
    e = LevelInteractionEngine(InteractionConfig(tick=0.1, **kw))
    e.watch(level, bars[0].close)
    out = []
    for b in bars:
        out += e.step(b, 1.0)
    return e, [x.kind + ("/post" if x.post_accept else "") for x in out]


def test_sweep_then_reclaim_is_one_outcome():
    t0 = ts(2026, 10, 20, 0)
    bars = [B(t0, 99, 99.5, 98.8, 99.2), B(t0 + 900, 99.2, 100.6, 99.1, 99.7)]
    _, k = run_levels(lvl(100.0), bars)
    assert "breakout_attempt" in k and "sweep" in k and "reclaim" in k and "breakout_acceptance" not in k


def test_acceptance_then_retest_success():
    t0 = ts(2026, 10, 20, 0)
    bars = [B(t0, 99, 99.5, 98.8, 99.2), B(t0 + 900, 99.2, 100.8, 99.1, 100.6), B(t0 + 1800, 100.6, 101.2, 100.4, 101.0),
            B(t0 + 2700, 101, 101.1, 100.02, 100.9)]
    _, k = run_levels(lvl(100.0), bars, reject_atr=0.25)
    assert k.index("breakout_acceptance") < k.index("retest_success/post")
    assert "reclaim" not in k


def test_level_not_used_before_available():
    t0 = ts(2026, 10, 20, 0)
    _, k = run_levels(lvl(100.0, avail=t0 + 900), [B(t0, 99, 101, 98, 99), B(t0 + 900, 99, 99.2, 98.9, 99)])
    assert "breakout_attempt" not in k


# ---------- registry causality ----------
def test_swing_available_only_after_k_bars_and_prev_day_after_day_end():
    t0 = ts(2026, 10, 19, 0)
    reg = LiquidityLevelRegistry("BTC", "x", 3600, TradingCalendar("crypto"), RegistryConfig(swing_k=2, sessions=False))
    highs = [1, 2, 5, 2, 1] + [1] * 25
    new = []
    for i, h in enumerate(highs):
        b = B(t0 + i * 3600, h - 0.5, h, h - 1, h - 0.5, 3600)
        for lv in reg.step(b, 1.0):
            new.append((i, lv))
    sw = [(i, lv) for i, lv in new if lv.source_type == "swing" and lv.kind == "high"]
    assert sw[0][1].price == 5 and sw[0][0] == 4 and sw[0][1].available_ts == t0 + 5 * 3600
    pd_ = [(i, lv) for i, lv in new if lv.source_type == "prev_day"]
    assert pd_ and pd_[0][0] == 24 and pd_[0][1].available_ts == t0 + 24 * 3600


# ---------- gold box / ORB availability ----------
def gold_bars(day=(2026, 10, 20), dur=300, skip=()):
    t0 = ts(*day, 12, 0)                                                      # 08:00 EDT
    out = []
    px = 2000.0
    for i in range(0, 4 * 3600 // dur):
        t = t0 + i * dur
        if t in skip:
            continue
        nyt = (t - t0) / 60
        if 20 <= nyt < 50:
            o, h, l, c = 2000, 2002, 1998, 2000
        elif 50 <= nyt < 60:
            o, h, l, c = 2000, 2004, 2000, 2003.5                             # breakout + acceptance
        elif 60 <= nyt < 70:
            o, h, l, c = 2003.5, 2004, 2001.9, 2003.0                         # retest of 2002 that holds
        else:
            o, h, l, c = px, px + 0.5, px - 0.5, px
        out.append(B(t, o, h, l, c, dur))
    return out


def gold_cfg(**kw):
    return SuiteConfig(toggles=StrategyToggles(False, True, True), tick=0.1, calendar="COMEX",
                       interaction=InteractionConfig(accept_bars=2, reject_atr=0.0), **kw)


def test_gold_box_available_only_at_0850_and_snapback_after_retest():
    e = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars())
    su = e.detectors[-1]
    box = [z for z in su.zones if z.zone_type.startswith("gold_box")]
    assert len(box) == 1 and box[0].confirmed_at == ts(2026, 10, 20, 12, 50)
    assert (box[0].lower_bound, box[0].upper_bound) == (1998, 2002)
    assert all(c.detected_at >= ts(2026, 10, 20, 12, 50) for c in su.candidates)
    dets = [c.detector for c in su.candidates]
    assert "gold_orb_breakout" in dets
    assert all(c.execution_permission == "none" for c in su.candidates)


def test_gold_box_on_15m_is_insufficient_data_not_guessed():
    e = PriceActionEngine("GC", 900, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars(dur=900))
    su = e.detectors[-1]
    assert not [z for z in su.zones if z.zone_type.startswith("gold_box")]
    assert any(n["reason"] == "INSUFFICIENT_DATA" for n in su.no_trades)


def test_missing_bar_in_box_abstains():
    e = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars(skip=(ts(2026, 10, 20, 12, 30),)))
    su = e.detectors[-1]
    assert not su.candidates and any(n["reason"] == "INSUFFICIENT_DATA" for n in su.no_trades)


def test_gold_rules_do_not_apply_to_other_assets():
    assert is_gold("GC") and is_gold("MGC") and not is_gold("SI") and not is_gold("GLD")
    e = PriceActionEngine("SI", 300, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars())
    assert not e.detectors[-1].candidates and not e.detectors[-1].zones


def test_live_batch_parity():
    bars = gold_bars()
    a = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    a.run_batch(bars)
    b = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    for x in bars:
        b.update(x)
    assert [c.to_dict() for c in a.candidates] == [c.to_dict() for c in b.candidates]


# ---------- conflict / dedupe / re-entry ----------
def test_continuation_and_reversal_on_same_event_never_both_actionable():
    e = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars())
    c = e.detectors[-1].candidates[0]
    u1 = unify(c, 300)
    import copy
    c2 = copy.deepcopy(c)
    c2.candidate_id += ":rev"
    c2.direction = "short" if c.direction == "long" else "long"
    u2 = unify(c2, 300)
    out = resolve([u1, u2])
    assert not any(u.actionable for u in out)
    assert {u.no_trade_reason for u in out} == {NoTradeReason.CONFLICTING_CANDIDATES.value}


def test_same_direction_shared_evidence_dedupes():
    e = PriceActionEngine("GC", 300, EngineConfig(suite=gold_cfg()))
    e.run_batch(gold_bars())
    c = e.detectors[-1].candidates[0]
    import copy
    c2 = copy.deepcopy(c)
    c2.candidate_id += ":dup"
    c2.detected_at += 300
    out = resolve([unify(c, 300), unify(c2, 300)])
    assert [u.actionable for u in out] == [True, False] and out[0].corroborating == [c2.candidate_id]


def test_reentry_limits():
    g = ReentryGovernor(ReentryConfig(per_level=1, per_day=2, cooldown_s=600))
    assert g.allow("sfp", "L1", "d", 0)[0]
    g.record("sfp", "L1", "d", 0)
    assert g.allow("sfp", "L1", "d", 10_000) == (False, "per-level limit")
    assert g.allow("sfp", "L2", "d", 100) == (False, "cooldown")
    g.record("sfp", "L2", "d", 1000)
    assert g.allow("sfp", "L3", "d", 10_000) == (False, "per-day limit")
    assert g.allow("orb", "L1", "d", 10_000)[0]


# ---------- HTF ----------
def test_htf_insufficient_then_bullish():
    d0 = ts(2025, 1, 1, 0)
    rows = [(d0 + i * 86400, 100 + i + 1 + (i % 7), 100 + i - 1, 100 + i + 0.5) for i in range(260)]
    hb = DailyBias(rows)
    assert hb.at(d0 + 100 * 86400)["bias"] == "insufficient"
    r = hb.at(d0 + 260 * 86400)
    assert r["trend_daily"] == "bullish" and r["bias"] in ("bullish", "conflicting")
    assert hb.at(d0 + 259 * 86400 + 3600)["daily_bars"] == 259                # bar 259 not yet available


# ---------- registry / selector / permissions ----------
def test_strategy_registry_toggles(tmp_path):
    r = StrategyRegistry(tmp_path / "s.json")
    assert not r.enabled("sfp") and r.enabled("wick_reversal")
    r.set("sfp", True)
    assert StrategyRegistry(tmp_path / "s.json").enabled("sfp")
    with pytest.raises(ValueError):
        r.set("four_box", True)
    assert all(x["execution_permission"] == "none" for x in r.listing())


def test_selector_context_is_causal_and_onehot():
    c = context(ts(2026, 10, 20, 12, 30), "bullish", 0.9, "short")
    assert c["vol_regime"] == "high" and c["htf_against"] == 1.0 and c["scenario"] == "bullish|high|ny_am"
    assert sum(c[k] for k in c if k.startswith("sess_")) == 1.0


def test_suite_off_by_default():
    e = PriceActionEngine("GC", 300, EngineConfig())
    assert not any(type(d).__name__ == "LevelSuiteDetector" for d in e.detectors)
