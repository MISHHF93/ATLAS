"""ContrainerMaster / ATLAS — AI Daily Investment Intelligence System (10 Vertical Features).

1. `ledger`: Canonical Investment Portfolio and Transaction Ledger (`cm_investment_accounts`, `cm_investment_transactions`)
2. `yesterday_brief`: Yesterday's Investment Activity Brief (NYSE/TSX calendar, T+1 settlement, epistemic separation)
3. `today_brief`: Today's AI Investment Brief & Point-in-Time Historical Regeneration
4. `market_data`: Historical Market Data & Verified Asset Intelligence (point-in-time bars, USD/CAD, benchmarks)
5. `multifactor_ratings`: Transparent Multifactor Asset Ratings (`atlas-multifactor-v2.1`, asset-class-specific pillars)
6. `ml_forecasting`: Machine Learning Research & Forecasting (`atlas-wf-ensemble-v2.4`, 3 baselines vs calibrated ensemble)
7. `portfolio_analytics`: Portfolio Risk, Performance & Attribution (TWR, MWR/XIRR, NAV bridge, VaR/CVaR, stress scenarios)
8. `mcp_research_tools`: 11 Governed MCP Research Tools with tenant isolation & prompt-injection defense
9. Daily Brief User Experience, Delivery & Personalization (`/trade?tab=brief` & `/trade?tab=markets`)
10. `compliance_and_pilot`: Canadian Compliance, Security, Testing, 10-Step Pilot & Release Governance
"""
from __future__ import annotations

from atlas.investment_intelligence.compliance_and_pilot import (
    INVESTMENT_INTELLIGENCE_RELEASE_GATES,
    InvestmentGovernanceGate,
    build_investment_compliance_and_security_report,
    run_end_to_end_pilot,
)
from atlas.investment_intelligence.ledger import (
    EPISTEMIC_CATEGORIES,
    EXECUTION_PERMISSION,
    POSTGRES_INVESTMENT_INTELLIGENCE_DDL,
    HoldingPosition,
    InvestmentPortfolioLedger,
    InvestmentTransactionRecord,
    compute_tx_dedup_hash,
    get_investment_ledger,
)
from atlas.investment_intelligence.market_data import (
    BENCHMARK_BY_ASSET_CLASS,
    get_historical_series,
    get_market_snapshot,
    get_point_in_time_usd_cad,
    load_point_in_time_bars,
    parse_cutoff_timestamp,
)
from atlas.investment_intelligence.mcp_research_tools import (
    INVESTMENT_INTELLIGENCE_MCP_TOOLS,
    InvestmentMCPToolSpec,
    call_investment_mcp_tool,
    detect_prompt_injection,
    list_investment_mcp_tools,
)
from atlas.investment_intelligence.ml_forecasting import (
    ML_MODEL_VERSION,
    batch_ml_forecasts,
    compute_psi_drift,
    forecast_symbol_ml,
)
from atlas.investment_intelligence.multifactor_ratings import (
    RATING_METHODOLOGY_VERSION,
    batch_multifactor_ratings,
    compute_asset_multifactor_rating,
)
from atlas.investment_intelligence.portfolio_analytics import (
    compute_mwr_xirr,
    compute_portfolio_risk_and_performance,
    compute_twr_subperiods,
)
from atlas.investment_intelligence.today_brief import (
    generate_full_daily_intelligence_brief,
    get_research_catalysts,
)
from atlas.investment_intelligence.yesterday_brief import (
    NORTH_AMERICAN_MARKET_HOLIDAYS,
    build_yesterday_investment_activity_brief,
    is_trading_day,
    next_trading_day,
    previous_trading_day,
)

__all__ = [
    "BENCHMARK_BY_ASSET_CLASS",
    "EPISTEMIC_CATEGORIES",
    "EXECUTION_PERMISSION",
    "HoldingPosition",
    "INVESTMENT_INTELLIGENCE_MCP_TOOLS",
    "INVESTMENT_INTELLIGENCE_RELEASE_GATES",
    "InvestmentGovernanceGate",
    "InvestmentMCPToolSpec",
    "InvestmentPortfolioLedger",
    "InvestmentTransactionRecord",
    "ML_MODEL_VERSION",
    "NORTH_AMERICAN_MARKET_HOLIDAYS",
    "POSTGRES_INVESTMENT_INTELLIGENCE_DDL",
    "RATING_METHODOLOGY_VERSION",
    "batch_ml_forecasts",
    "batch_multifactor_ratings",
    "build_investment_compliance_and_security_report",
    "build_yesterday_investment_activity_brief",
    "call_investment_mcp_tool",
    "compute_asset_multifactor_rating",
    "compute_mwr_xirr",
    "compute_portfolio_risk_and_performance",
    "compute_psi_drift",
    "compute_twr_subperiods",
    "compute_tx_dedup_hash",
    "detect_prompt_injection",
    "forecast_symbol_ml",
    "generate_full_daily_intelligence_brief",
    "get_historical_series",
    "get_investment_ledger",
    "get_market_snapshot",
    "get_point_in_time_usd_cad",
    "get_research_catalysts",
    "is_trading_day",
    "list_investment_mcp_tools",
    "load_point_in_time_bars",
    "next_trading_day",
    "parse_cutoff_timestamp",
    "previous_trading_day",
    "run_end_to_end_pilot",
]

