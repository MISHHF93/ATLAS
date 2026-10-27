"""Feature (3): ETF and Fund Intelligence (`src/atlas/assets/etf_intelligence.py`).

Catalogs authorized US and Canadian Exchange-Traded Funds (ETFs) with:
- Verified issuer information (BlackRock iShares, State Street SPDR, Vanguard, Invesco, VanEck, ARK, BMO ETFs)
- Tickers, mathematically verified ISO 6166 ISINs and ANSI X9.6 CUSIPs, and ISO 10383 exchange MICs (`ARCX`, `XNAS`, `XTSE`)
- Fund objectives, benchmark indices, underlying asset-class exposures, and replication methods
- Published management expense ratios (MER / expense ratio in bps) and distribution schedules
- Market price from `atlas_feed` with explicit NAV provenance distinction (`market_price` vs `end_of_day_issuer_nav` — never fabricating intraday iNAV when no issuer iNAV feed is licensed)
- Liquidity indicators (typical bid-ask spread bps, latest 1d bar volume, quote status) and NI 81-102 / SEC disclosures.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from atlas.assets.authenticity import make_cusip, make_isin

EXECUTION_PERMISSION = "none"

NI_81_102_ETF_DISCLOSURE = (
    "Exchange-traded funds (ETFs) are subject to management fees and expenses (MER), tracking error relative to "
    "their benchmark index, market-price premiums or discounts to Net Asset Value (NAV), and underlying market risk. "
    "Past performance may not be repeated. Displayed prices are secondary-market feed prints, not official issuer NAV."
)


@dataclass(frozen=True)
class ETFFundRecord:
    symbol: str
    instrument_id: str
    name: str
    issuer_id: str
    issuer_name: str
    exchange_mic: Literal["ARCX", "XNAS", "XTSE"]
    currency: Literal["USD", "CAD"]
    jurisdiction: Literal["US", "CA"]
    isin: str
    cusip: str
    sub_category: str
    underlying_exposure: str
    benchmark_index: str
    fund_objective: str
    replication_method: Literal[
        "physical_full_replication",
        "physical_representative_sampling",
        "physical_allocated_bullion_trust",
        "active_equity_management",
    ]
    expense_ratio_bps: float
    distribution_frequency: Literal["monthly", "quarterly", "semi_annual", "none"]
    typical_spread_bps: float
    official_prospectus_domain: str
    risk_and_regulatory_disclosure: str = NI_81_102_ETF_DISCLOSURE
    feed_symbol: str | None = None
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _etf(
    symbol: str,
    name: str,
    issuer_id: str,
    issuer_name: str,
    mic: Literal["ARCX", "XNAS", "XTSE"],
    ccy: Literal["USD", "CAD"],
    jur: Literal["US", "CA"],
    cusip8: str,
    sub_category: str,
    underlying_exposure: str,
    benchmark_index: str,
    fund_objective: str,
    expense_bps: float,
    dist: Literal["monthly", "quarterly", "semi_annual", "none"],
    spread_bps: float,
    domain: str,
    replication: ETFFundRecord["replication_method"] = "physical_full_replication",  # type: ignore[valid-type]
    feed_sym: str | None = "SELF",
) -> ETFFundRecord:
    cusip9 = make_cusip(cusip8)
    isin12 = make_isin(jur, cusip9)
    return ETFFundRecord(
        symbol=symbol,
        instrument_id=f"atlas:etf:{jur.lower()}:{symbol.lower().replace('.', '-')}",
        name=name,
        issuer_id=issuer_id,
        issuer_name=issuer_name,
        exchange_mic=mic,
        currency=ccy,
        jurisdiction=jur,
        isin=isin12,
        cusip=cusip9,
        sub_category=sub_category,
        underlying_exposure=underlying_exposure,
        benchmark_index=benchmark_index,
        fund_objective=fund_objective,
        replication_method=replication,  # type: ignore[arg-type]
        expense_ratio_bps=expense_bps,
        distribution_frequency=dist,
        typical_spread_bps=spread_bps,
        official_prospectus_domain=domain,
        feed_symbol=symbol if feed_sym == "SELF" else feed_sym,
    )


ETF_INTELLIGENCE_CATALOG: tuple[ETFFundRecord, ...] = (
    # --- 1. Broad US Equity Index ETFs (8) ---
    _etf("SPY", "SPDR S&P 500 ETF Trust", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "78462F10", "Broad Equity Index ETF", "us_large_cap_equity", "S&P 500 Index", "Seeks to provide investment results that, before expenses, correspond generally to the price and yield performance of the S&P 500 Index.", 9.45, "quarterly", 0.3, "https://www.ssga.com"),
    _etf("QQQ", "Invesco QQQ Trust Series 1", "issuer:invesco", "Invesco Capital Management LLC", "XNAS", "USD", "US", "46090E10", "Broad Equity Index ETF", "us_nasdaq100_large_cap", "Nasdaq-100 Index", "Seeks to track the investment results of the Nasdaq-100 Index of 100 largest non-financial companies listed on Nasdaq.", 20.0, "quarterly", 0.4, "https://www.invesco.com"),
    _etf("IWM", "iShares Russell 2000 ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428765", "Broad Equity Index ETF", "us_small_cap_equity", "Russell 2000 Index", "Seeks to track the investment results of an index composed of small-capitalization U.S. equities.", 19.0, "quarterly", 0.6, "https://www.ishares.com"),
    _etf("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "78467X10", "Broad Equity Index ETF", "us_blue_chip_30_equity", "Dow Jones Industrial Average", "Seeks to provide investment results that correspond generally to the price and yield performance of the Dow Jones Industrial Average.", 16.0, "monthly", 0.6, "https://www.ssga.com"),
    _etf("VOO", "Vanguard S&P 500 ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "ARCX", "USD", "US", "92290836", "Broad Equity Index ETF", "us_large_cap_equity", "S&P 500 Index", "Seeks to track the performance of a benchmark index that measures the investment return of large-capitalization stocks.", 3.0, "quarterly", 0.4, "https://investor.vanguard.com"),
    _etf("VTI", "Vanguard Total Stock Market ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "ARCX", "USD", "US", "92290876", "Broad Equity Index ETF", "us_total_market_equity", "CRSP US Total Market Index", "Seeks to track the performance of the CRSP US Total Market Index across large-, mid-, small-, and micro-cap equities.", 3.0, "quarterly", 0.5, "https://investor.vanguard.com", "physical_representative_sampling"),
    _etf("RSP", "Invesco S&P 500 Equal Weight ETF", "issuer:invesco", "Invesco Capital Management LLC", "ARCX", "USD", "US", "46137V35", "Broad Equity Index ETF", "us_equal_weight_large_cap", "S&P 500 Equal Weight Index", "Seeks to track the investment results of the S&P 500 Equal Weight Index.", 20.0, "quarterly", 0.8, "https://www.invesco.com"),
    _etf("MDY", "SPDR S&P MidCap 400 ETF Trust", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "78467Y10", "Broad Equity Index ETF", "us_mid_cap_equity", "S&P MidCap 400 Index", "Seeks to provide investment results corresponding to the S&P MidCap 400 Index.", 23.0, "quarterly", 0.8, "https://www.ssga.com"),

    # --- 2. US Select Sector SPDR & Communication ETFs (11) ---
    _etf("XLK", "Technology Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y80", "US Sector ETF", "us_sector_technology", "Technology Select Sector Index", "Seeks to provide precise exposure to technology and telecom companies in the S&P 500.", 9.0, "quarterly", 0.6, "https://www.ssga.com"),
    _etf("XLF", "Financial Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y60", "US Sector ETF", "us_sector_financials", "Financial Select Sector Index", "Seeks to provide exposure to diversified financial services, banking, insurance, and capital markets companies in the S&P 500.", 9.0, "quarterly", 0.6, "https://www.ssga.com"),
    _etf("XLE", "Energy Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y50", "US Sector ETF", "us_sector_energy", "Energy Select Sector Index", "Seeks to provide exposure to oil, gas, consumable fuels, and energy equipment companies in the S&P 500.", 9.0, "quarterly", 0.8, "https://www.ssga.com"),
    _etf("XLV", "Health Care Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y20", "US Sector ETF", "us_sector_healthcare", "Health Care Select Sector Index", "Seeks to provide exposure to pharmaceuticals, biotechnology, medical devices, and healthcare providers in the S&P 500.", 9.0, "quarterly", 0.7, "https://www.ssga.com"),
    _etf("XLI", "Industrial Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y70", "US Sector ETF", "us_sector_industrials", "Industrial Select Sector Index", "Seeks to provide exposure to aerospace, defense, machinery, transportation, and industrial conglomerates in the S&P 500.", 9.0, "quarterly", 0.7, "https://www.ssga.com"),
    _etf("XLP", "Consumer Staples Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y30", "US Sector ETF", "us_sector_consumer_staples", "Consumer Staples Select Sector Index", "Seeks to provide exposure to food, beverage, household products, and staple retailers in the S&P 500.", 9.0, "quarterly", 0.7, "https://www.ssga.com"),
    _etf("XLY", "Consumer Discretionary Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y40", "US Sector ETF", "us_sector_consumer_discretionary", "Consumer Discretionary Select Sector Index", "Seeks to provide exposure to retail, automobiles, hospitality, and consumer cyclical companies in the S&P 500.", 9.0, "quarterly", 0.7, "https://www.ssga.com"),
    _etf("XLU", "Utilities Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y88", "US Sector ETF", "us_sector_utilities", "Utilities Select Sector Index", "Seeks to provide exposure to electric, gas, water utilities, and independent power producers in the S&P 500.", 9.0, "quarterly", 0.8, "https://www.ssga.com"),
    _etf("XLB", "Materials Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y10", "US Sector ETF", "us_sector_materials", "Materials Select Sector Index", "Seeks to provide exposure to chemicals, metals, mining, paper, and construction materials companies in the S&P 500.", 9.0, "quarterly", 0.8, "https://www.ssga.com"),
    _etf("XLRE", "The Real Estate Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y86", "US Sector ETF", "us_sector_real_estate", "Real Estate Select Sector Index", "Seeks to provide exposure to equity REITs and real estate management companies in the S&P 500.", 9.0, "quarterly", 0.9, "https://www.ssga.com"),
    _etf("XLC", "Communication Services Select Sector SPDR Fund", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "81369Y85", "US Sector ETF", "us_sector_communication", "Communication Services Select Sector Index", "Seeks to provide exposure to interactive media, telecom, entertainment, and media companies in the S&P 500.", 9.0, "quarterly", 0.8, "https://www.ssga.com"),

    # --- 3. Semiconductor, Thematic & Real Estate REIT ETFs (5) ---
    _etf("SOXX", "iShares Semiconductor ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "XNAS", "USD", "US", "46428752", "Semiconductor ETF", "us_semiconductors", "NYSE Semiconductor Index", "Seeks to track the investment results of an index composed of U.S.-listed equities in the semiconductor sector.", 35.0, "quarterly", 0.9, "https://www.ishares.com"),
    _etf("SMH", "VanEck Semiconductor ETF", "issuer:vaneck", "VanEck Associates Corporation", "XNAS", "USD", "US", "92189F67", "Semiconductor ETF", "global_us_listed_semiconductors", "MVIS US Listed Semiconductor 25 Index", "Seeks to replicate as closely as possible the price and yield performance of the MVIS US Listed Semiconductor 25 Index.", 35.0, "quarterly", 0.8, "https://www.vaneck.com"),
    _etf("ARKK", "ARK Innovation ETF", "issuer:ark_invest", "ARK Investment Management LLC", "ARCX", "USD", "US", "00214Q10", "Active Thematic ETF", "disruptive_innovation_equities", "Actively Managed (No Index)", "Actively managed ETF seeking long-term growth of capital by investing in disruptive innovation themes.", 75.0, "semi_annual", 1.8, "https://ark-funds.com", "active_equity_management"),
    _etf("VNQ", "Vanguard Real Estate ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "ARCX", "USD", "US", "92290855", "Real Estate REIT ETF", "us_equity_reits", "MSCI US Investable Market Real Estate 25/50 Index", "Seeks to provide high income and moderate long-term capital appreciation by tracking U.S. equity REITs.", 13.0, "quarterly", 0.9, "https://investor.vanguard.com"),
    _etf("IYR", "iShares U.S. Real Estate ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428773", "Real Estate REIT ETF", "us_real_estate_reits", "Dow Jones U.S. Real Estate Capped Index", "Seeks to track the investment results of an index composed of U.S. equities in the real estate sector.", 39.0, "quarterly", 1.0, "https://www.ishares.com"),

    # --- 4. US Treasury, Sovereign, Aggregate, Municipal & Corporate Bond ETFs (13) ---
    _etf("TLT", "iShares 20+ Year Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "XNAS", "USD", "US", "46428743", "Treasury & Bond ETF", "us_treasury_20plus_year", "ICE U.S. Treasury 20+ Year Bond Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds with remaining maturities greater than twenty years.", 15.0, "monthly", 0.6, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("IEF", "iShares 7-10 Year Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "XNAS", "USD", "US", "46428744", "Treasury & Bond ETF", "us_treasury_7_to_10_year", "ICE U.S. Treasury 7-10 Year Bond Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds with remaining maturities between seven and ten years.", 15.0, "monthly", 0.6, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("SHY", "iShares 1-3 Year Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "XNAS", "USD", "US", "46428745", "Treasury & Bond ETF", "us_treasury_1_to_3_year", "ICE U.S. Treasury 1-3 Year Bond Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds with remaining maturities between one and three years.", 15.0, "monthly", 0.5, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("GOVT", "iShares U.S. Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46429B26", "Treasury & Bond ETF", "us_treasury_all_maturities", "ICE U.S. Treasury Core Bond Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds across the 1-to-30 year curve.", 5.0, "monthly", 0.6, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("VGIT", "Vanguard Intermediate-Term Treasury ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "XNAS", "USD", "US", "92206C70", "Treasury & Bond ETF", "us_treasury_3_to_10_year", "Bloomberg U.S. Treasury 3-10 Year Index", "Seeks to provide a moderate and sustainable level of current income from intermediate-term U.S. Treasury securities.", 4.0, "monthly", 0.6, "https://investor.vanguard.com", "physical_representative_sampling"),
    _etf("VGLT", "Vanguard Long-Term Treasury ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "XNAS", "USD", "US", "92206C84", "Treasury & Bond ETF", "us_treasury_10plus_year", "Bloomberg U.S. Long Treasury Index", "Seeks to provide a high and sustainable level of current income from long-term U.S. Treasury bonds.", 4.0, "monthly", 0.7, "https://investor.vanguard.com", "physical_representative_sampling"),
    _etf("TIP", "iShares TIPS Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428717", "Treasury & Bond ETF", "us_treasury_inflation_protected", "Bloomberg U.S. Treasury Inflation Protected Securities (TIPS) Index", "Seeks to track the investment results of an index composed of inflation-protected U.S. Treasury bonds.", 19.0, "monthly", 0.7, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("AGG", "iShares Core U.S. Aggregate Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428722", "Treasury & Bond ETF", "us_investment_grade_aggregate_bonds", "Bloomberg U.S. Aggregate Bond Index", "Seeks to track the investment results of an index composed of the total U.S. investment-grade bond market.", 3.0, "monthly", 0.5, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("BND", "Vanguard Total Bond Market ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "XNAS", "USD", "US", "92193783", "Treasury & Bond ETF", "us_investment_grade_aggregate_bonds", "Bloomberg U.S. Aggregate Float Adjusted Index", "Seeks to track the performance of a broad, market-weighted bond index across U.S. Treasuries, agencies, MBS, and IG corporates.", 3.0, "monthly", 0.5, "https://investor.vanguard.com", "physical_representative_sampling"),
    _etf("LQD", "iShares iBoxx $ Investment Grade Corporate Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428724", "Corporate Bond ETF", "us_investment_grade_corporate_bonds", "Markit iBoxx USD Liquid Investment Grade Index", "Seeks to track the investment results of an index composed of U.S. dollar-denominated, investment-grade corporate bonds.", 14.0, "monthly", 0.6, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428851", "High-Yield Bond ETF", "us_high_yield_corporate_bonds", "Markit iBoxx USD Liquid High Yield Index", "Seeks to track the investment results of an index composed of U.S. dollar-denominated, high-yield corporate bonds.", 49.0, "monthly", 0.8, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("JNK", "SPDR Bloomberg High Yield Bond ETF", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "78468R62", "High-Yield Bond ETF", "us_high_yield_corporate_bonds", "Bloomberg High Yield Very Liquid Index", "Seeks to provide investment results corresponding to the Bloomberg High Yield Very Liquid Index.", 40.0, "monthly", 0.8, "https://www.ssga.com", "physical_representative_sampling"),
    _etf("MUB", "iShares National Muni Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46428841", "Municipal Bond ETF", "us_investment_grade_municipal_bonds", "ICE AMT-Free US National Municipal Index", "Seeks to track the investment results of an index composed of investment-grade U.S. municipal bonds.", 5.0, "monthly", 0.6, "https://www.ishares.com", "physical_representative_sampling"),

    # --- 5. Ultrashort Treasury Bill / Cash-Equivalent ETFs (4) ---
    _etf("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF", "issuer:ssga_spdr", "State Street Global Advisors (SPDR)", "ARCX", "USD", "US", "78468R66", "Cash Equivalent T-Bill ETF", "us_treasury_bills_1_to_3_month", "Bloomberg 1-3 Month U.S. Treasury Bill Index", "Seeks to provide exposure to zero-coupon U.S. Treasury Bills with remaining maturity between 1 and 3 months.", 13.5, "monthly", 0.4, "https://www.ssga.com", "physical_representative_sampling"),
    _etf("SGOV", "iShares 0-3 Month Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "ARCX", "USD", "US", "46436E71", "Cash Equivalent T-Bill ETF", "us_treasury_bills_0_to_3_month", "ICE 0-3 Month US Treasury Securities Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds with remaining maturities of three months or less.", 9.0, "monthly", 0.3, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("SHV", "iShares Short Treasury Bond ETF", "issuer:blackrock_ishares", "BlackRock Fund Advisors (iShares)", "XNAS", "USD", "US", "46428867", "Cash Equivalent T-Bill ETF", "us_treasury_under_1_year", "ICE Short US Treasury Securities Index", "Seeks to track the investment results of an index composed of U.S. Treasury bonds with remaining maturities of one year or less.", 15.0, "monthly", 0.4, "https://www.ishares.com", "physical_representative_sampling"),
    _etf("VGSH", "Vanguard Short-Term Treasury ETF", "issuer:vanguard", "The Vanguard Group, Inc.", "XNAS", "USD", "US", "92206C10", "Cash Equivalent T-Bill ETF", "us_treasury_1_to_3_year", "Bloomberg U.S. Treasury 1-3 Year Index", "Seeks to provide current income with modest price fluctuation from short-term U.S. Treasury securities.", 4.0, "monthly", 0.5, "https://investor.vanguard.com", "physical_representative_sampling"),

    # --- 6. Precious Metals Physical Bullion ETFs (2) ---
    _etf("GLD", "SPDR Gold Shares Physical Bullion Trust", "issuer:ssga_spdr", "World Gold Trust Services / State Street (SPDR)", "ARCX", "USD", "US", "78463V10", "Precious Metals ETF", "physical_gold_bullion_lbma", "LBMA Gold Price PM", "Seeks to reflect the performance of the price of gold bullion, less the Trust's expenses.", 40.0, "none", 0.5, "https://www.spdrgoldshares.com", "physical_allocated_bullion_trust"),
    _etf("SLV", "iShares Silver Trust Physical Bullion ETF", "issuer:blackrock_ishares", "iShares Delaware Trust Sponsor LLC (BlackRock)", "ARCX", "USD", "US", "46428Q10", "Precious Metals ETF", "physical_silver_bullion_lbma", "LBMA Silver Price", "Seeks to reflect generally the performance of the price of silver, before payment of the Trust's expenses and liabilities.", 50.0, "none", 0.8, "https://www.ishares.com", "physical_allocated_bullion_trust"),

    # --- 7. Canadian TSX Listed Benchmark ETFs (NI 81-102 Regulated Funds) (4) ---
    _etf("XIU.TO", "iShares S&P/TSX 60 Index ETF", "issuer:blackrock_canada", "BlackRock Asset Management Canada Limited", "XTSE", "CAD", "CA", "46430010", "Canadian Broad Index ETF", "canadian_large_cap_60_equity", "S&P/TSX 60 Index", "Seeks to provide long-term capital growth by replicating the performance of the S&P/TSX 60 Index, net of expenses.", 18.0, "quarterly", 0.6, "https://www.blackrock.com/ca", "physical_full_replication", None),
    _etf("XIC.TO", "iShares Core S&P/TSX Capped Composite Index ETF", "issuer:blackrock_canada", "BlackRock Asset Management Canada Limited", "XTSE", "CAD", "CA", "46432F10", "Canadian Broad Index ETF", "canadian_total_composite_equity", "S&P/TSX Capped Composite Index", "Seeks to provide long-term capital growth by replicating the S&P/TSX Capped Composite Index.", 6.0, "quarterly", 0.7, "https://www.blackrock.com/ca", "physical_full_replication", None),
    _etf("ZAG.TO", "BMO Aggregate Bond Index ETF", "issuer:bmo_gam", "BMO Asset Management Inc.", "XTSE", "CAD", "CA", "05575T10", "Canadian Bond ETF", "canadian_investment_grade_bonds", "FTSE Canada Universe Bond Index", "Seeks to replicate the performance of the FTSE Canada Universe Bond Index across federal, provincial, and corporate bonds.", 9.0, "monthly", 0.8, "https://www.bmoetfs.ca", "physical_representative_sampling", None),
    _etf("CBIL.TO", "Global X 0-3 Month T-Bill ETF (Government of Canada T-Bills)", "issuer:globalx_canada", "Global X Investments Canada Inc.", "XTSE", "CAD", "CA", "37961T10", "Canadian Cash Equivalent ETF", "government_of_canada_tbills_0_to_3_month", "Solactive Canadian 0-3 Month T-Bill Index", "Seeks to provide interest income through exposure to Government of Canada Treasury Bills with remaining maturities of 3 months or less.", 10.0, "monthly", 0.5, "https://www.globalx.ca", "physical_full_replication", None),
)

ETFS_BY_SYMBOL: dict[str, ETFFundRecord] = {e.symbol.upper(): e for e in ETF_INTELLIGENCE_CATALOG}


def get_etf_fund_details(symbol: str, *, now: float | None = None) -> dict[str, Any]:
    """Retrieve complete Feature (3) ETF & Fund Intelligence profile with live market quote and NAV provenance."""
    from atlas.api.feeds_api import _feed, feed_quotes

    clean = symbol.strip().upper()
    rec = ETFS_BY_SYMBOL.get(clean)
    if rec is None:
        raise KeyError(f"ETF {clean!r} is not registered in ETF_INTELLIGENCE_CATALOG")

    now_ts = float(now or time.time())
    quotes = feed_quotes([rec.feed_symbol] if rec.feed_symbol else [], now_ts)
    q = (quotes.get(rec.feed_symbol) if rec.feed_symbol else None) or {}
    usd_cad_q = feed_quotes(["USD_CAD"], now_ts).get("USD_CAD") or {}
    usd_cad = usd_cad_q.get("price")

    feed = _feed()
    latest_1d_volume = None
    if feed is not None and rec.feed_symbol and rec.feed_symbol in feed.instruments:
        bars_1d = feed.store.bars(rec.feed_symbol, "1d", None, None, confirmed_only=True)[-5:]
        if bars_1d:
            latest_1d_volume = float(bars_1d[-1].volume)

    mkt_price = q.get("price")
    price_usd = mkt_price if rec.currency == "USD" else (round(mkt_price / usd_cad, 4) if (mkt_price and usd_cad) else None)
    price_cad = mkt_price if rec.currency == "CAD" else (round(mkt_price * usd_cad, 4) if (mkt_price and usd_cad) else None)

    return {
        **rec.as_dict(),
        "market_price": mkt_price,
        "market_price_usd": price_usd,
        "market_price_cad": price_cad,
        "change_pct": q.get("change_pct"),
        "quote_status": q.get("status") if rec.feed_symbol else "reference_only_requires_tsx_feed",
        "quote_source": q.get("source"),
        "quote_time_toronto": q.get("observed_at_toronto"),
        "nav_per_share": None,
        "nav_provenance_status": (
            "market_price_observed__official_nav_requires_licensed_issuer_eod_file"
            if mkt_price is not None
            else "no_live_quote__nav_requires_licensed_issuer_eod_file"
        ),
        "liquidity_indicators": {
            "typical_spread_bps": rec.typical_spread_bps,
            "latest_1d_volume_shares": latest_1d_volume,
            "primary_exchange_mic": rec.exchange_mic,
            "quote_status": q.get("status") if rec.feed_symbol else "reference_only",
        },
        "execution_permission": EXECUTION_PERMISSION,
    }


def list_etf_intelligence(
    *,
    sub_category: str | None = None,
    jurisdiction: str | None = None,
    issuer_id: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return all cataloged ETFs with live feed quotes, expense ratios, ISINs, and disclosures."""
    from atlas.api.feeds_api import feed_quotes

    now_ts = float(now or time.time())
    feed_syms = [e.feed_symbol for e in ETF_INTELLIGENCE_CATALOG if e.feed_symbol] + ["USD_CAD"]
    quotes = feed_quotes(feed_syms, now_ts)
    usd_cad = (quotes.get("USD_CAD") or {}).get("price")

    items = []
    for rec in ETF_INTELLIGENCE_CATALOG:
        if sub_category and sub_category.strip().lower() not in rec.sub_category.lower():
            continue
        if jurisdiction and rec.jurisdiction != jurisdiction.strip().upper():
            continue
        if issuer_id and rec.issuer_id != issuer_id.strip():
            continue

        q = (quotes.get(rec.feed_symbol) if rec.feed_symbol else None) or {}
        mkt_price = q.get("price")
        price_cad = mkt_price if rec.currency == "CAD" else (round(mkt_price * usd_cad, 2) if (mkt_price and usd_cad) else None)
        items.append({
            **rec.as_dict(),
            "market_price": mkt_price,
            "market_price_cad": price_cad,
            "change_pct": q.get("change_pct"),
            "quote_status": q.get("status") if rec.feed_symbol else "reference_only_requires_tsx_feed",
            "quote_source": q.get("source"),
            "quote_time_toronto": q.get("observed_at_toronto"),
            "nav_per_share": None,
            "nav_provenance_status": "market_price_observed__official_nav_requires_licensed_issuer_eod_file",
        })

    return {
        "feature_id": "feature_03_etf_and_fund_intelligence",
        "count": len(items),
        "ni_81_102_disclosure": NI_81_102_ETF_DISCLOSURE,
        "etfs": items,
        "execution_permission": EXECUTION_PERMISSION,
    }

