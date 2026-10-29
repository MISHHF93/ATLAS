"""Snapshot -> read-only features and context for the ML (never an order, never a limit change).

The ML may READ these. It may not widen anything: sizing stays with the deterministic control plane and ``risk_policy.yaml``."""
from __future__ import annotations

from math import floor
from typing import Any

from atlas.broker_state.snapshot import AccountSnapshot


def sizing_feasibility(snap: AccountSnapshot, risk_fraction: float = 0.005, stop_distance_frac: float = 0.02) -> dict[str, Any]:
    """Can a risk-policy-sized trade clear the broker's minimum order?  ideal notional = equity * risk / stop distance.
    If it cannot, the only trade that fits risks MORE than the policy allows, so the correct action is to wait (not to oversize)."""
    eq, mn = snap.balances.equity, snap.rules.min_order_notional
    out: dict[str, Any] = {"risk_fraction": risk_fraction, "stop_distance_frac": stop_distance_frac, "min_order_notional": mn,
                           "ideal_notional": None, "feasible": None, "forced_risk_fraction": None, "min_equity_for_policy": None}
    if not eq or eq <= 0 or risk_fraction <= 0 or stop_distance_frac <= 0:
        return out
    ideal = eq * risk_fraction / stop_distance_frac
    out["ideal_notional"] = round(ideal, 4)
    if mn is None:
        return out
    out["feasible"] = ideal >= mn and ideal <= eq * max(snap.balances.leverage_max or 1.0, 1.0)
    out["forced_risk_fraction"] = round(mn * stop_distance_frac / eq, 6)
    out["min_equity_for_policy"] = round(mn * stop_distance_frac / risk_fraction, 2)
    return out


def round_trip_fee_bps(snap: AccountSnapshot, notional: float) -> float | None:
    """Fixed per-order fees as basis points of a round trip (two orders) at this notional. Spread/slippage is added when known."""
    if notional <= 0:
        return None
    f = snap.fees
    per_order = (f.commission_per_order or 0.0) + (f.commission_per_unit or 0.0) * 0  # per-unit fees need a price; left to the caller
    if f.commission_min is not None:
        per_order = max(per_order, f.commission_min)
    bps = 2 * per_order / notional * 1e4
    if f.spread_bps_assumed is not None:
        bps += f.spread_bps_assumed * 2
    return round(bps, 2)


def snapshot_features(snap: AccountSnapshot, risk_fraction: float = 0.005, stop_distance_frac: float = 0.02) -> dict[str, Any]:
    """Flat numeric/boolean features; unknown stays None (the model must handle missing, not 0)."""
    b, eq = snap.balances, snap.balances.equity
    gross = sum(abs(p.market_value) for p in snap.positions if p.market_value is not None)
    top = max((abs(p.market_value) for p in snap.positions if p.market_value is not None), default=0.0)
    f: dict[str, Any] = {
        "acct_usable": snap.usable, "acct_equity": eq, "acct_cash_frac": (b.cash / eq) if eq and b.cash is not None else None,
        "acct_gross_exposure_frac": (gross / eq) if eq else None, "acct_top_position_frac": (top / eq) if eq else None,
        "acct_buying_power_ratio": (b.buying_power / eq) if eq and b.buying_power is not None else None,
        "acct_margin_utilization": (b.margin_used / eq) if eq and b.margin_used is not None else None,
        "acct_positions": len(snap.positions), "acct_open_orders": len(snap.open_orders),
        "acct_fractional": snap.rules.fractional, "acct_min_order_notional": snap.rules.min_order_notional,
        "acct_min_order_pct_equity": (snap.rules.min_order_notional / eq) if eq and snap.rules.min_order_notional else None,
        "acct_max_distinct_min_lots": floor(eq / snap.rules.min_order_notional) if eq and snap.rules.min_order_notional else None,
        "acct_pdt_constrained": snap.rules.pdt_applies, "acct_trading_blocked": snap.rules.trading_blocked,
        "acct_market_open": snap.market.is_open, "acct_leverage_max": b.leverage_max,
    }
    sf = sizing_feasibility(snap, risk_fraction, stop_distance_frac)
    f.update({"acct_policy_trade_feasible": sf["feasible"], "acct_forced_risk_fraction": sf["forced_risk_fraction"],
              "acct_min_equity_for_policy": sf["min_equity_for_policy"]})
    return f


def context_text(snap: AccountSnapshot) -> str:
    """One compact line for an LLM/agent context. Facts only; no instruction."""
    if not snap.usable:
        return f"[account:{snap.broker}/{snap.environment}] {snap.status}: {snap.reason}"
    b, r = snap.balances, snap.rules
    parts = [f"equity {b.equity:.2f} {snap.currency or ''}".strip(), f"cash {b.cash:.2f}" if b.cash is not None else None,
             f"buying power {b.buying_power:.2f}" if b.buying_power is not None else None, f"{len(snap.positions)} positions, {len(snap.open_orders)} open orders",
             f"min order {r.min_order_notional:g}" if r.min_order_notional else None, f"fractional={r.fractional}" if r.fractional is not None else None,
             {True: "market open", False: "market closed"}.get(snap.market.is_open)]
    return f"[account:{snap.broker}/{snap.environment}] " + "; ".join(p for p in parts if p) + ". Read-only; execution_permission=none."
