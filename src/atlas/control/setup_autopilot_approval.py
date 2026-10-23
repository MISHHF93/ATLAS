"""Owner approval for the paper setup autopilot switch (kept outside ``atlas.autopilot`` on purpose: the autopilot
package can never approve itself). Shared by the owner CLI and the API process through the state DB."""
from __future__ import annotations

import time
from typing import Any

from atlas.autopilot.control import StepUpRequired
from atlas.autopilot.setups import REQUESTS, SWITCH
from atlas.governance.audit import AuditLog
from atlas.risk.state_store import StateStore


def approve_request(store: StateStore, audit: AuditLog, request_id: str, actor: str, step_up_verified: bool,
                    expected_owner: str, safe_stop_engaged: bool, now: float | None = None) -> dict[str, Any]:
    """Owner approval (shared by the API process and the owner CLI through the state DB)."""
    now = time.time() if now is None else now
    if actor != expected_owner or not step_up_verified:
        audit.append("setup_autopilot.approve_refused", {"id": request_id, "reason": "owner step-up required"}, actor=actor)
        raise StepUpRequired("switching the paper autopilot on requires the owner with step-up")
    req = next((r for r in (store.get(REQUESTS) or []) if r["id"] == request_id and r["expires"] > now), None)
    if req is None:
        raise LookupError("unknown or expired request")
    store.update(REQUESTS, lambda old: [r for r in (old or []) if r["id"] != request_id], [])
    if safe_stop_engaged:
        audit.append("setup_autopilot.approve_refused", {"id": request_id, "reason": "safe_stop_engaged"}, actor=actor)
        raise PermissionError("Safe stop is engaged; reset it through the owner flow first")
    store.set(SWITCH, {"on": True, "by": actor, "request": request_id, "at": now})
    audit.append("setup_autopilot.switched_on", {"id": request_id}, actor=actor)
    return {"on": True, "request": request_id}
