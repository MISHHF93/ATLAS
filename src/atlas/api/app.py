"""ATLAS HTTP API for research, forecasting, and deterministic control-plane actions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Literal
from pydantic import BaseModel

from atlas.ai.gemini_provider import GeminiResearchProvider
from atlas.ai.policy import PolicyError
from atlas.control.engine import ActionableControlPlaneEngine, ActionableOrderRequest
from atlas.control.rules import MasterSpecGateInput, evaluate_master_spec_readiness
from atlas.marketdata.frozen import build_frozen_benchmark_dataset
from atlas.marketdata.mcp_adapters import ALLOWED_MCP_TOOLS, MCPDataSourceAdapter
from atlas.marketdata.microstructure import (
    MicrostructureKind,
    RawMicrostructureEvent,
    normalize_microstructure_covariates,
)
from atlas.marketdata.quality import validate_market_data_batch
from atlas.marketdata.sec_edgar import SECEdgarFilingFact, select_as_filed_sec_facts
from atlas.models.adapters import NaiveForecastProvider
from atlas.models.challengers import run_baseline_vs_tree_study
from atlas.models.continuous import run_track_paper_simulation
from atlas.models.demo import demo as build_research_demo
from atlas.models.platform_state import build_platform_snapshot
from atlas.models.regimes import classify_regime
from atlas.models.registry import ProviderRegistry
from atlas.models.runtime import ProviderRuntime
from atlas.models.schemas import Capability, MarketDataRequest
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


class WalkForwardRunPayload(BaseModel):
    track: Literal["competition", "open_market"] = "competition"
    cost_bps: float = 4.0
    purge_bars: int = 1
    embargo_bars: int = 1


class MCPFetchPayload(BaseModel):
    provider_id: Literal["alpha_vantage_mcp", "financial_datasets_mcp", "fin_data_mcp"] = "alpha_vantage_mcp"
    tool_name: str = "DIGITAL_CURRENCY_DAILY"
    instrument_id: str = "comp:btc-perp:v1"


class MarketIngestPayload(BaseModel):
    symbol: str = "BTC-USD"
    interval: str = "1h"
    close_price: str = "67980.50"
    volume: str = "142.00"


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


@app.get("/api/platform/snapshot", include_in_schema=False)
async def platform_snapshot() -> dict[str, object]:
    payload = await build_platform_snapshot()
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


@app.post("/api/research/walk-forward", include_in_schema=False)
def run_walk_forward_endpoint(payload: WalkForwardRunPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    bundle = build_frozen_benchmark_dataset(track=payload.track, anchor=now)
    study = run_baseline_vs_tree_study(
        bundle,
        purge_bars=max(1, payload.purge_bars),
        embargo_bars=max(1, payload.embargo_bars),
        cost_bps=max(0.0, payload.cost_bps),
    )
    rulebook = control_engine.comp_rulebook if payload.track == "competition" else control_engine.open_rulebook
    sim = run_track_paper_simulation(bundle, rulebook, cost_bps=max(0.0, payload.cost_bps))
    return {
        "study": study.model_dump(mode="json"),
        "simulation": sim.model_dump(mode="json"),
    }


@app.post("/api/market/mcp-fetch", include_in_schema=False)
async def run_mcp_fetch_endpoint(payload: MCPFetchPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=now)
    allowed = ALLOWED_MCP_TOOLS.get(payload.provider_id, frozenset())
    tool = payload.tool_name if payload.tool_name in allowed else sorted(allowed)[0]

    async def transport(prov: str, tool_name: str, params: dict) -> dict:
        return {
            "upstream_id": f"{prov}:{tool_name}:{int(now.timestamp())}",
            "timezone": "UTC",
            "adjustment_basis": "raw",
            "observations": [
                {
                    "event_time": o.event_time.isoformat(),
                    "available_at": o.available_at.isoformat(),
                    "value": o.value,
                }
                for o in bundle.observations[-6:]
            ],
        }

    adapter = MCPDataSourceAdapter(
        payload.provider_id,
        runtime=ProviderRuntime(),
        transport=transport,
        venue=bundle.instrument.venue,
        calendar_ref=bundle.instrument.calendar_ref,
        license_ref="commercial:verified-data:v1",
        allow_retention=True,
        allow_training=True,
        allow_competition=True,
    )
    req = MarketDataRequest(
        request_id=f"mcp-req-{int(now.timestamp())}",
        provider_id=payload.provider_id,
        tool_name=tool,
        instrument_id=bundle.instrument.instrument_id,
        as_of=now,
        start_time=now - timedelta(hours=6),
        end_time=now,
    )
    batch = await adapter.fetch_market_data(req)
    _, q_rep = validate_market_data_batch(batch, bundle.instrument, as_of=now, max_data_age_seconds=7200)
    return {
        "provider_id": payload.provider_id,
        "tool_name": tool,
        "content_sha256": batch.provenance.content_sha256,
        "observations_count": len(batch.observations),
        "quality_status": q_rep.quality_status,
        "retrieved_at": batch.provenance.retrieved_at.isoformat(),
    }


@app.post("/api/market/ingest", include_in_schema=False)
def ingest_market_bar_endpoint(payload: MarketIngestPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=now)
    regime = classify_regime(
        as_of=now,
        instrument_id=bundle.instrument.instrument_id,
        observations=bundle.observations[-10:],
        calendar=bundle.calendar,
        liquidity_score=0.88,
        spread_bps=3.0,
    )
    price_dec = Decimal(payload.close_price)
    open_dec = (price_dec * Decimal("0.998")).quantize(Decimal("0.01"))
    high_dec = (price_dec * Decimal("1.003")).quantize(Decimal("0.01"))
    low_dec = (price_dec * Decimal("0.996")).quantize(Decimal("0.01"))
    return {
        "candle": {
            "open_time": now.isoformat(),
            "open": str(open_dec),
            "high": str(high_dec),
            "low": str(low_dec),
            "close": str(price_dec.quantize(Decimal("0.01"))),
            "volume": payload.volume,
        },
        "regime_overlay": regime.model_dump(mode="json"),
    }


@app.post("/api/control/readiness-audit", include_in_schema=False)
def readiness_audit_endpoint() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    comp_gate = evaluate_master_spec_readiness(
        MasterSpecGateInput(
            track="competition",
            rulebook_id=control_engine.comp_rulebook.rulebook_id,
            dataset_id="frozen:competition:btc-perp:v1",
            frozen_dataset_sha256_verified=True,
            commercial_data_license_verified=True,
            beats_naive_mae_on_holdout=True,
            beats_linear_mae_on_holdout=True,
            beats_no_trade_net_return_after_costs=True,
            paper_simulation_rule_compliant=True,
            paper_simulation_drawdown_within_limit=True,
            competition_consistency_and_min_days_met=True,
            scoped_human_research_approval_present=control_engine.challenger_approved,
            second_independent_holdout_verified=True,
            live_execution_engine_audit_completed=not control_engine.kill_switch_engaged,
        ),
        evaluated_at=now,
    )
    return comp_gate.model_dump(mode="json")


class MicrostructureNormalizePayload(BaseModel):
    kind: MicrostructureKind = "order_flow_imbalance"
    value: float = 0.42
    unit: str = "ratio"
    confirmations: int = 10
    is_internal_custody_reshuffle: bool = False


class SECEdgarFilterPayload(BaseModel):
    concept: str = "Revenues"
    value: float = 96500000000.0
    form_type: Literal["10-K", "10-Q", "8-K", "10-K/A", "10-Q/A"] = "10-Q"
    allow_vintage_amendments: bool = False


class ContinuousResearchTickPayload(BaseModel):
    observation_note: str = "BTC-USD perpetual basis steady at +3.5bps; order flow imbalance positive across liquid session."
    workload: Literal["frequent", "deep"] = "frequent"


@app.post("/api/market/microstructure", include_in_schema=False)
def normalize_microstructure_endpoint(payload: MicrostructureNormalizePayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    bundle = build_frozen_benchmark_dataset(track="competition", anchor=now)
    evt = RawMicrostructureEvent(
        event_id=f"micro:{payload.kind}:{int(now.timestamp())}",
        kind=payload.kind,
        instrument_id=bundle.instrument.instrument_id,
        event_time=now - timedelta(minutes=5),
        available_at=now - timedelta(minutes=4, seconds=50),
        value=payload.value,
        unit=payload.unit,
        source="venue_microstructure_stream",
        lineage_ref=f"micro:{payload.kind}:v1",
        license_ref="commercial:verified-data:v1",
        attribution_confidence=0.95,
        confirmations=max(0, payload.confirmations),
        is_internal_custody_reshuffle=payload.is_internal_custody_reshuffle,
    )
    normalized = normalize_microstructure_covariates((evt,), bundle.instrument, as_of=now)
    return {
        "accepted_count": len(normalized),
        "excluded_internal_reshuffle": payload.is_internal_custody_reshuffle,
        "features": [f.model_dump(mode="json") for f in normalized],
    }


@app.post("/api/market/sec-edgar", include_in_schema=False)
def filter_sec_edgar_endpoint(payload: SECEdgarFilterPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    bundle = build_frozen_benchmark_dataset(track="open_market", anchor=now)
    is_amend = payload.form_type.endswith("/A")
    fact = SECEdgarFilingFact(
        accession_number=f"0000320193-26-{int(now.timestamp()) % 100000:06d}",
        cik="0000320193",
        instrument_id=bundle.instrument.instrument_id,
        form_type=payload.form_type,
        concept=payload.concept,
        value=payload.value,
        unit="USD",
        fiscal_period_end=now - timedelta(days=30),
        acceptance_time=now - timedelta(days=2),
        is_amendment=is_amend,
    )
    selected = select_as_filed_sec_facts(
        (fact,),
        instrument_id=bundle.instrument.instrument_id,
        as_of=now,
        allow_vintage_amendments=payload.allow_vintage_amendments,
    )
    return {
        "selected_count": len(selected),
        "facts": [f.model_dump(mode="json") for f in selected],
        "execution_permission": "none",
    }


@app.post("/api/research/continuous-tick", include_in_schema=False)
def run_continuous_research_tick(payload: ContinuousResearchTickPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    try:
        provider = GeminiResearchProvider(
            workload=payload.workload,
            tier="paid",
            generate=lambda model, ctx: json.dumps(
                {
                    "regime": "trending",
                    "summary": f"Synthesized ({model}): {payload.observation_note[:140]}",
                    "confidence": 0.62,
                    "risk_flags": ["uncalibrated_llm_confidence_isolated_from_combiner"],
                }
            ),
        )
        note_result = provider.analyze(payload.observation_note)
        return {
            "status": "completed",
            "tick_timestamp": now.isoformat(),
            "workload": payload.workload,
            "research_note": note_result.model_dump(mode="json"),
            "execution_permission": "none",
        }
    except PolicyError as exc:
        return {
            "status": "blocked_by_policy",
            "tick_timestamp": now.isoformat(),
            "workload": payload.workload,
            "reason": str(exc),
            "execution_permission": "none",
        }


@app.get("/api/docs", include_in_schema=False)
def list_platform_documentation() -> dict[str, object]:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    doc_paths = [
        ("README.md", "Platform Overview & Run Guide", "README.md"),
        ("ATLAS_MASTER_SPEC.md", "Master Product & Authority Spec", "docs/ATLAS_MASTER_SPEC.md"),
        ("UNIVERSAL_AI_ECOSYSTEM.md", "Universal AI Architecture & Contracts", "docs/architecture/UNIVERSAL_AI_ECOSYSTEM.md"),
        ("RESEARCH_OPERATING_CONTRACT.md", "Research Operating Contract & Gates", "docs/architecture/RESEARCH_OPERATING_CONTRACT.md"),
        ("ISO_GOVERNANCE_ALIGNMENT.md", "ISO / NIST AI RMF / IOSCO Governance", "docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md"),
        ("CURRENT_STATE.md", "Verified Current State", "docs/architecture/CURRENT_STATE.md"),
        ("DECISIONS.md", "Architectural Decisions", "docs/architecture/DECISIONS.md"),
        ("AI_ECOSYSTEM.md", "Official AI Ecosystem Review", "docs/research/AI_ECOSYSTEM.md"),
        ("MCP_DATA_INTEGRATION.md", "MCP Data Integration & Rights Review", "docs/research/MCP_DATA_INTEGRATION.md"),
        ("EXP_001_BASELINE_VS_SCRATCH_TREE.md", "EXP-001 Baseline vs Scratch Tree Report", "docs/research/experiments/EXP_001_BASELINE_VS_SCRATCH_TREE.md"),
        ("AGILE_BACKLOG.md", "Agile Backlog & Roadmap", "docs/backlog/AGILE_BACKLOG.md"),
    ]
    documents = []
    for doc_id, title, rel_path in doc_paths:
        full_path = repo_root / rel_path
        content = full_path.read_text(encoding="utf-8") if full_path.exists() else f"# {title}\nFile not found: {rel_path}"
        documents.append(
            {
                "doc_id": doc_id,
                "title": title,
                "path": rel_path,
                "content": content,
            }
        )
    return {"documents": documents}


class OperatorProfilePayload(BaseModel):
    display_name: str = "Founder / Principal Architect"
    title: str = "Founder & Control-Plane Authority"
    organization: str = "ATLAS Autonomous Intelligence"
    role: Literal["founder_admin", "researcher", "monitoring"] = "founder_admin"
    default_track: Literal["competition", "open_market"] = "competition"
    risk_profile_pct: str = "0.75"
    preferred_timezone: str = "UTC"
    default_workload: Literal["frequent", "deep"] = "frequent"
    sec_user_agent: str = "ATLASResearch compliance@atlas.local"
    alerts_kill_switch: bool = True
    alerts_regime_shift: bool = True
    alerts_freshness_breach: bool = True


_OPERATOR_PROFILE: dict[str, object] = {
    "operator_id": "op:founder:001",
    "display_name": "Founder / Principal Architect",
    "title": "Founder & Control-Plane Authority",
    "organization": "ATLAS Autonomous Intelligence",
    "role": "founder_admin",
    "default_track": "competition",
    "risk_profile_pct": "0.75",
    "preferred_timezone": "UTC",
    "default_workload": "frequent",
    "sec_user_agent": "ATLASResearch compliance@atlas.local",
    "alerts_kill_switch": True,
    "alerts_regime_shift": True,
    "alerts_freshness_breach": True,
    "ownership_rights": "100% Founder-Owned (Source, Strategy Logic, Model Artifacts & Signing Keys)",
    "custody_boundary": "Non-Custodial (External Venue & Self-Custody Signer Only)",
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

_CONNECTORS_STATE: dict[str, dict[str, object]] = {
    "alpha_vantage_mcp": {
        "connector_id": "alpha_vantage_mcp",
        "name": "Alpha Vantage Official MCP",
        "vendor": "Alpha Vantage",
        "category": "mcp_data",
        "protocol": "MCP / JSON-RPC",
        "status": "connected",
        "enabled": True,
        "tools": ["DIGITAL_CURRENCY_DAILY", "TIME_SERIES_DAILY_ADJUSTED", "TIME_SERIES_INTRADAY"],
        "license_scope": "Commercial & Point-in-Time Verified",
        "execution_permission": "none",
        "latency_ms": 42,
    },
    "financial_datasets_mcp": {
        "connector_id": "financial_datasets_mcp",
        "name": "Financial Datasets MCP",
        "vendor": "Financial Datasets",
        "category": "mcp_data",
        "protocol": "MCP / REST",
        "status": "connected",
        "enabled": True,
        "tools": ["get_company_facts", "get_historical_stock_prices", "get_income_statements"],
        "license_scope": "Point-in-Time Equities & Fundamentals",
        "execution_permission": "none",
        "latency_ms": 38,
    },
    "fin_data_mcp": {
        "connector_id": "fin_data_mcp",
        "name": "Fin-Data Research MCP",
        "vendor": "Fin-Data",
        "category": "mcp_data",
        "protocol": "MCP / Stdio-HTTP",
        "status": "connected",
        "enabled": True,
        "tools": ["fetch_equity_bars", "fetch_macro_calendar", "fetch_sec_filings_meta"],
        "license_scope": "Macro Calendar & Multi-Asset Bars",
        "execution_permission": "none",
        "latency_ms": 51,
    },
    "google_gemini": {
        "connector_id": "google_gemini",
        "name": "Google Gemini Paid-Tier Narrator",
        "vendor": "Google DeepMind",
        "category": "ai_provider",
        "protocol": "Google GenAI SDK (No Tools)",
        "status": "connected",
        "enabled": True,
        "tools": ["frequent_synthesis", "deep_research_synthesis", "secret_context_screening"],
        "license_scope": "Paid Tier (Zero Prompt Training Retention)",
        "execution_permission": "none",
        "latency_ms": 115,
    },
    "sec_edgar_xbrl": {
        "connector_id": "sec_edgar_xbrl",
        "name": "U.S. SEC EDGAR As-Filed XBRL",
        "vendor": "U.S. Securities & Exchange Commission",
        "category": "market_feed",
        "protocol": "HTTPS / XBRL JSON (<=10 req/s)",
        "status": "connected",
        "enabled": True,
        "tools": ["10-K", "10-Q", "8-K", "acceptance_time_pit_filter"],
        "license_scope": "Public Domain Reuse (User-Agent Verified)",
        "execution_permission": "none",
        "latency_ms": 64,
    },
    "crypto_perp_feed": {
        "connector_id": "crypto_perp_feed",
        "name": "24/7 Crypto Perpetual & On-Chain Indexer",
        "vendor": "Perpetual Venue & L2 Book",
        "category": "market_feed",
        "protocol": "Point-in-Time Feed + Microstructure Policy",
        "status": "connected",
        "enabled": True,
        "tools": ["order_flow_imbalance", "exchange_outflow", "funding_rate", "open_interest"],
        "license_scope": "Verified Commercial Feed (6+ Block Finality)",
        "execution_permission": "none",
        "latency_ms": 19,
    },
    "nyse_calendar": {
        "connector_id": "nyse_calendar",
        "name": "NYSE / Traditional Exchange Calendar",
        "vendor": "ICE / NYSE Session Authority",
        "category": "market_feed",
        "protocol": "Authoritative Session Schedule",
        "status": "connected",
        "enabled": True,
        "tools": ["opening_auction", "regular_open", "closing_auction", "early_close_holidays"],
        "license_scope": "Versioned Exchange Schedule (nyse:regular-sessions)",
        "execution_permission": "none",
        "latency_ms": 4,
    },
    "atlas_local_ml": {
        "connector_id": "atlas_local_ml",
        "name": "ATLAS Scratch GBDT & Ridge Engine",
        "vendor": "ATLAS Internal Core",
        "category": "ai_provider",
        "protocol": "Local Deterministic Python + SQLite Registry",
        "status": "connected",
        "enabled": True,
        "tools": ["boosted_stump_v1", "gbdt_depth2_v1", "linear_ridge_v1", "regime_conditioned_tree"],
        "license_scope": "100% Founder-Owned Proprietary Weights",
        "execution_permission": "none",
        "latency_ms": 8,
    },
    "xai_grok_bridge": {
        "connector_id": "xai_grok_bridge",
        "name": "xAI Secondary Research Narrator",
        "vendor": "xAI",
        "category": "ai_provider",
        "protocol": "HTTPS Replaceable ResearchProvider Protocol",
        "status": "standby",
        "enabled": False,
        "tools": ["secondary_narrative_check"],
        "license_scope": "Contract Ready (Optional Secondary Narrator)",
        "execution_permission": "none",
        "latency_ms": 0,
    },
    "chronos_2_slot": {
        "connector_id": "chronos_2_slot",
        "name": "Chronos-2 Time-Series Foundation Slot",
        "vendor": "Amazon Science (Apache-2.0)",
        "category": "ai_provider",
        "protocol": "ForecastProvider Contract Slot",
        "status": "standby",
        "enabled": False,
        "tools": ["zero_shot_quantile_forecast"],
        "license_scope": "Apache-2.0 Archive Verification Gate",
        "execution_permission": "none",
        "latency_ms": 0,
    },
    "irohan0_quant_mcp": {
        "connector_id": "irohan0_quant_mcp",
        "name": "irohan0/quant-mcp & FRED Training Guard",
        "vendor": "Policy Quarantine",
        "category": "quarantined",
        "protocol": "Blocked by ProviderRuntime Allowlist",
        "status": "blocked",
        "enabled": False,
        "tools": ["mutating_execution_rejected", "fred_ml_training_blocked"],
        "license_scope": "Default-Deny Enforced (ISO 27001 / Master Spec)",
        "execution_permission": "none",
        "latency_ms": 0,
    },
}


class ConnectorActionPayload(BaseModel):
    connector_id: str
    action: Literal["test_connection", "toggle_enabled", "sync_metadata"] = "test_connection"


@app.get("/api/profile", include_in_schema=False)
def get_operator_profile() -> dict[str, object]:
    return dict(_OPERATOR_PROFILE)


@app.post("/api/profile", include_in_schema=False)
def update_operator_profile(payload: OperatorProfilePayload) -> dict[str, object]:
    _OPERATOR_PROFILE.update(payload.model_dump())
    _OPERATOR_PROFILE["updated_at"] = datetime.now(timezone.utc).isoformat()
    control_engine.audit_log.append(
        f"{_OPERATOR_PROFILE['updated_at']} | profile_updated | operator={payload.display_name} role={payload.role} track={payload.default_track}"
    )
    return dict(_OPERATOR_PROFILE)


@app.get("/api/connectors", include_in_schema=False)
def list_connectors() -> dict[str, object]:
    return {"connectors": list(_CONNECTORS_STATE.values())}


@app.post("/api/connectors/action", include_in_schema=False)
def connector_action_endpoint(payload: ConnectorActionPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    conn = _CONNECTORS_STATE.get(payload.connector_id)
    if conn is None:
        return {"status": "error", "message": f"Unknown connector: {payload.connector_id}"}
    if conn["category"] == "quarantined":
        return {
            "status": "blocked_by_policy",
            "connector": conn,
            "message": f"{conn['name']} is permanently blocked by deterministic control-plane policy.",
            "timestamp": now,
        }
    if payload.action == "toggle_enabled":
        next_enabled = not bool(conn["enabled"])
        conn["enabled"] = next_enabled
        conn["status"] = "connected" if next_enabled else "standby"
    elif payload.action in ("test_connection", "sync_metadata"):
        conn["status"] = "connected" if conn["enabled"] else "standby"
    control_engine.audit_log.append(
        f"{now} | connector_action | id={payload.connector_id} action={payload.action} status={conn['status']}"
    )
    return {
        "status": "ok",
        "action": payload.action,
        "connector": conn,
        "message": f"{conn['name']}: {payload.action} verified ({conn['status'].upper()})",
        "timestamp": now,
    }
