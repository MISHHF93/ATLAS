"""Higher-timeframe (HTF) bias from TRUE daily bars (feed 1d) and causally aggregated 4h bars.

Daily, at time t, using only daily bars whose availability time <= t (availability = bar open + 86400 s, a
conservative rule because provider daily bars are stamped at the session date):
  sma50, sma200 of daily closes; slope50 = sma50_now - sma50 five completed days earlier;
  structure from confirmed daily fractal swings (k=2): last two swing highs and lows -> HH+HL = up, LH+LL = down, else mixed.
  trend = bullish if close > sma50 > sma200 and slope50 > 0; bearish if close < sma50 < sma200 and slope50 < 0; else neutral.
  bias = conflicting if trend and structure disagree (bullish vs down, bearish vs up) or the 4h trend opposes it;
  insufficient if fewer than 200 completed daily bars.
4h: UTC 4h buckets built from completed base bars; trend4h = sign(close - sma50_4h) when slope of sma50_4h agrees, else 0.
States: bullish | bearish | neutral | conflicting | insufficient.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Any, Sequence

import numpy as np

BIAS_STATES = ("bullish", "bearish", "neutral", "conflicting", "insufficient")


class DailyBias:
    def __init__(self, daily: Sequence[tuple[int, float, float, float]], k: int = 2):
        """daily: (bar_open_ts, high, low, close) of completed provider daily bars, ascending."""
        rows = sorted(daily)
        self.avail = [int(r[0]) + 86400 for r in rows]
        c = np.array([r[3] for r in rows], float)
        h = np.array([r[1] for r in rows], float)
        lo = np.array([r[2] for r in rows], float)
        self.c = c
        n = len(c)
        cs = np.concatenate([[0.0], np.cumsum(c)])
        self.sma50 = np.full(n, np.nan)
        self.sma200 = np.full(n, np.nan)
        for w, arr in ((50, self.sma50), (200, self.sma200)):
            if n >= w:
                arr[w - 1:] = (cs[w:] - cs[:-w]) / w
        # swing confirmations: (confirm_index, kind, price)
        self.sw: list[tuple[int, str, float]] = []
        for i in range(k, n - k):
            if h[i] > h[i - k:i].max() and h[i] >= h[i + 1:i + k + 1].max():
                self.sw.append((i + k, "H", h[i]))
            if lo[i] < lo[i - k:i].min() and lo[i] <= lo[i + 1:i + k + 1].min():
                self.sw.append((i + k, "L", lo[i]))

    def at(self, t: int, trend4h: int = 0) -> dict[str, Any]:
        i = bisect_right(self.avail, t) - 1
        if i < 204 or np.isnan(self.sma200[i]):
            return {"bias": "insufficient", "daily_bars": max(i + 1, 0)}
        slope = self.sma50[i] - self.sma50[i - 5]
        c, a, b = self.c[i], self.sma50[i], self.sma200[i]
        trend = "bullish" if (c > a > b and slope > 0) else "bearish" if (c < a < b and slope < 0) else "neutral"
        hs = [p for j, kd, p in self.sw if j <= i and kd == "H"][-2:]
        ls = [p for j, kd, p in self.sw if j <= i and kd == "L"][-2:]
        st = "mixed"
        if len(hs) == 2 and len(ls) == 2:
            st = "up" if hs[1] > hs[0] and ls[1] > ls[0] else "down" if hs[1] < hs[0] and ls[1] < ls[0] else "mixed"
        bias = trend
        if (trend == "bullish" and (st == "down" or trend4h < 0)) or (trend == "bearish" and (st == "up" or trend4h > 0)):
            bias = "conflicting"
        return {"bias": bias, "trend_daily": trend, "structure_daily": st, "trend_4h": trend4h, "close": float(c),
                "sma50": float(a), "sma200": float(b), "slope50": float(slope), "daily_bars": i + 1,
                "as_of_daily_available": self.avail[i]}


class FourHour:
    """Causal 4h aggregation (UTC buckets) of completed base bars; trend from sma50 of completed 4h closes."""

    def __init__(self) -> None:
        self.closes: list[float] = []
        self._b: int | None = None
        self._c = 0.0

    def update(self, start: int, close: float) -> None:
        b = start // 14400
        if self._b is not None and b != self._b:
            self.closes.append(self._c)
        self._b, self._c = b, close

    def trend(self) -> int:
        if len(self.closes) < 56:
            return 0
        x = self.closes
        s_now, s_prev = sum(x[-50:]) / 50, sum(x[-56:-6]) / 50
        if x[-1] > s_now and s_now > s_prev:
            return 1
        if x[-1] < s_now and s_now < s_prev:
            return -1
        return 0
