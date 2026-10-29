"""Append-only, hash-chained money ledger (``payouts_ledger``) for the finance export.

Records cash that moves between ATLAS and its counterparties (Stripe payouts, refunds, chargebacks, partner bounties, tax remittances).
It NEVER records anything about a user's trading funds: those stay at the user's own broker and ATLAS is not in that path.

* Each row's hash = sha256(prev_hash | canonical JSON of the money fields). ``flooos_batch`` is deliberately NOT hashed: it is the one
  field that may be set (once, NULL -> label) after export. Database triggers (migration 5) reject every other UPDATE and all DELETEs.
* ``dedupe_key`` makes event-driven inserts idempotent (a replayed Stripe webhook cannot double-book a payout).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from typing import Any

from .db import tx

GENESIS = "0" * 64
KINDS = ("stripe_payout", "stripe_fee", "refund", "chargeback", "dispute_fee", "partner_cpa", "user_credit", "tax_remittance", "adjustment")
_HASHED = ("id", "seq", "ts", "kind", "direction", "amount_cents", "currency", "fx_rate_micros", "counterparty", "stripe_payout_id",
           "invoice_id", "broker_referral_id", "tax_record_id", "bank_ref", "dedupe_key", "memo")
_CUR = re.compile(r"^[a-z]{3}$")


class LedgerError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _digest(prev: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev + "|" + json.dumps({k: row[k] for k in _HASHED}, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()


def append(conn: sqlite3.Connection, kind: str, direction: str, amount_cents: int, currency: str, counterparty: str, *,
           ts: float | None = None, fx_rate_micros: int | None = None, stripe_payout_id: str | None = None, invoice_id: str | None = None,
           broker_referral_id: str | None = None, tax_record_id: str | None = None, bank_ref: str | None = None,
           memo: str = "", dedupe_key: str | None = None) -> str | None:
    """Append one row. Returns its id, or None if ``dedupe_key`` was already booked."""
    if kind not in KINDS:
        raise LedgerError("bad_kind")
    if direction not in ("in", "out"):
        raise LedgerError("bad_direction")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or not 0 < amount_cents <= 10**12:
        raise LedgerError("bad_amount")
    cur = (currency or "").lower()
    if not _CUR.match(cur):
        raise LedgerError("bad_currency")
    cp = (counterparty or "").strip()[:60]
    if not cp:
        raise LedgerError("bad_counterparty")
    rid = uuid.uuid4().hex

    def _w(c: sqlite3.Connection) -> str | None:
        if dedupe_key and c.execute("SELECT 1 FROM payouts_ledger WHERE dedupe_key=?", (dedupe_key,)).fetchone():
            return None
        last = c.execute("SELECT seq, hash FROM payouts_ledger ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        row = {"id": rid, "seq": seq, "ts": int(time.time() if ts is None else ts), "kind": kind, "direction": direction, "amount_cents": amount_cents,
               "currency": cur, "fx_rate_micros": fx_rate_micros, "counterparty": cp, "stripe_payout_id": stripe_payout_id, "invoice_id": invoice_id,
               "broker_referral_id": broker_referral_id, "tax_record_id": tax_record_id, "bank_ref": bank_ref, "dedupe_key": dedupe_key, "memo": (memo or "")[:200]}
        c.execute("INSERT INTO payouts_ledger (id,seq,ts,kind,direction,amount_cents,currency,fx_rate_micros,counterparty,stripe_payout_id,invoice_id,broker_referral_id,"
                  "tax_record_id,bank_ref,dedupe_key,memo,prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (*[row[k] for k in _HASHED], prev, _digest(prev, row)))
        return rid

    if conn.in_transaction:
        return _w(conn)
    with tx(conn):
        return _w(conn)


def verify_chain(conn: sqlite3.Connection) -> dict[str, Any]:
    prev, n = GENESIS, 0
    for r in conn.execute("SELECT * FROM payouts_ledger ORDER BY seq"):
        row = {k: r[k] for k in _HASHED}
        if r["prev_hash"] != prev or _digest(prev, row) != r["hash"]:
            return {"ok": False, "broken_at_seq": r["seq"], "rows": n}
        prev, n = r["hash"], n + 1
    return {"ok": True, "rows": n}


def rows(conn: sqlite3.Connection, start: int = 0, end: int | None = None, limit: int = 5000) -> list[dict[str, Any]]:
    end = end if end is not None else 2**62
    return [dict(r) for r in conn.execute("SELECT * FROM payouts_ledger WHERE ts>=? AND ts<? ORDER BY seq LIMIT ?", (int(start), int(end), int(limit)))]


def mark_exported(conn: sqlite3.Connection, batch: str, start: int, end: int) -> int:
    """Label not-yet-exported rows in [start, end) with ``batch``. The only mutation the ledger allows (NULL -> label, once)."""
    batch = (batch or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]{3,40}$", batch):
        raise LedgerError("bad_batch")
    with tx(conn):
        return conn.execute("UPDATE payouts_ledger SET flooos_batch=? WHERE flooos_batch IS NULL AND ts>=? AND ts<?", (batch, int(start), int(end))).rowcount
