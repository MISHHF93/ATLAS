"""Payment files (SIMULATION): ISO 20022 pain.001 credit-transfer files for released payouts and pain.002 status
reports applied back to them. In production a file like this is what a treasury/partner bank channel accepts
(host-to-host / portal upload); here nothing is transmitted: the owner downloads the file, and status reports are
uploaded back (or produced by the offline simulated bank). EndToEndId = the payout's release reference."""
from __future__ import annotations

import datetime as dt
import json
import secrets

from atlas.ledgers.banking.iso20022 import pain, validate
from atlas.ledgers.db import tx
from atlas.ledgers.money import D, q
from atlas.ledgers.wallet.partners import TRUST_ACCOUNT

SCHEMA = """
CREATE TABLE IF NOT EXISTS w_payfiles(id INTEGER PRIMARY KEY, msg_id TEXT UNIQUE, kind TEXT, created_at REAL, created_by TEXT,
  n INTEGER, total TEXT, currency TEXT, execution_date TEXT, xml TEXT, xsd TEXT, status TEXT, last_report TEXT);
CREATE TABLE IF NOT EXISTS w_payfile_tx(file_id INTEGER, payout_id INTEGER, end_to_end_id TEXT UNIQUE, amount TEXT, status TEXT,
  reason TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS w_status_reports(id INTEGER PRIMARY KEY, msg_id TEXT UNIQUE, orig_msg_id TEXT, received_at REAL,
  received_by TEXT, group_status TEXT, summary TEXT);
"""
DEBTOR = {"name": TRUST_ACCOUNT["beneficiary"][:140], "account": TRUST_ACCOUNT["account"],
          "institution": TRUST_ACCOUNT["institution"], "transit": TRUST_ACCOUNT["transit"]}


class BankFileError(PermissionError):
    ...


def _schema(w):
    w.c.executescript(SCHEMA)


def _creditor(w, p: dict) -> dict:
    acct = w._payout_account(p["investor_id"], p["bank_id"])        # re-checks own-name, verified, cooling-off
    pii = w.pii(p["investor_id"])
    addr = pii.get("address_structured") or {}
    address = ({"street": addr.get("street"), "building": addr.get("building"), "postal_code": addr.get("postal_code"),
                "town": addr.get("city"), "subdivision": addr.get("province"), "country": addr.get("country")}
               if addr else {"country": pii.get("country"), "lines": [str(pii.get("address", ""))[:70]]})
    return {"name": acct["holder_name"], "account": acct["account_number"], "institution": acct["institution_number"],
            "transit": acct["transit"], "address": address}


def export_pain001(w, actor: str, payout_ids: list[int] | None = None) -> dict:
    """Build one pain.001 for released/paid payouts not yet in a file (or the given ids)."""
    _schema(w)
    rows = [dict(r) for r in w.c.execute(
        "SELECT * FROM w_payouts WHERE status IN ('paid','released') AND release_ref IS NOT NULL "
        "AND id NOT IN (SELECT payout_id FROM w_payfile_tx) ORDER BY id")]
    if payout_ids is not None:
        rows = [r for r in rows if r["id"] in {int(i) for i in payout_ids}]
    if not rows:
        raise BankFileError("no released payouts waiting for a payment file")
    txs = [{"end_to_end_id": r["release_ref"], "instr_id": f"PO{r['id']:06d}", "amount": D(r["amount"]),
            "currency": r["currency"], "creditor": _creditor(w, r), "remittance": f"{r['kind']} payout #{r['id']}"} for r in rows]
    now = w.clock()
    msg_id = f"PAIN001-{dt.date.fromtimestamp(now):%Y%m%d}-{secrets.token_hex(3).upper()}"
    exec_date = pain.execution_date_for(now)
    xml = pain.build_pain001(msg_id, now, DEBTOR, exec_date, txs, initiating_party="Example Fund LP (SIMULATION)")
    v = validate(xml, "pain.001")
    total = q(sum((t["amount"] for t in txs), D(0)))
    with tx(w.c):
        fid = w.c.execute("INSERT INTO w_payfiles(msg_id,kind,created_at,created_by,n,total,currency,execution_date,xml,xsd,status)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (msg_id, "pain.001.001.09", now, actor, len(txs), str(total),
                                                            ",".join(sorted({t["currency"] for t in txs})), exec_date, xml, v["xsd"],
                                                            "generated")).lastrowid
        for r in rows:
            w.c.execute("INSERT INTO w_payfile_tx VALUES(?,?,?,?,?,?,?)", (fid, r["id"], r["release_ref"], r["amount"], "generated", None, now))
    w._a(actor, "bankfile.pain001", id=fid, msg_id=msg_id, n=len(txs), total=str(total), xsd=v["xsd"])
    return payfile(w, fid)


CPA = {"originator_id": "SIMORIG001", "data_centre": "00000", "short_name": "EXAMPLE FUND", "long_name": "EXAMPLE FUND LP SIMULATION"}


def export_cpa005(w, actor: str, payout_ids: list[int] | None = None, file_number: int | None = None) -> dict:
    """SIMULATION: the same released payouts as a CPA-005 AFT credit file (for banks that take 005 instead of
    pain.001). A payout goes into one payment file only, whichever format. Placeholder originator ID."""
    from atlas.ledgers.banking import cpa005
    _schema(w)
    rows = [dict(r) for r in w.c.execute(
        "SELECT * FROM w_payouts WHERE status IN ('paid','released') AND release_ref IS NOT NULL AND currency='CAD' "
        "AND id NOT IN (SELECT payout_id FROM w_payfile_tx) ORDER BY id")]
    if payout_ids is not None:
        rows = [r for r in rows if r["id"] in {int(i) for i in payout_ids}]
    if not rows:
        raise BankFileError("no released CAD payouts waiting for a payment file")
    now = w.clock()
    fcn = file_number or 1 + w.c.execute("SELECT COUNT(*) FROM w_payfiles WHERE kind='cpa005'").fetchone()[0]
    due = dt.date.fromisoformat(pain.execution_date_for(now))
    items = []
    for r in rows:
        cr = _creditor(w, r)
        items.append({"amount": D(r["amount"]), "due_date": due, "institution": cr["institution"], "transit": cr["transit"],
                      "account": cr["account"], "payee_name": cr["name"], "cross_reference": r["release_ref"]})
    text = cpa005.build(originator_id=CPA["originator_id"], file_number=fcn, created=dt.date.fromtimestamp(now), data_centre=CPA["data_centre"],
                        currency="CAD", items=items, short_name=CPA["short_name"], long_name=CPA["long_name"],
                        return_account={"institution": DEBTOR["institution"], "transit": DEBTOR["transit"], "account": DEBTOR["account"].split("-")[-1]})
    chk = cpa005.parse(text)
    total = q(sum((i["amount"] for i in items), D(0)))
    msg_id = f"CPA005-{CPA['originator_id']}-{fcn:04d}"
    with tx(w.c):
        fid = w.c.execute("INSERT INTO w_payfiles(msg_id,kind,created_at,created_by,n,total,currency,execution_date,xml,xsd,status)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (msg_id, "cpa005", now, actor, len(items), str(total), "CAD", due.isoformat(),
                                                            text, "valid" if chk["valid"] else "invalid", "generated")).lastrowid
        for r in rows:
            w.c.execute("INSERT INTO w_payfile_tx VALUES(?,?,?,?,?,?,?)", (fid, r["id"], r["release_ref"], r["amount"], "generated", None, now))
    w._a(actor, "bankfile.cpa005", id=fid, file_number=fcn, n=len(items), total=str(total))
    return payfile(w, fid)


def payfile(w, fid, with_xml: bool = False) -> dict:
    _schema(w)
    r = w.c.execute("SELECT * FROM w_payfiles WHERE id=?", (int(fid),)).fetchone()
    if not r:
        raise KeyError(f"payment file {fid}")
    d = dict(r)
    if not with_xml:
        d.pop("xml")
    d["txs"] = [dict(t) for t in w.c.execute("SELECT * FROM w_payfile_tx WHERE file_id=? ORDER BY payout_id", (int(fid),))]
    return d


def payfiles(w, limit: int = 50) -> list[dict]:
    _schema(w)
    return [payfile(w, r[0]) for r in w.c.execute("SELECT id FROM w_payfiles ORDER BY id DESC LIMIT ?", (limit,))]


def apply_pain002(w, actor: str, xml: str) -> dict:
    """Apply a pain.002 status report: per-transaction status by OrgnlEndToEndId. RJCT marks the payout 'returned'
    (money did not reach the investor; reconciliation will show it and the payout must be re-approved)."""
    _schema(w)
    v = validate(xml, "pain.002")
    rep = pain.parse_pain002(xml)
    f = w.c.execute("SELECT * FROM w_payfiles WHERE msg_id=?", (rep["orig_msg_id"],)).fetchone()
    if not f:
        raise BankFileError(f"status report refers to unknown payment file {rep['orig_msg_id']}")
    if w.c.execute("SELECT 1 FROM w_status_reports WHERE msg_id=?", (rep["msg_id"],)).fetchone():
        raise BankFileError(f"status report {rep['msg_id']} already applied")
    now = w.clock()
    txs = rep["txs"] or [{"end_to_end_id": t["end_to_end_id"], "status": rep["group_status"],
                          "reason": (rep["group_reasons"] or [{}])[0].get("code"), "reason_text": None}
                         for t in payfile(w, f["id"])["txs"]]
    out = {"file": f["msg_id"], "group_status": rep["group_status"], "updated": [], "returned": [], "unknown": [], "xsd": v["xsd"]}
    with tx(w.c):
        for t in txs:
            row = w.c.execute("SELECT * FROM w_payfile_tx WHERE end_to_end_id=? AND file_id=?", (t["end_to_end_id"], f["id"])).fetchone()
            if not row:
                out["unknown"].append(t["end_to_end_id"])
                continue
            w.c.execute("UPDATE w_payfile_tx SET status=?, reason=?, updated_at=? WHERE end_to_end_id=?",
                        (t["status"], t.get("reason"), now, t["end_to_end_id"]))
            out["updated"].append(t["end_to_end_id"])
            if t["status"] in pain.REJECTED:
                w.c.execute("UPDATE w_payouts SET status='returned', note=? WHERE id=?",
                            (f"bank rejected: {t.get('reason')} {t.get('reason_text') or ''}"[:200], row["payout_id"]))
                out["returned"].append(row["payout_id"])
        statuses = {r[0] for r in w.c.execute("SELECT status FROM w_payfile_tx WHERE file_id=?", (f["id"],))}
        fstat = "settled" if statuses <= pain.FINAL_OK else "rejected" if statuses <= pain.REJECTED else "partially_rejected" \
            if statuses & pain.REJECTED else "accepted"
        w.c.execute("UPDATE w_payfiles SET status=?, last_report=? WHERE id=?", (fstat, rep["msg_id"], f["id"]))
        w.c.execute("INSERT INTO w_status_reports(msg_id,orig_msg_id,received_at,received_by,group_status,summary) VALUES(?,?,?,?,?,?)",
                    (rep["msg_id"], rep["orig_msg_id"], now, actor, rep["group_status"], json.dumps(out)))
    w._a(actor, "bankfile.pain002", file=f["msg_id"], report=rep["msg_id"], status=fstat, returned=out["returned"])
    out["file_status"] = fstat
    return out


def simulate_bank_response(w, fid, rejects: dict[str, str] | None = None) -> str:
    """SIM HOOK: the offline 'bank' answers a generated file with a pain.002."""
    f = payfile(w, fid, with_xml=True)
    if f["kind"] == "cpa005":
        raise BankFileError("CPA-005 files are answered with a returns file by the bank; no pain.002 simulation")
    return pain.build_pain002(f"PAIN002-{secrets.token_hex(4).upper()}", w.clock(), f["xml"], rejects)
