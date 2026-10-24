from datetime import date

from atlas.feeds.contracts import contract_for, front_contract, last_trade_date
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.levels import LiquidityLevelRegistry, RegistryConfig


def test_gc_contract_spec_uses_instrument_master():
    g = contract_for("GC")
    assert g.multiplier == 100 and g.tick_value == 10.0 and g.cost_price_units == 0.25
    assert g.verified is False and g.cost_source == "research_assumption" and g.gold_only
    assert last_trade_date(g, 2026, 12) == date(2026, 12, 29)
    code, lt, roll = front_contract(g, date(2026, 10, 24))
    assert code == "GCZ26" and roll < date(2026, 12, 1) < lt       # metals roll before first notice
    assert front_contract(g, date(2026, 11, 27))[0] == "GCG27"
    assert front_contract(contract_for("ES"), date(2026, 10, 24))[0] == "ESZ26"
    assert contract_for("BTCUSDT") is None


def test_round_levels_and_confluence():
    from atlas.features.price_action.calendar import calendar_for
    reg = LiquidityLevelRegistry("GC", "COMEX", 900, calendar_for("GC", "future"), RegistryConfig(round_step=50.0, sessions=False, periods=()), tick=0.1)
    t, out = 1_790_000_000, []
    for i, c in enumerate((4012.0, 4013.0, 4049.9, 4051.0)):
        out += reg.step(Bar(t + i * 900, 900, c, c + 1, c - 1, c, 1.0), atr=5.0)
    rounds = [l for l in out if l.source_type == "round"]
    assert {(l.kind, l.price) for l in rounds} >= {("high", 4050.0), ("low", 4000.0), ("high", 4100.0), ("low", 4050.0)}
    assert all(l.available_ts >= l.created_ts for l in rounds)
    lv = reg.levels[0]
    assert hasattr(lv, "confluence_ids") and lv.rejection_count == 0 and lv.sweep_count == 0


def test_ma_and_vwap_zone_types_are_causal_and_reuse_indicators():
    from atlas.features.price_action.calendar import calendar_for
    from atlas.features.price_action.indicators import EMA, BarVWAP
    from atlas.features.price_action.levels import priority_of
    reg = LiquidityLevelRegistry("GC", "COMEX", 900, calendar_for("GC", "future"),
                                 RegistryConfig(ma_periods=(3,), session_vwap=True, sessions=False, periods=()), tick=0.1)
    t, out, ema, vw = 1_790_000_000, [], EMA(3), BarVWAP()
    closes = (4000.0, 4002.0, 4004.0, 4006.0, 4001.0)
    for i, c in enumerate(closes):
        b = Bar(t + i * 900, 900, c, c + 1, c - 1, c, 10.0 + i)
        new = reg.step(b, atr=5.0)
        out += new
        exp = ema.update(c)
        ma = [l for l in new if l.source_type == "ma3"]
        if exp is None:
            assert not ma                      # not enough history: no level, nothing fabricated
        else:
            assert len(ma) == 1 and abs(ma[0].price - exp) < 1e-9 and ma[0].available_ts == b.end
            assert ma[0].kind == ("high" if exp > c else "low")
        s = reg.cal.session_of(b.start)
        if s is not None:
            v = vw.update(b.high, b.low, b.close, b.volume, s[0])
            got = [l for l in new if l.source_type == "vwap"]
            assert len(got) == 1 and abs(got[0].price - v) < 1e-9
    live = [l for l in reg.levels if l.source_type in ("ma3", "vwap") and (l.expires_ts or 0) > t + 5 * 900]
    assert len({l.source_type for l in live}) == len(live)   # one live dynamic level per type
    assert priority_of("ma20") == priority_of("ma3") == 2 and priority_of("vwap") == 3


def test_vwap_absent_without_volume():
    from atlas.features.price_action.calendar import calendar_for
    reg = LiquidityLevelRegistry("GC", "COMEX", 900, calendar_for("GC", "future"),
                                 RegistryConfig(session_vwap=True, sessions=False, periods=()), tick=0.1)
    out = []
    for i in range(4):
        out += reg.step(Bar(1_790_000_000 + i * 900, 900, 4000.0, 4001.0, 3999.0, 4000.0, 0.0), atr=5.0)
    assert not [l for l in out if l.source_type == "vwap"]
