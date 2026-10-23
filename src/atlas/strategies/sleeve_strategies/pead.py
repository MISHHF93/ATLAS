"""6. Post-earnings-announcement drift + revisions. NEEDS PAID point-in-time data (I/B/E/S-class);
free consensus is unreliable. This module defines the provider interface, a fixture provider for
tests, SUE / revision signals and an event-study backtest. No provider is enabled by default."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    announce: date            # date the result became public (PIT key)
    actual_eps: float
    consensus_eps: float      # consensus as known BEFORE the announcement
    eps_std: float            # dispersion / historical surprise std
    revision_30d: float = 0.0 # % change in consensus over the prior 30 days (as known at announce)
    revenue_surprise: float = 0.0


class EarningsProvider(Protocol):
    def events(self, start: date, end: date) -> list[EarningsEvent]: ...


class FixtureEarningsProvider:
    """CSV: symbol,announce,actual_eps,consensus_eps,eps_std[,revision_30d,revenue_surprise]."""

    def __init__(self, path):
        self.rows = []
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                self.rows.append(EarningsEvent(r["symbol"], date.fromisoformat(r["announce"]), float(r["actual_eps"]),
                                               float(r["consensus_eps"]), float(r["eps_std"]),
                                               float(r.get("revision_30d") or 0), float(r.get("revenue_surprise") or 0)))

    def events(self, start, end):
        return [e for e in self.rows if start <= e.announce <= end]


class PaidProviderPlaceholder:
    """Placeholder for a licensed feed. Disabled: raises so nothing silently trades on missing data."""

    def events(self, start, end):
        raise RuntimeError("PEAD needs a licensed point-in-time earnings feed (not configured)")


def sue(e: EarningsEvent) -> float:
    return (e.actual_eps - e.consensus_eps) / e.eps_std if e.eps_std > 0 else 0.0


@dataclass
class PeadSignal:
    sue_min: float = 1.5
    hold_days: int = 60
    revision_weight: float = 0.5
    revenue_weight: float = 0.5

    def score(self, e: EarningsEvent) -> float:
        return sue(e) + self.revision_weight * np.sign(e.revision_30d) + self.revenue_weight * np.sign(e.revenue_surprise)

    def longs(self, events: list[EarningsEvent], as_of: date, trading_days: pd.DatetimeIndex) -> list[str]:
        """Names with a qualifying surprise announced strictly BEFORE as_of (enter next day) and still in hold."""
        out = []
        t = pd.Timestamp(as_of)
        for e in events:
            a = pd.Timestamp(e.announce)
            if a < t and sue(e) >= self.sue_min:
                held = ((trading_days > a) & (trading_days <= t)).sum()
                if 1 <= held <= self.hold_days:
                    out.append(e.symbol)
        return sorted(set(out))


def event_backtest(close: pd.DataFrame, events: list[EarningsEvent], sig: PeadSignal, cost_bps: float = 10.0) -> pd.Series:
    """Equal-weight daily returns of the PEAD long book (cash when empty), costs on entry/exit."""
    r = close.pct_change().fillna(0)
    w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for d in close.index:
        names = [s for s in sig.longs(events, d.date(), close.index) if s in close.columns]
        if names:
            w.loc[d, names] = 1 / len(names)
    wl = w.shift(1).fillna(0)
    return (wl * r).sum(1) - w.diff().abs().sum(1).fillna(0) * cost_bps / 1e4
