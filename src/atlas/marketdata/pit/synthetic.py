"""Deterministic synthetic daily bars (GBM) on a venue's real sessions."""
from __future__ import annotations

import math
import random
from datetime import date

from atlas.marketdata.pit.calendars import session_close, sessions
from atlas.marketdata.pit.models import Bar


def gbm_bars(symbol: str, venue: str, start: date, end: date, s0: float = 100.0, mu: float = 0.07,
             sigma: float = 0.18, seed: int = 0) -> list[Bar]:
    rng = random.Random(f"{seed}-{symbol}")
    dt = 1 / 252
    px = s0
    out = []
    for d in sessions(venue, start, end):
        o = px * math.exp(rng.gauss(0, sigma * math.sqrt(dt) * 0.3))
        c = o * math.exp((mu - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * rng.gauss(0, 1))
        hi, lo = max(o, c) * (1 + abs(rng.gauss(0, 0.003))), min(o, c) * (1 - abs(rng.gauss(0, 0.003)))
        out.append(Bar(symbol=symbol, ts=session_close(venue, d), open=o, high=hi, low=lo, close=c, volume=1e6))
        px = c
    return out
