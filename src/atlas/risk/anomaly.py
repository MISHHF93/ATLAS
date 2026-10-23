"""Anomaly halts per risk_policy.anomaly_halts. Each trip engages the kill switch."""
from __future__ import annotations

import math
from collections import deque
from typing import Callable

from atlas.risk.killswitch import KillSwitch


class AnomalyMonitor:
    def __init__(self, ks: KillSwitch, stale_quote_seconds: float = 10, pnl_jump_sigma: float = 4,
                 fill_deviation_bps: float = 50, reject_count: int = 3, reject_window_s: float = 300,
                 clock: Callable[[], float] | None = None, min_pnl_obs: int = 20):
        self.ks = ks
        self.stale_quote_seconds = stale_quote_seconds
        self.pnl_jump_sigma = pnl_jump_sigma
        self.fill_deviation_bps = fill_deviation_bps
        self.reject_count = reject_count
        self.reject_window_s = reject_window_s
        self.clock = clock
        self.min_pnl_obs = min_pnl_obs
        self._rejects: deque[float] = deque()
        self._pnl: deque[float] = deque(maxlen=500)

    @classmethod
    def from_policy(cls, ks: KillSwitch, anomaly: dict, clock=None) -> "AnomalyMonitor":
        rs = anomaly.get("reject_spike", {}) or {}
        return cls(ks, anomaly.get("stale_quote_seconds", 10), anomaly.get("pnl_jump_sigma", 4),
                   anomaly.get("fill_deviation_bps", 50), rs.get("count", 3), rs.get("window_minutes", 5) * 60, clock)

    def quote_fresh(self, age_s: float | None) -> bool:
        return age_s is not None and 0 <= age_s <= self.stale_quote_seconds

    def on_fill(self, fill_price: float, reference_price: float) -> bool:
        dev = abs(fill_price - reference_price) / reference_price * 1e4
        if dev > self.fill_deviation_bps:
            self.ks.engage(f"anomaly: fill deviation {dev:.1f}bps > {self.fill_deviation_bps}", "anomaly")
            return False
        return True

    def on_broker_reject(self, now: float) -> bool:
        self._rejects.append(now)
        while self._rejects and now - self._rejects[0] > self.reject_window_s:
            self._rejects.popleft()
        if len(self._rejects) >= self.reject_count:
            self.ks.engage(f"anomaly: {len(self._rejects)} broker rejects in {self.reject_window_s}s", "anomaly")
            return False
        return True

    def on_pnl(self, pnl_change: float) -> bool:
        hist = list(self._pnl)
        self._pnl.append(pnl_change)
        if len(hist) < self.min_pnl_obs:
            return True
        mu = sum(hist) / len(hist)
        sd = math.sqrt(sum((x - mu) ** 2 for x in hist) / (len(hist) - 1))
        if sd > 0 and abs(pnl_change - mu) / sd > self.pnl_jump_sigma:
            self.ks.engage(f"anomaly: P&L jump {abs(pnl_change - mu) / sd:.1f} sigma", "anomaly")
            return False
        return True
