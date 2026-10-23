"""Append-only, hash-chained audit log on SQLite.

Each row stores sha256(prev_hash || canonical_json(record)). UPDATE/DELETE are
blocked by triggers; `verify()` recomputes the chain to detect tampering done
outside the triggers (e.g. raw file edits).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from atlas.telemetry.logging_setup import redact

from atlas.governance.integrity.hashchain import GENESIS, link  # noqa: E402  (shared chain primitive)


class AuditTamperError(Exception):
    pass


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        if path != ":memory:":
            from atlas.risk.state_store import restrict_sqlite_files
            restrict_sqlite_files(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT NOT NULL, event TEXT NOT NULL, actor TEXT NOT NULL,
              payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
              BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
              BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
            """
        )

    @staticmethod
    def _hash(prev: str, ts: str, event: str, actor: str, payload: str) -> str:
        return link("", _canon([prev, ts, event, actor, payload]))  # == sha256(canon(...)); format unchanged

    def append(self, event: str, payload: dict[str, Any], actor: str = "system") -> str:
        body = _canon(redact(payload))  # never persist secrets
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            row = self._db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            h = self._hash(prev, ts, event, actor, body)
            self._db.execute(
                "INSERT INTO audit(ts,event,actor,payload,prev_hash,hash) VALUES (?,?,?,?,?,?)",
                (ts, event, actor, body, prev, h),
            )
        return h

    def entries(self, event: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT seq,ts,event,actor,payload,prev_hash,hash FROM audit"
        rows = self._db.execute(q + (" WHERE event=?" if event else "") + " ORDER BY seq", (event,) if event else ()).fetchall()
        return [dict(seq=r[0], ts=r[1], event=r[2], actor=r[3], payload=json.loads(r[4]), prev_hash=r[5], hash=r[6]) for r in rows]

    def verify(self) -> int:
        prev = GENESIS
        n = 0
        for seq, ts, event, actor, payload, prev_hash, h in self._db.execute(
            "SELECT seq,ts,event,actor,payload,prev_hash,hash FROM audit ORDER BY seq"
        ):
            if prev_hash != prev or self._hash(prev, ts, event, actor, payload) != h:
                raise AuditTamperError(f"audit chain broken at seq {seq}")
            prev = h
            n += 1
        return n

    @property
    def connection(self) -> sqlite3.Connection:  # for tests only
        return self._db
