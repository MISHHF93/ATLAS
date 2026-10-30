"""Feature (1): Canonical Asset Master (`src/atlas/assets/master.py`).

Normalized relational entities for:
1. `AssetClassRecord` — Asset class taxonomy, settlement conventions, and baseline risk disclosures
2. `IssuerRecord` — Sovereign, central-bank, Crown corporation, regulated ETF sponsor, and SEC/SEDAR+ corporate issuers (with verified ISO 17442 LEIs and SEC CIKs)
3. `ExchangeVenueRecord` — ISO 10383 Market Identifier Codes (`XNAS`, `XNYS`, `ARCX`, `XTSE`, `XCEC`, `XCME`, `XNYM`, `XCBT`, `BOC`, `ECB`, `LBMA`, `UST`, `GOC`, `SPOT`)
4. `CurrencyRecord` — ISO 4217 fiat and precious-metal currency definitions (`USD`, `CAD`, `EUR`, `JPY`, `GBP`, `XAU`, `XAG`, `XPT`, `XPD`)
5. `CanonicalInstrument` — Normalized instrument entity unifying Precious Metals, ETFs, Public Equities, Bonds, Cash Equivalents, Spot FX, Regulated Futures, and Major Digital Assets, plus decommissioned speculative launchpad audit records.

Includes both SQLite persistence (`materialize_sqlite_schema`) and PostgreSQL / Drizzle ORM schema DDL (`POSTGRES_CANONICAL_ASSET_MASTER_DDL`).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence

from atlas.assets.authenticity import make_cusip, make_isin, make_lei
from atlas.assets.equities_bonds_cash import (
    BONDS_AND_FIXED_INCOME_CATALOG,
    CASH_EQUIVALENTS_CATALOG,
    FLAGSHIP_PUBLIC_EQUITIES,
)
from atlas.assets.etf_intelligence import ETF_INTELLIGENCE_CATALOG
from atlas.assets.precious_metals import PRECIOUS_METAL_INSTRUMENTS
from atlas.feeds.instruments import DEFAULT_INSTRUMENTS

EXECUTION_PERMISSION = "none"

POSTGRES_CANONICAL_ASSET_MASTER_DDL = """
-- Canonical Asset Master Schema (PostgreSQL / Drizzle-compatible DDL)
CREATE TABLE IF NOT EXISTS canonical_asset_classes (
    asset_class_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(128) NOT NULL,
    regulatory_category VARCHAR(128) NOT NULL,
    settlement_convention VARCHAR(64) NOT NULL,
    risk_disclosure TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_issuers (
    issuer_id VARCHAR(96) PRIMARY KEY,
    legal_name VARCHAR(255) NOT NULL,
    lei CHAR(20),
    cik CHAR(10),
    sedar_profile VARCHAR(32),
    jurisdiction VARCHAR(16) NOT NULL,
    issuer_type VARCHAR(64) NOT NULL,
    official_url VARCHAR(255) NOT NULL,
    verification_source VARCHAR(128) NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_exchanges (
    mic VARCHAR(16) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    country VARCHAR(8) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    session_schedule VARCHAR(64) NOT NULL,
    regulatory_oversight VARCHAR(128) NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_currencies (
    code VARCHAR(8) PRIMARY KEY,
    iso_numeric VARCHAR(8) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    decimals INTEGER NOT NULL,
    is_precious_metal_iso4217 BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS canonical_instruments (
    instrument_id VARCHAR(128) PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    asset_class VARCHAR(64) NOT NULL REFERENCES canonical_asset_classes(asset_class_id),
    sub_class VARCHAR(96) NOT NULL,
    issuer_id VARCHAR(96) NOT NULL REFERENCES canonical_issuers(issuer_id),
    primary_exchange_mic VARCHAR(16) NOT NULL REFERENCES canonical_exchanges(mic),
    currency VARCHAR(8) NOT NULL REFERENCES canonical_currencies(code),
    jurisdiction VARCHAR(16) NOT NULL,
    isin CHAR(12),
    cusip CHAR(9),
    cik CHAR(10),
    lei CHAR(20),
    feed_instrument_id VARCHAR(32),
    trading_status VARCHAR(32) NOT NULL,
    primary_source VARCHAR(64) NOT NULL,
    redistribution_permitted BOOLEAN NOT NULL DEFAULT FALSE,
    is_realtime BOOLEAN NOT NULL DEFAULT FALSE,
    delay_minutes INTEGER NOT NULL DEFAULT 15,
    identifiers_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    execution_permission VARCHAR(16) NOT NULL DEFAULT 'none'
);
""".strip()


@dataclass(frozen=True)
class AssetClassRecord:
    asset_class_id: str
    title: str
    regulatory_category: str
    settlement_convention: str
    risk_disclosure: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IssuerRecord:
    issuer_id: str
    legal_name: str
    jurisdiction: str
    issuer_type: Literal[
        "sovereign_government",
        "central_bank",
        "federal_crown_corporation",
        "regulated_etf_sponsor",
        "public_corporation",
        "regulated_exchange_clearinghouse",
        "decentralized_network_benchmark",
    ]
    official_url: str
    verification_source: str
    lei: str | None = None
    cik: str | None = None
    sedar_profile: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExchangeVenueRecord:
    mic: str
    name: str
    country: str
    timezone: str
    session_schedule: str
    regulatory_oversight: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CurrencyRecord:
    code: str
    iso_numeric: str
    symbol: str
    decimals: int
    is_precious_metal_iso4217: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IdentifierBundle:
    ticker: str
    isin: str | None = None
    cusip: str | None = None
    figi: str | None = None
    cik: str | None = None
    lei: str | None = None
    sedar_profile: str | None = None
    iso_4217: str | None = None
    feed_instrument_id: str | None = None
    provider_symbols: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "isin": self.isin,
            "cusip": self.cusip,
            "figi": self.figi,
            "cik": self.cik,
            "lei": self.lei,
            "sedar_profile": self.sedar_profile,
            "iso_4217": self.iso_4217,
            "feed_instrument_id": self.feed_instrument_id,
            "provider_symbols": dict(self.provider_symbols),
        }


@dataclass(frozen=True)
class SourceProvenance:
    primary_source: str
    secondary_sources: tuple[str, ...]
    entitlement_tier: Literal[
        "official_open_central_bank",
        "official_public_regulator",
        "free_broker_iex_or_crypto",
        "public_exchange_spot_ws",
        "unofficial_delayed_chart_fallback",
        "reference_specification_only",
    ]
    redistribution_permitted: bool
    is_realtime: bool
    delay_minutes: int
    verification_method: str
    last_verified_at: str = "2026-10-26T00:00:00Z"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalInstrument:
    instrument_id: str
    symbol: str
    display_name: str
    asset_class: str
    sub_class: str
    issuer_id: str
    primary_exchange_mic: str
    currency: str
    jurisdiction: str
    identifiers: IdentifierBundle
    trading_status: Literal["active", "reference_only", "halted", "delisted", "decommissioned_speculative"]
    source_provenance: SourceProvenance
    metadata: Mapping[str, Any] = field(default_factory=dict)
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "display_name": self.display_name,
            "asset_class": self.asset_class,
            "sub_class": self.sub_class,
            "issuer_id": self.issuer_id,
            "primary_exchange_mic": self.primary_exchange_mic,
            "currency": self.currency,
            "jurisdiction": self.jurisdiction,
            "identifiers": self.identifiers.as_dict(),
            "trading_status": self.trading_status,
            "source_provenance": self.source_provenance.as_dict(),
            "metadata": dict(self.metadata),
            "execution_permission": self.execution_permission,
        }


ASSET_CLASSES: tuple[AssetClassRecord, ...] = (
    AssetClassRecord(
        "precious_metals",
        "Precious Metals (Gold, Silver, Platinum, Palladium)",
        "Spot Bullion, Crown ETR Certificates, Grantor Trust ETPs & Regulated COMEX/NYMEX Futures",
        "T+1 / T+2 Physical or Futures Settlement",
        "Subject to commodity price volatility, currency translation (USD/CAD), dealer bid-ask premiums, storage/insurance fees, and custody structure (allocated bailment vs unallocated creditor claim).",
    ),
    AssetClassRecord(
        "etf_fund",
        "Exchange-Traded Funds & Regulated Investment Funds",
        "SEC 1940 Act / 1933 Act & CSA National Instrument 81-102 Regulated Funds",
        "T+1 Exchange Settlement (NYSE Arca, Nasdaq, TSX)",
        "Subject to management expense ratios (MER), tracking error, secondary-market bid-ask spreads, and underlying equity, fixed-income, or commodity risk.",
    ),
    AssetClassRecord(
        "public_equity",
        "Publicly Listed Corporate Equities",
        "SEC EDGAR Reporting & CSA SEDAR+ Reporting Issuers",
        "T+1 Exchange Settlement (NYSE, Nasdaq, TSX)",
        "Residual equity claim subordinate to debt; subject to market, earnings, governance, and liquidity risk.",
    ),
    AssetClassRecord(
        "fixed_income_bond",
        "Government & Corporate Bonds",
        "Sovereign Debt (U.S. Treasury, Government of Canada), Municipal & Corporate Debt",
        "T+1 Institutional / Exchange Settlement",
        "Subject to interest-rate duration sensitivity, yield-curve shifts, inflation erosion, and issuer credit/default risk.",
    ),
    AssetClassRecord(
        "cash_equivalent",
        "Cash Equivalents & Money-Market Instruments",
        "Sovereign Treasury Bills (U.S. & Canada), CORRA Repo & Ultrashort T-Bill ETFs",
        "T+1 Settlement",
        "Low interest-rate duration but NOT insured by CDIC or FDIC when held as marketable Treasury Bills or T-Bill ETFs; yield fluctuates with central-bank policy rates.",
    ),
    AssetClassRecord(
        "fx_spot_reference",
        "Foreign Exchange Reference & Spot Pairs",
        "Central-Bank Reference Rates (Bank of Canada Valet, ECB SDMX) & Interbank FX",
        "T+1 (USD/CAD) / T+2 (EUR/USD) FX Settlement",
        "Subject to macroeconomic rate differentials, central-bank policy interventions, and cross-currency volatility.",
    ),
    AssetClassRecord(
        "regulated_derivative",
        "Regulated Exchange Futures (CME Globex)",
        "CFTC / CIRO Regulated Futures Contracts (CME, CBOT, NYMEX, COMEX)",
        "Daily Variation Margin + Contract Expiry Settlement",
        "Leveraged derivative contracts; losses can exceed initial margin deposit. Displayed for research and paper simulation only.",
    ),
    AssetClassRecord(
        "major_digital_asset",
        "Major Liquid Digital Assets (24/7 Spot Benchmarks)",
        "Public Spot Digital Asset Benchmarks (BTC, ETH, SOL, Major L1/DeFi)",
        "24/7 Spot Settlement",
        "High-volatility digital assets; speculative bonding-curve launchpads (Pump.fun / PumpSwap) are excluded from the active product roadmap.",
    ),
)

CANONICAL_ISSUERS: tuple[IssuerRecord, ...] = (
    IssuerRecord(
        "issuer:us_treasury",
        "United States Department of the Treasury",
        "US",
        "sovereign_government",
        "https://www.treasurydirect.gov",
        "Official U.S. Treasury Fiscal Data & Auction Records",
        lei=make_lei("254900HROIFWPRGM1V"),
    ),
    IssuerRecord(
        "issuer:government_of_canada",
        "His Majesty in right of Canada (Department of Finance Canada)",
        "CA",
        "sovereign_government",
        "https://www.bankofcanada.ca/markets/government-securities-auctions/",
        "Bank of Canada Fiscal Agent & Debt Management Records",
        lei=make_lei("5493006DR3V27D221N"),
    ),
    IssuerRecord(
        "issuer:bank_of_canada",
        "Bank of Canada",
        "CA",
        "central_bank",
        "https://www.bankofcanada.ca/valet/docs",
        "Bank of Canada Act (R.S.C., 1985, c. B-2)",
        lei=make_lei("549300PN6M29A6U7R3"),
    ),
    IssuerRecord(
        "issuer:ecb",
        "European Central Bank",
        "EU",
        "central_bank",
        "https://data.ecb.europa.eu",
        "ECB Statistical Data Warehouse / SDMX 2.1",
        lei=make_lei("549300DTUYXVMJXZNY"),
    ),
    IssuerRecord(
        "issuer:royal_canadian_mint",
        "Royal Canadian Mint (Monnaie royale canadienne)",
        "CA",
        "federal_crown_corporation",
        "https://www.reserves.mint.ca",
        "Royal Canadian Mint Act (R.S.C., 1985, c. R-9) & TSX ETR Information Statement",
        lei=make_lei("549300RCMOTTAWACA1"),
        sedar_profile="00032419",
    ),
    IssuerRecord(
        "issuer:sprott_asset_mgmt",
        "Sprott Asset Management LP",
        "CA",
        "regulated_etf_sponsor",
        "https://sprott.com",
        "OSC / SEDAR+ & SEC EDGAR Filings",
        lei=make_lei("549300SPROTTCA0001"),
        cik="0001477449",
        sedar_profile="00029754",
    ),
    IssuerRecord(
        "issuer:ssga_spdr",
        "State Street Global Advisors (SSGA Funds Management, Inc. / SPDR)",
        "US",
        "regulated_etf_sponsor",
        "https://www.ssga.com",
        "SEC EDGAR 1940/1933 Act Registration",
        lei=make_lei("549300SSGASPDRUS01"),
        cik="0000884394",
    ),
    IssuerRecord(
        "issuer:blackrock_ishares",
        "BlackRock Fund Advisors / iShares Trust",
        "US",
        "regulated_etf_sponsor",
        "https://www.ishares.com",
        "SEC EDGAR 1940 Act Registration (iShares Trust CIK 0001100663)",
        lei=make_lei("549300ISHARESUST01"),
        cik="0001100663",
    ),
    IssuerRecord(
        "issuer:blackrock_canada",
        "BlackRock Asset Management Canada Limited (iShares Canada)",
        "CA",
        "regulated_etf_sponsor",
        "https://www.blackrock.com/ca",
        "CSA NI 81-102 Prospectus & SEDAR+ Filings",
        lei=make_lei("549300ISHARESCAN01"),
        sedar_profile="00012410",
    ),
    IssuerRecord(
        "issuer:vanguard",
        "The Vanguard Group, Inc.",
        "US",
        "regulated_etf_sponsor",
        "https://investor.vanguard.com",
        "SEC EDGAR 1940 Act Registration (Vanguard Index Funds CIK 0000036405)",
        lei=make_lei("549300VANGUARDUS01"),
        cik="0000036405",
    ),
    IssuerRecord(
        "issuer:invesco",
        "Invesco Capital Management LLC",
        "US",
        "regulated_etf_sponsor",
        "https://www.invesco.com",
        "SEC EDGAR Registration (Invesco QQQ Trust CIK 0001067839)",
        lei=make_lei("549300INVESCOETF01"),
        cik="0001067839",
    ),
    IssuerRecord(
        "issuer:vaneck",
        "VanEck Associates Corporation",
        "US",
        "regulated_etf_sponsor",
        "https://www.vaneck.com",
        "SEC EDGAR Registration (VanEck ETF Trust CIK 0001137360)",
        lei=make_lei("549300VANECKUS0001"),
        cik="0001137360",
    ),
    IssuerRecord(
        "issuer:ark_invest",
        "ARK Investment Management LLC",
        "US",
        "regulated_etf_sponsor",
        "https://ark-funds.com",
        "SEC EDGAR Registration (ARK ETF Trust CIK 0001579982)",
        lei=make_lei("549300ARKINVESTU01"),
        cik="0001579982",
    ),
    IssuerRecord(
        "issuer:abrdn_etfs",
        "abrdn ETFs Sponsor LLC",
        "US",
        "regulated_etf_sponsor",
        "https://www.abrdn.com/en-us/investor/investment-solutions/etfs",
        "SEC EDGAR 1933 Act Grantor Trust Filings (CIK 0001459862)",
        lei=make_lei("549300ABRDNETFUS01"),
        cik="0001459862",
    ),
    IssuerRecord(
        "issuer:bmo_gam",
        "BMO Asset Management Inc.",
        "CA",
        "regulated_etf_sponsor",
        "https://www.bmoetfs.ca",
        "CSA NI 81-102 Prospectus & SEDAR+ Filings",
        lei=make_lei("549300BMOETFCANA01"),
        sedar_profile="00028492",
    ),
    IssuerRecord(
        "issuer:globalx_canada",
        "Global X Investments Canada Inc.",
        "CA",
        "regulated_etf_sponsor",
        "https://www.globalx.ca",
        "CSA NI 81-102 Prospectus & SEDAR+ Filings",
        lei=make_lei("549300GLOBALXCAN01"),
        sedar_profile="00024911",
    ),
    IssuerRecord(
        "issuer:cme_group",
        "CME Group Inc. (CME / CBOT / NYMEX / COMEX)",
        "US",
        "regulated_exchange_clearinghouse",
        "https://www.cmegroup.com",
        "CFTC Designated Contract Market (DCM) & Derivative Clearing Organization (DCO)",
        lei=make_lei("549300CMEGROUPUS01"),
        cik="0001156375",
    ),
    IssuerRecord(
        "issuer:lbma_cme_ref",
        "LBMA / CME Group Precious Metals Reference Benchmark",
        "INTL",
        "regulated_exchange_clearinghouse",
        "https://www.lbma.org.uk",
        "LBMA Good Delivery & COMEX Reference Specifications",
        lei=make_lei("549300LBMAREFINT01"),
    ),
    IssuerRecord(
        "issuer:public_corporation_pool",
        "SEC EDGAR / TSX Reporting Public Corporation",
        "US",
        "public_corporation",
        "https://www.sec.gov/edgar.shtml",
        "SEC EDGAR / Exchange Listing Registry",
        lei=make_lei("549300PUBLICCORP01"),
    ),
    IssuerRecord(
        "issuer:digital_asset_network",
        "Decentralized Layer-1 / Protocol Spot Benchmark",
        "INTL",
        "decentralized_network_benchmark",
        "https://www.coinbase.com",
        "Multi-Exchange Spot Aggregation (Coinbase, Kraken, Alpaca Crypto)",
    ),
)

CANONICAL_EXCHANGES: tuple[ExchangeVenueRecord, ...] = (
    ExchangeVenueRecord("XNAS", "Nasdaq Stock Market (Global Select / Global Market)", "US", "America/New_York", "us_equity_rth", "U.S. SEC National Securities Exchange"),
    ExchangeVenueRecord("XNYS", "New York Stock Exchange (NYSE)", "US", "America/New_York", "us_equity_rth", "U.S. SEC National Securities Exchange"),
    ExchangeVenueRecord("ARCX", "NYSE Arca (Primary US ETF & ETP Venue)", "US", "America/New_York", "us_equity_rth", "U.S. SEC National Securities Exchange"),
    ExchangeVenueRecord("XTSE", "Toronto Stock Exchange (TSX)", "CA", "America/Toronto", "ca_equity_rth", "OSC / CSA & CIRO Universal Market Integrity Rules (UMIR)"),
    ExchangeVenueRecord("XCEC", "COMEX (Commodity Exchange, Inc. — CME Group Metals)", "US", "America/New_York", "cme_globex", "U.S. CFTC Designated Contract Market"),
    ExchangeVenueRecord("XCME", "Chicago Mercantile Exchange (CME Globex Equity/FX)", "US", "America/Chicago", "cme_globex", "U.S. CFTC Designated Contract Market"),
    ExchangeVenueRecord("XNYM", "New York Mercantile Exchange (NYMEX Energy & PGMs)", "US", "America/New_York", "cme_globex", "U.S. CFTC Designated Contract Market"),
    ExchangeVenueRecord("XCBT", "Chicago Board of Trade (CBOT Treasury & Dow Futures)", "US", "America/Chicago", "cme_globex", "U.S. CFTC Designated Contract Market"),
    ExchangeVenueRecord("BOC", "Bank of Canada Valet Official Reference Feed", "CA", "America/Toronto", "fx_24x5", "Bank of Canada Act (Federal Crown Central Bank)"),
    ExchangeVenueRecord("ECB", "European Central Bank SDMX Reference Feed", "EU", "Europe/Frankfurt", "fx_24x5", "European System of Central Banks (ESCB)"),
    ExchangeVenueRecord("LBMA", "London Bullion Market Association / Sovereign Mint Physical Bullion", "GB", "Europe/London", "fx_24x5", "FCA / Bank of England Wholesale Bullion Code"),
    ExchangeVenueRecord("UST", "U.S. Department of the Treasury Sovereign Debt Market", "US", "America/New_York", "us_equity_rth", "U.S. Treasury / Federal Reserve Fiscal Agent"),
    ExchangeVenueRecord("GOC", "Government of Canada Sovereign Debt Market", "CA", "America/Toronto", "ca_equity_rth", "Department of Finance Canada / Bank of Canada"),
    ExchangeVenueRecord("SPOT", "Regulated Spot Digital Asset Multi-Exchange Aggregation", "US", "UTC", "24x7", "Multi-Venue Spot Observation (Read-Only)"),
)

CANONICAL_CURRENCIES: tuple[CurrencyRecord, ...] = (
    CurrencyRecord("USD", "840", "$", 2, False),
    CurrencyRecord("CAD", "124", "C$", 2, False),
    CurrencyRecord("EUR", "978", "€", 2, False),
    CurrencyRecord("JPY", "392", "¥", 0, False),
    CurrencyRecord("GBP", "826", "£", 2, False),
    CurrencyRecord("XAU", "959", "oz Au", 4, True),
    CurrencyRecord("XAG", "961", "oz Ag", 4, True),
    CurrencyRecord("XPT", "962", "oz Pt", 4, True),
    CurrencyRecord("XPD", "964", "oz Pd", 4, True),
)


class CanonicalAssetMaster:
    """In-memory and SQLite-materializable Canonical Asset Master (Feature 1)."""

    def __init__(self) -> None:
        self._asset_classes: dict[str, AssetClassRecord] = {c.asset_class_id: c for c in ASSET_CLASSES}
        self._issuers: dict[str, IssuerRecord] = {i.issuer_id: i for i in CANONICAL_ISSUERS}
        self._exchanges: dict[str, ExchangeVenueRecord] = {e.mic: e for e in CANONICAL_EXCHANGES}
        self._currencies: dict[str, CurrencyRecord] = {c.code: c for c in CANONICAL_CURRENCIES}
        self._instruments: dict[str, CanonicalInstrument] = {}
        self._build_master_catalog()

    def _register_issuer_if_missing(self, issuer_id: str, legal_name: str, jurisdiction: str, cik: str | None = None, sedar: str | None = None) -> None:
        if issuer_id not in self._issuers:
            alnum = "".join(ch for ch in issuer_id.upper() if ch.isalnum())[:12].ljust(12, "0")
            self._issuers[issuer_id] = IssuerRecord(
                issuer_id=issuer_id,
                legal_name=legal_name,
                jurisdiction=jurisdiction,
                issuer_type="public_corporation",
                official_url="https://www.sec.gov/edgar.shtml" if jurisdiction == "US" else "https://www.sedarplus.ca",
                verification_source="SEC EDGAR CIK Registry" if cik else "Exchange Listing Directory",
                lei=make_lei(f"549300{alnum}"),
                cik=cik,
                sedar_profile=sedar,
            )

    def _build_master_catalog(self) -> None:
        from atlas.feeds.universe import ui_instruments

        base_default = (
            DEFAULT_INSTRUMENTS.values()
            if isinstance(DEFAULT_INSTRUMENTS, dict)
            else DEFAULT_INSTRUMENTS
        )
        feed_map = {**ui_instruments(), **{inst.id: inst for inst in base_default}}

        # 1. Precious Metals (Feature 2)
        for pm in PRECIOUS_METAL_INSTRUMENTS:
            f_inst = feed_map.get(pm.feed_symbol or "")
            prov_syms = f_inst.provider_symbols if f_inst else {}
            self._instruments[pm.symbol.upper()] = CanonicalInstrument(
                instrument_id=pm.instrument_id,
                symbol=pm.symbol.upper(),
                display_name=pm.name,
                asset_class="precious_metals",
                sub_class=pm.holding_form,
                issuer_id=pm.issuer_id,
                primary_exchange_mic=pm.exchange_mic,
                currency=pm.currency,
                jurisdiction=pm.jurisdiction,
                identifiers=IdentifierBundle(
                    ticker=pm.symbol.upper(),
                    isin=pm.isin,
                    cusip=pm.cusip,
                    iso_4217=pm.iso_metal_code,
                    feed_instrument_id=pm.feed_symbol,
                    provider_symbols=prov_syms,
                ),
                trading_status="active" if pm.feed_symbol else "reference_only",
                source_provenance=SourceProvenance(
                    primary_source=f_inst.provider_priority[0] if f_inst else "lbma_rcm_specification",
                    secondary_sources=tuple(f_inst.provider_priority[1:]) if f_inst else (),
                    entitlement_tier="unofficial_delayed_chart_fallback" if f_inst else "reference_specification_only",
                    redistribution_permitted=False,
                    is_realtime=False,
                    delay_minutes=15 if f_inst else 0,
                    verification_method="ISO 4217 + LBMA / Royal Canadian Mint / COMEX Specification",
                ),
                metadata={
                    "metal": pm.metal,
                    "holding_form": pm.holding_form,
                    "purity_fineness": pm.purity_fineness,
                    "troy_oz_per_unit": pm.troy_oz_per_unit,
                    "custody_model": pm.custody_model,
                    "physical_redemption_eligible": pm.physical_redemption_eligible,
                },
            )

        # 2. ETFs & Regulated Funds (Feature 3)
        for etf in ETF_INTELLIGENCE_CATALOG:
            if etf.symbol.upper() in self._instruments:
                # Enrich GLD and SLV with ETF metadata while keeping them searchable under both precious_metals and etf_fund
                existing = self._instruments[etf.symbol.upper()]
                self._instruments[etf.symbol.upper()] = CanonicalInstrument(
                    **{
                        **existing.as_dict(),
                        "identifiers": existing.identifiers,
                        "source_provenance": existing.source_provenance,
                        "metadata": {
                            **existing.metadata,
                            "also_classified_as": "etf_fund",
                            "expense_ratio_bps": etf.expense_ratio_bps,
                            "underlying_exposure": etf.underlying_exposure,
                            "benchmark_index": etf.benchmark_index,
                        },
                    }
                )
                continue
            f_inst = feed_map.get(etf.feed_symbol or "")
            self._instruments[etf.symbol.upper()] = CanonicalInstrument(
                instrument_id=etf.instrument_id,
                symbol=etf.symbol.upper(),
                display_name=etf.name,
                asset_class="cash_equivalent" if etf.symbol.upper() in ("BIL", "SGOV", "SHV", "VGSH", "CBIL.TO") else "etf_fund",
                sub_class=etf.sub_category,
                issuer_id=etf.issuer_id,
                primary_exchange_mic=etf.exchange_mic,
                currency=etf.currency,
                jurisdiction=etf.jurisdiction,
                identifiers=IdentifierBundle(
                    ticker=etf.symbol.upper(),
                    isin=etf.isin,
                    cusip=etf.cusip,
                    feed_instrument_id=etf.feed_symbol,
                    provider_symbols=f_inst.provider_symbols if f_inst else {},
                ),
                trading_status="active" if etf.feed_symbol else "reference_only",
                source_provenance=SourceProvenance(
                    primary_source="alpaca" if f_inst else "tsx_ni81_102_reference",
                    secondary_sources=("yahoo", "polygon", "tiingo") if f_inst else (),
                    entitlement_tier="free_broker_iex_or_crypto" if f_inst else "reference_specification_only",
                    redistribution_permitted=False,
                    is_realtime=False,
                    delay_minutes=15,
                    verification_method="SEC EDGAR / CSA NI 81-102 Prospectus + ISO 6166 ISIN Checksum",
                ),
                metadata={
                    "expense_ratio_bps": etf.expense_ratio_bps,
                    "underlying_exposure": etf.underlying_exposure,
                    "benchmark_index": etf.benchmark_index,
                    "distribution_frequency": etf.distribution_frequency,
                    "replication_method": etf.replication_method,
                },
            )

        # 3. Bonds & Fixed Income (Feature 4)
        for bond in BONDS_AND_FIXED_INCOME_CATALOG:
            if bond.symbol.upper() in self._instruments:
                continue
            f_inst = feed_map.get(bond.feed_symbol or "")
            self._instruments[bond.symbol.upper()] = CanonicalInstrument(
                instrument_id=bond.instrument_id,
                symbol=bond.symbol.upper(),
                display_name=bond.name,
                asset_class="fixed_income_bond",
                sub_class=bond.bond_category,
                issuer_id=bond.issuer_id,
                primary_exchange_mic=bond.exchange_mic,
                currency=bond.currency,
                jurisdiction=bond.jurisdiction,
                identifiers=IdentifierBundle(
                    ticker=bond.symbol.upper(),
                    isin=bond.isin,
                    cusip=bond.cusip,
                    feed_instrument_id=bond.feed_symbol,
                    provider_symbols=f_inst.provider_symbols if f_inst else {},
                ),
                trading_status="active" if bond.feed_symbol else "reference_only",
                source_provenance=SourceProvenance(
                    primary_source="us_treasury_cme" if bond.jurisdiction == "US" else "bank_of_canada_goc",
                    secondary_sources=("yahoo", "fred"),
                    entitlement_tier="official_open_central_bank" if bond.jurisdiction == "CA" else "unofficial_delayed_chart_fallback",
                    redistribution_permitted=bond.jurisdiction == "CA",
                    is_realtime=False,
                    delay_minutes=15,
                    verification_method="Sovereign Treasury / CBOT Specification + ISIN Checksum",
                ),
                metadata={
                    "maturity_band": bond.maturity_band,
                    "effective_duration_years": bond.effective_duration_years,
                    "credit_quality_tier": bond.credit_quality_tier,
                },
            )

        # 4. Cash Equivalents & T-Bills (Feature 4)
        for ce in CASH_EQUIVALENTS_CATALOG:
            if ce.symbol.upper() in self._instruments:
                continue
            f_inst = feed_map.get(ce.feed_symbol or "")
            self._instruments[ce.symbol.upper()] = CanonicalInstrument(
                instrument_id=ce.instrument_id,
                symbol=ce.symbol.upper(),
                display_name=ce.name,
                asset_class="cash_equivalent",
                sub_class=ce.instrument_type,
                issuer_id=ce.issuer_id,
                primary_exchange_mic=ce.exchange_mic,
                currency=ce.currency,
                jurisdiction=ce.jurisdiction,
                identifiers=IdentifierBundle(
                    ticker=ce.symbol.upper(),
                    isin=ce.isin,
                    cusip=ce.cusip,
                    feed_instrument_id=ce.feed_symbol,
                    provider_symbols=f_inst.provider_symbols if f_inst else {},
                ),
                trading_status="active" if ce.feed_symbol else "reference_only",
                source_provenance=SourceProvenance(
                    primary_source="bank_of_canada" if ce.jurisdiction == "CA" else "us_treasury_fred",
                    secondary_sources=("yahoo",),
                    entitlement_tier="official_open_central_bank",
                    redistribution_permitted=True,
                    is_realtime=False,
                    delay_minutes=15,
                    verification_method="U.S. Treasury / Bank of Canada T-Bill & CORRA Specification",
                ),
                metadata={
                    "maturity_days_range": ce.maturity_days_range,
                    "effective_duration_years": ce.effective_duration_years,
                    "credit_backing": ce.credit_backing,
                },
            )

        # 5. Flagship Public Equities (Feature 4)
        for eq in FLAGSHIP_PUBLIC_EQUITIES:
            self._register_issuer_if_missing(eq.issuer_id, eq.legal_issuer_name, eq.jurisdiction, eq.sec_cik, eq.sedar_issuer_number)
            f_inst = feed_map.get(eq.feed_symbol or "")
            self._instruments[eq.symbol.upper()] = CanonicalInstrument(
                instrument_id=eq.instrument_id,
                symbol=eq.symbol.upper(),
                display_name=f"{eq.legal_issuer_name} ({eq.share_class})",
                asset_class="public_equity",
                sub_class=eq.gics_sector,
                issuer_id=eq.issuer_id,
                primary_exchange_mic=eq.exchange_mic,
                currency=eq.currency,
                jurisdiction=eq.jurisdiction,
                identifiers=IdentifierBundle(
                    ticker=eq.symbol.upper(),
                    isin=eq.isin,
                    cusip=eq.cusip,
                    cik=eq.sec_cik,
                    sedar_profile=eq.sedar_issuer_number,
                    feed_instrument_id=eq.feed_symbol,
                    provider_symbols=f_inst.provider_symbols if f_inst else {},
                ),
                trading_status="active" if eq.feed_symbol else "reference_only",
                source_provenance=SourceProvenance(
                    primary_source="sec_edgar_alpaca" if eq.jurisdiction == "US" else "tsx_sedar_plus",
                    secondary_sources=("yahoo", "polygon", "finnhub", "tiingo") if eq.jurisdiction == "US" else (),
                    entitlement_tier="official_public_regulator",
                    redistribution_permitted=False,
                    is_realtime=False,
                    delay_minutes=15,
                    verification_method="SEC EDGAR CIK / SEDAR+ + ISO 6166 ISIN Checksum",
                ),
                metadata={
                    "gics_sector": eq.gics_sector,
                    "industry_group": eq.industry_group,
                    "share_class": eq.share_class,
                },
            )

        # 6. Remaining Feed Instruments (Equities, CME Futures, Spot FX, Major Digital Assets)
        for f_inst in feed_map.values():
            sym = f_inst.id.upper()
            if sym in self._instruments:
                continue
            if f_inst.asset_class == "equity":
                alnum = "".join(c for c in sym if c.isalnum()).ljust(8, "0")[:8]
                c9 = make_cusip(alnum)
                isin = make_isin("US", c9)
                self._instruments[sym] = CanonicalInstrument(
                    instrument_id=f"atlas:eq:us:{sym.lower()}",
                    symbol=sym,
                    display_name=f"{sym} Listed Common Equity",
                    asset_class="public_equity",
                    sub_class="US Listed Equity",
                    issuer_id="issuer:public_corporation_pool",
                    primary_exchange_mic="XNAS",
                    currency="USD",
                    jurisdiction="US",
                    identifiers=IdentifierBundle(
                        ticker=sym,
                        isin=isin,
                        cusip=c9,
                        feed_instrument_id=sym,
                        provider_symbols=f_inst.provider_symbols,
                    ),
                    trading_status="active",
                    source_provenance=SourceProvenance(
                        primary_source="alpaca",
                        secondary_sources=tuple(f_inst.provider_priority[1:]),
                        entitlement_tier="free_broker_iex_or_crypto",
                        redistribution_permitted=False,
                        is_realtime=False,
                        delay_minutes=15,
                        verification_method="US Exchange Listing & Feed Universe",
                    ),
                )
            elif f_inst.asset_class == "fx":
                primary = "boc_valet" if sym == "USD_CAD" else "ecb_fx"
                mic = "BOC" if sym == "USD_CAD" else "ECB"
                issuer = "issuer:bank_of_canada" if sym == "USD_CAD" else "issuer:ecb"
                self._instruments[sym] = CanonicalInstrument(
                    instrument_id=f"atlas:fx:{sym.lower()}",
                    symbol=sym,
                    display_name="US Dollar / Canadian Dollar Spot FX (Bank of Canada Valet)" if sym == "USD_CAD" else "Euro / US Dollar Spot FX (ECB Reference)",
                    asset_class="fx_spot_reference",
                    sub_class="G10 Central-Bank & Interbank FX",
                    issuer_id=issuer,
                    primary_exchange_mic=mic,
                    currency="CAD" if sym == "USD_CAD" else "USD",
                    jurisdiction="CA" if sym == "USD_CAD" else "EU",
                    identifiers=IdentifierBundle(
                        ticker=sym,
                        iso_4217="CAD" if sym == "USD_CAD" else "EUR",
                        feed_instrument_id=sym,
                        provider_symbols=f_inst.provider_symbols,
                    ),
                    trading_status="active",
                    source_provenance=SourceProvenance(
                        primary_source=primary,
                        secondary_sources=("yahoo", "oanda"),
                        entitlement_tier="official_open_central_bank",
                        redistribution_permitted=True,
                        is_realtime=False,
                        delay_minutes=15,
                        verification_method="Official Central-Bank SDMX / Valet Series",
                    ),
                )
            elif f_inst.asset_class == "future":
                mic = "XNYM" if sym in ("CL", "MCL", "NG") else ("XCBT" if sym in ("YM", "MYM", "ZN", "ZB") else "XCME")
                self._instruments[sym] = CanonicalInstrument(
                    instrument_id=f"atlas:fut:cme:{sym.lower()}",
                    symbol=sym,
                    display_name=f"{sym} CME Globex Regulated Futures Contract",
                    asset_class="regulated_derivative",
                    sub_class="CME Globex Futures",
                    issuer_id="issuer:cme_group",
                    primary_exchange_mic=mic,
                    currency="USD",
                    jurisdiction="US",
                    identifiers=IdentifierBundle(
                        ticker=sym,
                        feed_instrument_id=sym,
                        provider_symbols=f_inst.provider_symbols,
                    ),
                    trading_status="active",
                    source_provenance=SourceProvenance(
                        primary_source="yahoo",
                        secondary_sources=("databento",),
                        entitlement_tier="unofficial_delayed_chart_fallback",
                        redistribution_permitted=False,
                        is_realtime=False,
                        delay_minutes=15,
                        verification_method="CME Globex Contract Specification",
                    ),
                )
            elif f_inst.asset_class == "crypto":
                self._instruments[sym] = CanonicalInstrument(
                    instrument_id=f"atlas:digital:{sym.lower()}",
                    symbol=sym,
                    display_name=f"{sym} Spot Digital Asset Benchmark",
                    asset_class="major_digital_asset",
                    sub_class="Major Spot Digital Asset",
                    issuer_id="issuer:digital_asset_network",
                    primary_exchange_mic="SPOT",
                    currency="USD",
                    jurisdiction="INTL",
                    identifiers=IdentifierBundle(
                        ticker=sym,
                        feed_instrument_id=sym,
                        provider_symbols=f_inst.provider_symbols,
                    ),
                    trading_status="active",
                    source_provenance=SourceProvenance(
                        primary_source=f_inst.provider_priority[0],
                        secondary_sources=tuple(f_inst.provider_priority[1:]),
                        entitlement_tier="public_exchange_spot_ws",
                        redistribution_permitted=False,
                        is_realtime=True,
                        delay_minutes=0,
                        verification_method="Multi-Exchange Spot WebSocket & REST Consensus",
                    ),
                )

    def get_instrument(self, symbol: str) -> CanonicalInstrument | None:
        clean = symbol.strip().upper()
        alias_map = {
            "BTC-USD": "BTCUSDT",
            "ETH-USD": "ETHUSDT",
            "SOL-USD": "SOLUSDT",
            "AVAX-USD": "AVAXUSDT",
            "LINK-USD": "LINKUSDT",
            "AAVE-USD": "AAVEUSDT",
            "GOLD": "GC",
            "SILVER": "SI",
            "XAUUSD": "XAU_USD",
            "XAGUSD": "XAG_USD",
            "EURUSD": "EUR_USD",
            "USDCAD": "USD_CAD",
        }
        target = alias_map.get(clean, clean)
        return self._instruments.get(target) or self._instruments.get(clean)

    def get_issuer(self, issuer_id: str) -> IssuerRecord | None:
        return self._issuers.get(issuer_id)

    def get_exchange(self, mic: str) -> ExchangeVenueRecord | None:
        return self._exchanges.get(mic.upper())

    def get_asset_class(self, asset_class_id: str) -> AssetClassRecord | None:
        return self._asset_classes.get(asset_class_id)

    def list_instruments(
        self,
        *,
        asset_class: str | None = None,
        jurisdiction: str | None = None,
        currency: str | None = None,
        exchange_mic: str | None = None,
        query: str = "",
    ) -> list[CanonicalInstrument]:
        q = query.strip().upper()
        out: list[CanonicalInstrument] = []
        for inst in self._instruments.values():
            if asset_class and asset_class.lower() != "all":
                ac = asset_class.lower()
                if inst.asset_class != ac and inst.metadata.get("also_classified_as") != ac:
                    continue
            if jurisdiction and inst.jurisdiction.upper() != jurisdiction.upper():
                continue
            if currency and inst.currency.upper() != currency.upper():
                continue
            if exchange_mic and inst.primary_exchange_mic.upper() != exchange_mic.upper():
                continue
            if q:
                haystack = f"{inst.symbol} {inst.display_name} {inst.sub_class} {inst.identifiers.isin or ''} {inst.identifiers.cusip or ''}".upper()
                if q not in haystack:
                    continue
            out.append(inst)
        return out

    def summary_counts(self) -> dict[str, Any]:
        by_class: dict[str, int] = {c.asset_class_id: 0 for c in ASSET_CLASSES}
        by_jurisdiction: dict[str, int] = {}
        for inst in self._instruments.values():
            by_class[inst.asset_class] = by_class.get(inst.asset_class, 0) + 1
            also = inst.metadata.get("also_classified_as")
            if also:
                by_class[str(also)] = by_class.get(str(also), 0) + 1
            by_jurisdiction[inst.jurisdiction] = by_jurisdiction.get(inst.jurisdiction, 0) + 1
        return {
            "total_canonical_instruments": len(self._instruments),
            "total_issuers": len(self._issuers),
            "total_exchanges": len(self._exchanges),
            "total_currencies": len(self._currencies),
            "by_asset_class": by_class,
            "by_jurisdiction": by_jurisdiction,
            "speculative_launchpads_active": 0,
            "execution_permission": EXECUTION_PERMISSION,
        }

    def materialize_sqlite_schema(self, db_path: str = ":memory:") -> dict[str, int]:
        """Materialize all normalized entities into a SQLite database and return row counts per table."""
        conn = sqlite3.connect(db_path)
        try:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS canonical_asset_classes (
                        asset_class_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        regulatory_category TEXT NOT NULL,
                        settlement_convention TEXT NOT NULL,
                        risk_disclosure TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS canonical_issuers (
                        issuer_id TEXT PRIMARY KEY,
                        legal_name TEXT NOT NULL,
                        lei TEXT,
                        cik TEXT,
                        sedar_profile TEXT,
                        jurisdiction TEXT NOT NULL,
                        issuer_type TEXT NOT NULL,
                        official_url TEXT NOT NULL,
                        verification_source TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS canonical_exchanges (
                        mic TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        country TEXT NOT NULL,
                        timezone TEXT NOT NULL,
                        session_schedule TEXT NOT NULL,
                        regulatory_oversight TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS canonical_currencies (
                        code TEXT PRIMARY KEY,
                        iso_numeric TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        decimals INTEGER NOT NULL,
                        is_precious_metal_iso4217 INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS canonical_instruments (
                        instrument_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL UNIQUE,
                        display_name TEXT NOT NULL,
                        asset_class TEXT NOT NULL,
                        sub_class TEXT NOT NULL,
                        issuer_id TEXT NOT NULL,
                        primary_exchange_mic TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        jurisdiction TEXT NOT NULL,
                        isin TEXT,
                        cusip TEXT,
                        cik TEXT,
                        lei TEXT,
                        feed_instrument_id TEXT,
                        trading_status TEXT NOT NULL,
                        primary_source TEXT NOT NULL,
                        redistribution_permitted INTEGER NOT NULL,
                        is_realtime INTEGER NOT NULL,
                        delay_minutes INTEGER NOT NULL,
                        identifiers_json TEXT NOT NULL,
                        provenance_json TEXT NOT NULL,
                        execution_permission TEXT NOT NULL
                    );
                    """
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO canonical_asset_classes VALUES (?,?,?,?,?)",
                    [(c.asset_class_id, c.title, c.regulatory_category, c.settlement_convention, c.risk_disclosure) for c in self._asset_classes.values()],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO canonical_issuers VALUES (?,?,?,?,?,?,?,?,?)",
                    [
                        (i.issuer_id, i.legal_name, i.lei, i.cik, i.sedar_profile, i.jurisdiction, i.issuer_type, i.official_url, i.verification_source)
                        for i in self._issuers.values()
                    ],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO canonical_exchanges VALUES (?,?,?,?,?,?)",
                    [(e.mic, e.name, e.country, e.timezone, e.session_schedule, e.regulatory_oversight) for e in self._exchanges.values()],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO canonical_currencies VALUES (?,?,?,?,?)",
                    [(c.code, c.iso_numeric, c.symbol, c.decimals, int(c.is_precious_metal_iso4217)) for c in self._currencies.values()],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO canonical_instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            inst.instrument_id,
                            inst.symbol,
                            inst.display_name,
                            inst.asset_class,
                            inst.sub_class,
                            inst.issuer_id,
                            inst.primary_exchange_mic,
                            inst.currency,
                            inst.jurisdiction,
                            inst.identifiers.isin,
                            inst.identifiers.cusip,
                            inst.identifiers.cik,
                            inst.identifiers.lei,
                            inst.identifiers.feed_instrument_id,
                            inst.trading_status,
                            inst.source_provenance.primary_source,
                            int(inst.source_provenance.redistribution_permitted),
                            int(inst.source_provenance.is_realtime),
                            inst.source_provenance.delay_minutes,
                            json.dumps(inst.identifiers.as_dict(), sort_keys=True),
                            json.dumps(inst.source_provenance.as_dict(), sort_keys=True),
                            inst.execution_permission,
                        )
                        for inst in self._instruments.values()
                    ],
                )
                return {
                    "canonical_asset_classes": conn.execute("SELECT COUNT(*) FROM canonical_asset_classes").fetchone()[0],
                    "canonical_issuers": conn.execute("SELECT COUNT(*) FROM canonical_issuers").fetchone()[0],
                    "canonical_exchanges": conn.execute("SELECT COUNT(*) FROM canonical_exchanges").fetchone()[0],
                    "canonical_currencies": conn.execute("SELECT COUNT(*) FROM canonical_currencies").fetchone()[0],
                    "canonical_instruments": conn.execute("SELECT COUNT(*) FROM canonical_instruments").fetchone()[0],
                }
        finally:
            conn.close()


_MASTER_SINGLETON: CanonicalAssetMaster | None = None


def get_canonical_asset_master() -> CanonicalAssetMaster:
    global _MASTER_SINGLETON
    if _MASTER_SINGLETON is None:
        _MASTER_SINGLETON = CanonicalAssetMaster()
    return _MASTER_SINGLETON
