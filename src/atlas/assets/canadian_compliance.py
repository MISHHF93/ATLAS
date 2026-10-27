"""Feature 7 — Canadian Regulatory and Commercial Gates.

Evaluates and enforces Canadian securities, derivatives, non-custodial boundary,
AML, privacy, and commercial market-data licensing gates across the ATLAS
Authentic Assets Catalog:

1. CSA / OSC / CIRO National Instrument 31-103 (NI 31-103) — Registration
   Requirements, Exemptions and Ongoing Registrant Obligations:
   - Blocks personalized investment advice, suitability determinations, and
     live order execution unless performed by a duly registered Dealer or
     Adviser.
   - Permits objective, factual market data, educational research, and
     deterministic paper-trading simulation with `execution_permission="none"`.
2. CSA / CIRO National Instrument 21-101 & 23-101 (Marketplace Operation &
   Trading Rules / UMIR):
   -ATLAS is an internal quantitative research and paper-simulation workspace,
     not a Marketplace, Alternative Trading System (ATS), or order router.
3. CSA National Instrument 81-102 & 41-101 (Investment Funds, ETFs, and ETRs):
   - Requires clear separation of NAV vs. secondary market price, expense
     ratios (MER/bps), underlying exposure, and Fund Facts / ETF Facts
     provenance for Canadian-listed and US-listed ETFs and Royal Canadian Mint
     ETRs (`MNT.TO`, `MNS.TO`).
4. CSA National Instrument 93-101 (Derivatives Business Conduct), OSC Rule
   91-502, and Quebec Derivatives Act (CQLR c I-14.01):
   - Requires explicit leverage, margin, and expiry disclosures on futures
     contracts (`GC`, `MGC`, `SI`, `PL`, `PA`, `CL`, `ES`, `NQ`, `ZN`, `ZB`)
     and blocks live derivatives order routing.
5. NI 31-103 Part 14 — Non-Custodial Client Asset Boundary:
   - ATLAS never accepts, holds, or controls client cash, securities, physical
     bullion, or private keys.
6. PCMLTFA / FINTRAC — Anti-Money Laundering & Sanctions Boundary:
   - Because ATLAS is strictly non-custodial and performs zero money
     transmission or virtual-currency exchange, MSB money-transmission flows
     are disabled by architecture.
7. PIPEDA & Quebec Law 25 — Privacy & Data Governance Gate:
   - No collection of retail investor PII, SINs, or brokerage credentials in
     public telemetry or AI prompts.
8. Commercial Market-Data Licensing & Redistribution Gate:
   - Enforces `ATLAS_ALLOW_PAID_DATA=false` by default and blocks unauthorized
     public redistribution of proprietary exchange feeds (TMX Datalinx, CME
     Group, NYSE, Nasdaq, ICE).
9. Active Roadmap Scope Gate (Speculative Token-Launch Decommissioning):
   - Excludes unverified bonding-curve token launches (`pump_fun`, `pumpswap`)
     from active navigation and automated trading based on objective
     market-structure, issuer-disclosure, and liquidity-concentration criteria,
     without making unsubstantiated legal accusations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CanadianRegulatoryGate:
    gate_id: str
    title: str
    regulator_authority: str
    statutory_instrument: str
    jurisdiction: str
    status: str  # "enforced" | "permitted_with_disclosure" | "blocked_in_production"
    permitted_capabilities: tuple[str, ...]
    prohibited_capabilities: tuple[str, ...]
    technical_control: str
    required_user_disclosure: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["permitted_capabilities"] = list(self.permitted_capabilities)
        d["prohibited_capabilities"] = list(self.prohibited_capabilities)
        return d


CANADIAN_REGULATORY_GATES: tuple[CanadianRegulatoryGate, ...] = (
    CanadianRegulatoryGate(
        gate_id="CSA_NI_31_103_ADVISER_DEALER",
        title="Adviser & Dealer Registration Boundary (NI 31-103)",
        regulator_authority="Canadian Securities Administrators (CSA) / OSC / CIRO",
        statutory_instrument="National Instrument 31-103 — Registration Requirements, Exemptions and Ongoing Registrant Obligations",
        jurisdiction="CA (All Provinces & Territories)",
        status="enforced",
        permitted_capabilities=(
            "Objective factual catalog of verified financial instruments",
            "Historical OHLCV charting and statistical indicator calculation",
            "Deterministic paper-trading simulation with virtual balances",
            "Read-only AI/MCP instrument lookup with execution_permission='none'",
        ),
        prohibited_capabilities=(
            "Personalized investment recommendations or suitability assessments (NI 31-103 s. 13.3)",
            "Soliciting or routing live client securities orders as an unregistered Dealer",
            "Discretionary portfolio management for retail or institutional clients",
        ),
        technical_control=(
            "AI/ML nodes and MCP tools enforce `execution_permission='none'` and "
            "`personalized_advice=False`; live Alpaca brokerage endpoints are refused at configuration load."
        ),
        required_user_disclosure=(
            "ATLAS is a quantitative market research and paper-trading simulation platform. "
            "It is not registered as an Investment Dealer, Portfolio Manager, or Adviser under "
            "CSA National Instrument 31-103. Nothing in ATLAS constitutes personalized investment, "
            "legal, or tax advice."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="CSA_NI_21_101_MARKETPLACE_UMIR",
        title="Marketplace Operation & CIRO UMIR Order-Routing Gate",
        regulator_authority="CSA / Canadian Investment Regulatory Organization (CIRO)",
        statutory_instrument="National Instrument 21-101 (Marketplace Operation), NI 23-101 (Trading Rules), and CIRO UMIR",
        jurisdiction="CA",
        status="enforced",
        permitted_capabilities=(
            "Single-user local paper-order book simulation",
            "Deterministic risk-policy evaluation in paper mode",
        ),
        prohibited_capabilities=(
            "Operating an Alternative Trading System (ATS) or matching orders between multiple parties",
            "Direct Electronic Access (DEA) routing to TSX, TSXV, Cboe Canada, or CSE without a CIRO Participant Dealer",
        ),
        technical_control=(
            "Execution engine restricts order placement to local simulated paper ledger; "
            "no FIX/OUCH/STAMP live exchange sessions exist."
        ),
        required_user_disclosure=(
            "Simulated paper orders are evaluated locally against historical or delayed reference "
            "data and are never transmitted to any stock exchange or ATS."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="CSA_NI_81_102_INVESTMENT_FUNDS_ETF",
        title="Investment Funds, ETFs & Precious Metal Certificates Disclosure Gate",
        regulator_authority="CSA / OSC / AMF",
        statutory_instrument="National Instrument 81-102 (Investment Funds) & NI 41-101 (General Prospectus Requirements)",
        jurisdiction="CA / US Cross-Border",
        status="permitted_with_disclosure",
        permitted_capabilities=(
            "Displaying verified ETF issuer, ISIN/CUSIP, exchange MIC, MER/expense ratio (bps), and underlying index",
            "Distinguishing secondary-market share price from end-of-day Net Asset Value (NAV)",
            "Documenting Royal Canadian Mint ETR (MNT.TO, MNS.TO) and Sprott Physical Trust (PHYS, PSLV, SPPP) custody terms",
        ),
        prohibited_capabilities=(
            "Fabricating intraday NAV when only secondary-market prices are available",
            "Presenting management expense ratios or distribution yields as guaranteed returns",
            "Equating unallocated bullion accounts or futures with direct allocated physical title",
        ),
        technical_control=(
            "`ETFProfile.nav_provenance` explicitly labels whether live feeds supply secondary-market "
            "trade prices vs. official issuer EOD NAV; `PreciousMetalInstrument` enforces distinct "
            "`holding_form` and `counterparty_disclosure` fields."
        ),
        required_user_disclosure=(
            "Exchange-traded funds (ETFs) and Exchange-Traded Receipts (ETRs) are subject to management "
            "expenses, tracking error, and market bid-ask spreads. Investors should review official "
            "SEDAR+ ETF Facts / Fund Facts or SEC Form N-1A prospectuses before making investment decisions."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="CSA_NI_93_101_DERIVATIVES_FUTURES",
        title="Derivatives Business Conduct & Futures Risk Gate",
        regulator_authority="CSA / OSC / Autorité des marchés financiers (AMF Quebec)",
        statutory_instrument="National Instrument 93-101 (Derivatives: Business Conduct), OSC Rule 91-502, Quebec Derivatives Act",
        jurisdiction="CA",
        status="permitted_with_disclosure",
        permitted_capabilities=(
            "Displaying CME/COMEX/NYMEX/CBOT futures contract specifications (GC, MGC, SI, PL, PA, CL, ES, NQ, ZN, ZB)",
            "Simulating futures price sensitivity and contract multipliers in paper-research mode",
        ),
        prohibited_capabilities=(
            "Live retail derivatives dealing or margin collection without CIRO Futures Commission Merchant (FCM) registration",
            "Offering over-the-counter (OTC) contracts for difference (CFDs) or binary options to Canadian residents",
        ),
        technical_control=(
            "All futures instruments carry explicit contract-multiplier and roll/margin risk disclosures; "
            "OTC CFDs and binary options are excluded from `CanonicalAssetMaster`."
        ),
        required_user_disclosure=(
            "Futures contracts involve substantial leverage and roll risk and are displayed in ATLAS "
            "solely as macro and commodity price benchmarks."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="CSA_NI_31_103_PART_14_NON_CUSTODIAL",
        title="Non-Custodial Client Asset Boundary (NI 31-103 Part 14)",
        regulator_authority="CSA / CIRO / CIPF Boundary",
        statutory_instrument="National Instrument 31-103 Part 14 — Handling and Safeguarding Client Cash and Securities",
        jurisdiction="CA",
        status="enforced",
        permitted_capabilities=(
            "Tracking virtual paper-portfolio positions and simulated cash balances",
        ),
        prohibited_capabilities=(
            "Accepting deposits, holding client cash, custodying physical bullion, or storing live signing keys in public sessions",
        ),
        technical_control=(
            "Zero deposit/withdrawal rails exist; wallet signing and live brokerage credentials are disabled."
        ),
        required_user_disclosure=(
            "ATLAS is strictly non-custodial and never holds client funds, securities, or bullion."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="FINTRAC_PCMLTFA_AML_BOUNDARY",
        title="FINTRAC / PCMLTFA Anti-Money Laundering & Sanctions Boundary",
        regulator_authority="Financial Transactions and Reports Analysis Centre of Canada (FINTRAC)",
        statutory_instrument="Proceeds of Crime (Money Laundering) and Terrorist Financing Act (PCMLTFA)",
        jurisdiction="CA",
        status="enforced",
        permitted_capabilities=(
            "Read-only market data analytics on benchmark digital assets (BTC, ETH, SOL) from regulated venues",
        ),
        prohibited_capabilities=(
            "Money transferring, fiat-to-crypto exchange, or anonymous token-launch dealing",
        ),
        technical_control=(
            "No value transfer or peer-to-peer swap execution is enabled in production."
        ),
        required_user_disclosure=(
            "ATLAS does not operate as a Money Services Business (MSB) or virtual-currency exchange."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="PIPEDA_QUEBEC_LAW_25_PRIVACY",
        title="PIPEDA & Quebec Law 25 Privacy Protection Gate",
        regulator_authority="Office of the Privacy Commissioner of Canada (OPC) / CAI Quebec",
        statutory_instrument="Personal Information Protection and Electronic Documents Act (PIPEDA) & Quebec Law 25",
        jurisdiction="CA / QC",
        status="enforced",
        permitted_capabilities=(
            "Local workspace preferences (watchlist symbols, currency USD/CAD toggle, unit preferences)",
        ),
        prohibited_capabilities=(
            "Transmitting client financial PII, Social Insurance Numbers (SIN), or secret API keys to external LLM endpoints",
        ),
        technical_control=(
            "MCP asset tools accept only public ticker/ISIN/category parameters and log sanitized "
            "audit records to `var/ai/audit.jsonl`."
        ),
        required_user_disclosure=(
            "No personal financial identity data is transmitted to external market-data or AI providers."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="COMMERCIAL_MARKET_DATA_LICENSING",
        title="Commercial Exchange & Vendor Market-Data Licensing Gate",
        regulator_authority="TMX Datalinx / CME Group / NYSE / Nasdaq / Cboe / ICE",
        statutory_instrument="Exchange Market Data Subscriber & Redistribution Agreements",
        jurisdiction="CA / US / Global",
        status="enforced",
        permitted_capabilities=(
            "Ingesting public regulatory/central-bank series (Bank of Canada Valet, SEC EDGAR, ECB, FRED)",
            "Displaying local historical SQLite bars (`var/feeds/atlas_feed.sqlite`) with explicit source & freshness attribution",
        ),
        prohibited_capabilities=(
            "Public multi-tenant redistribution of real-time exchange order books without a commercial distributor license",
            "Silent fallback to paid vendor tiers when `ATLAS_ALLOW_PAID_DATA=false`",
        ),
        technical_control=(
            "`ATLAS_ALLOW_PAID_DATA=false` enforced in `src/atlas/integrations/registry.py`; "
            "every quote/bar carries `source`, `freshness`, and `redistribution_policy` metadata."
        ),
        required_user_disclosure=(
            "Market data is provided for single-workspace research and paper-simulation use only "
            "and may be delayed depending on venue entitlements."
        ),
    ),
    CanadianRegulatoryGate(
        gate_id="PRODUCT_ROADMAP_SPECULATIVE_TOKEN_EXCLUSION",
        title="Active Roadmap Scope Gate — Speculative Token-Launch Exclusion",
        regulator_authority="ATLAS Product Governance & Risk Committee / CSA Staff Notice 21-327",
        statutory_instrument="Internal Product Risk Policy & CSA Guidance on Crypto-Asset Trading Platforms",
        jurisdiction="CA / Global",
        status="enforced",
        permitted_capabilities=(
            "Maintaining read-only historical replay/audit tests for regression verification",
        ),
        prohibited_capabilities=(
            "Displaying Pump.fun or unverified bonding-curve token launches in active navigation",
            "Automated trading, wallet signing, or capital allocation to unverified meme-token launches",
        ),
        technical_control=(
            "`pump_fun` and `solana_rpc` services have `default_on=False` in `integrations/registry.py`; "
            "`/trade?tab=pump` redirects to `/trade?tab=markets`; `pump_api.py` marks roadmap status "
            "as `disabled_by_product_policy`."
        ),
        required_user_disclosure=(
            "Unverified bonding-curve token launches exhibit extreme volatility, concentrated "
            "liquidity risk, and absence of standardized issuer disclosures, and are excluded "
            "from the active ATLAS product roadmap in favor of verified financial instruments."
        ),
    ),
)


_PROHIBITED_ACTIONS = {
    "live_order_execution": "CSA_NI_31_103_ADVISER_DEALER",
    "personalized_investment_advice": "CSA_NI_31_103_ADVISER_DEALER",
    "client_asset_custody": "CSA_NI_31_103_PART_14_NON_CUSTODIAL",
    "public_quote_redistribution": "COMMERCIAL_MARKET_DATA_LICENSING",
    "pump_fun_live_trading": "PRODUCT_ROADMAP_SPECULATIVE_TOKEN_EXCLUSION",
    "otc_cfd_or_binary_option": "CSA_NI_93_101_DERIVATIVES_FUTURES",
}

_PERMITTED_ACTIONS = {
    "catalog_lookup": "CSA_NI_31_103_ADVISER_DEALER",
    "historical_charting": "CSA_NI_31_103_ADVISER_DEALER",
    "paper_trading_simulation": "CSA_NI_21_101_MARKETPLACE_UMIR",
    "etf_disclosure_inspection": "CSA_NI_81_102_INVESTMENT_FUNDS_ETF",
    "precious_metals_comparison": "CSA_NI_81_102_INVESTMENT_FUNDS_ETF",
    "mcp_read_only_query": "CSA_NI_31_103_ADVISER_DEALER",
}


def evaluate_canadian_regulatory_gate(
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically evaluate whether an action is permitted under Canadian regulatory gates."""
    norm_action = (action or "").strip().lower()
    payload = payload or {}
    gate_by_id = {g.gate_id: g for g in CANADIAN_REGULATORY_GATES}

    # Check if payload attempts to bypass execution_permission or use live endpoints
    if payload.get("execution_permission") not in (None, "none"):
        gate = gate_by_id["CSA_NI_31_103_ADVISER_DEALER"]
        return {
            "action": norm_action,
            "allowed": False,
            "gate_id": gate.gate_id,
            "statutory_instrument": gate.statutory_instrument,
            "reason": "Non-none execution_permission is prohibited on research/AI surfaces.",
            "required_disclosure": gate.required_user_disclosure,
            "execution_permission": "none",
        }

    if norm_action in _PROHIBITED_ACTIONS:
        gate_id = _PROHIBITED_ACTIONS[norm_action]
        gate = gate_by_id[gate_id]
        return {
            "action": norm_action,
            "allowed": False,
            "gate_id": gate.gate_id,
            "statutory_instrument": gate.statutory_instrument,
            "reason": f"Action '{norm_action}' is blocked by {gate.title} ({gate.statutory_instrument}).",
            "required_disclosure": gate.required_user_disclosure,
            "execution_permission": "none",
        }

    gate_id = _PERMITTED_ACTIONS.get(norm_action, "CSA_NI_31_103_ADVISER_DEALER")
    gate = gate_by_id[gate_id]
    return {
        "action": norm_action or "catalog_lookup",
        "allowed": True,
        "gate_id": gate.gate_id,
        "statutory_instrument": gate.statutory_instrument,
        "reason": f"Permitted in read-only research / paper-simulation mode under {gate.title}.",
        "required_disclosure": gate.required_user_disclosure,
        "execution_permission": "none",
    }


def build_canadian_compliance_report() -> dict[str, Any]:
    """Return the complete Canadian regulatory & commercial compliance posture report."""
    return {
        "jurisdiction": "Canada (CSA / OSC / AMF / CIRO / FINTRAC / PIPEDA)",
        "platform_posture": "non_custodial_research_and_paper_simulation",
        "execution_permission": "none",
        "paid_data_enabled": False,
        "speculative_token_launches_active": False,
        "total_gates": len(CANADIAN_REGULATORY_GATES),
        "gates": [g.to_dict() for g in CANADIAN_REGULATORY_GATES],
    }

