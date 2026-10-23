"""Outbound money movement controls.

Every outbound transfer: kill-switch check -> allowlisted & cooled-off payee ->
rail/currency check -> limits (per-transfer/daily/monthly, CAD) -> idempotency
-> owner approval(s) with step-up (2 distinct approvers if dual control) ->
simulated adapter submit -> double-entry posting -> audit."""
from __future__ import annotations
import datetime as dt
import json
from decimal import Decimal
from atlas.ledgers import audit
from atlas.ledgers.db import now, tx
from atlas.ledgers.ledger import Ledger
from atlas.ledgers.money import D, FX
from atlas.ledgers.providers import RAILS, ProviderDisabled, default_adapters
from atlas.ledgers.stepup import Approvers

COOLING_OFF_S = 24 * 3600
DEFAULT_SETTINGS = {"kill": "0", "dual_control": "0", "limit_per_transfer_cad": "50000",
                    "limit_daily_cad": "100000", "limit_monthly_cad": "500000",
                    "execution_mode": "manual"}  # manual (default) | adapter (simulated)

class ControlError(PermissionError): ...

class Treasury:
    def __init__(self, c, approvers: Approvers, fx: FX | None = None, adapters=None, clock=now):
        self.c, self.auth, self.fx, self.clock = c, approvers, fx or FX(), clock
        self.ledger = Ledger(c, self.fx, clock)
        self.adapters = adapters if adapters is not None else default_adapters()
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))

    # settings / kill switch
    def get(self, k): return self.c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()[0]
    def _set(self, k, v): self.c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)))
    def _audit(self, actor, action, **data): audit.append(self.c, actor, action, data, self.clock)

    def kill(self, actor: str, reason: str = ""):
        """Engaging the kill switch needs no step-up (fail-safe direction)."""
        self._set("kill", "1"); self._audit(actor, "kill_switch.on", reason=reason)

    def unkill(self, approver, passphrase, code):
        self.auth.verify(approver, passphrase, code)
        self._set("kill", "0"); self._audit(approver, "kill_switch.off")

    def set_setting(self, k, v, approver, passphrase, code):
        if k not in DEFAULT_SETTINGS or k == "kill":
            raise KeyError(k)
        if k == "execution_mode" and v not in ("manual", "adapter"):
            raise ValueError(v)
        self.auth.verify(approver, passphrase, code)
        self._set(k, v); self._audit(approver, "settings.change", key=k, value=str(v))

    def required_approvals(self) -> int:
        return 2 if self.get("dual_control") == "1" else 1

    def _approve(self, subject, sid, approver, passphrase, code) -> int:
        self.auth.verify(approver, passphrase, code)
        self.c.execute("INSERT OR IGNORE INTO approvals(subject,subject_id,approver,ts) VALUES(?,?,?,?)",
                       (subject, sid, approver, self.clock()))
        self._audit(approver, f"{subject}.approve", id=sid)
        return self.c.execute("SELECT COUNT(DISTINCT approver) FROM approvals WHERE subject=? AND subject_id=?",
                              (subject, sid)).fetchone()[0]

    # payees
    def request_payee(self, actor, name, kind, rail, currency, destination) -> int:
        if rail not in RAILS:
            raise ValueError(f"unknown rail {rail}")
        if kind == "wallet" and not RAILS[rail].crypto:
            raise ValueError("wallet payees must use CRYPTO rail")
        pid = self.c.execute("INSERT INTO payees(name,kind,rail,currency,destination,status,requested_at) VALUES(?,?,?,?,?,?,?)",
                             (name, kind, rail, currency, destination, "pending", self.clock())).lastrowid
        self._audit(actor, "payee.request", id=pid, name=name, rail=rail, destination=destination)
        return pid

    def approve_payee(self, pid, approver, passphrase, code):
        n = self._approve("payee", pid, approver, passphrase, code)
        if n >= self.required_approvals():
            t = self.clock()
            self.c.execute("UPDATE payees SET status='approved', approved_at=?, active_from=? WHERE id=? AND status='pending'",
                           (t, t + COOLING_OFF_S, pid))
        return self.payee(pid)

    def payee(self, pid):
        return self.c.execute("SELECT * FROM payees WHERE id=?", (pid,)).fetchone()

    # limits
    def _spent_cad(self, since: float) -> Decimal:
        rows = self.c.execute("SELECT amount_cad FROM transfers WHERE created_at>=? AND status NOT IN ('rejected','failed')", (since,))
        return sum((D(r[0]) for r in rows), Decimal(0))

    def _check_limits(self, cad: Decimal):
        t = dt.datetime.fromtimestamp(self.clock())
        day0 = t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        mon0 = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        if cad > D(self.get("limit_per_transfer_cad")):
            raise ControlError("per-transfer limit exceeded")
        if self._spent_cad(day0) + cad > D(self.get("limit_daily_cad")):
            raise ControlError("daily limit exceeded")
        if self._spent_cad(mon0) + cad > D(self.get("limit_monthly_cad")):
            raise ControlError("monthly limit exceeded")

    # transfers
    def request_transfer(self, actor, idem_key, payee_id, amount, currency, source="asset:bank:cad",
                         purpose="", debit_account="liability:payables"):
        amount = D(amount)
        prev = self.c.execute("SELECT * FROM transfers WHERE idem_key=?", (idem_key,)).fetchone()
        if prev:
            if prev["payee_id"] != payee_id or D(prev["amount"]) != amount or prev["currency"] != currency:
                raise ControlError("idempotency key reused with different parameters")
            return prev["id"]
        if self.get("kill") == "1":
            raise ControlError("payments kill switch engaged")
        if amount <= 0:
            raise ValueError("amount must be positive")
        p = self.payee(payee_id)
        if not p or p["status"] != "approved":
            raise ControlError("payee not on allowlist")
        if self.clock() < p["active_from"]:
            raise ControlError("payee in 24h cooling-off period")
        if p["currency"] != currency or currency not in RAILS[p["rail"]].currencies:
            raise ControlError("currency/rail mismatch")
        cad = self.fx.to_cad(amount, currency)
        mx = RAILS[p["rail"]].max_per_txn_cad
        if mx is not None and cad > mx:
            raise ControlError(f"{p['rail']} per-transaction cap exceeded")
        self._check_limits(cad)
        meta = json.dumps({"debit": debit_account})
        tid = self.c.execute(
            "INSERT INTO transfers(idem_key,payee_id,amount,currency,amount_cad,rail,source,purpose,status,created_at,provider_ref)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (idem_key, payee_id, str(amount), currency, str(cad), p["rail"], source, purpose, "pending_approval",
             self.clock(), meta)).lastrowid
        self._audit(actor, "transfer.request", id=tid, idem_key=idem_key, amount=str(amount), currency=currency, payee=payee_id, debit=debit_account)
        return tid

    def approve_transfer(self, tid, approver, passphrase, code):
        t = self.transfer(tid)
        if t["status"] != "pending_approval":
            raise ControlError(f"transfer is {t['status']}")
        if self.get("kill") == "1":
            raise ControlError("payments kill switch engaged")
        if self._approve("transfer", tid, approver, passphrase, code) >= self.required_approvals():
            # conditional: a transfer rejected meanwhile (another process) must not flip back to approved
            self.c.execute("UPDATE transfers SET status='approved' WHERE id=? AND status='pending_approval'", (tid,))
        return self.transfer(tid)

    def reject_transfer(self, tid, actor, reason=""):
        self.c.execute("UPDATE transfers SET status='rejected' WHERE id=? AND status IN ('pending_approval','approved')", (tid,))
        self._audit(actor, "transfer.reject", id=tid, reason=reason)

    def transfer(self, tid):
        return self.c.execute("SELECT * FROM transfers WHERE id=?", (tid,)).fetchone()

    def execute(self, tid, adapter: str, actor="system"):
        t = self.transfer(tid)
        if self.get("kill") == "1":
            raise ControlError("payments kill switch engaged")
        if self.get("execution_mode") != "adapter":
            raise ControlError("manual execution mode: generate an instruction sheet and mark executed (see manual.py)")
        if t["status"] != "approved":
            raise ControlError(f"transfer not approved (status {t['status']})")
        p = self.payee(t["payee_id"])
        debit = json.loads(t["provider_ref"])["debit"]
        ad = self.adapters[adapter]
        if not ad.enabled:
            raise ProviderDisabled(f"adapter {adapter} is disabled")
        if t["rail"] not in ad.rails:  # pre-flight checks (nothing sent) before the claim
            raise ValueError(f"{adapter} does not support rail {t['rail']}")
        # atomic claim approved -> submitting so two executors can never submit the same transfer twice
        with tx(self.c):
            if self.c.execute("UPDATE transfers SET status='submitting' WHERE id=? AND status='approved'", (tid,)).rowcount != 1:
                raise ControlError(f"transfer {tid} already being executed")
        try:
            ref = self.adapters[adapter].submit({**dict(t), "destination": p["destination"]})
        except Exception as e:
            # ProviderDisabled = nothing was sent: back to approved. Anything else: outcome unknown, so
            # do NOT allow an automatic retry; park as submit_error for manual review.
            st = "approved" if isinstance(e, ProviderDisabled) else "submit_error"
            self.c.execute("UPDATE transfers SET status=? WHERE id=?", (st, tid))
            self._audit(actor, "transfer.submit_error", id=tid, error=str(e))
            raise
        with tx(self.c):
            self.ledger.post(f"transfer {tid} to {p['name']}",
                             [(debit, D(t["amount"]), t["currency"]), (t["source"], -D(t["amount"]), t["currency"])], ref=ref)
            self.c.execute("UPDATE transfers SET status='executed', executed_at=?, provider_ref=? WHERE id=?",
                           (self.clock(), ref, tid))
        self._audit(actor, "transfer.executed", id=tid, provider_ref=ref)
        return ref
