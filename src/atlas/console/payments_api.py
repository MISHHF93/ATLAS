"""Payments / treasury (SIMULATION) endpoints for the console. Never imports tradingbot.

Uses the payments service's own classes (Treasury, Manual, Fund, Costs) and its own approver
identities (payments Approvers file). Controls are the service's: allowlist + 24h cooling-off,
limits, dual control, safe stop, idempotency keys, hash-chained audit.

Allowed without step-up (login + CSRF): request a payee, request a transfer, reject, prepare an
instruction sheet (moves no money), reconciliation upload, engage the payments safe stop.
Step-up (passphrase + TOTP of the logged-in user's payments approver identity): approve payee,
approve transfer, mark executed, release safe stop.
There is deliberately NO route that calls Treasury.execute (adapters): money moves only by the
owner in the provider's own UI (manual mode)."""
from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from atlas.ledgers import audit as pay_audit
from atlas.ledgers.costs import Costs
from atlas.ledgers.db import connect
from atlas.ledgers.fund import StubNAV
from atlas.ledgers.manual import Manual
from atlas.ledgers.money import D
from atlas.ledgers.providers import RAILS
from atlas.ledgers.statements import simple_pdf, to_csv, to_pdf
from atlas.ledgers.stepup import Approvers, AuthError
from atlas.ledgers.treasury import COOLING_OFF_S, Treasury

from atlas.console.web import Request, Response, Router

STATUSES = ("pending_approval", "approved", "instructed", "pending_settlement", "settled", "rejected", "expired",
            "submit_error", "executed")


class PaymentsAPI:
    def __init__(self, var_dir: str | Path):
        self.var = Path(var_dir)
        self.db = str(self.var / "payments.sqlite")
        self.approvers = Approvers(self.var / "approvers.json")

    # one connection per request (sqlite connections are per-thread)
    def _tr(self) -> Treasury:
        return Treasury(connect(self.db), self.approvers)

    def _manual(self, tr: Treasury) -> Manual:
        return Manual(tr, self.var / "sheets")

    def available(self) -> bool:
        return Path(self.db).exists()

    def verify_stepup(self, session, passphrase: str, code: str) -> bool:
        try:
            self.approvers.verify(session.user, passphrase, code)
            return True
        except AuthError:
            return False

    def approver_enrolled(self, user: str) -> bool:
        try:
            return user in self.approvers.names()
        except Exception:  # noqa: BLE001
            return False

    def routes(self, r: Router) -> None:
        g = lambda p, f: r.add("GET", p, f)  # noqa: E731
        g("/api/p/summary", self.summary)
        g("/api/p/ledger", self.ledger)
        g("/api/p/transfers", self.transfers)
        g("/api/p/transfers/<tid>", self.transfer)
        g("/api/p/transfers/<tid>/sheet/<fmt>", self.sheet)
        g("/api/p/payees", self.payees)
        g("/api/p/investors", self.investors)
        g("/api/p/investors/<iid>/statement/<fmt>", self.statement)
        g("/api/p/fees", self.fees)
        g("/api/p/costs", self.costs)
        g("/api/p/audit", self.audit)
        r.add("POST", "/api/p/transfers", self.request_transfer)
        r.add("POST", "/api/p/transfers/<tid>/approve", self.approve_transfer, stepup="payments")
        r.add("POST", "/api/p/transfers/<tid>/reject", self.reject_transfer)
        r.add("POST", "/api/p/transfers/<tid>/prepare", self.prepare)
        r.add("POST", "/api/p/transfers/<tid>/mark-executed", self.mark_executed, stepup="payments")
        r.add("POST", "/api/p/payees", self.request_payee)
        r.add("POST", "/api/p/payees/<pid>/approve", self.approve_payee, stepup="payments")
        r.add("POST", "/api/p/recon", self.recon, max_body=512_000, body_types=("text/csv",))
        r.add("POST", "/api/p/kill", self.kill)
        r.add("POST", "/api/p/unkill", self.unkill, stepup="payments")

    def _verified(self, req: Request) -> Treasury:
        """Treasury whose approver check accepts only the user whose step-up the HTTP layer just verified."""
        if not req.stepup_user:
            raise PermissionError("step-up not verified")
        return Treasury(connect(self.db), _StepUpPassthrough(req.stepup_user))

    def _need(self):
        if not self.available():
            raise KeyError("payments database not initialised (run atlas-payments init or seed-demo)")

    # ---------------------------------------------------------------- reads
    def summary(self, req: Request):
        if not self.available():
            return {"available": False, "reason": "payments DB not found"}
        tr = self._tr()
        c = tr.c
        bal: dict = {}
        for acct, ccy, amt in c.execute("SELECT account, currency, amount FROM postings"):
            if acct.startswith("asset:"):
                bal.setdefault(acct, {}).setdefault(ccy, Decimal(0))
                bal[acct][ccy] += D(amt)
        by_status = {s: n for s, n in c.execute("SELECT status, COUNT(*) FROM transfers GROUP BY status")}
        settings = {k: v for k, v in c.execute("SELECT k, v FROM settings")}
        pend = self._manual(tr).pending()
        cad_total = sum((tr.fx.to_cad(v, ccy) for d in bal.values() for ccy, v in d.items()), Decimal(0))
        return {"available": True, "balances": {a: {k: str(v) for k, v in d.items()} for a, d in bal.items()},
                "cash_cad_equiv": str(cad_total), "by_status": by_status, "settings": settings,
                "kill_switch": settings.get("kill") == "1", "pending_manual": pend,
                "required_approvals": tr.required_approvals(), "audit_entries": c.execute("SELECT COUNT(*) FROM audit").fetchone()[0],
                "rails": {k: {"currencies": sorted(v.currencies), "max_per_txn_cad": v.max_per_txn_cad, "crypto": v.crypto} for k, v in RAILS.items()}}

    def ledger(self, req: Request):
        self._need()
        c = self._tr().c
        lim = min(int(req.query.get("limit", "100")) if req.query.get("limit", "").isdigit() else 100, 500)
        js = [dict(r) for r in c.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (lim,))]
        for j in js:
            j["postings"] = [dict(p) for p in c.execute("SELECT account, currency, amount, amount_cad FROM postings WHERE journal_id=?", (j["id"],))]
        tb = sum((D(r[0]) for r in c.execute("SELECT amount_cad FROM postings")), Decimal(0))
        accts = []
        for a in c.execute("SELECT code, kind, currency FROM accounts ORDER BY code"):
            s = sum((D(r[0]) for r in c.execute("SELECT amount_cad FROM postings WHERE account=?", (a["code"],))), Decimal(0))
            accts.append({**dict(a), "balance_cad": str(s)})
        return {"journals": js, "trial_balance_cad": str(tb), "accounts": accts}

    def _transfers(self, c, where: str = "", args: tuple = ()) -> list[dict]:
        return [dict(r) for r in c.execute(
            "SELECT t.id, t.status, t.amount, t.currency, t.amount_cad, t.rail, t.source, t.purpose, t.created_at, t.executed_at,"
            " p.name AS payee, p.id AS payee_id, m.reference, m.value_date, m.expires_at, m.flag, m.confirmation"
            " FROM transfers t JOIN payees p ON p.id=t.payee_id LEFT JOIN manual_instructions m ON m.transfer_id=t.id"
            + where + " ORDER BY t.id DESC LIMIT 500", args)]

    def transfers(self, req: Request):
        self._need()
        c = self._tr().c
        st = req.query.get("status")
        rows = self._transfers(c, " WHERE t.status=?", (st,)) if st in STATUSES else self._transfers(c)
        if req.query.get("flagged") == "1":
            rows = [r for r in rows if r["flag"]]
        q = (req.query.get("q") or "").lower()
        if q:
            rows = [r for r in rows if q in json.dumps(r, default=str).lower()]
        return {"transfers": rows, "statuses": list(STATUSES)}

    def _actions(self, t: dict, tr: Treasury) -> list[str]:
        kill = tr.get("kill") == "1"
        s = t["status"]
        acts = []
        if s == "pending_approval" and not kill:
            acts += ["approve", "reject"]
        if s == "approved":
            acts += (["prepare"] if not kill else []) + ["reject"]
        if s == "instructed" and not kill:
            acts += ["mark-executed"]
        if t.get("reference"):
            acts += ["sheet"]
        return acts

    def transfer(self, req: Request):
        self._need()
        tr = self._tr()
        tid = int(req.params["tid"])
        rows = self._transfers(tr.c, " WHERE t.id=?", (tid,))
        if not rows:
            raise KeyError(tid)
        t = rows[0]
        appr = [dict(r) for r in tr.c.execute("SELECT approver, ts FROM approvals WHERE subject='transfer' AND subject_id=?", (tid,))]
        aud = [dict(r) for r in tr.c.execute("SELECT id, ts, actor, action, data FROM audit WHERE json_extract(data,'$.id')=?"
                                              " AND (action LIKE 'transfer.%') ORDER BY id", (tid,))]
        sheet = self._manual(tr).sheet_data(tid) if t["reference"] else None
        return {"transfer": t, "approvals": appr, "required_approvals": tr.required_approvals(), "audit": aud,
                "sheet": sheet, "actions": self._actions(t, tr), "kill_switch": tr.get("kill") == "1"}

    def sheet(self, req: Request):
        self._need()
        tr = self._tr()
        tid, fmt = int(req.params["tid"]), req.params["fmt"]
        m = self._manual(tr)
        d = m.sheet_data(tid)
        if not d["reference"]:
            raise KeyError("no instruction prepared for this transfer")
        md = Manual._md(d)
        name = f"transfer_{tid}_{d['reference']}"
        if fmt == "md":
            return Response.download(md, "text/markdown; charset=utf-8", name + ".md")
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["field", "value"])
            w.writerows([(k, v) for k, v in d.items() if k != "checklist"])
            w.writerows([("step", s) for s in d["checklist"]])
            return Response.download(buf.getvalue(), "text/csv", name + ".csv")
        if fmt == "pdf":
            from atlas.ledgers.manual import _wrap
            return Response.download(simple_pdf(_wrap(md.replace("|", " ").splitlines())), "application/pdf", name + ".pdf")
        raise KeyError(fmt)

    def payees(self, req: Request):
        self._need()
        tr = self._tr()
        now = tr.clock()
        out = []
        for p in tr.c.execute("SELECT * FROM payees ORDER BY id"):
            d = dict(p)
            d["destination_masked"] = "•" * min(max(len(d["destination"]) - 4, 0), 8) + d["destination"][-4:]
            del d["destination"]
            d["cooling_off_remaining_s"] = max(0, (p["active_from"] or 0) - now) if p["status"] == "approved" else None
            d["usable"] = p["status"] == "approved" and now >= (p["active_from"] or 0)
            d["approvals"] = [r[0] for r in tr.c.execute("SELECT approver FROM approvals WHERE subject='payee' AND subject_id=?", (p["id"],))]
            out.append(d)
        return {"payees": out, "cooling_off_s": COOLING_OFF_S, "rails": sorted(RAILS), "required_approvals": tr.required_approvals()}

    def _nav(self, tr) -> StubNAV:
        r = tr.c.execute("SELECT v FROM settings WHERE k='demo_nav'").fetchone()
        return StubNAV(r[0] if r else "10.00")

    def investors(self, req: Request):
        self._need()
        tr = self._tr()
        c = tr.c
        nav = self._nav(tr).nav_per_unit()
        inv = []
        for r in c.execute("SELECT * FROM investors ORDER BY id"):
            d = dict(r)
            d["value_cad"] = str(round(D(r["units"]) * nav, 2))
            inv.append(d)
        units = sum((D(i["units"]) for i in inv), Decimal(0))
        return {"nav_per_unit": str(nav), "units_outstanding": str(units), "aum_cad": str(round(units * nav, 2)),
                "investors": inv,
                "orders": [dict(r) | {"investor": r["name"]} for r in c.execute(
                    "SELECT o.*, i.name FROM orders o JOIN investors i ON i.id=o.investor_id ORDER BY o.id DESC LIMIT 200")],
                "flags": [dict(r) for r in c.execute("SELECT * FROM compliance_flags ORDER BY id DESC LIMIT 100")],
                "capital_calls": [dict(r) for r in c.execute("SELECT * FROM capital_calls ORDER BY id DESC LIMIT 100")],
                "nav_source": "StubNAV placeholder (read-only NAV feed from the trading side / administrator is PROPOSED)"}

    def statement(self, req: Request):
        self._need()
        tr = self._tr()
        iid, fmt = int(req.params["iid"]), req.params["fmt"]
        inv = tr.c.execute("SELECT name FROM investors WHERE id=?", (iid,)).fetchone()
        if not inv:
            raise KeyError(iid)
        nav = self._nav(tr)
        if fmt == "csv":
            return Response.download(to_csv(tr.c, iid, nav), "text/csv", f"statement_{iid}.csv")
        if fmt == "pdf":
            return Response.download(to_pdf(tr.c, iid, nav), "application/pdf", f"statement_{iid}.pdf")
        raise KeyError(fmt)

    def fees(self, req: Request):
        self._need()
        c = self._tr().c
        runs: dict = {}
        for r in c.execute("SELECT f.*, i.name FROM fees f JOIN investors i ON i.id=f.investor_id ORDER BY f.id"):
            k = (r["period"] or "-", r["kind"])
            run = runs.setdefault(k, {"period": k[0], "kind": k[1], "total_cad": Decimal(0), "lines": []})
            run["total_cad"] += D(r["amount"])
            run["lines"].append({"investor": r["name"], "amount": r["amount"], "ts": r["ts"]})
        out = sorted(runs.values(), key=lambda x: (x["period"], x["kind"]), reverse=True)
        for x in out:
            x["total_cad"] = str(x["total_cad"])
        return {"runs": out}

    def costs(self, req: Request):
        self._need()
        tr = self._tr()
        now = datetime.now()
        mf = req.query.get("from") or f"{now.year}-01"
        mt = req.query.get("to") or f"{now.year}-12"
        co = Costs(tr.c, tr.fx)
        rep = [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in co.report(mf, mt)]
        bills = [dict(r) for r in tr.c.execute("SELECT b.id, v.name AS vendor, v.category, b.amount, b.currency, b.amount_cad, b.month,"
                                               " b.status, b.invoice_sha256 FROM bills b JOIN vendors v ON v.id=b.vendor_id ORDER BY b.month DESC, b.id DESC LIMIT 300")]
        return {"from": mf, "to": mt, "report": rep, "bills": bills,
                "vendors": [dict(r) for r in tr.c.execute("SELECT * FROM vendors ORDER BY name")],
                "budgets": [dict(r) for r in tr.c.execute("SELECT * FROM budgets ORDER BY month DESC, category")]}

    def audit(self, req: Request):
        self._need()
        c = self._tr().c
        ok, bad = pay_audit.verify(c)
        q = (req.query.get("q") or "").lower()
        rows = [dict(r) for r in c.execute("SELECT id, ts, actor, action, data, hash FROM audit ORDER BY id DESC LIMIT 2000")]
        if q:
            rows = [r for r in rows if q in (r["action"] + r["actor"] + r["data"]).lower()]
        for r in rows:
            r["hash"] = r["hash"][:16]
        return {"chain": {"ok": ok, "broken_at": bad}, "entries": rows[:300], "total": len(rows)}

    # ---------------------------------------------------------------- writes
    def request_transfer(self, req: Request):
        self._need()
        b = req.body
        idem = str(b.get("idem_key") or "").strip()[:64] or "console-" + secrets.token_hex(8)
        amount = D(str(b.get("amount", "")).strip() or "0")
        if not amount.is_finite():
            raise ValueError("invalid amount")
        tr = self._tr()
        tid = tr.request_transfer(f"console:{req.session.user}", idem, int(b.get("payee_id", 0)), amount,
                                  str(b.get("currency", "CAD")).upper()[:3], str(b.get("source") or "asset:bank:cad")[:64],
                                  str(b.get("purpose", ""))[:200], str(b.get("debit_account") or "liability:payables")[:64])
        return {"id": tid, "status": tr.transfer(tid)["status"], "note": "request created; approval needs step-up"}

    def approve_transfer(self, req: Request):
        self._need()
        tr = self._verified(req)
        t = tr.approve_transfer(int(req.params["tid"]), req.stepup_user, "", "")
        return {"id": t["id"], "status": t["status"], "required_approvals": tr.required_approvals()}

    def reject_transfer(self, req: Request):
        self._need()
        tr = self._tr()
        tid = int(req.params["tid"])
        t = tr.transfer(tid)
        if not t:
            raise KeyError(tid)
        tr.reject_transfer(tid, f"console:{req.session.user}", str(req.body.get("reason", ""))[:200])
        return {"id": tid, "status": tr.transfer(tid)["status"]}

    def prepare(self, req: Request):
        self._need()
        tr = self._tr()
        tid = int(req.params["tid"])
        if not tr.transfer(tid):
            raise KeyError(tid)
        res = self._manual(tr).prepare(tid)
        return {"id": tid, "status": tr.transfer(tid)["status"], "reference": res["reference"]}

    def mark_executed(self, req: Request):
        self._need()
        conf = str(req.body.get("confirmation", "")).strip()[:100]
        if not conf:
            raise ValueError("provider confirmation number required")
        tr = self._verified(req)
        tid = int(req.params["tid"])
        Manual(tr, self.var / "sheets").mark_executed(tid, conf, req.stepup_user, "", "")
        return {"id": tid, "status": tr.transfer(tid)["status"]}

    def request_payee(self, req: Request):
        self._need()
        b = req.body
        tr = self._tr()
        pid = tr.request_payee(f"console:{req.session.user}", str(b.get("name", "")).strip()[:100] or "unnamed",
                               str(b.get("kind", "bank"))[:20], str(b.get("rail", "")).upper()[:10],
                               str(b.get("currency", "CAD")).upper()[:3], str(b.get("destination", "")).strip()[:200])
        return {"id": pid, "status": "pending", "note": f"approval needs step-up; then a {COOLING_OFF_S // 3600}h cooling-off applies"}

    def approve_payee(self, req: Request):
        self._need()
        tr = self._verified(req)
        p = tr.approve_payee(int(req.params["pid"]), req.stepup_user, "", "")
        if p is None:
            raise KeyError(req.params["pid"])
        return {"id": p["id"], "status": p["status"], "active_from": p["active_from"]}

    def recon(self, req: Request):
        self._need()
        text = req.raw.decode("utf-8", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows or not {"ref", "amount", "currency"} <= set(rows[0]):
            raise ValueError("CSV needs columns: date,ref,amount,currency[,memo]")
        stmt = []
        for r in rows[:5000]:
            amt = D(r["amount"])
            if not amt.is_finite():
                raise ValueError("bad amount")
            stmt.append({"date": r.get("date", ""), "ref": r["ref"], "amount": amt, "currency": r["currency"], "memo": r.get("memo", "")})
        tr = self._tr()
        res = self._manual(tr).reconcile(stmt)
        pay_audit.append(tr.c, f"console:{req.session.user}", "recon.upload", {"lines": len(stmt), "settled": res["settled"]})
        return res

    def kill(self, req: Request):
        self._need()
        tr = self._tr()
        tr.kill(f"console:{req.session.user}", str(req.body.get("reason", ""))[:200])
        return {"kill_switch": True}

    def unkill(self, req: Request):
        self._need()
        tr = self._verified(req)
        tr.unkill(req.stepup_user, "", "")
        return {"kill_switch": False}


class _StepUpPassthrough:
    """The HTTP layer already verified step-up (single-use TOTP). The payments service's own methods
    require (approver, passphrase, code) and verify again; a TOTP code cannot be reused, so for these
    calls we hand the service a verifier that accepts exactly the already-verified approver once."""

    def __init__(self, user: str):
        self.user, self.used = user, False

    def verify(self, name, passphrase, code):
        if self.used or name != self.user:
            raise AuthError("step-up failed")
        self.used = True

    def names(self):
        return [self.user]
