"""Event-driven backtester that reuses the production RiskEngine.

Per bar timestamp t (bar close):
  1. new session date => PaperBroker.roll_day + RiskEngine.roll_session
  2. orders decided at t-1 fill at the symbol's next bar OPEN (no same-bar fills)
     with slippage + commission + FX conversion
  3. mark-to-market at close
  4. strategies see ONLY bars with available_at <= t (point-in-time context)
  5. every intent goes through RiskEngine.evaluate (same code as paper/live path)
"""
from __future__ import annotations

import bisect
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from atlas.governance.audit import AuditLog
from atlas.control.policy import LoadedConfig
from atlas.marketdata.pit.models import Bar
from atlas.execution.paper.broker import CostModel, PaperBroker
from atlas.risk import KillSwitch, OrderIntent, RiskEngine, Watchdog
from atlas.risk.anomaly import AnomalyMonitor
from atlas.risk.fx import FxRateProvider, StaticFxProvider
from atlas.risk.models import PortfolioState, RiskDecision
from atlas.risk.state_store import StateStore

from atlas.ops.timez import TORONTO  # noqa: E402


@dataclass(frozen=True)
class Instrument:
    symbol: str
    currency: str = "CAD"
    sleeve: str = "core"
    asset_class: str = "index_etf"
    broker: str = "ibkr"
    sector: str | None = None
    issuer: str | None = None


class Strategy(Protocol):
    name: str

    def on_bar(self, ctx: "Context") -> list[OrderIntent]: ...


class Context:
    def __init__(self, bt: "Backtester", now: datetime, portfolio: PortfolioState, bot_capital: float):
        self._bt, self.now, self.portfolio, self.bot_capital = bt, now, portfolio, bot_capital

    pending_symbols: set = set()

    def has_pending(self, symbol: str) -> bool:
        return symbol in self.pending_symbols

    def history(self, symbol: str) -> list[Bar]:
        """Bars with available_at <= now (point-in-time)."""
        bars, avail = self._bt._bars[symbol], self._bt._avail[symbol]
        return bars[: bisect.bisect_right(avail, self.now)]

    def last_close(self, symbol: str) -> float | None:
        h = self.history(symbol)
        return h[-1].close if h else None

    def instrument(self, symbol: str) -> Instrument:
        return self._bt.instruments[symbol]

    def fx(self, ccy: str) -> float:
        return self._bt.fx.rate(ccy, self._bt.cfg.risk.base_currency)

    def position_value(self, symbol: str) -> float:
        p = self.portfolio.positions.get(symbol)
        return p.market_value_base if p else 0.0

    def intent(self, symbol: str, side: str, qty: float, strategy: str) -> OrderIntent | None:
        px = self.last_close(symbol)
        if px is None or qty <= 0:
            return None
        ins = self.instrument(symbol)
        return OrderIntent(symbol=symbol, side=side, qty=qty, order_type="market", reference_price=px,
                           quote_age_s=0.0, fx_rate_to_base=self.fx(ins.currency), currency=ins.currency,
                           sleeve=ins.sleeve, asset_class=ins.asset_class, broker=ins.broker, sector=ins.sector,
                           issuer=ins.issuer, source="strategy")


@dataclass
class BacktestResult:
    equity_curve: list[tuple[datetime, float]]
    trades: int
    fees: float
    realized_pnl: list[float]
    rejections: Counter
    approved: int
    halted: bool
    halt_reason: str | None
    benchmark_return: float | None = None
    decisions_log: list[tuple[datetime, str, bool]] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float | int | bool | str | None]:
        eq = [e for _, e in self.equity_curve]
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))] if len(eq) > 1 else []
        mu = sum(rets) / len(rets) if rets else 0.0
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0
        peak, mdd = -math.inf, 0.0
        for e in eq:
            peak = max(peak, e); mdd = max(mdd, (peak - e) / peak)
        years = max(len(rets) / 252, 1e-9)
        total = eq[-1] / eq[0] - 1 if eq else 0.0
        wins = sum(p for p in self.realized_pnl if p > 0); losses = -sum(p for p in self.realized_pnl if p < 0)
        return {"total_return_pct": total * 100, "cagr_pct": ((1 + total) ** (1 / years) - 1) * 100 if eq else 0.0,
                "sharpe": (mu / sd * math.sqrt(252)) if sd > 0 else 0.0, "max_drawdown_pct": mdd * 100,
                "trades": self.trades, "fees": self.fees, "profit_factor": (wins / losses) if losses > 0 else None,
                "approved_intents": self.approved, "rejected_intents": sum(self.rejections.values()),
                "halted": self.halted, "halt_reason": self.halt_reason,
                "benchmark_return_pct": None if self.benchmark_return is None else self.benchmark_return * 100}


class Backtester:
    def __init__(self, cfg: LoadedConfig, bars: dict[str, list[Bar]], instruments: dict[str, Instrument],
                 strategies: list[Strategy], total_account_equity: float = 100_000.0,
                 costs: CostModel | None = None, fx: FxRateProvider | None = None,
                 benchmark: list[str] | None = None):
        self.cfg = cfg
        self.instruments = instruments
        self.strategies = strategies
        self.fx = fx or StaticFxProvider(base=cfg.risk.base_currency)
        self._bars = {s: sorted(b, key=lambda x: x.available_at) for s, b in bars.items()}
        self._avail = {s: [x.available_at for x in b] for s, b in self._bars.items()}
        self.benchmark = benchmark or []
        bot_cap = cfg.risk.capital.allocation_cap_pct / 100 * total_account_equity
        self.non_bot_equity = total_account_equity - bot_cap
        self._t = 0.0
        clock = lambda: self._t  # noqa: E731
        self.audit = AuditLog()
        store = StateStore()
        self.ks = KillSwitch(self.audit, store=store)
        self.wd = Watchdog(cfg.risk.watchdog.heartbeat_interval_s, cfg.risk.watchdog.missed_beats_to_halt, self.ks, clock=clock)
        anomaly = AnomalyMonitor.from_policy(self.ks, getattr(cfg.risk, "anomaly_halts", {}) or {}, clock)
        self.engine = RiskEngine(cfg.risk, cfg.brokers, self.audit, self.ks, self.wd, clock=clock,
                                 fx=self.fx, anomaly=anomaly, store=store)
        self.broker = PaperBroker(total_account_equity_base=total_account_equity, bot_cash_base=bot_cap,
                                  costs=costs or CostModel())
        self.ks.add_on_engage(self.broker.cancel_all)

    def _set_fx_date(self, d) -> None:
        if hasattr(self.fx, "as_of"):
            self.fx.as_of = d  # type: ignore[attr-defined]

    def run(self) -> BacktestResult:
        events: dict[datetime, list[Bar]] = {}
        for bs in self._bars.values():
            for b in bs:
                events.setdefault(b.ts, []).append(b)
        pending: dict[str, list[tuple[OrderIntent, RiskDecision]]] = {}
        curve: list[tuple[datetime, float]] = []
        rejections: Counter = Counter()
        realized: list[float] = []
        approved = 0
        log: list[tuple[datetime, str, bool]] = []
        cur_day = None
        base = self.cfg.risk.base_currency
        for ts in sorted(events):
            self._t = ts.timestamp()
            day = ts.astimezone(TORONTO).date()
            self._set_fx_date(day)
            if day != cur_day:
                self.broker.roll_day(day)
                self.engine.roll_session(day.isoformat())
                cur_day = day
            self.wd.heartbeat()
            # 2. fills at next open
            for bar in events[ts]:
                for intent, dec in pending.pop(bar.symbol, []):
                    rate = self.fx.rate(intent.currency, base)
                    fill_int = intent.model_copy(update={"reference_price": bar.open, "fx_rate_to_base": rate})
                    pos = self.broker.positions.get(bar.symbol)
                    try:
                        if intent.side == "buy":
                            est = fill_int.qty * bar.open * rate * (1 + self.broker.costs.slippage_bps / 1e4)
                            if est + self.broker.costs.commission(est) > self.broker.bot_cash_base:
                                rejections["broker:insufficient_cash_at_open"] += 1
                                continue
                        avg = pos.avg_price if pos else 0.0
                        self.broker.submit(fill_int, dec)
                        f = self.broker.fills[-1]
                        if intent.side == "sell":
                            realized.append((f.price - avg) * f.qty * rate - f.commission)
                    except ValueError:
                        rejections["broker:reject"] += 1
            # 3. mark to market (+FX)
            for bar in events[ts]:
                p = self.broker.positions.get(bar.symbol)
                if p:
                    p.last_price = bar.close
                    p.fx_rate_to_base = self.fx.rate(p.currency, base)
            self.broker.total_account_equity_base = self.non_bot_equity + self.broker.bot_equity()
            self.engine.check_breaches(self.broker.snapshot())
            # 4/5. strategies -> risk gate
            snap = self.broker.snapshot()
            ctx = Context(self, ts, snap, self.engine.bot_capital(snap))
            ctx.pending_symbols = set(pending)
            for strat in self.strategies:
                for intent in strat.on_bar(ctx):
                    d = self.engine.evaluate(intent, self.broker.snapshot())
                    log.append((ts, intent.symbol, d.approved))
                    if d.approved:
                        approved += 1
                        pending.setdefault(intent.symbol, []).append((intent, d))
                    else:
                        for k, v in d.checks.items():
                            if not v:
                                rejections[k] += 1
            curve.append((ts, self.broker.bot_equity()))
        bench = None
        if self.benchmark:
            rs = [self._bars[s][-1].close / self._bars[s][0].open - 1 for s in self.benchmark if self._bars.get(s)]
            bench = sum(rs) / len(rs) if rs else None
        return BacktestResult(curve, len(self.broker.fills), sum(f.commission for f in self.broker.fills), realized,
                              rejections, approved, self.ks.engaged, self.ks.reason, bench, log)
