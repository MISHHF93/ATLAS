"""Prediction ledger: what the models said, when, and from which version (evo-16).

This is NOT the bar store. Predicted values are never written into ``bar_revisions`` and are never read back as training
labels; this file is only read for the health page (last prediction time) and for scoring a forecast against the real bar
that later arrives (live calibration)."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_PATH = "var/ml/predictions/log.sqlite"
_LOCK = threading.Lock()
_DBS: dict[str, sqlite3.Connection] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS latest(
  symbol TEXT NOT NULL, interval TEXT NOT NULL, computed_at REAL NOT NULL, status TEXT NOT NULL, reason TEXT,
  model_version TEXT, label TEXT, as_of_end INTEGER, direction TEXT, probability REAL, pool TEXT,
  PRIMARY KEY(symbol, interval));
CREATE TABLE IF NOT EXISTS latest_ok(
  symbol TEXT NOT NULL, interval TEXT NOT NULL, computed_at REAL NOT NULL, model_version TEXT, label TEXT, as_of_end INTEGER,
  direction TEXT, probability REAL, PRIMARY KEY(symbol, interval));
"""


def path_for(path: str | os.PathLike | None = None) -> str:
    if path:
        return str(path)
    env = os.environ.get("ATLAS_PREDICTION_LOG")
    if env:
        return env
    if "PYTEST_CURRENT_TEST" in os.environ:
        return ":memory:"   # tests never touch the developer's on-disk ledger
    return DEFAULT_PATH


def _db(path: str) -> sqlite3.Connection:
    with _LOCK:
        c = _DBS.get(path)
        if c is None:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(path, check_same_thread=False, timeout=10)
            c.executescript(SCHEMA)
            _DBS[path] = c
        return c


def reset() -> None:
    with _LOCK:
        for c in _DBS.values():
            try:
                c.close()
            except Exception:
                pass
        _DBS.clear()


def record(res: dict[str, Any], model_version: str | None, path=None) -> None:
    """Log one prediction result (any status). ``latest_ok`` only moves for a real model read. Never raises."""
    try:
        p = path_for(path)
        db = _db(p)
        sym, iv = str(res.get("symbol")), str(res.get("interval"))
        now = float(res.get("computed_at") or time.time())
        pool = res.get("pool")
        with _LOCK:
            db.execute("INSERT OR REPLACE INTO latest VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (sym, iv, now, str(res.get("status")), str(res.get("reason") or "")[:400], model_version, res.get("label"),
                        res.get("as_of_end"), res.get("direction"), res.get("probability"), ",".join(pool) if isinstance(pool, list) else None))
            if res.get("status") == "ok":
                db.execute("INSERT OR REPLACE INTO latest_ok VALUES(?,?,?,?,?,?,?,?)",
                           (sym, iv, now, model_version, res.get("label"), res.get("as_of_end"), res.get("direction"), res.get("probability")))
            db.commit()
    except Exception:
        pass


def latest(path=None) -> dict[tuple[str, str], dict[str, Any]]:
    db = _db(path_for(path))
    cols = ("symbol", "interval", "computed_at", "status", "reason", "model_version", "label", "as_of_end", "direction", "probability")
    with _LOCK:
        rows = db.execute("SELECT symbol, interval, computed_at, status, reason, model_version, label, as_of_end, direction, probability FROM latest").fetchall()
        ok = {(r[0], r[1]): r[2] for r in db.execute("SELECT symbol, interval, computed_at FROM latest_ok").fetchall()}
    out = {}
    for r in rows:
        d = dict(zip(cols, r))
        d["last_ok_at"] = ok.get((r[0], r[1]))
        out[(r[0], r[1])] = d
    return out
