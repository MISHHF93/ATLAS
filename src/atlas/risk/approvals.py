"""Owner approval queue with TTL, persisted in the shared StateStore so the
owner CLI (separate process) and the core process see the same queue.

Flow: AI/strategy intent approved by risk => `pending`
      owner (CLI/dashboard, step-up verified) => `owner_approved`
      core process re-runs the risk gate and executes => `executed` | `rejected`
      not acted on within TTL => `expired` (also checked at execution time)
The AI has no path to approve (not exposed over MCP)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from atlas.governance.audit import AuditLog
from atlas.risk.models import OrderIntent
from atlas.risk.state_store import StateStore

PREFIX = "approval:"


@dataclass
class Pending:
    approval_id: str
    intent: OrderIntent
    created: float
    expires: float
    status: str = "pending"
    result: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"approval_id": self.approval_id, "intent": self.intent.model_dump(), "created": self.created,
                "expires": self.expires, "status": self.status, "result": self.result}

    @classmethod
    def from_json(cls, d: dict) -> "Pending":
        return cls(d["approval_id"], OrderIntent(**d["intent"]), d["created"], d["expires"], d["status"], d.get("result", {}))


class ApprovalQueue:
    def __init__(self, ttl_s: float, owner: str, audit: AuditLog, clock: Callable[[], float] = time.time,
                 store: StateStore | None = None):
        self.ttl_s = ttl_s
        self.owner = owner
        self.audit = audit
        self.clock = clock
        self.store = store or StateStore()

    def _save(self, p: Pending) -> None:
        self.store.set(PREFIX + p.approval_id, p.to_json())

    def get(self, approval_id: str) -> Pending:
        d = self.store.get(PREFIX + approval_id)
        if d is None:
            raise KeyError(approval_id)
        return Pending.from_json(d)

    def all(self) -> list[Pending]:
        return [Pending.from_json(v) for v in self.store.items(PREFIX).values()]

    @property
    def items(self) -> dict[str, Pending]:
        return {p.approval_id: p for p in self.all()}

    def enqueue(self, intent: OrderIntent) -> Pending:
        now = self.clock()
        p = Pending(uuid.uuid4().hex, intent, now, now + self.ttl_s)
        self._save(p)
        self.audit.append("approval.enqueue", {"approval_id": p.approval_id, "intent_id": intent.intent_id})
        return p

    def expire(self) -> int:
        now, n = self.clock(), 0
        for p in self.all():
            if p.status in ("pending", "owner_approved") and now > p.expires:
                p.status = "expired"
                self._save(p)
                n += 1
                self.audit.append("approval.expired", {"approval_id": p.approval_id})
        return n

    def pending(self) -> list[Pending]:
        self.expire()
        return [p for p in self.all() if p.status == "pending"]

    def _check_owner(self, approval_id: str, approver: str, step_up_verified: bool) -> Pending:
        self.expire()
        p = self.get(approval_id)
        if approver != self.owner or not step_up_verified:
            self.audit.append("approval.denied", {"approval_id": approval_id, "approver": approver}, actor=approver)
            raise PermissionError("only the owner with step-up auth can approve")
        if p.status != "pending":
            raise ValueError(f"approval {approval_id} is {p.status}")
        return p

    def mark_owner_approved(self, approval_id: str, approver: str, step_up_verified: bool) -> Pending:
        """Called from the owner CLI. Execution happens in the core process."""
        p = self._check_owner(approval_id, approver, step_up_verified)
        ok = []

        def fn(d):  # pending -> owner_approved only if still pending and not expired (atomic)
            if d and d.get("status") == "pending" and self.clock() <= d["expires"]:
                ok.append(True)
                return {**d, "status": "owner_approved"}
            return d
        self.store.update(PREFIX + approval_id, fn)
        if not ok:
            raise ValueError(f"approval {approval_id} is no longer pending")
        p.status = "owner_approved"
        self.audit.append("approval.owner_approved", {"approval_id": approval_id}, actor=approver)
        return p

    def process_owner_approved(self, execute: Callable[[OrderIntent], dict]) -> list[Pending]:
        """Core process: execute owner-approved items (risk re-checked inside `execute`)."""
        self.expire()
        done = []
        for p in self.all():
            if p.status != "owner_approved" or not self._claim(p.approval_id):
                continue
            try:
                p.result = execute(p.intent)
            except Exception as e:  # noqa: BLE001  never leave an item stuck in 'executing'
                p.result = {"executes": False, "reasons": [f"execute error: {e!r}"[:200]]}
            p.status = "executed" if p.result.get("executes") else "rejected"
            self._save(p)
            self.audit.append("approval.processed", {"approval_id": p.approval_id, "status": p.status})
            done.append(p)
        return done

    def _claim(self, approval_id: str) -> bool:
        """Atomically move owner_approved -> executing. Only one process (core, dashboard beat, CLI)
        can win, so an approved order can never be executed twice."""
        won = []

        def fn(d):
            if d and d.get("status") == "owner_approved":
                won.append(True)
                return {**d, "status": "executing"}
            return d
        self.store.update(PREFIX + approval_id, fn)
        return bool(won)

    def approve(self, approval_id: str, approver: str, step_up_verified: bool,
                execute: Callable[[OrderIntent], dict]) -> dict:
        """In-process convenience: mark + execute immediately."""
        self.mark_owner_approved(approval_id, approver, step_up_verified)
        for p in self.process_owner_approved(execute):
            if p.approval_id == approval_id:
                return p.result
        raise ValueError(f"approval {approval_id} is expired")

    def reject(self, approval_id: str, approver: str) -> None:
        if approver != self.owner:
            self.audit.append("approval.reject_denied", {"approval_id": approval_id, "approver": approver}, actor=approver)
            raise PermissionError("only the owner can reject")
        p = self.get(approval_id)
        if p.status == "pending":
            p.status = "rejected"
            self._save(p)
            self.audit.append("approval.rejected", {"approval_id": approval_id}, actor=approver)
