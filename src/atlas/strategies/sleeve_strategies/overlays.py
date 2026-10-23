"""3. Exposure overlays (both can only SCALE DOWN; no leverage):

* Volatility-managed exposure (Moreira-Muir 2017): m = min(1, target_vol / realised_vol), smoothed and
  banded to limit turnover. Real-time gains are weaker than in-sample (Cederburg et al. 2020), hence
  challenger + DSR.
* Cash/risk trend switch (Hurst-Ooi-Pedersen): risk-on only if price > SMA(n) AND 12m return > T-bill;
  otherwise the multiplier is `off_mult` (default 0 = to cash).

The pipeline multiplies sizing by the CHAMPION overlay multipliers (clipped to [0, 1]); challengers
are logged in the decision trail's shadow outputs only."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class VolManaged:
    target_vol: float = 0.12
    lookback: int = 21
    band: float = 0.10          # only move the multiplier when it changes by > band
    floor: float = 0.0

    def multipliers(self, close: pd.Series) -> pd.Series:
        r = np.log(close).diff()
        rv = r.rolling(self.lookback, min_periods=self.lookback).std() * np.sqrt(252)
        raw = (self.target_vol / rv).clip(upper=1.0, lower=self.floor).shift(1)   # decided on t-1 info
        out, cur = [], 1.0
        for v in raw.fillna(1.0):
            if abs(v - cur) > self.band:
                cur = float(v)
            out.append(cur)
        return pd.Series(out, index=close.index)

    def multiplier(self, close: pd.Series) -> float:
        return float(min(1.0, max(0.0, self.multipliers(close).iloc[-1])))


@dataclass
class TrendSwitch:
    sma: int = 200
    mom_days: int = 252
    tbill_annual: float = 0.025
    off_mult: float = 0.0

    def multipliers(self, close: pd.Series) -> pd.Series:
        sma = close.rolling(self.sma, min_periods=self.sma).mean()
        ret = close / close.shift(self.mom_days) - 1
        above = (close > sma) | sma.isna()                       # warm-up: no signal -> leave sizing unchanged
        mom = (ret > self.tbill_annual * self.mom_days / 252) | ret.isna()
        on = (above & mom).shift(1).fillna(True)                 # decided on t-1 information
        return on.map(lambda x: 1.0 if x else self.off_mult).astype(float)

    def multiplier(self, close: pd.Series) -> float:
        return float(min(1.0, max(0.0, self.multipliers(close).iloc[-1])))


class OverlayModel:
    """Registry-loadable wrapper (kind strat_vol_managed / strat_trend_switch)."""

    @staticmethod
    def build(sm) -> object:
        cls = {"vol_managed": VolManaged, "trend_switch": TrendSwitch}[sm.name]
        return cls(**sm.params)


def overlay_returns(close: pd.Series, mult: pd.Series, cash_annual: float = 0.025, cost_bps: float = 2.0) -> pd.Series:
    """Daily returns of `mult` exposure to the asset + (1-mult) in cash, minus turnover cost."""
    r = close.pct_change().fillna(0)
    turn = mult.diff().abs().fillna(0)
    return mult * r + (1 - mult) * cash_annual / 252 - turn * cost_bps / 1e4
