"""Manual execution mode (DEFAULT). The pipeline prepares and records; a human
moves the money in the bank/broker/exchange UI.

approved transfer -> prepare(): instruction sheet (PDF + Markdown + CSV) with a
unique reference, masked payee details, value date, rail checklist, expiry
-> owner moves money manually -> mark_executed(confirmation#, step-up)
-> pending_settlement (ledger posted) -> reconcile(statement) matches by
reference + amount -> settled. Mismatches / overdue / expired are flagged."""
from __future__ import annotations
import csv, datetime as dt, io, json, secrets
from pathlib import Path
from atlas.ledgers.banking import calendars as _cal
from atlas.ledgers.money import D
from atlas.ledgers.statements import simple_pdf
from atlas.ledgers.db import tx
from atlas.ledgers.treasury import ControlError, Treasury

EXPIRY_S = 72 * 3600
SETTLE_DAYS = {"EFT": 3, "WIRE": 2, "INTERAC": 1, "LYNX": 1, "RTR": 1, "CRYPTO": 1, "INTERNAL": 3}

def mask(s: str) -> str:
    s = str(s); return "*" * max(len(s) - 4, 0) + s[-4:]

def next_business_day(d: dt.date) -> dt.date:
    """Next Payments Canada business day (weekends and system closures such as Sep 30 skipped)."""
    return _cal.next_business_day(d, "CA")

COMMON_PRE = ["Confirm the payments kill switch is OFF (`atlas-payments status`).",
              "Confirm the sheet has not expired and the transfer status is 'instructed'.",
              "Log in to the provider yourself (typed URL / bookmark; never via an emailed link)."]
COMMON_POST = ["Save the provider confirmation number / screenshot.",
               "Run: atlas-payments mark-executed {id} --confirmation <NUMBER> --approver <you>"]

def checklist(rail: str, provider: str, direction: str) -> list[str]:
    ref = "the reference code {ref} in the memo/reference field"
    steps = {
        "EFT": ["Bank > Payments > Bill/EFT payee: select the pre-saved payee matching the last 4 digits shown.",
                "Enter the exact amount and currency; put " + ref + ".",
                "Set the date to the value date (EFT batches settle T+1..T+3)."],
        "WIRE": ["Bank > Wires: use the saved wire template for this payee (do NOT retype details from email).",
                 "Verify beneficiary name, account last 4, bank/SWIFT/transit against the allowlist record.",
                 "Enter exact amount/currency; charges code as agreed (OUR/SHA); put " + ref + ".",
                 "If any beneficiary detail differs from the allowlist: STOP and call the payee on a known number."],
        "INTERAC": ["Bank > Interac e-Transfer: select the saved recipient (email/phone last 4 must match).",
                    "Prefer autodeposit recipients; if a security question is required, share the answer out-of-band.",
                    "Enter exact amount (bank limits apply) and put " + ref + " in the message."],
        "LYNX": ["Lynx is bank-initiated high-value: request via your bank's high-value/wire channel.",
                 "Verify payee details vs allowlist; include " + ref + "."],
        "RTR": ["RTR is a PLACEHOLDER: if your bank offers it, follow its real-time payment flow; otherwise use EFT/wire.",
                "Include " + ref + "."],
        "CRYPTO": [f"{provider.title() or 'Exchange'} > Withdraw: select the address from the exchange's own address book (allowlisted).",
                   "Verify the FULL address character-by-character against the allowlist record on a second device (not only last 4).",
                   "Verify the network/chain (e.g. Bitcoin vs Lightning, Ethereum vs L2) and any memo/tag.",
                   "RECOMMENDED for a new address or large amount: send a small test transfer first and confirm receipt.",
                   "Enter the exact amount; note network fee is extra; record the tx hash as the confirmation number."],
    }.get(rail, [])
    if provider == "ibkr":
        steps = (["IBKR Portal > Transfer & Pay > Transfer Funds > " + ("Deposit: create a deposit notification, then send the bank wire/EFT using IBKR's instructions." if direction == "deposit"
                  else "Withdraw: choose the saved (pre-verified) bank instruction; IBKR may hold new instructions."),
                  "Include " + ref + " where IBKR/your bank allows (wire memo / deposit notification note)."] + steps)
    elif provider in ("kraken", "coinbase") and rail != "CRYPTO":
        steps = [f"{provider.title()} > Funding: use the {'deposit' if direction == 'deposit' else 'withdrawal'} method saved for this account; verify the reference/memo exactly ({ref})."] + steps
    return COMMON_PRE + steps + COMMON_POST

def _provider(t) -> tuple[str, str]:
    debit = json.loads(t["meta"])["debit"] if t["meta"] else ""
    for name in ("ibkr", "kraken", "coinbase"):
        if name in debit: return name, "deposit"
        if name in t["source"]: return name, "withdrawal"
    return "bank", "payment"

class Manual:
    def __init__(self, tr: Treasury, out_dir="var/payments/sheets"):
        self.tr, self.c, self.out = tr, tr.c, Path(out_dir)

    def _row(self, tid):
        t = self.c.execute("SELECT t.*, m.reference, m.value_date, m.expires_at, m.confirmation, m.flag, m.batch,"
                           " p.name AS payee_name, p.destination, p.kind AS payee_kind FROM transfers t"
                           " JOIN payees p ON p.id=t.payee_id LEFT JOIN manual_instructions m ON m.transfer_id=t.id WHERE t.id=?", (tid,)).fetchone()
        if not t: raise KeyError(tid)
        return t

    def prepare(self, tid, batch: str | None = None) -> dict:
        t = self.tr.transfer(tid)
        if self.tr.get("kill") == "1":
            raise ControlError("payments kill switch engaged")
        if t["status"] != "approved":
            raise ControlError(f"transfer must be approved (status {t['status']})")
        now = self.tr.clock()
        ref = f"TBP{tid:05d}{secrets.token_hex(3).upper()}"
        vd = next_business_day(dt.date.fromtimestamp(now)).isoformat()
        self.c.execute("INSERT INTO manual_instructions(transfer_id,reference,value_date,created_at,expires_at,batch) VALUES(?,?,?,?,?,?)",
                       (tid, ref, vd, now, now + EXPIRY_S, batch))
        # keep debit account in meta; provider_ref column historically held it
        self.c.execute("UPDATE transfers SET status='instructed' WHERE id=?", (tid,))
        self.tr._audit("system", "transfer.instructed", id=tid, reference=ref, value_date=vd, batch=batch)
        return self.write_sheet(tid)

    def sheet_data(self, tid) -> dict:
        t = self._row(tid)
        prov, direction = _provider(self._with_meta(t))
        return {"transfer_id": t["id"], "reference": t["reference"], "amount": t["amount"], "currency": t["currency"],
                "amount_cad": t["amount_cad"], "rail": t["rail"], "provider": prov, "direction": direction,
                "payee": t["payee_name"], "payee_account": mask(t["destination"]), "source_account": t["source"],
                "purpose": t["purpose"], "value_date": t["value_date"],
                "expires": dt.datetime.fromtimestamp(t["expires_at"]).strftime("%Y-%m-%d %H:%M %Z").strip(),
                "status": t["status"],
                "checklist": [s.format(ref=t["reference"], id=t["id"]) for s in checklist(t["rail"], prov, direction)]}

    def _with_meta(self, t):
        d = dict(t); d["meta"] = self._meta(t["id"]); return d

    def _meta(self, tid):
        r = self.c.execute("SELECT data FROM audit WHERE action='transfer.request' AND json_extract(data,'$.id')=?", (tid,)).fetchone()
        return json.dumps({"debit": json.loads(r[0]).get("debit", "")}) if r else ""

    @staticmethod
    def _md(d) -> str:
        head = [f"# Transfer instruction {d['reference']} (MANUAL EXECUTION)", "",
                "| Field | Value |", "|---|---|"] + [f"| {k} | {d[k]} |" for k in
                ("transfer_id", "reference", "amount", "currency", "amount_cad", "rail", "provider", "direction", "payee",
                 "payee_account", "source_account", "purpose", "value_date", "expires")]
        return "\n".join(head + ["", "## Checklist"] + [f"{i}. [ ] {s}" for i, s in enumerate(d["checklist"], 1)] +
                         ["", "_Simulation tooling; verify everything with the provider. Not legal/tax advice._", ""])

    def write_sheet(self, tid) -> dict:
        d = self.sheet_data(tid)
        if not d["reference"]:
            raise ControlError("no instruction prepared for this transfer")
        self.out.mkdir(parents=True, exist_ok=True)
        base = self.out / f"transfer_{tid}_{d['reference']}"
        md = self._md(d)
        base.with_suffix(".md").write_text(md)
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(["field", "value"])
        w.writerows([(k, v) for k, v in d.items() if k != "checklist"]); w.writerows([("step", s) for s in d["checklist"]])
        base.with_suffix(".csv").write_text(buf.getvalue())
        base.with_suffix(".pdf").write_bytes(simple_pdf(_wrap(md.replace("|", " ").splitlines())))
        return {"reference": d["reference"], "md": str(base.with_suffix(".md")), "csv": str(base.with_suffix(".csv")),
                "pdf": str(base.with_suffix(".pdf"))}

    def batch(self, tids: list[int], name: str) -> dict:
        """One combined sheet for a run (e.g. daily fee run). Each transfer still
        passed its own limits/allowlist/approval and gets its own reference."""
        for tid in tids:
            if not self._row(tid)["reference"]:
                self.prepare(tid, batch=name)
        ds = [self.sheet_data(t) for t in tids]
        total = {}
        for d in ds: total[d["currency"]] = total.get(d["currency"], D(0)) + D(d["amount"])
        md = "\n".join([f"# Batch {name} ({len(ds)} transfers, MANUAL EXECUTION)", "",
                        "Totals: " + ", ".join(f"{v} {k}" for k, v in total.items()), "",
                        "| # | Reference | Payee | Account | Rail | Amount | Ccy | Value date |", "|---|---|---|---|---|---|---|---|"] +
                       [f"| {d['transfer_id']} | {d['reference']} | {d['payee']} | {d['payee_account']} | {d['rail']} | {d['amount']} | {d['currency']} | {d['value_date']} |" for d in ds] +
                       ["", "Execute each line using its individual sheet checklist, then mark each executed.", ""])
        self.out.mkdir(parents=True, exist_ok=True)
        base = self.out / f"batch_{name}"
        base.with_suffix(".md").write_text(md)
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["transfer_id", "reference", "payee", "payee_account", "rail", "amount", "currency", "value_date"])
        w.writerows([[d[k] for k in ("transfer_id", "reference", "payee", "payee_account", "rail", "amount", "currency", "value_date")] for d in ds])
        base.with_suffix(".csv").write_text(buf.getvalue())
        base.with_suffix(".pdf").write_bytes(simple_pdf(_wrap(md.replace("|", " ").splitlines())))
        self.tr._audit("system", "batch.sheet", name=name, transfers=tids)
        return {"md": str(base.with_suffix(".md")), "csv": str(base.with_suffix(".csv")), "pdf": str(base.with_suffix(".pdf")),
                "totals": {k: str(v) for k, v in total.items()}}

    def mark_executed(self, tid, confirmation: str, approver, passphrase, code):
        t = self._row(tid)
        if t["status"] != "instructed":
            raise ControlError(f"transfer is {t['status']}, expected 'instructed'")
        if not confirmation.strip():
            raise ValueError("provider confirmation number required")
        self.tr.auth.verify(approver, passphrase, code)
        with tx(self.c):  # atomic claim: a second concurrent mark-executed can't double-post the ledger
            claimed = self.c.execute("UPDATE transfers SET status='marking' WHERE id=? AND status='instructed'", (tid,)).rowcount
            if claimed != 1:
                raise ControlError(f"transfer {tid} is no longer 'instructed'")
            self._post_executed(tid, t, confirmation, approver)

    def _post_executed(self, tid, t, confirmation, approver):
        now = self.tr.clock()
        late = now > t["expires_at"]
        meta = json.loads(self._meta(tid) or '{"debit": "liability:payables"}')
        self.tr.ledger.post(f"manual transfer {tid} {t['reference']} to {t['payee_name']}",
                            [(meta["debit"] or "liability:payables", D(t["amount"]), t["currency"]),
                             (t["source"], -D(t["amount"]), t["currency"])], ref=t["reference"])
        self.c.execute("UPDATE manual_instructions SET confirmation=?, marked_by=?, marked_at=?, flag=? WHERE transfer_id=?",
                       (confirmation, approver, now, "executed_after_expiry" if late else None, tid))
        self.c.execute("UPDATE transfers SET status='pending_settlement', executed_at=?, provider_ref=? WHERE id=?",
                       (now, confirmation, tid))
        self.tr._audit(approver, "transfer.marked_executed", id=tid, reference=t["reference"], confirmation=confirmation, late=late)

    def pending(self) -> list[dict]:
        return [dict(r) for r in self.c.execute(
            "SELECT t.id, t.status, t.amount, t.currency, t.rail, p.name AS payee, m.reference, m.value_date, m.expires_at, m.flag"
            " FROM transfers t JOIN manual_instructions m ON m.transfer_id=t.id JOIN payees p ON p.id=t.payee_id"
            " WHERE t.status IN ('instructed','pending_settlement') OR m.flag IS NOT NULL AND t.status!='settled' ORDER BY t.id")]

    def reconcile(self, statement: list[dict]) -> dict:
        """statement rows: date,ref,amount,currency[,memo]; amount negative = outflow."""
        now = self.tr.clock(); today = dt.date.fromtimestamp(now)
        res = {"settled": [], "amount_mismatch": [], "overdue": [], "expired": [], "unmatched_lines": []}
        used = set()
        for r in self.c.execute("SELECT t.*, m.reference, m.value_date, m.expires_at FROM transfers t JOIN manual_instructions m"
                                " ON m.transfer_id=t.id WHERE t.status IN ('instructed','pending_settlement')").fetchall():
            if r["status"] == "instructed":
                if now > r["expires_at"]:
                    self.c.execute("UPDATE transfers SET status='expired' WHERE id=?", (r["id"],))
                    self._flag(r["id"], "expired"); res["expired"].append(r["id"])
                continue
            hits = [i for i, s in enumerate(statement) if r["reference"] in (s.get("ref", "") + " " + s.get("memo", ""))]
            if hits:
                i = hits[0]; s = statement[i]; used.add(i)
                if -D(s["amount"]) == D(r["amount"]) and s["currency"] == r["currency"]:
                    self.c.execute("UPDATE transfers SET status='settled' WHERE id=?", (r["id"],))
                    self.c.execute("UPDATE manual_instructions SET settled_at=?, statement_ref=?, flag=NULL WHERE transfer_id=?",
                                   (now, s.get("ref"), r["id"]))
                    self.tr._audit("recon", "transfer.settled", id=r["id"], reference=r["reference"])
                    res["settled"].append(r["id"])
                else:
                    self._flag(r["id"], f"amount_mismatch: statement {s['amount']} {s['currency']}"); res["amount_mismatch"].append(r["id"])
            elif today > _cal.add_business_days(r["value_date"], SETTLE_DAYS.get(r["rail"], 3), "CA"):
                cur = self.c.execute("SELECT flag FROM manual_instructions WHERE transfer_id=?", (r["id"],)).fetchone()[0]
                if not (cur or "").startswith("amount_mismatch"):  # keep the more serious flag
                    self._flag(r["id"], "overdue")
                res["overdue"].append(r["id"])
        res["unmatched_lines"] = [s.get("ref") for i, s in enumerate(statement) if i not in used]
        return res

    def _flag(self, tid, flag):
        self.c.execute("UPDATE manual_instructions SET flag=? WHERE transfer_id=?", (flag, tid))
        self.tr._audit("recon", "transfer.flag", id=tid, flag=flag)

def _wrap(lines, width=95):
    out = []
    for l in lines:
        while len(l) > width:
            out.append(l[:width]); l = "    " + l[width:]
        out.append(l)
    return out
