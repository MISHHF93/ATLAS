"""Privacy records (PIPEDA / Quebec Law 25), SIMULATION. Records only; nothing is sent to any regulator.

- Consent log: append-only grant/withdraw events per purpose with the notice version shown; current state is the
  latest event. Purposes required for the service cannot be withdrawn without closing the account.
- Breach / incident register: every breach of security safeguards is recorded and kept 24 months (PIPEDA s.10.3),
  with the real-risk-of-significant-harm (RROSH) assessment and whether the OPC / CAI and individuals were notified.
- Access requests: 30-day response deadline (one 30-day extension with notice); export assembles the individual's
  own data. Sanctions screening and FINTRAC records are excluded and listed as withheld (PCMLTFA / no tipping off)."""
from __future__ import annotations

import datetime as dt
import json

PURPOSES = {"service": True, "identity_verification": True, "statements_email": False, "marketing": False,
            "data_sharing_affiliates": False}            # purpose -> required for the service
RETAIN_INCIDENT_DAYS = 730
ACCESS_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS p_consents(id INTEGER PRIMARY KEY, investor_id INTEGER, purpose TEXT, granted INTEGER, notice_version TEXT,
  method TEXT, actor TEXT, ts REAL);
CREATE TRIGGER IF NOT EXISTS p_consents_noupd BEFORE UPDATE ON p_consents BEGIN SELECT RAISE(ABORT, 'consent log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS p_consents_nodel BEFORE DELETE ON p_consents BEGIN SELECT RAISE(ABORT, 'consent log is append-only'); END;
CREATE TABLE IF NOT EXISTS p_incidents(id INTEGER PRIMARY KEY, detected_at TEXT, occurred_at TEXT, summary TEXT, data_types TEXT,
  individuals INTEGER, investor_ids TEXT, cause TEXT, containment TEXT, rrosh TEXT, rrosh_reason TEXT, regulator_notified_at TEXT,
  individuals_notified_at TEXT, status TEXT, created_by TEXT, created_at REAL, retain_until TEXT, history TEXT);
CREATE TABLE IF NOT EXISTS p_access_requests(id INTEGER PRIMARY KEY, investor_id INTEGER, received_on TEXT, due_on TEXT, extended INTEGER DEFAULT 0,
  status TEXT, completed_on TEXT, actor TEXT, export_sha256 TEXT);
"""


class PrivacyError(ValueError):
    pass


def _d(x) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


class Privacy:
    def __init__(self, c, clock, audit=None):
        self.c, self.clock, self._audit = c, clock, audit or (lambda *a, **k: None)
        c.executescript(SCHEMA)

    def today(self) -> dt.date:
        return dt.datetime.fromtimestamp(self.clock()).date()

    # ---------------------------------------------------------------- consent
    def record_consent(self, actor: str, iid: int, purpose: str, granted: bool, notice_version: str, method: str) -> int:
        if purpose not in PURPOSES:
            raise PrivacyError(f"unknown purpose {purpose!r}")
        if method not in ("portal_checkbox", "paper_signed", "email_confirmation", "staff_recorded_call"):
            raise PrivacyError("method must be portal_checkbox | paper_signed | email_confirmation | staff_recorded_call")
        if not granted and PURPOSES[purpose]:
            raise PrivacyError(f"'{purpose}' is required to provide the service; withdrawing it means closing the account")
        if not str(notice_version).strip():
            raise PrivacyError("record which privacy-notice version was shown")
        cid = self.c.execute("INSERT INTO p_consents(investor_id,purpose,granted,notice_version,method,actor,ts) VALUES(?,?,?,?,?,?,?)",
                             (int(iid), purpose, int(bool(granted)), notice_version, method, actor, self.clock())).lastrowid
        self._audit(actor, "privacy.consent", investor=int(iid), purpose=purpose, granted=bool(granted))
        return cid

    def consents(self, iid: int) -> dict:
        cur = {p: {"purpose": p, "required": req, "granted": False, "since": None, "notice_version": None} for p, req in PURPOSES.items()}
        for r in self.c.execute("SELECT * FROM p_consents WHERE investor_id=? ORDER BY id", (int(iid),)):
            cur[r["purpose"]].update(granted=bool(r["granted"]), since=r["ts"], notice_version=r["notice_version"], method=r["method"])
        return {"current": list(cur.values()), "history": [dict(r) for r in self.c.execute(
            "SELECT * FROM p_consents WHERE investor_id=? ORDER BY id", (int(iid),))]}

    def has_consent(self, iid: int, purpose: str) -> bool:
        r = self.c.execute("SELECT granted FROM p_consents WHERE investor_id=? AND purpose=? ORDER BY id DESC LIMIT 1", (int(iid), purpose)).fetchone()
        return bool(r and r[0])

    # ---------------------------------------------------------------- incidents
    def record_incident(self, actor: str, *, summary: str, detected_at: str, data_types: list[str], individuals: int,
                        investor_ids: list[int] | None = None, occurred_at: str | None = None, cause: str = "", containment: str = "") -> int:
        if len(summary.strip()) < 10 or not data_types:
            raise PrivacyError("summary (10+ chars) and the data types involved are required")
        det = _d(detected_at)
        iid = self.c.execute("INSERT INTO p_incidents(detected_at,occurred_at,summary,data_types,individuals,investor_ids,cause,containment,rrosh,"
                             "status,created_by,created_at,retain_until,history) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (det.isoformat(), occurred_at, summary.strip(), json.dumps(sorted(data_types)), int(individuals),
                              json.dumps(investor_ids or []), cause, containment, "pending", "open", actor, self.clock(),
                              (det + dt.timedelta(days=RETAIN_INCIDENT_DAYS)).isoformat(), json.dumps([]))).lastrowid
        self._audit(actor, "privacy.incident", id=iid, individuals=int(individuals))
        return iid

    def assess_incident(self, actor: str, inc_id: int, rrosh: bool, reason: str, regulator_notified_at: str | None = None,
                        individuals_notified_at: str | None = None, close: bool = False) -> dict:
        r = self.c.execute("SELECT * FROM p_incidents WHERE id=?", (int(inc_id),)).fetchone()
        if not r:
            raise KeyError(inc_id)
        if len(reason.strip()) < 10:
            raise PrivacyError("explain the RROSH assessment (sensitivity + probability of misuse), 10+ chars")
        if close and rrosh and not (regulator_notified_at and individuals_notified_at):
            raise PrivacyError("real risk of significant harm: the OPC/CAI and affected individuals must be notified before closing")
        hist = json.loads(r["history"]) + [{"ts": self.clock(), "actor": actor, "rrosh": rrosh, "reason": reason.strip()}]
        self.c.execute("UPDATE p_incidents SET rrosh=?, rrosh_reason=?, regulator_notified_at=?, individuals_notified_at=?, status=?, history=? WHERE id=?",
                       ("yes" if rrosh else "no", reason.strip(), regulator_notified_at, individuals_notified_at,
                        "closed" if close else "assessed", json.dumps(hist), int(inc_id)))
        self._audit(actor, "privacy.incident_assess", id=int(inc_id), rrosh=rrosh, closed=close)
        return self.incident(inc_id)

    def incident(self, inc_id: int) -> dict:
        d = dict(self.c.execute("SELECT * FROM p_incidents WHERE id=?", (int(inc_id),)).fetchone())
        for k in ("data_types", "investor_ids", "history"):
            d[k] = json.loads(d[k])
        return d

    def incidents(self) -> list[dict]:
        return [self.incident(r[0]) for r in self.c.execute("SELECT id FROM p_incidents ORDER BY id DESC")]

    def purge_incidents(self, actor: str) -> int:
        n = self.c.execute("DELETE FROM p_incidents WHERE status='closed' AND retain_until < ?", (self.today().isoformat(),)).rowcount
        self._audit(actor, "privacy.incident_purge", deleted=n)
        return n

    # ---------------------------------------------------------------- access requests
    def open_access_request(self, actor: str, iid: int, received_on: str | None = None) -> dict:
        rec = _d(received_on or self.today())
        rid = self.c.execute("INSERT INTO p_access_requests(investor_id,received_on,due_on,status,actor) VALUES(?,?,?,?,?)",
                             (int(iid), rec.isoformat(), (rec + dt.timedelta(days=ACCESS_DAYS)).isoformat(), "open", actor)).lastrowid
        self._audit(actor, "privacy.access_request", id=rid, investor=int(iid))
        return self.access_request(rid)

    def extend_access_request(self, actor: str, rid: int, reason: str) -> dict:
        r = self.access_request(rid)
        if r["extended"]:
            raise PrivacyError("an access request can be extended once (30 days)")
        if len(reason.strip()) < 10:
            raise PrivacyError("give the reason sent to the individual")
        self.c.execute("UPDATE p_access_requests SET extended=1, due_on=? WHERE id=?",
                       ((_d(r["due_on"]) + dt.timedelta(days=ACCESS_DAYS)).isoformat(), int(rid)))
        self._audit(actor, "privacy.access_extend", id=int(rid), reason=reason.strip())
        return self.access_request(rid)

    def complete_access_request(self, actor: str, rid: int, export_sha256: str) -> dict:
        self.c.execute("UPDATE p_access_requests SET status='completed', completed_on=?, export_sha256=? WHERE id=?",
                       (self.today().isoformat(), export_sha256, int(rid)))
        self._audit(actor, "privacy.access_complete", id=int(rid))
        return self.access_request(rid)

    def access_request(self, rid: int) -> dict:
        d = dict(self.c.execute("SELECT * FROM p_access_requests WHERE id=?", (int(rid),)).fetchone())
        d["overdue"] = d["status"] == "open" and self.today() > _d(d["due_on"])
        return d

    def access_requests(self) -> list[dict]:
        return [self.access_request(r[0]) for r in self.c.execute("SELECT id FROM p_access_requests ORDER BY id DESC")]

    def status(self) -> dict:
        return {"open_incidents": self.c.execute("SELECT COUNT(*) FROM p_incidents WHERE status<>'closed'").fetchone()[0],
                "open_access_requests": self.c.execute("SELECT COUNT(*) FROM p_access_requests WHERE status='open'").fetchone()[0],
                "overdue_access_requests": sum(1 for r in self.access_requests() if r["overdue"])}


WITHHELD = ["sanctions screening results (PCMLTFA / Criminal Code; disclosure could tip off)",
            "FINTRAC transaction records and reports (PCMLTFA s.8, no tipping off)",
            "internal audit-log entries of other users"]

__all__ = ["Privacy", "PrivacyError", "PURPOSES", "WITHHELD"]
