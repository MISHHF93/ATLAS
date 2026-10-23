"""1. Cash/T-bill yield management: idle bot cash above an operating buffer -> cash-equivalent ETFs.

Only instruments whose asset class is allowed in the target sleeve by the (signed) risk policy are
used; otherwise the plan is "blocked by policy" and nothing is proposed. Proposals are OrderIntents
that still go through the risk engine (and the approval queue at L1). Cash ETFs are treated as
cash-equivalents with a liquidity flag in the plan; they are sold first when cash is needed."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Indicative only (yields move with the BoC policy rate); owner-editable, never fetched.
DEFAULT_INSTRUMENTS = [
    {"symbol": "CASH.TO", "currency": "CAD", "asset_class": "index_etf", "yield_pct": 2.6, "kind": "HISA ETF", "liquidity": "T+1, ~1bp spread"},
    {"symbol": "PSA.TO", "currency": "CAD", "asset_class": "index_etf", "yield_pct": 2.5, "kind": "HISA ETF", "liquidity": "T+1, ~1bp spread"},
    {"symbol": "ZMMK.TO", "currency": "CAD", "asset_class": "index_etf", "yield_pct": 2.4, "kind": "money market ETF", "liquidity": "T+1"},
    {"symbol": "CBIL.TO", "currency": "CAD", "asset_class": "index_etf", "yield_pct": 2.4, "kind": "T-bill ETF", "liquidity": "T+1"},
]


@dataclass
class CashYieldPlanner:
    buffer_pct: float = 5.0            # % of bot capital kept as raw cash (fees, settlement, exits)
    min_trade_base: float = 500.0
    sleeve: str = "core"
    instruments: list = field(default_factory=lambda: list(DEFAULT_INSTRUMENTS))

    def allowed(self, policy) -> list[dict]:
        sl = policy.sleeves.get(self.sleeve) if hasattr(policy, "sleeves") else None
        allowed = set(getattr(sl, "instruments", []) or [])
        return [i for i in self.instruments if i["asset_class"] in allowed]

    def plan(self, state, bot_capital: float, policy, prices: dict[str, float], sleeve_headroom_base: float | None = None) -> dict:
        cash_eq = {i["symbol"] for i in self.instruments}
        held_cash_eq = sum(p.market_value_base for s, p in state.positions.items() if s in cash_eq)
        idle = state.settled_cash - self.buffer_pct / 100 * bot_capital
        out = {"idle_cash_base": round(idle, 2), "held_cash_equivalents_base": round(held_cash_eq, 2), "intents": [], "notes": []}
        ok = [i for i in self.allowed(policy) if i["symbol"] in prices and i["currency"] == "CAD"]
        if not ok:
            out["notes"].append(f"blocked by policy: no cash-equivalent asset class allowed in sleeve {self.sleeve!r}")
            return out
        best = max(ok, key=lambda i: i["yield_pct"])
        amt = idle if sleeve_headroom_base is None else min(idle, sleeve_headroom_base)
        if amt < self.min_trade_base:
            out["notes"].append(f"idle cash {idle:,.0f} below min trade {self.min_trade_base:,.0f} (or no sleeve headroom)")
            return out
        px = prices[best["symbol"]]
        qty = int(amt // px)
        if qty <= 0:
            return out
        from atlas.risk.models import OrderIntent
        out["intents"].append(OrderIntent(symbol=best["symbol"], side="buy", qty=qty, order_type="limit", limit_price=round(px * 1.0005, 4),
                                          reference_price=px, sleeve=self.sleeve, asset_class=best["asset_class"], broker="ibkr",
                                          source="strategy", currency="CAD", sector=None, quote_age_s=0.0))
        out["notes"].append(f"park {qty * px:,.0f} CAD in {best['symbol']} ({best['kind']}, ~{best['yield_pct']}%/yr indicative, "
                            f"{best['liquidity']}); cash-equivalent, liquidity-flagged; sold first when cash is needed")
        out["expected_annual_income_base"] = round(qty * px * best["yield_pct"] / 100, 2)
        return out

    def needs_cash(self, state, required_base: float) -> list[tuple[str, float]]:
        """Which cash-equivalents to sell (largest first) to raise `required_base` above settled cash."""
        short = required_base - state.settled_cash
        out = []
        for s, p in sorted(state.positions.items(), key=lambda kv: -kv[1].market_value_base):
            if short <= 0:
                break
            if s in {i["symbol"] for i in self.instruments}:
                q = min(p.qty, -(-short // p.last_price))
                out.append((s, q)); short -= q * p.last_price
        return out


def backtest(idle_frac: np.ndarray, rate_annual: np.ndarray, spread_bps: float = 1.0, turnover: float = 0.02) -> np.ndarray:
    """Daily excess return on bot capital from parking idle cash: idle_frac * r/252 - turnover * spread."""
    return idle_frac * rate_annual / 252 - turnover * idle_frac * spread_bps / 1e4
