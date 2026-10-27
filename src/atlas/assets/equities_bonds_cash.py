"""Feature (4): Public Equities, Government & Corporate Bonds, and Cash Equivalents (`src/atlas/assets/equities_bonds_cash.py`).

Classifies and catalogs:
1. `public_equity` — SEC EDGAR CIK-verified US equities (`XNAS`, `XNYS`) and SEDAR+ Canadian TSX equities (`XTSE`)
2. `fixed_income_bond` — US Treasury & Government of Canada sovereign benchmarks, CBOT Treasury futures (`ZN`, `ZB`),
   and exchange-traded Treasury, Aggregate, Municipal, Investment-Grade Corporate, and High-Yield Bond funds
3. `cash_equivalent` — US & Canadian Sovereign Treasury Bills (`US-TBILL-1M/3M/6M`, `CA-TBILL-3M/6M`), CORRA overnight
   reference, and exchange-traded ultrashort T-Bill instruments (`BIL`, `SGOV`, `SHV`, `VGSH`, `CBIL.TO`).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from atlas.assets.authenticity import make_cusip, make_isin

EXECUTION_PERMISSION = "none"


@dataclass(frozen=True)
class PublicEquitySpec:
    symbol: str
    instrument_id: str
    legal_issuer_name: str
    issuer_id: str
    exchange_mic: Literal["XNAS", "XNYS", "XTSE"]
    currency: Literal["USD", "CAD"]
    jurisdiction: Literal["US", "CA"]
    gics_sector: str
    industry_group: str
    share_class: str
    isin: str
    cusip: str
    sec_cik: str | None = None
    sedar_issuer_number: str | None = None
    feed_symbol: str | None = None
    risk_disclosure: str = (
        "Publicly listed common equity represents a residual ownership claim subordinate to secured and unsecured debt; "
        "subject to market, earnings, sector, and dilution risk."
    )
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BondAndFixedIncomeSpec:
    symbol: str
    instrument_id: str
    name: str
    issuer_id: str
    issuer_name: str
    bond_category: Literal[
        "sovereign_us_treasury",
        "sovereign_government_of_canada",
        "municipal_tax_exempt",
        "corporate_investment_grade",
        "corporate_high_yield",
        "aggregate_broad_bond",
        "regulated_treasury_future",
    ]
    instrument_structure: Literal["direct_sovereign_benchmark", "exchange_traded_bond_fund", "cbot_treasury_future"]
    exchange_mic: str
    currency: Literal["USD", "CAD"]
    jurisdiction: Literal["US", "CA"]
    maturity_band: str
    effective_duration_years: float
    credit_quality_tier: str
    coupon_or_yield_convention: str
    isin: str | None
    cusip: str | None
    feed_symbol: str | None
    interest_rate_and_credit_disclosure: str
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CashEquivalentSpec:
    symbol: str
    instrument_id: str
    name: str
    issuer_id: str
    issuer_name: str
    instrument_type: Literal[
        "us_treasury_bill_benchmark",
        "canadian_treasury_bill_benchmark",
        "central_bank_overnight_rate",
        "exchange_traded_tbill_etf",
    ]
    exchange_mic: str
    currency: Literal["USD", "CAD"]
    jurisdiction: Literal["US", "CA"]
    maturity_days_range: str
    effective_duration_years: float
    settlement_convention: str
    credit_backing: str
    isin: str | None
    cusip: str | None
    feed_symbol: str | None
    liquidity_and_deposit_insurance_disclosure: str
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _eq(
    sym: str,
    legal_name: str,
    mic: Literal["XNAS", "XNYS", "XTSE"],
    ccy: Literal["USD", "CAD"],
    jur: Literal["US", "CA"],
    sector: str,
    industry: str,
    cusip8: str,
    cik: str | None = None,
    sedar: str | None = None,
    share_class: str = "Common Stock (1 vote/share)",
    feed_sym: str | None = "SELF",
) -> PublicEquitySpec:
    c9 = make_cusip(cusip8)
    isin = make_isin(jur, c9)
    return PublicEquitySpec(
        symbol=sym,
        instrument_id=f"atlas:eq:{jur.lower()}:{sym.lower().replace('.', '-')}",
        legal_issuer_name=legal_name,
        issuer_id=f"issuer:eq:{sym.lower().replace('.', '_')}",
        exchange_mic=mic,
        currency=ccy,
        jurisdiction=jur,
        gics_sector=sector,
        industry_group=industry,
        share_class=share_class,
        isin=isin,
        cusip=c9,
        sec_cik=cik,
        sedar_issuer_number=sedar,
        feed_symbol=sym if feed_sym == "SELF" else feed_sym,
    )


FLAGSHIP_PUBLIC_EQUITIES: tuple[PublicEquitySpec, ...] = (
    # SEC CIK-Verified US Equities
    _eq("NVDA", "NVIDIA Corporation", "XNAS", "USD", "US", "Information Technology", "Semiconductors & AI Compute", "67066G10", "0001045810"),
    _eq("AAPL", "Apple Inc.", "XNAS", "USD", "US", "Information Technology", "Technology Hardware & Ecosystems", "03783310", "0000320193"),
    _eq("MSFT", "Microsoft Corporation", "XNAS", "USD", "US", "Information Technology", "Systems & Cloud Software", "59491810", "0000789019"),
    _eq("AMZN", "Amazon.com, Inc.", "XNAS", "USD", "US", "Consumer Discretionary", "E-Commerce & Cloud Infrastructure", "02313510", "0001018724"),
    _eq("META", "Meta Platforms, Inc.", "XNAS", "USD", "US", "Communication Services", "Interactive Media & Services", "30303M10", "0001326801", None, "Class A Common Stock"),
    _eq("GOOGL", "Alphabet Inc.", "XNAS", "USD", "US", "Communication Services", "Interactive Media & Cloud", "02079K30", "0001652044", None, "Class A Common Stock (1 vote)"),
    _eq("GOOG", "Alphabet Inc.", "XNAS", "USD", "US", "Communication Services", "Interactive Media & Cloud", "02079K10", "0001652044", None, "Class C Capital Stock (non-voting)"),
    _eq("TSLA", "Tesla, Inc.", "XNAS", "USD", "US", "Consumer Discretionary", "Electric Vehicles & Energy Storage", "88160R10", "0001318605"),
    _eq("BRK-B", "Berkshire Hathaway Inc.", "XNYS", "USD", "US", "Financials", "Multi-Sector Holdings & Reinsurance", "08467070", "0001067983", None, "Class B Common Stock"),
    _eq("AVGO", "Broadcom Inc.", "XNAS", "USD", "US", "Information Technology", "Semiconductors & Infrastructure Software", "11135F10", "0001730168"),
    _eq("AMD", "Advanced Micro Devices, Inc.", "XNAS", "USD", "US", "Information Technology", "Semiconductors", "00790310", "0000002488"),
    _eq("JPM", "JPMorgan Chase & Co.", "XNYS", "USD", "US", "Financials", "Diversified Money-Center Banks", "46625H10", "0000019617"),
    _eq("GS", "The Goldman Sachs Group, Inc.", "XNYS", "USD", "US", "Financials", "Investment Banking & Brokerage", "38141G10", "0000886982"),
    _eq("V", "Visa Inc.", "XNYS", "USD", "US", "Financials", "Transaction & Payment Processing", "92826C83", "0001403161", None, "Class A Common Stock"),
    _eq("MA", "Mastercard Incorporated", "XNYS", "USD", "US", "Financials", "Transaction & Payment Processing", "57636Q10", "0001141391", None, "Class A Common Stock"),
    _eq("LLY", "Eli Lilly and Company", "XNYS", "USD", "US", "Health Care", "Pharmaceuticals", "53245710", "0000059478"),
    _eq("UNH", "UnitedHealth Group Incorporated", "XNYS", "USD", "US", "Health Care", "Managed Health Care", "91324P10", "0000731766"),
    _eq("JNJ", "Johnson & Johnson", "XNYS", "USD", "US", "Health Care", "Pharmaceuticals & MedTech", "47816010", "0000200406"),
    _eq("XOM", "Exxon Mobil Corporation", "XNYS", "USD", "US", "Energy", "Integrated Oil & Gas", "30231G10", "0000034088"),
    _eq("CVX", "Chevron Corporation", "XNYS", "USD", "US", "Energy", "Integrated Oil & Gas", "16676410", "0000093410"),
    _eq("WMT", "Walmart Inc.", "XNYS", "USD", "US", "Consumer Staples", "Consumer Staples Merchandise Retail", "93114210", "0000104169"),
    _eq("COST", "Costco Wholesale Corporation", "XNAS", "USD", "US", "Consumer Staples", "Warehouse Clubs & Supercenters", "22160K10", "0000909832"),
    _eq("PG", "The Procter & Gamble Company", "XNYS", "USD", "US", "Consumer Staples", "Household & Personal Products", "74271810", "0000080424"),
    _eq("KO", "The Coca-Cola Company", "XNYS", "USD", "US", "Consumer Staples", "Soft Drinks & Non-Alcoholic Beverages", "19121610", "0000021344"),
    _eq("PEP", "PepsiCo, Inc.", "XNAS", "USD", "US", "Consumer Staples", "Food & Beverage", "71344810", "0000077476"),

    # Canadian TSX Listed Flagship Public Equities (SEDAR+ Verified)
    _eq("RY.TO", "Royal Bank of Canada", "XTSE", "CAD", "CA", "Financials", "Canadian Schedule I Chartered Bank", "78008710", "0001000275", "00001567", "Common Shares", None),
    _eq("TD.TO", "The Toronto-Dominion Bank", "XTSE", "CAD", "CA", "Financials", "Canadian Schedule I Chartered Bank", "89116050", "0000947263", "00001570", "Common Shares", None),
    _eq("SHOP.TO", "Shopify Inc.", "XTSE", "CAD", "CA", "Information Technology", "Commerce Software & Payments", "82509L10", "0001594805", "00037039", "Class A Subordinate Voting Shares", None),
    _eq("ENB.TO", "Enbridge Inc.", "XTSE", "CAD", "CA", "Energy", "Oil & Gas Storage and Transportation", "29250N10", "0000895728", "00001289", "Common Shares", None),
    _eq("CNR.TO", "Canadian National Railway Company", "XTSE", "CAD", "CA", "Industrials", "Rail Transportation", "13637510", "0000016868", "00001334", "Common Shares", None),
)


BONDS_AND_FIXED_INCOME_CATALOG: tuple[BondAndFixedIncomeSpec, ...] = (
    # --- 1. Direct US Treasury & Government of Canada Sovereign Benchmarks ---
    BondAndFixedIncomeSpec(
        symbol="UST-2Y",
        instrument_id="atlas:bond:us:ust-2y",
        name="U.S. Treasury 2-Year Benchmark Note Reference",
        issuer_id="issuer:us_treasury",
        issuer_name="United States Department of the Treasury",
        bond_category="sovereign_us_treasury",
        instrument_structure="direct_sovereign_benchmark",
        exchange_mic="UST",
        currency="USD",
        jurisdiction="US",
        maturity_band="2 Years",
        effective_duration_years=1.88,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Semi-annual fixed coupon (Actual/Actual)",
        isin=make_isin("US", "912828YV6"),
        cusip=make_cusip("912828YV"),
        feed_symbol="SHY",
        interest_rate_and_credit_disclosure="Backed by the full faith and credit of the U.S. Government; market value fluctuates inversely with short-term Federal Reserve policy rate expectations.",
    ),
    BondAndFixedIncomeSpec(
        symbol="UST-10Y",
        instrument_id="atlas:bond:us:ust-10y",
        name="U.S. Treasury 10-Year Benchmark Note Reference",
        issuer_id="issuer:us_treasury",
        issuer_name="United States Department of the Treasury",
        bond_category="sovereign_us_treasury",
        instrument_structure="direct_sovereign_benchmark",
        exchange_mic="UST",
        currency="USD",
        jurisdiction="US",
        maturity_band="10 Years",
        effective_duration_years=8.10,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Semi-annual fixed coupon (Actual/Actual)",
        isin=make_isin("US", "912828Z94"),
        cusip=make_cusip("912828Z9"),
        feed_symbol="ZN",
        interest_rate_and_credit_disclosure="Global benchmark long-term discount rate; ~8.1 year duration means a +100 bps rise in 10Y yields reduces market price by ~8.1%.",
    ),
    BondAndFixedIncomeSpec(
        symbol="UST-30Y",
        instrument_id="atlas:bond:us:ust-30y",
        name="U.S. Treasury 30-Year Long Bond Benchmark Reference",
        issuer_id="issuer:us_treasury",
        issuer_name="United States Department of the Treasury",
        bond_category="sovereign_us_treasury",
        instrument_structure="direct_sovereign_benchmark",
        exchange_mic="UST",
        currency="USD",
        jurisdiction="US",
        maturity_band="30 Years",
        effective_duration_years=16.80,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Semi-annual fixed coupon (Actual/Actual)",
        isin=make_isin("US", "912810SZ2"),
        cusip=make_cusip("912810SZ"),
        feed_symbol="ZB",
        interest_rate_and_credit_disclosure="High interest-rate duration (~16.8 years); substantial mark-to-market price volatility prior to maturity despite sovereign credit backing.",
    ),
    BondAndFixedIncomeSpec(
        symbol="GOC-2Y",
        instrument_id="atlas:bond:ca:goc-2y",
        name="Government of Canada 2-Year Benchmark Bond Reference",
        issuer_id="issuer:government_of_canada",
        issuer_name="His Majesty in right of Canada (Department of Finance / Bank of Canada)",
        bond_category="sovereign_government_of_canada",
        instrument_structure="direct_sovereign_benchmark",
        exchange_mic="GOC",
        currency="CAD",
        jurisdiction="CA",
        maturity_band="2 Years",
        effective_duration_years=1.85,
        credit_quality_tier="Sovereign Canada (AAA / Aaa)",
        coupon_or_yield_convention="Semi-annual fixed coupon (Actual/365 Canadian convention)",
        isin=make_isin("CA", "135087N83"),
        cusip=make_cusip("135087N8"),
        feed_symbol=None,
        interest_rate_and_credit_disclosure="Direct CAD obligation of the Government of Canada; sensitive to Bank of Canada overnight policy rate path.",
    ),
    BondAndFixedIncomeSpec(
        symbol="GOC-10Y",
        instrument_id="atlas:bond:ca:goc-10y",
        name="Government of Canada 10-Year Benchmark Bond Reference",
        issuer_id="issuer:government_of_canada",
        issuer_name="His Majesty in right of Canada (Department of Finance / Bank of Canada)",
        bond_category="sovereign_government_of_canada",
        instrument_structure="direct_sovereign_benchmark",
        exchange_mic="GOC",
        currency="CAD",
        jurisdiction="CA",
        maturity_band="10 Years",
        effective_duration_years=8.25,
        credit_quality_tier="Sovereign Canada (AAA / Aaa)",
        coupon_or_yield_convention="Semi-annual fixed coupon (Actual/365 Canadian convention)",
        isin=make_isin("CA", "135087Q98"),
        cusip=make_cusip("135087Q9"),
        feed_symbol=None,
        interest_rate_and_credit_disclosure="Primary Canadian long-term fixed-income and mortgage-rate benchmark; subject to interest-rate duration risk.",
    ),

    # --- 2. CBOT Regulated Treasury Futures ---
    BondAndFixedIncomeSpec(
        symbol="ZN",
        instrument_id="atlas:bond:us:cbot-zn-fut",
        name="10-Year U.S. Treasury Note Futures (CBOT Front Month)",
        issuer_id="issuer:cme_group",
        issuer_name="Chicago Board of Trade (CME Group)",
        bond_category="regulated_treasury_future",
        instrument_structure="cbot_treasury_future",
        exchange_mic="XCBT",
        currency="USD",
        jurisdiction="US",
        maturity_band="6.5 to 10 Years Deliverable Basket",
        effective_duration_years=7.10,
        credit_quality_tier="CME Clearinghouse / Deliverable US Treasury Notes",
        coupon_or_yield_convention="6% notional standard coupon; 32nds fractional pricing",
        isin=None,
        cusip=None,
        feed_symbol="ZN",
        interest_rate_and_credit_disclosure="Leveraged interest-rate futures contract; tracks cheapest-to-deliver (CTD) 6.5–10Y U.S. Treasury Note.",
    ),
    BondAndFixedIncomeSpec(
        symbol="ZB",
        instrument_id="atlas:bond:us:cbot-zb-fut",
        name="30-Year U.S. Treasury Bond Futures (CBOT Front Month)",
        issuer_id="issuer:cme_group",
        issuer_name="Chicago Board of Trade (CME Group)",
        bond_category="regulated_treasury_future",
        instrument_structure="cbot_treasury_future",
        exchange_mic="XCBT",
        currency="USD",
        jurisdiction="US",
        maturity_band="15 to 25+ Years Deliverable Basket",
        effective_duration_years=14.80,
        credit_quality_tier="CME Clearinghouse / Deliverable US Treasury Bonds",
        coupon_or_yield_convention="6% notional standard coupon; 32nds fractional pricing",
        isin=None,
        cusip=None,
        feed_symbol="ZB",
        interest_rate_and_credit_disclosure="High-duration leveraged Treasury bond futures contract; subject to CME margin and convexity dynamics.",
    ),

    # --- 3. Tradable Bond ETFs (Treasury, Aggregate, Corporate IG, High-Yield, Municipal) ---
    BondAndFixedIncomeSpec(
        symbol="TLT",
        instrument_id="atlas:etf:us:tlt",
        name="iShares 20+ Year Treasury Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="sovereign_us_treasury",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="XNAS",
        currency="USD",
        jurisdiction="US",
        maturity_band="20+ Years",
        effective_duration_years=16.45,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Monthly distribution; 15 bps expense ratio",
        isin=make_isin("US", "46428743"),
        cusip=make_cusip("46428743"),
        feed_symbol="TLT",
        interest_rate_and_credit_disclosure="Long-duration US Treasury fund (~16.5y effective duration); high sensitivity to long-end yield curve shifts.",
    ),
    BondAndFixedIncomeSpec(
        symbol="IEF",
        instrument_id="atlas:etf:us:ief",
        name="iShares 7-10 Year Treasury Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="sovereign_us_treasury",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="XNAS",
        currency="USD",
        jurisdiction="US",
        maturity_band="7–10 Years",
        effective_duration_years=7.25,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Monthly distribution; 15 bps expense ratio",
        isin=make_isin("US", "46428744"),
        cusip=make_cusip("46428744"),
        feed_symbol="IEF",
        interest_rate_and_credit_disclosure="Intermediate-duration US Treasury exposure (~7.25y effective duration).",
    ),
    BondAndFixedIncomeSpec(
        symbol="SHY",
        instrument_id="atlas:etf:us:shy",
        name="iShares 1-3 Year Treasury Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="sovereign_us_treasury",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="XNAS",
        currency="USD",
        jurisdiction="US",
        maturity_band="1–3 Years",
        effective_duration_years=1.86,
        credit_quality_tier="Sovereign US Treasury (AA+ / Aaa)",
        coupon_or_yield_convention="Monthly distribution; 15 bps expense ratio",
        isin=make_isin("US", "46428745"),
        cusip=make_cusip("46428745"),
        feed_symbol="SHY",
        interest_rate_and_credit_disclosure="Short-duration US Treasury exposure (~1.86y effective duration).",
    ),
    BondAndFixedIncomeSpec(
        symbol="AGG",
        instrument_id="atlas:etf:us:agg",
        name="iShares Core U.S. Aggregate Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="aggregate_broad_bond",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_band="Intermediate Aggregate (5–10 Years Avg)",
        effective_duration_years=6.05,
        credit_quality_tier="Investment Grade Aggregate (AA / A / BBB)",
        coupon_or_yield_convention="Monthly distribution; 3 bps expense ratio",
        isin=make_isin("US", "46428722"),
        cusip=make_cusip("46428722"),
        feed_symbol="AGG",
        interest_rate_and_credit_disclosure="Broad US investment-grade bond exposure across Treasuries, agency MBS, and IG corporate bonds.",
    ),
    BondAndFixedIncomeSpec(
        symbol="LQD",
        instrument_id="atlas:etf:us:lqd",
        name="iShares iBoxx $ Investment Grade Corporate Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="corporate_investment_grade",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_band="3–20+ Years Corporate IG",
        effective_duration_years=8.35,
        credit_quality_tier="Investment Grade Corporate (AAA / AA / A / BBB)",
        coupon_or_yield_convention="Monthly distribution; 14 bps expense ratio",
        isin=make_isin("US", "46428724"),
        cusip=make_cusip("46428724"),
        feed_symbol="LQD",
        interest_rate_and_credit_disclosure="Subject to both interest-rate duration (~8.35y) and corporate credit-spread widening / downgrade risk.",
    ),
    BondAndFixedIncomeSpec(
        symbol="HYG",
        instrument_id="atlas:etf:us:hyg",
        name="iShares iBoxx $ High Yield Corporate Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="corporate_high_yield",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_band="3–10 Years Sub-Investment Grade",
        effective_duration_years=3.30,
        credit_quality_tier="Non-Investment Grade / High Yield (BB / B / CCC)",
        coupon_or_yield_convention="Monthly distribution; 49 bps expense ratio",
        isin=make_isin("US", "46428851"),
        cusip=make_cusip("46428851"),
        feed_symbol="HYG",
        interest_rate_and_credit_disclosure="Holds below-investment-grade corporate debt; elevated default, credit-spread, and liquidity stress risk during recessions.",
    ),
    BondAndFixedIncomeSpec(
        symbol="MUB",
        instrument_id="atlas:etf:us:mub",
        name="iShares National Muni Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        bond_category="municipal_tax_exempt",
        instrument_structure="exchange_traded_bond_fund",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_band="Intermediate Municipal",
        effective_duration_years=6.15,
        credit_quality_tier="Investment Grade US Municipal (AAA / AA / A)",
        coupon_or_yield_convention="Monthly distribution; 5 bps expense ratio",
        isin=make_isin("US", "46428841"),
        cusip=make_cusip("46428841"),
        feed_symbol="MUB",
        interest_rate_and_credit_disclosure="U.S. municipal tax-exempt interest treatment applies under U.S. federal tax rules and does NOT automatically apply to Canadian tax residents.",
    ),
)


CASH_EQUIVALENTS_CATALOG: tuple[CashEquivalentSpec, ...] = (
    CashEquivalentSpec(
        symbol="US-TBILL-1M",
        instrument_id="atlas:cash:us:tbill-1m",
        name="U.S. Treasury 4-Week (1-Month) Treasury Bill Benchmark",
        issuer_id="issuer:us_treasury",
        issuer_name="United States Department of the Treasury",
        instrument_type="us_treasury_bill_benchmark",
        exchange_mic="UST",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="28 Days (4-Week Zero-Coupon Discount Bill)",
        effective_duration_years=0.08,
        settlement_convention="T+1 Institutional / Auction Settlement",
        credit_backing="Full faith and credit of the United States Government",
        isin=make_isin("US", "912797KS5"),
        cusip=make_cusip("912797KS"),
        feed_symbol="SGOV",
        liquidity_and_deposit_insurance_disclosure="Zero-coupon sovereign discount bill; not an FDIC/CDIC bank deposit, though backed by U.S. Treasury sovereign credit.",
    ),
    CashEquivalentSpec(
        symbol="US-TBILL-3M",
        instrument_id="atlas:cash:us:tbill-3m",
        name="U.S. Treasury 13-Week (3-Month) Treasury Bill Benchmark",
        issuer_id="issuer:us_treasury",
        issuer_name="United States Department of the Treasury",
        instrument_type="us_treasury_bill_benchmark",
        exchange_mic="UST",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="91 Days (13-Week Zero-Coupon Discount Bill)",
        effective_duration_years=0.24,
        settlement_convention="T+1 Institutional / Auction Settlement",
        credit_backing="Full faith and credit of the United States Government",
        isin=make_isin("US", "912797KT3"),
        cusip=make_cusip("912797KT"),
        feed_symbol="BIL",
        liquidity_and_deposit_insurance_disclosure="Canonical short-term USD money-market sovereign benchmark; carries near-zero interest-rate duration (~0.24y).",
    ),
    CashEquivalentSpec(
        symbol="CA-TBILL-3M",
        instrument_id="atlas:cash:ca:goc-tbill-3m",
        name="Government of Canada 3-Month Treasury Bill Benchmark",
        issuer_id="issuer:government_of_canada",
        issuer_name="His Majesty in right of Canada (Bank of Canada Fiscal Agent)",
        instrument_type="canadian_treasury_bill_benchmark",
        exchange_mic="GOC",
        currency="CAD",
        jurisdiction="CA",
        maturity_days_range="91 Days (Actual/365 CAD Discount Bill)",
        effective_duration_years=0.24,
        settlement_convention="T+1 CDS Settlement",
        credit_backing="Direct sovereign obligation of the Government of Canada (AAA)",
        isin=make_isin("CA", "135095N21"),
        cusip=make_cusip("135095N2"),
        feed_symbol=None,
        liquidity_and_deposit_insurance_disclosure="Direct Government of Canada short-term sovereign obligation; distinct from CDIC-insured chartered bank GICs or savings deposits.",
    ),
    CashEquivalentSpec(
        symbol="CA-CORRA",
        instrument_id="atlas:cash:ca:corra-overnight",
        name="Canadian Overnight Repo Rate Average (CORRA — Bank of Canada Administered)",
        issuer_id="issuer:bank_of_canada",
        issuer_name="Bank of Canada",
        instrument_type="central_bank_overnight_rate",
        exchange_mic="BOC",
        currency="CAD",
        jurisdiction="CA",
        maturity_days_range="1 Day (Overnight Government of Canada Repo Benchmark)",
        effective_duration_years=0.003,
        settlement_convention="Overnight General Collateral Repo Reference",
        credit_backing="Collateralized by Government of Canada Treasury Bills and Bonds",
        isin=None,
        cusip=None,
        feed_symbol=None,
        liquidity_and_deposit_insurance_disclosure="Official Bank of Canada risk-free overnight benchmark rate that replaced CDOR.",
    ),
    CashEquivalentSpec(
        symbol="BIL",
        instrument_id="atlas:etf:us:bil",
        name="SPDR Bloomberg 1-3 Month T-Bill ETF",
        issuer_id="issuer:ssga_spdr",
        issuer_name="State Street Global Advisors (SPDR)",
        instrument_type="exchange_traded_tbill_etf",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="30–90 Days (1–3 Month U.S. Treasury Bills)",
        effective_duration_years=0.14,
        settlement_convention="T+1 NYSE Arca Secondary Market",
        credit_backing="Portfolio of 1–3 Month U.S. Treasury Bills (13.5 bps expense ratio)",
        isin=make_isin("US", "78468R66"),
        cusip=make_cusip("78468R66"),
        feed_symbol="BIL",
        liquidity_and_deposit_insurance_disclosure="Exchange-traded fund holding U.S. Treasury Bills; NOT a bank deposit and NOT insured by FDIC or CDIC.",
    ),
    CashEquivalentSpec(
        symbol="SGOV",
        instrument_id="atlas:etf:us:sgov",
        name="iShares 0-3 Month Treasury Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        instrument_type="exchange_traded_tbill_etf",
        exchange_mic="ARCX",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="0–90 Days (0–3 Month U.S. Treasury Bills)",
        effective_duration_years=0.10,
        settlement_convention="T+1 NYSE Arca Secondary Market",
        credit_backing="Portfolio of <=3 Month U.S. Treasury Bills (9.0 bps expense ratio)",
        isin=make_isin("US", "46436E71"),
        cusip=make_cusip("46436E71"),
        feed_symbol="SGOV",
        liquidity_and_deposit_insurance_disclosure="Ultrashort Treasury ETF (~0.10y duration); secondary-market shares are not FDIC/CDIC deposit-insured.",
    ),
    CashEquivalentSpec(
        symbol="SHV",
        instrument_id="atlas:etf:us:shv",
        name="iShares Short Treasury Bond ETF",
        issuer_id="issuer:blackrock_ishares",
        issuer_name="BlackRock Fund Advisors (iShares)",
        instrument_type="exchange_traded_tbill_etf",
        exchange_mic="XNAS",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="30–365 Days (<=1 Year U.S. Treasury Securities)",
        effective_duration_years=0.35,
        settlement_convention="T+1 Nasdaq Secondary Market",
        credit_backing="Portfolio of <=1 Year U.S. Treasury Bills & Notes (15.0 bps expense ratio)",
        isin=make_isin("US", "46428867"),
        cusip=make_cusip("46428867"),
        feed_symbol="SHV",
        liquidity_and_deposit_insurance_disclosure="Short-term U.S. Treasury ETF (~0.35y duration); subject to modest NAV fluctuation and secondary-market bid-ask spread.",
    ),
    CashEquivalentSpec(
        symbol="VGSH",
        instrument_id="atlas:etf:us:vgsh",
        name="Vanguard Short-Term Treasury ETF",
        issuer_id="issuer:vanguard",
        issuer_name="The Vanguard Group, Inc.",
        instrument_type="exchange_traded_tbill_etf",
        exchange_mic="XNAS",
        currency="USD",
        jurisdiction="US",
        maturity_days_range="1–3 Years Short-Term U.S. Treasuries",
        effective_duration_years=1.90,
        settlement_convention="T+1 Nasdaq Secondary Market",
        credit_backing="Portfolio of 1–3 Year U.S. Treasury Notes (4.0 bps expense ratio)",
        isin=make_isin("US", "92206C10"),
        cusip=make_cusip("92206C10"),
        feed_symbol="VGSH",
        liquidity_and_deposit_insurance_disclosure="Short-term Treasury Note ETF (~1.9y duration); low 4 bps expense ratio.",
    ),
    CashEquivalentSpec(
        symbol="CBIL.TO",
        instrument_id="atlas:etf:ca:cbil-to",
        name="Global X 0-3 Month T-Bill ETF (Government of Canada Treasury Bills — TSX)",
        issuer_id="issuer:globalx_canada",
        issuer_name="Global X Investments Canada Inc.",
        instrument_type="exchange_traded_tbill_etf",
        exchange_mic="XTSE",
        currency="CAD",
        jurisdiction="CA",
        maturity_days_range="0–90 Days (0–3 Month Government of Canada T-Bills)",
        effective_duration_years=0.12,
        settlement_convention="T+1 TSX / CDS Secondary Market",
        credit_backing="Portfolio of Government of Canada Treasury Bills (10.0 bps management fee)",
        isin=make_isin("CA", "37961T10"),
        cusip=make_cusip("37961T10"),
        feed_symbol=None,
        liquidity_and_deposit_insurance_disclosure="NI 81-102 regulated Canadian ETF holding GoC T-Bills; units are not insured by CDIC.",
    ),
)


def build_equities_bonds_cash_catalog(
    *,
    section: Literal["all", "equities", "bonds", "cash_equivalents"] = "all",
    now: float | None = None,
) -> dict[str, Any]:
    """Return Feature (4) Equities, Bonds, and Cash Equivalents enriched with live `atlas_feed` quotes."""
    from atlas.api.feeds_api import feed_quotes

    now_ts = float(now or time.time())
    all_feed_syms = list({
        *(e.feed_symbol for e in FLAGSHIP_PUBLIC_EQUITIES if e.feed_symbol),
        *(b.feed_symbol for b in BONDS_AND_FIXED_INCOME_CATALOG if b.feed_symbol),
        *(c.feed_symbol for c in CASH_EQUIVALENTS_CATALOG if c.feed_symbol),
        "USD_CAD",
    })
    quotes = feed_quotes(all_feed_syms, now_ts)
    usd_cad = (quotes.get("USD_CAD") or {}).get("price")

    def _enrich(item_dict: dict[str, Any], feed_sym: str | None, ccy: str) -> dict[str, Any]:
        q = (quotes.get(feed_sym) if feed_sym else None) or {}
        p = q.get("price")
        p_cad = p if ccy == "CAD" else (round(p * usd_cad, 2) if (p and usd_cad) else None)
        return {
            **item_dict,
            "market_price": p,
            "market_price_cad": p_cad,
            "change_pct": q.get("change_pct"),
            "quote_status": q.get("status") if feed_sym else "reference_only",
            "quote_source": q.get("source"),
            "quote_time_toronto": q.get("observed_at_toronto"),
        }

    equities_out = (
        [_enrich(e.as_dict(), e.feed_symbol, e.currency) for e in FLAGSHIP_PUBLIC_EQUITIES]
        if section in ("all", "equities")
        else []
    )
    bonds_out = (
        [_enrich(b.as_dict(), b.feed_symbol, b.currency) for b in BONDS_AND_FIXED_INCOME_CATALOG]
        if section in ("all", "bonds")
        else []
    )
    cash_out = (
        [_enrich(c.as_dict(), c.feed_symbol, c.currency) for c in CASH_EQUIVALENTS_CATALOG]
        if section in ("all", "cash_equivalents")
        else []
    )

    return {
        "feature_id": "feature_04_equities_bonds_cash_equivalents",
        "section": section,
        "counts": {
            "public_equities": len(equities_out),
            "bonds_and_fixed_income": len(bonds_out),
            "cash_equivalents": len(cash_out),
        },
        "usd_cad_fx_rate": usd_cad,
        "public_equities": equities_out,
        "bonds_and_fixed_income": bonds_out,
        "cash_equivalents": cash_out,
        "execution_permission": EXECUTION_PERMISSION,
    }

