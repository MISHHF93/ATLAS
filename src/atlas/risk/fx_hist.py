from __future__ import annotations

import bisect
from datetime import date

from atlas.risk.fx import FxRateUnavailable


class HistoricalFxProvider:
    """Point-in-time FX: rate = last observation on/before `as_of`. Missing => fail closed."""

    def __init__(self, series: dict[str, list[tuple[date, float]]], base: str = "CAD"):
        self.base = base
        self.series = {k: sorted(v) for k, v in series.items()}
        self.as_of: date | None = None

    def rate(self, ccy: str, base: str) -> float:
        if base != self.base:
            raise FxRateUnavailable("base mismatch")
        if ccy == base:
            return 1.0
        s = self.series.get(ccy)
        if not s or self.as_of is None:
            raise FxRateUnavailable(f"no {ccy} series / as_of unset")
        i = bisect.bisect_right([d for d, _ in s], self.as_of) - 1
        if i < 0:
            raise FxRateUnavailable(f"no {ccy} rate on/before {self.as_of}")
        return s[i][1]
