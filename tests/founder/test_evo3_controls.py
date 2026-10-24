"""evo3: tighten-only re-entry loss caps (section 13), contract single source (section 6), paper realism (section 25)."""
import pytest

from atlas.execution.paper import ExecRealism, PaperBroker
from atlas.features.price_action.bars import Bar
from atlas.features.price_action.reentry import ReentryConfig, ReentryGovernor, load_reentry_config, tighten
from atlas.features.price_action.replay import PAPER_REALISM, ReplayTrade, paper_replay_config, try_fill
from atlas.risk.models import RiskDecision
from atlas.risk.sizing import contracts_for_risk

from founder_conftest import intent


def ok(i):
    return RiskDecision(intent_id=i.intent_id, approved=True, reasons=[], checks={}, halted=False, policy_version=4)


# ---- section 13 -------------------------------------------------------------------------------------------
def test_overlay_can_only_tighten():
    base = ReentryConfig(per_level=1, per_day=3, cooldown_s=3600, max_loss_r_per_day=2.0)
    c = tighten(base, {"per_day": 5, "cooldown_s": 60, "max_loss_r_per_day": 9.0, "per_level": 0,
                       "max_consecutive_losses": 2, "bogus": 1, "max_loss_r_per_family_day": None})
    assert (c.per_day, c.cooldown_s, c.max_loss_r_per_day, c.per_level) == (3, 3600, 2.0, 1)
    assert c.max_consecutive_losses == 2
    assert any("loosen" in n for n in c.overlay_notes) and any("unknown" in n for n in c.overlay_notes)
    assert tighten(base, {"per_day": 2, "cooldown_s": 7200}).per_day == 2


def test_default_overlay_loaded_and_missing_overlay_is_code_defaults(tmp_path):
    c = load_reentry_config()
    assert c.max_loss_r_per_family_day == 2.0 and c.max_loss_r_per_day == 3.0 and c.max_consecutive_losses == 2
    d = load_reentry_config(tmp_path / "none.yaml")
    assert d.max_loss_r_per_day is None and d.per_day == 3


def test_loss_caps_block_after_realized_losses_and_reset_next_day():
    g = ReentryGovernor(ReentryConfig(per_level=9, per_day=9, cooldown_s=0, max_loss_r_per_family_day=2.0,
                                      max_loss_r_per_day=3.0, max_consecutive_losses=5))
    assert g.allow("sfp", "a", "d1", 0)[0]
    g.record_outcome("sfp", "d1", -1.0)
    g.record_outcome("sfp", "d1", -1.2)
    assert g.allow("sfp", "b", "d1", 1) == (False, "family loss cap")
    assert g.allow("orb", "b", "d1", 1)[0]
    g.record_outcome("orb", "d1", -0.9)
    assert g.allow("orb", "c", "d1", 2) == (False, "daily loss cap")
    assert g.allow("sfp", "b", "d2", 3)[0]


def test_consecutive_losses_reset_by_a_win():
    g = ReentryGovernor(ReentryConfig(per_level=9, per_day=9, cooldown_s=0, max_consecutive_losses=2))
    g.record_outcome("orb", "d", -0.1); g.record_outcome("orb", "d", 0.5); g.record_outcome("orb", "d", -0.1)
    assert g.allow("orb", "x", "d", 0)[0]
    g.record_outcome("orb", "d", -0.1)
    assert g.allow("orb", "x", "d", 0) == (False, "consecutive losses")


# ---- section 6 ---------------------------------------------------------------------------------------------
def test_intel_spec_derived_from_contracts():
    from atlas.feeds.contracts import default_contracts
    from atlas.intel.data import SPEC
    for root, c in default_contracts().items():
        if root in SPEC:
            assert SPEC[root][1] == c.tick_size


def test_contracts_for_risk_rounds_down_and_includes_cost():
    n = contracts_for_risk("MGC", 500.0, 2000.0, 1990.0)
    assert n["contracts"] == 4 and n["risk_used_usd"] <= 500.0
    assert contracts_for_risk("MGC", 50.0, 2000.0, 1990.0)["contracts"] == 0


# ---- section 25 --------------------------------------------------------------------------------------------
def _t(**kw):
    return ReplayTrade("c", "d", "long", 0, 100.0, 99.0, 102.0, entry_type="limit", **kw)


def test_replay_realism_latency_trade_through_participation():
    cfg = paper_replay_config()
    assert cfg.latency_bars == PAPER_REALISM["latency_bars"] == 1
    touch = Bar(0, 60, 100.5, 101, 100.0, 100.5, volume=100)
    through = Bar(60, 60, 100.5, 101, 99.9, 100.5, volume=50)
    t = _t()
    assert not try_fill(t, through, cfg, age=0)          # latency
    assert not try_fill(t, touch, cfg, age=1)            # touch is not a trade-through
    t2 = _t(order_qty=1.0)
    assert try_fill(t2, through, cfg, age=1) and t2.fill_ratio == 1.0
    t3 = _t(order_qty=10.0)
    assert try_fill(t3, through, cfg, age=1) and t3.fill_ratio == pytest.approx(0.5)
    assert not try_fill(_t(), Bar(0, 60, 100, 101, 99, 100, volume=0), cfg, age=1)


def test_paper_broker_realism_latency_trade_through_partials():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, realism=ExecRealism())
    m = intent(qty=10, order_type="market", limit_price=None)
    b.submit(m, ok(m))
    assert not b.fills                                   # latency: nothing at submit
    b.on_price(m.symbol, 100.0, volume=50)               # 10% of 50 = 5
    assert sum(f.qty for f in b.fills) == pytest.approx(5)
    b.on_price(m.symbol, 100.0, volume=None)             # unknown volume -> no fill
    assert sum(f.qty for f in b.fills) == pytest.approx(5)
    b.on_price(m.symbol, 100.0, volume=1000)
    assert sum(f.qty for f in b.fills) == pytest.approx(10) and not b.open_orders
    b2 = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, realism=ExecRealism(max_participation=None))
    lim = intent(qty=1, limit_price=99.0)
    b2.submit(lim, ok(lim))
    b2.on_price(lim.symbol, 99.0)                        # touch only
    assert not b2.fills
    b2.on_price(lim.symbol, 98.9)
    assert len(b2.fills) == 1


def test_paper_broker_default_unchanged():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000)
    m = intent(qty=1, order_type="market", limit_price=None)
    b.submit(m, ok(m))
    assert len(b.fills) == 1
