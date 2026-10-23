"""4. Execution timing (overlay on WHEN to deploy, not a standalone strategy):

* Turn-of-month: returns concentrate in trading days -1..+3 around month end (Lakonishok-Smidt 1988;
  McConnell-Xu 2008, incl. Canada). New cash and scheduled rebalances are deployed inside the window
  unless waiting would exceed `max_wait_days`.
* Overnight/intraday asymmetry (Lou-Polk-Skouras 2019): prefer the closing auction (MOC/LOC) for
  buys/rebalances and the opening auction for urgent exits; avoid mid-day for non-urgent orders."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def tom_days(index: pd.DatetimeIndex, before: int = 1, after: int = 3) -> pd.Series:
    """True on trading days within [-before, +after] of each month boundary (day +1 = first trading day)."""
    idx = pd.DatetimeIndex(index)
    ym = idx.year * 12 + idx.month
    prev0 = idx[0] - pd.offsets.BDay(1) if len(idx) else None
    first = np.r_[bool(len(idx)) and prev0.month != idx[0].month, ym[1:] != ym[:-1]]
    pos = np.full(len(idx), 10 ** 6)
    starts = np.flatnonzero(first)
    for s in starts:
        for k in range(-before, after):
            j = s + k
            if 0 <= j < len(idx):
                pos[j] = 0
    return pd.Series(pos == 0, index=idx)




class DeploymentTimer:
    def __init__(self, before: int = 1, after: int = 3, max_wait_days: int = 15):
        self.before, self.after, self.max_wait = before, after, max_wait_days

    def deploy_now(self, trading_days: pd.DatetimeIndex, today: date, cash_waiting_since: date | None = None) -> tuple[bool, str]:
        w = tom_days(trading_days, self.before, self.after)
        t = pd.Timestamp(today)
        in_win = bool(w.get(t, False))
        if in_win:
            return True, "turn-of-month window"
        if cash_waiting_since and (today - cash_waiting_since).days >= self.max_wait:
            return True, f"waited {self.max_wait}+ days: deploy anyway"
        return False, "outside turn-of-month window: hold new cash in cash-equivalents"


def auction_policy(side: str, urgent: bool, venue_has_auctions: bool = True) -> dict:
    if not venue_has_auctions:
        return {"style": "limit_twap", "why": "venue without auctions (crypto/FX): passive limit, TWAP"}
    if urgent:
        return {"style": "opening_auction", "why": "urgent (risk-reducing): opening auction / marketable limit"}
    return {"style": "closing_auction", "why": "non-urgent: closing auction (MOC/LOC) captures close, avoids intraday reversal costs"}


def tom_backtest(close: pd.Series, cash_annual: float = 0.025, cost_bps: float = 2.0) -> pd.Series:
    """Daily excess return of holding only in TOM windows (cash otherwise) vs always invested. Used as a
    challenger diagnostic; in production the overlay only shifts deployment dates."""
    r = close.pct_change().fillna(0)
    w = tom_days(close.index).astype(float).shift(1).fillna(0)
    strat = w * r + (1 - w) * cash_annual / 252 - w.diff().abs().fillna(0) * cost_bps / 1e4
    return strat - r
