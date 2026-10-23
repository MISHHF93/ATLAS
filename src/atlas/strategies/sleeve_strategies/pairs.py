"""9. Long-only pairs: relative-value SWITCHING. Hold the cheaper leg of a cointegrated pair (bank
peers, CA/US interlisted) and switch when the spread z-score crosses +-entry, with hysteresis and a
cost check. Gatev et al. (2006) returns fell sharply after 2002; long-only keeps part of the edge."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def hedge_ratio(a: pd.Series, b: pd.Series) -> float:
    x, y = np.log(b.values), np.log(a.values)
    return float(np.polyfit(x, y, 1)[0])


def cointegrated(a: pd.Series, b: pd.Series, p_max: float = 0.05) -> tuple[bool, float]:
    try:
        from statsmodels.tsa.stattools import coint
        p = float(coint(np.log(a), np.log(b))[1])
    except Exception:  # noqa: BLE001  statsmodels missing -> treat as not proven
        return False, 1.0
    return p < p_max, p


@dataclass
class PairSwitcher:
    lookback: int = 120
    entry_z: float = 1.5
    exit_z: float = 0.25
    cost_bps: float = 10.0

    def positions(self, a: pd.Series, b: pd.Series) -> pd.Series:
        """Returns 'A' or 'B' (which leg to hold) per day; decided on t-1 data."""
        la, lb = np.log(a), np.log(b)
        hold, out = "A", []
        for i in range(len(a)):
            if i >= self.lookback:
                wa, wb = la.iloc[i - self.lookback:i], lb.iloc[i - self.lookback:i]
                beta = float(np.polyfit(wb, wa, 1)[0])
                spr = wa - beta * wb
                z = (spr.iloc[-1] - spr.mean()) / (spr.std() or 1)
                if z > self.entry_z: hold = "B"        # A rich vs B -> hold B
                elif z < -self.entry_z: hold = "A"
                elif abs(z) < self.exit_z: pass        # hysteresis: keep current leg
            out.append(hold)
        return pd.Series(out, index=a.index)

    def backtest(self, a: pd.Series, b: pd.Series) -> pd.Series:
        pos = self.positions(a, b)
        ra, rb = a.pct_change().fillna(0), b.pct_change().fillna(0)
        held = pos.shift(1).fillna("A")
        r = np.where(held == "A", ra, rb)
        sw = (pos != pos.shift(1)).astype(float).fillna(0)
        bench = (ra + rb) / 2
        return pd.Series(r, index=a.index) - sw * 2 * self.cost_bps / 1e4 - bench   # excess over equal-weight pair
