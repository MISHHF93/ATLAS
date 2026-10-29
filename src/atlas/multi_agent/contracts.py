"""Typed contracts for ATLAS multi-agent research.

Every model inherits :class:`AdvisoryModel`, which forces
``execution_permission`` to ``"none"``.  Research objects can describe a
candidate trade, but they cannot authorize, size, or place one.

The contracts follow the TradingAgents role decomposition while keeping ATLAS'
existing deterministic evidence and control-plane boundaries.  Confidence
labels are *not* calibrated probabilities; only registered ATLAS models may
emit calibrated probabilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Stance = Literal["bullish", "bearish", "neutral", "mixed", "insufficient_evidence"]
ConfidenceLabel = Literal["low", "medium", "high", "unavailable"]
ReportStatus = Literal["ok", "not_applicable", "unavailable", "error"]
RiskVerdict = Literal["supports_candidate", "concerns_raised", "objects"]
ResearchOutcome = Literal[
    "BULLISH_CASE_STRONGER",
    "BEARISH_CASE_STRONGER",
    "MIXED_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "ABSTAIN",
]
PortfolioOutcome = Literal[
    "RECOMMEND_FOR_RISK_REVIEW",
    "REJECT_RESEARCH_PROPOSAL",
    "REQUEST_MORE_EVIDENCE",
    "ABSTAIN",
]
DeterministicOutcome = Literal[
    "PAPER_REVIEW_AUTHORIZED",
    "REJECTED",
    "NOT_APPLICABLE",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AdvisoryModel(BaseModel):
    """Base model that cannot carry an execution permission."""

    model_config = ConfigDict(extra="forbid")

    execution_permission: Literal["none"] = "none"

    @model_validator(mode="before")
    @classmethod
    def _force_advisory(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data["execution_permission"] = "none"
        return data


class EvidenceReference(AdvisoryModel):
    """A point-in-time reference to something an analyst observed.

    ``available_at`` is the moment the source became public.  A research run
    must not use evidence whose ``available_at`` is after the run's ``as_of``.
    """

    source_id: str = Field(min_length=1, max_length=300)
    source_type: str = Field(min_length=1, max_length=80)
    observed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    source_hash: str | None = Field(default=None, max_length=128)
    uri: str | None = Field(default=None, max_length=2000)
    untrusted: bool = False

    @field_validator("observed_at", "available_at", "retrieved_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class AnalystSpec(AdvisoryModel):
    name: str
    analyst_type: str
    description: str
    required: bool = False
    asset_classes: list[str] = Field(default_factory=list)
    version: str = "1.0.0"


class AnalystReport(AdvisoryModel):
    run_id: str
    analyst_type: str
    instrument_id: str
    as_of: datetime

    stance: Stance = "insufficient_evidence"
    confidence_label: ConfidenceLabel = "unavailable"
    status: ReportStatus = "ok"

    thesis: str = Field(min_length=1, max_length=4000)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceReference] = Field(default_factory=list)

    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)

    horizon: str = "unspecified"
    metrics: dict[str, Any] = Field(default_factory=dict)
    agent_version: str = "1.0.0"
    prompt_template_version: str = "none"

    @field_validator("as_of")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class ReconciliationConflict(AdvisoryModel):
    topic: str
    detail: str
    analyst_types: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ReconciliationReport(AdvisoryModel):
    agreements: list[str] = Field(default_factory=list)
    contradictions: list[ReconciliationConflict] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_timestamps: list[str] = Field(default_factory=list)
    data_quality_issues: list[str] = Field(default_factory=list)
    horizon_differences: list[str] = Field(default_factory=list)
    assumption_differences: list[str] = Field(default_factory=list)
    strategy_interpretation_conflicts: list[str] = Field(default_factory=list)
    prompt_injection_flags: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False
    notes: list[str] = Field(default_factory=list)


class DebateRound(AdvisoryModel):
    round: int
    bull_argument: str
    bear_argument: str
    bull_evidence_ids: list[str] = Field(default_factory=list)
    bear_evidence_ids: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    round_edge: float = 0.0


class DebateResult(AdvisoryModel):
    rounds_completed: int = 0
    rounds_max: int = 0
    bull_case_summary: str = ""
    bear_case_summary: str = ""
    bull_evidence_ids: list[str] = Field(default_factory=list)
    bear_evidence_ids: list[str] = Field(default_factory=list)
    bull_score: float = 0.0
    bear_score: float = 0.0
    net_score: float = 0.0
    challenges: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stopped_reason: str = "not_started"


class ResearchDecision(AdvisoryModel):
    outcome: ResearchOutcome
    thesis: str
    strongest_bull: str = ""
    strongest_bear: str = ""
    unresolved: list[str] = Field(default_factory=list)
    confidence_label: ConfidenceLabel = "unavailable"
    evidence_ids: list[str] = Field(default_factory=list)
    abstention_reason: str | None = None


class TradeProposal(AdvisoryModel):
    run_id: str
    instrument_id: str

    action: Literal["BUY_CANDIDATE", "SELL_CANDIDATE", "HOLD", "ABSTAIN"]

    strategy_id: str | None = None
    entry_condition: str | None = None
    stop_reference: str | None = None
    target_reference: str | None = None

    supporting_evidence_ids: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)

    side: Literal["buy", "sell"] | None = None
    notional_usd: float | None = Field(default=None, ge=0)
    stop_distance_bps: float | None = Field(default=None, ge=0)
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    reward_risk: float | None = None
    max_holding_horizon: str | None = None
    proposed_sizing_method: str = "deterministic control plane only"


class RiskReview(AdvisoryModel):
    perspective: Literal["aggressive", "conservative", "neutral"]
    verdict: RiskVerdict
    concerns: list[str] = Field(default_factory=list)
    favorable_factors: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = "low"


class PortfolioPosition(AdvisoryModel):
    instrument_id: str
    quantity: float
    average_price: float
    notional_usd: float | None = None


class PortfolioContext(AdvisoryModel):
    cash: float = Field(ge=0)
    currency: str = "USD"
    positions: list[PortfolioPosition] = Field(default_factory=list)
    max_position_pct: float = Field(default=0.25, gt=0, le=1)
    max_portfolio_risk_pct: float = Field(default=0.02, gt=0, le=1)
    daily_loss_used_usd: float = Field(default=0.0, ge=0)
    current_drawdown_pct: float = Field(default=0.0, ge=0, le=1)


class PortfolioReview(AdvisoryModel):
    outcome: PortfolioOutcome
    reasons: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    portfolio_context_available: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class DeterministicDecision(AdvisoryModel):
    outcome: DeterministicOutcome
    authorized: bool = False
    violations: list[str] = Field(default_factory=list)
    authority: str = "atlas.control.ActionableControlPlaneEngine.preview_order"
    submitted: bool = False
    notes: list[str] = Field(default_factory=list)


class NewsItem(AdvisoryModel):
    source: str = Field(min_length=1, max_length=120)
    published_at: datetime
    text: str = Field(min_length=1, max_length=8000)
    url: str | None = Field(default=None, max_length=2000)
    category: Literal["news", "social", "filing", "other"] = "news"

    @field_validator("published_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class MacroEvent(AdvisoryModel):
    name: str = Field(min_length=1, max_length=200)
    scheduled_at: datetime
    actual: float | None = None
    consensus: float | None = None
    previous: float | None = None
    source: str = "owner_supplied"
    unit: str | None = None

    @field_validator("scheduled_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class EvidenceSnapshot(AdvisoryModel):
    snapshot_id: str
    data_snapshot_id: str
    instrument_id: str
    timeframe: str
    asset_class: str
    as_of: datetime
    retrieved_at: datetime

    bars_count: int = 0
    bars_hash: str | None = None
    last_bar_at: datetime | None = None
    last_close: float | None = None
    freshness: dict[str, Any] = Field(default_factory=dict)
    point_in_time: bool = True

    technicals: dict[str, Any] = Field(default_factory=dict)
    conviction: dict[str, Any] = Field(default_factory=dict)
    trade_levels: dict[str, Any] = Field(default_factory=dict)
    fundamentals_status: str = "unavailable"
    fundamentals: dict[str, Any] = Field(default_factory=dict)
    fundamentals_metrics: dict[str, Any] = Field(default_factory=dict)
    strategy_candidates: list[dict[str, Any]] = Field(default_factory=list)
    ml_predictions: list[dict[str, Any]] = Field(default_factory=list)
    news_items: list[NewsItem] = Field(default_factory=list)
    macro_events: list[MacroEvent] = Field(default_factory=list)
    liquidity: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    sources: list[EvidenceReference] = Field(default_factory=list)
    prompt_injection_flags: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)

    @field_validator("as_of", "retrieved_at", "last_bar_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class NodeEvent(AdvisoryModel):
    node: str
    status: Literal["started", "succeeded", "failed", "skipped", "cancelled"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    state_hash: str | None = None
    error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class ResearchRunState(AdvisoryModel):
    run_id: str
    instrument_id: str
    timeframe: str = "15m"
    as_of: datetime
    created_at: datetime
    updated_at: datetime
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "resumed",
    ] = "pending"
    current_node: str | None = None

    config: dict[str, Any] = Field(default_factory=dict)
    portfolio: PortfolioContext | None = None

    snapshot: EvidenceSnapshot | None = None
    analyst_reports: list[AnalystReport] = Field(default_factory=list)
    reconciliation: ReconciliationReport | None = None
    debate: DebateResult | None = None
    research_decision: ResearchDecision | None = None
    trade_proposal: TradeProposal | None = None
    risk_reviews: list[RiskReview] = Field(default_factory=list)
    portfolio_review: PortfolioReview | None = None
    deterministic_decision: DeterministicDecision | None = None

    node_history: list[NodeEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    agent_versions: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    prompt_template_versions: dict[str, str] = Field(default_factory=dict)
    data_snapshot_id: str | None = None
    original_decision_hash: str | None = None

    @field_validator("as_of", "created_at", "updated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class RunRequest(BaseModel):
    """HTTP / service input.  It never contains credentials."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(default="BTCUSDT", min_length=1, max_length=80)
    timeframe: Literal["1m", "5m", "15m", "1h", "1d"] = "15m"
    as_of: datetime | None = None
    strategy_id: str | None = Field(default=None, max_length=120)
    debate_rounds: int | None = Field(default=None, ge=0, le=5)
    track: Literal["competition", "open_market"] = "competition"
    notional_usd: float = Field(default=1000.0, gt=0)
    portfolio: PortfolioContext | None = None
    news: list[NewsItem] = Field(default_factory=list)
    macro_events: list[MacroEvent] = Field(default_factory=list)
    enable_llm: bool = False
    run_id: str | None = Field(default=None, max_length=120)
    force: bool = False


class RunSummary(AdvisoryModel):
    run_id: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    status: str
    current_node: str | None = None
    created_at: datetime
    updated_at: datetime
    recommendation: str | None = None
    deterministic_outcome: str | None = None
    analyst_count: int = 0
    data_snapshot_id: str | None = None

    @field_validator("as_of", "created_at", "updated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class ReflectionRecord(AdvisoryModel):
    reflection_id: str
    run_id: str
    instrument_id: str
    as_of: datetime
    recommendation: ResearchOutcome
    proposal_action: str | None = None
    outcome_price: float
    outcome_as_of: datetime
    realized_return: float | None = None
    benchmark_return: float | None = None
    predicted_direction: Literal["up", "down", "none"]
    directional_correct: bool | None = None
    abstention_quality: Literal["good_abstention", "missed_opportunity", "not_applicable"] = "not_applicable"
    unsupported_assumptions: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    original_decision_hash: str | None = None
    created_at: datetime

    @field_validator("as_of", "outcome_as_of", "created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class BaselineMetric(AdvisoryModel):
    name: str
    status: Literal["available", "unavailable"]
    observations: int = 0
    directional_accuracy: float | None = None
    abstention_rate: float | None = None
    note: str = ""


class EvolutionReport(AdvisoryModel):
    generated_at: datetime
    completed_runs: int
    reflected_runs: int
    research_directional_accuracy: float | None = None
    research_abstention_rate: float | None = None
    baselines: list[BaselineMetric] = Field(default_factory=list)
    cost_notes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)


class AuditEvent(AdvisoryModel):
    seq: int
    run_id: str
    event: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str

    @field_validator("timestamp")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _utc(value)
