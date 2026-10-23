"""Owner console surfaces for the local web UI (localhost + same-origin only, ``X-Atlas-Console: 1`` on writes).

Only actions that are read-only or *reduce* risk/privilege are exposed here:
- setup autopilot: status, file an ON *request* (the owner still approves with step-up in the CLI), switch OFF;
- shadow-week stats (read-only);
- API keys: list, revoke, and create ``read``/``research`` keys (shown once). ``paper-trade`` keys stay CLI-only;
- paper approvals: reject. Approving stays ``atlas-owner approve <id>`` with step-up.
Nothing here places an order, moves money, resets the Safe stop or approves the autopilot.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from atlas.api.agent import _local, autopilot, keys

console_router = APIRouter(prefix="/api/console", tags=["console"])
UI_SCOPES = ("read", "research")
APPROVE_AUTOPILOT = "atlas-owner setup-autopilot-approve {rid}  (owner passphrase + TOTP)"


def _write(request: Request) -> None:
    _local(request)
    if request.headers.get("x-atlas-console") != "1":
        raise HTTPException(status_code=403, detail="console_header_required")


class OnIn(BaseModel):
    note: str = Field(default="", max_length=200)


class OffIn(BaseModel):
    reason: str = Field(default="switched_off_from_console", max_length=200)


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: str = "read"
    rate_per_min: int = Field(default=60, ge=1, le=6000)


@console_router.get("/autopilot")
def console_autopilot(request: Request) -> dict[str, Any]:
    _local(request)
    st = autopilot().status()
    st["approve_with"] = [APPROVE_AUTOPILOT.format(rid=r["id"]) for r in st.get("pending_requests", [])]
    return st


@console_router.post("/autopilot/request-on")
def console_autopilot_request_on(body: OnIn, request: Request) -> dict[str, Any]:
    _write(request)
    req = autopilot().request_on("console", body.note, channel="console")
    return {**req, "approve_with": APPROVE_AUTOPILOT.format(rid=req["id"])}


@console_router.post("/autopilot/off")
def console_autopilot_off(body: OffIn, request: Request) -> dict[str, Any]:
    _write(request)
    return autopilot().switch_off("console", body.reason)


@console_router.get("/shadow")
def console_shadow(request: Request) -> dict[str, Any]:
    _local(request)
    from atlas.models.shadow import ShadowCollector
    return {"weeks": ShadowCollector().weekly(), "rule": "conservative_ohlc_v1", "execution_permission": "none"}


@console_router.get("/keys")
def console_keys(request: Request) -> dict[str, Any]:
    _local(request)
    return {"keys": keys().list(), "ui_scopes": list(UI_SCOPES),
            "paper_trade_with": "python -m atlas.keys.cli create --name <name> --scope paper-trade"}


@console_router.post("/keys")
def console_create_key(body: KeyIn, request: Request) -> dict[str, Any]:
    _write(request)
    if body.scope not in UI_SCOPES:
        raise HTTPException(status_code=403, detail="paper-trade keys are created from the owner CLI only: "
                            "python -m atlas.keys.cli create --name <name> --scope paper-trade")
    key, rec = keys().create(body.name, body.scope, body.rate_per_min)
    return {"key": key, "record": rec, "shown_once": True}


@console_router.post("/keys/{key_id}/revoke")
def console_revoke_key(key_id: str, request: Request) -> dict[str, Any]:
    _write(request)
    if not keys().revoke(key_id):
        raise HTTPException(status_code=404, detail="not found or already revoked")
    return {"revoked": key_id}


@console_router.post("/approvals/{approval_id}/reject")
def console_reject(approval_id: str, request: Request) -> dict[str, Any]:
    _write(request)
    from atlas.api.founder import service
    q = service().approvals
    try:
        q.reject(approval_id, q.owner)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="unknown approval") from e
    return {"approval_id": approval_id, "status": q.get(approval_id).status}


@console_router.post("/approvals/{approval_id}/approve")
def console_approve(approval_id: str) -> dict[str, Any]:
    raise HTTPException(status_code=403, detail=f"Approving needs owner step-up: atlas-owner approve {approval_id}")


@console_router.get("/models")
def console_models(request: Request) -> dict[str, Any]:
    """Registered price-action setup models. Empty means every setup abstains (no validated model yet)."""
    _local(request)
    from atlas.models.predict import DEFAULT_REGISTRY
    return {"versions": DEFAULT_REGISTRY.versions(), "policy": "unregistered setups abstain", "execution_permission": "none"}


@console_router.get("/evidence")
def console_evidence(request: Request, name: str | None = None) -> dict[str, Any]:
    _local(request)
    from atlas.api.agent import _t_evidence
    try:
        return _t_evidence({"name": name} if name else {})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
