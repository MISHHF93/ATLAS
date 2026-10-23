"""Append-only, hash-chained audit log (SHA-256 over prev hash + record)."""
from __future__ import annotations
import json
from atlas.governance.integrity.hashchain import GENESIS, link
from atlas.ledgers.db import now


def append(c, actor: str, action: str, data: dict | None = None, clock=now) -> str:
    row = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    ts = clock()
    body = json.dumps({"ts": ts, "actor": actor, "action": action, "data": data or {}}, sort_keys=True, default=str)
    h = link(prev, body)
    c.execute("INSERT INTO audit(ts,actor,action,data,prev,hash) VALUES(?,?,?,?,?,?)",
              (ts, actor, action, json.dumps(data or {}, sort_keys=True, default=str), prev, h))
    return h

def verify(c) -> tuple[bool, int | None]:
    prev = GENESIS
    for r in c.execute("SELECT * FROM audit ORDER BY id"):
        body = json.dumps({"ts": r["ts"], "actor": r["actor"], "action": r["action"], "data": json.loads(r["data"])},
                          sort_keys=True, default=str)
        if r["prev"] != prev or link(prev, body) != r["hash"]:
            return False, r["id"]
        prev = r["hash"]
    return True, None
