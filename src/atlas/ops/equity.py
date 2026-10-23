"""Equity history (bounded) kept in the StateStore for the dashboard chart and reports."""
from __future__ import annotations

from datetime import datetime

KEY = "equity_series"
MAX_POINTS = 5000


def record_equity(svc, now: datetime, min_gap_s: float = 60) -> None:
    s = svc.store.get(KEY, []) or []
    eq = svc.broker.bot_equity()
    if s and (now.timestamp() - datetime.fromisoformat(s[-1][0]).timestamp()) < min_gap_s:
        s[-1] = [s[-1][0], eq]
    else:
        s.append([now.isoformat(), eq])
    svc.store.set(KEY, s[-MAX_POINTS:])


def equity_series(svc) -> list[list]:
    return svc.store.get(KEY, []) or []
