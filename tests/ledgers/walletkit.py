"""Shared wallet test kit (same setup as test_wallet.py's fixture) for the banking/compliance test modules."""
from decimal import Decimal

from atlas.ledgers.db import connect
from atlas.ledgers.stepup import Approvers, totp
from atlas.ledgers.wallet.partners import fake_partners
from atlas.ledgers.wallet.service import Wallet
from atlas.ledgers.wallet.vault import Vault, new_key

PW = "correct horse battery staple"
KEY = new_key()
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


def make_wallet(tmp_path, t=1_790_000_000.0):
    clock = Clock(t)
    c = connect(str(tmp_path / "p.sqlite"))
    appr = Approvers(tmp_path / "approvers.json", clock=clock)
    secrets = {n: appr.enroll(n, PW) for n in ("owner", "cfo", "ops")}
    parts = fake_partners(str(tmp_path / "partners_sim.sqlite"), clock)
    wal = Wallet(c, parts, appr, Vault(c, KEY, clock), clock)

    def creds(name):
        clock.advance(31)
        return name, PW, totp(secrets[name], clock())
    wal.creds, wal.tclock, wal.path = creds, clock, tmp_path
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
    w.p.administrator.review(w.investor(iid)["admin_ref"])
    w.sync_onboarding("console:owner", iid)
    return iid


def link_bank(w, iid, scenario="own", cool=True, institution="rbc"):
    b = w.bank_link_complete("console:owner", iid, w.bank_link_start(iid), institution, scenario)
    if cool:
        w.tclock.advance(25 * 3600)
    return b


def fund(w, iid, amount="50000"):
    s = w.request_subscription("console:owner", iid, amount, f"sub-{iid}-{amount}")
    w.p.administrator.receive_payment(s["reference"], Decimal(amount))
    return s
