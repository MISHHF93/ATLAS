"""Platform costs: vendors, budgets, recurring bills, approval, invoice storage,
category reports (CAD, with USD->CAD FX). Paying a bill is a Treasury transfer."""
from __future__ import annotations
import csv, hashlib, io, shutil
from decimal import Decimal
from pathlib import Path
from atlas.ledgers import audit
from atlas.ledgers.db import now
from atlas.ledgers.money import D, FX

CATEGORIES = ("data_feeds", "servers", "apis", "exchange_fees", "software", "other")

def _add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-")); m += n - 1
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"

class Costs:
    def __init__(self, c, fx: FX | None = None, invoice_dir="var/invoices", clock=now):
        self.c, self.fx, self.dir, self.clock = c, fx or FX(), Path(invoice_dir), clock

    def _a(self, actor, action, **d): audit.append(self.c, actor, action, d, self.clock)

    def add_vendor(self, name, category, currency="CAD") -> int:
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return self.c.execute("INSERT INTO vendors(name,category,currency) VALUES(?,?,?)", (name, category, currency)).lastrowid

    def set_budget(self, category, month, amount_cad):
        self.c.execute("INSERT OR REPLACE INTO budgets VALUES(?,?,?)", (category, month, str(D(amount_cad))))

    def add_bill(self, vendor_id, amount, month, currency=None, invoice_file=None, recurring_id=None) -> int:
        v = self.c.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
        ccy = currency or v["currency"]
        path = sha = None
        if invoice_file:
            data = Path(invoice_file).read_bytes(); sha = hashlib.sha256(data).hexdigest()
            self.dir.mkdir(parents=True, exist_ok=True)
            path = str(self.dir / f"{sha[:16]}{Path(invoice_file).suffix}")
            shutil.copyfile(invoice_file, path)
        bid = self.c.execute("INSERT INTO bills(vendor_id,amount,currency,amount_cad,month,status,invoice_path,invoice_sha256,recurring_id)"
                             " VALUES(?,?,?,?,?,?,?,?,?)", (vendor_id, str(D(amount)), ccy, str(self.fx.to_cad(amount, ccy)), month,
                                                            "pending", path, sha, recurring_id)).lastrowid
        self._a("finance", "bill.add", id=bid, vendor=v["name"], amount=str(amount), currency=ccy, month=month)
        return bid

    def approve_bill(self, bid, approvers, approver, passphrase, code):
        approvers.verify(approver, passphrase, code)
        self.c.execute("UPDATE bills SET status='approved' WHERE id=? AND status='pending'", (bid,))
        self._a(approver, "bill.approve", id=bid)

    def mark_paid(self, bid, transfer_id):
        self.c.execute("UPDATE bills SET status='paid' WHERE id=? AND status='approved'", (bid,))
        self._a("finance", "bill.paid", id=bid, transfer=transfer_id)

    def add_recurring(self, vendor_id, amount, start_month, every_months=1, currency=None) -> int:
        ccy = currency or self.c.execute("SELECT currency FROM vendors WHERE id=?", (vendor_id,)).fetchone()[0]
        return self.c.execute("INSERT INTO recurring(vendor_id,amount,currency,every_months,next_month,active) VALUES(?,?,?,?,?,1)",
                              (vendor_id, str(D(amount)), ccy, every_months, start_month)).lastrowid

    def run_recurring(self, through_month) -> list[int]:
        out = []
        for r in self.c.execute("SELECT * FROM recurring WHERE active=1").fetchall():
            m = r["next_month"]
            while m <= through_month:
                out.append(self.add_bill(r["vendor_id"], r["amount"], m, r["currency"], recurring_id=r["id"]))
                m = _add_months(m, r["every_months"])
            self.c.execute("UPDATE recurring SET next_month=? WHERE id=?", (m, r["id"]))
        return out

    def report(self, month_from, month_to) -> list[dict]:
        rows = self.c.execute("SELECT v.category, b.month, b.amount_cad FROM bills b JOIN vendors v ON v.id=b.vendor_id"
                              " WHERE b.month BETWEEN ? AND ?", (month_from, month_to)).fetchall()
        agg: dict = {}
        for r in rows:
            agg[(r[0], r[1])] = agg.get((r[0], r[1]), Decimal(0)) + D(r[2])
        for b in self.c.execute("SELECT * FROM budgets WHERE month BETWEEN ? AND ?", (month_from, month_to)):
            agg.setdefault((b["category"], b["month"]), Decimal(0))
        out = []
        for (cat, m), spent in sorted(agg.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            b = self.c.execute("SELECT amount_cad FROM budgets WHERE category=? AND month=?", (cat, m)).fetchone()
            budget = D(b[0]) if b else None
            out.append({"month": m, "category": cat, "spent_cad": spent, "budget_cad": budget,
                        "variance_cad": (budget - spent) if budget is not None else None,
                        "over_budget": budget is not None and spent > budget})
        return out

    def report_csv(self, month_from, month_to) -> str:
        buf = io.StringIO(); rows = self.report(month_from, month_to)
        w = csv.DictWriter(buf, fieldnames=["month", "category", "spent_cad", "budget_cad", "variance_cad", "over_budget"])
        w.writeheader(); w.writerows(rows); return buf.getvalue()
