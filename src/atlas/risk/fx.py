"""FX rate provider interface. Default: static offline table. Missing => fail closed."""
from __future__ import annotations

from typing import Protocol


class FxRateUnavailable(Exception):
    pass


class FxRateProvider(Protocol):
    def rate(self, ccy: str, base: str) -> float: ...


class StaticFxProvider:
    """Offline rates: units of `base` per 1 unit of ccy. Indicative only."""
    from atlas.governance.integrity.fx import STATIC_RATES_TO_CAD as _T
    DEFAULT = {k: float(v) for k, v in _T.items() if k in ("CAD", "USD", "EUR", "GBP", "JPY", "HKD", "AUD")}  # shared table
    del _T

    def __init__(self, rates_to_cad: dict[str, float] | None = None, base: str = "CAD"):
        self._rates = dict(self.DEFAULT if rates_to_cad is None else rates_to_cad)
        self._base = base

    def rate(self, ccy: str, base: str) -> float:
        if base != self._base:
            raise FxRateUnavailable(f"provider base {self._base} != {base}")
        if ccy == base:
            return 1.0
        r = self._rates.get(ccy)
        if r is None or r <= 0:
            raise FxRateUnavailable(f"no rate for {ccy}/{base}")
        return float(r)
