"""Research API for the persistent vertical slice.

The endpoints expose forecasts, walk-forward evidence, model inputs, resolved
outcomes, and paper authorizations. They never return an order permission.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.api.rbac import verify_role_action
from atlas.research.vertical_slice import (
    FEATURE_FAMILIES,
    PATH_ID,
    get_vertical_slice_scheduler,
    get_vertical_slice_service,
)

router = APIRouter(prefix="/api/research/vertical-slice", tags=["vertical-slice"])


class RunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC-USD"])
    bucket_seconds: int = Field(default=86_400, ge=60, le=86_400)
    horizon_steps: int = Field(default=1, ge=1, le=12)


class ResolveRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC-USD"])


class FeatureAblationRequest(BaseModel):
    symbol: str = Field(default="BTC-USD", min_length=1, max_length=32)
    bucket_seconds: int = Field(default=86_400, ge=60, le=86_400)
    horizon_steps: int = Field(default=1, ge=1, le=24)
    families: list[str] | None = Field(
        default=None,
        max_length=len(FEATURE_FAMILIES),
    )
    include_regimes: bool = False
    include_session: bool = False
    include_cross_asset: bool = False
    reference_symbol: str | None = Field(default=None, min_length=1, max_length=32)


class MultiFeatureAblationRequest(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: ["BTC-USD", "ETH-USD", "SPY"],
        min_length=1,
        max_length=6,
    )
    bucket_seconds: int = Field(default=86_400, ge=60, le=86_400)
    horizon_steps: list[int] = Field(
        default_factory=lambda: [1, 5],
        min_length=1,
        max_length=3,
    )
    families: list[str] | None = Field(
        default=None,
        max_length=len(FEATURE_FAMILIES),
    )
    include_regimes: bool = True
    include_session: bool = False
    include_cross_asset: bool = False
    reference_symbol: str | None = Field(default=None, min_length=1, max_length=32)


class MultiEvaluateRequest(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: ["BTC-USD", "ETH-USD", "SPY"],
        min_length=1,
        max_length=12,
    )
    bucket_seconds: int = Field(default=86_400, ge=60, le=86_400)
    horizon_steps: list[int] = Field(
        default_factory=lambda: [1, 5, 20],
        min_length=1,
        max_length=6,
    )


def _authorize(role_id: str | None, action: Literal["view", "run_walk_forward_experiment"]) -> None:
    if role_id is None or not role_id.strip():
        return
    try:
        verdict = verify_role_action(role_id, action, route="/research")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not verdict["authorized"]:
        raise HTTPException(status_code=403, detail=str(verdict["reason"]))


@router.get("/status")
def vertical_slice_status() -> dict:
    return {
        **get_vertical_slice_service().status(),
        "scheduler": get_vertical_slice_scheduler().status(),
    }


@router.get("/forecasts")
def vertical_slice_forecasts(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return {
        "path_id": PATH_ID,
        "forecasts": get_vertical_slice_service().forecasts(limit),
        "execution_permission": "none",
    }


@router.get("/chart")
def vertical_slice_chart(
    symbol: str = Query(default="BTC-USD", min_length=1, max_length=32),
    limit: int = Query(default=160, ge=20, le=500),
) -> dict:
    return get_vertical_slice_service().chart(symbol.upper(), limit)


@router.get("/paper-trades")
def vertical_slice_paper_trades(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return {
        "paper_trades": get_vertical_slice_service().paper_trades(limit),
        "execution_permission": "none",
        "notice": "These are paper authorizations, not venue fills.",
    }


@router.get("/lucky-moments")
def vertical_slice_lucky_moments(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return {
        "lucky_moments": get_vertical_slice_service().lucky_moments(limit),
        "notice": "These are favorable outcomes that may be luck; they are not evidence of repeatable skill.",
        "execution_permission": "none",
    }


@router.post("/feature-ablation")
def vertical_slice_feature_ablation(
    payload: FeatureAblationRequest,
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_service().ablate_features(
        symbol=payload.symbol.upper(),
        bucket_seconds=payload.bucket_seconds,
        horizon_steps=payload.horizon_steps,
        families=payload.families,
        include_regimes=payload.include_regimes,
        include_session=payload.include_session,
        include_cross_asset=payload.include_cross_asset,
        reference_symbol=payload.reference_symbol,
        fetch=True,
    )


@router.post("/feature-ablation-multi")
def vertical_slice_feature_ablation_multi(
    payload: MultiFeatureAblationRequest,
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_service().ablate_multi(
        symbols=[symbol.upper() for symbol in payload.symbols if symbol.strip()],
        bucket_seconds=payload.bucket_seconds,
        horizon_steps=payload.horizon_steps,
        families=payload.families,
        include_regimes=payload.include_regimes,
        include_session=payload.include_session,
        include_cross_asset=payload.include_cross_asset,
        reference_symbol=payload.reference_symbol,
        fetch=True,
    )


@router.post("/evaluate-multi")
def vertical_slice_evaluate_multi(
    payload: MultiEvaluateRequest,
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_service().evaluate_multi(
        symbols=[symbol.upper() for symbol in payload.symbols if symbol.strip()],
        bucket_seconds=payload.bucket_seconds,
        horizon_steps=payload.horizon_steps,
        fetch=True,
    )


@router.get("/scheduler")
def vertical_slice_scheduler_status() -> dict:
    return get_vertical_slice_scheduler().status()


@router.post("/scheduler/tick")
def vertical_slice_scheduler_tick(
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_scheduler().tick()


@router.post("/scheduler/start")
def vertical_slice_scheduler_start(
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_scheduler().start()


@router.post("/scheduler/stop")
def vertical_slice_scheduler_stop(
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_scheduler().stop()


@router.post("/run")
def vertical_slice_run(
    payload: RunRequest,
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_service().run(
        symbols=[symbol.upper() for symbol in payload.symbols if symbol.strip()],
        bucket_seconds=payload.bucket_seconds,
        horizon_steps=payload.horizon_steps,
        fetch=True,
    )


@router.post("/resolve")
def vertical_slice_resolve(
    payload: ResolveRequest,
    x_atlas_role: str | None = Header(default=None),
) -> dict:
    _authorize(x_atlas_role, "run_walk_forward_experiment")
    return get_vertical_slice_service().resolve(
        symbols=[symbol.upper() for symbol in payload.symbols if symbol.strip()],
        fetch=True,
    )
