"""Investor wallet service (SIMULATION ONLY). The app records and orchestrates; partners hold money and decide.

What the app does NOT do: hold or move investor money itself, keep stored-value balances, allow P2P transfers,
decide KYC / eligibility / suitability / sanctions (it only records the administrator's decisions), or pay to
any account other than a verified bank account in the investor's own name."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import secrets
import time
import unicodedata
from decimal import Decimal

from atlas.ledgers import audit
from atlas.ledgers.db import tx
from atlas.ledgers.money import D, q
from atlas.ledgers.statements import simple_pdf
from atlas.ledgers.banking.bankids import InvalidIdentifier, contains_pan, validate_ca_account
from atlas.ledgers.banking.addresses import address_lines, validate_address
from atlas.compliance.fintrac import Fintrac
from atlas.compliance.matching import name_score
from atlas.compliance.privacy import WITHHELD, Privacy
from atlas.compliance.screening import SanctionsBlock, Screener
from atlas.ledgers.wallet.partners import PartnerDisabled, PartnerSet, month_end
from atlas.ledgers.wallet.vault import Vault, VaultUnavailable, mask

SCHEMA = """
CREATE TABLE IF NOT EXISTS w_investors(id INTEGER PRIMARY KEY, legal_name TEXT, email TEXT, entity_type TEXT, country TEXT,
  province TEXT, pii_vault_id INTEGER, status TEXT, admin_ref TEXT, created_at REAL, submitted_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS w_decisions(id INTEGER PRIMARY KEY, investor_id INTEGER, kind TEXT, result TEXT, detail TEXT,
  source TEXT, admin_ref TEXT, decided_at REAL, recorded_at REAL);
CREATE TABLE IF NOT EXISTS w_bank(id INTEGER PRIMARY KEY, investor_id INTEGER, holder_name TEXT, institution TEXT,
  institution_number TEXT, transit_masked TEXT, account_masked TEXT, vault_id INTEGER, provider TEXT, verification_ref TEXT,
  name_match INTEGER, status TEXT, created_at REAL, verified_at REAL, ended_at REAL);
CREATE TABLE IF NOT EXISTS w_subs(id INTEGER PRIMARY KEY, investor_id INTEGER, idem_key TEXT UNIQUE, amount TEXT, currency TEXT,
  reference TEXT UNIQUE, status TEXT, received TEXT, units TEXT, nav TEXT, nav_date TEXT, instructions TEXT, requested_by TEXT,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS w_reds(id INTEGER PRIMARY KEY, investor_id INTEGER, idem_key TEXT UNIQUE, parent_id INTEGER, units TEXT,
  status TEXT, dealing_date TEXT, bank_id INTEGER, admin_ref TEXT, units_dealt TEXT, nav TEXT, gross TEXT, fees TEXT,
  withholding TEXT, net TEXT, gate_warning INTEGER, requested_by TEXT, forwarded_by TEXT, note TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS w_units(id INTEGER PRIMARY KEY, investor_id INTEGER, kind TEXT, units TEXT, ref TEXT UNIQUE, nav TEXT,
  nav_date TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS w_payouts(id INTEGER PRIMARY KEY, kind TEXT, investor_id INTEGER, redemption_id INTEGER, bank_id INTEGER,
  amount TEXT, currency TEXT, rail TEXT, purpose TEXT, status TEXT, requested_by TEXT, idem_key TEXT UNIQUE, release_ref TEXT,
  partner_ref TEXT, created_at REAL, paid_at REAL, note TEXT);
CREATE TABLE IF NOT EXISTS w_payout_approvals(payout_id INTEGER, approver TEXT, ts REAL, UNIQUE(payout_id, approver));
CREATE TABLE IF NOT EXISTS w_name_reviews(id INTEGER PRIMARY KEY, bank_id INTEGER UNIQUE, investor_id INTEGER, holder_name TEXT,
  legal_name TEXT, score REAL, status TEXT, reviewer TEXT, reason TEXT, created_at REAL, reviewed_at REAL);
CREATE TABLE IF NOT EXISTS w_recon(id INTEGER PRIMARY KEY, ts REAL, status TEXT, summary TEXT, breaks TEXT);
CREATE TRIGGER IF NOT EXISTS w_units_immutable_u BEFORE UPDATE ON w_units BEGIN SELECT RAISE(ABORT, 'unit ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS w_units_immutable_d BEFORE DELETE ON w_units BEGIN SELECT RAISE(ABORT, 'unit ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS w_decisions_immutable_u BEFORE UPDATE ON w_decisions BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS w_decisions_immutable_d BEFORE DELETE ON w_decisions BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
"""

DEFAULT_TERMS = {
    "notice_days": 30, "dealing": "monthly, month-end NAV", "lockup_days": 365, "gate_pct": 10,
    "min_subscription_cad": 25000, "om_12m_cap_cad": 10000, "min_redemption_cad": 1000, "min_holding_cad": 5000,
    "early_redemption_fee_pct": 0, "bank_cooling_off_hours": 24, "nonresident_withholding": 0.25,
    "source": "offering memorandum terms (SIMULATION placeholders; confirm with counsel)"}
NAME_REVIEW_MIN = 0.80      # holder-name similarity that goes to staff review instead of automatic rejection
REQUIRED = ("legal_name", "email", "entity_type", "country", "province", "dob_or_incorporation", "address", "occupation",
            "income", "financial_assets", "net_assets", "risk_tolerance", "horizon_years", "objective", "id_type", "id_last4")
PUBLIC_FIELDS = ("legal_name", "email", "entity_type", "country", "province")
DECISION_KINDS = ("kyc", "eligibility", "suitability", "sanctions_pep", "beneficial_ownership")
OPEN_PAYOUT = ("pending_approval",)


class WalletError(PermissionError):
    ...


class SanctionsHold(WalletError):
    pass


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(mr|mrs|ms|dr|mme|m)\b\.?", " ", s)
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    return " ".join(sorted(s.split()))


def _plain_actor(actor: str) -> str:
    return actor.split(":", 1)[1] if ":" in actor else actor


class Wallet:
    def __init__(self, c, partners: PartnerSet, approvers=None, vault: Vault | None = None, clock=time.time):
        self.c, self.p, self.auth, self._vault, self.clock = c, partners, approvers, vault, clock
        c.executescript(SCHEMA)
        c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
        c.execute("INSERT OR IGNORE INTO settings VALUES('wallet_terms', ?)", (json.dumps(DEFAULT_TERMS),))

    # ------------------------------------------------------------------ plumbing
    @property
    def vault(self) -> Vault:
        if self._vault is None:
            self._vault = Vault(self.c, clock=self.clock)       # raises VaultUnavailable if no key
        return self._vault

    def terms(self) -> dict:
        return {**DEFAULT_TERMS, **json.loads(self.c.execute("SELECT v FROM settings WHERE k='wallet_terms'").fetchone()[0])}

    def off_platform_refs(self) -> list[str]:
        r = self.c.execute("SELECT v FROM settings WHERE k='wallet_off_platform_refs'").fetchone()
        return json.loads(r[0]) if r else []

    def set_off_platform_refs(self, actor: str, refs: list[str]) -> None:
        self.c.execute("INSERT OR REPLACE INTO settings VALUES('wallet_off_platform_refs', ?)", (json.dumps(sorted(set(refs))),))
        self._a(actor, "recon.off_platform_refs", refs=sorted(set(refs)))

    def _a(self, actor, action, **d):
        audit.append(self.c, actor, "wallet." + action, d, self.clock)

    @property
    def screening(self) -> Screener:
        if getattr(self, "_screener", None) is None:
            self._screener = Screener(self.c, self.clock, audit=lambda actor, action, **d: self._a(actor, action, **d), auth=self.auth,
                                      on_confirm=self._sanctions_confirmed)
        return self._screener

    @property
    def fintrac(self) -> Fintrac:
        if getattr(self, "_fintrac", None) is None:
            self._fintrac = Fintrac(self.c, self.clock, audit=lambda actor, action, **d: self._a(actor, action, **d))
        return self._fintrac

    @property
    def privacy(self) -> Privacy:
        if getattr(self, "_privacy", None) is None:
            self._privacy = Privacy(self.c, self.clock, audit=lambda actor, action, **d: self._a(actor, action, **d))
        return self._privacy

    def access_export(self, actor: str, iid, request_id: int | None = None) -> dict:
        """Everything held about the investor that they are entitled to see (PIPEDA principle 4.9 / Law 25 s.27).
        Full bank numbers stay masked (the investor already has them); screening/FINTRAC data is withheld and listed."""
        import hashlib
        inv = self.investor(iid)
        units = self.c.execute("SELECT kind,units,ref,nav,ts FROM w_units WHERE investor_id=? ORDER BY id", (int(iid),)).fetchall()
        out = {"generated_at": dt.datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds"), "simulation": True,
               "investor": {k: inv[k] for k in ("id", "legal_name", "email", "entity_type", "country", "province", "status", "created_at")},
               "personal_information": self.pii(iid), "decisions": self.decisions(iid), "bank_accounts": self.banks(iid),
               "subscriptions": [dict(r) for r in self.c.execute("SELECT * FROM w_subs WHERE investor_id=? ORDER BY id", (int(iid),))],
               "redemptions": [dict(r) for r in self.c.execute("SELECT * FROM w_reds WHERE investor_id=? ORDER BY id", (int(iid),))],
               "payouts": [{k: r[k] for k in r.keys() if k not in ("release_ref",)} for r in
                           self.c.execute("SELECT * FROM w_payouts WHERE investor_id=? ORDER BY id", (int(iid),))],
               "unit_ledger": [dict(r) for r in units], "consents": self.privacy.consents(iid),
               "identity_verification": [{k: v for k, v in x.items() if k in ("method", "verified_on", "performed_by")}
                                         for x in self.fintrac.id_verifications(iid)],
               "withheld": WITHHELD}
        blob = json.dumps(out, sort_keys=True, default=str)
        sha = hashlib.sha256(blob.encode()).hexdigest()
        if request_id is not None:
            self.privacy.complete_access_request(actor, int(request_id), sha)
        self._a(actor, "privacy.access_export", investor=int(iid), sha256=sha[:16])
        return {"sha256": sha, "data": out}

    def _sanctions_confirmed(self, actor: str, hit: dict) -> None:
        """Confirmed match: property stays frozen (gate) and a listed-person property record is drafted."""
        iid = hit["investor_id"]
        nav = self.nav()
        u = self.units(iid)
        prop = [{"type": "fund units", "units": str(u), "nav_per_unit": nav.get("nav_per_unit"), "nav_date": nav.get("nav_date"),
                 "value_cad": str(q(u * D(nav.get("nav_per_unit") or 0)))}]
        for r in self.c.execute("SELECT reference, received FROM w_subs WHERE investor_id=? AND status IN ('awaiting_funds','funds_received')", (int(iid),)):
            if D(r["received"] or 0) > 0:
                prop.append({"type": "subscription cash held in administrator trust", "reference": r["reference"], "value_cad": r["received"]})
        self.fintrac.record_listed_property(actor, iid, hit, prop)

    def fintrac_scan(self, actor: str = "system", camt054: str | None = None) -> dict:
        """Feed trust-account receipts (camt.054) into FINTRAC record-keeping (threshold + 24-hour rule, travel rule)."""
        from atlas.ledgers.banking.iso20022 import camt
        from atlas.ledgers.wallet.partners import ACCOUNT_IDS, TRUST, TRUST_ACCOUNT
        xml = camt054 or (self.p.custodian.camt054() if hasattr(self.p.custodian, "camt054") else None)
        if not xml:
            return {"scanned": 0}
        refs = {r["reference"]: r["investor_id"] for r in self.c.execute("SELECT reference, investor_id FROM w_subs")}
        ben = {"name": TRUST_ACCOUNT["beneficiary"], "address": "SIMULATED trust account address, Toronto ON CA",
               "account": ACCOUNT_IDS[TRUST]}
        n = recs = 0
        for r in camt.parse(xml)["reports"]:
            res = self.fintrac.scan_camt054(actor, r["entries"], refs, ben)
            n += len(res)
            recs += sum(1 for x in res if x.get("record") and not x.get("duplicate"))
        return {"scanned": n, "records_touched": recs}

    def _sanctions(self, iid, context: str, actor: str = "system", subjects: list[dict] | None = None) -> None:
        """Screen (when subjects given) then gate: raises SanctionsHold while a hit is open/confirmed or lists are missing."""
        sc = self.screening
        if subjects is not None and sc.active_lists():
            sc.screen(actor, int(iid), subjects, context)
        try:
            sc.gate(iid, context)
        except SanctionsBlock as e:
            self._a(actor, "sanctions.blocked", investor=int(iid), context=context, reason=str(e)[:200])
            raise SanctionsHold(str(e)) from e

    def rescreen_all(self, actor: str = "system") -> dict:
        res = {"screened": 0, "new_hits": 0}
        for r in self.c.execute("SELECT id FROM w_investors WHERE status<>'draft' ORDER BY id").fetchall():
            out = self.screening.screen(actor, r[0], Screener.subjects(self.investor(r[0]), self.pii(r[0])), "rescreen")
            res["screened"] += 1
            res["new_hits"] += len(out["new_hits"])
        self._a(actor, "sanctions.rescreen", **res)
        return res

    def _kill(self) -> bool:
        r = self.c.execute("SELECT v FROM settings WHERE k='kill'").fetchone()
        return bool(r and r[0] == "1")

    def investor(self, iid) -> dict:
        r = self.c.execute("SELECT * FROM w_investors WHERE id=?", (int(iid),)).fetchone()
        if not r:
            raise KeyError(f"investor {iid}")
        return dict(r)

    # ------------------------------------------------------------------ onboarding (app collects; partner decides)
    def _validate(self, data: dict) -> dict:
        if data.get("address_structured"):
            data = dict(data, address_structured=validate_address(data["address_structured"]))
            a = data["address_structured"]
            data["address"] = ", ".join(address_lines(a))      # structured address is authoritative
            if a["country"] == "CA" and str(data.get("country", "")).upper() == "CA" and data.get("province") and a["province"] != str(data["province"]).upper():
                raise ValueError("address province does not match the investor's province")
        missing = [k for k in REQUIRED if str(data.get(k, "")).strip() == ""]
        if missing:
            raise ValueError("missing fields: " + ", ".join(missing))
        if data["entity_type"] not in ("individual", "corporation", "trust"):
            raise ValueError("entity_type must be individual | corporation | trust")
        if data["risk_tolerance"] not in ("low", "medium", "high"):
            raise ValueError("risk_tolerance must be low | medium | high")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", str(data["email"]), re.I):
            raise ValueError("invalid email")
        if not re.fullmatch(r"\d{4}", str(data["id_last4"])):
            raise ValueError("id_last4: 4 digits (never the full ID number)")
        if any(contains_pan(v) for v in data.values() if isinstance(v, (str, int))):
            raise ValueError("payment card numbers are never accepted (out of PCI DSS scope by design)")
        if any(k in data for k in ("sin", "id_number", "account_number")):
            raise ValueError("do not send full SIN / ID / account numbers; the administrator collects them directly")
        for k in ("income", "financial_assets", "net_assets"):
            if D(data[k]) < 0:
                raise ValueError(f"{k} must be >= 0")
        clean = {k: data[k] for k in REQUIRED + ("pep", "beneficial_owners", "phone", "address_structured") if k in data}
        clean["horizon_years"] = int(clean["horizon_years"])
        return clean

    def create_investor(self, actor: str, data: dict) -> int:
        d = self._validate(data)
        vid = self.vault.put("investor_pii", json.dumps(d, sort_keys=True, default=str))
        t = self.clock()
        iid = self.c.execute("INSERT INTO w_investors(legal_name,email,entity_type,country,province,pii_vault_id,status,created_at,updated_at)"
                             " VALUES(?,?,?,?,?,?,?,?,?)", (*[str(d[k]) for k in PUBLIC_FIELDS], vid, "draft", t, t)).lastrowid
        self._a(actor, "investor.create", id=iid)
        return iid

    def pii(self, iid) -> dict:
        return json.loads(self.vault.get(self.investor(iid)["pii_vault_id"]))

    def update_investor(self, actor: str, iid, data: dict) -> None:
        inv = self.investor(iid)
        if inv["status"] not in ("draft", "action_required"):
            raise WalletError(f"investor is {inv['status']}; data changes go through the administrator")
        d = self._validate({**self.pii(iid), **data})
        vid = self.vault.put("investor_pii", json.dumps(d, sort_keys=True, default=str))
        self.c.execute("UPDATE w_investors SET legal_name=?,email=?,entity_type=?,country=?,province=?,pii_vault_id=?,updated_at=? WHERE id=?",
                       (*[str(d[k]) for k in PUBLIC_FIELDS], vid, self.clock(), int(iid)))
        self._a(actor, "investor.update", id=int(iid), fields=sorted(data))

    def submit_onboarding(self, actor: str, iid) -> str:
        inv = self.investor(iid)
        if inv["status"] not in ("draft", "action_required"):
            raise WalletError(f"investor is {inv['status']}")
        payload = self.pii(iid)
        self._sanctions(iid, "onboarding", actor, Screener.subjects(inv, payload))
        if inv["admin_ref"]:
            self.p.administrator.update_case(inv["admin_ref"], payload)
            ref = inv["admin_ref"]
        else:
            ref = self.p.administrator.open_case(payload)
        self.c.execute("UPDATE w_investors SET status='submitted', admin_ref=?, submitted_at=?, updated_at=? WHERE id=?",
                       (ref, self.clock(), self.clock(), int(iid)))
        self._a(actor, "investor.submit", id=int(iid), admin_ref=ref)
        return ref

    def sync_onboarding(self, actor: str, iid) -> dict:
        """Record the administrator's decisions (append-only). The app never sets a decision itself."""
        inv = self.investor(iid)
        if not inv["admin_ref"]:
            raise WalletError("not submitted to the administrator yet")
        case = self.p.administrator.case(inv["admin_ref"])
        seen = {(r["kind"], r["result"], r["decided_at"]) for r in
                self.c.execute("SELECT kind,result,decided_at FROM w_decisions WHERE investor_id=?", (int(iid),))}
        new = 0
        for d in case["decisions"]:
            if d["kind"] in DECISION_KINDS and (d["kind"], d["result"], d["ts"]) not in seen:
                self.c.execute("INSERT INTO w_decisions(investor_id,kind,result,detail,source,admin_ref,decided_at,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                               (int(iid), d["kind"], d["result"], d["detail"], self.p.administrator.name, inv["admin_ref"], d["ts"], self.clock()))
                new += 1
        status = {"approved": "approved", "rejected": "rejected", "action_required": "action_required"}.get(case["status"], "under_review")
        idv = getattr(self.p.administrator, "id_verification", lambda ref: None)(inv["admin_ref"])
        if idv and not self.fintrac.id_verifications(iid):
            m = idv.pop("method")
            self.fintrac.record_id_verification(actor, int(iid), m, idv, f"{self.p.administrator.name} (agent/mandatary of the reporting entity)")
        self.c.execute("UPDATE w_investors SET status=?, updated_at=? WHERE id=?", (status, self.clock(), int(iid)))
        self._a(actor, "investor.sync", id=int(iid), status=status, new_decisions=new)
        return {"status": status, "new_decisions": new}

    def decisions(self, iid) -> list[dict]:
        out = {}
        for r in self.c.execute("SELECT * FROM w_decisions WHERE investor_id=? ORDER BY id", (int(iid),)):
            out[r["kind"]] = dict(r)
        return [out.get(k, {"kind": k, "result": "pending", "detail": "awaiting administrator", "source": None}) for k in DECISION_KINDS]

    def _eligibility(self, iid) -> str:
        return next((d["result"] for d in self.decisions(iid) if d["kind"] == "eligibility"), "pending")

    def _need_approved(self, iid) -> dict:
        inv = self.investor(iid)
        if inv["status"] != "approved":
            raise WalletError(f"investor onboarding is {inv['status']} (administrator approval required)")
        return inv

    # ------------------------------------------------------------------ bank verification
    def bank_link_start(self, iid) -> str:
        inv = self.investor(iid)
        if inv["status"] in ("draft", "rejected"):
            raise WalletError("submit onboarding before linking a bank account")
        return self.p.bank_verification.start(f"inv-{inv['id']}", inv["legal_name"])

    def bank_link_complete(self, actor: str, iid, link_token: str, institution: str, scenario: str = "own") -> dict:
        inv = self.investor(iid)
        bv = self.p.bank_verification
        pub = bv.complete(link_token, institution, scenario)
        acct = bv.fetch(pub)
        if acct.get("link_subject") not in (None, f"inv-{inv['id']}"):
            raise WalletError("bank link was started for a different investor")
        try:   # format check on the returned account (Payments Canada institution/transit, 7-12 digit account)
            validate_ca_account(acct["institution_number"], acct["transit"], acct["account_number"])
        except InvalidIdentifier as e:
            self._a(actor, "bank.invalid_account", investor=int(iid), reason=str(e))
            raise WalletError(f"bank verification returned an invalid Canadian account: {e}") from e
        self._sanctions(iid, "bank_link", actor, [{"name": acct["holder_name"], "role": "bank_holder"}])
        match = norm_name(acct["holder_name"]) == norm_name(inv["legal_name"])
        joint = bool(re.search(r"&|/|\band\b|\bet\b|\bor\b|\bou\b", acct["holder_name"], re.I))   # sole-name accounts only
        close = 0.0 if match or joint else name_score(acct["holder_name"], inv["legal_name"])
        vid = self.vault.put("bank_account", json.dumps({k: acct[k] for k in ("institution_number", "transit", "account_number", "holder_name")}))
        t = self.clock()
        status = "verified" if match else ("pending_name_review" if close >= NAME_REVIEW_MIN else "rejected_name_mismatch")
        with tx(self.c):
            if match:
                self.c.execute("UPDATE w_bank SET status='superseded', ended_at=? WHERE investor_id=? AND status='verified'", (t, int(iid)))
            bid = self.c.execute(
                "INSERT INTO w_bank(investor_id,holder_name,institution,institution_number,transit_masked,account_masked,vault_id,provider,"
                "verification_ref,name_match,status,created_at,verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(iid), acct["holder_name"], acct["institution"], acct["institution_number"], mask(acct["transit"], 2),
                 mask(acct["account_number"]), vid, acct["provider"], acct["verification_ref"][:12] + "…", int(match), status, t,
                 t if match else None)).lastrowid
        if status == "pending_name_review":
            self.c.execute("INSERT INTO w_name_reviews(bank_id,investor_id,holder_name,legal_name,score,status,created_at) VALUES(?,?,?,?,?,?,?)",
                           (bid, int(iid), acct["holder_name"], inv["legal_name"], round(close, 3), "pending", t))
        self._a(actor, "bank.verify", investor=int(iid), bank=bid, status=status, account=mask(acct["account_number"]))
        return self.bank(bid)

    def name_reviews(self, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM w_name_reviews" + (" WHERE status=?" if status else "") + " ORDER BY id DESC"
        return [dict(r) for r in self.c.execute(q, (status,) if status else ())]

    def review_bank_name(self, actor: str, bid, approve: bool, reason: str) -> dict:
        """Close-match holder name (e.g. middle name, initial, accents, 'Bob' vs 'Robert'): staff confirm it is the
        investor's own account against documents. Approval starts the cooling-off clock; rejection is final."""
        r = self.c.execute("SELECT * FROM w_name_reviews WHERE bank_id=? AND status='pending'", (int(bid),)).fetchone()
        if not r:
            raise WalletError("no pending name review for this bank account")
        if len(reason.strip()) < 10:
            raise WalletError("record what was checked (10+ characters)")
        t = self.clock()
        with tx(self.c):
            self.c.execute("UPDATE w_name_reviews SET status=?, reviewer=?, reason=?, reviewed_at=? WHERE id=?",
                           ("approved" if approve else "rejected", _plain_actor(actor), reason.strip(), t, r["id"]))
            if approve:
                self.c.execute("UPDATE w_bank SET status='superseded', ended_at=? WHERE investor_id=? AND status='verified'", (t, r["investor_id"]))
                self.c.execute("UPDATE w_bank SET status='verified', name_match=1, verified_at=? WHERE id=?", (t, int(bid)))
            else:
                self.c.execute("UPDATE w_bank SET status='rejected_name_mismatch' WHERE id=?", (int(bid),))
        self._a(actor, "bank.name_review", bank=int(bid), approved=bool(approve))
        return self.bank(bid)

    def bank(self, bid) -> dict:
        r = self.c.execute("SELECT * FROM w_bank WHERE id=?", (int(bid),)).fetchone()
        if not r:
            raise KeyError(f"bank {bid}")
        d = dict(r)
        d.pop("vault_id")
        cool = self.terms()["bank_cooling_off_hours"] * 3600
        d["usable_from"] = (d["verified_at"] or 0) + cool if d["status"] == "verified" else None
        d["usable"] = d["status"] == "verified" and bool(d["name_match"]) and self.clock() >= d["usable_from"]
        return d

    def banks(self, iid) -> list[dict]:
        return [self.bank(r[0]) for r in self.c.execute("SELECT id FROM w_bank WHERE investor_id=? ORDER BY id DESC", (int(iid),))]

    def verified_bank(self, iid) -> dict | None:
        r = self.c.execute("SELECT id FROM w_bank WHERE investor_id=? AND status='verified' ORDER BY id DESC LIMIT 1", (int(iid),)).fetchone()
        return self.bank(r[0]) if r else None

    def revoke_bank(self, actor: str, bid) -> None:
        self.c.execute("UPDATE w_bank SET status='revoked', ended_at=? WHERE id=? AND status='verified'", (self.clock(), int(bid)))
        self._a(actor, "bank.revoke", bank=int(bid))

    def _payout_account(self, iid, bid) -> dict:
        b = self.bank(bid)
        if b["investor_id"] != int(iid):
            raise WalletError("bank account belongs to another investor (no third-party payouts)")
        if b["status"] != "verified" or not b["name_match"]:
            raise WalletError("payout account is not a verified account in the investor's own name")
        if not b["usable"]:
            raise WalletError("payout account is in its cooling-off period after verification")
        raw = json.loads(self.vault.get(self.c.execute("SELECT vault_id FROM w_bank WHERE id=?", (int(bid),)).fetchone()[0]))
        approved = self.c.execute("SELECT 1 FROM w_name_reviews WHERE bank_id=? AND status='approved'", (int(bid),)).fetchone()
        if raw["holder_name"] != b["holder_name"] or (norm_name(raw["holder_name"]) != norm_name(self.investor(iid)["legal_name"]) and not approved):
            raise WalletError("holder name mismatch")
        return raw

    # ------------------------------------------------------------------ subscriptions
    def request_subscription(self, actor: str, iid, amount, idem_key: str, currency: str = "CAD") -> dict:
        prev = self.c.execute("SELECT * FROM w_subs WHERE idem_key=?", (idem_key,)).fetchone()
        if prev:
            if prev["investor_id"] != int(iid) or D(prev["amount"]) != D(amount):
                raise WalletError("idempotency key reused with different parameters")
            return self.subscription(prev["id"])
        inv = self._need_approved(iid)
        self._sanctions(iid, "subscription", actor)
        amt = D(amount)
        if not amt.is_finite() or amt <= 0:
            raise ValueError("amount must be positive")
        t = self.terms()
        elig = self._eligibility(iid)
        if elig == "accredited_investor" and amt < D(t["min_subscription_cad"]):
            raise WalletError(f"minimum subscription is CAD {t['min_subscription_cad']}")
        if elig == "om_eligible":
            year = sum((D(r[0]) for r in self.c.execute(
                "SELECT amount FROM w_subs WHERE investor_id=? AND status!='cancelled' AND created_at>=?", (int(iid), self.clock() - 365 * 86400))), Decimal(0))
            if year + amt > D(t["om_12m_cap_cad"]):
                raise WalletError(f"offering-memorandum 12-month investment cap CAD {t['om_12m_cap_cad']} (placeholder) exceeded")
        ins = self.p.administrator.subscription_instructions(inv["admin_ref"], amt, currency)
        now = self.clock()
        sid = self.c.execute("INSERT INTO w_subs(investor_id,idem_key,amount,currency,reference,status,received,instructions,requested_by,created_at,updated_at)"
                             " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (int(iid), idem_key, str(q(amt)), currency, ins["reference"], "instructed", "0",
                                                                 json.dumps(ins), actor, now, now)).lastrowid
        self._a(actor, "subscription.request", id=sid, investor=int(iid), amount=str(q(amt)), reference=ins["reference"])
        return self.subscription(sid)

    def subscription(self, sid) -> dict:
        r = self.c.execute("SELECT * FROM w_subs WHERE id=?", (int(sid),)).fetchone()
        if not r:
            raise KeyError(f"subscription {sid}")
        d = dict(r)
        d["instructions"] = json.loads(d["instructions"] or "{}")
        return d

    def cancel_subscription(self, actor: str, sid) -> None:
        if self.c.execute("UPDATE w_subs SET status='cancelled', updated_at=? WHERE id=? AND status='instructed'", (self.clock(), int(sid))).rowcount != 1:
            raise WalletError("only an unfunded (instructed) subscription can be cancelled")
        self._a(actor, "subscription.cancel", id=int(sid))

    # ------------------------------------------------------------------ redemptions
    def units(self, iid) -> Decimal:
        return sum((D(r[0]) for r in self.c.execute("SELECT units FROM w_units WHERE investor_id=?", (int(iid),))), Decimal(0))

    def nav(self) -> dict:
        return self.p.administrator.nav()

    def dealing_date(self, from_ts: float | None = None) -> str:
        d = dt.date.fromtimestamp(from_ts or self.clock()) + dt.timedelta(days=int(self.terms()["notice_days"]))
        return month_end(d).isoformat()

    def request_redemption(self, actor: str, iid, units, idem_key: str) -> dict:
        prev = self.c.execute("SELECT * FROM w_reds WHERE idem_key=?", (idem_key,)).fetchone()
        if prev:
            if prev["investor_id"] != int(iid) or D(prev["units"]) != D(units):
                raise WalletError("idempotency key reused with different parameters")
            return self.redemption(prev["id"])
        self._need_approved(iid)
        self._sanctions(iid, "redemption", actor)
        u = D(units)
        if not u.is_finite() or u <= 0:
            raise ValueError("units must be positive")
        t = self.terms()
        held = self.units(iid)
        pend = sum((D(r[0]) for r in self.c.execute(
            "SELECT units FROM w_reds WHERE investor_id=? AND status IN ('requested','forwarded')", (int(iid),))), Decimal(0))
        if u + pend > held:
            raise WalletError("units exceed holdings net of pending redemptions")
        first = self.c.execute("SELECT MIN(ts) FROM w_units WHERE investor_id=? AND kind='issue'", (int(iid),)).fetchone()[0]
        if first is None or self.clock() < first + int(t["lockup_days"]) * 86400:
            until = dt.date.fromtimestamp((first or self.clock()) + int(t["lockup_days"]) * 86400).isoformat()
            raise WalletError(f"lock-up: redemptions allowed from {until}")
        nav = D(self.nav()["nav_per_unit"])
        if u * nav < D(t["min_redemption_cad"]) and u != held - pend:
            raise WalletError(f"minimum redemption CAD {t['min_redemption_cad']}")
        rest = (held - pend - u) * nav
        if 0 < rest < D(t["min_holding_cad"]):
            raise WalletError(f"would leave CAD {q(rest)} < minimum holding {t['min_holding_cad']}; redeem all units instead")
        bank = self.verified_bank(iid)
        if not bank:
            raise WalletError("a verified bank account in the investor's own name is required before redeeming")
        na = D(self.nav()["net_assets"] or 0)
        pending_all = sum((D(r[0]) for r in self.c.execute("SELECT units FROM w_reds WHERE status IN ('requested','forwarded')")), Decimal(0))
        gate_warn = na > 0 and (pending_all + u) * nav > na * D(t["gate_pct"]) / 100
        now = self.clock()
        rid = self.c.execute("INSERT INTO w_reds(investor_id,idem_key,units,status,dealing_date,bank_id,gate_warning,requested_by,created_at,updated_at)"
                             " VALUES(?,?,?,?,?,?,?,?,?,?)", (int(iid), idem_key, str(u), "requested", self.dealing_date(), bank["id"],
                                                             int(gate_warn), actor, now, now)).lastrowid
        self._a(actor, "redemption.request", id=rid, investor=int(iid), units=str(u), gate_warning=bool(gate_warn))
        return self.redemption(rid)

    def redemption(self, rid) -> dict:
        r = self.c.execute("SELECT * FROM w_reds WHERE id=?", (int(rid),)).fetchone()
        if not r:
            raise KeyError(f"redemption {rid}")
        return dict(r)

    def forward_redemption(self, approver: str, rid) -> dict:
        r = self.redemption(rid)
        if r["status"] != "requested":
            raise WalletError(f"redemption is {r['status']}")
        self._sanctions(r["investor_id"], "redemption_forward", approver)
        inv = self.investor(r["investor_id"])
        ref = self.p.administrator.submit_redemption(inv["admin_ref"], D(r["units"]), f"wred-{r['id']}", f"bank:{r['bank_id']}", r["dealing_date"])
        self.c.execute("UPDATE w_reds SET status='forwarded', admin_ref=?, forwarded_by=?, updated_at=? WHERE id=?",
                       (ref, approver, self.clock(), int(rid)))
        self._a(approver, "redemption.forward", id=int(rid), admin_ref=ref)
        return self.redemption(rid)

    def reject_redemption(self, actor: str, rid, reason: str = "") -> None:
        if self.c.execute("UPDATE w_reds SET status='cancelled', note=?, updated_at=? WHERE id=? AND status='requested'",
                          (reason[:200], self.clock(), int(rid))).rowcount != 1:
            raise WalletError("only a request not yet forwarded to the administrator can be cancelled")
        self._a(actor, "redemption.cancel", id=int(rid), reason=reason[:200])

    # ------------------------------------------------------------------ sync from administrator
    def sync(self, actor: str = "system") -> dict:
        adm = self.p.administrator
        out = {"subs_updated": 0, "units_issued": 0, "redemptions_dealt": 0, "payouts_created": 0, "paid": 0}
        for s in adm.subscriptions():
            w = self.c.execute("SELECT * FROM w_subs WHERE reference=?", (s["reference"],)).fetchone()
            if not w or w["status"] == "cancelled":
                continue
            if s["status"] != w["status"] or s["received"] != w["received"]:
                self.c.execute("UPDATE w_subs SET status=?, received=?, units=?, nav=?, nav_date=?, updated_at=? WHERE id=?",
                               (s["status"], s["received"], s["units"], s["nav"], s["nav_date"], self.clock(), w["id"]))
                out["subs_updated"] += 1
            if s["status"] == "units_issued":
                if self.c.execute("INSERT OR IGNORE INTO w_units(investor_id,kind,units,ref,nav,nav_date,ts) VALUES(?,?,?,?,?,?,?)",
                                  (w["investor_id"], "issue", s["units"], "sub:" + s["reference"], s["nav"], s["nav_date"], self.clock())).rowcount:
                    out["units_issued"] += 1
        for a in adm.redemptions():
            base = a["request_ref"].removesuffix("-gated")
            rid = int(base.split("-")[1].split("-")[0]) if base.startswith("wred-") else None
            if rid is None:
                continue
            w = self.c.execute("SELECT * FROM w_reds WHERE admin_ref=?", (a["ref"],)).fetchone()
            if not w and a["request_ref"].endswith("-gated"):
                parent = self.redemption(rid)
                now = self.clock()
                cid = self.c.execute("INSERT INTO w_reds(investor_id,idem_key,parent_id,units,status,dealing_date,bank_id,admin_ref,requested_by,note,created_at,updated_at)"
                                     " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (parent["investor_id"], "gated:" + a["ref"], rid, a["units"], "forwarded",
                                                                          a["dealing_date"], parent["bank_id"], a["ref"], "administrator",
                                                                          "gated remainder carried forward", now, now)).lastrowid
                w = self.c.execute("SELECT * FROM w_reds WHERE id=?", (cid,)).fetchone()
            if not w:
                continue
            if a["status"] in ("dealt", "paid") and w["status"] == "forwarded":
                with tx(self.c):
                    st = "dealt" + (" (partially gated)" if D(a["units_dealt"]) < D(a["units"]) else "")
                    self.c.execute("UPDATE w_reds SET status=?, units_dealt=?, nav=?, gross=?, fees=?, withholding=?, net=?, updated_at=? WHERE id=?",
                                   ("dealt", a["units_dealt"], a["nav"], a["gross"], a["fees"], a["withholding"], a["net"], self.clock(), w["id"]))
                    if st.endswith("gated)"):
                        self.c.execute("UPDATE w_reds SET note=? WHERE id=?", ("partially gated by the administrator; remainder carried forward", w["id"]))
                    self.c.execute("INSERT OR IGNORE INTO w_units(investor_id,kind,units,ref,nav,nav_date,ts) VALUES(?,?,?,?,?,?,?)",
                                   (w["investor_id"], "redeem", str(-D(a["units_dealt"])), "red:" + a["ref"], a["nav"], a["dealing_date"], self.clock()))
                    self.c.execute("INSERT OR IGNORE INTO w_payouts(kind,investor_id,redemption_id,bank_id,amount,currency,rail,purpose,status,requested_by,idem_key,created_at)"
                                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("redemption", w["investor_id"], w["id"], w["bank_id"], a["net"], "CAD",
                                                                       "administrator EFT/wire", f"redemption {a['ref']} net proceeds", "pending_approval",
                                                                       "administrator", "red:" + a["ref"], self.clock()))
                out["redemptions_dealt"] += 1
                out["payouts_created"] += 1
            if a["status"] == "paid":
                n = self.c.execute("UPDATE w_payouts SET status='paid', paid_at=? WHERE idem_key=? AND status='released'",
                                   (a["paid"], "red:" + a["ref"])).rowcount
                self.c.execute("UPDATE w_reds SET status='paid', updated_at=? WHERE id=? AND status='dealt'", (self.clock(), w["id"]))
                out["paid"] += n
        out["fintrac_records"] = self.fintrac_scan(actor).get("records_touched", 0)
        self._a(actor, "sync", **out)
        return out

    # ------------------------------------------------------------------ payouts (two-person approval)
    def request_payout(self, actor: str, iid, amount, rail: str, purpose: str, idem_key: str) -> dict:
        """Non-fund payout (e.g. a referral reward) from a PSP partner's trust account; never investor capital."""
        prev = self.c.execute("SELECT id FROM w_payouts WHERE idem_key=?", (idem_key,)).fetchone()
        if prev:
            return self.payout(prev[0])
        self._need_approved(iid)
        self._sanctions(iid, "payout_request", actor)
        if rail not in self.p.rails:
            raise ValueError(f"unknown payout rail {rail}")
        amt = D(amount)
        if not amt.is_finite() or amt <= 0:
            raise ValueError("amount must be positive")
        bank = self.verified_bank(iid)
        if not bank:
            raise WalletError("no verified bank account in the investor's own name")
        pid = self.c.execute("INSERT INTO w_payouts(kind,investor_id,bank_id,amount,currency,rail,purpose,status,requested_by,idem_key,created_at)"
                             " VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("non_fund", int(iid), bank["id"], str(q(amt)), "CAD", rail, purpose[:200],
                                                               "pending_approval", actor, idem_key, self.clock())).lastrowid
        self._a(actor, "payout.request", id=pid, investor=int(iid), amount=str(q(amt)), rail=rail)
        return self.payout(pid)

    def payout(self, pid) -> dict:
        r = self.c.execute("SELECT * FROM w_payouts WHERE id=?", (int(pid),)).fetchone()
        if not r:
            raise KeyError(f"payout {pid}")
        d = dict(r)
        d["approvals"] = [a[0] for a in self.c.execute("SELECT approver FROM w_payout_approvals WHERE payout_id=? ORDER BY ts", (int(pid),))]
        d["required_approvals"] = 2
        b = self.bank(d["bank_id"]) if d["bank_id"] else None
        d["destination"] = f"{b['institution']} {b['account_masked']} ({b['holder_name']})" if b else None
        return d

    def approve_payout(self, pid, approver: str, passphrase: str, code: str) -> dict:
        self.auth.verify(approver, passphrase, code)
        p = self.payout(pid)
        if p["status"] not in OPEN_PAYOUT:
            raise WalletError(f"payout is {p['status']}")
        if self._kill():
            raise WalletError("payments kill switch engaged")
        if _plain_actor(p["requested_by"]) == approver:
            raise WalletError("the requester cannot approve their own payout")
        if approver in p["approvals"]:
            raise WalletError("already approved by this approver; a second, different person must approve")
        self._sanctions(p["investor_id"], "payout_approval", approver)
        self._payout_account(p["investor_id"], p["bank_id"])      # destination re-checked at every approval
        self.c.execute("INSERT INTO w_payout_approvals VALUES(?,?,?)", (int(pid), approver, self.clock()))
        self._a(approver, "payout.approve", id=int(pid))
        p = self.payout(pid)
        if len(set(p["approvals"])) >= 2:
            return self._release(p)
        return p

    def _release(self, p: dict) -> dict:
        self._sanctions(p["investor_id"], "payout_release")
        with tx(self.c):
            if self.c.execute("UPDATE w_payouts SET status='releasing' WHERE id=? AND status='pending_approval'", (p["id"],)).rowcount != 1:
                raise WalletError("payout already being released")
        release_ref = "REL-" + secrets.token_hex(4).upper()
        try:
            acct = self._payout_account(p["investor_id"], p["bank_id"])
            if p["kind"] == "redemption":
                red = self.redemption(p["redemption_id"])
                res = self.p.administrator.release_payout(red["admin_ref"], release_ref, p["approvals"])
                st, pref = ("paid" if res.get("status") == "paid" else "released"), red["admin_ref"]
            else:
                pref = self.p.rails[p["rail"]].payout(release_ref, D(p["amount"]), p["currency"], acct)
                st = "paid"
        except PartnerDisabled as e:
            self.c.execute("UPDATE w_payouts SET status='pending_approval', note=? WHERE id=?", (str(e)[:200], p["id"]))
            raise
        except Exception as e:
            self.c.execute("UPDATE w_payouts SET status='release_error', note=? WHERE id=?", (str(e)[:200], p["id"]))
            self._a("system", "payout.release_error", id=p["id"], error=str(e)[:200])
            raise
        self.c.execute("UPDATE w_payouts SET status=?, release_ref=?, partner_ref=?, paid_at=? WHERE id=?",
                       (st, release_ref, pref, self.clock() if st == "paid" else None, p["id"]))
        if p["kind"] == "redemption" and st == "paid":
            self.c.execute("UPDATE w_reds SET status='paid', updated_at=? WHERE id=?", (self.clock(), p["redemption_id"]))
        self._a("system", "payout.released", id=p["id"], release_ref=release_ref, partner_ref=pref, approvers=p["approvals"])
        return self.payout(p["id"])

    def reject_payout(self, actor: str, pid, reason: str = "") -> None:
        if self.c.execute("UPDATE w_payouts SET status='rejected', note=? WHERE id=? AND status='pending_approval'",
                          (reason[:200], int(pid))).rowcount != 1:
            raise WalletError("only a pending payout can be rejected")
        self._a(actor, "payout.reject", id=int(pid), reason=reason[:200])

    # ------------------------------------------------------------------ views
    def investor_wallet(self, iid) -> dict:
        inv = self.investor(iid)
        nav = self.nav()
        p = D(nav["nav_per_unit"])
        units = self.units(iid)
        subs = [self.subscription(r[0]) for r in self.c.execute("SELECT id FROM w_subs WHERE investor_id=? ORDER BY id DESC", (int(iid),))]
        reds = [dict(r) for r in self.c.execute("SELECT * FROM w_reds WHERE investor_id=? ORDER BY id DESC", (int(iid),))]
        pays = [self.payout(r[0]) for r in self.c.execute("SELECT id FROM w_payouts WHERE investor_id=? ORDER BY id DESC", (int(iid),))]
        pend_sub = sum((D(s["amount"]) for s in subs if s["status"] in ("instructed", "awaiting_funds", "funds_received")), Decimal(0))
        pend_red = sum((D(r["units"]) for r in reds if r["status"] in ("requested", "forwarded")), Decimal(0))
        return {"investor": {k: inv[k] for k in ("id", "legal_name", "email", "entity_type", "country", "province", "status", "admin_ref")},
                "decisions": self.decisions(iid), "units": str(units), "nav": nav, "value_cad": str(q(units * p)),
                "pending_subscriptions_cad": str(q(pend_sub)), "pending_redemption_units": str(pend_red),
                "pending_redemption_est_cad": str(q(pend_red * p)), "subscriptions": subs, "redemptions": reds, "payouts": pays,
                "banks": self.banks(iid), "ledger": [dict(r) for r in self.c.execute("SELECT * FROM w_units WHERE investor_id=? ORDER BY id", (int(iid),))],
                "terms": self.terms(), "next_dealing_date": self.dealing_date(),
                "held_by": "Investor money is held by the fund administrator/custodian, never by this platform."}

    def overview(self) -> dict:
        nav = self.nav()
        p = D(nav["nav_per_unit"])
        rows = []
        for inv in self.c.execute("SELECT * FROM w_investors ORDER BY id").fetchall():
            u = self.units(inv["id"])
            ps = sum((D(r[0]) for r in self.c.execute("SELECT amount FROM w_subs WHERE investor_id=? AND status IN ('instructed','awaiting_funds','funds_received')", (inv["id"],))), Decimal(0))
            pr = sum((D(r[0]) for r in self.c.execute("SELECT units FROM w_reds WHERE investor_id=? AND status IN ('requested','forwarded')", (inv["id"],))), Decimal(0))
            b = self.verified_bank(inv["id"])
            rows.append({"id": inv["id"], "legal_name": inv["legal_name"], "entity_type": inv["entity_type"], "status": inv["status"],
                         "admin_ref": inv["admin_ref"], "units": str(u), "value_cad": str(q(u * p)), "pending_sub_cad": str(q(ps)),
                         "pending_red_units": str(pr), "bank": (b["account_masked"] + (" ✓" if b["usable"] else " (cooling-off)")) if b else None})
        last = self.c.execute("SELECT * FROM w_recon ORDER BY id DESC LIMIT 1").fetchone()
        return {"nav": nav, "investors": rows, "units_total": str(sum((D(r["units"]) for r in rows), Decimal(0))),
                "value_total": str(sum((D(r["value_cad"]) for r in rows), Decimal(0))),
                "pending_payouts": self.c.execute("SELECT COUNT(*) FROM w_payouts WHERE status='pending_approval'").fetchone()[0],
                "requested_redemptions": self.c.execute("SELECT COUNT(*) FROM w_reds WHERE status='requested'").fetchone()[0],
                "last_recon": ({**dict(last), "summary": json.loads(last["summary"]), "breaks": len(json.loads(last["breaks"]))} if last else None),
                "terms": self.terms()}

    def statement_rows(self, iid) -> list[tuple]:
        nav = self.nav()
        rows = [("date", "type", "reference", "units", "nav", "amount_cad", "status")]
        for s in self.c.execute("SELECT * FROM w_subs WHERE investor_id=? ORDER BY id", (int(iid),)):
            rows.append((dt.date.fromtimestamp(s["created_at"]).isoformat(), "subscription", s["reference"], s["units"] or "", s["nav"] or "", s["amount"], s["status"]))
        for r in self.c.execute("SELECT * FROM w_reds WHERE investor_id=? ORDER BY id", (int(iid),)):
            rows.append((r["dealing_date"], "redemption", r["admin_ref"] or f"request {r['id']}", "-" + (r["units_dealt"] or r["units"]), r["nav"] or "", r["net"] or "", r["status"]))
        u = self.units(iid)
        rows.append((nav.get("nav_date") or "", "closing (administrator NAV)", "", str(u), nav["nav_per_unit"], str(q(u * D(nav["nav_per_unit"]))), ""))
        return rows

    def statement_csv(self, iid) -> str:
        buf = io.StringIO()
        csv.writer(buf).writerows(self.statement_rows(iid))
        return buf.getvalue()

    def statement_pdf(self, iid) -> bytes:
        inv = self.investor(iid)
        lines = [f"Wallet statement - {inv['legal_name']} (SIMULATION)", f"Administrator ref {inv['admin_ref']}  |  Fund: {self.nav().get('fund', '')}",
                 "Assets are held by the fund administrator / custodian, not by this platform. Not tax advice.", ""]
        lines += ["  ".join(str(x).ljust(12)[:22] for x in r) for r in self.statement_rows(iid)]
        return simple_pdf(lines)


__all__ = ["Wallet", "WalletError", "VaultUnavailable", "DEFAULT_TERMS", "norm_name"]
