"""Founder workbench API (ported from the Lola trading platform; see docs/lola-port-plan.md).

Read-mostly, paper-only endpoints for the owner's own-capital track: Safe stop, approval queue,
Action-needed inbox, Canadian venues, tax (ACB / superficial loss / BoC FX / T5008 / T1135),
the 8 non-custodial money ledgers and compliance. Every response carries
``execution_permission: "none"`` and ``trading: "paper_only"``. Nothing here can place, approve or
size an order. The one write (engage Safe stop) can only *halt*; reset and approvals require the
owner CLI with step-up auth (``atlas-owner``) and are deliberately not exposed over HTTP.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from atlas.control.founder_track import build_founder_rulebook, founder_policy_dir
from atlas.governance import EIGHT_NON_CUSTODIAL_LEDGERS, LEDGER_IMPLEMENTATIONS
from atlas.governance.audit import AuditLog
from atlas.risk.approvals import ApprovalQueue
from atlas.risk.killswitch import KillSwitch
from atlas.risk.state_store import StateStore

router = APIRouter(prefix="/api/founder", tags=["founder"])

ENVELOPE = {"execution_permission": "none", "trading": "paper_only", "track": "founder_capital"}


def _env(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, **ENVELOPE}


class _Svc:
    """Shares the SQLite state with the core/watchdog processes when ATLAS_STATE_DB / ATLAS_AUDIT_DB are set."""

    def __init__(self) -> None:
        self.store = StateStore(os.environ.get("ATLAS_STATE_DB", ":memory:"))
        self.audit = AuditLog(os.environ.get("ATLAS_AUDIT_DB", ":memory:"))
        from atlas.risk.safe_stop import shared_safe_stop

        self.ks = shared_safe_stop()  # the same Safe stop the control plane uses
        cfg = _config()
        ttl = float(cfg.risk.autonomy.approval_ttl_seconds) if cfg else 120.0
        owner = cfg.risk.owner if cfg else "owner"
        self.approvals = ApprovalQueue(ttl, owner, self.audit, store=self.store)


@lru_cache(maxsize=1)
def _config():
    try:
        from atlas.control.policy import load_all

        return load_all(founder_policy_dir())
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def service() -> _Svc:
    return _Svc()


def _safe_stop(svc: _Svc) -> dict[str, Any]:
    return {"engaged": svc.ks.engaged, "reason": svc.ks.reason, "engaged_at": svc.ks.engaged_at,
            "reset": "owner CLI only: `atlas-owner reset-kill-switch` (step-up auth)"}


class SafeStopPayload(BaseModel):
    reason: str = Field(default="owner_safe_stop_button", min_length=1, max_length=200)


@router.get("/state")
def founder_state() -> dict[str, Any]:
    book = build_founder_rulebook()
    svc = service()
    return _env({
        "rulebook_id": book.rulebook_id,
        "max_daily_loss_fraction": str(book.max_daily_loss_fraction),
        "max_drawdown_fraction": str(book.max_drawdown_fraction),
        "policy_loaded": _config() is not None,
        "safe_stop": _safe_stop(svc),
        "pending_approvals": len(svc.approvals.pending()),
        "ai_authority": "shrink_or_veto_only",
        "live_trading": "locked",
    })


@router.get("/safe-stop")
def safe_stop_status() -> dict[str, Any]:
    return _env(_safe_stop(service()))


@router.post("/safe-stop")
def safe_stop_engage(payload: SafeStopPayload) -> dict[str, Any]:
    """Halt only. Engaging never needs step-up (reducing risk is always allowed); resetting does."""
    res = service().ks.engage(payload.reason, channel="atlas_frontend")
    return _env({"result": res, **_safe_stop(service())})


@router.post("/safe-stop/reset")
def safe_stop_reset() -> dict[str, Any]:
    raise HTTPException(status_code=403, detail="Safe stop reset requires the owner CLI with step-up auth (atlas-owner).")


@router.get("/approvals")
def approvals() -> dict[str, Any]:
    items = [{"approval_id": p.approval_id, "symbol": p.intent.symbol, "side": p.intent.side, "qty": p.intent.qty,
              "status": p.status} for p in service().approvals.pending()]
    return _env({"pending": items, "decide_with": "atlas-owner approve|reject <id> (step-up auth)"})


@router.get("/inbox")
def action_inbox() -> dict[str, Any]:
    svc = service()
    items: list[dict[str, Any]] = []
    if svc.ks.engaged:
        items.append({"area": "trading", "kind": "safe_stop", "severity": "critical", "title": "Trading is halted",
                      "detail": f"Safe stop: {svc.ks.reason or 'no reason'}. Reset needs step-up.", "href": "/control"})
    pend = svc.approvals.pending()
    if pend:
        items.append({"area": "trading", "kind": "approval", "severity": "high",
                      "title": f"{len(pend)} proposed paper trade(s) to approve or reject", "detail": "Expires if you do nothing.",
                      "href": "/inbox", "count": len(pend)})
    if _config() is None:
        items.append({"area": "trading", "kind": "policy", "severity": "high", "title": "Founder risk policy did not load",
                      "detail": "Built-in 2% daily-loss defaults are in force (fail closed).", "href": "/compliance"})
    for name, problem in _venue_problems():
        items.append({"area": "compliance", "kind": "venue", "severity": "normal", "title": f"Venue {name}: re-verify",
                      "detail": problem, "href": "/compliance"})
    return _env({"items": items, "count": len(items)})


def _venue_problems() -> list[tuple[str, str]]:
    cfg = _config()
    if not cfg or not cfg.venues:
        return []
    from atlas.control.policy.venues import as_of_date, registration_problem

    out = []
    for name, v in cfg.venues.venues.items():
        p = registration_problem(v, cfg.venues, as_of_date())
        if p:
            out.append((name, p))
    return out


@router.get("/venues")
def venues() -> dict[str, Any]:
    cfg = _config()
    if not cfg or not cfg.venues:
        return _env({"available": False, "venues": []})
    vc = cfg.venues
    rows = [{"venue": k, "legal_entity": v.legal_entity, "regulator": v.registration.regulator,
             "registration": v.registration.status, "last_verified": v.registration.last_verified.isoformat(),
             "paper_only": v.paper_only, "asset_classes": v.asset_classes, "spot_only": v.flags.spot_only,
             "margin": v.flags.margin, "derivatives": v.flags.derivatives} for k, v in vc.venues.items()]
    return _env({"available": True, "operating_entity": vc.operating_entity.model_dump(mode="json"),
                 "venues": rows, "excluded_venues": vc.excluded_venues, "problems": dict(_venue_problems())})


@router.get("/tax")
def tax_summary() -> dict[str, Any]:
    cfg = _config()
    tax = cfg.tax if cfg else None
    return _env({
        "jurisdiction": "CA",
        "method": "adjusted cost base (ACB, average cost per CRA)",
        "superficial_loss_guard": getattr(tax, "superficial_loss_guard", "warn"),
        "fx_source": "Bank of Canada daily rates (atlas.tax.boc_fetch)",
        "reports": ["T5008-style dispositions CSV", "T1135 foreign property check", "Schedule 3 capital gains"],
        "foreign_currencies": list(getattr(tax, "foreign_currencies", ["USD", "EUR", "GBP"])),
        "notice": "Records for your accountant; not tax advice and nothing is filed.",
    })


@router.get("/ledgers")
def ledgers() -> dict[str, Any]:
    rows = [{"ledger": k, **LEDGER_IMPLEMENTATIONS[k]} for k in EIGHT_NON_CUSTODIAL_LEDGERS]
    balances: dict[str, Any] = {"available": False}
    db = os.environ.get("ATLAS_PAYMENTS_DB")
    if db and os.path.exists(db):
        from atlas.ledgers.readonly import BalanceView

        try:
            balances = {"available": True, **BalanceView(db).summary()}
        except Exception as exc:  # noqa: BLE001
            balances = {"available": False, "error": type(exc).__name__}
    return _env({"custody": "non_custodial", "ledgers": rows, "payments": balances})


@router.get("/compliance")
def compliance() -> dict[str, Any]:
    from atlas.compliance.fintrac import KINDS, RETENTION_YEARS, THRESHOLD, TRAVEL_RULE_MIN

    return _env({
        "fintrac": {"mode": "records_only_simulation", "record_kinds": KINDS, "threshold_cad": str(THRESHOLD),
                    "travel_rule_min_cad": str(TRAVEL_RULE_MIN), "retention_years": RETENTION_YEARS},
        "sanctions": {"lists": ["SEMA (Canada)", "UN", "OFAC SDN"], "refresh": "python tools/fetch_sanctions_lists.py"},
        "privacy": "PIPEDA: minimum data, retention + purge with legal hold (atlas.compliance.privacy)",
        "venue_problems": dict(_venue_problems()),
        "notice": "Not legal advice. Nothing is filed or transmitted.",
    })
