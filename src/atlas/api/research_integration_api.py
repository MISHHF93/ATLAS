"""FastAPI Router for ATLAS Complete Research-to-Execution Intelligence Integration.

Exposes Strategy Discovery, Knowledge Base, Pine v5/v6 Analysis & Parity, Realistic Walk-Forward
Backtesting, Broker MCP & Reconciliation Intelligence, Dynamic Position Sizing, Research Memory,
Cross-Session Handoffs, Market Candidate Gate, and the End-to-End Workflow Runner.
"""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.market.sessions import evaluate_candidate_market_gate
from atlas.research.broker_intelligence import (
    build_broker_intelligence_snapshot,
    evaluate_broker_capability_guard,
)
from atlas.research.memory_handoff import (
    DEFAULT_HANDOFF_PATH,
    build_requirements_traceability_matrix,
    explain_strategy_recommendation,
    generate_and_verify_session_handoff,
    load_research_memory,
    record_research_memory,
    run_complete_research_to_execution_workflow,
)
from atlas.research.position_sizing import compute_dynamic_position_sizing
from atlas.research.strategy_engine import (
    EXTERNAL_RESEARCH_REFERENCES,
    STRATEGY_LIFECYCLE_STAGES,
    import_strategy_into_knowledge_base,
    load_strategy_knowledge_base,
    parse_and_validate_pine,
    run_realistic_strategy_backtest,
    transition_strategy_lifecycle,
    verify_pine_to_python_parity,
)
import json

EXECUTION_PERMISSION = "none"

router = APIRouter()


class StrategyImportPayload(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=64)
    strategy_name: str = Field(min_length=1, max_length=120)
    source_code: str = Field(min_length=10)
    source_reference: str = "manual_verified_import"
    source_license: str = "MIT"
    strategy_family: str = "imported_pine"
    origin_kind: str = "imported_source"
    supported_instruments: list[str] = ["GC", "SPY", "BTC-USD"]
    supported_timeframes: list[str] = ["15m", "1h"]
    research_notes: str = ""


class StrategyTransitionPayload(BaseModel):
    target_stage: str
    evidence_note: str = ""
    backtest_id: str | None = None


class PineAnalyzePayload(BaseModel):
    source_code: str
    strategy_id: str = "custom_pine"
    source_license: str = "MIT"
    source_reference: str = "manual_import"
    instrument_scope: list[str] = ["equities", "futures", "crypto"]
    timeframe: str = "15m"


class BacktestPayload(BaseModel):
    strategy_id: str = "sfp"
    symbol: str = "GC"
    timeframe: str = "15m"
    cost_multiplier: float = 1.0
    purge_bars: int = 4
    embargo_bars: int = 4


class SizingRequestPayload(BaseModel):
    candidate_id: str = "cand-001"
    account_id: str = "paper-main"
    symbol: str = "GC"
    side: str = "buy"
    track: str = "competition"
    entry_price: float = 2750.0
    stop_price: float | None = None
    atr_value: float | None = 12.5
    atr_multiplier: float = 1.5
    account_equity_usd: float | None = None
    risk_fraction: float = 0.005
    win_probability: float | None = 0.58
    payoff_ratio_b: float | None = 2.0
    calibration_ece: float = 0.04
    spread_bps: float = 2.5
    liquidity_score: float = 0.90
    current_drawdown_pct: float = 0.5
    correlated_exposure_usd: float = 0.0
    sector_exposure_usd: float = 0.0
    daily_loss_used_usd: float = 0.0
    event_risk_active: bool = False


class MemoryRecordPayload(BaseModel):
    hypothesis: str
    source_references: list[str] = ["atlas://research"]
    source_code_version: str = "1.0.0"
    strategy_configuration: dict[str, Any] = {}
    dataset_identifier: str = "atlas_feed:GC:15m"
    dataset_coverage: str = "3,500 bars"
    experiment_identifier: str = "exp-custom-001"
    model_version: str = "equity-15m"
    backtest_parameters: dict[str, Any] = {}
    backtest_results: dict[str, Any] = {}
    validation_results: dict[str, Any] = {}
    calibration_results: dict[str, Any] = {}
    known_limitations: list[str] = []
    decision: str = "EXPERIMENTAL"
    supporting_evidence: list[str] = []
    reproduction_commands: list[str] = []
    ai_summary: str = ""
    evidence_classification: str = "EXPERIMENT_RESULT"


class WorkflowRunPayload(BaseModel):
    strategy_id: str = "sfp"
    symbol: str = "GC"
    timeframe: str = "15m"
    track: str = "competition"
    risk_fraction: float = 0.005


@router.get("/traceability-matrix")
def get_traceability_matrix() -> dict[str, Any]:
    return build_requirements_traceability_matrix()


@router.get("/strategies")
def get_strategies(family: str | None = None, stage: str | None = None) -> dict[str, Any]:
    records = load_strategy_knowledge_base()
    if family:
        records = [r for r in records if r.get("strategy_family") == family]
    if stage:
        records = [r for r in records if r.get("lifecycle_stage") == stage]
    return {
        "count": len(records),
        "lifecycle_stages": list(STRATEGY_LIFECYCLE_STAGES),
        "external_references": EXTERNAL_RESEARCH_REFERENCES,
        "strategies": records,
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.post("/strategies/import")
def post_strategy_import(body: StrategyImportPayload) -> dict[str, Any]:
    return import_strategy_into_knowledge_base(
        strategy_id=body.strategy_id,
        strategy_name=body.strategy_name,
        source_code=body.source_code,
        source_reference=body.source_reference,
        source_license=body.source_license,
        strategy_family=body.strategy_family,
        origin_kind=body.origin_kind,
        supported_instruments=body.supported_instruments,
        supported_timeframes=body.supported_timeframes,
        research_notes=body.research_notes,
    )


@router.post("/strategies/{strategy_id}/transition")
def post_strategy_transition(strategy_id: str, body: StrategyTransitionPayload) -> dict[str, Any]:
    try:
        return transition_strategy_lifecycle(
            strategy_id,
            body.target_stage,
            evidence_note=body.evidence_note,
            backtest_id=body.backtest_id,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/strategies/{strategy_id}/explain")
def get_strategy_explanation(
    strategy_id: str,
    symbol: str = Query("GC"),
    timeframe: str = Query("15m"),
) -> dict[str, Any]:
    return explain_strategy_recommendation(strategy_id, symbol=symbol, timeframe=timeframe)


@router.post("/pine/analyze")
def post_pine_analyze(body: PineAnalyzePayload) -> dict[str, Any]:
    return parse_and_validate_pine(
        body.source_code,
        strategy_id=body.strategy_id,
        source_license=body.source_license,
        source_reference=body.source_reference,
        instrument_scope=body.instrument_scope,
        timeframe=body.timeframe,
    )


@router.get("/pine/parity/{strategy_id}")
def get_pine_parity(
    strategy_id: str,
    symbol: str = Query("GC"),
    timeframe: str = Query("15m"),
) -> dict[str, Any]:
    return verify_pine_to_python_parity(strategy_id, symbol=symbol, timeframe=timeframe)


@router.post("/backtest")
def post_realistic_backtest(body: BacktestPayload) -> dict[str, Any]:
    return run_realistic_strategy_backtest(
        body.strategy_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        cost_multiplier=body.cost_multiplier,
        purge_bars=body.purge_bars,
        embargo_bars=body.embargo_bars,
    )


@router.get("/broker-intelligence")
def get_broker_intelligence() -> dict[str, Any]:
    return build_broker_intelligence_snapshot()


@router.get("/broker-capability-guard")
def get_broker_capability_guard(
    capability: str = Query("BROKER_READ_ONLY"),
    tool_name: str = Query("get_account"),
    is_llm_caller: bool = Query(True),
    control_plane_approved: bool = Query(False),
) -> dict[str, Any]:
    return evaluate_broker_capability_guard(
        capability,
        tool_name=tool_name,
        is_llm_caller=is_llm_caller,
        control_plane_approved=control_plane_approved,
    )


@router.post("/position-sizing")
def post_position_sizing(body: SizingRequestPayload) -> dict[str, Any]:
    try:
        return compute_dynamic_position_sizing(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidate-market-gate")
def get_candidate_market_gate(
    symbol: str = Query("GC"),
    venue_reported_status: str | None = None,
    data_feed_health: str | None = None,
    data_age_seconds: float | None = None,
    broker_available: bool = True,
    instrument_permitted: bool = True,
    account_restricted: bool = False,
) -> dict[str, Any]:
    return evaluate_candidate_market_gate(
        symbol,
        venue_reported_status=venue_reported_status,
        data_feed_health=data_feed_health,
        data_age_seconds=data_age_seconds,
        broker_available=broker_available,
        instrument_permitted=instrument_permitted,
        account_restricted=account_restricted,
    )


@router.get("/memory")
def get_research_memory() -> dict[str, Any]:
    records = load_research_memory()
    return {
        "count": len(records),
        "records": records,
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.post("/memory")
def post_research_memory(body: MemoryRecordPayload) -> dict[str, Any]:
    return record_research_memory(**body.model_dump())


@router.get("/handoffs")
def get_session_handoffs() -> dict[str, Any]:
    if not DEFAULT_HANDOFF_PATH.exists():
        first = generate_and_verify_session_handoff()
        return {"count": 1, "latest": first, "handoffs": [first], "execution_permission": EXECUTION_PERMISSION}
    try:
        handoffs = json.loads(DEFAULT_HANDOFF_PATH.read_text(encoding="utf-8"))
    except Exception:
        handoffs = [generate_and_verify_session_handoff()]
    return {
        "count": len(handoffs),
        "latest": handoffs[0] if handoffs else None,
        "handoffs": handoffs,
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.post("/handoffs")
def post_session_handoff(current_objective: str = "ATLAS Session Handoff Checkpoint") -> dict[str, Any]:
    return generate_and_verify_session_handoff(current_objective=current_objective)


@router.post("/workflow-run")
def post_workflow_run(body: WorkflowRunPayload) -> dict[str, Any]:
    return run_complete_research_to_execution_workflow(
        strategy_id=body.strategy_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        track=body.track,
        risk_fraction=body.risk_fraction,
    )
