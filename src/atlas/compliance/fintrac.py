"""FINTRAC record-keeping (SIMULATION / RECORDS ONLY - nothing is filed or transmitted).

Under the fund-administrator architecture the platform never holds client money, so the administrator / dealer /
bank holding the trust account is normally the reporting entity. This module keeps the records the platform needs
to evidence what it saw and to hand a complete package to the reporting entity (or to file itself if counsel
decides the platform is a reporting entity), on the PCMLTFA / PCMLTFR rules:

* LCTR  large cash transaction: cash >= $10,000 in one transaction or several within 24 consecutive hours by/for
        the same person; report within 15 calendar days.
* EFTR  international electronic funds transfer >= $10,000 (incoming or outgoing; 24-hour rule); report within
        5 working days (Payments Canada business-day calendar; weekends and public holidays excluded).
* LVCTR large virtual currency transaction >= $10,000 equivalent (24-hour rule); 5 working days.
* LPEPR listed person or entity property report (SEMA / JVCFOA since 2025-10-01, UN regulations, Criminal Code):
        property of a listed person in our possession or control; report immediately (due same day); property frozen.
* Travel rule: EFTs >= $1,000 must carry originator name, address and account/reference number, and beneficiary
        name, address and account/reference number; missing fields are flagged on the record.
* ID verification: structured record of the method used (government-issued photo ID, credit file, dual process,
  affiliate/member, reliance, agent/mandatary) with only masked document numbers.
* Retention: at least 5 years (transaction records: from creation; ID records: 5 years after the relationship ends).
  Deletion before retain_until or while under legal hold is refused by the database.
Suspicious transaction reports (STRs) need human judgement and are out of scope (escalation note only)."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from decimal import Decimal

from atlas.ledgers.banking import calendars as cal

THRESHOLD = Decimal("10000")
TRAVEL_FIELDS = ("originator_name", "originator_address", "originator_account", "beneficiary_name", "beneficiary_address", "beneficiary_account")
TRAVEL_RULE_MIN = Decimal("1000")
RETENTION_YEARS = 5
KINDS = {"LCTR": "Large cash transaction record", "EFTR_IN": "International EFT (incoming) record",
         "EFTR_OUT": "International EFT (outgoing) record", "LVCTR": "Large virtual currency transaction record",
         "LPEPR": "Listed person or entity property record"}
ID_METHODS = {
    "government_photo_id": ("doc_type", "issuing_jurisdiction", "doc_number_last4", "expiry", "verified_on", "manner"),
    "credit_file": ("bureau", "file_reference_last4", "file_age_years", "verified_on"),
    "dual_process": ("source_1", "source_1_info", "source_2", "source_2_info", "verified_on"),
    "affiliate_or_member": ("entity", "verified_on"),
    "reliance": ("relied_on_entity", "agreement_ref", "verified_on"),
    "agent_or_mandatary": ("agent", "agreement_ref", "method_used_by_agent", "verified_on"),
}
DUAL_INFO = {"name_address", "name_dob", "name_financial_account"}
METHOD_KIND = {"cash": "LCTR", "wire_international": "EFTR_IN", "virtual_currency": "LVCTR"}
SUBFAMILY_METHOD = {"XBCT": "wire_international", "CDPT": "cash", "VCOM": "virtual_currency"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS f_transactions(id INTEGER PRIMARY KEY, investor_id INTEGER, method TEXT, direction TEXT, amount TEXT,
  currency TEXT, ts REAL, source_ref TEXT UNIQUE, details TEXT, record_id INTEGER);
CREATE TABLE IF NOT EXISTS f_records(id INTEGER PRIMARY KEY, kind TEXT, investor_id INTEGER, status TEXT, amount TEXT, currency TEXT,
  first_ts REAL, last_ts REAL, due_date TEXT, transactions TEXT, details TEXT, travel_rule_missing TEXT, created_at REAL,
  created_by TEXT, retain_until TEXT, legal_hold INTEGER DEFAULT 0, note TEXT, external_ref TEXT);
CREATE TABLE IF NOT EXISTS f_id_verifications(id INTEGER PRIMARY KEY, investor_id INTEGER, method TEXT, details TEXT,
  verified_on TEXT, performed_by TEXT, recorded_at REAL, recorded_by TEXT, retain_until TEXT, legal_hold INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS f_retention_log(id INTEGER PRIMARY KEY, ts REAL, actor TEXT, action TEXT, detail TEXT);
CREATE TRIGGER IF NOT EXISTS f_records_retention BEFORE DELETE ON f_records
  WHEN OLD.legal_hold = 1 OR OLD.retain_until > COALESCE((SELECT v FROM settings WHERE k='fintrac_purge_cutoff'), '0000')
  BEGIN SELECT RAISE(ABORT, 'FINTRAC record under retention or legal hold'); END;
CREATE TRIGGER IF NOT EXISTS f_idv_retention BEFORE DELETE ON f_id_verifications
  WHEN OLD.legal_hold = 1 OR OLD.retain_until > COALESCE((SELECT v FROM settings WHERE k='fintrac_purge_cutoff'), '0000')
  BEGIN SELECT RAISE(ABORT, 'ID verification record under retention or legal hold'); END;
CREATE TRIGGER IF NOT EXISTS f_retention_log_u BEFORE UPDATE ON f_retention_log BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS f_retention_log_d BEFORE DELETE ON f_retention_log BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


class FintracError(ValueError):
    ...


def _date(ts: float) -> dt.date:
    return dt.date.fromtimestamp(ts)


def due_date(kind: str, ts: float) -> str:
    d = _date(ts)
    if kind == "LCTR":
        return (d + dt.timedelta(days=15)).isoformat()
    if kind in ("EFTR_IN", "EFTR_OUT", "LVCTR"):
        return cal.add_business_days(d, 5, "CA").isoformat()
    if kind == "LPEPR":
        return d.isoformat()                                    # immediately
    raise FintracError(kind)


def retain_until(ts: float, years: int = RETENTION_YEARS) -> str:
    d = _date(ts)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:                                          # Feb 29
        return d.replace(year=d.year + years, day=28).isoformat()


class Fintrac:
    def __init__(self, c, clock=time.time, audit=None):
        self.c, self.clock, self._audit = c, clock, audit or (lambda *a, **k: None)
        c.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
        c.executescript(SCHEMA)

    # ------------------------------------------------------------------ transactions -> records
    def observe(self, actor: str, investor_id: int | None, method: str, amount, currency: str, ts: float, source_ref: str,
                direction: str = "in", details: dict | None = None, cad_rate: Decimal | None = None) -> dict:
        """Record one observed transaction (idempotent on source_ref) and apply the threshold + 24-hour rule.
        Amounts in other currencies need cad_rate (Bank of Canada rate for the day) - recorded with the details."""
        prev = self.c.execute("SELECT * FROM f_transactions WHERE source_ref=?", (source_ref,)).fetchone()
        if prev:
            return {"transaction": prev["id"], "record": prev["record_id"], "duplicate": True}
        amt = Decimal(str(amount))
        cad = amt if currency == "CAD" else (amt * Decimal(str(cad_rate)) if cad_rate else None)
        if cad is None:
            raise FintracError(f"{currency} amount needs the day's CAD exchange rate (cad_rate)")
        d = dict(details or {}, cad_equivalent=str(cad), cad_rate=str(cad_rate) if cad_rate else None)
        tid = self.c.execute("INSERT INTO f_transactions(investor_id,method,direction,amount,currency,ts,source_ref,details) VALUES(?,?,?,?,?,?,?,?)",
                             (investor_id, method, direction, str(amt), currency, ts, source_ref, json.dumps(d, default=str))).lastrowid
        kind = METHOD_KIND.get(method)
        if kind == "EFTR_IN" and direction == "out":
            kind = "EFTR_OUT"
        rec = None
        if kind:
            rec = self._apply_24h(actor, kind, investor_id, ts, method, direction)
        missing = self.travel_rule_missing(d) if method in ("wire_international", "wire_domestic", "eft") and cad >= TRAVEL_RULE_MIN else []
        return {"transaction": tid, "record": rec, "travel_rule_missing": missing}

    def _apply_24h(self, actor, kind, investor_id, ts, method, direction):
        rows = self.c.execute("SELECT * FROM f_transactions WHERE investor_id IS ? AND method=? AND direction=? AND ts>? AND ts<=? ORDER BY ts",
                              (investor_id, method, direction, ts - 86400, ts)).fetchall()
        total = sum((Decimal(json.loads(r["details"])["cad_equivalent"]) for r in rows), Decimal(0))
        ids = [r["id"] for r in rows]
        existing = {r["record_id"] for r in rows if r["record_id"]}
        if total < THRESHOLD and not existing:                 # below threshold and not linked to an open 24h record
            return None
        details = [json.loads(r["details"]) for r in rows]
        merged = {k: v for d in details for k, v in d.items() if v not in (None, "")}
        # travel-rule info is required per transfer: a gap in any aggregated transfer is a gap in the record
        gaps = [self.travel_rule_missing(d) for d in details] if kind.startswith("EFTR") else []
        missing = sorted({k for g in gaps for k in g}, key=lambda k: TRAVEL_FIELDS.index(k))
        if existing:                                           # extend the open record covering this window
            rid = max(existing)
            r = self.c.execute("SELECT * FROM f_records WHERE id=?", (rid,)).fetchone()
            all_ids = sorted(set(json.loads(r["transactions"])) | set(ids))
            amt = sum((Decimal(json.loads(x["details"])["cad_equivalent"]) for x in self.c.execute(
                f"SELECT details FROM f_transactions WHERE id IN ({','.join('?' * len(all_ids))})", all_ids)), Decimal(0))
            self.c.execute("UPDATE f_records SET amount=?, last_ts=?, transactions=?, travel_rule_missing=? WHERE id=?",
                           (str(amt), ts, json.dumps(all_ids), json.dumps(missing), rid))
        else:
            rid = self.c.execute("INSERT INTO f_records(kind,investor_id,status,amount,currency,first_ts,last_ts,due_date,transactions,details,"
                                 "travel_rule_missing,created_at,created_by,retain_until) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (kind, investor_id, "draft", str(total), "CAD", rows[0]["ts"], ts, due_date(kind, rows[0]["ts"]),
                                  json.dumps(ids), json.dumps(merged, default=str), json.dumps(missing), self.clock(), actor,
                                  retain_until(self.clock()))).lastrowid
            self._audit(actor, "fintrac.record", id=rid, kind=kind, amount=str(total), due=due_date(kind, rows[0]["ts"]))
        self.c.execute(f"UPDATE f_transactions SET record_id=? WHERE id IN ({','.join('?' * len(ids))})", (rid, *ids))
        return rid

    @staticmethod
    def travel_rule_missing(d: dict) -> list[str]:
        return [k for k in TRAVEL_FIELDS if not str(d.get(k) or "").strip()]

    def scan_camt054(self, actor: str, entries: list[dict], ref_to_investor: dict, beneficiary: dict) -> list[dict]:
        """Feed credit entries from a camt.054 (parsed) into observe(); method from the bank transaction sub-family
        (XBCT cross-border, CDPT cash deposit, VCOM virtual currency) or a non-CA debtor country."""
        out = []
        for e in entries:
            if e["amount"] <= 0 or (e.get("bank_tx_code") or "").endswith("/BOOK"):
                continue
            sub = (e.get("bank_tx_code") or "").split("/")[-1]
            method = SUBFAMILY_METHOD.get(sub) or ("wire_international" if (e.get("counterparty_country") or "CA") != "CA" else "eft")
            m = re.search(r"\bSUB-[0-9A-F]{8}\b", " ".join(x for x in (e.get("end_to_end_id"), e.get("remittance")) if x))
            iid = ref_to_investor.get(m.group(0)) if m else None
            ts = dt.datetime.fromisoformat(e["booked_at"]).timestamp() if e.get("booked_at") else \
                dt.datetime.combine(dt.date.fromisoformat(e["booking_date"]), dt.time(12)).timestamp()
            det = {"originator_name": e.get("counterparty"), "originator_address": (   # a country code alone is not an address
                " ".join(x for x in (e.get("counterparty_address"), e.get("counterparty_country")) if x) if e.get("counterparty_address") else ""), "originator_account": e.get("counterparty_account"),
                "beneficiary_name": beneficiary.get("name"), "beneficiary_address": beneficiary.get("address"),
                "beneficiary_account": beneficiary.get("account"), "bank_reference": e.get("servicer_ref"),
                "originator_country": e.get("counterparty_country"), "reference": m.group(0) if m else None}
            out.append(self.observe(actor, iid, method, e["amount"], e.get("currency") or "CAD", ts,
                                    f"camt:{e.get('servicer_ref') or e.get('entry_ref')}", "in", det))
        return out

    # ------------------------------------------------------------------ LPEPR
    def record_listed_property(self, actor: str, investor_id: int, hit: dict, property_desc: list[dict]) -> int:
        prev = self.c.execute("SELECT id FROM f_records WHERE kind='LPEPR' AND investor_id=? AND json_extract(details,'$.hit_id')=?",
                              (investor_id, hit["id"])).fetchone()
        if prev:
            return prev[0]
        now = self.clock()
        total = sum((Decimal(str(p.get("value_cad") or 0)) for p in property_desc), Decimal(0))
        rid = self.c.execute("INSERT INTO f_records(kind,investor_id,status,amount,currency,first_ts,last_ts,due_date,transactions,details,"
                             "travel_rule_missing,created_at,created_by,retain_until,legal_hold,note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             ("LPEPR", investor_id, "draft", str(total), "CAD", now, now, due_date("LPEPR", now), "[]",
                              json.dumps({"hit_id": hit["id"], "list": hit["source"], "list_uid": hit["uid"], "listed_name": hit["listed_name"],
                                          "programs": hit.get("programs"), "property": property_desc, "frozen": True}, default=str),
                              "[]", now, actor, retain_until(now), 1,
                              "Property frozen; disclose to RCMP and CSIS (SEMA/JVCFOA/UN) and report to FINTRAC without delay")).lastrowid
        self._audit(actor, "fintrac.lpepr", id=rid, investor=investor_id, hit=hit["id"])
        return rid

    # ------------------------------------------------------------------ ID verification
    def record_id_verification(self, actor: str, investor_id: int, method: str, details: dict, performed_by: str) -> int:
        if method not in ID_METHODS:
            raise FintracError(f"method must be one of {sorted(ID_METHODS)}")
        missing = [k for k in ID_METHODS[method] if not str(details.get(k) or "").strip()]
        if missing:
            raise FintracError(f"{method}: missing {', '.join(missing)}")
        for k, v in details.items():
            if ("number" in k or "reference" in k) and not k.endswith("_last4") and re.search(r"\d{5,}", str(v)):
                raise FintracError(f"{k}: store only the last 4 digits of document/file numbers")
            if k.endswith("_last4") and not re.fullmatch(r"[A-Za-z0-9]{1,4}", str(v)):
                raise FintracError(f"{k}: at most 4 characters")
        if method == "dual_process":
            if details["source_1"].strip().lower() == details["source_2"].strip().lower():
                raise FintracError("dual process: the two sources must be different and independent")
            if {details["source_1_info"], details["source_2_info"]} - DUAL_INFO or details["source_1_info"] == details["source_2_info"]:
                raise FintracError(f"dual process: two different information types from {sorted(DUAL_INFO)}")
        if method == "credit_file" and float(details["file_age_years"]) < 3:
            raise FintracError("credit file must have existed for at least 3 years")
        if method == "government_photo_id" and details["manner"] not in ("in_person", "remote_authenticated"):
            raise FintracError("government_photo_id manner: in_person | remote_authenticated (document authenticated + live match)")
        now = self.clock()
        vid = self.c.execute("INSERT INTO f_id_verifications(investor_id,method,details,verified_on,performed_by,recorded_at,recorded_by,retain_until)"
                             " VALUES(?,?,?,?,?,?,?,?)", (int(investor_id), method, json.dumps(details, sort_keys=True), details["verified_on"],
                                                          performed_by, now, actor, retain_until(now))).lastrowid
        self._audit(actor, "fintrac.id_verification", id=vid, investor=int(investor_id), method=method)
        return vid

    def extend_id_retention(self, actor: str, investor_id: int, relationship_ended_ts: float) -> int:
        until = retain_until(relationship_ended_ts)
        n = self.c.execute("UPDATE f_id_verifications SET retain_until=MAX(retain_until, ?) WHERE investor_id=?", (until, int(investor_id))).rowcount
        self._log(actor, "id_retention_extended", {"investor": investor_id, "until": until})
        return n

    def id_verifications(self, investor_id=None) -> list[dict]:
        q, a = ("SELECT * FROM f_id_verifications WHERE investor_id=? ORDER BY id", (int(investor_id),)) if investor_id is not None else \
            ("SELECT * FROM f_id_verifications ORDER BY id DESC", ())
        return [{**dict(r), "details": json.loads(r["details"])} for r in self.c.execute(q, a)]

    # ------------------------------------------------------------------ views / status
    def records(self, kind: str | None = None) -> list[dict]:
        today = _date(self.clock()).isoformat()
        q, a = ("SELECT * FROM f_records WHERE kind=? ORDER BY id DESC", (kind,)) if kind else ("SELECT * FROM f_records ORDER BY id DESC", ())
        out = []
        for r in self.c.execute(q, a):
            d = dict(r)
            d["details"], d["transactions"], d["travel_rule_missing"] = json.loads(d["details"]), json.loads(d["transactions"]), json.loads(d["travel_rule_missing"])
            d["overdue"] = d["status"] in ("draft", "ready") and today > d["due_date"]
            d["kind_name"] = KINDS.get(d["kind"], d["kind"])
            out.append(d)
        return out

    def mark(self, actor: str, rid: int, status: str, external_ref: str = "", note: str = "") -> None:
        """Workflow status only: draft -> ready (package complete) -> handed_to_reporting_entity | not_required (with reason)."""
        if status not in ("ready", "handed_to_reporting_entity", "not_required"):
            raise FintracError("status: ready | handed_to_reporting_entity | not_required")
        if status == "not_required" and len(note.strip()) < 10:
            raise FintracError("a reason is required to mark a record not required")
        r = self.c.execute("SELECT * FROM f_records WHERE id=?", (int(rid),)).fetchone()
        if not r:
            raise KeyError(rid)
        if status in ("ready", "handed_to_reporting_entity") and json.loads(r["travel_rule_missing"] or "[]"):
            raise FintracError("travel-rule information missing: " + ", ".join(json.loads(r["travel_rule_missing"])))
        self.c.execute("UPDATE f_records SET status=?, external_ref=?, note=COALESCE(NULLIF(?, ''), note) WHERE id=?",
                       (status, external_ref[:64], note[:500], int(rid)))
        self._audit(actor, "fintrac.mark", id=int(rid), status=status)

    def legal_hold(self, actor: str, rid: int, on: bool, reason: str) -> None:
        self.c.execute("UPDATE f_records SET legal_hold=? WHERE id=?", (int(on), int(rid)))
        self._log(actor, "legal_hold_on" if on else "legal_hold_off", {"record": rid, "reason": reason})

    def purge_expired(self, actor: str) -> dict:
        """Delete records past retain_until and not on legal hold (the DB trigger enforces the same rule)."""
        cutoff = _date(self.clock()).isoformat()
        self.c.execute("INSERT OR REPLACE INTO settings VALUES('fintrac_purge_cutoff', ?)", (cutoff,))
        try:
            n1 = self.c.execute("DELETE FROM f_records WHERE retain_until <= ? AND legal_hold=0", (cutoff,)).rowcount
            n2 = self.c.execute("DELETE FROM f_id_verifications WHERE retain_until <= ? AND legal_hold=0", (cutoff,)).rowcount
        finally:
            self.c.execute("DELETE FROM settings WHERE k='fintrac_purge_cutoff'")
        self._log(actor, "purge", {"cutoff": cutoff, "records": n1, "id_verifications": n2})
        return {"cutoff": cutoff, "records": n1, "id_verifications": n2}

    def _log(self, actor, action, detail):
        self.c.execute("INSERT INTO f_retention_log(ts,actor,action,detail) VALUES(?,?,?,?)", (self.clock(), actor, action, json.dumps(detail, default=str)))
        self._audit(actor, f"fintrac.{action}", **{k: str(v) for k, v in detail.items()})

    def status(self) -> dict:
        recs = self.records()
        return {"open": sum(r["status"] in ("draft", "ready") for r in recs), "overdue": sum(r["overdue"] for r in recs),
                "by_kind": {k: sum(r["kind"] == k for r in recs) for k in KINDS},
                "travel_rule_incomplete": sum(bool(r["travel_rule_missing"]) for r in recs),
                "id_verifications": self.c.execute("SELECT COUNT(*) FROM f_id_verifications").fetchone()[0],
                "note": "records only - nothing is filed; the reporting entity files with FINTRAC"}
