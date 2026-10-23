"""Partner adapter interfaces + DISABLED real adapters + OFFLINE fakes (simulation).

Roles (who holds the money; the platform never does):
* FundAdministrator (e.g. an SGGG-style fund administrator / dealer): onboarding decisions (KYC, accredited / OM
  eligibility, suitability, sanctions/PEP, beneficial ownership), subscription trust account and reference IDs,
  the unit register, NAV, dealing, redemption processing and payouts to the investor's verified bank account.
* Custodian: statements for the fund's custody / broker accounts and the administrator's trust account.
* PayoutRail (Zum Rails / VoPay): optional non-fund payouts, from the PARTNER's trust account.
* BankVerification (Plaid / Flinks): account ownership (holder name, institution / transit / account).

Real adapters have NO network code: every call raises PartnerDisabled. Credentials are env-var NAMES only.
The fakes keep the partners' state in their own SQLite file (`partners_sim.sqlite`), separate from the app's
DB, so reconciliation compares genuinely independent records."""
from __future__ import annotations

import datetime as dt
import json
import secrets
import sqlite3
import time
from decimal import Decimal
from typing import Protocol

from atlas.ledgers.banking.calendars import last_business_day_of_month
from atlas.ledgers.money import D, q


class PartnerDisabled(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------- interfaces
class FundAdministrator(Protocol):
    name: str
    enabled: bool
    def open_case(self, payload: dict) -> str: ...
    def case(self, case_ref: str) -> dict: ...
    def subscription_instructions(self, case_ref: str, amount: Decimal, currency: str) -> dict: ...
    def subscriptions(self) -> list[dict]: ...
    def submit_redemption(self, case_ref: str, units: Decimal, request_ref: str, bank_token: str, dealing_date: str) -> str: ...
    def redemptions(self) -> list[dict]: ...
    def release_payout(self, admin_ref: str, release_ref: str, approvers: list[str]) -> dict: ...
    def register(self) -> dict[str, Decimal]: ...
    def nav(self) -> dict: ...
    def payout_report(self) -> list[dict]: ...


class Custodian(Protocol):
    name: str
    enabled: bool
    def statement(self) -> dict: ...


class PayoutRail(Protocol):
    name: str
    enabled: bool
    def payout(self, reference: str, amount: Decimal, currency: str, account: dict) -> str: ...
    def report(self) -> list[dict]: ...


class BankVerification(Protocol):
    name: str
    enabled: bool
    def start(self, investor_ref: str, holder_hint: str = "") -> str: ...
    def complete(self, link_token: str, institution: str, scenario: str = "own") -> str: ...
    def fetch(self, public_token: str) -> dict: ...


# ---------------------------------------------------------------------------------------------- real (disabled)
class _Disabled:
    name = "disabled"
    kind = ""
    enabled = False
    docs = ""
    credentials: dict = {}

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        def _no(*a, **k):
            raise PartnerDisabled(f"{self.name} adapter is disabled in this build (needs a signed contract, "
                                  f"credentials {sorted(self.credentials.values())} and an explicit enable); no network code")
        return _no

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "enabled": False, "mode": "disabled (real; no network code)",
                "docs": self.docs, "credentials": self.credentials}


class SGGGStyleAdministrator(_Disabled):
    name, kind, docs = "fund-administrator (SGGG-style)", "FundAdministrator", "https://www.sggg.com/ (SFTP/CSV or API per contract)"
    credentials = {"sftp_host": "env:FUNDADMIN_SFTP_HOST", "sftp_key": "env:FUNDADMIN_SFTP_KEY_PATH"}


class TrustCustodian(_Disabled):
    name, kind, docs = "custodian (bank / trust company)", "Custodian", "statement files (BAI2 / CAMT.053) per contract"
    credentials = {"statement_drop": "env:CUSTODIAN_STATEMENT_DIR"}


class ZumRails(_Disabled):
    name, kind, docs = "zum-rails", "PayoutRail", "https://docs.zumrails.com/"
    credentials = {"api_key": "env:ZUMRAILS_API_KEY"}


class VoPay(_Disabled):
    name, kind, docs = "vopay", "PayoutRail", "https://docs.vopay.com/"
    credentials = {"account_id": "env:VOPAY_ACCOUNT_ID", "api_key": "env:VOPAY_API_KEY"}


class Plaid(_Disabled):
    name, kind, docs = "plaid", "BankVerification", "https://plaid.com/docs/auth/"
    credentials = {"client_id": "env:PLAID_CLIENT_ID", "secret": "env:PLAID_SECRET"}


class Flinks(_Disabled):
    name, kind, docs = "flinks", "BankVerification", "https://flinks.com/"
    credentials = {"customer_id": "env:FLINKS_CUSTOMER_ID"}


# ---------------------------------------------------------------------------------------------- fakes
SIM_SCHEMA = """
CREATE TABLE IF NOT EXISTS adm_cases(ref TEXT PRIMARY KEY, payload TEXT, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS adm_decisions(id INTEGER PRIMARY KEY, case_ref TEXT, kind TEXT, result TEXT, detail TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS adm_register(case_ref TEXT PRIMARY KEY, units TEXT);
CREATE TABLE IF NOT EXISTS adm_subs(reference TEXT PRIMARY KEY, case_ref TEXT, amount TEXT, currency TEXT, status TEXT,
  received TEXT, units TEXT, nav TEXT, nav_date TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS adm_reds(ref TEXT PRIMARY KEY, case_ref TEXT, units TEXT, request_ref TEXT UNIQUE, bank_token TEXT,
  status TEXT, dealing_date TEXT, units_dealt TEXT, nav TEXT, gross TEXT, fees TEXT, withholding TEXT, net TEXT,
  release_ref TEXT, approvers TEXT, paid REAL, created REAL);
CREATE TABLE IF NOT EXISTS adm_nav(nav_date TEXT PRIMARY KEY, nav_per_unit TEXT, net_assets TEXT, units_outstanding TEXT);
CREATE TABLE IF NOT EXISTS cust_lines(id INTEGER PRIMARY KEY, account TEXT, ts REAL, amount TEXT, memo TEXT, ref TEXT);
CREATE TABLE IF NOT EXISTS cust_line_meta(line_id INTEGER PRIMARY KEY, method TEXT, originator TEXT);
CREATE TABLE IF NOT EXISTS rail_payouts(ref TEXT PRIMARY KEY, rail TEXT, reference TEXT UNIQUE, amount TEXT, currency TEXT,
  account_last4 TEXT, status TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS bv_links(token TEXT PRIMARY KEY, investor_ref TEXT, holder TEXT, public_token TEXT, institution TEXT,
  scenario TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS sim_kv(k TEXT PRIMARY KEY, v TEXT);
"""
TRUST = "trust:subscriptions"           # administrator's subscription/redemption trust account at the custodian
FUND_ACCOUNTS = ("custody:cad", "broker:ibkr", "broker:kraken")
TRUST_ACCOUNT = {"beneficiary": "Fund Administrator Inc. in trust for Example Fund LP (SIMULATION)",
                 "institution": "001", "transit": "00011", "account": "9988776", "swift": "BOFMCAM2",
                 "bank": "Bank of Montreal (SIMULATED ACCOUNT, DO NOT PAY)"}
ACCOUNT_IDS = {TRUST: f"{TRUST_ACCOUNT['institution']}-{TRUST_ACCOUNT['transit']}-{TRUST_ACCOUNT['account']}",
               "custody:cad": "CUST-FUND-CAD-0001", "broker:ibkr": "BRK-IBKR-SIM-0001", "broker:kraken": "BRK-KRKN-SIM-0001"}
SANCTIONS_DEMO = {"sanctioned person (demo)"}
INSTITUTIONS = {"rbc": ("003", "Royal Bank of Canada"), "td": ("004", "TD Canada Trust"), "bmo": ("001", "Bank of Montreal"),
                "scotia": ("002", "Scotiabank"), "cibc": ("010", "CIBC"), "desjardins": ("815", "Desjardins")}


def month_end(d: dt.date) -> dt.date:
    """Dealing/NAV date for the month containing d: the LAST PAYMENTS CANADA BUSINESS DAY of the month (not the
    calendar month end; e.g. Sep 2026 -> Tue Sep 29, because Wed Sep 30 is a system closure)."""
    return last_business_day_of_month(d, "CA")


class SimDB:
    def __init__(self, path: str, clock=time.time):
        self.path, self.clock = path, clock
        self.c = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.executescript(SIM_SCHEMA)

    def kv(self, k, default=None):
        r = self.c.execute("SELECT v FROM sim_kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_kv(self, k, v):
        self.c.execute("INSERT OR REPLACE INTO sim_kv VALUES(?,?)", (k, str(v)))

    def line(self, account, amount, memo, ref="", method=None, originator=None):
        lid = self.c.execute("INSERT INTO cust_lines(account,ts,amount,memo,ref) VALUES(?,?,?,?,?)",
                             (account, self.clock(), str(q(amount)), memo, ref)).lastrowid
        if method or originator:
            self.c.execute("INSERT INTO cust_line_meta VALUES(?,?,?)", (lid, method, json.dumps(originator or {})))
        return lid

    def balance(self, account) -> Decimal:
        return sum((D(r[0]) for r in self.c.execute("SELECT amount FROM cust_lines WHERE account=?", (account,))), Decimal(0))


class FakeAdministrator:
    """Offline simulation of a fund administrator / exempt-market dealer back office."""
    name, kind, enabled = "fake-administrator (offline simulation)", "FundAdministrator", True

    def __init__(self, sim: SimDB, fund_name="Example Fund LP (SIMULATION)", mgmt_fee_annual="0.02"):
        self.sim, self.fund_name, self.mgmt = sim, fund_name, D(mgmt_fee_annual)

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "enabled": True, "mode": "offline fake", "fund": self.fund_name}

    @property
    def c(self):
        return self.sim.c

    # ---- onboarding
    def open_case(self, payload: dict) -> str:
        ref = "ADM-" + secrets.token_hex(4).upper()
        self.c.execute("INSERT INTO adm_cases VALUES(?,?,?,?)", (ref, json.dumps(payload, sort_keys=True), "under_review", self.sim.clock()))
        self.c.execute("INSERT OR IGNORE INTO adm_register VALUES(?,?)", (ref, "0"))
        return ref

    def update_case(self, case_ref: str, payload: dict) -> None:
        self.c.execute("UPDATE adm_cases SET payload=?, status='under_review' WHERE ref=?", (json.dumps(payload, sort_keys=True), case_ref))

    def review(self, case_ref: str) -> dict:
        """SIM HOOK (administrator / dealer back office): decide the case using simple, documented rules."""
        r = self.c.execute("SELECT * FROM adm_cases WHERE ref=?", (case_ref,)).fetchone()
        if not r:
            raise KeyError(case_ref)
        p = json.loads(r["payload"])
        name = str(p.get("legal_name", "")).strip().lower()
        dec = {}
        dec["sanctions_pep"] = ("hit", "consolidated list match (SIMULATED)") if name in SANCTIONS_DEMO else \
            (("pep_review", "self-declared PEP/HIO") if p.get("pep") else ("clear", "no match (SIMULATED screening)"))
        dec["kyc"] = ("verified", f"{p.get('id_type', '')} document + liveness (SIMULATED)") if p.get("id_type") and p.get("id_last4") \
            else ("more_info_required", "government photo ID required")
        inc, fin, net = D(p.get("income", 0) or 0), D(p.get("financial_assets", 0) or 0), D(p.get("net_assets", 0) or 0)
        if p.get("entity_type", "individual") == "individual":
            acc = inc >= 200000 or fin >= 1000000 or net >= 5000000
        else:
            acc = net >= 5000000
        dec["eligibility"] = ("accredited_investor", "NI 45-106 s.1.1 (dealer-verified, SIMULATED)") if acc else \
            (("om_eligible", "offering memorandum exemption; investment limits apply") if p.get("province") else ("not_eligible", "no exemption"))
        dec["suitability"] = ("suitable", "high risk tolerance, long horizon") if p.get("risk_tolerance") == "high" and \
            p.get("horizon_years", 0) and int(p.get("horizon_years", 0)) >= 3 else ("unsuitable", "fund risk rating HIGH exceeds profile")
        if p.get("entity_type", "individual") == "individual":
            dec["beneficial_ownership"] = ("not_applicable", "individual")
        else:
            dec["beneficial_ownership"] = ("confirmed", "owners >=25% identified") if p.get("beneficial_owners") else ("required", "list owners >= 25%")
        ok = (dec["sanctions_pep"][0] == "clear" and dec["kyc"][0] == "verified" and dec["eligibility"][0] != "not_eligible"
              and dec["suitability"][0] == "suitable" and dec["beneficial_ownership"][0] in ("confirmed", "not_applicable"))
        status = "approved" if ok else ("rejected" if dec["sanctions_pep"][0] == "hit" or dec["eligibility"][0] == "not_eligible" else "action_required")
        t = self.sim.clock()
        for k, (res, det) in dec.items():
            self.c.execute("INSERT INTO adm_decisions(case_ref,kind,result,detail,ts) VALUES(?,?,?,?,?)", (case_ref, k, res, det, t))
        self.c.execute("UPDATE adm_cases SET status=? WHERE ref=?", (status, case_ref))
        return self.case(case_ref)

    def id_verification(self, case_ref: str) -> dict | None:
        """Structured record of how the administrator verified identity (SIMULATED; masked document number only)."""
        r = self.c.execute("SELECT * FROM adm_cases WHERE ref=?", (case_ref,)).fetchone()
        k = self.c.execute("SELECT * FROM adm_decisions WHERE case_ref=? AND kind='kyc' ORDER BY id DESC LIMIT 1", (case_ref,)).fetchone()
        if not r or not k or k["result"] != "verified":
            return None
        p = json.loads(r["payload"])
        d = dt.date.fromtimestamp(k["ts"])
        return {"method": "government_photo_id", "doc_type": p.get("id_type"), "issuing_jurisdiction": p.get("province") or p.get("country"),
                "doc_number_last4": str(p.get("id_last4")), "expiry": d.replace(year=d.year + 5).isoformat(), "verified_on": d.isoformat(),
                "manner": "remote_authenticated", "liveness": "passed (SIMULATED)"}

    def case(self, case_ref: str) -> dict:
        r = self.c.execute("SELECT * FROM adm_cases WHERE ref=?", (case_ref,)).fetchone()
        if not r:
            raise KeyError(case_ref)
        decs = [dict(d) for d in self.c.execute("SELECT kind,result,detail,ts FROM adm_decisions WHERE case_ref=? ORDER BY id", (case_ref,))]
        latest = {}
        for d in decs:
            latest[d["kind"]] = d
        return {"ref": case_ref, "status": r["status"], "decisions": list(latest.values())}

    # ---- subscriptions
    def subscription_instructions(self, case_ref: str, amount, currency: str) -> dict:
        if self.case(case_ref)["status"] != "approved":
            raise PermissionError("administrator: investor not approved")
        if currency != "CAD":
            raise ValueError("administrator accepts CAD subscriptions only (SIMULATION)")
        ref = "SUB-" + secrets.token_hex(4).upper()
        t = self.sim.clock()
        self.c.execute("INSERT INTO adm_subs(reference,case_ref,amount,currency,status,received,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                       (ref, case_ref, str(q(amount)), currency, "awaiting_funds", "0", t, t))
        cutoff = month_end(dt.date.fromtimestamp(t))
        return {"reference": ref, "pay_to": TRUST_ACCOUNT, "amount": str(q(amount)), "currency": currency,
                "cutoff": cutoff.isoformat(), "dealing": f"next NAV after funds clear (month-end {cutoff.isoformat()})",
                "memo": f"Include reference {ref} in the payment memo. Pay from an account in your own name."}

    def receive_payment(self, reference: str, amount, method: str = "eft", originator: dict | None = None) -> dict:
        """SIM HOOK: the investor's EFT/wire lands in the administrator's trust account (custodian line).
        method: eft | wire_domestic | wire_international | cash | virtual_currency; originator: {name, address, country,
        account, institution} as the payment carried it (travel-rule data)."""
        s = self.c.execute("SELECT * FROM adm_subs WHERE reference=?", (reference,)).fetchone()
        if not s:
            raise KeyError(reference)
        if s["status"] not in ("awaiting_funds", "funds_received"):
            raise ValueError(f"subscription {reference} is {s['status']}")
        rec = D(s["received"]) + D(amount)
        self.sim.line(TRUST, D(amount), f"incoming subscription {reference}", reference, method, originator)
        self.c.execute("UPDATE adm_subs SET received=?, status=?, updated=? WHERE reference=?",
                       (str(q(rec)), "funds_received" if rec >= D(s["amount"]) else "awaiting_funds", self.sim.clock(), reference))
        return dict(self.c.execute("SELECT * FROM adm_subs WHERE reference=?", (reference,)).fetchone())

    def subscriptions(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM adm_subs ORDER BY created")]

    # ---- redemptions
    def submit_redemption(self, case_ref, units, request_ref, bank_token, dealing_date) -> str:
        prev = self.c.execute("SELECT ref FROM adm_reds WHERE request_ref=?", (request_ref,)).fetchone()
        if prev:
            return prev[0]                                # idempotent
        held = D(self.register().get(case_ref, 0))
        pend = sum((D(r[0]) for r in self.c.execute("SELECT units FROM adm_reds WHERE case_ref=? AND status IN ('received','accepted')", (case_ref,))), Decimal(0))
        if D(units) <= 0 or D(units) + pend > held:
            raise ValueError("administrator: units exceed register holdings")
        ref = "RED-" + secrets.token_hex(4).upper()
        self.c.execute("INSERT INTO adm_reds(ref,case_ref,units,request_ref,bank_token,status,dealing_date,created) VALUES(?,?,?,?,?,?,?,?)",
                       (ref, case_ref, str(D(units)), request_ref, bank_token, "accepted", dealing_date, self.sim.clock()))
        return ref

    def redemptions(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM adm_reds ORDER BY created")]

    def release_payout(self, admin_ref, release_ref, approvers) -> dict:
        r = self.c.execute("SELECT * FROM adm_reds WHERE ref=?", (admin_ref,)).fetchone()
        if not r:
            raise KeyError(admin_ref)
        if r["status"] == "paid":
            return dict(r)
        if r["status"] != "dealt":
            raise ValueError(f"administrator: redemption {admin_ref} is {r['status']}")
        if len(set(approvers)) < 2:
            raise PermissionError("administrator: two distinct authorised signatories required")
        self.sim.line(TRUST, -D(r["net"]), f"redemption payout {admin_ref} to verified account", release_ref)
        self.c.execute("UPDATE adm_reds SET status='paid', release_ref=?, approvers=?, paid=? WHERE ref=?",
                       (release_ref, json.dumps(sorted(set(approvers))), self.sim.clock(), admin_ref))
        return dict(self.c.execute("SELECT * FROM adm_reds WHERE ref=?", (admin_ref,)).fetchone())

    def payout_report(self) -> list[dict]:
        return [{"admin_ref": r["ref"], "release_ref": r["release_ref"], "net": r["net"], "paid": r["paid"]}
                for r in self.c.execute("SELECT * FROM adm_reds WHERE status='paid' ORDER BY paid")]

    # ---- register / NAV / dealing
    def register(self) -> dict[str, Decimal]:
        return {r["case_ref"]: D(r["units"]) for r in self.c.execute("SELECT * FROM adm_register")}

    def _net_assets(self) -> Decimal:
        return sum((self.sim.balance(a) for a in FUND_ACCOUNTS), Decimal(0)) - D(self.sim.kv("accrued_fees", "0"))

    def nav(self) -> dict:
        r = self.c.execute("SELECT * FROM adm_nav ORDER BY nav_date DESC LIMIT 1").fetchone()
        if not r:
            return {"nav_date": None, "nav_per_unit": "10.0000", "net_assets": "0", "units_outstanding": "0", "fund": self.fund_name}
        return {**dict(r), "fund": self.fund_name}

    def nav_history(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM adm_nav ORDER BY nav_date")]

    def deal(self, nav_date: str, gate_pct="10", nonresident_withholding="0.25", early_fee_pct="0") -> dict:
        """SIM HOOK (administrator month-end): strike NAV, issue units for cleared subscriptions, process accepted
        redemptions due on/before nav_date (pro-rata gate), accrue management fee, publish confirmations."""
        units_out = sum(self.register().values(), Decimal(0))
        na = self._net_assets()
        nav = q(na / units_out, "0.0001") if units_out > 0 else D(self.nav()["nav_per_unit"])
        if nav <= 0:
            raise ValueError("non-positive NAV")
        issued, dealt = [], []
        for s in self.c.execute("SELECT * FROM adm_subs WHERE status='funds_received'").fetchall():
            u = q(D(s["received"]) / nav, "0.0001")
            self.c.execute("UPDATE adm_register SET units=? WHERE case_ref=?", (str(D(self.register()[s["case_ref"]]) + u), s["case_ref"]))
            self.c.execute("UPDATE adm_subs SET status='units_issued', units=?, nav=?, nav_date=?, updated=? WHERE reference=?",
                           (str(u), str(nav), nav_date, self.sim.clock(), s["reference"]))
            self.sim.line(TRUST, -D(s["received"]), f"subscription {s['reference']} to fund custody", s["reference"])
            self.sim.line("custody:cad", D(s["received"]), f"subscription {s['reference']} from trust", s["reference"])
            issued.append(s["reference"])
        due = self.c.execute("SELECT * FROM adm_reds WHERE status='accepted' AND dealing_date<=? ORDER BY created", (nav_date,)).fetchall()
        total = sum((D(r["units"]) * nav for r in due), Decimal(0))
        cap = na * D(gate_pct) / 100
        ratio = min(Decimal(1), cap / total) if total > 0 else Decimal(1)
        for r in due:
            case = json.loads(self.c.execute("SELECT payload FROM adm_cases WHERE ref=?", (r["case_ref"],)).fetchone()[0])
            u = q(D(r["units"]) * ratio, "0.0001")
            gross = q(u * nav)
            fees = q(gross * D(early_fee_pct) / 100)
            wh = q((gross - fees) * D(nonresident_withholding)) if case.get("country", "CA") != "CA" else Decimal(0)
            net = gross - fees - wh
            self.c.execute("UPDATE adm_register SET units=? WHERE case_ref=?", (str(D(self.register()[r["case_ref"]]) - u), r["case_ref"]))
            self.sim.line("custody:cad", -gross, f"redemption {r['ref']} to trust", r["ref"])
            self.sim.line(TRUST, gross - wh, f"redemption {r['ref']} from custody (net of withholding)", r["ref"])
            self.c.execute("UPDATE adm_reds SET status='dealt', units_dealt=?, nav=?, gross=?, fees=?, withholding=?, net=? WHERE ref=?",
                           (str(u), str(nav), str(gross), str(fees), str(wh), str(net), r["ref"]))
            rest = D(r["units"]) - u
            if rest > 0:                                        # gated remainder carried to the next dealing date
                self.c.execute("INSERT INTO adm_reds(ref,case_ref,units,request_ref,bank_token,status,dealing_date,created) VALUES(?,?,?,?,?,?,?,?)",
                               (r["ref"] + "-G", r["case_ref"], str(rest), r["request_ref"] + "-gated", r["bank_token"], "accepted",
                                month_end(dt.date.fromisoformat(nav_date) + dt.timedelta(days=1)).isoformat(), self.sim.clock()))
            dealt.append(r["ref"])
        units_after = sum(self.register().values(), Decimal(0))
        na_after = self._net_assets()
        fee = q(na_after * self.mgmt / 12)
        self.sim.set_kv("accrued_fees", str(q(D(self.sim.kv("accrued_fees", "0")) + fee)))
        na_after -= fee
        nav_after = q(na_after / units_after, "0.0001") if units_after > 0 else nav
        self.c.execute("INSERT OR REPLACE INTO adm_nav VALUES(?,?,?,?)", (nav_date, str(nav_after), str(q(na_after)), str(units_after)))
        return {"nav_date": nav_date, "dealing_nav": str(nav), "closing_nav": str(nav_after), "issued": issued, "redeemed": dealt,
                "gate_ratio": str(q(ratio, "0.0001")), "mgmt_fee_accrued": str(fee)}


class FakeCustodian:
    name, kind, enabled = "fake-custodian (offline simulation)", "Custodian", True

    def __init__(self, sim: SimDB):
        self.sim = sim

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "enabled": True, "mode": "offline fake"}

    def statement(self) -> dict:
        accts = (TRUST,) + FUND_ACCOUNTS
        return {"as_of": self.sim.clock(), "accounts": {a: str(q(self.sim.balance(a))) for a in accts},
                "lines": [dict(r) for r in self.sim.c.execute("SELECT * FROM cust_lines ORDER BY id DESC LIMIT 200")]}

    def _lines(self, account, start_ts=None, end_ts=None):
        q_ = "SELECT * FROM cust_lines WHERE account=?"
        args: list = [account]
        if start_ts is not None:
            q_ += " AND ts>=?"; args.append(start_ts)
        if end_ts is not None:
            q_ += " AND ts<?"; args.append(end_ts)
        return [dict(r) for r in self.sim.c.execute(q_ + " ORDER BY id", args)]

    def _is_book_transfer(self, r) -> bool:
        """Internal transfer between custody accounts (same ref, opposite leg in another account at the same time)."""
        return bool(r["ref"]) and self.sim.c.execute(
            "SELECT 1 FROM cust_lines WHERE ref=? AND account<>? AND ts=? AND CAST(amount AS REAL) < 0 = ?",
            (r["ref"], r["account"], r["ts"], D(r["amount"]) > 0)).fetchone() is not None

    SUBFAMILY = {"wire_international": "XBCT", "cash": "CDPT", "virtual_currency": "VCOM", "wire_domestic": "DMCT", "eft": "DMCT"}

    def _entry(self, r) -> dict:
        m = self.sim.c.execute("SELECT method, originator FROM cust_line_meta WHERE line_id=?", (r["id"],)).fetchone()
        orig = json.loads(m["originator"]) if m and m["originator"] else {}
        sub = "BOOK" if self._is_book_transfer(r) else self.SUBFAMILY.get(m["method"] if m else "eft", "DMCT")
        return {"amount": D(r["amount"]), "booking_date": dt.date.fromtimestamp(r["ts"]).isoformat(),
                "servicer_ref": f"CL{r['id']:08d}", "end_to_end_id": (r["ref"] or None), "remittance": r["memo"],
                "sub_family": sub, "counterparty": orig.get("name"), "counterparty_country": orig.get("country"),
                "counterparty_address": orig.get("address"), "counterparty_account": orig.get("account"),
                "booking_ts": r["ts"]}

    def camt053(self, from_date: str | None = None, to_date: str | None = None) -> str:
        """Custodian statement for all fund + trust accounts as ISO 20022 camt.053.001.08 (what a real custodian
        delivers by SFTP/host-to-host; here generated from the offline ledger)."""
        from atlas.ledgers.banking.iso20022 import camt
        now = self.sim.clock()
        to_d = dt.date.fromisoformat(to_date) if to_date else dt.date.fromtimestamp(now)
        fr_d = dt.date.fromisoformat(from_date) if from_date else to_d.replace(day=1)
        start = dt.datetime.combine(fr_d, dt.time()).timestamp()
        end = dt.datetime.combine(to_d + dt.timedelta(days=1), dt.time()).timestamp()
        sts = []
        for a in (TRUST,) + FUND_ACCOUNTS:
            before = sum((D(r["amount"]) for r in self._lines(a, None, start)), Decimal(0))
            ents = [self._entry(r) for r in self._lines(a, start, end)]
            sts.append({"id": f"STMT-{ACCOUNT_IDS[a]}-{to_d:%Y%m%d}"[:35], "account": ACCOUNT_IDS[a], "currency": "CAD",
                        "opening": before, "from": fr_d.isoformat(), "to": to_d.isoformat(), "entries": ents})
        return camt.build_camt053(f"CAMT053-{to_d:%Y%m%d}-{int(now) % 100000:05d}", now, sts, TRUST_ACCOUNT["swift"])

    def camt054(self, since_ts: float | None = None) -> str:
        """Credit notifications on the administrator trust account (camt.054.001.08), used to match incoming
        subscription money to SUB- references."""
        from atlas.ledgers.banking.iso20022 import camt
        now = self.sim.clock()
        ents = [self._entry(r) for r in self._lines(TRUST, since_ts, None) if D(r["amount"]) > 0]
        return camt.build_camt054(f"CAMT054-{int(now)}", now, ACCOUNT_IDS[TRUST], "CAD", ents, TRUST_ACCOUNT["swift"])

    def mark_market(self, account: str, pct) -> Decimal:
        """SIM HOOK: market move on a fund broker account."""
        if account not in FUND_ACCOUNTS[1:]:
            raise ValueError(account)
        chg = q(self.sim.balance(account) * D(pct) / 100)
        self.sim.line(account, chg, f"mark-to-market {pct}% (SIMULATED)")
        return chg


class FakePayoutRail:
    kind, enabled = "PayoutRail", True

    def __init__(self, sim: SimDB, rail: str):
        self.sim, self.rail = sim, rail
        self.name = f"fake-{rail} (offline simulation; partner trust account)"

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "enabled": True, "mode": "offline fake"}

    def payout(self, reference, amount, currency, account) -> str:
        prev = self.sim.c.execute("SELECT ref FROM rail_payouts WHERE reference=?", (reference,)).fetchone()
        if prev:
            return prev[0]
        ref = f"{self.rail.upper()}-" + secrets.token_hex(4).upper()
        self.sim.c.execute("INSERT INTO rail_payouts VALUES(?,?,?,?,?,?,?,?)", (ref, self.rail, reference, str(q(amount)), currency,
                                                                                 str(account.get("account_number", ""))[-4:], "paid", self.sim.clock()))
        return ref

    def report(self) -> list[dict]:
        return [dict(r) for r in self.sim.c.execute("SELECT * FROM rail_payouts WHERE rail=? ORDER BY ts", (self.rail,))]


class FakeBankVerification:
    """Offline stand-in for Plaid Link / Flinks Connect. scenario='own' returns an account in the investor's
    name; 'third_party' returns someone else's account (must be refused for payouts)."""
    kind, enabled = "BankVerification", True

    def __init__(self, sim: SimDB, provider="plaid"):
        self.sim, self.provider = sim, provider
        self.name = f"fake-{provider} (offline simulation)"

    def info(self) -> dict:
        return {"name": self.name, "kind": self.kind, "enabled": True, "mode": "offline fake", "institutions": sorted(INSTITUTIONS)}

    def start(self, investor_ref: str, holder_hint: str = "") -> str:
        """holder_hint stands in for the name on file at the simulated bank (a real provider returns the bank's own record)."""
        tok = "link-sim-" + secrets.token_hex(8)
        self.sim.c.execute("INSERT INTO bv_links(token,investor_ref,holder,ts) VALUES(?,?,?,?)", (tok, investor_ref, holder_hint, self.sim.clock()))
        return tok

    def complete(self, link_token: str, institution: str, scenario: str = "own") -> str:
        if institution not in INSTITUTIONS:
            raise ValueError("unknown institution")
        if scenario not in ("own", "third_party", "joint", "close"):
            raise ValueError("scenario")
        pub = "public-sim-" + secrets.token_hex(8)
        n = self.sim.c.execute("UPDATE bv_links SET public_token=?, institution=?, scenario=? WHERE token=? AND public_token IS NULL",
                               (pub, institution, scenario, link_token)).rowcount
        if n != 1:
            raise ValueError("invalid or used link token")
        return pub

    def fetch(self, public_token: str) -> dict:
        r = self.sim.c.execute("SELECT * FROM bv_links WHERE public_token=?", (public_token,)).fetchone()
        if not r:
            raise KeyError("public token")
        inst_no, inst_name = INSTITUTIONS[r["institution"]]
        own = r["holder"] or "Account Holder"
        first, _, rest = own.partition(" ")
        holder = {"own": own, "third_party": "Unrelated Third Party", "joint": f"{own} & Partner",
                  "close": f"{first} Q. {rest}".strip()}[r["scenario"]]          # close: middle initial on the bank record
        seed = int(r["token"][-6:], 16)
        return {"provider": self.provider, "holder_name": holder, "institution": inst_name, "institution_number": inst_no,
                "transit": f"{seed % 100000:05d}", "account_number": f"{(seed * 7919) % 10**7:07d}", "account_type": "chequing",
                "currency": "CAD", "verification_ref": public_token, "link_subject": r["investor_ref"]}


class PartnerSet:
    def __init__(self, administrator, custodian, rails: dict, bank_verification):
        self.administrator, self.custodian, self.rails, self.bank_verification = administrator, custodian, rails, bank_verification

    def info(self) -> list[dict]:
        out = [self.administrator.info(), self.custodian.info(), self.bank_verification.info()] + [r.info() for r in self.rails.values()]
        out += [cls().info() for cls in (SGGGStyleAdministrator, TrustCustodian, ZumRails, VoPay, Plaid, Flinks)]
        return out


def fake_partners(sim_path: str, clock=time.time) -> PartnerSet:
    sim = SimDB(sim_path, clock)
    return PartnerSet(FakeAdministrator(sim), FakeCustodian(sim),
                      {"zumrails": FakePayoutRail(sim, "zumrails"), "vopay": FakePayoutRail(sim, "vopay")},
                      FakeBankVerification(sim, "plaid"))


def real_partners() -> PartnerSet:
    """The production wiring: every adapter disabled (no network code in this build)."""
    return PartnerSet(SGGGStyleAdministrator(), TrustCustodian(), {"zumrails": ZumRails(), "vopay": VoPay()}, Plaid())
