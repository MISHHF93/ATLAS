"""Decimal money + FX (CAD base). Rates are a static/fixture table; a real
source (Bank of Canada Valet API) is PROPOSED, not wired."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP

BASE = "CAD"
D = lambda x: Decimal(str(x))

def q(x, places="0.01") -> Decimal:
    return D(x).quantize(Decimal(places), rounding=ROUND_HALF_UP)

class FX:
    def __init__(self, rates: dict[str, str] | None = None):
        # units of CAD per 1 unit of currency
        from atlas.governance.integrity.fx import STATIC_RATES_TO_CAD
        self.rates = {k: D(v) for k, v in STATIC_RATES_TO_CAD.items()}
        if rates:
            self.rates.update({k: D(v) for k, v in rates.items()})

    def to_cad(self, amount, ccy: str) -> Decimal:
        if ccy not in self.rates:
            raise KeyError(f"no FX rate for {ccy}")
        return q(D(amount) * self.rates[ccy])

    def convert(self, amount, src: str, dst: str) -> Decimal:
        return q(D(amount) * self.rates[src] / self.rates[dst])
