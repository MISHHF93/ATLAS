"""FastAPI router for the 10-Vertical Authentic Assets Catalog (`/api/assets/*`)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.assets.authenticity import verify_instrument_authenticity
from atlas.assets.canadian_compliance import (
    build_canadian_compliance_report,
    evaluate_canadian_regulatory_gate,
)
from atlas.assets.connectors import audit_market_data_connectors
from atlas.assets.equities_bonds_cash import (
    BONDS_AND_FIXED_INCOME_CATALOG,
    CASH_EQUIVALENTS_CATALOG,
    FLAGSHIP_PUBLIC_EQUITIES,
    build_equities_bonds_cash_catalog,
)
from atlas.assets.etf_intelligence import (
    ETFS_BY_SYMBOL,
    ETF_INTELLIGENCE_CATALOG,
    get_etf_fund_details,
    list_etf_intelligence,
)
from atlas.assets.master import (
    POSTGRES_CANONICAL_ASSET_MASTER_DDL,
    get_canonical_asset_master,
)
from atlas.assets.mcp_tools import (
    _get_usd_cad_rate,
    _query_latest_feed_quote,
    call_governed_mcp_tool,
    list_governed_mcp_tools,
)
from atlas.assets.precious_metals import (
    METALS_BY_SYMBOL,
    PRECIOUS_METAL_INSTRUMENTS,
    build_precious_metals_catalog,
)

router = APIRouter(tags=["authentic-assets"])


class ComplianceEvaluationRequest(BaseModel):
    action: str = Field(..., description="Action to evaluate under Canadian regulatory gates")
    payload: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallRequest(BaseModel):
    tool: str = Field(..., description="Governed read-only MCP tool name")
    params: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(default="default_workspace")
    role: str = Field(default="researcher")


@router.get("/master")
def get_asset_master_endpoint(
    q: str = Query(default="", description="Search query"),
    asset_class: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=500),
    include_ddl: bool = Query(default=False),
) -> dict[str, Any]:
    master = get_canonical_asset_master()
    matches = master.list_instruments(
        asset_class=asset_class,
        jurisdiction=jurisdiction,
        currency=currency,
        query=q,
    )[:limit]
    resp: dict[str, Any] = {
        "feature": "1_canonical_asset_master",
        "execution_permission": "none",
        "summary": master.summary_counts(),
        "count": len(matches),
        "items": [m.as_dict() for m in matches],
    }
    if include_ddl:
        resp["postgres_drizzle_ddl"] = POSTGRES_CANONICAL_ASSET_MASTER_DDL
    return resp


@router.get("/profile/{symbol}")
def get_asset_profile_endpoint(symbol: str) -> dict[str, Any]:
    sym = symbol.strip().upper()
    master = get_canonical_asset_master()
    inst = master.get_instrument(sym)
    if inst is None:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument '{sym}' not found in verified Canonical Asset Master.",
        )
    issuer = master.get_issuer(inst.issuer_id)
    venue = master.get_exchange(inst.primary_exchange_mic)
    usd_cad = _get_usd_cad_rate()
    quote = _query_latest_feed_quote(sym)
    etf = ETFS_BY_SYMBOL.get(sym)
    pm = METALS_BY_SYMBOL.get(sym)
    auth_report = verify_instrument_authenticity(sym, master_record=inst)
    return {
        "execution_permission": "none",
        "instrument": inst.as_dict(),
        "issuer": issuer.as_dict() if issuer else None,
        "exchange_venue": venue.as_dict() if venue else None,
        "latest_quote": quote,
        "usd_cad_rate": usd_cad,
        "authenticity": auth_report.as_dict(),
        "etf_details": etf.as_dict() if etf else None,
        "precious_metal_details": pm.as_dict() if pm else None,
    }


@router.get("/metals")
def get_precious_metals_endpoint(
    metal: str | None = Query(default=None, description="gold, silver, platinum, palladium"),
    holding_form: str | None = Query(default=None),
) -> dict[str, Any]:
    out = build_precious_metals_catalog(metal=metal, holding_form=holding_form)
    out["feature"] = "2_precious_metals_catalog"
    return out


@router.get("/etfs")
def get_etfs_endpoint(
    category: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    issuer: str | None = Query(default=None),
) -> dict[str, Any]:
    out = list_etf_intelligence(
        sub_category=category,
        jurisdiction=jurisdiction,
        issuer_id=issuer,
    )
    out["feature"] = "3_etf_and_fund_intelligence"
    return out


@router.get("/etfs/{symbol}")
def get_single_etf_endpoint(symbol: str) -> dict[str, Any]:
    try:
        out = get_etf_fund_details(symbol)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    out["feature"] = "3_etf_and_fund_intelligence"
    return out


@router.get("/equities-bonds-cash")
def get_equities_bonds_cash_endpoint(
    section: str = Query(default="all", description="all | equities | bonds | cash_equivalents"),
) -> dict[str, Any]:
    sec = section if section in ("all", "equities", "bonds", "cash_equivalents") else "all"
    out = build_equities_bonds_cash_catalog(section=sec)  # type: ignore[arg-type]
    out["feature"] = "4_equities_bonds_and_cash_equivalents"
    return out


@router.get("/connectors")
def get_connectors_endpoint() -> dict[str, Any]:
    report = audit_market_data_connectors()
    report["feature"] = "5_authorized_market_data_connectors"
    report["execution_permission"] = "none"
    return report


@router.get("/verify/{symbol}")
def verify_symbol_endpoint(symbol: str) -> dict[str, Any]:
    report = verify_instrument_authenticity(symbol)
    out = report.as_dict()
    out["feature"] = "6_instrument_authenticity_and_data_quality"
    out["execution_permission"] = "none"
    return out


@router.get("/canadian-compliance")
def get_canadian_compliance_endpoint() -> dict[str, Any]:
    report = build_canadian_compliance_report()
    report["feature"] = "7_canadian_regulatory_and_commercial_gates"
    return report


@router.post("/canadian-compliance/evaluate")
def evaluate_canadian_compliance_endpoint(
    req: ComplianceEvaluationRequest,
) -> dict[str, Any]:
    res = evaluate_canadian_regulatory_gate(req.action, req.payload)
    res["feature"] = "7_canadian_regulatory_and_commercial_gates"
    return res


@router.get("/compare")
def compare_assets_endpoint(
    symbols: str = Query(
        default="GC,GLD,MNT.TO,TLT",
        description="Comma-separated list of symbols to compare side by side",
    ),
) -> dict[str, Any]:
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    res = call_governed_mcp_tool(
        "assets.compare",
        {"symbols": sym_list},
        role="researcher",
    )
    res["feature"] = "8_unified_asset_discovery_comparison"
    return res


@router.get("/mcp/tools")
def list_mcp_tools_endpoint() -> dict[str, Any]:
    tools = list_governed_mcp_tools()
    return {
        "feature": "9_gemini_ai_and_mcp_asset_capabilities",
        "execution_permission": "none",
        "count": len(tools),
        "tools": tools,
    }


@router.post("/mcp/call")
def call_mcp_tool_endpoint(req: MCPToolCallRequest) -> dict[str, Any]:
    return call_governed_mcp_tool(
        req.tool,
        req.params,
        tenant_id=req.tenant_id,
        role=req.role,
    )


@router.get("/readiness-report")
def get_readiness_report_endpoint() -> dict[str, Any]:
    master = get_canonical_asset_master()
    connectors = audit_market_data_connectors()
    compliance = build_canadian_compliance_report()
    mcp_tools = list_governed_mcp_tools()
    return {
        "feature": "10_independent_testing_and_release_readiness",
        "status": "READY",
        "execution_permission": "none",
        "pump_fun_roadmap_status": "disabled_by_product_policy",
        "paid_data_enabled": False,
        "canonical_master_summary": master.summary_counts(),
        "precious_metals_count": len(PRECIOUS_METAL_INSTRUMENTS),
        "etf_catalog_count": len(ETF_INTELLIGENCE_CATALOG),
        "public_equities_count": len(FLAGSHIP_PUBLIC_EQUITIES),
        "bonds_count": len(BONDS_AND_FIXED_INCOME_CATALOG),
        "cash_equivalents_count": len(CASH_EQUIVALENTS_CATALOG),
        "connectors_summary": {
            "total_connectors": len(connectors.get("connectors", [])),
            "feed_sqlite_path": connectors.get("feed_sqlite_path"),
        },
        "canadian_regulatory_gates_count": compliance["total_gates"],
        "governed_mcp_tools_count": len(mcp_tools),
        "governed_mcp_tool_names": [t["name"] for t in mcp_tools],
    }


@router.get("/daily-brief")
def get_assets_daily_brief_endpoint(
    symbols: str | None = Query(
        default=None,
        description="Optional comma-separated symbol list for the AI Daily Investment & ML Research Brief",
    ),
    include_llm_narrative: bool = Query(default=True),
) -> dict[str, Any]:
    from atlas.ai.daily_brief import build_ai_daily_investment_brief

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return build_ai_daily_investment_brief(
        symbols=sym_list,
        include_llm_narrative=include_llm_narrative,
        execute_top_paper=False,
    )


