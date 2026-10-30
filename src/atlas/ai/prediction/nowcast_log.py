"""Nowcast issue/score ledger (evo-16 M3): live calibration. Separate sqlite file, never the bar store, never a label source.

``issue`` freezes the last nowcast made BEFORE a target bar closed (rows are not updated once the bar's end has passed);
``score_due`` grades each against the real bar when it arrives (end-of-day bars can arrive with a lag, so unresolved rows wait)."""
from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

DEFAULT = "var/ml/predictions/nowcast.sqlite"
_LOCK = threading.Lock()
_MEM: dict[str, sqlite3.Connection] = {}
DDL = """
CREATE TABLE IF NOT EXISTS issued(symbol TEXT, interval TEXT, target_start INTEGER, target_end INTEGER, made_at REAL, anchor_t REAL,
  anchor_px REAL, mid REAL, lo REAL, hi REAL, k REAL, pool TEXT, mode TEXT, scale REAL, PRIMARY KEY(symbol, interval, target_start));
CREATE TABLE IF NOT EXISTS scored(symbol TEXT, interval TEXT, target_start INTEGER, scored_at REAL, actual REAL, mid REAL, lo REAL, hi REAL,
  anchor_px REAL, err_log REAL, naive_err_log REAL, z REAL, covered INTEGER, k REAL, pool TEXT, mode TEXT, made_at REAL,
  PRIMARY KEY(symbol, interval, target_start));
CREATE INDEX IF NOT EXISTS ix_scored_pool ON scored(pool, interval, scored_at);
"""


def path_for(path: str | None = None) -> str:
    if path:
        return path
    env = os.environ.get("ATLAS_NOWCAST_LOG")
    if env:
        return env
    return ":memory:" if "PYTEST_CURRENT_TEST" in os.environ else DEFAULT


def _conn(path: str | None) -> sqlite3.Connection:
    p = path_for(path)
    with _LOCK:
        c = _MEM.get(p)
        if c is None:
            if p != ":memory:":
                Path(p).parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(p, check_same_thread=False, timeout=30)
            c.executescript(DDL)
            _MEM[p] = c
        return c


def reset(path: str | None = None) -> None:
    with _LOCK:
        c = _MEM.pop(path_for(path), None)
    if c is not None:
        c.close()


def issue(rows: Iterable[dict[str, Any]], now: float, path: str | None = None) -> int:
    """Upsert the forecast for each target bar still open at ``now``; a target whose end has passed is never overwritten."""
    c = _conn(path)
    n = 0
    with _LOCK:
        for r in rows:
            if r["target_end"] <= now:
                continue
            c.execute("INSERT OR REPLACE INTO issued VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["symbol"], r["interval"], r["target_start"], r["target_end"], now, r["anchor_t"], r["anchor_px"], r["mid"], r["lo"], r["hi"],
                       r["k"], r.get("pool"), r.get("mode"), r.get("scale", 1.0)))
            n += 1
        c.commit()
    return n


def score_due(real_bar, now: float, path: str | None = None, limit: int = 4000) -> dict[str, Any]:
    """``real_bar(symbol, interval, start) -> close | None`` (closed, confirmed). Grades every issued row whose target bar has ended."""
    c = _conn(path)
    with _LOCK:
        due = c.execute("SELECT symbol,interval,target_start,target_end,made_at,anchor_px,mid,lo,hi,k,pool,mode,scale FROM issued "
                        "WHERE target_end<=? AND (symbol,interval,target_start) NOT IN (SELECT symbol,interval,target_start FROM scored) "
                        "ORDER BY target_end LIMIT ?", (now, limit)).fetchall()
    scored = waiting = 0
    out = []
    with _LOCK:   # a target that never produced a real bar within 14 days (holiday, delisted) is dropped, not left to skew counts
        exp = c.execute("DELETE FROM issued WHERE target_end<? AND (symbol,interval,target_start) NOT IN (SELECT symbol,interval,target_start FROM scored)",
                        (now - 14 * 86400,)).rowcount
        c.commit()
    for sym, iv, ts, te, made, apx, mid, lo, hi, k, pool, mode, sc in due:
        try:
            actual = real_bar(sym, iv, ts)
        except Exception:
            actual = None
        if actual is None or not actual > 0:
            waiting += 1
            continue
        half = math.log(hi / lo) / 2
        err = math.log(actual / mid)
        naive = math.log(actual / apx)
        z = err / (half / (sc or 1.0)) if half > 0 else float("nan")   # relative to the UNSCALED band, so live scaling never compounds
        out.append((sym, iv, ts, now, actual, mid, lo, hi, apx, err, naive, z, int(lo <= actual <= hi), k, pool, mode, made))
        scored += 1
    if out:
        with _LOCK:
            c.executemany("INSERT OR IGNORE INTO scored VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", out)
            c.commit()
    return {"scored": scored, "waiting_for_real_bar": waiting, "expired": exp}


def calibration(path: str | None = None, pool: str | None = None, interval: str | None = None, since: float | None = None) -> dict[str, Any]:
    """Live calibration of the nowcast: coverage of the 80% interval, error vs the naive last-print forecast, by pool x interval."""
    c = _conn(path)
    q, a = "SELECT pool, interval, covered, err_log, naive_err_log, z, k, mode FROM scored WHERE 1=1", []
    if pool:
        q += " AND pool=?"; a.append(pool)
    if interval:
        q += " AND interval=?"; a.append(interval)
    if since:
        q += " AND scored_at>=?"; a.append(since)
    with _LOCK:
        rows = c.execute(q, a).fetchall()
        n_issued = c.execute("SELECT COUNT(*) FROM issued").fetchone()[0]
        n_wait = c.execute("SELECT COUNT(*) FROM issued WHERE (symbol,interval,target_start) NOT IN (SELECT symbol,interval,target_start FROM scored)").fetchone()[0]
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r[0], r[1]), []).append(r)
    cells = []
    for (pl, iv), rs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        n = len(rs)
        cov = sum(r[2] for r in rs) / n
        mae = sum(abs(r[3]) for r in rs) / n
        nmae = sum(abs(r[4]) for r in rs) / n
        zs = sorted(abs(r[5]) for r in rs if r[5] == r[5])
        cells.append({"pool": pl, "interval": iv, "n": n, "coverage_80": round(cov, 4), "target": 0.8, "mae_bps": round(mae * 1e4, 3),
                      "naive_mae_bps": round(nmae * 1e4, 3), "mean_k": round(sum(r[6] for r in rs) / n, 2),
                      "abs_z_p80": round(zs[min(len(zs) - 1, int(0.8 * len(zs)))], 3) if zs else None})
    n_all = len(rows)
    return {"n_scored": n_all, "n_issued": n_issued, "n_waiting": n_wait,
            "coverage_80": round(sum(r[2] for r in rows) / n_all, 4) if n_all else None, "target": 0.8,
            "note": "Live out-of-sample: each row is a nowcast frozen before its bar closed, graded against the real bar. Coverage should be near 0.80; "
                    "n is small until bars accumulate. No profitability claim.", "cells": cells}


def live_scale(pool: str, interval: str, path: str | None = None, min_n: int = 60) -> float:
    """Multiplier on the interval half-width from live coverage: |z| p80 above 1 means the band was too tight. Bounded to [0.8, 1.6]."""
    c = _conn(path)
    with _LOCK:
        zs = [abs(r[0]) for r in c.execute("SELECT z FROM scored WHERE pool=? AND interval=? ORDER BY scored_at DESC LIMIT 800", (pool, interval)).fetchall()
              if r[0] == r[0]]
    if len(zs) < min_n:
        return 1.0
    zs.sort()
    p80 = zs[min(len(zs) - 1, int(0.8 * len(zs)))]
    return float(min(1.6, max(0.8, p80)))
