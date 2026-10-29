"""GET /api/account/snapshot: read-only, broker-agnostic account state. No order, no key echoed, execution_permission=none."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/api/account/snapshot")
def account_snapshot(broker: str = Query("paper_sim", max_length=20), sim_equity: float | None = Query(None, ge=0.5, le=10_000_000),
                     risk_fraction: float = Query(0.005, gt=0, le=0.05), stop_distance: float = Query(0.02, gt=0, le=0.5)) -> dict[str, Any]:
    from atlas.accounts.credentials import effective_environ
    from atlas.broker_state.service import get_snapshot
    from atlas.integrations.registry import load_env
    env = load_env(environ=dict(effective_environ()))
    return get_snapshot(broker, env, sim_equity=sim_equity, risk_fraction=risk_fraction, stop_distance_frac=stop_distance)
