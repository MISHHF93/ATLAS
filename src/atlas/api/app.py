"""ATLAS HTTP API for research, forecasting, and deterministic control-plane actions."""

from typing import Literal
from pydantic import BaseModel

from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.models.adapters import NaiveForecastProvider
from atlas.models.demo import demo as build_research_demo
from atlas.models.registry import ProviderRegistry
from atlas.models.schemas import Capability
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atlas.market.fixtures import candle_page
from atlas.market.schemas import CandlePage

app = FastAPI(title="ATLAS", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

control_engine = ActionableControlPlaneEngine()


class KillSwitchPayload(BaseModel):
    engaged: bool
    reason: str = "operator_action"


class LifecycleActionPayload(BaseModel):
    action: Literal["approve_challenger", "revoke_challenger", "promote_challenger", "rollback_to_champion"]


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
    payload = await build_research_demo()
    payload["control_plane_state"] = control_engine.get_state().model_dump(mode="json")
    return payload


@app.get("/api/control/state", include_in_schema=False)
def get_control_state() -> dict[str, object]:
    return control_engine.get_state().model_dump(mode="json")


@app.post("/api/control/order", include_in_schema=False)
def submit_control_order(request: ActionableOrderRequest) -> dict[str, object]:
    decision = control_engine.submit_order(request)
    return {
        "decision": decision.model_dump(mode="json"),
        "state": control_engine.get_state().model_dump(mode="json"),
    }


@app.post("/api/control/kill-switch", include_in_schema=False)
def toggle_kill_switch(payload: KillSwitchPayload) -> dict[str, object]:
    state = control_engine.set_kill_switch(payload.engaged, reason=payload.reason)
    return state.model_dump(mode="json")


@app.post("/api/control/flatten", include_in_schema=False)
def flatten_positions() -> dict[str, object]:
    state = control_engine.flatten_all_positions(reason="operator_flatten_button")
    return state.model_dump(mode="json")


@app.post("/api/control/lifecycle", include_in_schema=False)
def lifecycle_action(payload: LifecycleActionPayload) -> dict[str, object]:
    state = control_engine.apply_lifecycle_action(payload.action)
    return state.model_dump(mode="json")


@app.post("/api/research/train", include_in_schema=False)
def trigger_self_training() -> dict[str, object]:
    state = control_engine.record_training_run()
    return state.model_dump(mode="json")
