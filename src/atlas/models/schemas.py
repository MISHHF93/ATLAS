"""Typed, immutable research contracts; adapters own their wire formats."""
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Text = Annotated[str, Field(min_length=1)]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
NonnegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Capability(StrEnum):
    RESEARCH = "research"
    FORECAST = "forecast"
    PREDICT = "predict"
    TRAIN = "train"
    EMBED = "embed"
    RETRIEVE = "retrieve"
    REGISTRY = "registry"
    BATCH = "batch"
    STREAM = "stream"
    FINE_TUNE = "fine_tune"
    GPU_TRAIN = "gpu_train"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALL = "tool_call"
    DEPLOY = "deploy"
    DATA_SOURCE = "data_source"


class ProviderInfo(Record):
    provider_id: Text
    capabilities: frozenset[Capability]
    location: Literal["local", "cloud"]
    # These are adapter capabilities, not everything offered by the vendor.
    models: tuple[str, ...] = ()


class ModelRef(Record):
    provider_id: Text
    model_id: Text
    revision: Text

    @property
    def key(self) -> tuple[str, str, str]:
        return self.provider_id, self.model_id, self.revision


class Usage(Record):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: NonnegativeDecimal | None = None
    cost_kind: Literal["unknown", "estimated", "reported"] = "unknown"

    @model_validator(mode="after")
    def cost_consistent(self) -> Self:
        if (self.cost_usd is None) != (self.cost_kind == "unknown"):
            raise ValueError("Unknown cost must be null; known cost needs a provenance")
        return self


class AssetClass(StrEnum):
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_DERIVATIVE = "crypto_derivative"
    FOREX = "forex"
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    OPTION = "option"
    COMMODITY = "commodity"
    OTHER = "other"


class MarginRequirements(Record):
    policy_ref: Text
    currency: Text
    initial_rate: NonnegativeDecimal | None = None
    maintenance_rate: NonnegativeDecimal | None = None
    fixed_amount: NonnegativeDecimal | None = None
    as_of: AwareDatetime


class Instrument(Record):
    instrument_id: Text
    venue: Text
    symbol: Text
    asset_class: AssetClass
    base_currency: Text | None = None
    quote_currency: Text
    contract_size: PositiveDecimal
    tick_size: PositiveDecimal
    lot_size: PositiveDecimal
    margin_policy_ref: Text  # Versioned venue policy, not a universal leverage formula.
    margin_requirements: MarginRequirements | None = None
    calendar_ref: Text  # Includes holidays, timezone, sessions and version.
    settlement: Text
    market_data: frozenset[str]
    permitted_research: bool = False
    execution_permission: Literal["none"] = "none"
    underlying_id: Text | None = None
    expiry: AwareDatetime | None = None
    strike: Annotated[Decimal, Field(allow_inf_nan=False)] | None = None
    option_right: Literal["call", "put"] | None = None

    @model_validator(mode="after")
    def option_metadata(self) -> Self:
        if self.asset_class == AssetClass.OPTION and any(
            value is None for value in (self.underlying_id, self.expiry, self.strike, self.option_right)
        ):
            raise ValueError("Options require underlying, expiry, strike and right")
        if self.asset_class == AssetClass.FUTURE and self.expiry is None:
            raise ValueError("Futures require an expiry; continuous series are research data")
        return self


class Horizon(Record):
    horizon_id: Text
    sampling: Literal["time", "event", "volume", "session"]
    resolution: Text  # e.g. 5min, 100 trades, 1 session; adapter interprets explicitly.
    steps: int = Field(gt=0)
    clock: Literal["wall", "trading", "event"]
    family: Literal["short_term", "intraday", "swing", "long_term"]
    max_data_age_seconds: float = Field(gt=0, allow_inf_nan=False)
    max_forecast_age_seconds: float = Field(gt=0, allow_inf_nan=False)
    method: Literal["direct", "recursive", "multi_output", "hierarchical"] = "direct"


class Observation(Record):
    event_time: AwareDatetime
    available_at: AwareDatetime
    value: FiniteFloat

    @model_validator(mode="after")
    def availability(self) -> Self:
        if self.available_at < self.event_time:
            raise ValueError("Observation cannot be available before it occurs")
        return self


class FeatureValue(Observation):
    name: Text
    source: Text
    lineage_ref: Text
    license_ref: Text
    quality: Literal["verified", "unknown", "rejected"] = "unknown"


class ForecastRequest(Record):
    request_id: Text
    instrument_id: Text
    horizon_id: Text
    as_of: AwareDatetime
    target: Text  # price, return, volatility, funding, event count, etc.
    unit: Text
    observations: tuple[Observation, ...] = Field(min_length=1)
    features: tuple[FeatureValue, ...] = ()
    # Explicit target times permit sessions and irregular events without candle assumptions.
    target_times: tuple[AwareDatetime, ...] = Field(min_length=1)
    dataset_id: Text
    data_license_ref: Text
    quality: Literal["verified", "unknown", "rejected"] = "unknown"

    @model_validator(mode="after")
    def point_in_time(self) -> Self:
        times = [row.event_time for row in self.observations]
        if times != sorted(set(times)):
            raise ValueError("Observations must be unique and ordered")
        if any(row.available_at > self.as_of for row in (*self.observations, *self.features)):
            raise ValueError("Future information is not permitted")
        if tuple(sorted(set(self.target_times))) != self.target_times:
            raise ValueError("Target times must be unique and ordered")
        if self.target_times[0] <= self.as_of:
            raise ValueError("Targets must be after as_of")
        return self


class ForecastPoint(Record):
    timestamp: AwareDatetime
    value: FiniteFloat
    lower: FiniteFloat | None = None
    upper: FiniteFloat | None = None
    interval_coverage: Probability | None = None

    @model_validator(mode="after")
    def interval(self) -> Self:
        present = (self.lower is not None, self.upper is not None, self.interval_coverage is not None)
        if any(present) and not all(present):
            raise ValueError("Intervals need both bounds and coverage")
        if self.lower is not None and not self.lower <= self.value <= self.upper:
            raise ValueError("Forecast must lie within its interval")
        return self


class Forecast(Record):
    request_id: Text
    model: ModelRef
    instrument_id: Text
    horizon_id: Text
    target: Text
    unit: Text
    data_as_of: AwareDatetime
    generated_at: AwareDatetime
    points: tuple[ForecastPoint, ...] = Field(min_length=1)
    probability_up: Probability | None = None
    calibration_ref: Text | None = None
    usage: Usage = Field(default_factory=Usage)
    execution_permission: Literal["none"] = "none"


class PredictionRequest(Record):
    request_id: Text
    model: ModelRef
    feature_schema_ref: Text
    rows: tuple[tuple[FiniteFloat, ...], ...] = Field(min_length=1)


class PredictionResult(Record):
    request_id: Text
    model: ModelRef
    values: tuple[tuple[FiniteFloat, ...], ...]
    usage: Usage = Field(default_factory=Usage)


class EmbeddingRequest(Record):
    texts: tuple[Text, ...] = Field(min_length=1)
    model: ModelRef


class EmbeddingResult(Record):
    model: ModelRef
    vectors: tuple[tuple[FiniteFloat, ...], ...]
    usage: Usage = Field(default_factory=Usage)


class RetrievalRequest(Record):
    query: Text
    collection_id: Text
    as_of: AwareDatetime
    limit: int = Field(default=10, gt=0, le=100)


class RetrievalHit(Record):
    document_id: Text
    source: Text
    available_at: AwareDatetime
    text: Text
    score: FiniteFloat


class DatasetManifest(Record):
    dataset_id: Text
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    source_refs: tuple[Text, ...] = Field(min_length=1)
    license_refs: tuple[Text, ...] = Field(min_length=1)
    feature_lineage: tuple[Text, ...]
    transform_revision: Text
    train_end: AwareDatetime
    validation_start: AwareDatetime
    validation_end: AwareDatetime
    test_start: AwareDatetime
    test_end: AwareDatetime

    @model_validator(mode="after")
    def disjoint_splits(self) -> Self:
        if not self.train_end < self.validation_start <= self.validation_end < self.test_start <= self.test_end:
            raise ValueError("Train, calibration/validation and test periods must be disjoint")
        return self


    def verify_content(self, content: bytes) -> None:
        import hashlib
        if hashlib.sha256(content).hexdigest() != self.content_sha256:
            raise ValueError("Dataset content does not match frozen manifest")


class TrainingRequest(Record):
    experiment_id: Text
    idempotency_key: Text
    dataset: DatasetManifest
    method: Literal["supervised", "transfer", "fine_tune", "ensemble", "hyperparameter_search"]
    base_model: ModelRef | None = None
    code_revision: Text
    environment_digest: Text
    seed: int
    hyperparameters_json: Text
    max_cost_usd: PositiveDecimal
    max_duration_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_training(self) -> Self:
        import json
        if not isinstance(json.loads(self.hyperparameters_json), dict):
            raise ValueError("Hyperparameters must be a JSON object")
        if self.method in {"transfer", "fine_tune"} and self.base_model is None:
            raise ValueError("Transfer/fine-tuning requires a pinned base model")
        return self


class TrainingJob(Record):
    job_id: Text
    experiment_id: Text
    state: Literal["queued", "running", "succeeded", "failed", "cancelled", "unknown"]
    artifact: ModelRef | None = None
    usage: Usage = Field(default_factory=Usage)


class ModelRecord(Record):
    model: ModelRef
    artifact_uri: Text
    artifact_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    dataset_id: Text
    experiment_id: Text
    license_ref: Text
    commercial_use_verified: bool = False
    execution_permission: Literal["none"] = "none"


class Eligibility(Record):
    model: ModelRef
    instrument_id: Text
    horizon_id: Text
    target: Text
    unit: Text
    strategy_family: Text
    evaluation_ref: Text
    approver: Text
    approved_at: AwareDatetime
    expires_at: AwareDatetime
    max_cost_bps: float = Field(ge=0, allow_inf_nan=False)
    min_liquidity_score: Probability
    research_approved: bool = False

    @model_validator(mode="after")
    def approval_dates(self) -> Self:
        if self.expires_at <= self.approved_at:
            raise ValueError("Approval expiry must follow approval")
        return self


class DataProvenance(Record):
    provider_id: Text
    source_ref: Text
    upstream_id: Text
    instrument_id: Text
    venue: Text
    timezone: Text
    adjustment_basis: Literal["raw", "split_adjusted", "total_return", "vintage_as_filed", "unknown"] = "unknown"
    calendar_ref: Text
    license_ref: Text
    allow_retention: bool = False
    allow_training: bool = False
    allow_competition: bool = False
    retrieved_at: AwareDatetime
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class MarketDataRequest(Record):
    request_id: Text
    provider_id: Text
    tool_name: Text
    instrument_id: Text
    as_of: AwareDatetime
    start_time: AwareDatetime
    end_time: AwareDatetime
    max_rows: int = Field(default=500, gt=0, le=5000)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if not self.start_time <= self.end_time <= self.as_of:
            raise ValueError("MarketDataRequest window must satisfy start_time <= end_time <= as_of")
        return self


class MarketDataBatch(Record):
    request_id: Text
    provenance: DataProvenance
    observations: tuple[Observation, ...] = ()
    features: tuple[FeatureValue, ...] = ()
    quality: Literal["verified", "unknown", "rejected"] = "unknown"
    usage: Usage = Field(default_factory=Usage)
    execution_permission: Literal["none"] = "none"

    @model_validator(mode="after")
    def point_in_time_batch(self) -> Self:
        times = [row.event_time for row in self.observations]
        if times != sorted(set(times)):
            raise ValueError("Batch observations must be unique and ordered")
        return self
