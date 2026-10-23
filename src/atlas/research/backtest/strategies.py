"""Example strategies (illustrative, not investment advice)."""
from __future__ import annotations

from dataclasses import dataclass, field

from atlas.risk.models import OrderIntent
from atlas.research.backtest.engine import Context


@dataclass
class CoreRebalancer:
    """Holds core ETFs at fixed weights of bot capital. Rebalances on the first
    session of each ISO week, or whenever a holding drifts by > drift_band_pp."""
    weights: dict[str, float]  # fraction of bot capital, e.g. {"XIC": 0.095, ...}
    drift_band_pp: float = 5.0
    min_trade_value: float = 50.0
    name: str = "core_rebalancer"
    _last_week: tuple[int, int] | None = field(default=None, init=False)

    def on_bar(self, ctx: Context) -> list[OrderIntent]:
        cap = ctx.bot_capital
        if cap <= 0:
            return []
        week = ctx.now.isocalendar()[:2]
        drift = any(abs(ctx.position_value(s) / cap - w) * 100 > self.drift_band_pp for s, w in self.weights.items())
        if week == self._last_week and not drift:
            return []
        self._last_week = week
        sells, buys = [], []
        for sym, w in self.weights.items():
            px = ctx.last_close(sym)
            if px is None:
                continue
            fx = ctx.fx(ctx.instrument(sym).currency)
            delta = w * cap - ctx.position_value(sym)
            if abs(delta) < self.min_trade_value:
                continue
            qty = round(abs(delta) / (px * fx), 4)
            held = ctx.portfolio.positions[sym].qty if sym in ctx.portfolio.positions else 0.0
            if delta < 0:
                qty = min(qty, held)
            i = ctx.intent(sym, "buy" if delta > 0 else "sell", qty, self.name)
            if i:
                (buys if delta > 0 else sells).append(i)
        return sells + buys


@dataclass
class SmaCrossover:
    """Active sleeve: long when SMA(fast) > SMA(slow), flat otherwise."""
    symbols: list[str]
    fast: int = 20
    slow: int = 50
    weight: float = 0.09
    name: str = "sma_crossover"

    def on_bar(self, ctx: Context) -> list[OrderIntent]:
        out = []
        for sym in self.symbols:
            h = ctx.history(sym)
            if len(h) < self.slow:
                continue
            closes = [b.close for b in h]
            f, s = sum(closes[-self.fast:]) / self.fast, sum(closes[-self.slow:]) / self.slow
            held = ctx.portfolio.positions[sym].qty if sym in ctx.portfolio.positions else 0.0
            if ctx.has_pending(sym):
                continue
            if f > s and held == 0:
                fx = ctx.fx(ctx.instrument(sym).currency)
                qty = round(self.weight * ctx.bot_capital / (closes[-1] * fx), 4)
                i = ctx.intent(sym, "buy", qty, self.name)
            elif f < s and held > 0:
                i = ctx.intent(sym, "sell", held, self.name)
            else:
                i = None
            if i:
                out.append(i)
        return out


@dataclass
class SleeveRebalanceStrategy:
    """Backtester adapter for sleeves.rebalancer.SleeveRebalancer."""
    rebalancer: "object"
    name: str = "sleeve_rebalancer"
    plans: list = field(default_factory=list)

    def on_bar(self, ctx: Context) -> list[OrderIntent]:
        prices = {}
        for sym in self.rebalancer.symbol_sleeve():
            px = ctx.last_close(sym)
            if px is not None:
                prices[sym] = (px, ctx.fx(ctx.instrument(sym).currency))
        # positions not managed by the rebalancer still need prices for cap reductions
        for sym in ctx.portfolio.positions:
            if sym not in prices and ctx.last_close(sym) is not None:
                prices[sym] = (ctx.last_close(sym), ctx.fx(ctx.instrument(sym).currency))
        from atlas.ops.timez import TORONTO
        plan = self.rebalancer.plan(ctx.portfolio, prices, ctx.now.astimezone(TORONTO).date())
        if plan.triggered:
            self.plans.append((ctx.now, plan))
        out = []
        for t in plan.trades:
            if ctx.has_pending(t.symbol):  # don't double-order before the previous fill
                continue
            i = ctx.intent(t.symbol, t.side, t.qty, self.name)
            if i:
                out.append(i)
        return out
