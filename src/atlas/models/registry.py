"""Process-local discovery and immutable metadata registries."""
from typing import Generic, TypeVar

from atlas.models.providers import (
    BatchForecastProvider, DeploymentProvider, Discoverable, EmbeddingProvider,
    ForecastProvider, ModelRegistryProvider, PredictionProvider, ReadOnlyDataProvider,
    ResearchProvider, RetrievalProvider, StreamingResearchProvider, TrainingProvider,
)
from atlas.models.schemas import Capability, Horizon, Instrument, ModelRecord, ModelRef, ProviderInfo

T = TypeVar("T", Instrument, Horizon)


class MetadataRegistry(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, record: T) -> None:
        key = record.instrument_id if isinstance(record, Instrument) else record.horizon_id
        if key in self._items:
            raise ValueError(f"Duplicate metadata ID: {key}; use a new versioned ID")
        self._items[key] = record

    def get(self, key: str) -> T:
        return self._items[key]

    def list(self) -> tuple[T, ...]:
        return tuple(self._items.values())


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Discoverable] = {}
        self._info: dict[str, ProviderInfo] = {}

    def register(self, provider: Discoverable) -> None:
        info = provider.describe()
        contracts = {
            Capability.RESEARCH: ResearchProvider, Capability.FORECAST: ForecastProvider,
            Capability.PREDICT: PredictionProvider, Capability.TRAIN: TrainingProvider,
            Capability.EMBED: EmbeddingProvider, Capability.RETRIEVE: RetrievalProvider,
            Capability.REGISTRY: ModelRegistryProvider, Capability.BATCH: BatchForecastProvider,
            Capability.STREAM: StreamingResearchProvider, Capability.DEPLOY: DeploymentProvider,
            Capability.FINE_TUNE: TrainingProvider, Capability.GPU_TRAIN: TrainingProvider,
            Capability.DATA_SOURCE: ReadOnlyDataProvider,
        }
        dependencies = {
            Capability.FINE_TUNE: Capability.TRAIN, Capability.GPU_TRAIN: Capability.TRAIN,
            Capability.BATCH: Capability.FORECAST, Capability.STREAM: Capability.RESEARCH,
        }
        for optional, required in dependencies.items():
            if optional in info.capabilities and required not in info.capabilities:
                raise ValueError(f"{optional} requires {required}")
        for capability in info.capabilities:
            contract = contracts.get(capability)
            if contract and not isinstance(provider, contract):
                raise TypeError(f"Adapter advertises {capability} without its protocol")
        if info.provider_id in self._providers:
            raise ValueError("Provider already registered")
        self._providers[info.provider_id] = provider
        self._info[info.provider_id] = info

    def discover(self, capability: Capability) -> tuple[ProviderInfo, ...]:
        return tuple(info for info in self._info.values() if capability in info.capabilities)

    def require(self, provider_id: str, capability: Capability) -> Discoverable:
        if capability not in self._info[provider_id].capabilities:
            raise ValueError(f"Provider does not support {capability}")
        return self._providers[provider_id]

    def preferred_research(self) -> Discoverable:
        available = self.discover(Capability.RESEARCH)
        if not available:
            raise LookupError("No research provider registered")
        selected = next((item for item in available if item.provider_id == "gemini"), available[0])
        return self._providers[selected.provider_id]


class InMemoryModelRegistry:
    """Research registry; alias changes are not production deployments."""
    def __init__(self) -> None:
        self._models: dict[tuple[str, str, str], ModelRecord] = {}
        self._aliases: dict[str, ModelRef] = {}
        self._history: dict[str, list[ModelRef]] = {}

    def describe(self) -> ProviderInfo:
        return ProviderInfo(provider_id="memory-registry", capabilities={Capability.REGISTRY}, location="local")

    def register(self, record: ModelRecord) -> None:
        if record.model.key in self._models:
            raise ValueError("Model revision is immutable")
        self._models[record.model.key] = record

    def get(self, model: ModelRef) -> ModelRecord:
        return self._models[model.key]

    def list_models(self) -> tuple[ModelRecord, ...]:
        return tuple(self._models.values())

    def set_research_alias(self, alias: str, model: ModelRef) -> None:
        self.get(model)
        if alias in self._aliases:
            self._history.setdefault(alias, []).append(self._aliases[alias])
        self._aliases[alias] = model

    def resolve(self, alias: str) -> ModelRef:
        return self._aliases[alias]

    def rollback_research_alias(self, alias: str) -> ModelRef:
        previous = self._history.get(alias, [])
        if not previous:
            raise ValueError("No previous research revision")
        self._aliases[alias] = previous.pop()
        return self._aliases[alias]
