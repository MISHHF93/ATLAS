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
