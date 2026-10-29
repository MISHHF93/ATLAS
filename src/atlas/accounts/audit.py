"""Append-only, hash-chained audit log. Records WHAT changed and WHO did it, never secret values.
Each row's hash = sha256(prev_hash | canonical JSON of the row), so editing or deleting a row breaks ``verify_chain``."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

from .db import tx

GENESIS = "0" * 64
# Keys that must never appear in an audit detail, whatever the caller passes.
_FORBIDDEN = ("secret", "password", "token", "key", "dsn", "webhook", "value", "ciphertext")


def _clean(detail: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (detail or {}).items():
        lk = str(k).lower()
        if any(f in lk for f in _FORBIDDEN) and lk not in ("key_last4", "field", "fields", "keys_present"):
            out[k] = "[redacted]"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:200]
        elif isinstance(v, (list, tuple)):
            out[k] = [x if isinstance(x, (int, float, bool)) else str(x)[:80] for x in v][:40]
        else:
            out[k] = str(v)[:200]
    return out


def _digest(prev: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev + "|" + json.dumps(row, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def log(conn: sqlite3.Connection, actor_user_id: str | None, action: str, target_type: str = "", target_id: str = "",
        outcome: str = "ok", detail: dict[str, Any] | None = None, now: float | None = None) -> str:
    ts = int(now if now is not None else time.time())
    d = _clean(detail)
    rid = uuid.uuid4().hex

    def _write(c: sqlite3.Connection) -> None:
        last = c.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        row = {"id": rid, "seq": seq, "ts": ts, "actor": actor_user_id, "action": action, "tt": target_type, "ti": target_id,
               "outcome": outcome, "detail": d}
        c.execute("INSERT INTO audit_log (id, seq, ts, actor_user_id, action, target_type, target_id, outcome, detail_json, prev_hash, hash)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (rid, seq, ts, actor_user_id, action, target_type, target_id, outcome, json.dumps(d, sort_keys=True), prev, _digest(prev, row)))

    if conn.in_transaction:
        _write(conn)
    else:
        with tx(conn):
            _write(conn)
    return rid


def verify_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    prev, n = GENESIS, 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY seq"):
        row = {"id": r["id"], "seq": r["seq"], "ts": r["ts"], "actor": r["actor_user_id"], "action": r["action"],
               "tt": r["target_type"], "ti": r["target_id"], "outcome": r["outcome"], "detail": json.loads(r["detail_json"])}
        if r["prev_hash"] != prev or _digest(prev, row) != r["hash"]:
            return {"ok": False, "broken_at_seq": r["seq"], "rows": n}
        prev, n = r["hash"], n + 1
    return {"ok": True, "rows": n}


def recent(conn: sqlite3.Connection, user_id: str | None, limit: int = 100) -> list[dict[str, Any]]:
    """``user_id=None`` returns everyone's rows (admin view). Otherwise only that actor's own rows."""
    q = "SELECT seq, ts, actor_user_id, action, target_type, target_id, outcome, detail_json FROM audit_log"
    args: tuple = ()
    if user_id is not None:
        q += " WHERE actor_user_id = ?"
        args = (user_id,)
    q += " ORDER BY seq DESC LIMIT ?"
    return [{"seq": r["seq"], "ts": r["ts"], "actor": r["actor_user_id"], "action": r["action"], "target_type": r["target_type"],
             "target_id": r["target_id"], "outcome": r["outcome"], "detail": json.loads(r["detail_json"])}
            for r in conn.execute(q, args + (int(limit),))]
