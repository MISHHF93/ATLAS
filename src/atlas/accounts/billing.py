"""Plans, entitlements seed and subscription lookup.

NO PER-TRADE COMMISSIONS, EVER: ATLAS is paper-only, never touches client funds and takes no cut of any trade. Revenue is
subscriptions (plan_entitlements gate features and quotas) plus a referral ledger (partner_referrals). See docs/atlas/monetization.md.

TODO(pricing): every plan below is a PLACEHOLDER. Names, prices and limits are NOT decided. Replace via a new migration or an admin
tool, set is_placeholder=0, and complete the legal review in docs/atlas/monetization.md before any live Stripe key is ever used.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

# key -> (kind, free, pro, team, period). quota None = unlimited. flags are booleans.
ENTITLEMENT_KEYS: dict[str, tuple[str, Any, Any, Any, str]] = {
    "connectors.max":          ("quota", 4, 12, 25, "none"),     # saved connectors in the library
    "connector_tests.daily":   ("quota", 20, 200, 1000, "day"),  # outbound connection tests per UTC day
    "alerts.channels.max":     ("quota", 1, 3, 5, "none"),       # alert-category connectors (Telegram / Discord / ntfy)
    "feature.research_lab":    ("flag", False, True, True, "none"),
    "feature.team_workspace":  ("flag", False, False, True, "none"),
}
# (code, name, description, price_cents, sort)  PLACEHOLDER PRICES: not real, not decided.
PLANS: tuple[tuple[str, str, str, int, int], ...] = (
    ("free", "Free", "PLACEHOLDER plan. Paper trading research with a small connector allowance.", 0, 0),
    ("pro", "Pro", "PLACEHOLDER plan. More connectors, research lab. Price is a placeholder, not an offer.", 1900, 1),
    ("team", "Team", "PLACEHOLDER plan. Team workspace flag reserved (not built yet). Price is a placeholder, not an offer.", 4900, 2),
)
ACTIVE_STATUSES = ("active", "trialing")


def seed_plans(conn: sqlite3.Connection) -> None:
    """Idempotent. Inserts missing plans / entitlements only, so operator edits to existing rows are never overwritten."""
    now = int(time.time())
    conn.execute("BEGIN IMMEDIATE")
    try:
        for code, name, desc, cents, sort in PLANS:
            conn.execute("INSERT OR IGNORE INTO plans (id,code,name,description,price_cents,currency,billing_interval,is_placeholder,active,sort,created_at)"
                         " VALUES (?,?,?,?,?,'usd','month',1,1,?,?)", (f"plan_{code}", code, name, desc, cents, sort, now))
        idx = {"free": 1, "pro": 2, "team": 3}
        for key, spec in ENTITLEMENT_KEYS.items():
            kind, period = spec[0], spec[4]
            for code, i in idx.items():
                v = spec[i]
                conn.execute("INSERT OR IGNORE INTO plan_entitlements (plan_id,key,kind,bool_value,int_value,period) VALUES (?,?,?,?,?,?)",
                             (f"plan_{code}", key, kind, (1 if v else 0) if kind == "flag" else None, v if kind == "quota" else None, period))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def plans_public(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for p in conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort"):
        ents = {e["key"]: ({"kind": "flag", "value": bool(e["bool_value"])} if e["kind"] == "flag"
                           else {"kind": "quota", "limit": e["int_value"], "period": e["period"]})
                for e in conn.execute("SELECT * FROM plan_entitlements WHERE plan_id=?", (p["id"],))}
        out.append({"code": p["code"], "name": p["name"], "description": p["description"], "price_cents": p["price_cents"],
                    "currency": p["currency"], "interval": p["billing_interval"], "is_placeholder": bool(p["is_placeholder"]), "entitlements": ents})
    return out


def current_subscription(conn: sqlite3.Connection, user_id: str, now: float | None = None) -> sqlite3.Row | None:
    now = int(time.time() if now is None else now)
    return conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? AND status IN ('active','trialing') AND (current_period_end IS NULL OR current_period_end > ?)"
        " ORDER BY updated_at DESC LIMIT 1", (user_id, now - 3 * 86400)).fetchone()


def plan_for_user(conn: sqlite3.Connection, user_id: str, now: float | None = None) -> sqlite3.Row:
    """The user's effective plan. Anything not provably active (past_due, canceled, unknown) is the Free plan: fail to the smallest limits."""
    sub = current_subscription(conn, user_id, now)
    row = conn.execute("SELECT * FROM plans WHERE id=?", (sub["plan_id"],)).fetchone() if sub else None
    return row or conn.execute("SELECT * FROM plans WHERE code='free'").fetchone()


def subscription_public(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    plan = plan_for_user(conn, user_id)
    sub = current_subscription(conn, user_id)
    invs = [{"id": r["stripe_invoice_id"], "status": r["status"], "amount_paid": r["amount_paid"], "amount_due": r["amount_due"],
             "currency": r["currency"], "url": r["hosted_invoice_url"], "created_at": r["created_at"]}
            for r in conn.execute("SELECT * FROM invoices WHERE user_id=? ORDER BY created_at DESC LIMIT 12", (user_id,))]
    return {"plan": plan["code"], "plan_name": plan["name"], "is_placeholder": bool(plan["is_placeholder"]),
            "status": sub["status"] if sub else "free", "current_period_end": sub["current_period_end"] if sub else None,
            "cancel_at_period_end": bool(sub["cancel_at_period_end"]) if sub else False, "invoices": invs}
