"""7. S&P/TSX Composite addition predictor (quarterly reviews). Effect is smaller than historically
and crowded (Greenwood-Sammon 2022 for the US). Rule-based eligibility proxy + logistic score:
float-adjusted market cap rank vs the current smallest constituents, liquidity (float turnover),
price >= $1, listed >= 12 months, Canadian-domiciled. Long-only use: buy predicted additions BEFORE
the announcement and exit into the effective date. Public methodology; data from local fixtures."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class IndexAdditionPredictor:
    min_price: float = 1.0
    min_listing_months: int = 12
    min_float_turnover: float = 0.5      # annual traded value / float cap
    cap_buffer: float = 1.10             # must exceed smallest constituent cap by this factor
    k: float = 6.0                       # logistic steepness

    def eligible(self, s: dict) -> tuple[bool, list[str]]:
        why = []
        if s["price"] < self.min_price: why.append("price < $1")
        if s["listing_months"] < self.min_listing_months: why.append("listed < 12 months")
        if s["float_turnover"] < self.min_float_turnover: why.append("low float turnover")
        if not s.get("canadian", True): why.append("not Canadian-domiciled")
        if s.get("in_index"): why.append("already a constituent")
        return (not why), why

    def probability(self, s: dict, smallest_constituent_cap: float) -> float:
        ok, _ = self.eligible(s)
        if not ok:
            return 0.0
        x = math.log(s["float_cap"] / (smallest_constituent_cap * self.cap_buffer)) + 0.3 * math.log(max(s["float_turnover"], 1e-6) / self.min_float_turnover)
        return 1 / (1 + math.exp(-self.k * x))

    def rank(self, universe: list[dict], smallest_constituent_cap: float, top: int = 5) -> list[dict]:
        rows = [{"symbol": s["symbol"], "p_add": round(self.probability(s, smallest_constituent_cap), 3),
                 "ineligible": self.eligible(s)[1]} for s in universe]
        return sorted(rows, key=lambda r: -r["p_add"])[:top]
