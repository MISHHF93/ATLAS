"""Plans, entitlements seed and subscription lookup.

NO PER-TRADE FEES AND NO PERFORMANCE FEE, EVER: ATLAS is paper-only, never touches client funds and takes no cut of any trade or profit.
Revenue is flat subscriptions (plan_entitlements gate features and quotas), plus an OPTIONAL fixed-bounty broker referral that stays
switched off until counsel approves it (brokers.py). See docs/atlas/monetization.md and docs-research/monetization_plan.md.

TODO(pricing): every plan below is a PLACEHOLDER seeded from monetization_plan.md section 2 (USD/CAD, monthly/yearly). Prices are
configurable data: edit the ``plans`` rows (admin endpoint ``POST /api/admin/plans/update``), set is_placeholder=0 once approved, and
complete the legal review before any live Stripe key is ever used. Seeding never overwrites rows an operator has edited.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

FEES = {"per_trade_fee_cents": 0, "performance_fee": False}  # published with every plan listing; there is no code path to change it
INTERVALS = ("month", "year")
CURRENCIES = ("usd", "cad")
TIERS = ("free", "pro", "team")

# key -> (kind, free, pro, team, period). quota None = unlimited. flags are booleans. Values are PROPOSALS (monetization_plan.md section 2).
ENTITLEMENT_KEYS: dict[str, tuple[str, Any, Any, Any, str]] = {
    # enforced today
    "connectors.max":          ("quota", 4, 12, 25, "none"),     # saved connectors in the library
    "connector_tests.daily":   ("quota", 20, 200, 1000, "day"),  # outbound connection tests per UTC day
    "alerts.channels.max":     ("quota", 1, 3, 5, "none"),       # alert-category connectors (Telegram / Discord / ntfy)
    "feature.research_lab":    ("flag", False, True, True, "none"),
    "feature.team_workspace":  ("flag", False, False, True, "none"),
    # seeded from the pricing plan; features not built yet, enforced as each ships
    "seats":                   ("quota", 1, 1, 5, "none"),
    "broker.connections":      ("quota", 1, 3, 10, "none"),
    "strategies.active":       ("quota", 3, 15, 50, "none"),
    "watchlist.symbols":       ("quota", 20, 100, 500, "none"),
    "ai.queries":              ("quota", 10, 300, 1500, "month"),
    "alerts.active":           ("quota", 5, 100, 500, "none"),
    "backtests.runs":          ("quota", 10, 200, 1000, "month"),
    "history.days":            ("quota", 90, 1825, 3650, "none"),
    "webhooks":                ("flag", False, True, True, "none"),
    "api.access":              ("flag", False, False, True, "none"),  # Pro gets it as a paid add-on (not built)
    "audit.export":            ("flag", False, False, True, "none"),
    "live_order_routing":      ("flag", False, False, False, "none"),  # OFF for every tier until counsel signs off in writing. Never bypassed.
}
# (tier, interval, currency) -> price in minor units. PLACEHOLDERS. Annual = 10 x monthly (two months free).
PRICES: dict[tuple[str, str, str], int] = {
    ("pro", "month", "usd"): 2900, ("pro", "year", "usd"): 29000, ("pro", "month", "cad"): 3900, ("pro", "year", "cad"): 39000,
    ("team", "month", "usd"): 9900, ("team", "year", "usd"): 99000, ("team", "month", "cad"): 13500, ("team", "year", "cad"): 135000,
}
EXTRA_SEAT_MONTH = {"usd": 1500, "cad": 2000}  # Team extra seat per month; yearly = 10 x
TEAM_SEATS = 5
MAX_SEATS = 100
ADDONS = (  # informational placeholders (not purchasable yet)
    {"code": "ai_pack_500", "name": "AI query pack, 500 queries", "usd": 900, "cad": 1200},
    {"code": "extra_broker_connection", "name": "Extra broker connection (per month)", "usd": 500, "cad": 700},
    {"code": "api_access_pro", "name": "API access on Pro (per month)", "usd": 4900, "cad": 6900},
)
ACTIVE_STATUSES = ("active", "trialing")
# (code, name, program_type, terms_url) partner programmes. ALL seeded not_approved + inactive until counsel approves (monetization_plan.md 3.5).
BROKER_PARTNERS = (
    ("oanda", "OANDA", "cpa", "https://partners.oanda.com/en/partner-programmes/"),
    ("ibkr", "Interactive Brokers", "cpa", "https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/"),
    ("alpaca", "Alpaca", "pfof_share", "https://alpaca.markets/trading-api"),
)


def plan_code(tier: str, interval: str, currency: str) -> str:
    return "free" if tier == "free" else f"{tier}_{interval}_{currency}"


def _variants() -> list[tuple[str, str, str, str, int, int, int, int]]:
    """(code, tier, interval, currency, price_cents, extra_seat_cents, seats_included, sort)"""
    out = [("free", "free", "month", "usd", 0, 0, 1, 0)]
    for ti, tier in ((1, "pro"), (2, "team")):
        for ii, interval in enumerate(INTERVALS):
            for ci, cur in enumerate(CURRENCIES):
                seat = (EXTRA_SEAT_MONTH[cur] * (10 if interval == "year" else 1)) if tier == "team" else 0
                out.append((plan_code(tier, interval, cur), tier, interval, cur, PRICES[(tier, interval, cur)], seat,
                            TEAM_SEATS if tier == "team" else 1, ti * 10 + ii * 2 + ci))
    return out


def _desc(tier: str) -> str:
    return {"free": "PLACEHOLDER plan. Paper trading research with a small connector allowance.",
            "pro": "PLACEHOLDER plan. Individual trader or researcher: more connectors, research lab, webhooks. Price is a placeholder, not an offer.",
            "team": "PLACEHOLDER plan. Small desk or club: 5 seats included, extra seats billed per seat. Team workspace is reserved (not built yet). Price is a placeholder, not an offer."}[tier]


def seed_plans(conn: sqlite3.Connection) -> None:
    """Idempotent. Inserts missing plans / entitlements / broker partners only, so operator edits to existing rows are never overwritten."""
    now = int(time.time())
    conn.execute("BEGIN IMMEDIATE")
    try:
        idx = {"free": 1, "pro": 2, "team": 3}
        for code, tier, interval, cur, cents, seat, seats_inc, sort in _variants():
            row = conn.execute("SELECT id FROM plans WHERE code=?", (code,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO plans (id,code,name,description,price_cents,currency,billing_interval,is_placeholder,active,sort,created_at,tier,seats_included,extra_seat_cents)"
                             " VALUES (?,?,?,?,?,?,?,1,1,?,?,?,?,?)",
                             (f"plan_{code}", code, tier.capitalize(), _desc(tier), cents, cur, interval, sort, now, tier, seats_inc, seat))
                pid = f"plan_{code}"
            else:
                pid = row["id"]
            for key, spec in ENTITLEMENT_KEYS.items():
                kind, period, v = spec[0], spec[4], spec[idx[tier]]
                conn.execute("INSERT OR IGNORE INTO plan_entitlements (plan_id,key,kind,bool_value,int_value,period) VALUES (?,?,?,?,?,?)",
                             (pid, key, kind, (1 if v else 0) if kind == "flag" else None, v if kind == "quota" else None, period))
        for code, name, ptype, url in BROKER_PARTNERS:
            conn.execute("INSERT OR IGNORE INTO broker_partners (id,code,name,program_type,legal_status,terms_url,active,created_at) VALUES (?,?,?,?,'not_approved',?,0,?)",
                         (f"bp_{code}", code, name, ptype, url, now))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def resolve_plan(conn: sqlite3.Connection, plan: str, interval: str | None = None, currency: str | None = None) -> sqlite3.Row | None:
    """``plan`` is either an exact plan code (``pro_year_cad``) or a tier (``pro``) combined with interval and currency."""
    plan = (plan or "").strip().lower()
    row = conn.execute("SELECT * FROM plans WHERE code=? AND active=1", (plan,)).fetchone()
    if row is not None:
        return row
    if plan in ("pro", "team"):
        iv, cur = (interval or "month").lower(), (currency or "usd").lower()
        if iv in INTERVALS and cur in CURRENCIES:
            return conn.execute("SELECT * FROM plans WHERE code=? AND active=1", (plan_code(plan, iv, cur),)).fetchone()
    return None


def plans_public(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    out = []
    for p in conn.execute("SELECT * FROM plans WHERE active=1 ORDER BY sort"):
        ents = {e["key"]: ({"kind": "flag", "value": bool(e["bool_value"])} if e["kind"] == "flag"
                           else {"kind": "quota", "limit": e["int_value"], "period": e["period"]})
                for e in conn.execute("SELECT * FROM plan_entitlements WHERE plan_id=?", (p["id"],))}
        out.append({"code": p["code"], "tier": p["tier"], "name": p["name"], "description": p["description"], "price_cents": p["price_cents"],
                    "currency": p["currency"], "interval": p["billing_interval"], "seats_included": p["seats_included"],
                    "extra_seat_cents": p["extra_seat_cents"], "tax_behavior": p["tax_behavior"],
                    "is_placeholder": bool(p["is_placeholder"]), "entitlements": ents})
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
    return {"plan": plan["code"], "tier": plan["tier"], "plan_name": plan["name"], "is_placeholder": bool(plan["is_placeholder"]),
            "interval": plan["billing_interval"], "currency": plan["currency"], "seats": int(sub["seats"]) if sub else 1,
            "status": sub["status"] if sub else "free", "current_period_end": sub["current_period_end"] if sub else None,
            "cancel_at_period_end": bool(sub["cancel_at_period_end"]) if sub else False, "invoices": invs}
