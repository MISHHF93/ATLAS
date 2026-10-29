"""Optional fixed-bounty broker-partner referrals. OFF BY DEFAULT.

Guardrails (monetization_plan.md sections 3.3, 3.5, 8.10):
* A partner is usable only when ``legal_status='approved'`` AND ``active=1``; every seeded partner starts ``not_approved`` and inactive.
  Only an admin can flip that, and every flip is audit-logged. No link is shown to a user for any other partner.
* The bounty is a FIXED amount per qualified account (``cpa_cents``). Nothing here reads trade volume, order flow or profit.
* A referral is recorded only after the user was shown the disclosure (``disclosure_shown_at``) that ATLAS may be paid when they open an account.
* Partners are listed alphabetically, never ranked by payout.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from . import audit, ledger
from .db import tx

DISCLOSURE = "ATLAS may be paid a fixed fee by this broker if you open and fund an account through this link. It does not change your trading costs and ATLAS never sees your trades or funds."
STATUSES = ("clicked", "account_opened", "qualified", "paid", "void")


class BrokerError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def public_partners(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT code,name,program_type,terms_url FROM broker_partners WHERE legal_status='approved' AND active=1 ORDER BY name").fetchall()
    return {"enabled": bool(rows), "disclosure": DISCLOSURE, "partners": [{"code": r["code"], "name": r["name"], "terms_url": r["terms_url"]} for r in rows],
            "note": "Broker referrals are switched off until a legal opinion approves them." if not rows else None}


def _partner(conn, code: str, require_usable: bool = True):
    p = conn.execute("SELECT * FROM broker_partners WHERE code=?", (code,)).fetchone()
    if p is None or (require_usable and not (p["legal_status"] == "approved" and p["active"] == 1)):
        raise BrokerError("partner_unavailable", 404)  # same answer for unknown and not-approved: nothing to enumerate
    return p


def start_referral(conn: sqlite3.Connection, user_id: str, code: str, disclosure_shown: bool, now: float | None = None) -> dict[str, Any]:
    p = _partner(conn, code)
    if disclosure_shown is not True:
        raise BrokerError("disclosure_required", 400)
    now_i = int(time.time() if now is None else now)
    with tx(conn):
        conn.execute("INSERT OR IGNORE INTO broker_referrals (id,user_id,partner_id,status,disclosure_shown_at,created_at) VALUES (?,?,?,'clicked',?,?)",
                     (uuid.uuid4().hex, user_id, p["id"], now_i, now_i))
        audit.log(conn, user_id, "broker.referral_started", "broker_partner", p["code"], now=now_i)
    return {"partner": p["code"], "terms_url": p["terms_url"], "status": "clicked"}


def set_partner(conn: sqlite3.Connection, actor_id: str, code: str, legal_status: str | None, active: bool | None) -> dict[str, Any]:
    p = _partner(conn, code, require_usable=False)
    ls = p["legal_status"] if legal_status is None else legal_status
    if ls not in ("not_approved", "approved"):
        raise BrokerError("bad_legal_status")
    act = p["active"] if active is None else int(bool(active))
    if act and ls != "approved":
        raise BrokerError("cannot_activate_unapproved_partner")
    with tx(conn):
        conn.execute("UPDATE broker_partners SET legal_status=?, active=? WHERE id=?", (ls, act, p["id"]))
        audit.log(conn, actor_id, "broker.partner_set", "broker_partner", code, detail={"legal_status": ls, "active": act})
    return {"code": code, "legal_status": ls, "active": bool(act)}


def update_referral(conn: sqlite3.Connection, actor_id: str, referral_id: str, status: str, cpa_cents: int | None = None,
                    currency: str = "usd", bank_ref: str | None = None, now: float | None = None) -> dict[str, Any]:
    """Admin moves a referral along. ``paid`` books the partner bounty into the ledger as incoming cash (fixed amount only)."""
    if status not in STATUSES:
        raise BrokerError("bad_status")
    now_i = int(time.time() if now is None else now)
    with tx(conn):
        r = conn.execute("SELECT r.*, p.code AS pcode FROM broker_referrals r JOIN broker_partners p ON p.id=r.partner_id WHERE r.id=?", (referral_id,)).fetchone()
        if r is None:
            raise BrokerError("not_found", 404)
        cents = r["cpa_cents"] if cpa_cents is None else int(cpa_cents)
        if not 0 <= cents <= 500_000:
            raise BrokerError("bad_cpa")
        conn.execute("UPDATE broker_referrals SET status=?, cpa_cents=?, currency=?, qualified_at=COALESCE(qualified_at, ?), paid_at=? WHERE id=?",
                     (status, cents, currency.lower()[:3], now_i if status in ("qualified", "paid") else None, now_i if status == "paid" else None, referral_id))
        if status == "paid":
            if cents <= 0:
                raise BrokerError("paid_needs_amount")
            ledger.append(conn, "partner_cpa", "in", cents, currency, r["pcode"], ts=now_i, broker_referral_id=referral_id, bank_ref=bank_ref,
                          memo="fixed partner bounty", dedupe_key=f"cpa:{referral_id}")
        audit.log(conn, actor_id, "broker.referral_updated", "broker_referral", referral_id, detail={"status": status, "cpa_cents": cents}, now=now_i)
    return {"id": referral_id, "status": status, "cpa_cents": cents}
