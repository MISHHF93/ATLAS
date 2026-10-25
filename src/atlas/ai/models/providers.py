"""Small capability-specific protocols; no universal generate/train method."""
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from atlas.ai.schemas import MarketResearchResult
from atlas.schemas import (
    EmbeddingRequest, EmbeddingResult, Forecast, ForecastRequest, MarketDataBatch,
    MarketDataRequest, ModelRecord, ModelRef, PredictionRequest, PredictionResult,
    ProviderInfo, RetrievalHit, RetrievalRequest, TrainingJob, TrainingRequest,
)


@runtime_checkable
class Discoverable(Protocol):
    def describe(self) -> ProviderInfo: ...


@runtime_checkable
class ResearchProvider(Discoverable, Protocol):
    async def research(self, context: str) -> MarketResearchResult: ...


@runtime_checkable
class ForecastProvider(Discoverable, Protocol):
    async def forecast(self, model: ModelRef, request: ForecastRequest) -> Forecast: ...


@runtime_checkable
class PredictionProvider(Discoverable, Protocol):
    """Shared contract for local ML and hosted prediction, not for LLM narration."""
    async def predict(self, request: PredictionRequest) -> PredictionResult: ...


@runtime_checkable
class TrainingProvider(Discoverable, Protocol):
    async def submit_training(self, request: TrainingRequest) -> TrainingJob: ...
    async def training_status(self, job_id: str) -> TrainingJob: ...
    async def cancel_training(self, job_id: str) -> TrainingJob: ...


@runtime_checkable
class EmbeddingProvider(Discoverable, Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...


@runtime_checkable
class RetrievalProvider(Discoverable, Protocol):
    async def retrieve(self, request: RetrievalRequest) -> tuple[RetrievalHit, ...]: ...


@runtime_checkable
class ModelRegistryProvider(Discoverable, Protocol):
    def register(self, record: ModelRecord) -> None: ...
    def get(self, model: ModelRef) -> ModelRecord: ...
    def list_models(self) -> tuple[ModelRecord, ...]: ...


@runtime_checkable
class BatchForecastProvider(ForecastProvider, Protocol):
    async def forecast_batch(self, model: ModelRef, requests: tuple[ForecastRequest, ...]) -> tuple[Forecast, ...]: ...


@runtime_checkable
class StreamingResearchProvider(ResearchProvider, Protocol):
    def stream_research(self, context: str) -> AsyncIterator[str]: ...


@runtime_checkable
class DeploymentProvider(Discoverable, Protocol):
    async def deploy(self, model: ModelRef, approval_ref: str) -> str: ...
    async def rollback(self, deployment_id: str, previous_model: ModelRef, approval_ref: str) -> str: ...


@runtime_checkable
class ReadOnlyDataProvider(Discoverable, Protocol):
    """Read-only market/research data surface. Cannot place orders or mutate remote state."""
    async def fetch_market_data(self, request: MarketDataRequest) -> MarketDataBatch: ...

