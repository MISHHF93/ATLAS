"""Feature 8 — Gemini Daily Brief Generation and MCP Research Tools.

Implements the 11 governed, read-only Model Context Protocol (MCP) tools for
ContrainerMaster / ATLAS Daily Investment Intelligence:

1.  `portfolio.get_holdings`
2.  `portfolio.get_transactions`
3.  `portfolio.get_yesterday_activity`
4.  `portfolio.get_performance`
5.  `markets.get_snapshot`
6.  `markets.get_history`
7.  `assets.get_rating`
8.  `research.get_catalysts`
9.  `models.get_forecast`
10. `risk.get_exposures`
11. `briefs.generate_daily`

Every tool enforces:
- `execution_permission == "none"` (READ-only, no autonomous trading or order submission)
- Strict tenant authorization (`tenant_id`) and role verification
- Prompt-injection detection & sanitization (`detect_prompt_injection`)
- Explicit provenance, methodology/model versions, and uncertainty disclosures
- Append-only audit logging to `var/ai/audit.jsonl`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any

from atlas.ai.node import audit as ai_audit
from atlas.investment_intelligence.ledger import (
    EXECUTION_PERMISSION,
    InvestmentPortfolioLedger,
    get_investment_ledger,
)
from atlas.investment_intelligence.market_data import (
    get_historical_series,
    get_market_snapshot,
    get_point_in_time_usd_cad,
)
from atlas.investment_intelligence.ml_forecasting import (
    ML_MODEL_VERSION,
    forecast_symbol_ml,
)
from atlas.investment_intelligence.multifactor_ratings import (
    RATING_METHODOLOGY_VERSION,
    compute_asset_multifactor_rating,
)
from atlas.investment_intelligence.portfolio_analytics import (
    compute_portfolio_risk_and_performance,
)
from atlas.investment_intelligence.today_brief import (
    generate_full_daily_intelligence_brief,
    get_research_catalysts,
)
from atlas.investment_intelligence.yesterday_brief import (
    build_yesterday_investment_activity_brief,
)

ALLOWED_ROLES = frozenset({"researcher", "auditor", "compliance", "founder", "viewer", "prop_firm_admin"})

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions", re.IGNORECASE),
    re.compile(r"override\s+execution[_\s]?permission", re.IGNORECASE),
    re.compile(r"submit\s+live\s+(broker|alpaca)\s+order", re.IGNORECASE),
    re.compile(r"fabricate\s+(market\s+)?price", re.IGNORECASE),
    re.compile(r"bypass\s+(tenant|ni[\s-]?31[\s-]?103|risk)\s+(isolation|gate|control)", re.IGNORECASE),
    re.compile(r"DROP\s+TABLE|DELETE\s+FROM\s+cm_investment", re.IGNORECASE),
)


def detect_prompt_injection(payload: Any) -> tuple[bool, str | None]:
    """Recursively inspect MCP arguments or user prompts for prompt-injection or SQL/execution override attempts."""
    if isinstance(payload, str):
        for pat in _INJECTION_PATTERNS:
            m = pat.search(payload)
            if m:
                return True, f"Blocked adversarial pattern: '{m.group(0)}'"
        return False, None
    if isinstance(payload, dict):
        for k, v in payload.items():
            flagged, reason = detect_prompt_injection(str(k))
            if flagged:
                return True, reason
            flagged, reason = detect_prompt_injection(v)
            if flagged:
                return True, reason
        return False, None
    if isinstance(payload, (list, tuple)):
        for item in payload:
            flagged, reason = detect_prompt_injection(item)
            if flagged:
                return True, reason
        return False, None
    return False, None


@dataclass(frozen=True)
class InvestmentMCPToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    execution_permission: str = EXECUTION_PERMISSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


INVESTMENT_INTELLIGENCE_MCP_TOOLS: tuple[InvestmentMCPToolSpec, ...] = (
    InvestmentMCPToolSpec(
        name="portfolio.get_holdings",
        description="Return tenant-scoped verified portfolio holdings, cost basis, market value (USD/CAD), and cash balances.",
        input_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": "string", "description": "Optional YYYY-MM-DD point-in-time cutoff"},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="portfolio.get_transactions",
        description="Return tenant-scoped append-only transaction history with trade/settlement dates, fees, and verification status.",
        input_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": "string"},
                "symbol": {"type": "string"},
                "include_superseded": {"type": "boolean", "default": False},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="portfolio.get_yesterday_activity",
        description="Generate Yesterday's Investment Activity Brief separating confirmed transactions from market movements and open orders.",
        input_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": "string"},
                "timezone": {"type": "string", "default": "America/Toronto"},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="portfolio.get_performance",
        description="Compute Time-Weighted Return (TWR), Money-Weighted Return (MWR), NAV attribution bridge, and benchmark comparisons.",
        input_schema={
            "type": "object",
            "properties": {"as_of_date": {"type": "string"}},
        },
    ),
    InvestmentMCPToolSpec(
        name="markets.get_snapshot",
        description="Retrieve point-in-time market snapshot across equities, ETFs, precious metals, bonds, T-Bills, FX, and crypto.",
        input_schema={
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"}},
                "as_of_date": {"type": "string"},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="markets.get_history",
        description="Retrieve point-in-time adjusted historical bar series and benchmark mapping for a symbol.",
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "default": "1d"},
                "as_of_date": {"type": "string"},
                "limit": {"type": "integer", "default": 90},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="assets.get_rating",
        description="Compute transparent multifactor asset rating (v2.1) with asset-class-specific pillars and historical comparison.",
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "as_of_date": {"type": "string"},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="research.get_catalysts",
        description="Retrieve upcoming macroeconomic announcements, central-bank rate schedules, ETF distributions, and SEC filing catalysts.",
        input_schema={
            "type": "object",
            "properties": {
                "symbols": {"type": "array", "items": {"type": "string"}},
                "as_of_date": {"type": "string"},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="models.get_forecast",
        description="Run point-in-time purged walk-forward ML forecast (v2.4) comparing 3 baselines against calibrated ensemble.",
        input_schema={
            "type": "object",
            "required": ["symbol"],
            "properties": {
                "symbol": {"type": "string"},
                "as_of_date": {"type": "string"},
                "horizon_days": {"type": "integer", "default": 5},
            },
        },
    ),
    InvestmentMCPToolSpec(
        name="risk.get_exposures",
        description="Return portfolio asset-class weights, USD/CAD currency exposure, HHI concentration, VaR/CVaR, and 4 stress scenarios.",
        input_schema={
            "type": "object",
            "properties": {"as_of_date": {"type": "string"}},
        },
    ),
    InvestmentMCPToolSpec(
        name="briefs.generate_daily",
        description="Generate and archive the complete AI Daily Investment Intelligence Brief with point-in-time cutoff and epistemic tags.",
        input_schema={
            "type": "object",
            "properties": {
                "as_of_date": {"type": "string"},
                "timezone": {"type": "string", "default": "America/Toronto"},
                "symbols": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
)


def list_investment_mcp_tools() -> list[dict[str, Any]]:
    return [t.to_dict() for t in INVESTMENT_INTELLIGENCE_MCP_TOOLS]


def call_investment_mcp_tool(
    tool_name: str,
    params: dict[str, Any] | None = None,
    *,
    tenant_id: str = "default_workspace",
    role: str = "researcher",
    ledger: InvestmentPortfolioLedger | None = None,
) -> dict[str, Any]:
    """Execute one of the 11 governed Investment Intelligence MCP tools."""
    args = dict(params or {})

    # 1. Tenant & Role Authorization Check
    if not tenant_id or not str(tenant_id).strip():
        raise PermissionError("MCP tool invocation requires an explicit authenticated tenant_id")
    if role not in ALLOWED_ROLES:
        raise PermissionError(f"Role '{role}' is not authorized to invoke Investment Intelligence MCP tools")

    # Prevent cross-tenant override attempts inside args
    requested_tenant = args.get("tenant_id")
    if requested_tenant and str(requested_tenant).strip() != str(tenant_id).strip():
        ai_audit(
            "mcp_cross_tenant_blocked",
            {"tool": tool_name, "authenticated_tenant": tenant_id, "requested_tenant": requested_tenant},
        )
        raise PermissionError(f"Cross-tenant access denied: authenticated as '{tenant_id}', cannot read '{requested_tenant}'")

    # 2. Prompt-Injection Detection
    flagged, reason = detect_prompt_injection(args)
    if flagged:
        ai_audit("mcp_prompt_injection_blocked", {"tool": tool_name, "tenant_id": tenant_id, "reason": reason})
        return {
            "status": "refused",
            "error": "PROMPT_INJECTION_BLOCKED",
            "reason": reason,
            "tool": tool_name,
            "tenant_id": tenant_id,
            "read_only": True,
            "execution_permission": EXECUTION_PERMISSION,
        }

    led = ledger or get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=tenant_id)
    as_of_date = args.get("as_of_date")

    if tool_name == "portfolio.get_holdings":
        snap = get_market_snapshot(as_of_date=as_of_date)
        usd_cad = get_point_in_time_usd_cad(as_of_date=as_of_date)
        data = led.compute_portfolio_state(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            price_lookup=snap["quotes_by_symbol"],
            usd_cad_rate=usd_cad,
        )
    elif tool_name == "portfolio.get_transactions":
        txs = led.list_transactions(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            include_superseded=bool(args.get("include_superseded", False)),
            symbol=args.get("symbol"),
        )
        data = {
            "tenant_id": tenant_id,
            "as_of_date": as_of_date or "latest",
            "count": len(txs),
            "transactions": [t.as_dict() for t in txs],
        }
    elif tool_name == "portfolio.get_yesterday_activity":
        data = build_yesterday_investment_activity_brief(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            timezone_name=str(args.get("timezone") or "America/Toronto"),
            ledger=led,
        )
    elif tool_name == "portfolio.get_performance":
        data = compute_portfolio_risk_and_performance(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            ledger=led,
        )
    elif tool_name == "markets.get_snapshot":
        data = get_market_snapshot(symbols=args.get("symbols"), as_of_date=as_of_date)
    elif tool_name == "markets.get_history":
        sym = str(args.get("symbol") or "AAPL")
        data = get_historical_series(
            symbol=sym,
            timeframe=str(args.get("timeframe") or "1d"),
            as_of_date=as_of_date,
            limit=int(args.get("limit") or 90),
        )
    elif tool_name == "assets.get_rating":
        sym = str(args.get("symbol") or "AAPL")
        data = compute_asset_multifactor_rating(symbol=sym, as_of_date=as_of_date)
    elif tool_name == "research.get_catalysts":
        data = get_research_catalysts(symbols=args.get("symbols"), as_of_date=as_of_date)
    elif tool_name == "models.get_forecast":
        sym = str(args.get("symbol") or "AAPL")
        data = forecast_symbol_ml(
            symbol=sym,
            as_of_date=as_of_date,
            horizon_days=int(args.get("horizon_days") or 5),
        )
    elif tool_name == "risk.get_exposures":
        perf = compute_portfolio_risk_and_performance(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            ledger=led,
        )
        data = {
            "tenant_id": tenant_id,
            "as_of_date": perf["as_of_date"],
            "risk_and_exposure_metrics": perf["risk_and_exposure_metrics"],
            "stress_scenarios": perf["stress_scenarios"],
            "risk_alerts": perf["risk_alerts"],
        }
    elif tool_name == "briefs.generate_daily":
        data = generate_full_daily_intelligence_brief(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
            symbols=args.get("symbols"),
            timezone_name=str(args.get("timezone") or "America/Toronto"),
            ledger=led,
            archive_result=True,
        )
    else:
        raise KeyError(f"Unknown Investment Intelligence MCP tool: {tool_name}")

    envelope = {
        "status": "ok",
        "tool": tool_name,
        "tenant_id": tenant_id,
        "role": role,
        "invoked_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "personalized_advice": False,
        "rating_methodology_version": RATING_METHODOLOGY_VERSION,
        "model_version": ML_MODEL_VERSION,
        "uncertainty_disclosure": (
            "Deterministic financial calculations and governed research outputs only. "
            "No autonomous order execution (execution_permission='none'). Not personalized advice under NI 31-103."
        ),
        "data": data,
        "execution_permission": EXECUTION_PERMISSION,
    }
    ai_audit(
        "investment_mcp_tool_called",
        {"tool": tool_name, "tenant_id": tenant_id, "role": role, "as_of_date": as_of_date},
    )
    return envelope

