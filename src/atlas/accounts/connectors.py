"""Per-user connector storage. EVERY query here is scoped by ``user_id``: there is no function that reads another user's row.
Secrets are write-only: ``state`` returns booleans and the last four characters, never a value. Values are decrypted only
inside the server (connection tests and the credential resolver)."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from atlas.risk.safety import LiveTradingForbidden

from . import audit, crypto
from .catalog import BY_ID, CATALOG, ConnectorSpec, TestContext, validate_values
from .db import tx


class ConnectorError(Exception):
    def __init__(self, code: str, status: int = 400, message: str | None = None):
        super().__init__(message or code)
        self.code, self.status = code, status


def _spec(connector_id: str) -> ConnectorSpec:
    s = BY_ID.get(connector_id)
    if not s:
        raise ConnectorError("unknown_connector", 404)
    return s


def _row(conn, user_id: str, connector_id: str):
    return conn.execute("SELECT * FROM connectors WHERE user_id=? AND connector_id=?", (user_id, connector_id)).fetchone()


def count_for(conn, user_id: str, category: str | None = None) -> int:
    rows = conn.execute("SELECT connector_id FROM connectors WHERE user_id=?", (user_id,)).fetchall()
    if category is None:
        return len(rows)
    return sum(1 for r in rows if BY_ID.get(r["connector_id"]) and BY_ID[r["connector_id"]].category == category)


def _secret_rows(conn, user_id: str, pk: str):
    return {r["field"]: r for r in conn.execute("SELECT * FROM connector_secrets WHERE user_id=? AND connector_pk=?", (user_id, pk))}


def load_values(conn, user_id: str, connector_id: str, env: dict[str, str] | None = None) -> dict[str, str] | None:
    """Decrypted field values (secrets + config) for ONE user's connector, or None. Server-internal: never serialize the result."""
    row = _row(conn, user_id, connector_id)
    if not row:
        return None
    vals: dict[str, str] = dict(json.loads(row["config_json"]))
    for field, s in _secret_rows(conn, user_id, row["id"]).items():
        vals[field] = crypto.open_secret(dict(s), user_id=user_id, connector=connector_id, field=field, version=s["version"], env=env)
    return vals


def state(conn, user_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute("SELECT * FROM connectors WHERE user_id=?", (user_id,)):
        secrets = {f: {"set": True, "last4": s["last4"], "version": s["version"], "updated_at": s["updated_at"]}
                   for f, s in _secret_rows(conn, user_id, row["id"]).items()}
        out[row["connector_id"]] = {"status": row["status"], "mode": row["mode"], "config": json.loads(row["config_json"]), "secrets": secrets,
                                    "last_tested_at": row["last_tested_at"], "last_test_ok": None if row["last_test_ok"] is None else bool(row["last_test_ok"]),
                                    "last_test_detail": row["last_test_detail"], "updated_at": row["updated_at"]}
    return out


def library(conn, user_id: str) -> list[dict[str, Any]]:
    st = state(conn, user_id)
    items = []
    for spec in CATALOG:
        s = st.get(spec.id)
        light = "gray" if not s else {"ok": "green", "failed": "red"}.get(s["status"], "amber")
        if s and s["status"] == "ok" and s.get("last_test_detail", "").startswith("DSN format"):
            light = "amber"
        items.append({**spec.public(), "light": light, "state": s})
    return items


def save(conn, user_id: str, connector_id: str, values: dict[str, str], env: dict[str, str] | None = None, now: float | None = None) -> dict[str, Any]:
    spec = _spec(connector_id)
    now = int(time.time() if now is None else now)
    existing = _row(conn, user_id, connector_id)
    prior = load_values(conn, user_id, connector_id, env) if existing else {}
    incoming = {k: (v if isinstance(v, str) else "") for k, v in (values or {}).items() if spec.field(k)}
    merged = dict(prior or {})
    for f in spec.fields:
        v = incoming.get(f.name, "").strip()
        if v:
            merged[f.name] = v
        elif not f.secret and f.name in incoming:  # an explicitly blank non-secret field resets to its default
            merged.pop(f.name, None)
    try:
        clean = validate_values(spec, merged)
    except LiveTradingForbidden as ex:
        audit.log(conn, user_id, "connector.refused", "connector", connector_id, outcome="refused", detail={"reason": "live_or_unsafe", "fields": list(incoming.keys())}, now=now)
        raise ConnectorError("refused_live_trading", 422, str(ex)) from ex
    except ValueError as ex:
        raise ConnectorError("invalid_value", 400, str(ex)) from ex
    secret_fields = [f.name for f in spec.fields if f.secret and f.name in clean]
    written = [f for f in secret_fields if incoming.get(f, "").strip()]
    pk = existing["id"] if existing else uuid.uuid4().hex
    prior_secrets = _secret_rows(conn, user_id, pk) if existing else {}
    sealed: dict[str, tuple[crypto.SealedSecret, int, str]] = {}
    for f in written:  # may raise MasterKeyError BEFORE any write: fail closed
        ver = (prior_secrets[f]["version"] + 1) if f in prior_secrets else 1
        sealed[f] = (crypto.seal(clean[f], user_id=user_id, connector=connector_id, field=f, version=ver, env=env), ver, crypto.last4(clean[f]))
    config = {k: v for k, v in clean.items() if not (spec.field(k) and spec.field(k).secret)}
    with tx(conn):
        if existing:
            conn.execute("UPDATE connectors SET config_json=?, status='saved', mode=?, last_tested_at=NULL, last_test_ok=NULL, last_test_detail=NULL, updated_at=? WHERE id=? AND user_id=?",
                         (json.dumps(config, sort_keys=True), spec.mode, now, pk, user_id))
        else:
            conn.execute("INSERT INTO connectors (id,user_id,connector_id,config_json,status,mode,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (pk, user_id, connector_id, json.dumps(config, sort_keys=True), "saved", spec.mode, now, now))
        for f, (s, ver, l4) in sealed.items():
            conn.execute("DELETE FROM connector_secrets WHERE connector_pk=? AND field=? AND user_id=?", (pk, f, user_id))
            conn.execute("INSERT INTO connector_secrets (id,user_id,connector_pk,field,last4,ciphertext,nonce,wrapped_dek,wrap_nonce,kid,alg,version,created_at,updated_at)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (uuid.uuid4().hex, user_id, pk, f, l4, s.ciphertext, s.nonce, s.wrapped_dek, s.wrap_nonce, s.kid, crypto.ALG, ver, now, now))
        audit.log(conn, user_id, "connector.save" if not existing else "connector.update", "connector", connector_id,
                  detail={"fields": list(incoming.keys()), "written_fields": written, "rotated_fields": [f for f in written if f in prior_secrets]}, now=now)
    return state(conn, user_id)[connector_id]


def rotate(conn, user_id: str, connector_id: str, field: str, value: str, env: dict[str, str] | None = None, now: float | None = None) -> dict[str, Any]:
    spec = _spec(connector_id)
    f = spec.field(field)
    if not f or not f.secret:
        raise ConnectorError("not_a_secret_field", 400)
    if not _row(conn, user_id, connector_id):
        raise ConnectorError("not_found", 404)
    out = save(conn, user_id, connector_id, {field: value}, env=env, now=now)
    audit.log(conn, user_id, "connector.secret.rotate", "connector", connector_id, detail={"field": field}, now=now)
    return out


def delete(conn, user_id: str, connector_id: str, now: float | None = None) -> bool:
    _spec(connector_id)
    now = int(time.time() if now is None else now)
    with tx(conn):
        cur = conn.execute("DELETE FROM connectors WHERE user_id=? AND connector_id=?", (user_id, connector_id))  # cascades to secrets
        if cur.rowcount:
            audit.log(conn, user_id, "connector.delete", "connector", connector_id, now=now)
    return bool(cur.rowcount)


def run_test(conn, user_id: str, connector_id: str, ctx: TestContext, env: dict[str, str] | None = None, now: float | None = None) -> dict[str, Any]:
    spec = _spec(connector_id)
    now = int(time.time() if now is None else now)
    vals = load_values(conn, user_id, connector_id, env)
    if vals is None:
        raise ConnectorError("not_saved", 404, "Save this connector first")
    res = spec.test(vals, ctx)
    status = "ok" if res.ok else "failed"
    with tx(conn):
        conn.execute("UPDATE connectors SET status=?, last_tested_at=?, last_test_ok=?, last_test_detail=? WHERE user_id=? AND connector_id=?",
                     (status, now, 1 if res.ok else 0, res.detail[:240], user_id, connector_id))
        audit.log(conn, user_id, "connector.test", "connector", connector_id, outcome=status, detail={"result": res.state or status}, now=now)
    s = state(conn, user_id)[connector_id]
    s["light"] = "amber" if res.state == "format_only" else ("green" if res.ok else "red")
    return s


def rewrap_all(conn, env: dict[str, str] | None = None, now: float | None = None) -> dict[str, int]:
    """Master key rotation: move every wrapped DEK to the current ATLAS_MASTER_KEY. Secret ciphertexts are untouched."""
    n = 0
    rows = conn.execute("SELECT s.*, c.connector_id AS cid FROM connector_secrets s JOIN connectors c ON c.id=s.connector_pk").fetchall()
    _, kid = crypto.master_key(env)
    with tx(conn):
        for r in rows:
            if r["kid"] == kid:
                continue
            ns = crypto.rewrap(dict(r), user_id=r["user_id"], connector=r["cid"], field=r["field"], version=r["version"], env=env)
            conn.execute("UPDATE connector_secrets SET wrapped_dek=?, wrap_nonce=?, kid=? WHERE id=?", (ns.wrapped_dek, ns.wrap_nonce, ns.kid, r["id"]))
            n += 1
        audit.log(conn, None, "crypto.rewrap", "connector_secrets", "*", detail={"rows": n, "kid": kid}, now=now)
    return {"rewrapped": n, "total": len(rows)}
