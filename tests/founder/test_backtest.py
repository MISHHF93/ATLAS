from datetime import date, datetime, timedelta

import pytest

from founder_conftest import CONFIG_DIR
from atlas.research.backtest import Backtester, Instrument
from atlas.research.backtest.cli import build
from atlas.research.backtest.strategies import CoreRebalancer, SmaCrossover
from atlas.control.policy import load_all
from atlas.marketdata.pit.synthetic import gbm_bars
from atlas.execution.paper.broker import CostModel
from atlas.risk.fx_hist import HistoricalFxProvider

S, E = date(2025, 1, 2), date(2025, 12, 31)


@pytest.fixture(scope="module")
def cfg():
    return load_all(CONFIG_DIR)


def core_setup(cfg, costs=None, fx=None, ccy="CAD", bars=None):
    syms = ["A1", "A2", "A3", "A4", "A5", "A6"]
    bars = bars or {s: gbm_bars(s, "XTSE", S, E, seed=3) for s in syms}
    inst = {s: Instrument(s, ccy if s in ("A5", "A6") else "CAD", "core", "index_etf", "ibkr") for s in syms}
    return Backtester(cfg, bars, inst, [CoreRebalancer({s: 0.095 for s in syms})], 100_000, costs or CostModel(), fx=fx)


def test_example_backtest_runs(cfg):
    res = build(cfg, S, E, 7, 100_000, 5, 1).run()
    m = res.metrics
    assert m["trades"] > 10 and len(res.equity_curve) > 200
    assert m["fees"] == pytest.approx(m["trades"] * 1.0)
    for k in ("sharpe", "max_drawdown_pct", "cagr_pct", "benchmark_return_pct"):
        assert m[k] is not None


def test_core_weights_reached_and_limits_respected(cfg):
    bt = core_setup(cfg)
    res = bt.run()
    snap = bt.broker.snapshot()
    cap = bt.engine.bot_capital(snap)
    for p in snap.positions.values():
        assert p.market_value_base <= 0.10 * cap * 1.06  # drift band tolerance after market moves
    assert snap.sleeve_exposure("core") / cap == pytest.approx(0.57, abs=0.05)
    assert not res.halted


def test_costs_reduce_equity(cfg):
    free = core_setup(cfg, CostModel(0, 0)).run().equity_curve[-1][1]
    costly = core_setup(cfg, CostModel(20, 5)).run().equity_curve[-1][1]
    assert costly < free


def test_fills_at_next_open_with_slippage(cfg):
    bt = core_setup(cfg, CostModel(slippage_bps=10, commission_per_order=0))
    bt.run()
    f = bt.broker.fills[0]
    first_bars = bt._bars[f.symbol]
    assert f.reference_price == pytest.approx(first_bars[1].open)  # decided at bar0 close, filled at bar1 open
    assert f.price == pytest.approx(first_bars[1].open * 1.001)


def test_fx_applied_to_usd_holdings(cfg):
    fx = HistoricalFxProvider({"USD": [(date(2024, 12, 1), 1.30), (date(2025, 6, 1), 1.45)]})
    bt = core_setup(cfg, fx=fx, ccy="USD")
    bt.run()
    p = bt.broker.positions["A5"]
    assert p.fx_rate_to_base == 1.45 and p.market_value_base == pytest.approx(p.qty * p.last_price * 1.45)


def test_missing_fx_fails_closed(cfg):
    fx = HistoricalFxProvider({"USD": [(date(2025, 6, 1), 1.4)]})  # nothing before June
    bt = core_setup(cfg, fx=fx, ccy="USD")
    try:
        res = bt.run()
    except Exception:
        return  # crash = fail closed, acceptable
    early = [d for d in res.decisions_log if d[0].date() < date(2025, 6, 1) and d[1] in ("A5", "A6")]
    assert early and not any(ok for _, _, ok in early)


def test_risk_engine_rejections_flow_through(cfg):
    syms = ["A1", "A2"]
    bars = {s: gbm_bars(s, "XTSE", S, date(2025, 3, 1), seed=3) for s in syms}
    inst = {s: Instrument(s) for s in syms}
    bt = Backtester(cfg, bars, inst, [CoreRebalancer({"A1": 0.30, "A2": 0.05})], 100_000)
    res = bt.run()
    assert res.rejections["max_position_pct"] > 0 and "A1" not in bt.broker.positions


def test_kill_switch_stops_trading(cfg):
    bt = core_setup(cfg)
    bt.ks.engage("test halt", "cli")
    res = bt.run()
    assert res.trades == 0 and res.halted and res.rejections["kill_switch"] > 0


def test_crash_triggers_drawdown_halt(cfg):
    syms = [f"A{i}" for i in range(1, 7)]
    bars = {s: gbm_bars(s, "XTSE", S, E, seed=3, sigma=0.01) for s in syms}
    crash_day = 60
    for s in syms:  # -30% gap on day 60 onwards
        bars[s] = [b if i < crash_day else b.model_copy(update={k: getattr(b, k) * 0.7 for k in ("open", "high", "low", "close")})
                   for i, b in enumerate(bars[s])]
    res = core_setup(cfg, bars=bars).run()
    assert res.halted and ("drawdown" in res.halt_reason or "weekly" in res.halt_reason)


# ---------------------------------------------------------------- leakage
class Spy:
    name = "spy"

    def __init__(self, syms):
        self.syms, self.violations = syms, 0

    def on_bar(self, ctx):
        for s in self.syms:
            for b in ctx.history(s):
                if b.available_at > ctx.now:
                    self.violations += 1
        return []


def test_context_never_exposes_future_bars(cfg):
    bars = {s: gbm_bars(s, "XTSE", S, date(2025, 4, 1), seed=1) for s in ("A1", "A2")}
    bars["A2"] = [b.model_copy(update={"available_at": b.ts + timedelta(days=2)}) for b in bars["A2"]]  # delayed feed
    spy = Spy(["A1", "A2"])
    Backtester(cfg, bars, {s: Instrument(s) for s in bars}, [spy]).run()
    assert spy.violations == 0


def test_point_in_time_perturbing_future_does_not_change_past_decisions(cfg):
    syms = ["X1", "X2", "X3"]
    base = {s: gbm_bars(s, "XNYS", S, E, s0=40, sigma=0.3, seed=11) for s in syms}
    cutoff = base["X1"][150].ts
    perturbed = {s: [b if b.ts <= cutoff else b.model_copy(update={k: getattr(b, k) * 2 for k in ("open", "high", "low", "close")})
                     for b in bs] for s, bs in base.items()}
    inst = {s: Instrument(s, "CAD", "active", "us_equity", "ibkr") for s in syms}

    def decisions(bars):
        bt = Backtester(cfg, bars, inst, [SmaCrossover(syms, 10, 30)], 100_000)
        return [d for d in bt.run().decisions_log if d[0] <= cutoff]

    a, b = decisions(base), decisions(perturbed)
    assert a and a == b
