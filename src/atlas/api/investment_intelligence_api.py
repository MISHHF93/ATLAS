"""FastAPI Router for the ContrainerMaster / ATLAS AI Daily Investment Intelligence System.

Mounted at `/api/investment-intelligence/*`, exposing all 10 Complete Vertical Features:
1. `/portfolio`, `/transactions`, `/transactions/import`, `/reconcile` (Feature 1)
2. `/yesterday` (Feature 2)
3. `/daily-brief` (Feature 3)
4. `/market-snapshot`, `/market-history/{symbol}` (Feature 4)
5. `/ratings`, `/ratings/{symbol}` (Feature 5)
6. `/ml-forecasts`, `/ml-forecasts/{symbol}` (Feature 6)
7. `/performance` (Feature 7)
8. `/mcp/tools`, `/mcp/call` (Feature 8 — 11 governed MCP tools)
9. `/preferences`, `/archive` (Feature 9)
10. `/compliance`, `/pilot` (Feature 10)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.investment_intelligence import (
    EXECUTION_PERMISSION,
    POSTGRES_INVESTMENT_INTELLIGENCE_DDL,
    batch_ml_forecasts,
    batch_multifactor_ratings,
    build_investment_compliance_and_security_report,
    build_yesterday_investment_activity_brief,
    call_investment_mcp_tool,
    compute_asset_multifactor_rating,
    compute_portfolio_risk_and_performance,
    forecast_symbol_ml,
    generate_full_daily_intelligence_brief,
    get_historical_series,
    get_investment_ledger,
    get_market_snapshot,
    get_point_in_time_usd_cad,
    get_research_catalysts,
    list_investment_mcp_tools,
    run_end_to_end_pilot,
)

router = APIRouter(tags=["investment-intelligence"])


class ManualTransactionInput(BaseModel):
    tenant_id: str = Field(default="default_workspace")
    account_id: str = Field(default="default_workspace_core_multi_asset")
    tx_type: str = Field(..., description="BUY | SELL | DEPOSIT | WITHDRAWAL | DIVIDEND | DISTRIBUTION | INTEREST | FEE | SPLIT")
    trade_date: str = Field(..., description="YYYY-MM-DD")
    settlement_date: str | None = None
    symbol: str | None = None
    quantity: float = 0.0
    price: float = 0.0
    gross_amount: float | None = None
    fee: float = 0.0
    currency: str = "USD"
    verification_status: str = "USER_ENTERED"
    source_provenance: str = "manual_user_entry"
    correction_of_tx_id: str | None = None
    notes: str = ""


class BatchImportInput(BaseModel):
    tenant_id: str = Field(default="default_workspace")
    account_id: str = Field(default="default_workspace_core_multi_asset")
    rows: list[dict[str, Any]]
    source_provenance: str = "statement_upload_csv_json"
    default_verification_status: str = "VERIFIED_TRANSACTION"


class PreferencesUpdateInput(BaseModel):
    tenant_id: str = Field(default="default_workspace")
    preferred_currency: str | None = None
    timezone_name: str | None = None
    watchlist_symbols: list[str] | None = None
    research_interests: list[str] | None = None
    schedule_cron: str | None = None
    delivery_channel: str | None = None
    notification_opt_in: bool | None = None


class InvestmentMCPCallInput(BaseModel):
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = Field(default="default_workspace")
    role: str = Field(default="researcher")


@router.get("/portfolio")
def get_portfolio_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    as_of_date: str | None = Query(default=None),
    include_ddl: bool = Query(default=False),
) -> dict[str, Any]:
    led = get_investment_ledger()
    snap = get_market_snapshot(as_of_date=as_of_date)
    usd_cad = get_point_in_time_usd_cad(as_of_date=as_of_date)
    out = led.compute_portfolio_state(
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        price_lookup=snap["quotes_by_symbol"],
        usd_cad_rate=usd_cad,
    )
    out["feature"] = "1_canonical_investment_portfolio_and_transaction_ledger"
    if include_ddl:
        out["postgres_drizzle_ddl"] = POSTGRES_INVESTMENT_INTELLIGENCE_DDL
    return out


@router.get("/transactions")
def get_transactions_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    as_of_date: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    include_superseded: bool = Query(default=False),
) -> dict[str, Any]:
    led = get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=tenant_id)
    txs = led.list_transactions(
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        include_superseded=include_superseded,
        symbol=symbol,
    )
    return {
        "feature": "1_canonical_investment_portfolio_and_transaction_ledger",
        "tenant_id": tenant_id,
        "count": len(txs),
        "transactions": [t.as_dict() for t in txs],
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.post("/transactions")
def post_manual_transaction_endpoint(body: ManualTransactionInput) -> dict[str, Any]:
    led = get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=body.tenant_id)
    try:
        return led.record_transaction(
            tenant_id=body.tenant_id,
            account_id=body.account_id,
            tx_type=body.tx_type,  # type: ignore[arg-type]
            trade_date=body.trade_date,
            settlement_date=body.settlement_date,
            symbol=body.symbol,
            quantity=body.quantity,
            price=body.price,
            gross_amount=body.gross_amount,
            fee=body.fee,
            currency=body.currency,
            verification_status=body.verification_status,  # type: ignore[arg-type]
            source_provenance=body.source_provenance,
            correction_of_tx_id=body.correction_of_tx_id,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transactions/import")
def post_import_transactions_endpoint(body: BatchImportInput) -> dict[str, Any]:
    led = get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=body.tenant_id)
    return led.import_transactions(
        tenant_id=body.tenant_id,
        account_id=body.account_id,
        rows=body.rows,
        source_provenance=body.source_provenance,
        default_verification_status=body.default_verification_status,  # type: ignore[arg-type]
    )


@router.get("/reconcile")
def get_reconcile_endpoint(tenant_id: str = Query(default="default_workspace")) -> dict[str, Any]:
    led = get_investment_ledger()
    snap = get_market_snapshot()
    return led.reconcile_holdings(
        tenant_id=tenant_id,
        price_lookup=snap["quotes_by_symbol"],
        usd_cad_rate=snap["usd_cad_rate"],
    )


@router.get("/yesterday")
def get_yesterday_activity_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    as_of_date: str | None = Query(default=None),
    timezone: str = Query(default="America/Toronto"),
) -> dict[str, Any]:
    return build_yesterday_investment_activity_brief(
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        timezone_name=timezone,
    )


@router.get("/daily-brief")
def get_full_daily_brief_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    as_of_date: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    timezone: str = Query(default="America/Toronto"),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return generate_full_daily_intelligence_brief(
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        symbols=sym_list,
        timezone_name=timezone,
        archive_result=True,
    )


@router.get("/market-snapshot")
def get_market_snapshot_endpoint(
    symbols: str | None = Query(default=None),
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return get_market_snapshot(symbols=sym_list, as_of_date=as_of_date)


@router.get("/market-history/{symbol}")
def get_market_history_endpoint(
    symbol: str,
    timeframe: str = Query(default="1d"),
    as_of_date: str | None = Query(default=None),
    limit: int = Query(default=90, ge=5, le=260),
) -> dict[str, Any]:
    return get_historical_series(symbol=symbol, timeframe=timeframe, as_of_date=as_of_date, limit=limit)


@router.get("/ratings")
def get_batch_ratings_endpoint(
    symbols: str | None = Query(default=None),
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return batch_multifactor_ratings(symbols=sym_list, as_of_date=as_of_date)


@router.get("/ratings/{symbol}")
def get_single_rating_endpoint(
    symbol: str,
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    return compute_asset_multifactor_rating(symbol=symbol, as_of_date=as_of_date)


@router.get("/ml-forecasts")
def get_batch_ml_forecasts_endpoint(
    symbols: str | None = Query(default=None),
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return batch_ml_forecasts(symbols=sym_list, as_of_date=as_of_date)


@router.get("/ml-forecasts/{symbol}")
def get_single_ml_forecast_endpoint(
    symbol: str,
    as_of_date: str | None = Query(default=None),
    horizon_days: int = Query(default=5, ge=1, le=30),
) -> dict[str, Any]:
    return forecast_symbol_ml(symbol=symbol, as_of_date=as_of_date, horizon_days=horizon_days)


@router.get("/performance")
def get_performance_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    return compute_portfolio_risk_and_performance(tenant_id=tenant_id, as_of_date=as_of_date)


@router.get("/catalysts")
def get_catalysts_endpoint(
    symbols: str | None = Query(default=None),
    as_of_date: str | None = Query(default=None),
) -> dict[str, Any]:
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    return get_research_catalysts(symbols=sym_list, as_of_date=as_of_date)


@router.get("/mcp/tools")
def get_investment_mcp_tools_endpoint() -> dict[str, Any]:
    tools = list_investment_mcp_tools()
    return {
        "feature": "8_gemini_daily_brief_generation_and_mcp_research_tools",
        "count": len(tools),
        "tools": tools,
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.post("/mcp/call")
def post_investment_mcp_call_endpoint(body: InvestmentMCPCallInput) -> dict[str, Any]:
    try:
        return call_investment_mcp_tool(
            body.tool,
            body.params,
            tenant_id=body.tenant_id,
            role=body.role,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/preferences")
def get_preferences_endpoint(tenant_id: str = Query(default="default_workspace")) -> dict[str, Any]:
    led = get_investment_ledger()
    return led.get_user_preferences(tenant_id=tenant_id)


@router.post("/preferences")
def post_preferences_endpoint(body: PreferencesUpdateInput) -> dict[str, Any]:
    led = get_investment_ledger()
    return led.update_user_preferences(
        tenant_id=body.tenant_id,
        preferred_currency=body.preferred_currency,
        timezone_name=body.timezone_name,
        watchlist_symbols=body.watchlist_symbols,
        research_interests=body.research_interests,
        schedule_cron=body.schedule_cron,
        delivery_channel=body.delivery_channel,
        notification_opt_in=body.notification_opt_in,
    )


@router.get("/archive")
def get_archive_endpoint(
    tenant_id: str = Query(default="default_workspace"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    led = get_investment_ledger()
    items = led.list_archived_briefs(tenant_id=tenant_id, limit=limit)
    return {
        "feature": "9_daily_brief_user_experience_delivery_and_personalization",
        "tenant_id": tenant_id,
        "count": len(items),
        "archived_briefs": items,
        "execution_permission": EXECUTION_PERMISSION,
    }


@router.get("/compliance")
def get_compliance_endpoint(tenant_id: str = Query(default="default_workspace")) -> dict[str, Any]:
    return build_investment_compliance_and_security_report(tenant_id=tenant_id)


@router.get("/pilot")
@router.post("/pilot")
def run_pilot_endpoint(
    tenant_id: str = Query(default="pilot_contrainer_master"),
    reporting_date: str = Query(default="2026-10-26"),
) -> dict[str, Any]:
    return run_end_to_end_pilot(tenant_id=tenant_id, reporting_date=reporting_date)

