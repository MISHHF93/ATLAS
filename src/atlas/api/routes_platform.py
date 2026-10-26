"""Platform/operator endpoints (operator profile, connectors, listings, sync pipelines,
platform configuration). Split out of ``atlas.api.app`` in streamline pass 4; mounted at the
same position so route order is unchanged. Shared singletons are read from ``atlas.api.app``
at call time."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _app():
    return sys.modules["atlas.api.app"]


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

def _connector_record(
    connector_id: str, *, name: str, vendor: str, category: str,
    protocol: str, tools: list[str], enabled: bool = True,
) -> dict[str, object]:
    """Describe an integration slot without claiming a tested vendor session.

    These records are separate from the actual public-feed health endpoints.
    Enabling a record does not configure a transport or establish data rights.
    """
    blocked = category == "quarantined"
    return {
        "connector_id": connector_id, "name": name, "vendor": vendor,
        "category": category, "protocol": protocol, "tools": tools,
        "status": "blocked" if blocked else "unconfigured" if enabled else "standby",
        "enabled": enabled, "record_only": True, "connected": False,
        "transport_configured": False, "connection_test_status": "not_tested",
        "last_tested_at": None, "latency_ms": None,
        "license_scope": "Unknown: this record does not verify provider terms or data-use rights.",
        "license_status": "unknown", "license_ref": None,
        "data_use_eligibility": {use: "unknown" for use in ("display", "retention", "training", "competition", "redistribution")},
        "deployment_eligible": False, "execution_permission": "none",
        "notice": "Integration record only. No vendor transport or entitlement has been tested here.",
    }


_CONNECTORS_STATE: dict[str, dict[str, object]] = {
    "alpha_vantage_mcp": {
        "connector_id": "alpha_vantage_mcp",
        "name": "Alpha Vantage Official MCP",
        "vendor": "Alpha Vantage",
        "category": "mcp_data",
        "protocol": "MCP / JSON-RPC",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["DIGITAL_CURRENCY_DAILY", "TIME_SERIES_DAILY_ADJUSTED", "TIME_SERIES_INTRADAY"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "financial_datasets_mcp": {
        "connector_id": "financial_datasets_mcp",
        "name": "Financial Datasets MCP",
        "vendor": "Financial Datasets",
        "category": "mcp_data",
        "protocol": "MCP / REST",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["get_company_facts", "get_historical_stock_prices", "get_income_statements"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "fin_data_mcp": {
        "connector_id": "fin_data_mcp",
        "name": "Fin-Data Research MCP",
        "vendor": "Fin-Data",
        "category": "mcp_data",
        "protocol": "MCP / Stdio-HTTP",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["fetch_equity_bars", "fetch_macro_calendar", "fetch_sec_filings_meta"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "google_gemini": {
        "connector_id": "google_gemini",
        "name": "Google Gemini Paid-Tier Narrator",
        "vendor": "Google DeepMind",
        "category": "ai_provider",
        "protocol": "Google GenAI SDK (No Tools)",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["frequent_synthesis", "deep_research_synthesis", "secret_context_screening"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "sec_edgar_xbrl": {
        "connector_id": "sec_edgar_xbrl",
        "name": "U.S. SEC EDGAR As-Filed XBRL",
        "vendor": "U.S. Securities & Exchange Commission",
        "category": "market_feed",
        "protocol": "HTTPS / XBRL JSON (<=10 req/s)",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["10-K", "10-Q", "8-K", "acceptance_time_pit_filter"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "crypto_perp_feed": {
        "connector_id": "crypto_perp_feed",
        "name": "24/7 Crypto Perpetual & On-Chain Indexer",
        "vendor": "Perpetual Venue & L2 Book",
        "category": "market_feed",
        "protocol": "Point-in-Time Feed + Microstructure Policy",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["order_flow_imbalance", "exchange_outflow", "funding_rate", "open_interest"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "nyse_calendar": {
        "connector_id": "nyse_calendar",
        "name": "NYSE / Traditional Exchange Calendar",
        "vendor": "ICE / NYSE Session Authority",
        "category": "market_feed",
        "protocol": "Authoritative Session Schedule",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["opening_auction", "regular_open", "closing_auction", "early_close_holidays"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
    "atlas_local_ml": {
        "connector_id": "atlas_local_ml",
        "name": "ATLAS Scratch GBDT & Ridge Engine",
        "vendor": "ATLAS Internal Core",
        "category": "ai_provider",
        "protocol": "Local Deterministic Python + SQLite Registry",
        "status": "unconfigured",
        "enabled": True,
        "tools": ["boosted_stump_v1", "gbdt_depth2_v1", "linear_ridge_v1", "regime_conditioned_tree"],
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
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
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
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
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
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
        "license_scope": "unknown",
        "execution_permission": "none",
        "latency_ms": None,
    },
}


_CONNECTORS_STATE = {
    connector_id: _connector_record(
        connector_id, name=str(row["name"]), vendor=str(row["vendor"]),
        category=str(row["category"]), protocol=str(row["protocol"]),
        tools=list(row["tools"]), enabled=bool(row["enabled"]),
    )
    for connector_id, row in _CONNECTORS_STATE.items()
}


class ConnectorActionPayload(BaseModel):
    connector_id: str
    action: Literal["test_connection", "toggle_enabled", "sync_metadata"] = "test_connection"


@router.get("/api/profile", include_in_schema=False)
def get_operator_profile() -> dict[str, object]:
    return dict(_OPERATOR_PROFILE)


@router.post("/api/profile", include_in_schema=False)
def update_operator_profile(payload: OperatorProfilePayload) -> dict[str, object]:
    _OPERATOR_PROFILE.update(payload.model_dump())
    _OPERATOR_PROFILE["updated_at"] = datetime.now(timezone.utc).isoformat()
    _app().control_engine.audit_log.append(
        f"{_OPERATOR_PROFILE['updated_at']} | profile_updated | operator={payload.display_name} role={payload.role} track={payload.default_track}"
    )
    return dict(_OPERATOR_PROFILE)


@router.get("/api/connectors", include_in_schema=False)
def list_connectors() -> dict[str, object]:
    return {"connectors": list(_CONNECTORS_STATE.values()), "record_only": True,
            "notice": "Integration records are not live-session evidence. Actual public-feed coverage is reported by /api/ml/live-observer/status and /api/market/live-artifacts."}


@router.post("/api/connectors/action", include_in_schema=False)
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
        conn["status"] = "unconfigured" if next_enabled else "standby"
    # No transport probe or provider metadata fetch is implemented by these
    # record actions. Preserve that distinction even after repeated requests.
    operation_status = "record_updated" if payload.action == "toggle_enabled" else "not_tested" if payload.action == "test_connection" else "not_synced"
    conn["connected"] = False
    conn["connection_test_status"] = "not_tested"
    conn["last_tested_at"] = None
    conn["latency_ms"] = None
    _app().control_engine.audit_log.append(
        f"{now} | connector_record_action | id={payload.connector_id} action={payload.action} result={operation_status}"
    )
    return {
        "status": "ok",
        "operation_status": operation_status,
        "record_only": True,
        "data_synced": False,
        "action": payload.action,
        "connector": conn,
        "message": f"{conn['name']}: {operation_status}. Record action only; no vendor session, metadata sync, or data-use entitlement was verified.",
        "timestamp": now,
    }


# Static listing metadata only. Prices/changes/freshness are NEVER stored here: get_live_listings() overlays the latest
# ATLAS feed quote (source + Toronto time + status) on every request; with no stored print the price is None/no_data.
_LIVE_LISTINGS_STATE: list[dict[str, object]] = [
    {
        "instrument_id": "open:spy-etf:v1",
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF Trust (Benchmark Stock Index)",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "us_equity_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:nvda-eq:v1",
        "symbol": "NVDA",
        "name": "NVIDIA Corp. (Common Stock + SEC XBRL CIK 0001045810)",
        "track": "open_market",
        "venue": "Nasdaq Global Select · XNAS",
        "asset_class": "us_equity_sec",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:aapl-eq:v1",
        "symbol": "AAPL",
        "name": "Apple Inc. (Common Stock + SEC XBRL CIK 0000320193)",
        "track": "open_market",
        "venue": "Nasdaq Global Select · XNAS",
        "asset_class": "us_equity_sec",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:msft-eq:v1",
        "symbol": "MSFT",
        "name": "Microsoft Corp. (Common Stock + SEC XBRL CIK 0000789019)",
        "track": "open_market",
        "venue": "Nasdaq Global Select · XNAS",
        "asset_class": "us_equity_sec",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:qqq-etf:v1",
        "symbol": "QQQ",
        "name": "Invesco QQQ Trust (Nasdaq-100 Stock Index)",
        "track": "open_market",
        "venue": "Nasdaq · Regular Session",
        "asset_class": "us_equity_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:tsla-eq:v1",
        "symbol": "TSLA",
        "name": "Tesla Inc. (Common Stock + SEC XBRL CIK 0001318605)",
        "track": "open_market",
        "venue": "Nasdaq Global Select · XNAS",
        "asset_class": "us_equity_sec",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "comp:btc-perp:v1",
        "symbol": "BTC-USD",
        "name": "Bitcoin Perpetual Swap (Prop Competition Desk)",
        "track": "competition",
        "venue": "Prop Competition 24/7 Venue",
        "asset_class": "crypto_perp",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "comp:eth-perp:v1",
        "symbol": "ETH-USD",
        "name": "Ethereum Perpetual Swap (Prop Competition Desk)",
        "track": "competition",
        "venue": "Prop Competition 24/7 Venue",
        "asset_class": "crypto_perp",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "comp:sol-perp:v1",
        "symbol": "SOL-USD",
        "name": "Solana Perpetual Swap (Prop Competition Desk)",
        "track": "competition",
        "venue": "Prop Competition 24/7 Venue",
        "asset_class": "crypto_perp",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:gc-fut:v1",
        "symbol": "GC",
        "name": "Gold Futures — COMEX Front Month (XAU/USD Benchmark)",
        "track": "open_market",
        "venue": "CME Globex · COMEX Metals",
        "asset_class": "precious_metal_future",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:si-fut:v1",
        "symbol": "SI",
        "name": "Silver Futures — COMEX Front Month (XAG/USD Benchmark)",
        "track": "open_market",
        "venue": "CME Globex · COMEX Metals",
        "asset_class": "precious_metal_future",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:gld-etf:v1",
        "symbol": "GLD",
        "name": "SPDR Gold Shares Physical Bullion Trust ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "precious_metal_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:slv-etf:v1",
        "symbol": "SLV",
        "name": "iShares Silver Trust Physical Bullion ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "precious_metal_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:iwm-etf:v1",
        "symbol": "IWM",
        "name": "iShares Russell 2000 Small-Cap Index ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "us_equity_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:tlt-etf:v1",
        "symbol": "TLT",
        "name": "iShares 20+ Year US Treasury Bond ETF",
        "track": "open_market",
        "venue": "Nasdaq · Regular Session",
        "asset_class": "treasury_bond_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:xlk-etf:v1",
        "symbol": "XLK",
        "name": "Technology Select Sector SPDR Fund ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "sector_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:xlf-etf:v1",
        "symbol": "XLF",
        "name": "Financial Select Sector SPDR Fund ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "sector_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:xle-etf:v1",
        "symbol": "XLE",
        "name": "Energy Select Sector SPDR Fund ETF",
        "track": "open_market",
        "venue": "NYSE Arca · Regular Session",
        "asset_class": "sector_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:soxx-etf:v1",
        "symbol": "SOXX",
        "name": "iShares Semiconductor Index ETF",
        "track": "open_market",
        "venue": "Nasdaq · Regular Session",
        "asset_class": "thematic_etf",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:es-fut:v1",
        "symbol": "ES",
        "name": "E-mini S&P 500 Index Futures (CME Globex)",
        "track": "open_market",
        "venue": "CME Globex · Equity Index",
        "asset_class": "cme_future",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:cl-fut:v1",
        "symbol": "CL",
        "name": "WTI Light Sweet Crude Oil Futures (NYMEX)",
        "track": "open_market",
        "venue": "CME Globex · NYMEX Energy",
        "asset_class": "cme_future",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:eurusd-fx:v1",
        "symbol": "EUR_USD",
        "name": "Euro / US Dollar Spot Foreign Exchange (ECB & Interbank)",
        "track": "open_market",
        "venue": "ECB Reference & Global FX Spot",
        "asset_class": "fx_spot",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
    {
        "instrument_id": "open:usdcad-fx:v1",
        "symbol": "USD_CAD",
        "name": "US Dollar / Canadian Dollar Spot Foreign Exchange (BoC Valet)",
        "track": "open_market",
        "venue": "Bank of Canada & Global FX Spot",
        "asset_class": "fx_spot",
        "price": None,
        "change_24h_pct": None,
        "volume_24h_usd": None,
        "spread_bps": None,
        "regime": None,
        "pit_status": "verified",
        "freshness_seconds": None,
        "model_signal": None,
        "enabled": True,
    },
]

_SYNC_PIPELINES_STATE: list[dict[str, object]] = [
    {
        "pipeline_id": "sync:crypto_perp_ohlcv",
        "name": "24/7 Crypto Perp OHLCV & Funding Feed",
        "source": "crypto_perp_feed (unconfigured)",
        "cadence": "5s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
    {
        "pipeline_id": "sync:nyse_session_bars",
        "name": "NYSE / Nasdaq Session-Aligned Equity Bars",
        "source": "nyse:regular-sessions / financial_datasets_mcp",
        "cadence": "15s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
    {
        "pipeline_id": "sync:mcp_allowlist_surface",
        "name": "Allowlisted MCP Read-Only Data Surface",
        "source": "alpha_vantage_mcp + fin_data_mcp",
        "cadence": "60s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
    {
        "pipeline_id": "sync:sec_edgar_xbrl_pit",
        "name": "U.S. SEC EDGAR As-Filed XBRL Point-in-Time",
        "source": "sec_edgar_xbrl (acceptance_time <= as_of)",
        "cadence": "60s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
    {
        "pipeline_id": "sync:whale_microstructure",
        "name": "On-Chain Whale & L2 Order-Flow Covariates",
        "source": "onchain_indexer (unconfigured)",
        "cadence": "15s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
    {
        "pipeline_id": "sync:sqlite_model_registry",
        "name": "SQLite Model Registry & Experiment Checkpoints",
        "source": "local_sqlite_wal",
        "cadence": "5s",
        "status": "record_only",
        "records_synced": 0,
        "manifest_sha256": None,
        "latency_ms": None,
        "last_synced_at": None,
    },
]

for _pipeline_record in _SYNC_PIPELINES_STATE:
    _pipeline_record.update(
        record_only=True, operation_status="not_synced", data_synced=False,
        license_status="unknown", last_requested_at=None,
        notice="Pipeline configuration record only. No transport, scheduler, data transfer, or verified manifest is attached to this action.",
    )

_PLATFORM_CONFIG_STATE: dict[str, object] = {
    "competition_max_notional_usd": "50000.00",
    "open_market_max_notional_usd": "40000.00",
    "daily_loss_limit_pct": "4.00",
    "trailing_drawdown_limit_pct": "8.00",
    "per_trade_risk_limit_pct": "0.75",
    "min_stop_distance_bps": 25,
    "auto_flatten_on_breach": True,
    "enforce_consistency_rule": True,
    "default_challenger_family": "boosted_stump_v1",
    "gemini_workload_tier": "frequent",
    "secret_context_screening": True,
    "ensemble_correlation_gate": 0.80,
    "default_purge_bars": 1,
    "default_embargo_bars": 1,
    "default_round_trip_cost_bps": 4.0,
    "sync_cadence_seconds": 15,
    "provider_timeout_ms": 8000,
    "max_provider_retries": 2,
    "circuit_breaker_threshold": 3,
    "sec_edgar_rate_limit_rps": 10,
    "updated_at": "2026-10-19T22:00:00Z",
}


class ListingActionPayload(BaseModel):
    instrument_id: str
    symbol: str = "BTC-USD"
    name: str = "Custom Listing"
    track: Literal["competition", "open_market"] = "competition"
    price: str = "100.00"
    action: Literal["toggle_enabled", "refresh_quote", "add_listing"] = "refresh_quote"


class SyncRunPayload(BaseModel):
    pipeline_id: str = "all"
    cadence: str | None = None


class PlatformConfigPayload(BaseModel):
    competition_max_notional_usd: str = "50000.00"
    open_market_max_notional_usd: str = "40000.00"
    daily_loss_limit_pct: str = "4.00"
    trailing_drawdown_limit_pct: str = "8.00"
    per_trade_risk_limit_pct: str = "0.75"
    min_stop_distance_bps: int = 25
    auto_flatten_on_breach: bool = True
    enforce_consistency_rule: bool = True
    default_challenger_family: str = "boosted_stump_v1"
    gemini_workload_tier: Literal["frequent", "deep"] = "frequent"
    secret_context_screening: bool = True
    ensemble_correlation_gate: float = 0.80
    default_purge_bars: int = 1
    default_embargo_bars: int = 1
    default_round_trip_cost_bps: float = 4.0
    sync_cadence_seconds: int = 15
    provider_timeout_ms: int = 8000
    max_provider_retries: int = 2
    circuit_breaker_threshold: int = 3
    sec_edgar_rate_limit_rps: int = 10


def _with_feed_quotes(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Overlay the ATLAS feed quote on each row: price/change/source/status/Toronto time. No feed print -> price None."""
    from atlas.api.feeds_api import feed_quotes
    if os.environ.get("ATLAS_DISABLE_FEED_QUOTES") == "1":
        q = {}
    else:
        q = feed_quotes([str(r["symbol"]) for r in rows])
    out = []
    for r in rows:
        v = q.get(str(r["symbol"])) or {"status": "no_data", "price": None, "source": None}
        out.append({**r, "price": None if v.get("price") is None else f"{v['price']:.8g}" if v["price"] < 1 else f"{v['price']:.2f}",
                    "change_24h_pct": v.get("change_pct"), "quote_source": v.get("source"), "quote_status": v["status"],
                    "quote_time": v.get("observed_at_toronto"), "quote_epoch": v.get("observed_at"),
                    "freshness_seconds": v.get("age_seconds"), "feed_instrument": v.get("instrument")})
    return out


@router.get("/api/listings", include_in_schema=False)
def get_live_listings() -> dict[str, object]:
    return {"listings": _with_feed_quotes(list(_LIVE_LISTINGS_STATE))}


@router.post("/api/listings/action", include_in_schema=False)
def listing_action_endpoint(payload: ListingActionPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    if payload.action == "add_listing":
        new_item = {
            "instrument_id": payload.instrument_id,
            "symbol": payload.symbol.upper(),
            "name": payload.name,
            "track": payload.track,
            "venue": "Crypto Perp 24/7 Venue" if payload.track == "competition" else "NYSE / Nasdaq Session",
            "asset_class": "crypto_perp" if payload.track == "competition" else "us_equity_etf",
            "price": None,  # the client-supplied price is ignored: quotes come from the ATLAS feed only
            "change_24h_pct": None,
            "volume_24h_usd": None,
            "spread_bps": None,
            "regime": None,
            "pit_status": "unverified",
            "freshness_seconds": None,
            "model_signal": None,
            "enabled": True,
        }
        _LIVE_LISTINGS_STATE.append(new_item)
        _app().control_engine.audit_log.append(f"{now} | listing_added | id={payload.instrument_id} symbol={payload.symbol}")
        return {"status": "ok", "listings": _with_feed_quotes(list(_LIVE_LISTINGS_STATE)), "message": f"Added live listing {payload.symbol}"}

    for item in _LIVE_LISTINGS_STATE:
        if item["instrument_id"] == payload.instrument_id:
            if payload.action == "toggle_enabled":
                item["enabled"] = not bool(item["enabled"])
            elif payload.action == "refresh_quote":
                pass  # quotes are re-read from the feed store below; nothing is faked here
            _app().control_engine.audit_log.append(
                f"{now} | listing_{payload.action} | id={payload.instrument_id} enabled={item['enabled']}"
            )
            return {"status": "ok", "listings": _with_feed_quotes(list(_LIVE_LISTINGS_STATE)), "message": f"Updated {item['symbol']}"}
    return {"status": "ok", "listings": _with_feed_quotes(list(_LIVE_LISTINGS_STATE)), "message": "Listings synchronized"}


@router.get("/api/sync", include_in_schema=False)
def get_sync_pipelines() -> dict[str, object]:
    return {"pipelines": list(_SYNC_PIPELINES_STATE), "record_only": True,
            "notice": "These are pipeline configuration records, not completed sync evidence. Actual received-feed artifacts are reported by /api/market/live-artifacts."}


@router.post("/api/sync/run", include_in_schema=False)
def run_sync_pipeline(payload: SyncRunPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    requested_count = 0
    for pipe in _SYNC_PIPELINES_STATE:
        if payload.pipeline_id in ("all", pipe["pipeline_id"]):
            pipe["last_requested_at"] = now
            if payload.cadence:
                pipe["cadence"] = payload.cadence
            requested_count += 1
    _app().control_engine.audit_log.append(
        f"{now} | sync_record_action | target={payload.pipeline_id} records_updated={requested_count} data_synced=false"
    )
    return {
        "status": "ok" if requested_count else "error",
        "operation_status": "not_synced" if requested_count else "not_found",
        "record_only": True,
        "data_synced": False,
        "pipelines": list(_SYNC_PIPELINES_STATE),
        "message": f"Recorded a request for {requested_count} pipeline(s). No data was fetched, synchronized, or licensed; cadence changes update this record only.",
        "timestamp": now,
    }


@router.get("/api/configurations", include_in_schema=False)
def get_platform_configurations() -> dict[str, object]:
    return dict(_PLATFORM_CONFIG_STATE)


@router.post("/api/configurations", include_in_schema=False)
def update_platform_configurations(payload: PlatformConfigPayload) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    _PLATFORM_CONFIG_STATE.update(payload.model_dump())
    _PLATFORM_CONFIG_STATE["updated_at"] = now
    _app().control_engine.audit_log.append(
        f"{now} | platform_configurations_updated | comp_cap=${payload.competition_max_notional_usd} risk={payload.per_trade_risk_limit_pct}% sync={payload.sync_cadence_seconds}s"
    )
    return dict(_PLATFORM_CONFIG_STATE)


@router.get("/api/configurations/auto-optimize", include_in_schema=False)
@router.post("/api/configurations/auto-optimize", include_in_schema=False)
def auto_optimize_platform_configurations(symbol: str = "BTC-USD") -> dict[str, object]:
    """Zero-touch autonomous configuration optimizer.

    Automatically derives track, staleness circuit breaker, VPIN toxicity stop-widening,
    ATR structural stop distance, execution algorithm, and risk-optimal notional sizing
    from the live market stream and 12-Factor Whale Opportunity Engine (`execution_permission: 'none'`).
    """
    sym = symbol.upper().strip()
    is_crypto = sym.endswith("-USD") or sym in {"BTC-USD", "ETH-USD", "SOL-USD"}
    auto_track: Literal["competition", "open_market"] = "competition" if is_crypto else "open_market"

    pred = _app().bot_orchestrator.predict_live_market_data(
        _app().live_market_gateway,
        symbol=sym,
        granularity=900,
        allow_network=False,
    )
    opp = pred.get("locked_whale_opportunity") or {}
    micro = pred.get("live_microstructure") or {}

    vpin_val = float(micro.get("vpin", 0.29))
    vpin_widening = vpin_val >= 0.40
    raw_stop_bps = float(opp.get("stop_distance_bps", 95.0))
    effective_stop_bps = round(raw_stop_bps * (1.5 if vpin_widening else 1.0), 1)

    # Risk-optimal notional targeting 0.45% equity risk ($450 risk budget) capped by track ceiling
    max_cap = 45000.0 if auto_track == "competition" else 38000.0
    risk_budget_usd = float(_app().control_engine.current_equity_usd) * 0.0045
    optimal_notional = min(max_cap, max(5000.0, round((risk_budget_usd / max(0.0025, effective_stop_bps / 10_000.0)) / 500.0) * 500.0))

    now_iso = datetime.now(timezone.utc).isoformat()
    _PLATFORM_CONFIG_STATE.update(
        {
            "daily_loss_limit_pct": "4.00" if auto_track == "competition" else "3.00",
            "trailing_drawdown_limit_pct": "8.00" if auto_track == "competition" else "10.00",
            "per_trade_risk_limit_pct": "0.75" if auto_track == "competition" else "0.50",
            "min_stop_distance_bps": int(max(25, round(effective_stop_bps))),
            "auto_flatten_on_breach": True,
            "enforce_consistency_rule": auto_track == "competition",
            "updated_at": now_iso,
        }
    )

    return {
        "status": "ok",
        "autopilot_mode": "zero_touch_active",
        "symbol": sym,
        "auto_track": auto_track,
        "auto_side": str(opp.get("action", "BUY")).lower(),
        "auto_execution_tactic": str(opp.get("execution_tactic", "ALMGREN_CHRISS")),
        "auto_atr_stop_bps": effective_stop_bps,
        "auto_optimal_notional_usd": optimal_notional,
        "auto_staleness_breaker_ms": 500 if auto_track == "competition" else 2000,
        "auto_vpin_stop_widening": vpin_widening,
        "locked_opportunity": opp,
        "configurations": dict(_PLATFORM_CONFIG_STATE),
        "execution_permission": "none",
    }
