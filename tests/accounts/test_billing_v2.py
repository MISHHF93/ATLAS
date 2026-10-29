"""M0005: priced plans (USD/CAD, monthly/yearly, seats), tax records, broker partners, hash-chained payouts ledger, Flooos export."""
import json
import sqlite3
import time
from urllib.parse import parse_qs

import pytest

from atlas.accounts import audit, auth, billing, brokers, db, entitlements, flooos, ledger, migrations, stripe_client
from atlas.accounts.stripe_client import StripeError

from .conftest import PW, mkuser, signup
from .test_billing import SECRET, _event, _signed

PRICES = {"pro_month_usd": 2900, "pro_month_cad": 3900, "pro_year_usd": 29000, "pro_year_cad": 39000,
          "team_month_usd": 9900, "team_month_cad": 13500, "team_year_usd": 99000, "team_year_cad": 135000}


# ---- migration / seed ----
def test_seed_prices_seats_and_extra_seats(conn):
    got = {r["code"]: r for r in conn.execute("SELECT * FROM plans")}
    assert set(got) == set(PRICES) | {"free"}
    for code, cents in PRICES.items():
        assert got[code]["price_cents"] == cents and got[code]["is_placeholder"] == 1
    assert got["free"]["price_cents"] == 0
    assert got["team_month_usd"]["seats_included"] == 5 and got["team_month_usd"]["extra_seat_cents"] == 1500
    assert got["team_month_cad"]["extra_seat_cents"] == 2000
    assert got["team_year_usd"]["extra_seat_cents"] == 15000 and got["pro_month_usd"]["seats_included"] == 1
    assert {r["tax_behavior"] for r in got.values()} == {"exclusive"}
    assert got["pro_year_cad"]["billing_interval"] == "year" and got["pro_year_cad"]["currency"] == "cad"


def test_upgrade_from_m0004_renames_legacy_plans_and_keeps_subscriptions(tmp_path):
    c = sqlite3.connect(tmp_path / "x.sqlite", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    old = [m for m in migrations.MIGRATIONS if m[0] <= 4]
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at BIGINT NOT NULL)")
    for v, n, sql in old:
        c.executescript("BEGIN;\n" + sql + f"\nINSERT INTO schema_migrations VALUES ({v},'{n}',1);\nCOMMIT;")
    c.execute("INSERT INTO plans (id,code,name,price_cents,is_placeholder,sort,created_at) VALUES ('plan_pro','pro','Pro',1900,1,10,1)")
    c.execute("INSERT INTO plans (id,code,name,price_cents,is_placeholder,sort,created_at) VALUES ('plan_team','team','Team',4900,0,20,1)")
    billing_pre = c.execute("SELECT id FROM plans WHERE code='pro'").fetchone()
    c.execute("INSERT INTO users (id,email,created_at,updated_at) VALUES ('u1','a@b.co',1,1)")
    c.execute("INSERT INTO subscriptions (id,user_id,plan_id,status,created_at,updated_at) VALUES ('s1','u1',?,'active',1,1)", (billing_pre["id"],))
    assert db.migrate(c) == [5]
    billing.seed_plans(c)
    r = c.execute("SELECT p.code, p.price_cents, p.tier FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.id='s1'").fetchone()
    assert (r["code"], r["tier"], r["price_cents"]) == ("pro_month_usd", "pro", 2900)
    assert c.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 10 - 1  # free + 8 variants; legacy team renamed to team_month_usd
    assert c.execute("SELECT price_cents FROM plans WHERE code='team_month_usd'").fetchone()[0] == 4900  # operator-edited price is kept
    assert c.execute("SELECT id FROM plans WHERE code='pro_month_usd'").fetchone()[0] == "plan_pro"  # id preserved for FK stability
    assert db.migrate(c) == []


def test_seed_idempotent_never_overwrites_operator_price(conn):
    conn.execute("UPDATE plans SET price_cents=3100, is_placeholder=0 WHERE code='pro_month_usd'")
    billing.seed_plans(conn)
    billing.seed_plans(conn)
    r = conn.execute("SELECT price_cents FROM plans WHERE code='pro_month_usd'").fetchone()
    assert r[0] == 3100 and conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM plan_entitlements WHERE plan_id=(SELECT id FROM plans WHERE code='pro_month_usd') AND key='seats'").fetchone()[0] == 1


def test_live_order_routing_off_for_every_plan_and_never_bypassed(conn):
    for r in conn.execute("SELECT p.code, e.bool_value FROM plan_entitlements e JOIN plans p ON p.id=e.plan_id WHERE e.key='live_order_routing'"):
        assert r["bool_value"] == 0, r["code"]
    owner = mkuser(conn, "o@example.com")
    conn.execute("UPDATE users SET role='owner' WHERE id=?", (owner.id,))
    with pytest.raises(entitlements.EntitlementDenied):
        entitlements.enforce(conn, owner.id, "owner", "live_order_routing")
    assert "live_order_routing" in entitlements.NEVER_BYPASS


def test_no_fee_columns_and_plans_api_reports_zero_fees(client, conn):
    cols = [r[1].lower() for t in ("plans", "plan_entitlements", "subscriptions", "usage_events", "invoices", "payouts_ledger", "broker_referrals")
            for r in conn.execute(f"PRAGMA table_info({t})")]
    assert not [c for c in cols if "per_trade" in c or "commission" in c or "performance" in c or "take_rate" in c]
    j = client.get("/api/billing/plans").json()
    assert j["fees"]["per_trade_fee_cents"] == 0 and j["fees"]["performance_fee"] is False and j["prices_exclude_tax"] is True
    assert {p["code"] for p in j["plans"]} == set(PRICES) | {"free"}


def test_resolve_plan(conn):
    assert billing.resolve_plan(conn, "team", "year", "cad")["code"] == "team_year_cad"
    assert billing.resolve_plan(conn, "pro")["code"] == "pro_month_usd"
    assert billing.resolve_plan(conn, "pro", "week", "usd") is None and billing.resolve_plan(conn, "gold") is None
    assert billing.resolve_plan(conn, "pro_year_usd")["price_cents"] == 29000


# ---- checkout: seats + tax hooks ----
class _R:
    status_code = 200

    def json(self):
        return {"url": "https://checkout.stripe.com/c/test_1", "id": "cs_test_1", "livemode": False}


def _checkout(conn, code, seats=None, env=None):
    u = mkuser(conn, f"c{time.time_ns()}@example.com")
    plan = conn.execute("SELECT * FROM plans WHERE code=?", (code,)).fetchone()
    cap = {}

    def post(url, data=None, headers=None):
        cap["data"] = data
        return _R()
    stripe_client.create_checkout_session(u.public(), plan, env={"STRIPE_SECRET_KEY": "sk_test_abc123", **(env or {})}, post=post, seats=seats)
    return cap["data"]


def test_checkout_extra_seats_line_and_metadata(conn):
    d = _checkout(conn, "team_month_cad", seats=8)
    assert d["line_items[0][price_data][unit_amount]"] == "13500" and d["line_items[0][price_data][currency]"] == "cad"
    assert d["line_items[1][quantity]"] == "3" and d["line_items[1][price_data][unit_amount]"] == "2000"
    assert d["metadata[seats]"] == "8" and d["subscription_data[metadata][seats]"] == "8"
    assert d["line_items[0][price_data][tax_behavior]"] == "exclusive"
    d5 = _checkout(conn, "team_month_usd")
    assert "line_items[1][quantity]" not in d5 and d5["metadata[seats]"] == "5"


@pytest.mark.parametrize("code,seats", [("team_month_usd", 4), ("team_month_usd", 101), ("pro_month_usd", 2), ("team_month_usd", 0)])
def test_checkout_rejects_bad_seats(conn, code, seats):
    with pytest.raises(StripeError) as e:
        _checkout(conn, code, seats=seats)
    assert e.value.code == "bad_seats"


def test_checkout_stripe_tax_hooks_only_when_enabled(conn):
    off = _checkout(conn, "pro_month_usd")
    assert not any(k.startswith(("automatic_tax", "tax_id_collection")) for k in off)
    on = _checkout(conn, "pro_month_usd", env={"ATLAS_STRIPE_TAX": "1", "ATLAS_STRIPE_TAX_CODE": "txcd_10103001"})
    assert on["automatic_tax[enabled]"] == "true" and on["billing_address_collection"] == "required" and on["tax_id_collection[enabled]"] == "true"
    assert on["line_items[0][price_data][product_data][tax_code]"] == "txcd_10103001"


def test_checkout_api_accepts_tier_interval_currency(client, monkeypatch):
    h = signup(client)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc123")
    seen = {}

    def post(url, **kw):
        seen.update(kw["data"])
        return _R()
    monkeypatch.setattr(stripe_client.httpx, "post", post)
    r = client.post("/api/billing/checkout", json={"plan": "team", "interval": "year", "currency": "cad", "seats": 7}, headers=h)
    assert r.status_code == 200, r.text
    assert seen["metadata[plan_code]"] == "team_year_cad" and seen["line_items[1][quantity]"] == "2"
    assert client.post("/api/billing/checkout", json={"plan": "team", "seats": "7"}, headers=h).status_code == 400
    assert client.post("/api/billing/checkout", json={"plan": "pro", "interval": "week"}, headers=h).status_code == 404


# ---- webhook -> subscription seats, invoices, tax, ledger ----
def _inv(uid, eid="evt_i1", paid=3900, tax=507, **kw):
    obj = {"id": "in_1", "customer": "cus_1", "subscription": "sub_1", "status": "paid", "currency": "cad", "amount_due": paid, "amount_paid": paid,
           "subtotal": paid - tax, "tax": tax, "number": "ATLAS-0001", "charge": "ch_1", "created": 1_760_000_000,
           "customer_address": {"country": "CA", "state": "ON"}, "status_transitions": {"paid_at": 1_760_000_100},
           "total_taxes": [{"amount": tax, "taxable_amount": paid - tax, "tax_rate_details": {"tax_type": "hst", "percentage_decimal": "13.0", "state": "ON"}}],
           "metadata": {"user_id": uid}}
    obj.update(kw)
    return {"id": eid, "type": "invoice.paid", "livemode": False, "data": {"object": obj}}


def test_checkout_completed_stores_seats_and_currency(conn):
    u = mkuser(conn)
    ev = _event(u.id, plan="team_month_cad")
    ev["data"]["object"]["metadata"]["seats"] = "8"
    stripe_client.handle_event(conn, ev)
    s = billing.current_subscription(conn, u.id)
    assert s["seats"] == 8 and s["currency"] == "cad"
    assert billing.plan_for_user(conn, u.id)["code"] == "team_month_cad"
    assert billing.subscription_public(conn, u.id)["seats"] == 8


def test_invoice_mirror_and_tax_record(conn):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _inv(u.id))
    i = conn.execute("SELECT * FROM invoices").fetchone()
    assert (i["amount_subtotal"], i["amount_tax"], i["stripe_charge_id"], i["number"], i["paid_at"]) == (3393, 507, "ch_1", "ATLAS-0001", 1_760_000_100)
    t = conn.execute("SELECT * FROM tax_records").fetchall()
    assert len(t) == 1 and (t[0]["country"], t[0]["region"], t[0]["tax_type"], t[0]["rate_bps"], t[0]["tax_amount"], t[0]["status"]) == ("CA", "ON", "hst", 1300, 507, "collected")
    assert t[0]["filing_period"].endswith("Q4") and json.loads(t[0]["location_evidence_json"])["billing_address_country"] == "CA"
    # a replayed / re-sent invoice event with a new id does not duplicate tax rows
    stripe_client.handle_event(conn, _inv(u.id, eid="evt_i2"))
    assert conn.execute("SELECT COUNT(*) FROM tax_records").fetchone()[0] == 1 and conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1


def test_invoice_without_tax_makes_no_tax_record(conn):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _inv(u.id, tax=0, total_taxes=[]))
    assert conn.execute("SELECT COUNT(*) FROM tax_records").fetchone()[0] == 0


def test_invoice_cannot_overwrite_other_users_invoice(conn):
    a, b = mkuser(conn, "a@example.com"), mkuser(conn, "b@example.com")
    stripe_client.handle_event(conn, _inv(a.id))
    stripe_client.handle_event(conn, _inv(b.id, eid="evt_x", paid=1, tax=0, total_taxes=[]))
    r = conn.execute("SELECT user_id, amount_paid FROM invoices").fetchall()
    assert len(r) == 1 and r[0]["user_id"] == a.id and r[0]["amount_paid"] == 3900


def test_payout_refund_dispute_book_into_ledger_once(conn, client, monkeypatch):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _inv(u.id))
    payout = {"id": "evt_p", "type": "payout.paid", "livemode": False, "data": {"object": {"id": "po_1", "amount": 100000, "currency": "cad", "arrival_date": 1_760_100_000}}}
    refund = {"id": "evt_r", "type": "charge.refunded", "livemode": False, "data": {"object": {"id": "ch_1", "amount_refunded": 1000, "currency": "cad"}}}
    dispute = {"id": "evt_d", "type": "charge.dispute.created", "livemode": False, "data": {"object": {"id": "dp_1", "amount": 3900, "currency": "cad"}}}
    for ev in (payout, refund, dispute):
        stripe_client.handle_event(conn, ev)
        stripe_client.handle_event(conn, ev)  # replay
    kinds = [(r["kind"], r["direction"], r["amount_cents"]) for r in conn.execute("SELECT * FROM payouts_ledger ORDER BY seq")]
    assert kinds == [("stripe_payout", "in", 100000), ("refund", "out", 1000), ("chargeback", "out", 3900), ("dispute_fee", "out", 1500)]
    # a second refund event on the same charge books only the delta
    r2 = {"id": "evt_r2", "type": "charge.refunded", "livemode": False, "data": {"object": {"id": "ch_1", "amount_refunded": 2500, "currency": "cad"}}}
    stripe_client.handle_event(conn, r2)
    assert [x["amount_cents"] for x in conn.execute("SELECT amount_cents FROM payouts_ledger WHERE kind='refund' ORDER BY seq")] == [1000, 1500]
    assert ledger.verify_chain(conn) == {"ok": True, "rows": 5}


# ---- ledger ----
def test_ledger_chain_dedupe_and_validation(conn):
    a = ledger.append(conn, "adjustment", "in", 500, "usd", "ops", dedupe_key="k1", ts=100)
    assert a and ledger.append(conn, "adjustment", "in", 500, "usd", "ops", dedupe_key="k1") is None
    ledger.append(conn, "tax_remittance", "out", 70, "CAD", "cra", ts=200)
    assert ledger.verify_chain(conn) == {"ok": True, "rows": 2}
    for bad in (dict(kind="nope"), dict(direction="sideways"), dict(amount_cents=0), dict(amount_cents=-5), dict(amount_cents=1.5), dict(currency="dollars"), dict(counterparty=" ")):
        args = dict(kind="adjustment", direction="in", amount_cents=1, currency="usd", counterparty="x")
        args.update(bad)
        with pytest.raises(ledger.LedgerError):
            ledger.append(conn, args["kind"], args["direction"], args["amount_cents"], args["currency"], args["counterparty"])


def test_ledger_triggers_block_update_delete_and_chain_detects_tamper(conn):
    ledger.append(conn, "adjustment", "in", 500, "usd", "ops", ts=100)
    ledger.append(conn, "adjustment", "in", 700, "usd", "ops", ts=200)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE payouts_ledger SET amount_cents=1")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM payouts_ledger")
    # a privileged attacker who drops the trigger is still caught by the hash chain
    conn.execute("DROP TRIGGER payouts_ledger_no_update")
    conn.execute("UPDATE payouts_ledger SET amount_cents=1 WHERE seq=1")
    assert ledger.verify_chain(conn) == {"ok": False, "broken_at_seq": 1, "rows": 0}


def test_mark_exported_only_once_and_hash_unchanged(conn):
    ledger.append(conn, "adjustment", "in", 500, "usd", "ops", ts=100)
    h = conn.execute("SELECT hash FROM payouts_ledger").fetchone()[0]
    assert ledger.mark_exported(conn, "batch-2026-10", 0, 1000) == 1
    assert ledger.mark_exported(conn, "batch-other", 0, 1000) == 0
    assert conn.execute("SELECT hash, flooos_batch FROM payouts_ledger").fetchone()[:] == (h, "batch-2026-10")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE payouts_ledger SET flooos_batch='again'")
    assert ledger.verify_chain(conn)["ok"]
    with pytest.raises(ledger.LedgerError):
        ledger.mark_exported(conn, "bad batch!", 0, 1)


# ---- Flooos export ----
def test_flooos_export_has_no_user_ids_and_neutralises_csv_injection(conn):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _inv(u.id))
    ledger.append(conn, "adjustment", "in", 100, "usd", "=HYPERLINK(\"http://evil\")", memo="+cmd|x", ts=1_760_000_200)
    out = flooos.build(conn, 0, None)
    blob = json.dumps(out)
    assert u.id not in blob and "a@example.com" not in blob
    assert out["format"] == "atlas-flooos-v1" and out["per_trade_fees"] == 0 and out["performance_fees"] == 0 and out["chain"]["ok"]
    assert out["summary"]["tax_collected_cents"] and out["summary"]["revenue_subscriptions_subtotal_cents"]
    csv_text = flooos.to_csv(out["ledger"])
    assert "'=HYPERLINK" in csv_text and ",=HYPERLINK" not in csv_text and "'+cmd" in csv_text


# ---- brokers ----
def test_seeded_partners_are_unapproved_and_inactive(conn):
    rows = conn.execute("SELECT legal_status, active FROM broker_partners").fetchall()
    assert rows and all(r["legal_status"] == "not_approved" and r["active"] == 0 for r in rows)
    assert brokers.public_partners(conn)["enabled"] is False


def _approve(conn, admin_id):
    code = conn.execute("SELECT code FROM broker_partners ORDER BY code").fetchone()[0]
    brokers.set_partner(conn, admin_id, code, "approved", True)
    return code


def test_referral_refused_until_approved_active_and_disclosed(conn):
    u, adm = mkuser(conn), mkuser(conn, "adm@example.com")
    code = conn.execute("SELECT code FROM broker_partners ORDER BY code").fetchone()[0]
    with pytest.raises(brokers.BrokerError) as e:
        brokers.start_referral(conn, u.id, code, True)
    assert e.value.code == "partner_unavailable"
    with pytest.raises(brokers.BrokerError):
        brokers.set_partner(conn, adm.id, code, None, True)  # cannot activate unapproved
    brokers.set_partner(conn, adm.id, code, "approved", None)
    with pytest.raises(brokers.BrokerError):
        brokers.start_referral(conn, u.id, code, True)  # approved but not active
    brokers.set_partner(conn, adm.id, code, None, True)
    with pytest.raises(brokers.BrokerError) as e:
        brokers.start_referral(conn, u.id, code, False)
    assert e.value.code == "disclosure_required"
    assert brokers.start_referral(conn, u.id, code, True)["status"] == "clicked"
    brokers.start_referral(conn, u.id, code, True)
    assert conn.execute("SELECT COUNT(*) FROM broker_referrals").fetchone()[0] == 1


def test_referral_paid_books_fixed_cpa_once(conn):
    u, adm = mkuser(conn), mkuser(conn, "adm@example.com")
    code = _approve(conn, adm.id)
    brokers.start_referral(conn, u.id, code, True)
    rid = conn.execute("SELECT id FROM broker_referrals").fetchone()[0]
    with pytest.raises(brokers.BrokerError):
        brokers.update_referral(conn, adm.id, rid, "paid", 0)
    brokers.update_referral(conn, adm.id, rid, "paid", 5000, "usd", "wire-1")
    brokers.update_referral(conn, adm.id, rid, "paid", 5000, "usd", "wire-1")
    rows = conn.execute("SELECT kind,direction,amount_cents,broker_referral_id FROM payouts_ledger").fetchall()
    assert [tuple(r) for r in rows] == [("partner_cpa", "in", 5000, rid)]
    with pytest.raises(brokers.BrokerError):
        brokers.update_referral(conn, adm.id, rid, "bogus")
    with pytest.raises(brokers.BrokerError):
        brokers.update_referral(conn, adm.id, rid, "qualified", 10**7)


def test_broker_api_gated(client):
    h = signup(client)
    j = client.get("/api/account/brokers").json()
    assert j["enabled"] is False and j["partners"] == []
    r = client.post("/api/account/brokers/anything/refer", json={"disclosure_shown": True}, headers=h)
    assert r.status_code == 404 and r.json()["error"] == "partner_unavailable"
    client.cookies.clear()
    assert client.get("/api/account/brokers").status_code in (200, 401)  # public listing needs a session only when ATLAS_REQUIRE_AUTH is on


# ---- admin API ----
def _owner(client, monkeypatch):
    monkeypatch.setenv("ATLAS_OWNER_EMAIL", "boss@example.com")
    return signup(client, "boss@example.com")


def test_admin_routes_forbidden_for_normal_users(client):
    h = signup(client)
    for method, path, body in (("post", "/api/admin/plans/update", {"code": "pro_month_usd", "price_cents": 1}), ("get", "/api/admin/brokers", None),
                               ("post", "/api/admin/brokers/update", {"code": "x"}), ("post", "/api/admin/ledger/append", {}),
                               ("get", "/api/admin/flooos/export", None), ("post", "/api/admin/flooos/mark", {})):
        r = getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, path


def test_admin_plan_update_bounded_and_audited(client, conn, monkeypatch):
    h = _owner(client, monkeypatch)
    ok = client.post("/api/admin/plans/update", json={"code": "pro_month_usd", "price_cents": 3100, "is_placeholder": False}, headers=h)
    assert ok.status_code == 200 and ok.json()["plan"]["price_cents"] == 3100
    for body in ({"price_cents": -1}, {"price_cents": 10**9}, {"price_cents": "5"}, {"price_cents": True}, {"seats_included": 0}, {"tax_behavior": "none"},
                 {"stripe_price_id": "not_a_price"}, {"active": "yes"}, {}):
        r = client.post("/api/admin/plans/update", json={"code": "pro_month_usd", **body}, headers=h)
        assert r.status_code == 400, body
    assert client.post("/api/admin/plans/update", json={"code": "nope", "price_cents": 1}, headers=h).status_code == 404
    acts = [r["action"] for r in audit.rows(conn)] if hasattr(audit, "rows") else [r[0] for r in conn.execute("SELECT action FROM audit_log")]
    assert "admin.plan_update" in acts


def test_admin_ledger_and_flooos_endpoints(client, monkeypatch):
    h = _owner(client, monkeypatch)
    assert client.post("/api/admin/ledger/append", json={"kind": "partner_cpa", "direction": "in", "amount_cents": 5, "currency": "usd", "counterparty": "x"}, headers=h).status_code == 400
    r = client.post("/api/admin/ledger/append", json={"kind": "tax_remittance", "direction": "out", "amount_cents": 507, "currency": "cad", "counterparty": "CRA", "bank_ref": "r1"}, headers=h)
    assert r.status_code == 200 and r.json()["chain"]["ok"]
    j = client.get("/api/admin/flooos/export", headers=h).json()
    assert j["ledger"][0]["flooos_category"] == "tax_remitted" and j["per_trade_fees"] == 0
    c = client.get("/api/admin/flooos/export?format=csv", headers=h)
    assert c.headers["content-type"].startswith("text/csv") and "tax_remittance" in c.text
    assert client.get("/api/admin/flooos/export?from=abc", headers=h).status_code == 400
    m = client.post("/api/admin/flooos/mark", json={"batch": "2026-10-a", "from": 0, "to": 2**40}, headers=h)
    assert m.json() == {"marked": 1}
    assert client.post("/api/admin/flooos/mark", json={"batch": "2026-10-b", "from": 0, "to": 2**40}, headers=h).json() == {"marked": 0}


# ---- retention on account deletion ----
def test_delete_account_anonymises_when_tax_records_exist(conn):
    u = mkuser(conn)
    stripe_client.handle_event(conn, _inv(u.id))
    auth.delete_account(conn, u.id, PW)
    r = conn.execute("SELECT email, password_hash, status FROM users WHERE id=?", (u.id,)).fetchone()
    assert r["email"].endswith("@deleted.invalid") and r["password_hash"] is None and r["status"] == "disabled"
    assert conn.execute("SELECT COUNT(*) FROM tax_records WHERE user_id=?", (u.id,)).fetchone()[0] == 1
    with pytest.raises(auth.AuthError):
        auth.authenticate(conn, r["email"], "anything", ip="10.0.0.9")
    assert mkuser(conn, "a@example.com")  # the address is free again


def test_delete_account_hard_deletes_without_financial_records(conn):
    u = mkuser(conn)
    auth.delete_account(conn, u.id, PW)
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id=?", (u.id,)).fetchone()[0] == 0


def test_usage_events_idempotent_and_cost_recorded(conn):
    u = mkuser(conn)
    assert entitlements.record_usage(conn, u.id, "ai.queries", 1, idempotency_key="req-1", unit_cost_micros=2500) is True
    assert entitlements.record_usage(conn, u.id, "ai.queries", 1, idempotency_key="req-1", unit_cost_micros=2500) is False
    assert conn.execute("SELECT COUNT(*), SUM(unit_cost_micros) FROM usage_events").fetchone()[:] == (1, 2500)


def test_dispute_fee_env_override_is_bounded():
    assert stripe_client.dispute_fee_cents({}) == 1500
    assert stripe_client.dispute_fee_cents({"ATLAS_DISPUTE_FEE_CENTS": "2000"}) == 2000
    assert stripe_client.dispute_fee_cents({"ATLAS_DISPUTE_FEE_CENTS": "-5"}) == 1500
    assert stripe_client.dispute_fee_cents({"ATLAS_DISPUTE_FEE_CENTS": "abc"}) == 1500
