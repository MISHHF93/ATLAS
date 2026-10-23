"""Read-only bridge from the ATLAS API to the ported Lola data services (trading, payments, investor wallet,
compliance, tax). Only whitelisted GET handlers are reachable; every write stays in the step-up CLIs / owner
console. Data directory: ``ATLAS_FOUNDER_VAR`` (name only; default ``var/demo``, seeded with
``atlas-console seed-demo``; DEMO data is labelled as such)."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from atlas.console.web import Request

router = APIRouter(prefix="/api/founder/data", tags=["founder"])

READS: dict[str, tuple[str, ...]] = {
    "trading": ("state", "equity", "risk", "approvals", "decisions", "orders", "models", "strategies", "trials", "autopilot",
                "recipes", "feeds", "tax", "fund_nav", "reports", "audit", "ai_decisions"),
    "payments": ("summary", "ledger", "transfers", "transfer", "payees", "investors", "fees", "costs", "audit"),
    "wallet": ("summary", "subscriptions", "redemptions", "payouts", "recon_runs", "partners", "investor",
               "compliance", "hits", "fintrac", "calendar"),
}
_LOCK = threading.Lock()
_APIS: dict[str, Any] = {}


def founder_var() -> Path:
    return Path(os.environ.get("ATLAS_FOUNDER_VAR", "var/demo"))


def _apis() -> dict[str, Any]:
    with _LOCK:
        if _APIS:
            return _APIS
        from atlas.console.app import ConsolePaths
        from atlas.console.payments_api import PaymentsAPI
        from atlas.console.trading_api import TradingAPI
        from atlas.console.wallet_api import WalletAPI
        from atlas.control.founder_track import founder_policy_dir
        from atlas.mcp.trading.service import build_service

        var = founder_var()
        if not (var / "state.sqlite").exists():
            raise HTTPException(status_code=404, detail=f"No founder data in {var}. Run: atlas-console seed-demo --var {var}")
        if not os.environ.get("ATLAS_VAULT_KEY") and (var / "DEMO_VAULT_KEY").exists():
            os.environ["ATLAS_VAULT_KEY"] = (var / "DEMO_VAULT_KEY").read_text().strip()  # DEMO key only, never real
        paths = ConsolePaths.under(var, founder_policy_dir())
        svc = build_service(str(paths.config), paths.audit_db, paths.state_db, tax_db_path=paths.tax_db)
        svc.models_root = str(paths.models)
        _APIS.update(trading=TradingAPI(svc, paths.config, paths.stepup, paths.tokens, paths.reports, paths.models),
                     payments=PaymentsAPI(paths.payments_var), wallet=WalletAPI(paths.payments_var),
                     demo=(var / "DEMO_DATA_MARKER").exists())
        return _APIS


def reset_cache() -> None:
    with _LOCK:
        _APIS.clear()


@router.get("/status")
def status() -> dict[str, Any]:
    """Lets the UI show an empty state instead of probing views that 404 when nothing is seeded."""
    var = founder_var()
    return {"available": (var / "state.sqlite").exists(), "demo": (var / "DEMO_DATA_MARKER").exists(),
            "hint": f"atlas-console seed-demo --var {var}", "execution_permission": "none", "trading": "paper_only"}


@router.get("/{area}/{name}")
def read(area: str, name: str, id: str | None = None, status: str | None = None) -> dict[str, Any]:  # noqa: A002
    if name not in READS.get(area, ()):
        raise HTTPException(status_code=404, detail="not a readable founder view")
    apis = _apis()
    params = {"tid": id, "iid": id} if id else {}
    query = {"status": status} if status else {}
    req = Request("GET", f"/{area}/{name}", query, params, {})
    try:
        out = getattr(apis[area], name)(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not isinstance(out, dict):
        out = {"items": out}
    from atlas.console.web import _finite

    return {**_finite(out), "demo": apis["demo"], "execution_permission": "none", "trading": "paper_only",
            "writes": "owner CLI / step-up only (atlas-owner, atlas-payments)"}
