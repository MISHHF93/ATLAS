from datetime import date

import pytest

from founder_conftest import CONFIG_DIR, state
from atlas.control.policy import load_all
from atlas.risk import Position
from atlas.portfolio.sleeves.rebalancer import SleeveRebalancer

MON, TUE, WED = date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)
CORE = {f"E{i}": 1 / 6 for i in range(6)}
HR = {"BTC": 1.0}


@pytest.fixture(scope="module")
def cfg():
    return load_all(CONFIG_DIR)


def prices(syms, px=100.0):
    return {s: (px, 1.0) for s in syms}


def held(values: dict[str, float], sleeve_of) -> dict[str, Position]:
    return {s: Position(symbol=s, qty=v / 100, avg_price=100, last_price=100, sleeve=sleeve_of(s)) for s, v in values.items()}


def sl(s):
    return "high_risk" if s == "BTC" else "core"


def at_target(extra=None):
    v = {s: 1960.0 for s in CORE} | {"BTC": 1960.0}
    v.update(extra or {})
    return v


def mk(cfg, **kw):
    return SleeveRebalancer(cfg.risk, {"core": CORE, "high_risk": HR}, **kw)


def test_validation(cfg):
    with pytest.raises(ValueError):
        SleeveRebalancer(cfg.risk, {"derivatives": {"X": 1}})
    with pytest.raises(ValueError):
        SleeveRebalancer(cfg.risk, {"nope": {"X": 1}})
    with pytest.raises(ValueError):
        SleeveRebalancer(cfg.risk, {"core": {"A": 0.7, "B": 0.5}})


def test_initial_deployment_ignores_cost_and_clips_to_position_limit(cfg):
    r = mk(cfg, slippage_bps=5, commission_per_order=1)
    plan = r.plan(state(), prices(list(CORE) + ["BTC"]), MON)
    assert "schedule" in plan.triggered
    buys = {t.symbol: t for t in plan.trades}
    assert set(buys) == set(CORE) | {"BTC"}
    assert all(t.value_base <= 0.10 * 20_000 * 0.98 + 1e-6 for t in buys.values())  # 10% position limit
    assert buys["BTC"].value_base == pytest.approx(1960)  # 10% sleeve target clipped to 9.8%


def test_no_trigger_within_band(cfg):
    r = mk(cfg)
    r.plan(state(), prices(CORE), MON)  # consume this week's schedule
    v = at_target({"E0": 2100})
    s = state(cash=20_000 - sum(v.values()), positions=held(v, sl))
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), TUE)
    assert plan.triggered == [] and plan.trades == []


def test_holding_drift_triggers(cfg):
    r = mk(cfg)
    r.plan(state(), prices(CORE), MON)
    v = at_target({"E0": 1960 + 1200})  # +6pp of bot capital
    s = state(cash=max(0, 20_000 - sum(v.values())), positions=held(v, sl), total=100_000)
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), TUE)
    assert any(t.startswith("drift") for t in plan.triggered)
    assert any(t.symbol == "E0" and t.side == "sell" for t in plan.trades)


def test_sleeve_drift_triggers(cfg):
    r = mk(cfg)
    r.plan(state(), prices(CORE), MON)
    v = {s: 1960.0 for s in CORE} | {"BTC": 3200.0}  # high_risk 16% vs 10%
    s = state(cash=20_000 - sum(v.values()), positions=held(v, sl))
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), WED)
    assert "drift:high_risk" in plan.triggered


def test_cost_aware_skips_small_in_band_trades(cfg):
    r = mk(cfg, slippage_bps=5, commission_per_order=1)
    v = at_target({"E0": 1860, "E1": 2060})  # $100 off: 5bps + 100bps commission > 10bps, in band
    s = state(cash=20_000 - sum(v.values()), positions=held(v, sl))
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), MON)  # scheduled
    assert "schedule" in plan.triggered
    assert not any(t.symbol in ("E0", "E1") for t in plan.trades)
    assert any("cost" in why for sym, why in plan.skipped if sym in ("E0", "E1"))


def test_cheap_in_band_trade_executes(cfg):
    r = mk(cfg, slippage_bps=1, commission_per_order=0.05)
    v = at_target({"E0": 1700})
    s = state(cash=20_000 - sum(v.values()), positions=held(v, sl))
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), MON)
    assert any(t.symbol == "E0" and t.side == "buy" for t in plan.trades)


def test_min_trade_value(cfg):
    r = mk(cfg, slippage_bps=0, commission_per_order=0)
    v = at_target({"E0": 1930})  # $30 < $50
    s = state(cash=20_000 - sum(v.values()), positions=held(v, sl))
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), MON)
    assert not any(t.symbol == "E0" for t in plan.trades)
    assert ("E0", "below min trade 50.0") in plan.skipped


def test_cap_breach_forces_pro_rata_sells_and_no_buys(cfg):
    r = mk(cfg, slippage_bps=5, commission_per_order=1)
    r.plan(state(), prices(CORE), MON)
    v = {s: 1960.0 for s in CORE} | {"BTC": 1960.0, "ACT": 6000.0}  # 17,720 gross
    s = state(total=80_000, cash=500, positions=held(v, lambda x: "active" if x == "ACT" else sl(x)))  # cap = 16,000
    s = s.model_copy(update={"total_account_equity_base": 80_000})
    plan = r.plan(s, prices(list(v)), TUE)
    assert "cap_breach" in plan.triggered
    assert plan.trades and all(t.side == "sell" for t in plan.trades)
    assert any(t.symbol == "ACT" for t in plan.trades)  # unmanaged sleeve reduced too
    sold = sum(t.value_base for t in plan.trades)
    assert sum(v.values()) - sold <= 16_000 * 0.98 + 1


def test_buys_scaled_to_settled_cash(cfg):
    r = mk(cfg, slippage_bps=0, commission_per_order=0)
    s = state().model_copy(update={"settled_cash_base": 5_000.0})
    plan = r.plan(s, prices(list(CORE) + ["BTC"]), MON)
    assert sum(t.value_base for t in plan.trades if t.side == "buy") <= 5_000 * 0.98 + 1e-6


def test_schedule_once_per_week(cfg):
    r = mk(cfg)
    assert r._scheduled(MON) and not r._scheduled(TUE) and r._scheduled(date(2026, 10, 19))


# ---------------------------------------------------------------- backtest wiring
def test_backtest_sleeves_converge_and_respect_limits(cfg):
    from atlas.research.backtest.cli import build
    bt = build(cfg, date(2025, 1, 2), date(2025, 6, 30), 7, 100_000, 5, 1)
    res = bt.run()
    snap = bt.broker.snapshot()
    cap = bt.engine.bot_capital(snap)
    core = snap.sleeve_exposure("core") / cap * 100
    hr = snap.sleeve_exposure("high_risk") / cap * 100
    assert 50 <= core <= 70 and 0 < hr <= 15
    assert snap.gross_exposure_base <= 0.20 * snap.total_account_equity_base + 1
    assert res.rejections.get("broker:reject", 0) == 0
    reb = bt.strategies[0]
    assert reb.plans and any("schedule" in p.triggered for _, p in reb.plans)


def test_backtest_cap_enforced_when_bot_outgrows_cap(cfg):
    from atlas.research.backtest import Backtester, Instrument
    from atlas.research.backtest.strategies import SleeveRebalanceStrategy
    from atlas.marketdata.pit.synthetic import gbm_bars
    syms = [f"E{i}" for i in range(6)]
    bars = {s: gbm_bars(s, "XTSE", date(2025, 1, 2), date(2025, 12, 31), mu=0.0, sigma=0.05, seed=5) for s in syms}
    for s in syms:  # +60% jump mid-year
        bars[s] = [b if i < 120 else b.model_copy(update={k: getattr(b, k) * 1.6 for k in ("open", "high", "low", "close")})
                   for i, b in enumerate(bars[s])]
    reb = SleeveRebalanceStrategy(SleeveRebalancer(cfg.risk, {"core": {s: 1 / 6 for s in syms}}))
    bt = Backtester(cfg, bars, {s: Instrument(s) for s in syms}, [reb], 100_000)
    bt.run()
    snap = bt.broker.snapshot()
    assert snap.gross_exposure_base <= 0.20 * snap.total_account_equity_base * 1.01
    assert not bt.ks.engaged
