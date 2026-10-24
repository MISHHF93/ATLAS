"""Keyless FRED public CSV (fredgraph.csv) with conservative point-in-time release lags (section 22).

The keyed ALFRED API (``fred.py``) gives true vintages; without a key we only get the *latest* vintage, so this
adapter (a) prefers series that are never or rarely revised and (b) stamps every value with a conservative
``realtime_start`` = the first UTC date on which it is certainly public. A feature may use a value only from
``realtime_start`` 00:00 UTC onward (see ``atlas.ml.context``). Lags (documented assumptions, not measured):

  DGS10 / DGS2 (H.15, published next business day ~16:15 ET)  -> next business day + 1 calendar day
  VIXCLS (Cboe close, same evening)                            -> next business day + 1 calendar day
  DTWEXBGS (H.10, published weekly on Monday for the prior week) -> date + 10 calendar days
  CPIAUCNS (CPI-U NSA, not seasonally revised; released ~mid M+1) -> first day of month M+2

Source: https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES> (public, no key). Terms:
https://fred.stlouisfed.org/docs/api/terms_of_use.html . Values are FRED's; nothing is synthesised.
"""
from __future__ import annotations

import csv
import io
import time
import urllib.request
from datetime import date, timedelta
from typing import Callable

from ..core import FeedObservation

PROVIDER = "fred_graph_lagged"
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def _next_bday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _lag_daily(d: date) -> date:
    return _next_bday(d) + timedelta(days=1)


def _lag_weekly_h10(d: date) -> date:
    return d + timedelta(days=10)


def _lag_monthly(d: date) -> date:
    y, m = d.year + (d.month + 1) // 12, (d.month + 1) % 12 + 1
    return date(y, m, 1)


SERIES: dict[str, tuple[str, Callable[[date], date]]] = {
    "DGS10": ("10y Treasury constant maturity (%)", _lag_daily),
    "DGS2": ("2y Treasury constant maturity (%)", _lag_daily),
    "VIXCLS": ("Cboe VIX close", _lag_daily),
    "DTWEXBGS": ("Broad trade-weighted USD index (DXY proxy)", _lag_weekly_h10),
    "CPIAUCNS": ("CPI-U all items, NSA (unrevised)", _lag_monthly),
}


def parse_csv(series_id: str, text: str, receipt_time: int | None = None) -> list[FeedObservation]:
    lag = SERIES[series_id][1]
    now = int(receipt_time if receipt_time is not None else time.time())
    out = []
    rd = csv.reader(io.StringIO(text))
    header = next(rd, None)
    if not header or len(header) < 2:
        raise ValueError(f"unexpected FRED CSV header for {series_id}: {header}")
    for row in rd:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        d = date.fromisoformat(row[0])
        out.append(FeedObservation(series_id, d.isoformat(), float(row[1]), lag(d).isoformat(), PROVIDER, now))
    return out


def fetch(series_id: str, timeout: float = 30.0) -> list[FeedObservation]:
    req = urllib.request.Request(URL.format(sid=series_id), headers={"User-Agent": "atlas-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:    # noqa: S310 - fixed public https URL
        return parse_csv(series_id, r.read().decode())
