"""Read-only price-action endpoints. Candidates are proposals for the deterministic control plane;
nothing here submits, sizes, or authorizes an order (execution_permission: none)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.features.price_action import PRESETS, EngineConfig, PriceActionEngine, bars_from_rows
from atlas.features.price_action.proposals import candidate_to_signal, evaluate
from atlas.features.price_action.replay import ReplayConfig, replay

quant_router = APIRouter(prefix="/api/quant", tags=["quant"])


class BarsIn(BaseModel):
    instrument: str = Field(min_length=1)
    timeframe: int = Field(gt=0)
    rows: list[list[float]] = Field(description="[t_start_unix, o, h, l, c, v]")
    session: str | None = None
    data_label: str = Field(default="caller_supplied", description="e.g. synthetic_fixture")


def _engine(instrument: str, timeframe: int, session: str | None) -> PriceActionEngine:
    if session is not None and session not in PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown session; choose one of {sorted(PRESETS)}")
    return PriceActionEngine(instrument, timeframe, EngineConfig(session=PRESETS.get(session) if session else None))


def _payload(eng: PriceActionEngine, origin: Any) -> dict[str, Any]:
    out = eng.summary()
    out["evaluations"], out["proposals"] = [], []
    for c in eng.candidates:
        pred, ev = evaluate(c)   # default registry: no validated setup model -> abstains
        out["evaluations"].append({"candidate_id": c.candidate_id, "prediction": pred.to_dict(), "evaluation": ev.to_dict()})
        if not ev.abstained:
            out["proposals"].append({"candidate_id": c.candidate_id, "signal": candidate_to_signal(c, ev).model_dump(mode="json"),
                                     "submitted": False, "authority": "ActionableControlPlaneEngine"})
    out["feed_origin"] = origin
    return out


def _visible(symbol: str, resolution: str) -> tuple[list, Any, int]:
    from atlas.api.app import live_market_gateway
    from atlas.api.udf import _desk_symbol, _projected_rows, causal_bars, resolution_seconds

    bucket = resolution_seconds(resolution)
    if bucket is None:
        raise HTTPException(status_code=400, detail="unsupported_resolution")
    rows, report = _projected_rows(live_market_gateway, _desk_symbol(symbol), bucket)
    now = int(datetime.now(timezone.utc).timestamp())
    visible = causal_bars(rows, bucket_seconds=bucket, start=0, end=now + 1, as_of=now)
    return visible, report, bucket


def _desk(symbol: str, resolution: str, session: str | None) -> dict[str, Any]:
    now = int(datetime.now(timezone.utc).timestamp())
    visible, report, bucket = _visible(symbol, resolution)
    eng = _engine(symbol.upper(), bucket, session)
    eng.run_batch(bars_from_rows(visible, bucket), now=now)
    out = _payload(eng, report.get("feed_origin"))
    out["bars_used"] = len(visible)
    out["bars"] = [list(r) for r in visible]
    if not visible:
        out["note"] = "no confirmed bars available for this symbol"
    return out


@quant_router.get("/zones")
def quant_zones(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None) -> dict[str, Any]:
    out = _desk(symbol, resolution, session)
    return {k: out[k] for k in ("instrument", "timeframe", "zones", "bars_used", "feed_origin", "execution_permission")}


@quant_router.get("/setups")
def quant_setups(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None) -> dict[str, Any]:
    return _desk(symbol, resolution, session)


@quant_router.post("/analyze")
def quant_analyze(body: BarsIn) -> dict[str, Any]:
    """Stateless analysis of caller-supplied bars (read-only; nothing persisted)."""
    eng = _engine(body.instrument, body.timeframe, body.session)
    try:
        eng.run_batch(bars_from_rows(body.rows, body.timeframe))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _payload(eng, body.data_label)


@quant_router.get("/replay")
def quant_replay(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None,
                 cost_per_unit: float = Query(0.0, ge=0), max_hold_bars: int = Query(8, ge=1, le=500)) -> dict[str, Any]:
    """Conservative OHLC paper replay over the platform's confirmed bars (live detection path). Research only."""
    visible, report, bucket = _visible(symbol, resolution)
    eng = _engine(symbol.upper(), bucket, session)
    res = replay(symbol.upper(), bucket, bars_from_rows(visible, bucket), engine_cfg=eng.cfg,
                 cfg=ReplayConfig(cost_per_unit=cost_per_unit, max_hold_bars=max_hold_bars),
                 data_label=f"real:{report.get('feed_origin')}" if visible else "no_data")
    out = res.to_dict()
    out["feed_origin"] = report.get("feed_origin")
    out["note"] = "descriptive replay only; not a validated performance estimate"
    return out


# ---------- price-level suite + strategy registry (research; execution_permission none) ----------
from dataclasses import asdict as _asdict  # noqa: E402

from atlas.features.price_action.strategies import BY_ID as _STRAT, StrategyRegistry  # noqa: E402
from atlas.features.price_action.suite import StrategyToggles, SuiteConfig, is_gold  # noqa: E402

_CAL = {"GC": "COMEX", "MGC": "COMEX", "SI": "COMEX", "HG": "COMEX", "CL": "NYMEX", "ES": "CMES", "NQ": "CMES"}


class ToggleIn(BaseModel):
    enabled: bool


@quant_router.get("/strategies")
def quant_strategies() -> dict[str, Any]:
    return {"strategies": StrategyRegistry().listing(), "execution_permission": "none",
            "note": "toggles choose which detectors run and which candidates the selector may rank; they never authorize orders"}


@quant_router.post("/strategies/{sid}")
def quant_strategy_toggle(sid: str, body: ToggleIn) -> dict[str, Any]:
    if sid not in _STRAT:
        raise HTTPException(status_code=404, detail="unknown strategy")
    try:
        StrategyRegistry().set(sid, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return quant_strategies()


def _suite_calendar(sym: str) -> str:
    if sym in _CAL:
        return _CAL[sym]
    return "crypto" if sym.endswith(("USDT", "USD", "USDC")) else "XNYS"


@quant_router.get("/levels")
def quant_levels(symbol: str = Query(min_length=1), resolution: str = "15") -> dict[str, Any]:
    """Potential liquidity reference levels, interaction events, SFP / gold-box candidates and NO_TRADE reasons."""
    sym = symbol.upper()
    reg = StrategyRegistry()
    visible, report, bucket = _visible(symbol, resolution)
    try:
        daily_rows, _, _ = _visible(symbol, "D")
    except HTTPException:
        daily_rows = []
    now = int(datetime.now(timezone.utc).timestamp())
    toggles = StrategyToggles(reg.enabled("sfp"), reg.enabled("gold_snapback"), reg.enabled("gold_orb_breakout"))
    sc = SuiteConfig(toggles=toggles, calendar=_suite_calendar(sym), daily=tuple((int(r[0]), r[2], r[3], r[4]) for r in daily_rows))
    eng = PriceActionEngine(sym, bucket, EngineConfig(suite=sc))
    eng.run_batch(bars_from_rows(visible, bucket), now=now)
    su = eng.detectors[-1]
    on = reg.enabled_detectors()
    return {
        "instrument": sym, "timeframe": bucket, "calendar": sc.calendar, "gold_rules_applied": is_gold(sym),
        "label": "POTENTIAL LIQUIDITY REFERENCE LEVELS",
        "levels": [_asdict(lv) for lv in su.registry.levels[-300:]],
        "events": [_asdict(e) for e in su.level_events[-500:]],
        "zones": [z.to_dict() for z in su.zones],
        "candidates": [c.to_dict() for c in su.candidates if c.detector in on],
        "no_trades": su.no_trades[-300:], "transitions": [_asdict(t) for t in su.transitions[-300:]],
        "htf": su.htf(now), "strategies": reg.listing(),
        "bars": [list(r) for r in visible], "bars_used": len(visible), "feed_origin": report.get("feed_origin"),
        "data_gaps": {"order_flow": "missing", "economic_calendar": "missing"},
        "execution_permission": "none",
    }
