"""Stripe, TEST MODE ONLY. No SDK: one form-encoded POST for Checkout and an HMAC verifier for webhooks.

* ``STRIPE_SECRET_KEY`` must start with ``sk_test_`` (anything else is refused, including ``sk_live_`` and restricted live keys).
* Webhooks are accepted only with a valid ``Stripe-Signature`` (HMAC-SHA256 of ``t.payload`` with ``STRIPE_WEBHOOK_SECRET``,
  300 s tolerance, constant-time compare) and events with ``livemode: true`` are rejected.
* The subscription row is created ONLY from a verified webhook, never from the browser returning from Checkout.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from . import audit
from .db import tx

TOLERANCE_S = 300
API = "https://api.stripe.com/v1"


class StripeError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _env(env, k):
    return ((env if env is not None else os.environ).get(k) or "").strip()


def configured(env=None) -> dict[str, bool]:
    return {"secret_key": _env(env, "STRIPE_SECRET_KEY").startswith("sk_test_"), "webhook_secret": _env(env, "STRIPE_WEBHOOK_SECRET").startswith("whsec_")}


def test_key(env=None) -> str:
    k = _env(env, "STRIPE_SECRET_KEY")
    if not k:
        raise StripeError("stripe_not_configured", 503)
    if not k.startswith("sk_test_"):
        raise StripeError("stripe_live_key_refused: ATLAS only accepts a Stripe TEST-mode secret key (sk_test_…)", 503)
    return k


def public_base(env=None) -> str:
    u = _env(env, "ATLAS_PUBLIC_URL") or "http://localhost:3000"
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or (p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1")):
        raise StripeError("bad_public_url", 500)
    return u.rstrip("/")


def create_checkout_session(user: dict[str, Any], plan: sqlite3.Row, env=None, post: Callable | None = None) -> dict[str, str]:
    if plan["price_cents"] <= 0 and not plan["stripe_price_id"]:
        raise StripeError("plan_not_purchasable", 400)
    key = test_key(env)
    base = public_base(env)
    form = {"mode": "subscription", "client_reference_id": user["id"], "customer_email": user["email"],
            "success_url": f"{base}/settings?tab=billing&checkout=success", "cancel_url": f"{base}/settings?tab=billing&checkout=cancel",
            "metadata[user_id]": user["id"], "metadata[plan_code]": plan["code"],
            "subscription_data[metadata][user_id]": user["id"], "subscription_data[metadata][plan_code]": plan["code"], "line_items[0][quantity]": "1"}
    if plan["stripe_price_id"]:
        form["line_items[0][price]"] = plan["stripe_price_id"]
    else:  # placeholder plan: inline test price so a test-mode demo needs no dashboard setup
        form.update({"line_items[0][price_data][currency]": plan["currency"], "line_items[0][price_data][unit_amount]": str(plan["price_cents"]),
                     "line_items[0][price_data][recurring][interval]": plan["billing_interval"],
                     "line_items[0][price_data][product_data][name]": f"ATLAS {plan['name']} (TEST MODE, placeholder price)"})
    poster = post or (lambda u, **kw: httpx.post(u, timeout=15, follow_redirects=False, **kw))
    r = poster(API + "/checkout/sessions", data=form, headers={"Authorization": "Bearer " + key, "Idempotency-Key": uuid.uuid4().hex})
    if r.status_code != 200:
        raise StripeError("stripe_error", 502)
    js = r.json()
    if js.get("livemode"):
        raise StripeError("stripe_live_session_refused", 502)
    return {"url": js["url"], "id": js["id"]}


# ---------------- webhook ----------------
def sign(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Test helper and reference: builds the header Stripe would send."""
    ts = int(time.time() if ts is None else ts)
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(payload: bytes, header: str | None, secret: str, now: float | None = None, tolerance: int = TOLERANCE_S) -> None:
    if not secret:
        raise StripeError("webhook_not_configured", 503)
    if not header:
        raise StripeError("bad_signature", 400)
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    ts_s = next((v for k, v in parts if k.strip() == "t"), None)
    sigs = [v.strip() for k, v in parts if k.strip() == "v1"]
    try:
        ts = int(ts_s or "")
    except ValueError as ex:
        raise StripeError("bad_signature", 400) from ex
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise StripeError("bad_signature", 400)
    if abs((time.time() if now is None else now) - ts) > tolerance:
        raise StripeError("stale_signature", 400)


def _period(obj: dict[str, Any]) -> tuple[int | None, int | None]:
    item = ((obj.get("items") or {}).get("data") or [{}])[0]
    return (obj.get("current_period_start") or item.get("current_period_start"), obj.get("current_period_end") or item.get("current_period_end"))


def _plan_id(conn, code: str | None):
    r = conn.execute("SELECT id FROM plans WHERE code=? AND active=1", (code or "",)).fetchone()
    return r["id"] if r else None


def _upsert_sub(conn, user_id, plan_id, status, customer, sub_id, ps, pe, cancel, now):
    if sub_id:
        cur = conn.execute("UPDATE subscriptions SET status=?, plan_id=COALESCE(?,plan_id), stripe_customer_id=COALESCE(?,stripe_customer_id),"
                           " current_period_start=COALESCE(?,current_period_start), current_period_end=COALESCE(?,current_period_end), cancel_at_period_end=?, updated_at=?"
                           " WHERE stripe_subscription_id=? AND user_id=?", (status, plan_id, customer, ps, pe, int(bool(cancel)), now, sub_id, user_id))
        if cur.rowcount:
            return
    if not plan_id:
        return
    conn.execute("INSERT INTO subscriptions (id,user_id,plan_id,status,stripe_customer_id,stripe_subscription_id,current_period_start,current_period_end,cancel_at_period_end,created_at,updated_at)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, user_id, plan_id, status, customer, sub_id, ps, pe, int(bool(cancel)), now, now))


def _user_for(conn, obj: dict[str, Any]) -> str | None:
    md = obj.get("metadata") or {}
    uid = md.get("user_id") or obj.get("client_reference_id")
    if uid and conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        return uid
    for col, v in (("stripe_subscription_id", obj.get("subscription") or (obj.get("id") if str(obj.get("object")) == "subscription" else None)),
                   ("stripe_customer_id", obj.get("customer"))):
        if v:
            r = conn.execute(f"SELECT user_id FROM subscriptions WHERE {col}=? ORDER BY updated_at DESC LIMIT 1", (v,)).fetchone()
            if r:
                return r["user_id"]
    return None


def _qualify_referral(conn, user_id: str, now: int) -> None:
    # TODO(referrals): reward_cents stays 0 until the partner programme terms are decided and legally reviewed. No payouts are made.
    conn.execute("UPDATE partner_referrals SET status='qualified', qualified_at=? WHERE referred_user_id=? AND status='pending'", (now, user_id))


def handle_event(conn: sqlite3.Connection, event: dict[str, Any], now: float | None = None) -> str:
    """Apply one VERIFIED event. Idempotent on event id. Returns 'processed' | 'duplicate' | 'ignored'."""
    now_i = int(time.time() if now is None else now)
    if event.get("livemode"):
        raise StripeError("livemode_event_refused", 400)
    eid, etype = str(event.get("id") or ""), str(event.get("type") or "")
    if not eid:
        raise StripeError("bad_event", 400)
    obj = (event.get("data") or {}).get("object") or {}
    result = "ignored"
    with tx(conn):
        if conn.execute("INSERT OR IGNORE INTO stripe_events (event_id,type,livemode,received_at) VALUES (?,?,0,?)", (eid, etype, now_i)).rowcount == 0:
            return "duplicate"
        uid = _user_for(conn, obj)
        if etype == "checkout.session.completed" and uid and obj.get("mode") == "subscription":
            if obj.get("payment_status") in ("paid", "no_payment_required"):
                _upsert_sub(conn, uid, _plan_id(conn, (obj.get("metadata") or {}).get("plan_code")), "active", obj.get("customer"), obj.get("subscription"), None, None, False, now_i)
                result = "processed"
        elif etype in ("customer.subscription.created", "customer.subscription.updated") and uid:
            ps, pe = _period(obj)
            _upsert_sub(conn, uid, _plan_id(conn, (obj.get("metadata") or {}).get("plan_code")), str(obj.get("status") or "incomplete"), obj.get("customer"), obj.get("id"), ps, pe, obj.get("cancel_at_period_end"), now_i)
            result = "processed"
        elif etype == "customer.subscription.deleted" and uid:
            conn.execute("UPDATE subscriptions SET status='canceled', updated_at=? WHERE stripe_subscription_id=? AND user_id=?", (now_i, obj.get("id"), uid))
            result = "processed"
        elif etype in ("invoice.paid", "invoice.payment_failed", "invoice.finalized", "invoice.created", "invoice.voided") and uid and obj.get("id"):
            conn.execute("INSERT INTO invoices (id,user_id,stripe_invoice_id,subscription_id,status,currency,amount_due,amount_paid,hosted_invoice_url,period_start,period_end,created_at,mirrored_at)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(stripe_invoice_id) DO UPDATE SET status=excluded.status, amount_due=excluded.amount_due,"
                         " amount_paid=excluded.amount_paid, hosted_invoice_url=excluded.hosted_invoice_url, mirrored_at=excluded.mirrored_at WHERE invoices.user_id=excluded.user_id",
                         (uuid.uuid4().hex, uid, obj["id"], obj.get("subscription"), str(obj.get("status") or etype.split(".")[1]), obj.get("currency") or "usd",
                          int(obj.get("amount_due") or 0), int(obj.get("amount_paid") or 0), obj.get("hosted_invoice_url"), obj.get("period_start"), obj.get("period_end"),
                          int(obj.get("created") or now_i), now_i))
            if etype == "invoice.paid" and int(obj.get("amount_paid") or 0) > 0:
                _qualify_referral(conn, uid, now_i)
            result = "processed"
        conn.execute("UPDATE stripe_events SET processed_at=? WHERE event_id=?", (now_i, eid))
        audit.log(conn, uid, "billing.webhook", "stripe_event", eid, outcome=result, detail={"type": etype}, now=now_i)
    return result


def process_webhook(conn, payload: bytes, header: str | None, env=None, now: float | None = None) -> str:
    verify_signature(payload, header, _env(env, "STRIPE_WEBHOOK_SECRET"), now)
    try:
        event = json.loads(payload)
    except ValueError as ex:
        raise StripeError("bad_event", 400) from ex
    return handle_event(conn, event, now)
