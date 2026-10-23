"""Remaining audit items: shared rate budget, broker persistence, open-sell no-short, unknown sector,
bounded trail, WAL/SHM perms."""
from __future__ import annotations

import os

from founder_conftest import CONFIG_DIR, intent, pos, state
from atlas.risk.ratelimit import SharedWindowLimiter
from atlas.risk.state_store import StateStore


def test_rate_budget_shared_between_processes(tmp_path):
    p = str(tmp_path / "s.sqlite"); t = [1000.0]
    a = SharedWindowLimiter(StateStore(p), 2, 60, clock=lambda: t[0])
    b = SharedWindowLimiter(StateStore(p), 2, 60, clock=lambda: t[0])
    a.record(); b.record()
    assert not a.would_allow() and not b.would_allow()
    t[0] += 61
    assert a.would_allow()


def test_open_sells_count_against_no_short(engine):
    s = state(cash=19_000, positions={"SPY": pos(qty=10)}).model_copy(update={"pending_sell_qty": {"SPY": 8.0}})
    d = engine.evaluate(intent(side="sell", qty=5), s)
    assert not d.approved and any("open sells" in r for r in d.reasons)
    assert engine.evaluate(intent(side="sell", qty=2), s).approved


def test_unknown_sector_is_capped(engine):
    cap = engine.policy.position_limits.max_sector_pct / 100 * 20_000
    held = {f"U{i}": pos(f"U{i}", qty=cap / 100 / 2, price=100.0) for i in range(2)}  # sector None, asset_class equity
    s = state(cash=20_000 - cap, positions=held)
    d = engine.evaluate(intent(symbol="NEW", qty=5, asset_class="equity"), s)
    assert any("sector unknown" in r for r in d.reasons)
    assert not any("sector" in r for r in engine.evaluate(intent(symbol="ETF", qty=5), s).reasons)  # index_etf exempt


def test_broker_state_survives_restart(tmp_path):
    from datetime import date
    from atlas.mcp.trading.service import build_service
    from atlas.risk.models import OrderIntent, RiskDecision
    sp = str(tmp_path / "state.sqlite")
    svc = build_service(CONFIG_DIR, state_path=sp)
    b = svc.broker
    i = OrderIntent(symbol="SPY", side="buy", qty=3, order_type="market", reference_price=100.0, sleeve="core",
                    asset_class="index_etf", broker="paper_sim", quote_age_s=0)
    b.submit(i, RiskDecision(intent_id=i.intent_id, approved=True, reasons=[], warnings=[], checks={}, halted=False, policy_version=1))
    lim = OrderIntent(symbol="SPY", side="sell", qty=1, order_type="limit", limit_price=150.0, reference_price=100.0,
                      sleeve="core", asset_class="index_etf", broker="paper_sim", quote_age_s=0)
    b.submit(lim, RiskDecision(intent_id=lim.intent_id, approved=True, reasons=[], warnings=[], checks={}, halted=False, policy_version=1))
    b.start_of_day_equity = 12345.0; b.today = date(2026, 10, 16)
    svc.persist()
    svc2 = build_service(CONFIG_DIR, state_path=sp)
    b2 = svc2.broker
    assert b2.positions["SPY"].qty == 3 and len(b2.open_orders) == 1 and b2.start_of_day_equity == 12345.0
    assert b2.snapshot().pending_sell_qty == {"SPY": 1.0}
    assert svc2.ledger.positions == {"SPY": 3} and abs(svc2.ledger.cash - b2.bot_cash_base) < 1e-6
    assert svc2.reconcile() == []
    assert next(b2._ids) > 2  # order ids don't collide after restart


def test_trail_bounded():
    from atlas.ops.pipeline_full import FullPipeline
    p = FullPipeline.__new__(FullPipeline); p.trail = []; p.trail_max = 3; p.pending_outcomes = []
    for i in range(10):
        p.trail.append({"i": i}); p.n_decisions = i + 1
        if len(p.trail) > p.trail_max:
            del p.trail[: len(p.trail) - p.trail_max]
    assert [t["i"] for t in p.trail] == [7, 8, 9]


def test_wal_shm_owner_only(tmp_path):
    p = str(tmp_path / "s.sqlite"); st = StateStore(p); st.set("k", 1); StateStore(p)
    for f in (p, p + "-wal", p + "-shm"):
        if os.path.exists(f):
            assert oct(os.stat(f).st_mode)[-3:] == "600", f
