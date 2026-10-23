"""10. Interlisted CA/US stocks: true arbitrage needs shorting (infeasible). Usable: VENUE SELECTION,
i.e. execute in whichever line (TSX/CAD or NYSE-NASDAQ/USD) has the lower all-in cost after
half-spread, commission and the FX conversion route from fx_cost. Lead-lag (US leads) is exposed as
a feature for TSX decisions."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from atlas.strategies.sleeve_strategies.fx_cost import FxCosts, plan as fx_plan


@dataclass(frozen=True)
class Line:
    symbol: str
    currency: str
    bid: float
    ask: float
    commission: float = 1.0     # in line currency


def all_in_cost_cad(line: Line, notional_cad: float, usd_on_hand: float, usdcad: float, account: str = "taxable",
                    fx: FxCosts = FxCosts()) -> dict:
    mid = (line.bid + line.ask) / 2
    half_spread_bps = (line.ask - line.bid) / 2 / mid * 1e4
    cost = notional_cad * half_spread_bps / 1e4 + line.commission * (usdcad if line.currency == "USD" else 1.0)
    fx_cost = 0.0
    if line.currency == "USD":
        need_usd_cad = max(0.0, notional_cad - usd_on_hand * usdcad)
        if need_usd_cad > 0:
            fx_cost = fx_plan(need_usd_cad, account, fx)["best"]["cost_cad"]
    return {"symbol": line.symbol, "half_spread_bps": round(half_spread_bps, 2), "cost_cad": round(cost + fx_cost, 2),
            "fx_cost_cad": round(fx_cost, 2)}


def choose_venue(ca: Line, us: Line, notional_cad: float, usd_on_hand: float = 0.0, usdcad: float = 1.37,
                 account: str = "taxable") -> dict:
    a = all_in_cost_cad(ca, notional_cad, usd_on_hand, usdcad, account)
    b = all_in_cost_cad(us, notional_cad, usd_on_hand, usdcad, account)
    best = a if a["cost_cad"] <= b["cost_cad"] else b
    return {"choose": best["symbol"], "options": [a, b], "saving_cad": round(abs(a["cost_cad"] - b["cost_cad"]), 2)}


def lead_lag_feature(us_close: pd.Series, usdcad: pd.Series) -> pd.Series:
    """US-line overnight return in CAD terms, aligned to the NEXT TSX session (feature, t-1 info only)."""
    us_cad = us_close * usdcad.reindex(us_close.index).ffill()
    return us_cad.pct_change().shift(1)
