"""HTTP surface for the ATLAS multi-agent research graph.

Every response is advisory.  There is deliberately no submit-order endpoint;
the strongest outcome in this API is a ``PAPER_REVIEW_AUTHORIZED`` dry-run.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.multi_agent.contracts import RunRequest
from atlas.multi_agent.service import MultiAgentService

router = APIRouter(prefix="/api/multi-agent", tags=["multi-agent"])


@lru_cache(maxsize=1)
def get_service() -> MultiAgentService:
    return MultiAgentService()


class ReflectRequest(BaseModel):
    model_config = {"extra": "forbid"}
    outcome_price: float = Field(gt=0)
    outcome_as_of: datetime | None = None
    benchmark_return: float | None = None


@router.get("/status")
def status() -> dict[str, Any]:
    return get_service().status()


@router.get("/agents")
def agents() -> dict[str, Any]:
    svc = get_service()
    return {"agents": svc.agents(), "execution_permission": "none"}


@router.post("/runs")
def create_run(request: RunRequest, force: bool = Query(default=False)) -> dict[str, Any]:
    try:
        state = get_service().start(request, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"run": state.model_dump(mode="json"), "execution_permission": "none"}


@router.get("/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=500), status: str | None = None) -> dict[str, Any]:
    rows = get_service().list_runs(limit=limit, status=status)
    return {"runs": [r.model_dump(mode="json") for r in rows], "execution_permission": "none"}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    state = get_service().get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"run": state.model_dump(mode="json"), "execution_permission": "none"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict[str, Any]:
    state = get_service().resume(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"run": state.model_dump(mode="json"), "execution_permission": "none"}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    if not get_service().cancel(run_id):
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"cancel_requested": True, "run_id": run_id, "execution_permission": "none"}


@router.get("/runs/{run_id}/audit")
def get_audit(run_id: str) -> dict[str, Any]:
    svc = get_service()
    if svc.get(run_id) is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {
        "events": svc.audit_log(run_id),
        "verification": svc.audit_verify(run_id),
        "execution_permission": "none",
    }


@router.post("/runs/{run_id}/reflect")
def reflect(run_id: str, request: ReflectRequest) -> dict[str, Any]:
    try:
        record = get_service().reflect(
            run_id,
            outcome_price=request.outcome_price,
            outcome_as_of=request.outcome_as_of,
            benchmark_return=request.benchmark_return,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reflection": record.model_dump(mode="json"), "execution_permission": "none"}


@router.get("/runs/{run_id}/reflections")
def reflections(run_id: str, limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    return {
        "reflections": [r.model_dump(mode="json") for r in get_service().reflections(run_id=run_id, limit=limit)],
        "execution_permission": "none",
    }


@router.get("/evolution")
def evolution() -> dict[str, Any]:
    report = get_service().evolution()
    return {"report": report.model_dump(mode="json"), "execution_permission": "none"}


__all__ = ["router", "get_service"]
