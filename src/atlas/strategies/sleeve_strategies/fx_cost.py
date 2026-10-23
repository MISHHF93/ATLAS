"""2. FX conversion cost minimisation (CAD<->USD): IBKR IDEALPRO spot vs Norbert's gambit (DLR/DLR.U)
vs a retail bank spread. Saved cost, not alpha. The planner returns the cheapest route and the
exact steps; execution of each leg is a normal (risk-checked) order. Registered accounts often
can't hold USD cash at some brokers -> DLR route is preferred there."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FxCosts:
    retail_spread_pct: float = 2.0          # typical bank/robo CAD<->USD markup
    ibkr_bps: float = 0.2                   # IDEALPRO commission
    ibkr_min_usd: float = 2.0
    ibkr_spread_bps: float = 0.5            # half the interbank spread
    dlr_spread_bps: float = 2.0             # per leg, half-spread on DLR / DLR.U
    commission_per_leg_cad: float = 1.0
    journal_days: int = 2                   # broker journals DLR -> DLR.U (settlement wait)
    cash_yield_pct: float = 2.5             # opportunity cost of waiting
    usdcad: float = 1.37


def route_costs(amount_cad: float, account: str = "taxable", c: FxCosts = FxCosts()) -> list[dict]:
    a = float(amount_cad)
    ib = max(c.ibkr_min_usd * c.usdcad, a * c.ibkr_bps / 1e4) + a * c.ibkr_spread_bps / 1e4
    ng = 2 * c.commission_per_leg_cad + 2 * a * c.dlr_spread_bps / 1e4 + a * c.cash_yield_pct / 100 * c.journal_days / 365
    rt = a * c.retail_spread_pct / 100
    routes = [
        {"route": "ibkr_spot", "cost_cad": ib, "steps": ["IBKR: convert CAD->USD on IDEALPRO (limit near mid)"],
         "note": "simplest; IBKR holds USD cash" + ("; check plan allows USD cash" if account != "taxable" else "")},
        {"route": "norberts_gambit", "cost_cad": ng,
         "steps": ["buy DLR.TO (CAD) with limit at ask", f"request journal DLR -> DLR.U (~{c.journal_days} business days)",
                   "sell DLR.U.TO (USD) with limit at bid"],
         "note": "two commissions + two half-spreads + settlement wait; preferred in registered accounts"},
        {"route": "retail_conversion", "cost_cad": rt, "steps": ["broker/bank conversion"], "note": "avoid"},
    ]
    for r in routes:
        r["cost_cad"] = round(r["cost_cad"], 2); r["cost_bps"] = round(r["cost_cad"] / a * 1e4, 2) if a else 0.0
    return sorted(routes, key=lambda r: r["cost_cad"])


def plan(amount_cad: float, account: str = "taxable", c: FxCosts = FxCosts()) -> dict:
    rs = route_costs(amount_cad, account, c)
    best = rs[0]
    if account in ("rrsp", "tfsa", "fhsa", "resp") and best["route"] == "ibkr_spot":
        ng = next(r for r in rs if r["route"] == "norberts_gambit")
        best = ng if ng["cost_cad"] <= best["cost_cad"] * 1.5 else best   # registered: prefer DLR unless much dearer
    return {"amount_cad": amount_cad, "account": account, "best": best, "routes": rs,
            "saving_vs_retail_cad": round(next(r for r in rs if r["route"] == "retail_conversion")["cost_cad"] - best["cost_cad"], 2)}


def savings_series(conversions_cad, c: FxCosts = FxCosts(), capital: float = 100_000.0):
    """Per-period saving (as a return on capital) of the best route vs retail, for the trial log."""
    import numpy as np
    return np.array([(plan(a, c=c)["saving_vs_retail_cad"]) / capital for a in conversions_cad])
