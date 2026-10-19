"""Read-only HTTP API. There is no order route."""

from atlas.models.adapters import NaiveForecastProvider
from atlas.models.demo import demo as build_research_demo
from atlas.models.registry import ProviderRegistry
from atlas.models.schemas import Capability
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas.market.fixtures import candle_page
from atlas.market.schemas import CandlePage

app = FastAPI(title="ATLAS", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["Accept"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "trading": "disabled"}


@app.get("/api/market/candles", response_model=CandlePage)
def candles(symbol: str = "BTC-USD", interval: str = "1h") -> CandlePage:
    return candle_page(symbol, interval)


@app.get("/api/research/capabilities")
def research_capabilities() -> dict[str, object]:
    providers = ProviderRegistry()
    providers.register(NaiveForecastProvider())
    forecast_providers = providers.discover(Capability.FORECAST)
    return {
        "providers": [
            {
                "provider_id": provider.provider_id,
                "location": provider.location,
                "capabilities": sorted(capability.value for capability in provider.capabilities),
                "models": list(provider.models),
            }
            for provider in forecast_providers
        ],
        "components": {
            "market_data": "fixture_only",
            "forecasting": "local_baselines",
            "evaluation": "offline_library_only",
            "training": "contracts_only",
            "experiment_store": "local_sqlite_library_only",
        },
        "execution": {"enabled": False, "permission": "none", "order_routes": False},
    }


@app.get("/api/research/demo")
async def research_demo() -> dict[str, object]:
    return await build_research_demo()
