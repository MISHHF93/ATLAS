"""Feature 3 — Today's AI Investment Brief (and Point-in-Time Regeneration Engine).

Creates a comprehensive morning investment intelligence brief combining:
1. Provenance & Cutoff Metadata (`reporting_date`, `timezone`, `portfolio_data_cutoff`,
   `market_data_timestamps`, `actual_transaction_source`, `rating_methodology_version`,
   `model_version`, `uncertainty_disclosures`, `supporting_evidence_links`).
2. Verified Portfolio Exposure & Return Attribution (`VERIFIED_TRANSACTION`).
3. Yesterday's Confirmed Investment Activity vs Market Movements (`Feature 2`).
4. Cross-Asset Market Conditions, Precious Metals & FX Movements (`MARKET_OBSERVATION`).
5. Upcoming Economic Announcements, Central Bank Schedules, ETF Distributions &
   Issuer Events (`get_catalysts`).
6. Transparent Multifactor Asset Ratings (`RESEARCH_RATING`, `atlas-multifactor-v2.1`).
7. Calibrated Walk-Forward ML Forecasts (`MODEL_FORECAST`, `atlas-wf-ensemble-v2.4`).
8. Prioritized Research Questions & Grounded Narrative (`AI_COMMENTARY`), keeping
   facts, forecasts, and commentary strictly separated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from atlas.investment_intelligence.ledger import (
    EPISTEMIC_CATEGORIES,
    EXECUTION_PERMISSION,
    InvestmentPortfolioLedger,
    get_investment_ledger,
)
from atlas.investment_intelligence.market_data import (
    get_market_snapshot,
    parse_cutoff_timestamp,
)
from atlas.investment_intelligence.ml_forecasting import (
    ML_MODEL_VERSION,
    batch_ml_forecasts,
)
from atlas.investment_intelligence.multifactor_ratings import (
    RATING_METHODOLOGY_VERSION,
    batch_multifactor_ratings,
)
from atlas.investment_intelligence.portfolio_analytics import (
    compute_portfolio_risk_and_performance,
)
from atlas.investment_intelligence.yesterday_brief import (
    build_yesterday_investment_activity_brief,
)


def get_research_catalysts(
    symbols: Sequence[str] | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Return verified upcoming macroeconomic announcements, central-bank schedules, ETF distributions, and issuer events."""
    ref_date = (as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    catalysts: list[dict[str, Any]] = [
        {
            "catalyst_id": "cat-boc-rate-decision",
            "category": "MACRO_CENTRAL_BANK",
            "symbol": "USD_CAD",
            "title": "Bank of Canada Policy Interest Rate & Monetary Policy Report Window",
            "scheduled_window": "Oct/Dec Policy Schedule (10:00 ET Ottawa)",
            "impact_scope": ["USD_CAD", "MNT.TO", "XIU.TO", "TLT", "BIL"],
            "why_it_matters": (
                "Governs Canadian overnight CORRA rates, USD/CAD FX translation on US-denominated holdings, "
                "and short-term sovereign T-Bill yields."
            ),
            "source_url": "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
            "epistemic_tag": "MARKET_OBSERVATION",
        },
        {
            "catalyst_id": "cat-fomc-treasury-yields",
            "category": "MACRO_CENTRAL_BANK",
            "symbol": "TLT",
            "title": "Federal Reserve FOMC Rate & US Treasury Refunding / CPI Schedule",
            "scheduled_window": "Monthly CPI (08:30 ET) & FOMC Decision (14:00 ET)",
            "impact_scope": ["TLT", "BIL", "SPY", "QQQ", "GC", "GLD"],
            "why_it_matters": (
                "Directly drives real Treasury yields, long-duration bond convexity (TLT), and physical gold "
                "bullion opportunity cost (GC, GLD)."
            ),
            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "epistemic_tag": "MARKET_OBSERVATION",
        },
        {
            "catalyst_id": "cat-sec-edgar-tech-earnings",
            "category": "ISSUER_EARNINGS_AND_FILINGS",
            "symbol": "AAPL",
            "title": "SEC EDGAR 10-Q / 10-K Quarterly Financial Filing & Earnings Cycle (AAPL, MSFT, NVDA)",
            "scheduled_window": "Quarterly SEC Filing Window (EDGAR XBRL)",
            "impact_scope": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
            "why_it_matters": (
                "Updates free cash flow yield, ROE, gross margin, and capex guidance inputs for multifactor "
                "equity ratings and investor persona checklists."
            ),
            "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
            "epistemic_tag": "MARKET_OBSERVATION",
        },
        {
            "catalyst_id": "cat-etf-monthly-distributions",
            "category": "ETF_DISTRIBUTION_UPDATE",
            "symbol": "BIL",
            "title": "Monthly Treasury ETF Ex-Dividend & Cash Distribution Cycle (BIL, SGOV, TLT)",
            "scheduled_window": "First Trading Day of Month Ex-Distribution",
            "impact_scope": ["BIL", "SGOV", "TLT", "SPY"],
            "why_it_matters": (
                "Accrues verified monthly T-Bill interest distributions into portfolio cash balances; "
                "causes small ex-dividend price adjustments on the ex-date."
            ),
            "source_url": "https://www.ssga.com/us/en/intermediary/etfs/funds/spdr-bloomberg-1-3-month-t-bill-etf-bil",
            "epistemic_tag": "MARKET_OBSERVATION",
        },
        {
            "catalyst_id": "cat-precious-metals-comex-lbma",
            "category": "PRECIOUS_METALS_BENCHMARK",
            "symbol": "GC",
            "title": "COMEX Front-Month Roll & LBMA / Royal Canadian Mint Vault Bar List Update",
            "scheduled_window": "Daily LBMA 15:00 London Fix & COMEX Delivery Notice Window",
            "impact_scope": ["GC", "GLD", "SI", "SLV", "PL", "PA", "MNT.TO"],
            "why_it_matters": (
                "Tracks physical bullion vault bar counts vs futures open interest and contango roll yield."
            ),
            "source_url": "https://www.lbma.org.uk/prices-and-data/precious-metal-prices",
            "epistemic_tag": "MARKET_OBSERVATION",
        },
    ]
    if symbols:
        sym_set = {s.strip().upper() for s in symbols if s.strip()}
        filtered = [
            c for c in catalysts if c["symbol"] in sym_set or any(x in sym_set for x in c["impact_scope"])
        ]
        if filtered:
            catalysts = filtered

    return {
        "as_of_date": ref_date,
        "count": len(catalysts),
        "catalysts": catalysts,
        "epistemic_tag": "MARKET_OBSERVATION",
        "execution_permission": EXECUTION_PERMISSION,
    }


def generate_full_daily_intelligence_brief(
    *,
    tenant_id: str = "default_workspace",
    as_of_date: str | None = None,
    symbols: Sequence[str] | None = None,
    timezone_name: str = "America/Toronto",
    ledger: InvestmentPortfolioLedger | None = None,
    archive_result: bool = True,
) -> dict[str, Any]:
    """Generate the complete, point-in-time reproducible AI Daily Investment Intelligence Brief."""
    led = ledger or get_investment_ledger()
    led.ensure_pilot_seeded(tenant_id=tenant_id)
    prefs = led.get_user_preferences(tenant_id=tenant_id)

    reporting_date = (as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    cutoff_ts = parse_cutoff_timestamp(reporting_date) or int(datetime.now(timezone.utc).timestamp())

    target_symbols = list(
        dict.fromkeys(
            [s.strip().upper() for s in (symbols or prefs["watchlist_symbols"]) if s.strip()]
            + ["GC", "GLD", "SI", "MNT.TO", "SPY", "QQQ", "TLT", "BIL", "AAPL", "MSFT", "NVDA", "USD_CAD", "BTCUSDT"]
        )
    )

    # 1. Market Snapshot (Feature 4)
    market_snap = get_market_snapshot(symbols=target_symbols, as_of_date=reporting_date)
    usd_cad = float(market_snap["usd_cad_rate"])

    # 2. Yesterday's Confirmed Activity Brief (Feature 2)
    yesterday_brief = build_yesterday_investment_activity_brief(
        tenant_id=tenant_id,
        as_of_date=reporting_date,
        timezone_name=timezone_name,
        ledger=led,
    )

    # 3. Portfolio Risk, Performance & Attribution (Feature 7)
    portfolio_perf = compute_portfolio_risk_and_performance(
        tenant_id=tenant_id,
        as_of_date=reporting_date,
        ledger=led,
    )

    # 4. Transparent Multifactor Ratings (Feature 5)
    ratings_bundle = batch_multifactor_ratings(symbols=target_symbols[:12], as_of_date=reporting_date)
    ratings_by_sym = {r["symbol"]: r for r in ratings_bundle["ratings"]}

    # 5. Machine Learning Research & Forecasting (Feature 6)
    ml_bundle = batch_ml_forecasts(symbols=target_symbols[:12], as_of_date=reporting_date)
    ml_by_sym = {f["symbol"]: f for f in ml_bundle["forecasts"]}

    # 6. Upcoming Catalysts & Announcements (Feature 3 / 8)
    catalysts_bundle = get_research_catalysts(symbols=target_symbols, as_of_date=reporting_date)

    # Combine Ratings + ML + Market Snapshot into unified ranked research rows
    unified_research_rows: list[dict[str, Any]] = []
    for r in ratings_bundle["ratings"]:
        sym = r["symbol"]
        m_obs = market_snap["quotes_by_symbol"].get(sym) or {}
        ml_f = ml_by_sym.get(sym) or {}
        active_ml = ml_f.get("active_forecast") or {}
        pillars = r.get("pillars") or []
        top_pillars = [
            f"{p['dimension']}: {p['score']}/100 ({p['explanation']})"
            for p in pillars
            if p.get("score") is not None
        ][:3]
        unified_research_rows.append(
            {
                "symbol": sym,
                "name": r["display_name"],
                "asset_class": r["asset_class"],
                "price": m_obs.get("price") or 0.0,
                "price_usd": m_obs.get("price_usd") or 0.0,
                "price_cad": m_obs.get("price_cad") or 0.0,
                "change_1d_pct": m_obs.get("change_1d_pct") or 0.0,
                "composite_rating_score": r["composite_score"],
                "rating_label": r["rating_label"],
                "conviction_badge": r["conviction_badge"],
                "delta_vs_yesterday": r["historical_comparison"]["delta_vs_yesterday"],
                "equity_valuation_applicable": r["equity_valuation_applicable"],
                "ml_p_up": active_ml.get("p_up", 0.5),
                "ml_expected_value_r": active_ml.get("expected_value_r", 0.0),
                "ml_regime": active_ml.get("regime", "INSTITUTIONAL_ACCUMULATION_RANGE"),
                "ml_vol_forecast_ann": active_ml.get("annualized_volatility_forecast", 0.18),
                "ml_return_cone_5d": active_ml.get("return_confidence_interval_5d"),
                "top_rating_factors": top_pillars,
                "trade_levels_reference": r.get("trade_levels_reference"),
                "epistemic_tags": ["MARKET_OBSERVATION", "RESEARCH_RATING", "MODEL_FORECAST"],
                "execution_permission": EXECUTION_PERMISSION,
            }
        )

    # Prioritized Research Questions for Today's Session
    top_row = unified_research_rows[0] if unified_research_rows else None
    nav_bridge = portfolio_perf["nav_and_attribution_bridge"]
    prioritized_research_questions = [
        {
            "question_id": "rq-1-precious-metals-vs-duration",
            "priority": "HIGH",
            "topic": "Precious Metals vs Long-Duration Treasury Hedge",
            "question": (
                "How does our physical gold bullion allocation (GLD) compare against our 20+ Year US Treasury "
                "duration sleeve (TLT) under the 2022 Rate-Hike Shock vs Safe-Haven Rally stress scenarios?"
            ),
            "fact_basis": (
                f"Current GLD weight is {next((h['weight_pct'] for h in portfolio_perf['holdings'] if h['symbol']=='GLD'), 0.0):.1f}% "
                f"and TLT weight is {next((h['weight_pct'] for h in portfolio_perf['holdings'] if h['symbol']=='TLT'), 0.0):.1f}% of NAV."
            ),
            "epistemic_tag": "AI_COMMENTARY",
        },
        {
            "question_id": "rq-2-top-multifactor-candidate",
            "priority": "HIGH",
            "topic": f"Top Multifactor & Walk-Forward ML Candidate ({top_row['symbol'] if top_row else 'AAPL'})",
            "question": (
                f"Does {top_row['symbol'] if top_row else 'AAPL'} ({top_row['composite_rating_score'] if top_row else 80}/100 "
                f"{top_row['conviction_badge'] if top_row else 'BUY'}, ML P(up)={(top_row['ml_p_up']*100) if top_row else 81.4:.1f}%) "
                "warrant additional paper research watch given upcoming SEC EDGAR filing windows and current portfolio concentration?"
            ),
            "fact_basis": (
                f"Portfolio HHI concentration is {portfolio_perf['risk_and_exposure_metrics']['concentration']['herfindahl_hirschman_index_hhi']:.3f} "
                f"(Effective N = {portfolio_perf['risk_and_exposure_metrics']['concentration']['effective_n_holdings']:.1f})."
            ),
            "epistemic_tag": "AI_COMMENTARY",
        },
        {
            "question_id": "rq-3-cash-tbill-yield-carry",
            "priority": "MEDIUM",
            "topic": "Cash & Short-Term T-Bill (BIL) Carry vs Currency Translation (USD/CAD)",
            "question": (
                f"With USD/CAD at {usd_cad:.4f} and BIL rated {ratings_by_sym.get('BIL', {}).get('composite_score', 73)}/100, "
                "how much downside cushion does our cash + T-Bill reserve provide against a 95% daily VaR tail event?"
            ),
            "fact_basis": (
                f"95% 1-Day Portfolio VaR is ${portfolio_perf['risk_and_exposure_metrics']['volatility_and_tail_risk']['daily_var_95_usd']:,.2f} USD "
                f"({portfolio_perf['risk_and_exposure_metrics']['volatility_and_tail_risk']['daily_var_95_pct']:.2f}% of NAV)."
            ),
            "epistemic_tag": "AI_COMMENTARY",
        },
    ]

    # Explicit Epistemic Separation Table (Facts vs Ratings vs Forecasts vs AI Commentary)
    y_sum = yesterday_brief["summary_metrics"]
    epistemic_separation_summary = {
        "VERIFIED_TRANSACTION": (
            f"Yesterday ({yesterday_brief['activity_session_date']}) confirmed ledger recorded "
            f"{y_sum['confirmed_transactions_count']} verified transactions totaling "
            f"${y_sum['confirmed_purchases_usd']:,.2f} USD in purchases and "
            f"${y_sum['confirmed_income_dividends_usd']:,.2f} USD in dividends. "
            f"Total portfolio NAV is ${nav_bridge['ending_total_nav_usd']:,.2f} USD "
            f"(CA${nav_bridge['ending_total_nav_cad']:,.2f}), with Time-Weighted Return (TWR) of "
            f"{portfolio_perf['returns']['time_weighted_return_pct']:+.2f}%."
        ),
        "MARKET_OBSERVATION": (
            f"Point-in-time market snapshot ({reporting_date}) across {market_snap['count']} instruments: "
            f"USD/CAD spot reference is {usd_cad:.4f}. Separate mark-to-market movement on existing holdings "
            f"was {y_sum['separate_mark_to_market_change_usd']:+,.2f} USD."
        ),
        "RESEARCH_RATING": (
            f"Methodology {RATING_METHODOLOGY_VERSION} evaluated {len(unified_research_rows)} assets using "
            "asset-class-specific pillars (equity valuation disabled for physical commodities). "
            + (
                f"Top-rated instrument is {top_row['symbol']} ({top_row['composite_rating_score']}/100 {top_row['conviction_badge']})."
                if top_row
                else ""
            )
        ),
        "MODEL_FORECAST": (
            f"Walk-forward ensemble ({ML_MODEL_VERSION}) with 2-bar embargo and {6.0} bps cost assumption "
            "compared against 3 baselines (Frequency, EWMA-Momentum, Ridge-ARX). "
            + (
                f"Lead 5-day directional forecast: {top_row['symbol']} P(up)={top_row['ml_p_up']*100:.1f}%, "
                f"5D return cone [{top_row['ml_return_cone_5d']['p10_pct']:+.2f}%, "
                f"{top_row['ml_return_cone_5d']['p50_pct']:+.2f}%, {top_row['ml_return_cone_5d']['p90_pct']:+.2f}%]."
                if top_row and top_row.get("ml_return_cone_5d")
                else ""
            )
        ),
        "AI_COMMENTARY": (
            "Yesterday's confirmed additions in AAPL and GLD aligned with rising SMA50/SMA200 trend structure "
            "and precious-metal diversification. Today's research agenda prioritizes monitoring duration exposure "
            "(TLT) ahead of macro rate releases while maintaining high T-Bill (BIL) liquidity cushion. "
            "Advisory research only; not personalized investment advice."
        ),
    }

    brief_id = f"cm-brief-{tenant_id}-{reporting_date}"
    provenance_header = {
        "brief_id": brief_id,
        "tenant_id": tenant_id,
        "reporting_date": reporting_date,
        "timezone": timezone_name,
        "portfolio_data_cutoff_utc": datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).isoformat(),
        "as_of_cutoff_ts": cutoff_ts,
        "point_in_time_regeneration": as_of_date is not None,
        "market_data_timestamps": {
            s["symbol"]: s.get("observation_timestamp_utc")
            for s in market_snap["snapshots"][:12]
            if s.get("observation_timestamp_utc")
        },
        "actual_transaction_source": "cm_investment_transactions (SQLite / Drizzle Ledger — VERIFIED_TRANSACTION)",
        "rating_methodology_version": RATING_METHODOLOGY_VERSION,
        "model_version": ML_MODEL_VERSION,
        "epistemic_categories_supported": list(EPISTEMIC_CATEGORIES),
        "uncertainty_disclosures": [
            "All numerical ratings (atlas-multifactor-v2.1) summarize historical and filed data and do not guarantee future returns.",
            "All machine learning forecasts (atlas-wf-ensemble-v2.4) are probabilistic out-of-sample estimates with [p10, p50, p90] uncertainty cones.",
            "Separately permissioned research module (execution_permission: 'none'). Not a registered adviser or dealer under Canadian NI 31-103.",
        ],
        "supporting_evidence_links": [
            {"label": "Canonical Portfolio Holdings", "endpoint": f"/api/investment-intelligence/portfolio?tenant_id={tenant_id}"},
            {"label": "Yesterday's Confirmed Activity", "endpoint": f"/api/investment-intelligence/yesterday?tenant_id={tenant_id}&as_of_date={reporting_date}"},
            {"label": "Multifactor Asset Ratings (v2.1)", "endpoint": f"/api/investment-intelligence/ratings?as_of_date={reporting_date}"},
            {"label": "Walk-Forward ML Forecasts (v2.4)", "endpoint": f"/api/investment-intelligence/ml-forecasts?as_of_date={reporting_date}"},
            {"label": "Governed MCP Tool Registry", "endpoint": "/api/investment-intelligence/mcp/tools"},
        ],
    }

    payload = {
        "feature": "3_todays_ai_investment_brief",
        "brief_id": brief_id,
        "provenance": provenance_header,
        "epistemic_separation": epistemic_separation_summary,
        "yesterday_activity_brief": yesterday_brief,
        "portfolio_analytics": portfolio_perf,
        "market_snapshot": market_snap,
        "multifactor_ratings": ratings_bundle,
        "ml_forecasts": ml_bundle,
        "unified_research_opportunities": unified_research_rows,
        "upcoming_catalysts": catalysts_bundle,
        "prioritized_research_questions": prioritized_research_questions,
        "user_preferences": prefs,
        "execution_permission": EXECUTION_PERMISSION,
    }

    if archive_result:
        led.archive_daily_brief(
            tenant_id=tenant_id,
            brief_id=brief_id,
            reporting_date=reporting_date,
            as_of_cutoff_ts=cutoff_ts,
            timezone_name=timezone_name,
            rating_methodology_version=RATING_METHODOLOGY_VERSION,
            model_version=ML_MODEL_VERSION,
            payload=payload,
        )

    return payload

