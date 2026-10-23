"""Investor wallet (SIMULATION): onboarding decisions come from the administrator, bank verification in the
investor's own name, subscriptions to the administrator's trust account, redemption terms, two-person payouts,
encrypted vault, three-way reconciliation, and the "platform never holds money" boundaries."""
import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.ledgers.db import connect
from atlas.ledgers.stepup import Approvers, totp
from atlas.ledgers.wallet import recon
from atlas.ledgers.wallet.partners import (TRUST, PartnerDisabled, fake_partners, real_partners)
from atlas.ledgers.wallet.portal_auth import InvestorAuthError, InvestorLogins
from atlas.ledgers.wallet.service import SanctionsHold, Wallet, WalletError, norm_name
from atlas.ledgers.wallet.vault import Vault, VaultUnavailable, mask, new_key

PW = "correct horse battery staple"
KEY = new_key()
PKG = Path(__file__).resolve().parents[2] / "src" / "atlas" / "ledgers" / "wallet"
DAY = 86400


class Clock:
    def __init__(self, t=1_790_000_000.0): self.t = t
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def person(name="Alice Martin", **kw):
    d = {"legal_name": name, "email": "alice@example.com", "entity_type": "individual", "country": "CA", "province": "ON",
         "dob_or_incorporation": "1980-01-01", "address": "1 King St W, Toronto", "occupation": "engineer", "income": "250000",
         "financial_assets": "400000", "net_assets": "900000", "risk_tolerance": "high", "horizon_years": 5,
         "objective": "growth", "id_type": "passport", "id_last4": "1234"}
    d.update(kw)
    return d


@pytest.fixture
def w(tmp_path):
    clock = Clock()
    c = connect(str(tmp_path / "p.sqlite"))
    appr = Approvers(tmp_path / "approvers.json", clock=clock)
    secrets = {n: appr.enroll(n, PW) for n in ("owner", "cfo", "ops")}
    parts = fake_partners(str(tmp_path / "partners_sim.sqlite"), clock)
    wal = Wallet(c, parts, appr, Vault(c, KEY, clock), clock)

    def creds(name):
        clock.advance(31)
        return name, PW, totp(secrets[name], clock())
    wal.creds, wal.tclock, wal.path = creds, clock, tmp_path
    # seed the fund: cash at custody so NAV is defined
    sim = parts.administrator.sim
    sim.line("custody:cad", Decimal("1000000"), "seed capital (GP)")
    sim.line("broker:ibkr", Decimal("0"), "open")
    sim.c.execute("INSERT INTO adm_register VALUES('GP', '100000')")
    wal.set_off_platform_refs("console:owner", ["GP"])
    wal.screening.load_samples("test")      # sanctions screening fails closed without lists (synthetic sample lists)
    return wal


def onboard(w, name="Alice Martin", **kw):
    iid = w.create_investor("console:owner", person(name, **kw))
    w.submit_onboarding("console:owner", iid)
    w.p.administrator.review(w.investor(iid)["admin_ref"])       # administrator back office (SIM)
    w.sync_onboarding("console:owner", iid)
    return iid


def link_bank(w, iid, scenario="own", cool=True):
    tok = w.bank_link_start(iid)
    b = w.bank_link_complete("console:owner", iid, tok, "rbc", scenario)
    if cool:
        w.tclock.advance(25 * 3600)
    return b


def fund(w, iid, amount="50000"):
    s = w.request_subscription("console:owner", iid, amount, f"sub-{iid}-{amount}")
    w.p.administrator.receive_payment(s["reference"], D(amount))
    w.p.administrator.deal("2026-10-31")
    w.sync()
    return s


def D(x): return Decimal(str(x))


# ----------------------------------------------------------------------------- onboarding
def test_onboarding_decisions_come_from_administrator_and_are_append_only(w):
    iid = w.create_investor("console:owner", person())
    assert w.investor(iid)["status"] == "draft"
    with pytest.raises(WalletError):
        w.request_subscription("x", iid, "30000", "k1")                 # not approved
    w.submit_onboarding("console:owner", iid)
    assert all(d["result"] == "pending" for d in w.decisions(iid))
    w.p.administrator.review(w.investor(iid)["admin_ref"])
    res = w.sync_onboarding("console:owner", iid)
    assert res["status"] == "approved" and res["new_decisions"] == 5
    d = {x["kind"]: x for x in w.decisions(iid)}
    assert d["kyc"]["result"] == "verified" and d["eligibility"]["result"] == "accredited_investor"
    assert d["sanctions_pep"]["result"] == "clear" and d["suitability"]["result"] == "suitable"
    assert all(x["source"].startswith("fake-administrator") for x in d.values())
    assert w.sync_onboarding("console:owner", iid)["new_decisions"] == 0   # idempotent
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("UPDATE w_decisions SET result='verified'")
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("DELETE FROM w_decisions")
    # no API on Wallet lets the app set a decision itself
    assert not [m for m in dir(Wallet) if m.startswith(("set_kyc", "set_decision", "approve_investor", "decide"))]


def test_onboarding_rejections_and_data_minimisation(w):
    # platform-side sanctions screening holds the submission before it reaches the administrator
    with pytest.raises(SanctionsHold, match="sanctions hit under review"):
        onboard(w, "Sanctioned Person (DEMO)")
    s = w.c.execute("SELECT id FROM w_investors WHERE legal_name='Sanctioned Person (DEMO)'").fetchone()[0]
    assert w.investor(s)["status"] == "draft" and w.screening.blocking_hits(s)[0]["source"] == "UN"
    # test shortcut past the platform hold: the administrator's own screening still rejects the case
    w.c.execute("UPDATE s_hits SET status='cleared'")
    w.submit_onboarding("console:owner", s)
    w.p.administrator.review(w.investor(s)["admin_ref"])
    w.sync_onboarding("console:owner", s)
    assert w.investor(s)["status"] == "rejected"
    u = onboard(w, "Bob Low", risk_tolerance="low", email="bob@example.com")
    assert w.investor(u)["status"] == "action_required"
    with pytest.raises(ValueError, match="missing"):
        w.create_investor("x", {"legal_name": "X"})
    with pytest.raises(ValueError, match="SIN"):
        w.create_investor("x", person(sin="123456789"))
    with pytest.raises(ValueError):
        w.create_investor("x", person(id_last4="123456789"))
    # PII lives encrypted in the vault, not in plaintext columns
    raw = (w.path / "p.sqlite").read_bytes()
    assert b"1 King St W" not in raw and b"1980-01-01" not in raw
    assert w.pii(u)["address"] == "1 King St W, Toronto"


# ----------------------------------------------------------------------------- vault
def test_vault_aes_gcm_masking_and_fail_closed(w, monkeypatch):
    v = w.vault
    vid = v.put("bank_account", "003-12345-7654321")
    assert v.get(vid) == "003-12345-7654321"
    raw = w.c.execute("SELECT ciphertext FROM vault WHERE id=?", (vid,)).fetchone()[0]
    assert b"7654321" not in raw
    other = v.put("bank_account", "x")
    w.c.execute("UPDATE vault SET ciphertext=(SELECT ciphertext FROM vault WHERE id=?), nonce=(SELECT nonce FROM vault WHERE id=?) WHERE id=?", (vid, vid, other))
    with pytest.raises(Exception):
        v.get(other)                                       # bound to its row id (AAD)
    with pytest.raises(VaultUnavailable):
        Vault(w.c, new_key()).get(vid)                     # wrong key
    monkeypatch.delenv("ATLAS_VAULT_KEY", raising=False)
    for bad in ("", "changeme", "placeholder", "notbase64!!", "c2hvcnQ="):
        with pytest.raises(VaultUnavailable):
            Vault(w.c, bad)
    with pytest.raises(VaultUnavailable):
        Vault(w.c)                                          # env missing
    assert mask("7654321") == "•••4321" and mask("12") == "12"


# ----------------------------------------------------------------------------- bank verification
def test_bank_verification_own_name_only(w):
    iid = onboard(w)
    bad = link_bank(w, iid, "third_party")
    assert bad["status"] == "rejected_name_mismatch" and not bad["usable"]
    joint = link_bank(w, iid, "joint")
    assert joint["status"] == "rejected_name_mismatch"
    good = link_bank(w, iid, "own", cool=False)
    assert good["status"] == "verified" and good["account_masked"].startswith("•") and not good["usable"]  # cooling-off
    w.tclock.advance(25 * 3600)
    assert w.bank(good["id"])["usable"]
    assert "account_number" not in json.dumps(w.banks(iid))
    second = link_bank(w, iid, "own")
    assert w.bank(good["id"])["status"] == "superseded" and second["status"] == "verified"
    assert norm_name("Dr. Alice  MARTIN") == norm_name("martin alice")


# ----------------------------------------------------------------------------- subscriptions
def test_subscription_reference_trust_account_and_units_at_next_nav(w):
    iid = onboard(w)
    with pytest.raises(WalletError, match="minimum"):
        w.request_subscription("console:owner", iid, "1000", "k0")
    s = w.request_subscription("console:owner", iid, "50000", "k1")
    assert s["status"] == "instructed" and s["reference"].startswith("SUB-")
    ins = s["instructions"]
    assert "in trust" in ins["pay_to"]["beneficiary"] and s["reference"] in ins["memo"]
    assert w.request_subscription("console:owner", iid, "50000", "k1")["id"] == s["id"]     # idempotent
    with pytest.raises(WalletError):
        w.request_subscription("console:owner", iid, "60000", "k1")
    assert w.units(iid) == 0
    w.p.administrator.receive_payment(s["reference"], D("50000"))
    w.sync()
    assert w.subscription(s["id"])["status"] == "funds_received" and w.units(iid) == 0
    assert D(w.p.custodian.statement()["accounts"][TRUST]) == D("50000")
    deal = w.p.administrator.deal("2026-10-31")
    assert s["reference"] in deal["issued"]
    w.sync()
    assert w.subscription(s["id"])["status"] == "units_issued"
    assert w.units(iid) == D("5000.0000")                                   # 50,000 / NAV 10.0000
    assert D(w.p.custodian.statement()["accounts"][TRUST]) == 0
    w.sync()
    assert len(w.c.execute("SELECT * FROM w_units").fetchall()) == 1        # idempotent sync
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("UPDATE w_units SET units='999'")


def test_om_eligible_cap(w):
    iid = onboard(w, "Carol Om", income="50000", financial_assets="20000", net_assets="100000", email="c@example.com")
    assert {d["kind"]: d["result"] for d in w.decisions(iid)}["eligibility"] == "om_eligible"
    w.request_subscription("console:owner", iid, "8000", "om1")
    with pytest.raises(WalletError, match="cap"):
        w.request_subscription("console:owner", iid, "3000", "om2")


# ----------------------------------------------------------------------------- redemptions + payouts
def test_redemption_terms_lockup_notice_min_holding(w):
    iid = onboard(w)
    fund(w, iid, "50000")
    with pytest.raises(WalletError, match="lock-up"):
        w.request_redemption("investor:alice", iid, "100", "r0")
    w.tclock.advance(366 * DAY)
    with pytest.raises(WalletError, match="verified bank"):
        w.request_redemption("investor:alice", iid, "1000", "r1")
    link_bank(w, iid)
    with pytest.raises(WalletError, match="exceed"):
        w.request_redemption("investor:alice", iid, "6000", "r2")
    with pytest.raises(WalletError, match="minimum redemption"):
        w.request_redemption("investor:alice", iid, "10", "r3")
    with pytest.raises(WalletError, match="minimum holding"):
        w.request_redemption("investor:alice", iid, "4800", "r4")
    r = w.request_redemption("investor:alice", iid, "1000", "r5")
    assert r["status"] == "requested" and r["dealing_date"] >= w.dealing_date(w.tclock() - 1)
    import datetime as dt
    assert dt.date.fromisoformat(r["dealing_date"]) >= dt.date.fromtimestamp(w.tclock()) + dt.timedelta(days=30)


def test_redemption_flow_two_person_payout_to_verified_account(w):
    iid = onboard(w)
    fund(w, iid, "50000")
    w.tclock.advance(366 * DAY)
    link_bank(w, iid)
    r = w.request_redemption("investor:alice", iid, "1000", "r1")
    r = w.forward_redemption("owner", r["id"])
    assert r["status"] == "forwarded" and r["admin_ref"].startswith("RED-")
    w.p.administrator.deal(r["dealing_date"])
    out = w.sync()
    assert out["redemptions_dealt"] == 1 and w.units(iid) == D("4000")
    pay = w.c.execute("SELECT * FROM w_payouts WHERE redemption_id=?", (r["id"],)).fetchone()
    assert pay["status"] == "pending_approval" and pay["bank_id"] == r["bank_id"]
    p1 = w.approve_payout(pay["id"], *w.creds("owner"))
    assert p1["status"] == "pending_approval" and p1["approvals"] == ["owner"]
    with pytest.raises(WalletError, match="different person"):
        w.approve_payout(pay["id"], *w.creds("owner"))
    p2 = w.approve_payout(pay["id"], *w.creds("cfo"))
    assert p2["status"] == "paid" and p2["release_ref"].startswith("REL-")
    assert w.redemption(r["id"])["status"] == "paid"
    rep = w.p.administrator.payout_report()
    assert rep and rep[0]["release_ref"] == p2["release_ref"]
    assert sorted(json.loads(w.p.administrator.redemptions()[0]["approvers"])) == ["cfo", "owner"]
    res = recon.run(w)
    assert res["status"] == "clean", res["breaks"]


def test_payout_controls_requester_kill_switch_bank_revocation(w):
    iid = onboard(w)
    link_bank(w, iid)
    p = w.request_payout("console:ops", iid, "250", "zumrails", "referral reward", "np1")
    assert p["status"] == "pending_approval" and p["required_approvals"] == 2
    with pytest.raises(WalletError, match="requester"):
        w.approve_payout(p["id"], *w.creds("ops"))
    w.c.execute("INSERT OR REPLACE INTO settings VALUES('kill','1')")
    with pytest.raises(WalletError, match="kill"):
        w.approve_payout(p["id"], *w.creds("owner"))
    w.c.execute("INSERT OR REPLACE INTO settings VALUES('kill','0')")
    w.approve_payout(p["id"], *w.creds("owner"))
    w.revoke_bank("console:owner", w.verified_bank(iid)["id"])
    with pytest.raises(WalletError, match="verified"):
        w.approve_payout(p["id"], *w.creds("cfo"))
    link_bank(w, iid)
    q2 = w.request_payout("console:ops", iid, "100", "vopay", "rebate", "np2")
    w.approve_payout(q2["id"], *w.creds("owner"))
    done = w.approve_payout(q2["id"], *w.creds("cfo"))
    assert done["status"] == "paid" and done["partner_ref"].startswith("VOPAY-")
    with pytest.raises(Exception):
        w.approve_payout(q2["id"], "cfo", PW, "000000")        # wrong TOTP
    w.reject_payout("console:owner", p["id"], "stale")
    assert w.payout(p["id"])["status"] == "rejected"


def test_gate_prorates_and_carries_forward(w):
    a = onboard(w)
    fund(w, a, "200000")
    w.tclock.advance(366 * DAY)
    link_bank(w, a)
    r = w.forward_redemption("owner", w.request_redemption("investor:a", a, "15000", "g1")["id"])
    res = w.p.administrator.deal(r["dealing_date"], gate_pct="10")
    assert D(res["gate_ratio"]) < 1
    w.sync()
    child = w.c.execute("SELECT * FROM w_reds WHERE parent_id=?", (r["id"],)).fetchone()
    assert child and child["status"] == "forwarded" and "gated" in child["note"]
    assert D(w.redemption(r["id"])["units_dealt"]) < D("15000")


# ----------------------------------------------------------------------------- reconciliation
def test_three_way_recon_detects_breaks(w):
    iid = onboard(w)
    fund(w, iid, "50000")
    assert recon.run(w)["status"] == "clean"
    sim = w.p.administrator.sim
    sim.c.execute("UPDATE adm_register SET units='4995' WHERE case_ref=?", (w.investor(iid)["admin_ref"],))   # register error
    w.p.custodian.mark_market("broker:ibkr", 0)
    sim.line("broker:ibkr", D("1500"), "unexplained receipt")
    s2 = w.request_subscription("console:owner", iid, "30000", "k2")
    sim.line(TRUST, D("30000"), "trust receipt not yet booked by administrator", s2["reference"])
    res = recon.run(w)
    checks = {b["check"] for b in res["breaks"]}
    assert {"units_per_investor", "value_per_investor", "units_outstanding", "fund_net_assets", "trust_cash_in_transit"} <= checks
    csvtxt = recon.breaks_csv(w, res["id"])
    assert csvtxt.startswith("check,subject,internal,administrator,custodian") and "units_per_investor" in csvtxt
    assert recon.runs(w)[0]["id"] == res["id"]


# ----------------------------------------------------------------------------- partners + boundaries
def test_real_adapters_disabled_without_network_code():
    rp = real_partners()
    for ad in [rp.administrator, rp.custodian, rp.bank_verification, *rp.rails.values()]:
        assert ad.enabled is False
        with pytest.raises(PartnerDisabled):
            ad.open_case({}) if hasattr(type(ad), "open_case") else ad.statement()
        for v in ad.info()["credentials"].values():
            assert v.startswith("env:")
    for f in PKG.glob("*.py"):
        mods = set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                mods.add(n.module.split(".")[0])
        assert not mods & {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "tradingbot", "ssl", "paramiko"}, (f, mods)


def test_no_stored_value_p2p_or_pooled_account(w):
    names = " ".join(dir(Wallet)).lower()
    for bad in ("deposit_to_wallet", "transfer_between", "p2p", "send_to_investor", "top_up", "withdraw_balance", "credit_balance"):
        assert bad not in names
    tables = {r[0] for r in w.c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("balance" in t for t in tables if t.startswith("w_"))
    cols = {r[1] for t in tables if t.startswith("w_") for r in w.c.execute(f"PRAGMA table_info({t})")}
    assert "balance" not in cols and "cash_balance" not in cols
    # the payout destination can only be the investor's own verified bank account
    a, b = onboard(w, "Alice Martin"), onboard(w, "Dan Other", email="d@example.com")
    link_bank(w, a)
    link_bank(w, b)
    p = w.request_payout("console:ops", a, "50", "zumrails", "reward", "x1")
    w.c.execute("UPDATE w_payouts SET bank_id=? WHERE id=?", (w.verified_bank(b)["id"], p["id"]))   # tampered destination
    with pytest.raises(WalletError, match="another investor"):
        w.approve_payout(p["id"], *w.creds("owner"))


def test_investor_logins_separate_role_and_step_up(tmp_path):
    clock = Clock()
    il = InvestorLogins(tmp_path / "investor_logins.json", clock)
    sec = il.enroll("alice", PW, 7)
    assert il.check("alice", PW) == 7 and il.investor_id("alice") == 7
    with pytest.raises(InvestorAuthError):
        il.check("alice", "wrong passphrase")
    code = totp(sec, clock())
    assert il.verify("alice", PW, code) == 7
    with pytest.raises(InvestorAuthError):
        il.verify("alice", PW, code)                         # single use
    for _ in range(5):
        with pytest.raises(InvestorAuthError):
            il.check("alice", "nope nope nope")
    with pytest.raises(InvestorAuthError, match="locked"):
        il.check("alice", PW)
    assert oct((tmp_path / "investor_logins.json").stat().st_mode & 0o777) == "0o600"
