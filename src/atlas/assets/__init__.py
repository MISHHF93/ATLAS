"""ATLAS Authentic Assets Catalog — 10 Vertical Features Package.

1. `master`: Canonical Asset Master (SQLite & PostgreSQL/Drizzle schema + normalized entities)
2. `precious_metals`: Precious Metals Catalog (Gold, Silver, Platinum, Palladium across 7 holding forms)
3. `etf_intelligence`: ETF and Fund Intelligence (47 verified US & Canadian ETFs with ISIN/CUSIP/MER/NAV provenance)
4. `equities_bonds_cash`: Public Equities, Sovereign/Corporate Bonds, and Cash Equivalents (T-Bills/CORRA)
5. `connectors`: Authorized Market-Data Connectors & live SQLite feed store health audit
6. `authenticity`: Instrument Authenticity & Data Quality (ISO 6166 ISIN, CUSIP, LEI, SEC CIK, MIC checksums & cross-provider reconciliation)
7. `canadian_compliance`: Canadian Regulatory & Commercial Gates (CSA NI 31-103, NI 21-101, NI 81-102, NI 93-101, FINTRAC, PIPEDA/Law 25)
8. Unified Asset Discovery Experience (served via `/api/assets/*` & `/trade?tab=markets`)
9. `mcp_tools`: Governed Gemini AI & MCP Read-Only Asset Capabilities (`execution_permission="none"`)
10. Independent Testing & Release Readiness Report
"""

from atlas.assets.authenticity import (
    AUTHENTICITY_VS_SAFETY_DISCLOSURE,
    KNOWN_UNLISTED_PRIVATE_ENTITIES,
    VALID_ISO10383_MICS,
    VALID_ISO4217_CODES,
    AuthenticityVerificationReport,
    compute_cusip_check_digit,
    compute_isin_check_digit,
    detect_corporate_action_or_split_flags,
    make_cusip,
    make_isin,
    make_lei,
    reconcile_instrument_sources,
    validate_cusip,
    validate_isin,
    validate_lei,
    validate_sec_cik,
    verify_instrument_authenticity,
)
from atlas.assets.canadian_compliance import (
    CANADIAN_REGULATORY_GATES,
    CanadianRegulatoryGate,
    build_canadian_compliance_report,
    evaluate_canadian_regulatory_gate,
)
from atlas.assets.connectors import (
    AUTHORIZED_MARKET_DATA_CONNECTORS,
    AuthorizedMarketDataConnector,
    audit_market_data_connectors,
)
from atlas.assets.equities_bonds_cash import (
    BONDS_AND_FIXED_INCOME_CATALOG,
    CASH_EQUIVALENTS_CATALOG,
    FLAGSHIP_PUBLIC_EQUITIES,
    BondAndFixedIncomeSpec,
    CashEquivalentSpec,
    PublicEquitySpec,
    build_equities_bonds_cash_catalog,
)
from atlas.assets.etf_intelligence import (
    ETFS_BY_SYMBOL,
    ETF_INTELLIGENCE_CATALOG,
    ETFFundRecord,
    NI_81_102_ETF_DISCLOSURE,
    get_etf_fund_details,
    list_etf_intelligence,
)
from atlas.assets.master import (
    ASSET_CLASSES,
    POSTGRES_CANONICAL_ASSET_MASTER_DDL,
    AssetClassRecord,
    CanonicalAssetMaster,
    CanonicalInstrument,
    CurrencyRecord,
    ExchangeVenueRecord,
    IdentifierBundle,
    IssuerRecord,
    SourceProvenance,
    get_canonical_asset_master,
)
from atlas.assets.mcp_tools import (
    GOVERNED_ASSET_MCP_TOOLS,
    GovernedMCPToolSpec,
    call_governed_mcp_tool,
    list_governed_mcp_tools,
)
from atlas.assets.precious_metals import (
    KG_TO_TROY_OZ,
    METALS_BY_SYMBOL,
    PRECIOUS_METAL_INSTRUMENTS,
    TROY_OZ_TO_GRAMS,
    PreciousMetalInstrumentSpec,
    build_precious_metals_catalog,
    normalize_metal_price,
)

__all__ = [
    "ASSET_CLASSES",
    "AUTHENTICITY_VS_SAFETY_DISCLOSURE",
    "AUTHORIZED_MARKET_DATA_CONNECTORS",
    "AssetClassRecord",
    "AuthenticityVerificationReport",
    "AuthorizedMarketDataConnector",
    "BONDS_AND_FIXED_INCOME_CATALOG",
    "BondAndFixedIncomeSpec",
    "CANADIAN_REGULATORY_GATES",
    "CASH_EQUIVALENTS_CATALOG",
    "CanadianRegulatoryGate",
    "CanonicalAssetMaster",
    "CanonicalInstrument",
    "CashEquivalentSpec",
    "CurrencyRecord",
    "ETFFundRecord",
    "ETFS_BY_SYMBOL",
    "ETF_INTELLIGENCE_CATALOG",
    "ExchangeVenueRecord",
    "FLAGSHIP_PUBLIC_EQUITIES",
    "GOVERNED_ASSET_MCP_TOOLS",
    "GovernedMCPToolSpec",
    "IdentifierBundle",
    "IssuerRecord",
    "KG_TO_TROY_OZ",
    "KNOWN_UNLISTED_PRIVATE_ENTITIES",
    "METALS_BY_SYMBOL",
    "NI_81_102_ETF_DISCLOSURE",
    "POSTGRES_CANONICAL_ASSET_MASTER_DDL",
    "PRECIOUS_METAL_INSTRUMENTS",
    "PreciousMetalInstrumentSpec",
    "PublicEquitySpec",
    "SourceProvenance",
    "TROY_OZ_TO_GRAMS",
    "VALID_ISO10383_MICS",
    "VALID_ISO4217_CODES",
    "audit_market_data_connectors",
    "build_canadian_compliance_report",
    "build_equities_bonds_cash_catalog",
    "build_precious_metals_catalog",
    "call_governed_mcp_tool",
    "compute_cusip_check_digit",
    "compute_isin_check_digit",
    "detect_corporate_action_or_split_flags",
    "evaluate_canadian_regulatory_gate",
    "get_canonical_asset_master",
    "get_etf_fund_details",
    "list_etf_intelligence",
    "list_governed_mcp_tools",
    "make_cusip",
    "make_isin",
    "make_lei",
    "normalize_metal_price",
    "reconcile_instrument_sources",
    "validate_cusip",
    "validate_isin",
    "validate_lei",
    "validate_sec_cik",
    "verify_instrument_authenticity",
]

