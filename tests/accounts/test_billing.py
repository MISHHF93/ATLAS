import json
import time

import pytest

from atlas.accounts import audit, billing, db, entitlements, stripe_client
from atlas.accounts.stripe_client import StripeError

from .conftest import PW, mkuser, signup

SECRET = "whsec_testsecret0123456789"


def _event(uid, etype="checkout.session.completed", eid="evt_1", plan="pro", **extra):
    obj = {"client_reference_id": uid, "mode": "subscription", "payment_status": "paid", "customer": "cus_1", "subscription": "sub_1",
           "metadata": {"user_id": uid, "plan_code": plan}}
    obj.update(extra)
    return {"id": eid, "type": etype, "livemode": False, "data": {"object": obj}}


def _signed(ev, ts=None, secret=SECRET):
    body = json.dumps(ev).encode()
    return body, stripe_client.sign(body, secret, ts)


# ---- schema / seed ----
def test_billing_tables_and_seed(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"plans", "plan_entitlements", "subscriptions", "usage_events", "invoices", "partner_referrals"} <= names
    rows = conn.execute("SELECT code,is_placeholder,price_cents FROM plans ORDER BY sort").fetchall()
    assert [r["code"] for r in rows] == ["free", "pro", "team"] and all(r["is_placeholder"] == 1 for r in rows)


def test_no_commission_columns_anywhere(conn):
    cols = [r[1].lower() for t in ("plans", "plan_entitlements", "subscriptions", "usage_events", "invoices", "partner_referrals")
            for r in conn.execute(f"PRAGMA table_info({t})")]
    assert not [c for c in cols if "commission" in c or "per_trade" in c or "take_rate" in c or "spread" in c]


def test_plans_endpoint_flags_placeholder_and_no_commission(client):
    j = client.get("/api/billing/plans").json()
    assert j["placeholder"] is True and j["per_trade_commission"] is False and len(j["plans"]) == 3


def test_seed_is_idempotent_and_keeps_operator_edits(conn):
    conn.execute("UPDATE plans SET price_cents=777 WHERE code='pro'")
    billing.seed_plans(conn)
    assert conn.execute("SELECT price_cents FROM plans WHERE code='pro'").fetchone()[0] == 777


# ---- entitlement gating ----
def test_free_quota_connectors_max(client):
    h = signup(client)
    ok = 0
    for cid in ("tiingo", "finnhub", "twelvedata", "alphavantage"):
        r = client.post(f"/api/account/connectors/{cid}/save", json={"values": {"api_key": "k" * 20}}, headers=h)
        ok += r.status_code == 200
    assert ok == 4
    r = client.post("/api/account/connectors/fmp/save", json={"values": {"api_key": "k" * 20}}, headers=h)
    assert r.status_code == 402 and r.json()["key"] == "connectors.max" and r.json()["plan"] == "free"
    # updating an existing connector is not a new slot
    assert client.post("/api/account/connectors/tiingo/save", json={"values": {"api_key": "n" * 20}}, headers=h).status_code == 200


def test_alert_channel_quota(client):
    h = signup(client)
    assert client.post("/api/account/connectors/telegram/save", json={"values": {"bot_token": "123456789:" + "A" * 35, "chat_id": "123456789"}}, headers=h).status_code == 200
    r = client.post("/api/account/connectors/ntfy/save", json={"values": {"topic": "atlas-alerts-topic-1"}}, headers=h)
    assert r.status_code == 402 and r.json()["key"] == "alerts.channels.max"


def test_feature_flag_gates_lab_route(client):
    signup(client)
    r = client.get("/api/intel/lab/runs")
    assert r.status_code == 402 and r.json()["key"] == "feature.research_lab"


def test_pro_plan_unlocks_feature_after_verified_webhook(client, monkeypatch, acct_env):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    signup(client)
    uid = client.get("/api/account/me").json()["user"]["id"]
    body, sig = _signed(_event(uid))
    r = client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert r.status_code == 200
    assert client.get("/api/billing/subscription").json()["plan"] == "pro"
    assert client.get("/api/intel/lab/runs").status_code != 402


def test_owner_and_admin_bypass(conn):
    o = mkuser(conn, "boss@example.com", env={"ATLAS_OWNER_EMAIL": "boss@example.com"})
    assert entitlements.enforce(conn, o.id, "owner", "feature.research_lab")["bypass"]
    u = mkuser(conn, "u@example.com")
    with pytest.raises(entitlements.EntitlementDenied):
        entitlements.enforce(conn, u.id, "user", "feature.research_lab")


def test_unknown_key_denied_and_period_metering(conn):
    u = mkuser(conn)
    with pytest.raises(entitlements.EntitlementDenied) as e:
        entitlements.enforce(conn, u.id, "user", "feature.does_not_exist")
    assert e.value.reason == "not_in_plan"
    for _ in range(20):
        entitlements.enforce(conn, u.id, "user", "connector_tests.daily", record=True)
    with pytest.raises(entitlements.EntitlementDenied):
        entitlements.enforce(conn, u.id, "user", "connector_tests.daily", record=True)
    # next UTC day the window resets
    entitlements.enforce(conn, u.id, "user", "connector_tests.daily", record=True, now=time.time() + 90000)


def test_canceled_subscription_falls_back_to_free(conn):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _event(u.id))
    assert billing.plan_for_user(conn, u.id)["code"] == "pro"
    stripe_client.handle_event(conn, {"id": "evt_2", "type": "customer.subscription.deleted", "livemode": False,
                                      "data": {"object": {"id": "sub_1", "metadata": {"user_id": u.id}}}})
    assert billing.plan_for_user(conn, u.id)["code"] == "free"


# ---- webhook signature ----
def test_webhook_valid_signature_accepted(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    body, sig = _signed(_event("nouser", "ping.unknown", "evt_ok"))
    assert client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig}).status_code == 200


@pytest.mark.parametrize("mut", ["no_header", "garbage", "wrong_secret", "tampered_body", "stale", "future", "no_v1"])
def test_webhook_rejects_bad_signatures(client, monkeypatch, mut):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    ev = _event("u1", eid="evt_bad")
    body, sig = _signed(ev)
    headers = {"stripe-signature": sig}
    if mut == "no_header":
        headers = {}
    elif mut == "garbage":
        headers = {"stripe-signature": "hello"}
    elif mut == "wrong_secret":
        body, sig = _signed(ev, secret="whsec_other")
        headers = {"stripe-signature": sig}
    elif mut == "tampered_body":
        body = body.replace(b"pro", b"team")
    elif mut == "stale":
        body, sig = _signed(ev, ts=int(time.time()) - 3600)
        headers = {"stripe-signature": sig}
    elif mut == "future":
        body, sig = _signed(ev, ts=int(time.time()) + 3600)
        headers = {"stripe-signature": sig}
    elif mut == "no_v1":
        headers = {"stripe-signature": f"t={int(time.time())}"}
    r = client.post("/api/billing/webhook", content=body, headers=headers)
    assert r.status_code == 400, r.text
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0] == 0


def test_webhook_not_configured_is_503_not_open(client):
    body, sig = _signed(_event("u1"))
    assert client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig}).status_code == 503


def test_webhook_signature_unit_constant_time_api():
    body = b'{"a":1}'
    h = stripe_client.sign(body, SECRET)
    stripe_client.verify_signature(body, h, SECRET)
    with pytest.raises(StripeError):
        stripe_client.verify_signature(body, h, "")
    with pytest.raises(StripeError):
        stripe_client.verify_signature(body + b" ", h, SECRET)


def test_webhook_exempt_from_csrf_and_session(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ATLAS_REQUIRE_AUTH", "true")
    body, sig = _signed(_event("nouser", "ping.unknown", "evt_x"))
    assert client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig}).status_code == 200


def test_webhook_idempotent(conn):
    u = mkuser(conn)
    ev = _event(u.id)
    assert stripe_client.handle_event(conn, ev) == "processed"
    assert stripe_client.handle_event(conn, ev) == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (u.id,)).fetchone()[0] == 1


def test_livemode_event_refused(conn):
    ev = _event("u1")
    ev["livemode"] = True
    with pytest.raises(StripeError):
        stripe_client.handle_event(conn, ev)


def test_webhook_cannot_touch_other_users_subscription(conn):
    a, b = mkuser(conn, "a@example.com"), mkuser(conn, "b@example.com")
    stripe_client.handle_event(conn, _event(a.id, plan="pro"))
    stripe_client.handle_event(conn, {"id": "evt_d", "type": "customer.subscription.deleted", "livemode": False,
                                      "data": {"object": {"id": "sub_1", "metadata": {"user_id": b.id}}}})
    assert billing.plan_for_user(conn, a.id)["code"] == "pro"


def test_referral_pending_then_qualified_without_payout(conn):
    a = mkuser(conn, "a@example.com")
    b = mkuser(conn, "b@example.com", ref=a.referral_code)
    r = conn.execute("SELECT status, reward_cents FROM partner_referrals WHERE referred_user_id=?", (b.id,)).fetchone()
    assert r["status"] == "pending"
    stripe_client.handle_event(conn, {"id": "evt_i", "type": "invoice.paid", "livemode": False,
                                      "data": {"object": {"id": "in_1", "customer": "cus_1", "subscription": "sub_1", "amount_paid": 1900, "amount_due": 1900,
                                                          "metadata": {"user_id": b.id}, "client_reference_id": b.id}}})
    r = conn.execute("SELECT status, reward_cents FROM partner_referrals WHERE referred_user_id=?", (b.id,)).fetchone()
    assert r["reward_cents"] == 0


# ---- checkout (stripe mocked) ----
class _R:
    status_code = 200

    def __init__(self, live=False):
        self.live = live

    def json(self):
        return {"url": "https://checkout.stripe.com/c/test_1", "id": "cs_test_1", "livemode": self.live}


def test_checkout_refuses_live_key_and_missing_key(client, monkeypatch):
    h = signup(client)
    assert client.post("/api/billing/checkout", json={"plan": "pro"}, headers=h).status_code == 503
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_" + "x" * 24)
    r = client.post("/api/billing/checkout", json={"plan": "pro"}, headers=h)
    assert r.status_code == 503 and "sk_live" not in r.text
    assert client.post("/api/billing/checkout", json={"plan": "nope"}, headers=h).status_code == 404


def test_checkout_builds_test_session_with_user_metadata(conn, monkeypatch):
    u = mkuser(conn)
    plan = conn.execute("SELECT * FROM plans WHERE code='pro'").fetchone()
    cap = {}

    def post(url, data=None, headers=None):
        cap.update(url=url, data=data, headers=headers)
        return _R()
    out = stripe_client.create_checkout_session(u.public(), plan, env={"STRIPE_SECRET_KEY": "sk_test_abc123"}, post=post)
    assert out["url"].startswith("https://checkout.stripe.com") and cap["data"]["metadata[user_id]"] == u.id
    assert "TEST MODE" in cap["data"]["line_items[0][price_data][product_data][name]"] and cap["data"]["mode"] == "subscription"
    with pytest.raises(StripeError):
        stripe_client.create_checkout_session(u.public(), plan, env={"STRIPE_SECRET_KEY": "sk_test_abc123"}, post=lambda *a, **k: _R(live=True))
    free = conn.execute("SELECT * FROM plans WHERE code='free'").fetchone()
    with pytest.raises(StripeError):
        stripe_client.create_checkout_session(u.public(), free, env={"STRIPE_SECRET_KEY": "sk_test_abc123"}, post=post)


def test_checkout_requires_login(client):
    assert client.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 401
