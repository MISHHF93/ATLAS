"""Predicted fill for missing seconds in the crypto 1s trade bars (t227u).

A "missing second" is a second with no trade: the real table simply has no row. This module ESTIMATES the last-trade
price inside short gaps (<= MAX_GAP seconds, between two real bars of the same instrument) with a log-linear bridge
and an empirical, calibrated 80% interval by gap length.

Rules (tests enforce them):
  * output goes ONLY to ``pred_1s`` in its own sqlite (default var/ml/nowcast_xgb/pred_1s.sqlite). Never into
    ``atlas_1s.sqlite`` or the feed store, never as a bar;
  * each row is flagged ``predicted=1`` and ``uses_future=1`` (the bridge needs the NEXT real bar), so it can never be a
    decision-time feature or a training label. ``multires`` reads only real tables;
  * the interval comes from masked real data: the bridge is evaluated on real interior seconds with both endpoints taken
    from real bars, and compared with the carry-forward baseline. With too little history the interval is None
    ("uncalibrated") instead of invented;
  * a gradient-boosted model is NOT used here on purpose: both endpoints are known, so interpolation is the right
    estimator, and the 1s store holds days, not the weeks a learned residual model would need. The calibration report
    says when that changes.
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

MAX_GAP = 300
MIN_CALIB = 200
BUCKETS = ((2, 2), (3, 5), (6, 15), (16, 60), (61, 300))       # gap length in seconds (b - a), inclusive
ALPHA = 0.2
METHOD = "log_linear_bridge"
LABEL = "Predicted (not market data)"
SQL = """
CREATE TABLE IF NOT EXISTS pred_1s(
  venue TEXT NOT NULL, instrument TEXT NOT NULL, ts INTEGER NOT NULL, est_close REAL NOT NULL, lo REAL, hi REAL,
  gap_len INTEGER NOT NULL, method TEXT NOT NULL, calib_n INTEGER NOT NULL, made_at INTEGER NOT NULL,
  predicted INTEGER NOT NULL DEFAULT 1 CHECK(predicted=1), uses_future INTEGER NOT NULL DEFAULT 1 CHECK(uses_future=1),
  PRIMARY KEY(venue, instrument, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS calib(
  venue TEXT NOT NULL, bucket TEXT NOT NULL, n INTEGER NOT NULL, q80_abs REAL, mae_bridge REAL, mae_carry REAL, made_at INTEGER NOT NULL,
  PRIMARY KEY(venue, bucket));
"""


def default_path() -> str:
    env = os.environ.get("ATLAS_PRED_1S_DB")
    if env:
        return env
    return ":memory:" if "pytest" in sys.modules else "var/ml/nowcast_xgb/pred_1s.sqlite"


def bucket_of(L: int) -> str | None:
    for lo, hi in BUCKETS:
        if lo <= L <= hi:
            return f"{lo}-{hi}"
    return None


def bridge(ta: int, pa: float, tb: int, pb: float, s: int) -> float:
    w = (s - ta) / (tb - ta)
    return math.exp(math.log(pa) + (math.log(pb) - math.log(pa)) * w)


def real_series(rows: Sequence[tuple]) -> tuple[np.ndarray, np.ndarray]:
    """rows from TradeBarStore.bars_1s -> (ts, close) of REAL bars."""
    ts = np.array([r[0] for r in rows], dtype=np.int64)
    c = np.array([r[4] for r in rows], dtype=float)
    return ts, c


def calibrate(series: Sequence[tuple[np.ndarray, np.ndarray]], rng_seed: int = 5, max_samples: int = 40000) -> dict:
    """Mask real interior seconds: for real a<s<b with b-a in a bucket, predict s from (a,b) only. Pooled over a venue's instruments."""
    out = {}
    rng = np.random.default_rng(rng_seed)
    errs: dict[str, list[tuple[float, float]]] = {}
    total = 0
    for ts, c in series:
        n = len(ts)
        for i in range(n - 2):
            for j in (i + 2, i + 3, i + 5, i + 9, i + 17, i + 33):
                if j >= n:
                    break
                b = bucket_of(int(ts[j] - ts[i]))
                if b is None:
                    continue
                m = int(rng.integers(i + 1, j))
                est = bridge(int(ts[i]), float(c[i]), int(ts[j]), float(c[j]), int(ts[m]))
                errs.setdefault(b, []).append((abs(math.log(c[m] / est)), abs(math.log(c[m] / c[i]))))
                total += 1
            if total > max_samples:
                break
    for b, v in errs.items():
        a = np.array(v)
        k = min(1.0, math.ceil((len(a) + 1) * (1 - ALPHA)) / len(a))
        out[b] = {"n": len(a), "q80_abs": float(np.quantile(a[:, 0], k, method="higher")) if len(a) >= MIN_CALIB else None,
                  "mae_bridge": float(a[:, 0].mean()), "mae_carry": float(a[:, 1].mean())}
    return out


def calibrate_venue(trade_store, venue: str, t0: int, t1: int) -> dict:
    ids = [r[0] for r in _ids(trade_store, venue, t0, t1)]
    return calibrate([real_series(trade_store.bars_1s(venue, i, t0, t1)) for i in ids])


def _ids(trade_store, venue: str, t0: int, t1: int):
    with trade_store._ro() as c:
        return c.execute("SELECT DISTINCT instrument FROM bars_1s WHERE venue=? AND ts>=? AND ts<?", (venue, int(t0), int(t1))).fetchall()


class PredStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._c.executescript(SQL)

    def save_calib(self, venue: str, cal: dict, now: int) -> None:
        with self._c:
            for b, v in cal.items():
                self._c.execute("INSERT OR REPLACE INTO calib VALUES(?,?,?,?,?,?,?)", (venue, b, v["n"], v["q80_abs"], v["mae_bridge"], v["mae_carry"], int(now)))

    def calib(self, venue: str) -> dict:
        return {b: {"n": n, "q80_abs": q, "mae_bridge": mb, "mae_carry": mc}
                for b, n, q, mb, mc in self._c.execute("SELECT bucket,n,q80_abs,mae_bridge,mae_carry FROM calib WHERE venue=?", (venue,))}

    def rows(self, venue: str, instrument: str, t0: int, t1: int) -> list[tuple]:
        return self._c.execute("SELECT ts,est_close,lo,hi,gap_len,method,calib_n,predicted,uses_future FROM pred_1s WHERE venue=? AND instrument=? AND ts>=? AND ts<? ORDER BY ts",
                               (venue, instrument, int(t0), int(t1))).fetchall()

    def put(self, rows: list[tuple]) -> None:
        with self._c:
            self._c.executemany("INSERT OR REPLACE INTO pred_1s(venue,instrument,ts,est_close,lo,hi,gap_len,method,calib_n,made_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)

    def close(self) -> None:
        self._c.close()


def fill(trade_store, store: PredStore, venue: str, instrument: str, t0: int, t1: int, now: int | None = None) -> list[dict]:
    """Predict missing seconds in (t0, t1) for gaps of 2..MAX_GAP seconds between two REAL bars. Reads trade_store read-only."""
    now = int(now if now is not None else time.time())
    ts, c = real_series(trade_store.bars_1s(venue, instrument, t0, t1))
    cal = store.calib(venue)
    out, rows = [], []
    for i in range(len(ts) - 1):
        L = int(ts[i + 1] - ts[i])
        if L < 2 or L > MAX_GAP:
            continue
        b = bucket_of(L)
        cb = cal.get(b) if b else None
        q = cb["q80_abs"] if cb else None
        n = cb["n"] if cb else 0
        for s in range(int(ts[i]) + 1, int(ts[i + 1])):
            est = bridge(int(ts[i]), float(c[i]), int(ts[i + 1]), float(c[i + 1]), s)
            lo = est * math.exp(-q) if q is not None else None
            hi = est * math.exp(q) if q is not None else None
            rows.append((venue, instrument, s, est, lo, hi, L, METHOD, n, now))
            out.append({"venue": venue, "instrument": instrument, "ts": s, "est_close": est, "lo": lo, "hi": hi, "gap_len": L,
                        "predicted": True, "uses_future": True, "label": LABEL, "interval": "80%" if q is not None else "uncalibrated"})
    store.put(rows)
    return out
