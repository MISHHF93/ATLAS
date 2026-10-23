"""Cost-aware 60/30/10 sleeve rebalancer with drift bands and 20% cap enforcement.

Triggers (any): scheduled (first session of the week on/after the policy weekday),
sleeve drift > drift_band_pp, any managed holding drifting > drift_band_pp, or bot
exposure above the 20% allocation cap.
Cost-awareness: each trade's estimated cost (slippage + commission) in bps of trade
value must be <= rebalance.max_cost_bps, UNLESS the holding is far off target
(holding outside its drift band, or not yet held = initial deployment) or the trade is a cap-reduction sell.
Trades below min_trade_value_base are skipped. Sells are emitted before buys; buys
are scaled to fit settled cash. Targets are clipped to the per-position limits so
the RiskEngine is not asked for something it will reject.
The RiskEngine still gates every resulting intent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from atlas.control.policy.schemas import RiskPolicy
from atlas.risk.models import PortfolioState

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
POSITION_BUFFER = 0.98  # stay 2% inside per-position limits


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: str
    qty: float
    value_base: float
    est_cost_bps: float
    reason: str


@dataclass
class RebalancePlan:
    triggered: list[str]
    trades: list[Trade] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    sleeve_drift_pp: dict[str, float] = field(default_factory=dict)
    targets_base: dict[str, float] = field(default_factory=dict)


class SleeveRebalancer:
    def __init__(self, policy: RiskPolicy, holdings: dict[str, dict[str, float]],
                 slippage_bps: float = 5.0, commission_per_order: float = 1.0):
        """holdings: sleeve -> {symbol: weight within sleeve}. Sleeves without an entry
        (e.g. 'active', strategy-driven) are measured but not traded by the rebalancer."""
        for sl, w in holdings.items():
            if sl not in policy.sleeves:
                raise ValueError(f"unknown sleeve {sl!r}")
            if policy.sleeves[sl].locked:
                raise ValueError(f"sleeve {sl!r} is locked")
            if sum(w.values()) > 1 + 1e-9 or any(v < 0 for v in w.values()):
                raise ValueError(f"weights in sleeve {sl!r} must be >= 0 and sum to <= 1")
        self.p = policy
        self.holdings = holdings
        self.slippage_bps = slippage_bps
        self.commission = commission_per_order
        rb = policy.rebalance
        self.band = rb.drift_band_pp
        self.max_cost_bps = rb.max_cost_bps
        self.min_trade = rb.min_trade_value_base
        self.weekday = WEEKDAYS.get(rb.schedule_time_et.split()[0], 0)
        self._last_scheduled: tuple[int, int] | None = None

    def symbol_sleeve(self) -> dict[str, str]:
        return {s: sl for sl, w in self.holdings.items() for s in w}

    def est_cost_bps(self, value: float) -> float:
        return self.slippage_bps + (self.commission / value * 1e4 if value > 0 else float("inf"))

    def _scheduled(self, today: date) -> bool:
        wk = today.isocalendar()[:2]
        if wk != self._last_scheduled and today.weekday() >= self.weekday:
            self._last_scheduled = wk
            return True
        return False

    def plan(self, state: PortfolioState, prices: dict[str, tuple[float, float]], today: date,
             force: bool = False) -> RebalancePlan:
        """prices: symbol -> (price in instrument ccy, fx_rate_to_base)."""
        p = self.p
        cap_abs = p.capital.allocation_cap_pct / 100 * state.total_account_equity_base
        bot_cap = max(0.0, min(state.bot_equity, cap_abs))
        gross = state.gross_exposure_base
        triggered: list[str] = []
        if force:
            triggered.append("forced")
        if self._scheduled(today):
            triggered.append("schedule")
        over_cap = gross > cap_abs * (1 + 1e-6)
        if over_cap:
            triggered.append("cap_breach")
        drift = {}
        for sl, cfg in p.sleeves.items():
            if cfg.locked:
                continue
            actual = state.sleeve_exposure(sl) / bot_cap * 100 if bot_cap else 0.0
            drift[sl] = actual - cfg.target_pct
            if sl in self.holdings and abs(drift[sl]) > self.band:
                triggered.append(f"drift:{sl}")
        # per-holding targets (clipped to position limits)
        pl = p.position_limits
        max_pos = min(pl.max_position_pct_bot_capital / 100 * bot_cap, pl.max_position_notional_base) * POSITION_BUFFER
        targets: dict[str, float] = {}
        for sl, w in self.holdings.items():
            for sym, wt in w.items():
                targets[sym] = min(p.sleeves[sl].target_pct / 100 * wt * bot_cap, max_pos)
        if over_cap:  # scale everything (incl. unmanaged) so total exposure fits under the cap
            scale = cap_abs * POSITION_BUFFER / gross
            for sym, pos in state.positions.items():
                targets[sym] = min(targets.get(sym, pos.market_value_base), pos.market_value_base * scale)
        for sym, t in targets.items():
            cur = state.positions[sym].market_value_base if sym in state.positions else 0.0
            if bot_cap and abs(cur - t) / bot_cap * 100 > self.band and f"drift:{sym}" not in triggered:
                triggered.append(f"drift:{sym}")
        plan = RebalancePlan(triggered, sleeve_drift_pp=drift, targets_base=targets)
        if not triggered:
            return plan
        sells, buys = [], []
        for sym, t in targets.items():
            if sym not in prices:
                plan.skipped.append((sym, "no price")); continue
            px, fx = prices[sym]
            pos = state.positions.get(sym)
            cur = pos.market_value_base if pos else 0.0
            delta = t - cur
            val = abs(delta)
            cap_sell = over_cap and delta < 0
            if val < self.min_trade and not (cap_sell and val > 0):
                if val > 0:
                    plan.skipped.append((sym, f"below min trade {self.min_trade}"))
                continue
            cost = self.est_cost_bps(val)
            out_of_band = cur == 0 or (bot_cap > 0 and val / bot_cap * 100 > self.band)
            if cost > self.max_cost_bps and not (out_of_band or cap_sell):
                plan.skipped.append((sym, f"cost {cost:.1f}bps > {self.max_cost_bps}bps"))
                continue
            qty = val / (px * fx)
            if delta < 0:
                qty = min(qty, pos.qty if pos else 0.0)
                if qty <= 0:
                    continue
                sells.append(Trade(sym, "sell", round(qty, 6), val, cost, "cap" if cap_sell else "rebalance"))
            else:
                buys.append(Trade(sym, "buy", qty, val, cost, "rebalance"))
        if not over_cap:
            budget = min(state.settled_cash, state.bot_cash_base) * POSITION_BUFFER
            need = sum(b.value_base * (1 + b.est_cost_bps / 1e4) for b in buys)
            if need > budget and need > 0:
                f = budget / need
                buys = [Trade(b.symbol, "buy", b.qty * f, b.value_base * f, b.est_cost_bps, "rebalance(scaled to cash)")
                        for b in buys if b.value_base * f >= self.min_trade]
        else:
            buys = []  # never add exposure while over the cap
        plan.trades = sells + [Trade(b.symbol, b.side, round(b.qty, 6), b.value_base, b.est_cost_bps, b.reason) for b in buys if round(b.qty, 6) > 0]
        return plan
