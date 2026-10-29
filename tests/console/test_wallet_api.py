"""Investor wallet in the console (SIMULATION): staff routes vs investor-portal role separation, portal login +
lockout, own-data-only, step-up on redemption / bank change / forward / payout approval, two-person approval,
reconciliation breaks CSV, statements, vault fail-closed, and process boundaries (no tradingbot import, no network)."""
from __future__ import annotations

import ast
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_console_api import CONFIG, PKG, Client, FakeClock, _free_port
from atlas.governance.integrity.crypto import totp
from atlas.console.app import ConsolePaths, build_app
from atlas.console.demo import seed
from atlas.console.web import make_handler


class PortalClient(Client):
    """Same transport, but the investor portal cookie and login endpoint."""
    def call(self, method, path, body=None, headers=None, **kw):
        hdr = dict(headers or {})
        if self.cookie:
            hdr["Cookie"] = f"tbi_session={self.cookie}"
        saved, self.cookie = self.cookie, None
        try:
            return super().call(method, path, body, hdr, **kw)
        finally:
            self.cookie = saved

    def login(self, user, pw):
        r = self.call("POST", "/api/portal/login", {"username": user, "passphrase": pw})
        if r.status == 200:
            self.cookie = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
            self.csrf, self.sid = r.json["csrf"], r.json["session_id"]
        return r


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    var = tmp_path_factory.mktemp("wallet") / "demo"
    seed(var, CONFIG, run_sim=False, verbose=False)
    cred = dict(line.split("=", 1) for line in (var / "DEMO_CREDENTIALS.txt").read_text().splitlines()[1:])
    from atlas.mcp.trading.service import build_service
    paths = ConsolePaths.under(var, CONFIG)
    svc = build_service(str(CONFIG), paths.audit_db, paths.state_db, tax_db_path=paths.tax_db)
    port = _free_port()
    app, trading, payments = build_app(svc, paths, port, demo=True)
    clock = FakeClock()
    payments.approvers.clock = clock
    app.wallet.logins.clock = clock
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    staff, cfo, inv = Client(port), Client(port), PortalClient(port)
    assert staff.login(cred["username"], cred["passphrase"]).status == 200
    assert cfo.login(cred["cfo_username"], cred["cfo_passphrase"]).status == 200
    assert inv.login(cred["portal_username"], cred["portal_passphrase"]).status == 200
    yield SimpleNamespace(port=port, app=app, cred=cred, clock=clock, staff=staff, cfo=cfo, inv=inv, owner=cred["username"])
    srv.shutdown()
    srv.server_close()


def pay_su(env, who="owner", good=True):
    env.clock.tick()
    sec, pw = ((env.cred["payments_totp_secret"], env.cred["passphrase"]) if who == "owner"
               else (env.cred["cfo_payments_totp_secret"], env.cred["cfo_passphrase"]))
    code = totp(sec, env.clock())
    return {"passphrase": pw, "code": code if good else f"{(int(code) + 1) % 1_000_000:06d}"}


def inv_su(env, good=True):
    env.clock.tick()
    code = totp(env.cred["portal_totp_secret"], env.clock())
    return {"passphrase": env.cred["portal_passphrase"], "code": code if good else f"{(int(code) + 1) % 1_000_000:06d}"}


def ids(env):
    s = env.staff.call("GET", "/api/w/summary").json
    return {i["legal_name"].split()[0].lower(): i["id"] for i in s["investors"]}


# ------------------------------------------------------------------------------- Home inbox: one set of numbers
def test_home_inbox_matches_every_page(env):
    c = env.staff
    ib = c.call("GET", "/api/inbox").json
    by = {i["kind"]: i for i in ib["items"]}
    assert ib["counts"]["total"] == sum(i["count"] for i in ib["items"]) and ib["items"]
    assert [i["severity"] for i in ib["items"]] == sorted((i["severity"] for i in ib["items"]), key=["critical", "high", "normal", "info"].index)
    st = c.call("GET", "/api/t/state").json
    assert by.get("approval", {"count": 0})["count"] == len(st["approvals"])
    pays = c.call("GET", "/api/w/payouts").json["payouts"]
    assert by["payout_approval"]["count"] == sum(p["status"] == "pending_approval" for p in pays) == c.call("GET", "/api/w/summary").json["pending_payouts"]
    comp = c.call("GET", "/api/w/compliance").json
    assert by["sanctions_hits"]["count"] == comp["sanctions"]["blocking_hits"] == c.call("GET", "/api/w/summary").json["compliance_blocking"]
    assert by["fintrac_records"]["count"] == comp["fintrac"]["open"]
    ps = c.call("GET", "/api/p/summary").json
    assert by.get("transfer_approval", {"count": 0})["count"] == ps["by_status"].get("pending_approval", 0)
    recon_runs = c.call("GET", "/api/w/recon").json["runs"]
    assert by["recon_breaks"]["count"] == len(recon_runs[0]["breaks"])
    assert c.call("GET", "/api/nav").json["sections"] == ib["counts"]
    assert all(i["href"].startswith("/") for i in ib["items"])
    for path in {i["href"].split("?")[0] for i in ib["items"]}:
        assert c.call("GET", path).status == 200, path                        # every inbox link is a real page
    for path in ("/money", "/compliance", "/compliance/tax", "/money/payments"):
        assert c.call("GET", path).status == 200, path


def test_every_nav_route_and_old_url_is_served(env):
    import re
    js = (PKG / "static" / "js" / "app.js").read_text()
    tabs = set(re.findall(r'\["(/[a-z/]*)", "[^"]+"\]', js.split("export const ALIASES")[0]))
    aliases = re.findall(r'\["(/[a-z/]+)", "(/[a-z/]*)"\]', js.split("export const ALIASES")[1].split("];")[0])
    assert len(tabs) == 13 and len(aliases) >= 8
    for path in tabs | {a for a, _ in aliases} | {b for _, b in aliases}:
        assert env.staff.call("GET", path).status == 200, path               # SPA shell: never a 404 for a known URL


# ------------------------------------------------------------------------------- staff views
def test_staff_wallet_views(env):
    c = env.staff
    s = c.call("GET", "/api/w/summary")
    assert s.status == 200 and s.json["available"] and s.json["sim"]
    assert Decimal_(s.json["nav"]["nav_per_unit"]) > 0 and "never holds" in s.json["principle"]
    st = {i["legal_name"]: i["status"] for i in s.json["investors"]}
    assert st["Alice Martin"] == "approved" and st["Bob Low"] == "action_required" and st["Dmitri Draft"] == "draft"
    assert st["Sanctioned Person (DEMO)"] == "draft" and st["Erin Review"] == "submitted"   # held by platform sanctions screening
    for p in ("/api/w/subscriptions", "/api/w/redemptions", "/api/w/payouts", "/api/w/recon", "/api/w/partners"):
        r = c.call("GET", p)
        assert r.status == 200 and r.json is not None, p
    parts = c.call("GET", "/api/w/partners").json["partners"]
    real = [p for p in parts if not p["enabled"]]
    assert {p["kind"] for p in real} == {"FundAdministrator", "Custodian", "PayoutRail", "BankVerification"}
    assert all(v.startswith("env:") for p in real for v in (p.get("credentials") or {}).values())
    d = c.call("GET", f"/api/w/investors/{ids(env)['alice']}").json
    assert d["units"] != "0" and d["decisions"] and d["collected"]["id_last4"].startswith("••")
    assert all(b["account_masked"].startswith("•") for b in d["banks"]) and "account_number" not in str(d["banks"])
    for fmt, ct in (("pdf", "application/pdf"), ("csv", "text/csv")):
        r = c.call("GET", f"/api/w/investors/{ids(env)['alice']}/statement/{fmt}")
        assert r.status == 200 and r.headers["Content-Type"].startswith(ct)
    assert c.call("GET", "/wallet/investors/1").status == 200            # SPA route


def Decimal_(x):
    from decimal import Decimal
    return Decimal(str(x))


# ------------------------------------------------------------------------------- role separation
def test_roles_are_separate(env):
    inv, staff = env.inv, env.staff
    gets = [r.pattern.pattern.strip("^$") for r in env.app.router.routes if r.method == "GET" and "(?P" not in r.pattern.pattern
            and not r.pattern.pattern.startswith("^/api/i/") and not r.public]
    assert len(gets) > 20
    for p in gets:
        assert inv.call("GET", p).status == 401, p                         # portal cookie is not a staff session
    assert staff.call("GET", "/api/i/me").status == 401                     # staff cookie is not an investor session
    assert inv.call("GET", "/api/session").json["authenticated"] is False
    assert staff.call("GET", "/api/portal/session").json["authenticated"] is False
    # portal SPA shell not ported (ATLAS frontend hosts the investor portal page)
    routes = env.app.router.routes
    assert all((r.role == "investor") == r.pattern.pattern.startswith("^/api/i/") for r in routes)
    # an investor route cannot be registered outside /api/i/ (and vice versa)
    with pytest.raises(Exception):
        env.app.router.add("GET", "/api/w/leak", lambda r: {}, role="investor")


def test_portal_login_lockout_and_csrf(env):
    from atlas.ledgers.wallet.portal_auth import InvestorLogins
    InvestorLogins(Path(env.app.wallet.var) / "investor_logins.json").enroll("lockme", "lockme-passphrase-123", ids(env)["carol"])
    p = PortalClient(env.port)
    assert p.login("alice", "wrong-passphrase-xx").status == 401
    for _ in range(5):
        p.login("lockme", "wrong-passphrase-xx")
    assert p.login("lockme", "lockme-passphrase-123").status == 401        # locked out
    r = env.inv.call("POST", "/api/i/subscriptions", {"amount": "30000"}, csrf=False)
    assert r.status == 403                                                  # CSRF enforced on the portal too


# ------------------------------------------------------------------------------- investor portal
def test_investor_sees_only_own_data(env):
    me = env.inv.call("GET", "/api/i/me")
    assert me.status == 200 and me.json["investor"]["legal_name"] == "Alice Martin"
    assert "ledger" not in me.json and all("approvals" not in p for p in me.json["payouts"])
    carol_sub = [s for s in env.staff.call("GET", "/api/w/subscriptions").json["subscriptions"] if s["investor"] == "Carol Nguyen"][0]
    assert env.inv.call("POST", f"/api/i/subscriptions/{carol_sub['id']}/cancel", {}).status == 404
    assert env.inv.call("GET", "/api/i/statement/csv").status == 200
    # a bank link started for another investor cannot be completed by this investor
    tok = env.staff.call("POST", f"/api/w/investors/{ids(env)['carol']}/bank/start", {}).json["link_token"]
    r = env.inv.call("POST", "/api/i/bank/complete", {"link_token": tok, "institution": "rbc", "stepup": inv_su(env)})
    assert r.status == 409


def test_investor_subscription_instructions(env):
    r = env.inv.call("POST", "/api/i/subscriptions", {"amount": "30000"})
    assert r.status == 200 and r.json["reference"].startswith("SUB-") and "in trust" in r.json["instructions"]["pay_to"]["beneficiary"]
    assert env.inv.call("POST", "/api/i/subscriptions", {"amount": "10"}).status == 409   # below minimum
    assert env.inv.call("POST", f"/api/i/subscriptions/{r.json['id']}/cancel", {}).status == 200


def test_investor_redemption_requires_investor_stepup(env):
    r = env.inv.call("POST", "/api/i/redemptions", {"units": "100"})
    assert r.status == 401 and r.json["stepup"] == "investor"
    assert env.inv.call("POST", "/api/i/redemptions", {"units": "100", "stepup": inv_su(env, good=False)}).status == 403
    ok = env.inv.call("POST", "/api/i/redemptions", {"units": "200", "stepup": inv_su(env)})
    assert ok.status == 200 and ok.json["status"] == "requested", ok.json
    # staff payments step-up cannot stand in for the investor's own
    assert env.inv.call("POST", "/api/i/redemptions", {"units": "100", "stepup": pay_su(env)}).status == 403


# ------------------------------------------------------------------------------- staff step-up + two-person rule
def test_staff_sensitive_actions_need_payments_stepup(env):
    c, i = env.staff, ids(env)
    tok = c.call("POST", f"/api/w/investors/{i['alice']}/bank/start", {}).json["link_token"]
    assert c.call("POST", f"/api/w/investors/{i['alice']}/bank/complete", {"link_token": tok, "institution": "rbc"}).status == 401
    req = [r for r in c.call("GET", "/api/w/redemptions").json["redemptions"] if r["status"] == "requested"][0]
    assert c.call("POST", f"/api/w/redemptions/{req['id']}/forward", {}).status == 401
    f = c.call("POST", f"/api/w/redemptions/{req['id']}/forward", {"stepup": pay_su(env)})
    assert f.status == 200 and f.json["status"] == "forwarded"
    pend = [p for p in c.call("GET", "/api/w/payouts").json["payouts"] if p["status"] == "pending_approval"]
    assert pend and c.call("POST", f"/api/w/payouts/{pend[0]['id']}/approve", {}).status == 401


def test_two_person_payout_approval(env):
    c, cfo = env.staff, env.cfo
    red = [p for p in c.call("GET", "/api/w/payouts").json["payouts"] if p["status"] == "pending_approval" and p["kind"] == "redemption"][0]
    assert red["approvals"] == [env.owner]
    again = c.call("POST", f"/api/w/payouts/{red['id']}/approve", {"stepup": pay_su(env)})
    assert again.status == 409                                              # same person twice
    done = cfo.call("POST", f"/api/w/payouts/{red['id']}/approve", {"stepup": pay_su(env, "cfo")})
    assert done.status == 200 and done.json["status"] in ("released", "paid"), done.json
    # the requester cannot approve their own payout
    alice = ids(env)["alice"]
    p = cfo.call("POST", "/api/w/payouts", {"investor_id": alice, "amount": "75", "rail": "vopay", "purpose": "test refund"})
    assert p.status == 200 and p.json["status"] == "pending_approval"
    assert cfo.call("POST", f"/api/w/payouts/{p.json['id']}/approve", {"stepup": pay_su(env, "cfo")}).status == 409
    one = c.call("POST", f"/api/w/payouts/{p.json['id']}/approve", {"stepup": pay_su(env)})
    assert one.status == 200 and one.json["status"] == "pending_approval"   # 1 of 2: not released
    assert c.call("POST", f"/api/w/payouts/{p.json['id']}/reject", {"reason": "test"}).status == 200


# ------------------------------------------------------------------------------- reconciliation + vault
def test_recon_breaks_report(env):
    c = env.staff
    r = c.call("POST", "/api/w/recon/run", {})
    assert r.status == 200 and {"status", "breaks", "summary"} <= set(r.json)
    rid = c.call("GET", "/api/w/recon").json["runs"][0]["id"]
    csv = c.call("GET", f"/api/w/recon/{rid}/breaks.csv")
    assert csv.status == 200 and csv.headers["Content-Type"].startswith("text/csv") and b"check" in csv.raw.splitlines()[0]
    seeded = [x for x in c.call("GET", "/api/w/recon").json["runs"] if x["breaks"]]
    assert seeded and {b["check"] for b in seeded[-1]["breaks"]} >= {"trust_cash_in_transit"}


def test_vault_missing_fails_closed_503(env, monkeypatch):
    monkeypatch.delenv("ATLAS_VAULT_KEY", raising=False)
    r = env.staff.call("POST", "/api/w/investors", {"legal_name": "X Y", "email": "x@example.com"})
    assert r.status in (400, 503)
    full = {"legal_name": "Vault Test", "email": "v@example.com", "entity_type": "individual", "country": "CA", "province": "ON",
            "dob_or_incorporation": "1990-01-01", "address": "1 Main", "occupation": "x", "income": "1", "financial_assets": "1",
            "net_assets": "1", "risk_tolerance": "low", "horizon_years": "1", "objective": "x", "id_type": "passport", "id_last4": "1111"}
    assert env.staff.call("POST", "/api/w/investors", full).status == 503
    monkeypatch.setenv("ATLAS_VAULT_KEY", "changeme")
    assert env.staff.call("POST", "/api/w/investors", full).status == 503   # placeholder key refused


# ------------------------------------------------------------------------------- boundaries
def test_wallet_api_boundaries(env):
    src = (PKG / "wallet_api.py").read_text()
    mods = {(n.module or "") for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m == "tradingbot" or m.startswith("tradingbot.") for m in mods)
    wpkg = Path(__import__("atlas.ledgers.wallet", fromlist=["x"]).__file__).parent
    for f in list(wpkg.glob("*.py")) + [PKG / "wallet_api.py"]:
        tree = ast.parse(f.read_text())
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
                {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "smtplib", "ftplib", "paramiko"}, f
    posts = [r.pattern.pattern for r in env.app.router.routes if r.method == "POST" and "/api/w/" in r.pattern.pattern]
    assert not [p for p in posts if any(w in p for w in ("execute", "transfer", "deposit", "withdraw", "p2p", "balance"))]
    # stepped routes: bank change, forward, approve (staff); redemption + bank change (investor)
    st = {r.pattern.pattern: r.stepup for r in env.app.router.routes if r.method == "POST"}
    assert st["^/api/w/payouts/(?P<pid>[A-Za-z0-9_.:-]+)/approve$"] == "payments"
    assert st["^/api/i/redemptions$"] == "investor" and st["^/api/i/bank/complete$"] == "investor"


# ------------------------------------------------------------------------------- banking + compliance (SIMULATION)
def test_compliance_overview_and_calendar(env):
    c = env.staff
    d = c.call("GET", "/api/w/compliance").json
    by = {h["investor"]: h for h in d["hits"]}
    assert by["Sanctioned Person (DEMO)"]["status"] == "open" and by["Sanctioned Person (DEMO)"]["source"] == "UN"
    assert by["Carol Nguyen"]["status"] == "pending_second" and by["Northwind Holdings Ltd"]["status"] == "cleared"
    assert d["sanctions"]["blocking_hits"] >= 2 and any("SYNTHETIC" in w for w in d["sanctions"]["warnings"])
    kinds = {(r["kind"], r["investor"], r["status"]) for r in d["records"]}
    assert ("EFTR_IN", "Northwind Holdings Ltd", "handed_to_reporting_entity") in kinds and ("EFTR_IN", "Alice Martin", "draft") in kinds
    alice_eftr = next(r for r in d["records"] if r["investor"] == "Alice Martin")
    assert "originator_address" in alice_eftr["travel_rule_missing"]
    assert d["id_verifications"] and all(len(v["details"]["doc_number_last4"]) <= 4 for v in d["id_verifications"])
    assert any(x["name"] == "Remembrance Day" for x in d["calendar"]["upcoming_closures"])
    assert c.call("GET", "/api/w/summary").json["compliance_blocking"] >= 2
    cal = c.call("GET", "/api/w/banking/calendar?year=2026&region=CA-QC").json
    assert {"2026-06-24", "2026-09-30"} <= {x["date"] for x in cal["closures"]}
    v = c.call("POST", "/api/w/banking/validate", {"kind": "iban", "value": "GB82 WEST 1234 5698 7654 32"}).json
    assert v["valid"] and c.call("POST", "/api/w/banking/validate", {"kind": "aba", "value": "123"}).json["valid"] is False
    assert c.call("GET", "/wallet/compliance").status == 200 and c.call("GET", "/wallet/bankfiles").status == 200


def test_sanctions_review_two_person_and_payout_block(env):
    c, cfo = env.staff, env.cfo
    hit = next(h for h in c.call("GET", "/api/w/compliance/hits").json["hits"] if h["investor"] == "Carol Nguyen")
    carol_pay = next(p for p in c.call("GET", "/api/w/payouts").json["payouts"] if p["investor"] == "Carol Nguyen" and p["status"] == "pending_approval")
    blocked = c.call("POST", f"/api/w/payouts/{carol_pay['id']}/approve", {"stepup": pay_su(env)})
    assert carol_pay["sanctions_hold"] and blocked.status in (403, 409) and "sanctions" in blocked.json["error"]
    body = {"decision": "false_positive", "reason": "ID re-checked: DOB and province differ from the listed person"}
    assert c.call("POST", f"/api/w/compliance/hits/{hit['id']}/review", body).status == 401                 # step-up required
    again = c.call("POST", f"/api/w/compliance/hits/{hit['id']}/review", dict(body, stepup=pay_su(env)))
    assert again.status in (403, 409) and "different reviewer" in again.json["error"]                       # owner already reviewed
    ok = cfo.call("POST", f"/api/w/compliance/hits/{hit['id']}/review", dict(body, stepup=pay_su(env, "cfo")))
    assert ok.status == 200 and ok.json["status"] == "cleared"
    assert c.call("POST", f"/api/w/payouts/{carol_pay['id']}/approve", {"stepup": pay_su(env)}).status == 200


def test_investor_portal_is_not_tipped_off(env):
    w = env.app.wallet._w()
    w.screening.load_docs("test", [{"source": "UN", "published": "t", "sha256": "t", "file": "t", "entries": [
        {"uid": "T-ALICE", "kind": "individual", "name": "Alice Martin", "names": ["Alice Martin"], "dobs": [], "countries": [], "programs": ["T"], "listed_on": ""}]}])
    assert w.rescreen_all("test")["new_hits"] >= 1
    r = env.inv.call("POST", "/api/i/redemptions", {"units": "10", "stepup": inv_su(env)})
    assert r.status == 403 and "routine review" in r.json["error"] and "sanction" not in r.json["error"].lower()
    s = env.inv.call("POST", "/api/i/subscriptions", {"amount": "30000"})
    assert s.status == 403 and "sanction" not in s.json["error"].lower()
    hid = next(h["id"] for h in env.staff.call("GET", "/api/w/compliance/hits?status=open").json["hits"] if h["uid"] == "T-ALICE")
    for cl, who in ((env.staff, "owner"), (env.cfo, "cfo")):
        assert cl.call("POST", f"/api/w/compliance/hits/{hid}/review",
                       {"decision": "false_positive", "reason": "test entry, not the investor", "stepup": pay_su(env, who)}).status == 200
    assert env.staff.call("POST", "/api/w/compliance/sanctions/load", {"source": "samples"}).status == 200


def test_bank_files_pain001_pain002_and_camt(env):
    c = env.staff
    d = c.call("GET", "/api/w/bankfiles").json
    assert d["statement"]["reports"] and all(r["check"]["opening_plus_booked_equals_closing"] for r in d["statement"]["reports"])
    assert c.call("POST", "/api/w/bankfiles/pain001", {}).status == 401
    g = c.call("POST", "/api/w/bankfiles/pain001", {"stepup": pay_su(env)})
    assert g.status == 200 and "<CstmrCdtTrfInitn>" in g.json["xml"] and "<Cd>CACPA</Cd>" in g.json["xml"], g.json
    f = g.json["file"]
    assert f["xsd"] in ("valid", "unavailable") and f["n"] >= 1
    x = c.call("POST", f"/api/w/bankfiles/{f['id']}/xml", {"stepup": pay_su(env)})
    assert x.status == 200 and x.json["msg_id"] == f["msg_id"]
    e2e = f["txs"][0]["end_to_end_id"]
    sim = c.call("POST", f"/api/w/bankfiles/{f['id']}/simulate", {"reject": [e2e], "reason": "AC04", "stepup": pay_su(env)})
    assert sim.status == 200 and sim.json["applied"]["returned"] and "<CstmrPmtStsRpt>" in sim.json["xml"]
    dup = c.call("POST", "/api/w/bankfiles/pain002", {"xml": sim.json["xml"], "stepup": pay_su(env)})
    assert dup.status in (403, 409) and "already applied" in dup.json["error"]
    pays = {p["id"]: p for p in c.call("GET", "/api/w/payouts").json["payouts"]}
    assert pays[f["txs"][0]["payout_id"]]["status"] == "returned"
    xml = c.call("GET", "/api/w/bankfiles/camt053.xml")
    assert xml.status == 200 and b"camt.053.001.08" in xml.raw
    bad = xml.raw.decode().replace("<Cd>CLBD</Cd>", "<Cd>CLBD</Cd>", 1)
    rr = c.call("POST", "/api/w/bankfiles/camt/recon", {"camt053": bad})
    assert rr.status == 200 and rr.json["summary"]["custodian_source"].startswith("camt.053")
    assert c.call("POST", "/api/w/bankfiles/camt/recon", {"camt053": "<!DOCTYPE x><x/>"}).status == 400


def test_name_review_privacy_and_cpa005(env):
    c, cfo = env.staff, env.cfo
    pv = c.call("GET", "/api/w/privacy").json
    (rv,) = [r for r in pv["name_reviews"] if r["status"] == "pending"]
    assert rv["investor"] == "Erin Review" and rv["holder_name"] == "Erin Q. Review"
    body = {"approve": True, "reason": "Driver's licence shows middle name Quinn"}
    assert c.call("POST", f"/api/w/banks/{rv['bank_id']}/name-review", body).status == 401
    ok = cfo.call("POST", f"/api/w/banks/{rv['bank_id']}/name-review", dict(body, stepup=pay_su(env, "cfo")))
    assert ok.status == 200 and ok.json["status"] == "verified" and ok.json["name_match"] == 1
    assert pv["incidents"][0]["status"] == "closed" and pv["incidents"][0]["rrosh"] == "no"
    inc = c.call("POST", "/api/w/privacy/incidents", {"summary": "Laptop with exported CSV lost (test)", "detected_at": "2026-10-15",
                                                      "data_types": "name, email", "individuals": 3})
    assert inc.status == 200
    bad = c.call("POST", f"/api/w/privacy/incidents/{inc.json['id']}/assess", {"rrosh": "yes", "reason": "unencrypted, emails exposed", "close": True})
    assert bad.status == 400 and "notified" in bad.json["error"]
    (ar,) = [r for r in pv["access_requests"] if r["status"] == "open"]
    assert ar["investor"] == "Northwind Holdings Ltd" and ar["due_on"] == "2026-11-01"
    assert c.call("POST", f"/api/w/privacy/access/{ar['id']}/export", {}).status == 401
    ex = c.call("POST", f"/api/w/privacy/access/{ar['id']}/export", {"stepup": pay_su(env)})
    assert ex.status == 200 and ex.json["data"]["investor"]["legal_name"] == "Northwind Holdings Ltd" and ex.json["data"]["withheld"]
    assert "account_number" not in str(ex.json) and len(ex.json["sha256"]) == 64
    assert c.call("GET", "/api/w/privacy").json["status"]["open_access_requests"] == 0
    assert c.call("POST", "/api/w/bankfiles/cpa005", {}).status == 401
    cp = c.call("POST", "/api/w/bankfiles/cpa005", {"stepup": pay_su(env)})
    assert cp.status in (403, 409) and "no released CAD payouts" in cp.json["error"]          # everything already in a pain.001


def test_banking_api_boundaries(env):
    tree = ast.parse((PKG / "banking_api.py").read_text())
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
            {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not names & {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "smtplib", "ftplib", "paramiko", "tradingbot"}
    st = {r.pattern.pattern: r.stepup for r in env.app.router.routes if r.method == "POST"}
    for p in ("^/api/w/compliance/hits/(?P<hid>[A-Za-z0-9_.:-]+)/review$", "^/api/w/bankfiles/pain001$", "^/api/w/bankfiles/pain002$",
              "^/api/w/bankfiles/(?P<fid>[A-Za-z0-9_.:-]+)/xml$", "^/api/w/bankfiles/cpa005$",
              "^/api/w/banks/(?P<bid>[A-Za-z0-9_.:-]+)/name-review$", "^/api/w/privacy/access/(?P<rid>[A-Za-z0-9_.:-]+)/export$"):
        assert st[p] == "payments", p
