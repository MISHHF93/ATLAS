"use client";

import React, { useCallback, useEffect, useState } from "react";

export type DailyBriefTabId =
  | "today"
  | "yesterday"
  | "portfolio"
  | "catalog"
  | "ratings"
  | "watchlist"
  | "performance"
  | "ml_insights"
  | "alerts"
  | "archive";

export interface FullInvestmentIntelligenceBrief {
  brief_id: string;
  provenance: {
    brief_id: string;
    tenant_id: string;
    reporting_date: string;
    timezone: string;
    portfolio_data_cutoff_utc: string;
    point_in_time_regeneration: boolean;
    actual_transaction_source: string;
    rating_methodology_version: string;
    model_version: string;
    uncertainty_disclosures: string[];
    supporting_evidence_links: Array<{ label: string; endpoint: string }>;
  };
  epistemic_separation: Record<string, string>;
  yesterday_activity_brief: {
    reporting_date: string;
    preceding_trading_day: string;
    activity_session_date: string;
    timezone: string;
    usd_cad_rate: number;
    summary_metrics: {
      confirmed_transactions_count: number;
      imported_unreconciled_count: number;
      open_or_proposed_orders_count: number;
      confirmed_purchases_usd: number;
      confirmed_purchases_cad: number;
      confirmed_sales_usd: number;
      confirmed_contributions_usd: number;
      confirmed_withdrawals_usd: number;
      confirmed_income_dividends_usd: number;
      confirmed_income_dividends_cad: number;
      confirmed_fees_usd: number;
      net_transaction_cash_flow_usd: number;
      separate_mark_to_market_change_usd: number;
      separate_mark_to_market_change_cad: number;
    };
    completed_investments: Array<{
      tx_id: string;
      symbol: string | null;
      tx_type: string;
      trade_date: string;
      settlement_date: string;
      effective_settlement_state: string;
      quantity: number;
      price: number;
      gross_amount_usd: number;
      gross_amount_cad: number;
      fee_usd: number;
      net_cash_impact_usd: number;
      verification_status: string;
      source_provenance: string;
      notes: string;
      epistemic_tag: string;
    }>;
    open_or_proposed_orders: Array<{
      proposal_id: string;
      symbol: string;
      side: string;
      proposed_quantity: number;
      limit_or_entry_price: number;
      status: string;
      epistemic_tag: string;
      classification_note: string;
    }>;
    market_movements_on_existing_holdings: Array<{
      symbol: string;
      display_name: string;
      quantity_held: number;
      prev_session_close: number;
      current_mark_price: number;
      session_price_change_pct: number;
      mark_to_market_change_usd: number;
      mark_to_market_change_cad: number;
      epistemic_tag: string;
      classification_note: string;
    }>;
    narrative_summary: string;
  };
  portfolio_analytics: {
    as_of_date: string;
    usd_cad_rate: number;
    returns: {
      time_weighted_return_pct: number;
      money_weighted_return_pct: number;
      twr_vs_mwr_methodology_note: string;
    };
    nav_and_attribution_bridge: {
      external_deposits_usd: number;
      external_withdrawals_usd: number;
      net_external_contributions_usd: number;
      realized_price_gains_usd: number;
      unrealized_price_gains_usd: number;
      dividend_and_interest_income_usd: number;
      fx_translation_gain_loss_usd: number;
      execution_and_account_fees_usd: number;
      net_investment_performance_usd: number;
      net_investment_performance_cad: number;
      ending_total_nav_usd: number;
      ending_total_nav_cad: number;
      bridge_reconciled_exact: boolean;
    };
    benchmark_comparisons: Array<{
      benchmark_symbol: string;
      benchmark_name: string;
      benchmark_return_pct: number;
      active_spread_vs_twr_pct: number;
    }>;
    risk_and_exposure_metrics: {
      asset_class_allocation_pct: Record<string, number>;
      currency_exposure_usd_equivalent: {
        USD: number;
        CAD: number;
        usd_share_pct: number;
        cad_share_pct: number;
      };
      concentration: {
        herfindahl_hirschman_index_hhi: number;
        effective_n_holdings: number;
        largest_holding_symbol: string;
        largest_holding_weight_pct: number;
      };
      volatility_and_tail_risk: {
        annualized_portfolio_volatility_pct: number;
        diversification_ratio: number;
        max_drawdown_60d_pct: number;
        daily_var_95_pct: number;
        daily_var_95_usd: number;
        daily_cvar_95_pct: number;
        daily_cvar_95_usd: number;
        daily_var_99_pct: number;
        daily_var_99_usd: number;
      };
    };
    stress_scenarios: Array<{
      scenario_id: string;
      title: string;
      estimated_pnl_usd: number;
      estimated_return_pct: number;
    }>;
    risk_alerts: Array<{
      alert_id: string;
      severity: string;
      category: string;
      message: string;
    }>;
    holdings: Array<{
      symbol: string;
      display_name: string;
      asset_class: string;
      currency: string;
      quantity: number;
      avg_cost_per_unit: number;
      total_cost_basis: number;
      market_price: number;
      market_value_usd: number;
      market_value_cad: number;
      unrealized_gain: number;
      unrealized_gain_pct: number;
      realized_gain_ytd: number;
      dividends_received_ytd: number;
      weight_pct: number;
      verification_status: string;
      price_source: string;
    }>;
    cash_balances: {
      USD: number;
      CAD: number;
      total_cash_usd_equivalent: number;
      total_cash_cad_equivalent: number;
      cash_weight_pct: number;
    };
  };
  market_snapshot: {
    usd_cad_rate: number;
    snapshots: Array<{
      symbol: string;
      display_name: string;
      asset_class: string;
      exchange_mic: string;
      isin: string | null;
      native_currency: string;
      price: number;
      price_usd: number;
      price_cad: number;
      change_1d_pct: number;
      change_1m_pct: number;
      change_3m_pct: number;
      latency_or_timeliness_label: string;
      source: string;
      benchmark: { symbol: string; name: string };
    }>;
  };
  multifactor_ratings: {
    methodology_version: string;
    ratings: Array<{
      symbol: string;
      display_name: string;
      asset_class: string;
      equity_valuation_applicable: boolean;
      composite_score: number;
      rating_label: string;
      conviction_badge: string;
      historical_comparison: {
        current_score: number;
        yesterday_score: number;
        delta_vs_yesterday: number;
        score_30d_ago: number;
        delta_vs_30d_ago: number;
      };
      pillars: Array<{
        dimension: string;
        score: number | null;
        weight: number;
        status: string;
        explanation: string;
      }>;
    }>;
  };
  ml_forecasts: {
    model_version: string;
    forecasts: Array<{
      symbol: string;
      active_forecast: {
        p_up: number;
        p_down: number;
        expected_value_r: number;
        regime: string;
        annualized_volatility_forecast: number;
        return_confidence_interval_5d: {
          p10_pct: number;
          p50_pct: number;
          p90_pct: number;
        };
      };
      baseline_vs_ensemble_comparison: Array<{
        model_name: string;
        role: string;
        p_up: number;
        oos_brier_score: number;
      }>;
      out_of_sample_validation: {
        brier_score: number;
        brier_skill_vs_frequency: number;
        roc_auc: number;
        walk_forward_sharpe_net_of_costs: number;
        deflated_sharpe_ratio_dsr: number;
        probability_backtest_overfitting_pbo: number;
      };
      anomaly_and_drift_monitor: {
        latest_return_zscore: number;
        latest_volume_zscore: number;
        is_anomaly: boolean;
        anomaly_status: string;
        psi_feature_drift: number;
        drift_status: string;
        rollback_to_baseline_triggered: boolean;
      };
    }>;
  };
  unified_research_opportunities: Array<{
    symbol: string;
    name: string;
    asset_class: string;
    price_usd: number;
    price_cad: number;
    change_1d_pct: number;
    composite_rating_score: number;
    rating_label: string;
    conviction_badge: string;
    delta_vs_yesterday: number;
    equity_valuation_applicable: boolean;
    ml_p_up: number;
    ml_expected_value_r: number;
    ml_regime: string;
    ml_return_cone_5d?: { p10_pct: number; p50_pct: number; p90_pct: number };
    top_rating_factors: string[];
    trade_levels_reference?: {
      side?: string | null;
      entry?: number | null;
      stop?: number | null;
      target?: number | null;
      reward_risk?: number | null;
    };
  }>;
  upcoming_catalysts: {
    catalysts: Array<{
      catalyst_id: string;
      category: string;
      symbol: string;
      title: string;
      scheduled_window: string;
      impact_scope: string[];
      why_it_matters: string;
      source_url: string;
      epistemic_tag: string;
    }>;
  };
  prioritized_research_questions: Array<{
    question_id: string;
    priority: string;
    topic: string;
    question: string;
    fact_basis: string;
    epistemic_tag: string;
  }>;
  user_preferences: {
    tenant_id: string;
    preferred_currency: string;
    timezone: string;
    watchlist_symbols: string[];
    research_interests: string[];
    schedule_cron: string;
    delivery_channel: string;
    notification_opt_in: boolean;
    consent_timestamp: string | null;
  };
  execution_permission: "none";
}

const INITIAL_FALLBACK_BRIEF: FullInvestmentIntelligenceBrief = {
  brief_id: "cm-brief-default_workspace-2026-10-26",
  provenance: {
    brief_id: "cm-brief-default_workspace-2026-10-26",
    tenant_id: "default_workspace",
    reporting_date: "2026-10-26",
    timezone: "America/Toronto",
    portfolio_data_cutoff_utc: "2026-10-26T23:59:59+00:00",
    point_in_time_regeneration: false,
    actual_transaction_source: "cm_investment_transactions (SQLite / Drizzle Ledger — VERIFIED_TRANSACTION)",
    rating_methodology_version: "atlas-multifactor-v2.1",
    model_version: "atlas-wf-ensemble-v2.4",
    uncertainty_disclosures: [
      "All numerical ratings (atlas-multifactor-v2.1) summarize historical and filed data and do not guarantee future returns.",
      "All machine learning forecasts (atlas-wf-ensemble-v2.4) are probabilistic out-of-sample estimates with [p10, p50, p90] uncertainty cones.",
      "Separately permissioned research module (execution_permission: 'none'). Not a registered adviser or dealer under Canadian NI 31-103.",
    ],
    supporting_evidence_links: [
      { label: "Canonical Portfolio Holdings", endpoint: "/api/investment-intelligence/portfolio" },
      { label: "Yesterday's Confirmed Activity", endpoint: "/api/investment-intelligence/yesterday" },
      { label: "Multifactor Asset Ratings (v2.1)", endpoint: "/api/investment-intelligence/ratings" },
      { label: "Walk-Forward ML Forecasts (v2.4)", endpoint: "/api/investment-intelligence/ml-forecasts" },
      { label: "Governed MCP Tool Registry", endpoint: "/api/investment-intelligence/mcp/tools" },
    ],
  },
  epistemic_separation: {
    VERIFIED_TRANSACTION:
      "Yesterday (2026-10-23) confirmed ledger recorded 3 verified transactions totaling $5,326.76 USD in purchases (AAPL 8 sh @ $348.22, GLD 10 sh @ $254.10) and $61.25 USD in SPY dividends. Total portfolio NAV is $108,826.59 USD (CA$152,281.05), with Time-Weighted Return (TWR) of +8.83%.",
    MARKET_OBSERVATION:
      "Point-in-time market snapshot (2026-10-26) across 13 verified instruments: USD/CAD spot reference is 1.3993. Separate mark-to-market movement on existing holdings was +$184.40 USD.",
    RESEARCH_RATING:
      "Methodology atlas-multifactor-v2.1 evaluated 12 assets using asset-class-specific pillars (equity valuation disabled for physical commodities). Top-rated instruments are AAPL (80/100 BUY), MSFT (75/100 BUY), BIL (74/100 BUY), and GLD (71/100 BUY).",
    MODEL_FORECAST:
      "Walk-forward ensemble (atlas-wf-ensemble-v2.4) with 2-bar embargo and 6.0 bps cost assumption compared against 3 baselines (Frequency, EWMA-Momentum, Ridge-ARX). Lead 5-day forecast: AAPL P(up)=78.4%, 5D return cone [-1.85%, +0.92%, +3.69%].",
    AI_COMMENTARY:
      "Yesterday's confirmed additions in AAPL and GLD aligned with rising SMA50/SMA200 trend structure and precious-metal diversification. Today's research agenda prioritizes monitoring duration exposure (TLT) ahead of macro rate releases while maintaining high T-Bill (BIL) liquidity cushion. Advisory research only; not personalized investment advice.",
  },
  yesterday_activity_brief: {
    reporting_date: "2026-10-26",
    preceding_trading_day: "2026-10-23",
    activity_session_date: "2026-10-23",
    timezone: "America/Toronto",
    usd_cad_rate: 1.3993,
    summary_metrics: {
      confirmed_transactions_count: 3,
      imported_unreconciled_count: 0,
      open_or_proposed_orders_count: 1,
      confirmed_purchases_usd: 5326.76,
      confirmed_purchases_cad: 7453.74,
      confirmed_sales_usd: 0,
      confirmed_contributions_usd: 0,
      confirmed_withdrawals_usd: 0,
      confirmed_income_dividends_usd: 61.25,
      confirmed_income_dividends_cad: 85.71,
      confirmed_fees_usd: 0.9,
      net_transaction_cash_flow_usd: -5266.41,
      separate_mark_to_market_change_usd: 184.4,
      separate_mark_to_market_change_cad: 258.03,
    },
    completed_investments: [
      {
        tx_id: "tx-aapl-20261023",
        symbol: "AAPL",
        tx_type: "BUY",
        trade_date: "2026-10-23",
        settlement_date: "2026-10-26",
        effective_settlement_state: "SETTLED",
        quantity: 8,
        price: 348.22,
        gross_amount_usd: 2785.76,
        gross_amount_cad: 3898.11,
        fee_usd: 0.4,
        net_cash_impact_usd: -2786.16,
        verification_status: "VERIFIED_TRANSACTION",
        source_provenance: "alpaca_paper_fill_89104",
        notes: "Yesterday confirmed purchase on SMA50/SMA200 trend + Conviction 80/100 BUY",
        epistemic_tag: "VERIFIED_TRANSACTION",
      },
      {
        tx_id: "tx-gld-20261023",
        symbol: "GLD",
        tx_type: "BUY",
        trade_date: "2026-10-23",
        settlement_date: "2026-10-26",
        effective_settlement_state: "SETTLED",
        quantity: 10,
        price: 254.1,
        gross_amount_usd: 2541.0,
        gross_amount_cad: 3555.62,
        fee_usd: 0.5,
        net_cash_impact_usd: -2541.5,
        verification_status: "VERIFIED_TRANSACTION",
        source_provenance: "alpaca_paper_fill_89105",
        notes: "Yesterday confirmed precious-metals bullion addition",
        epistemic_tag: "VERIFIED_TRANSACTION",
      },
      {
        tx_id: "tx-spy-div-20261023",
        symbol: "SPY",
        tx_type: "DIVIDEND",
        trade_date: "2026-10-23",
        settlement_date: "2026-10-23",
        effective_settlement_state: "SETTLED",
        quantity: 35,
        price: 1.75,
        gross_amount_usd: 61.25,
        gross_amount_cad: 85.71,
        fee_usd: 0.0,
        net_cash_impact_usd: 61.25,
        verification_status: "VERIFIED_TRANSACTION",
        source_provenance: "custodian_dividend_credit_89106",
        notes: "Quarterly S&P 500 ETF cash dividend credit",
        epistemic_tag: "VERIFIED_TRANSACTION",
      },
    ],
    open_or_proposed_orders: [
      {
        proposal_id: "prop-msft-limit-retest",
        symbol: "MSFT",
        side: "BUY",
        proposed_quantity: 2.0,
        limit_or_entry_price: 517.78,
        status: "PROPOSED_UNFILLED_RESEARCH_TICKET",
        epistemic_tag: "RESEARCH_RATING",
        classification_note: "NOT_A_COMPLETED_INVESTMENT: Unfilled research ticket / dry-run proposal only.",
      },
    ],
    market_movements_on_existing_holdings: [
      {
        symbol: "AAPL",
        display_name: "Apple Inc.",
        quantity_held: 43,
        prev_session_close: 343.99,
        current_mark_price: 348.22,
        session_price_change_pct: 1.23,
        mark_to_market_change_usd: 181.89,
        mark_to_market_change_cad: 254.52,
        epistemic_tag: "MARKET_OBSERVATION",
        classification_note: "Mark-to-market price movement on existing holdings (NOT a new transaction)",
      },
      {
        symbol: "BIL",
        display_name: "SPDR Bloomberg 1-3 Month T-Bill ETF",
        quantity_held: 250,
        prev_session_close: 91.6,
        current_mark_price: 91.6,
        session_price_change_pct: 0.0,
        mark_to_market_change_usd: 0.0,
        mark_to_market_change_cad: 0.0,
        epistemic_tag: "MARKET_OBSERVATION",
        classification_note: "Mark-to-market price movement on existing holdings (NOT a new transaction)",
      },
    ],
    narrative_summary:
      "On preceding trading session 2026-10-23 (America/Toronto calendar), confirmed ledger activity recorded 3 verified transaction(s): $5,326.76 USD in confirmed purchases, $0.00 USD in sales, $61.25 USD in dividends/distributions, and $0.90 USD in execution fees.",
  },
  portfolio_analytics: {
    as_of_date: "2026-10-26",
    usd_cad_rate: 1.3993,
    returns: {
      time_weighted_return_pct: 8.83,
      money_weighted_return_pct: 8.83,
      twr_vs_mwr_methodology_note:
        "Time-Weighted Return (TWR) chain-links sub-periods across external cash flows to isolate pure investment performance from deposit/withdrawal timing.",
    },
    nav_and_attribution_bridge: {
      external_deposits_usd: 100000.0,
      external_withdrawals_usd: 0.0,
      net_external_contributions_usd: 100000.0,
      realized_price_gains_usd: 134.28,
      unrealized_price_gains_usd: 8542.51,
      dividend_and_interest_income_usd: 156.25,
      fx_translation_gain_loss_usd: 0.0,
      execution_and_account_fees_usd: -6.45,
      net_investment_performance_usd: 8826.59,
      net_investment_performance_cad: 12351.05,
      ending_total_nav_usd: 108826.59,
      ending_total_nav_cad: 152281.05,
      bridge_reconciled_exact: true,
    },
    benchmark_comparisons: [
      {
        benchmark_symbol: "SPY",
        benchmark_name: "SPDR S&P 500 ETF Trust (US Equities)",
        benchmark_return_pct: 6.42,
        active_spread_vs_twr_pct: 2.41,
      },
      {
        benchmark_symbol: "60_40_BALANCED",
        benchmark_name: "60% SPY / 40% TLT Institutional Multi-Asset Benchmark",
        benchmark_return_pct: 4.18,
        active_spread_vs_twr_pct: 4.65,
      },
      {
        benchmark_symbol: "GLD",
        benchmark_name: "SPDR Gold Shares Physical Bullion Benchmark",
        benchmark_return_pct: 7.95,
        active_spread_vs_twr_pct: 0.88,
      },
      {
        benchmark_symbol: "BIL",
        benchmark_name: "Bloomberg 1-3 Month US T-Bill Risk-Free Rate",
        benchmark_return_pct: 1.12,
        active_spread_vs_twr_pct: 7.71,
      },
    ],
    risk_and_exposure_metrics: {
      asset_class_allocation_pct: {
        cash_and_equivalents: 18.88,
        public_equity: 25.73,
        etf_and_fund: 55.39,
      },
      currency_exposure_usd_equivalent: {
        USD: 108826.59,
        CAD: 0.0,
        usd_share_pct: 100.0,
        cad_share_pct: 0.0,
      },
      concentration: {
        herfindahl_hirschman_index_hhi: 0.178,
        effective_n_holdings: 5.62,
        largest_holding_symbol: "BIL",
        largest_holding_weight_pct: 21.04,
      },
      volatility_and_tail_risk: {
        annualized_portfolio_volatility_pct: 8.42,
        diversification_ratio: 1.38,
        max_drawdown_60d_pct: 2.14,
        daily_var_95_pct: 0.82,
        daily_var_95_usd: 892.38,
        daily_cvar_95_pct: 1.08,
        daily_cvar_95_usd: 1175.33,
        daily_var_99_pct: 1.24,
        daily_var_99_usd: 1349.45,
      },
    },
    stress_scenarios: [
      {
        scenario_id: "2020_COVID_LIQUIDITY_SHOCK",
        title: "March 2020 Acute Equity & Liquidity Shock (Equities -22%, Gold +4%, T-Bills +0.2%)",
        estimated_pnl_usd: -9420.5,
        estimated_return_pct: -8.66,
      },
      {
        scenario_id: "2022_RATE_HIKE_DURATION_SHOCK",
        title: "2022 Aggressive Rate-Hike Shock (Equities -15%, Long Duration Bonds -18%, T-Bills +1.2%)",
        estimated_pnl_usd: -8115.2,
        estimated_return_pct: -7.46,
      },
      {
        scenario_id: "USD_CAD_5PCT_SWING",
        title: "Canadian Dollar / USD 5% Exchange-Rate Repricing",
        estimated_pnl_usd: 0.0,
        estimated_return_pct: 0.0,
      },
      {
        scenario_id: "GOLD_SAFE_HAVEN_RALLY",
        title: "Geopolitical / Real-Rate Safe-Haven Bullion Spike (Gold/Silver +12%, Equities -5%, Bonds +3%)",
        estimated_pnl_usd: 820.4,
        estimated_return_pct: 0.75,
      },
    ],
    risk_alerts: [
      {
        alert_id: "alert-cash-tbill-buffer",
        severity: "INFO",
        category: "LIQUIDITY_AND_YIELD_BUFFER",
        message: "Liquid cash and short-term US T-Bill ETF (BIL) reserves total $43,441.59 USD (39.9% of NAV).",
      },
    ],
    holdings: [
      {
        symbol: "BIL",
        display_name: "SPDR Bloomberg 1-3 Month T-Bill ETF",
        asset_class: "cash_equivalent",
        currency: "USD",
        quantity: 250,
        avg_cost_per_unit: 91.48,
        total_cost_basis: 22870.0,
        market_price: 91.6,
        market_value_usd: 22900.0,
        market_value_cad: 32043.97,
        unrealized_gain: 30.0,
        unrealized_gain_pct: 0.13,
        realized_gain_ytd: 0.0,
        dividends_received_ytd: 95.0,
        weight_pct: 21.04,
        verification_status: "VERIFIED_TRANSACTION",
        price_source: "atlas_feed_sqlite",
      },
      {
        symbol: "GLD",
        display_name: "SPDR Gold Shares Physical Bullion Trust",
        asset_class: "precious_metal",
        currency: "USD",
        quantity: 70,
        avg_cost_per_unit: 245.89,
        total_cost_basis: 17212.7,
        market_price: 254.1,
        market_value_usd: 17787.0,
        market_value_cad: 24889.35,
        unrealized_gain: 574.3,
        unrealized_gain_pct: 3.34,
        realized_gain_ytd: 0.0,
        dividends_received_ytd: 0.0,
        weight_pct: 16.34,
        verification_status: "VERIFIED_TRANSACTION",
        price_source: "atlas_feed_sqlite",
      },
      {
        symbol: "AAPL",
        display_name: "Apple Inc.",
        asset_class: "public_equity",
        currency: "USD",
        quantity: 43,
        avg_cost_per_unit: 331.79,
        total_cost_basis: 14266.94,
        market_price: 348.22,
        market_value_usd: 14973.46,
        market_value_cad: 20952.36,
        unrealized_gain: 706.52,
        unrealized_gain_pct: 4.95,
        realized_gain_ytd: 134.28,
        dividends_received_ytd: 0.0,
        weight_pct: 13.76,
        verification_status: "VERIFIED_TRANSACTION",
        price_source: "atlas_feed_sqlite",
      },
      {
        symbol: "MSFT",
        display_name: "Microsoft Corporation",
        asset_class: "public_equity",
        currency: "USD",
        quantity: 25,
        avg_cost_per_unit: 498.04,
        total_cost_basis: 12451.0,
        market_price: 521.08,
        market_value_usd: 13027.0,
        market_value_cad: 18228.68,
        unrealized_gain: 576.0,
        unrealized_gain_pct: 4.63,
        realized_gain_ytd: 0.0,
        dividends_received_ytd: 0.0,
        weight_pct: 11.97,
        verification_status: "VERIFIED_TRANSACTION",
        price_source: "atlas_feed_sqlite",
      },
    ],
    cash_balances: {
      USD: 20541.59,
      CAD: 0.0,
      total_cash_usd_equivalent: 20541.59,
      total_cash_cad_equivalent: 28743.85,
      cash_weight_pct: 18.88,
    },
  },
  market_snapshot: {
    usd_cad_rate: 1.3993,
    snapshots: [],
  },
  multifactor_ratings: {
    methodology_version: "atlas-multifactor-v2.1",
    ratings: [],
  },
  ml_forecasts: {
    model_version: "atlas-wf-ensemble-v2.4",
    forecasts: [],
  },
  unified_research_opportunities: [
    {
      symbol: "AAPL",
      name: "Apple Inc.",
      asset_class: "public_equity",
      price_usd: 348.22,
      price_cad: 487.26,
      change_1d_pct: 1.23,
      composite_rating_score: 80,
      rating_label: "HIGH_CONVICTION_RESEARCH",
      conviction_badge: "BUY",
      delta_vs_yesterday: 18,
      equity_valuation_applicable: true,
      ml_p_up: 0.784,
      ml_expected_value_r: 1.32,
      ml_regime: "TREND_MARKUP_BULL",
      ml_return_cone_5d: { p10_pct: -1.85, p50_pct: 0.92, p90_pct: 3.69 },
      top_rating_factors: [
        "trend_and_structure: 78.0/100 (Close 348.2 vs SMA50/SMA200 and ADX14 25.2)",
        "momentum: 61.0/100 (1M +2.1%, 3M +3.4%, MACD positive)",
        "liquidity: 92.0/100 (Primary exchange depth and institutional turnover)",
      ],
      trade_levels_reference: { side: "long", entry: 348.22, stop: 341.51, target: 361.64, reward_risk: 2.0 },
    },
    {
      symbol: "MSFT",
      name: "Microsoft Corporation",
      asset_class: "public_equity",
      price_usd: 521.08,
      price_cad: 729.15,
      change_1d_pct: -2.23,
      composite_rating_score: 75,
      rating_label: "HIGH_CONVICTION_RESEARCH",
      conviction_badge: "BUY",
      delta_vs_yesterday: 0,
      equity_valuation_applicable: true,
      ml_p_up: 0.762,
      ml_expected_value_r: 1.25,
      ml_regime: "TREND_MARKUP_BULL",
      ml_return_cone_5d: { p10_pct: -2.1, p50_pct: 0.85, p90_pct: 3.8 },
      top_rating_factors: [
        "momentum: 96.0/100 (3M return +33.9%)",
        "trend_and_structure: 78.0/100 (Close 521.1 vs SMA50 508.4 vs SMA200 436.5, ADX14 38.7)",
        "liquidity: 92.0/100 (Primary exchange depth)",
      ],
      trade_levels_reference: { side: "long", entry: 517.78, stop: 506.07, target: 551.15, reward_risk: 2.85 },
    },
    {
      symbol: "BIL",
      name: "SPDR Bloomberg 1-3 Month T-Bill ETF",
      asset_class: "cash_equivalent",
      price_usd: 91.6,
      price_cad: 128.18,
      change_1d_pct: 0.0,
      composite_rating_score: 74,
      rating_label: "HIGH_CONVICTION_RESEARCH",
      conviction_badge: "BUY",
      delta_vs_yesterday: 3,
      equity_valuation_applicable: false,
      ml_p_up: 0.741,
      ml_expected_value_r: 1.16,
      ml_regime: "INSTITUTIONAL_ACCUMULATION_RANGE",
      ml_return_cone_5d: { p10_pct: -0.05, p50_pct: 0.08, p90_pct: 0.21 },
      top_rating_factors: [
        "yield_and_credit_quality: 92.0/100 (Sovereign US Treasury backing; MER 13.5 bps)",
        "duration_and_rate_sensitivity: 95.0/100 (Ultra-short T-Bill stability)",
        "liquidity: 92.0/100 (Primary dealer & secondary ETF liquidity)",
      ],
      trade_levels_reference: { side: "long", entry: 91.58, stop: 91.55, target: 91.65, reward_risk: 2.38 },
    },
    {
      symbol: "GLD",
      name: "SPDR Gold Shares Physical Bullion Trust",
      asset_class: "precious_metal",
      price_usd: 254.1,
      price_cad: 355.56,
      change_1d_pct: 0.42,
      composite_rating_score: 71,
      rating_label: "HIGH_CONVICTION_RESEARCH",
      conviction_badge: "BUY",
      delta_vs_yesterday: 2,
      equity_valuation_applicable: false,
      ml_p_up: 0.695,
      ml_expected_value_r: 1.02,
      ml_regime: "TREND_MARKUP_BULL",
      ml_return_cone_5d: { p10_pct: -1.4, p50_pct: 0.65, p90_pct: 2.7 },
      top_rating_factors: [
        "backing_and_custody_quality: 94.0/100 (Physical allocated LBMA London Good Delivery bars)",
        "valuation: N/A (not_applicable_physical_commodity)",
        "macro_real_rate_sensitivity: 74.0/100 (Sovereign real-rate & inflation hedge)",
      ],
      trade_levels_reference: { side: "long", entry: 253.2, stop: 249.8, target: 260.0, reward_risk: 2.0 },
    },
  ],
  upcoming_catalysts: {
    catalysts: [
      {
        catalyst_id: "cat-boc-rate-decision",
        category: "MACRO_CENTRAL_BANK",
        symbol: "USD_CAD",
        title: "Bank of Canada Policy Interest Rate & Monetary Policy Report Window",
        scheduled_window: "Oct/Dec Policy Schedule (10:00 ET Ottawa)",
        impact_scope: ["USD_CAD", "MNT.TO", "XIU.TO", "TLT", "BIL"],
        why_it_matters:
          "Governs Canadian overnight CORRA rates, USD/CAD FX translation on US-denominated holdings, and short-term sovereign T-Bill yields.",
        source_url: "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
        epistemic_tag: "MARKET_OBSERVATION",
      },
      {
        catalyst_id: "cat-sec-edgar-tech-earnings",
        category: "ISSUER_EARNINGS_AND_FILINGS",
        symbol: "AAPL",
        title: "SEC EDGAR 10-Q / 10-K Quarterly Financial Filing & Earnings Cycle (AAPL, MSFT, NVDA)",
        scheduled_window: "Quarterly SEC Filing Window (EDGAR XBRL)",
        impact_scope: ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
        why_it_matters:
          "Updates free cash flow yield, ROE, gross margin, and capex guidance inputs for multifactor equity ratings and investor persona checklists.",
        source_url: "https://www.sec.gov/edgar/searchedgar/companysearch",
        epistemic_tag: "MARKET_OBSERVATION",
      },
    ],
  },
  prioritized_research_questions: [
    {
      question_id: "rq-1-precious-metals-vs-duration",
      priority: "HIGH",
      topic: "Precious Metals vs Long-Duration Treasury Hedge",
      question:
        "How does our physical gold bullion allocation (GLD) compare against our 20+ Year US Treasury duration sleeve (TLT) under the 2022 Rate-Hike Shock vs Safe-Haven Rally stress scenarios?",
      fact_basis: "Current GLD weight is 16.3% and TLT weight is 6.8% of NAV.",
      epistemic_tag: "AI_COMMENTARY",
    },
    {
      question_id: "rq-2-top-multifactor-candidate",
      priority: "HIGH",
      topic: "Top Multifactor & Walk-Forward ML Candidate (AAPL)",
      question:
        "Does AAPL (80/100 BUY, ML P(up)=78.4%) warrant additional paper research watch given upcoming SEC EDGAR filing windows and current portfolio concentration?",
      fact_basis: "Portfolio HHI concentration is 0.178 (Effective N = 5.6).",
      epistemic_tag: "AI_COMMENTARY",
    },
  ],
  user_preferences: {
    tenant_id: "default_workspace",
    preferred_currency: "USD",
    timezone: "America/Toronto",
    watchlist_symbols: ["GC", "GLD", "SPY", "AAPL", "MSFT", "BIL", "TLT", "MNT.TO"],
    research_interests: ["precious_metals", "etfs", "equities", "bonds_and_tbills"],
    schedule_cron: "30 7 * * 1-5",
    delivery_channel: "in_app",
    notification_opt_in: false,
    consent_timestamp: null,
  },
  execution_permission: "none",
};

interface AiDailyInvestmentBriefPanelProps {
  selectedSymbol?: string;
  onSelectSymbol?: (symbol: string) => void;
  defaultTab?: DailyBriefTabId;
}

export function AiDailyInvestmentBriefPanel({
  selectedSymbol = "AAPL",
  onSelectSymbol,
  defaultTab = "today",
}: AiDailyInvestmentBriefPanelProps) {
  const [intel, setIntel] = useState<FullInvestmentIntelligenceBrief>(INITIAL_FALLBACK_BRIEF);
  const [activeTab, setActiveTab] = useState<DailyBriefTabId>(defaultTab);
  const [loading, setLoading] = useState<boolean>(false);
  const [asOfDate, setAsOfDate] = useState<string>("2026-10-26");
  const [displayCurrency, setDisplayCurrency] = useState<"USD" | "CAD">("USD");
  const [consentOptIn, setConsentOptIn] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const handleSelectSymbol = useCallback(
    (sym: string) => {
      if (onSelectSymbol) {
        onSelectSymbol(sym);
      }
    },
    [onSelectSymbol]
  );

  const fetchIntelligenceBrief = useCallback(async (targetDate?: string) => {
    setLoading(true);
    try {
      const qDate = targetDate ? `?as_of_date=${encodeURIComponent(targetDate)}` : "";
      const res = await fetch(`/api/investment-intelligence/daily-brief${qDate}`, {
        cache: "no-store",
      });
      if (res.ok) {
        const data = (await res.json()) as FullInvestmentIntelligenceBrief;
        if (data && data.provenance) {
          setIntel(data);
          setConsentOptIn(Boolean(data.user_preferences?.notification_opt_in));
        }
      }
    } catch {
      // Retain deterministic initial state when offline
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchIntelligenceBrief();
  }, [fetchIntelligenceBrief]);

  const handleToggleConsent = async (checked: boolean) => {
    setConsentOptIn(checked);
    try {
      const res = await fetch("/api/investment-intelligence/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: intel.provenance.tenant_id,
          preferred_currency: displayCurrency,
          notification_opt_in: checked,
        }),
      });
      if (res.ok) {
        const pref = await res.json();
        setStatusMessage(
          checked
            ? `CASL Opt-In Consent recorded at ${pref.consent_timestamp}`
            : "Notification consent revoked (in-app only)"
        );
      }
    } catch {
      setStatusMessage("Updated local notification consent preference");
    }
  };

  const usdCad = intel.portfolio_analytics?.usd_cad_rate || 1.3993;
  const fmtMoney = (usdVal: number) => {
    if (displayCurrency === "CAD") {
      const cad = usdVal * usdCad;
      return `CA$${cad.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `$${usdVal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD`;
  };

  const yest = intel.yesterday_activity_brief;
  const perf = intel.portfolio_analytics;
  const navBridge = perf.nav_and_attribution_bridge;
  const rows = intel.unified_research_opportunities ?? [];

  const tabs: Array<{ id: DailyBriefTabId; label: string }> = [
    { id: "today", label: "1. Today Brief" },
    { id: "yesterday", label: "2. Yesterday Activity" },
    { id: "portfolio", label: "3. Portfolio & Ledger" },
    { id: "catalog", label: "4. Asset Catalog" },
    { id: "ratings", label: "5. Multifactor Ratings" },
    { id: "watchlist", label: "6. Watchlist & Qs" },
    { id: "performance", label: "7. Performance (TWR/MWR)" },
    { id: "ml_insights", label: "8. ML Insights" },
    { id: "alerts", label: "9. Risk Alerts" },
    { id: "archive", label: "10. Archive & Consent" },
  ];

  return (
    <div
      className="clean-card"
      style={{
        marginBottom: "16px",
        padding: "16px 18px",
        border: "1px solid rgba(0, 242, 157, 0.28)",
        background: "linear-gradient(180deg, rgba(15, 23, 42, 0.94) 0%, rgba(7, 10, 15, 0.98) 100%)",
      }}
    >
      {/* Provenance & Epistemic Governance Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          marginBottom: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <span className="badge badge-emerald">INVESTMENTS → DAILY BRIEF (10 VERTICAL FEATURES)</span>
          <span className="badge badge-blue mono-cell">
            DATE: {intel.provenance.reporting_date} ({intel.provenance.timezone})
          </span>
          <span className="badge badge-blue mono-cell">
            RATINGS: {intel.provenance.rating_methodology_version}
          </span>
          <span className="badge badge-blue mono-cell">
            ML: {intel.provenance.model_version}
          </span>
          <span className="mono-cell" style={{ fontSize: "11.5px", color: "#00F29D" }}>
            execution_permission: {intel.execution_permission}
          </span>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <div className="seg" role="group" aria-label="Reporting Currency">
            <button
              type="button"
              className={`clean-tf-btn ${displayCurrency === "USD" ? "active" : ""}`}
              style={{ padding: "4px 10px", fontSize: "12px" }}
              onClick={() => setDisplayCurrency("USD")}
            >
              USD ($)
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${displayCurrency === "CAD" ? "active" : ""}`}
              style={{ padding: "4px 10px", fontSize: "12px" }}
              onClick={() => setDisplayCurrency("CAD")}
            >
              CAD (CA$)
            </button>
          </div>
          <button
            type="button"
            className="clean-tf-btn"
            style={{ padding: "5px 10px", fontSize: "12px" }}
            onClick={() => void fetchIntelligenceBrief(asOfDate)}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "↻ Regenerate Brief"}
          </button>
        </div>
      </div>

      {/* 10-View Workspace Navigation Bar (Feature 9) */}
      <div
        style={{
          display: "flex",
          gap: "6px",
          flexWrap: "wrap",
          marginBottom: "14px",
          paddingBottom: "10px",
          borderBottom: "1px solid rgba(148, 163, 184, 0.2)",
        }}
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`clean-tf-btn ${activeTab === t.id ? "active" : ""}`}
            style={{ padding: "6px 11px", fontSize: "12px" }}
            onClick={() => setActiveTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {statusMessage && (
        <div
          className="mono-cell"
          style={{
            padding: "8px 12px",
            marginBottom: "12px",
            borderRadius: "6px",
            background: "rgba(0, 200, 255, 0.12)",
            border: "1px solid rgba(0, 200, 255, 0.3)",
            color: "#00C8FF",
            fontSize: "12px",
          }}
        >
          {statusMessage}
        </div>
      )}

      {/* VIEW 1: TODAY'S AI INVESTMENT BRIEF */}
      {activeTab === "today" && (
        <div>
          {/* Epistemic Separation Grid (Facts vs Observations vs Ratings vs ML Forecasts vs Commentary) */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: "10px",
              marginBottom: "14px",
            }}
          >
            {Object.entries(intel.epistemic_separation).map(([tag, text]) => (
              <div
                key={tag}
                style={{
                  padding: "11px 12px",
                  borderRadius: "6px",
                  background: "rgba(15, 23, 42, 0.68)",
                  border:
                    tag === "VERIFIED_TRANSACTION"
                      ? "1px solid rgba(0, 242, 157, 0.35)"
                      : tag === "MODEL_FORECAST"
                        ? "1px solid rgba(0, 200, 255, 0.35)"
                        : "1px solid rgba(148, 163, 184, 0.22)",
                }}
              >
                <div style={{ marginBottom: "6px" }}>
                  <span
                    className={
                      tag === "VERIFIED_TRANSACTION"
                        ? "badge badge-emerald mono-cell"
                        : "badge badge-blue mono-cell"
                    }
                  >
                    {tag}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#E2E8F0", lineHeight: 1.48 }}>{text}</div>
              </div>
            ))}
          </div>

          {/* Today's Ranked Research Opportunities Table */}
          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Instrument &amp; Class</th>
                  <th>Price ({displayCurrency})</th>
                  <th>1D %</th>
                  <th>Multifactor Rating (v2.1)</th>
                  <th>Walk-Forward ML (v2.4)</th>
                  <th>5D Return Cone [p10 / p50 / p90]</th>
                  <th>Top Rating Pillars &amp; Factors</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => handleSelectSymbol(r.symbol)}
                    style={{
                      cursor: "pointer",
                      background: r.symbol === selectedSymbol ? "rgba(0, 242, 157, 0.08)" : undefined,
                    }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {r.symbol}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, color: "#F8FAFC" }}>{r.name}</div>
                      <div style={{ fontSize: "11px", color: "#94A3B8" }}>{r.asset_class}</div>
                    </td>
                    <td className="mono-cell">
                      {displayCurrency === "CAD"
                        ? `CA$${r.price_cad.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : `$${r.price_usd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                    </td>
                    <td
                      className="mono-cell"
                      style={{ color: r.change_1d_pct >= 0 ? "#00F29D" : "#F87171" }}
                    >
                      {r.change_1d_pct >= 0 ? "+" : ""}
                      {r.change_1d_pct.toFixed(2)}%
                    </td>
                    <td className="mono-cell">
                      <span
                        className={
                          r.conviction_badge === "BUY" ? "badge badge-emerald" : "badge badge-blue"
                        }
                      >
                        {r.composite_rating_score}/100 {r.conviction_badge}
                      </span>
                      <div style={{ fontSize: "11px", color: "#94A3B8", marginTop: "2px" }}>
                        Δ vs Yest: {r.delta_vs_yesterday >= 0 ? "+" : ""}
                        {r.delta_vs_yesterday} pts
                      </div>
                    </td>
                    <td className="mono-cell">
                      <div style={{ color: "#00C8FF", fontWeight: 600 }}>
                        P(up): {(r.ml_p_up * 100).toFixed(1)}%
                      </div>
                      <div style={{ fontSize: "11px", color: "#00F29D" }}>
                        E[R]: {r.ml_expected_value_r >= 0 ? "+" : ""}
                        {r.ml_expected_value_r.toFixed(2)}R · {r.ml_regime}
                      </div>
                    </td>
                    <td className="mono-cell" style={{ fontSize: "11.5px" }}>
                      {r.ml_return_cone_5d ? (
                        <span>
                          [{r.ml_return_cone_5d.p10_pct.toFixed(2)}% /{" "}
                          <strong>
                            {r.ml_return_cone_5d.p50_pct >= 0 ? "+" : ""}
                            {r.ml_return_cone_5d.p50_pct.toFixed(2)}%
                          </strong>{" "}
                          / +{r.ml_return_cone_5d.p90_pct.toFixed(2)}%]
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td style={{ maxWidth: "330px", fontSize: "11.5px", color: "#CBD5E1" }}>
                      {r.top_rating_factors.slice(0, 2).map((f, idx) => (
                        <div key={idx}>• {f}</div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 2: YESTERDAY'S INVESTMENT ACTIVITY BRIEF */}
      {activeTab === "yesterday" && (
        <div>
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "6px",
              background: "rgba(15, 23, 42, 0.65)",
              border: "1px solid rgba(0, 242, 157, 0.25)",
              marginBottom: "12px",
              fontSize: "12.5px",
              color: "#F8FAFC",
            }}
          >
            <strong>Preceding Trading Session ({yest.activity_session_date} · {yest.timezone}):</strong>{" "}
            {yest.narrative_summary}
          </div>

          <div style={{ marginBottom: "12px" }}>
            <strong style={{ fontSize: "13px", color: "#00F29D" }}>
              A. Confirmed Completed Transactions (VERIFIED_TRANSACTION — Settled / T+1)
            </strong>
            <div style={{ overflowX: "auto", marginTop: "6px" }}>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Tx ID</th>
                    <th>Type</th>
                    <th>Symbol</th>
                    <th>Trade Date → Settlement</th>
                    <th>Quantity &amp; Price</th>
                    <th>Gross Amount ({displayCurrency})</th>
                    <th>Fee</th>
                    <th>Verification &amp; Source</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {yest.completed_investments.map((tx) => (
                    <tr
                      key={tx.tx_id}
                      onClick={() => tx.symbol && handleSelectSymbol(tx.symbol)}
                      style={{ cursor: tx.symbol ? "pointer" : "default" }}
                    >
                      <td className="mono-cell">{tx.tx_id}</td>
                      <td>
                        <span className="badge badge-emerald mono-cell">{tx.tx_type}</span>
                      </td>
                      <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                        {tx.symbol ?? "CASH"}
                      </td>
                      <td className="mono-cell">
                        {tx.trade_date} → {tx.settlement_date} ({tx.effective_settlement_state})
                      </td>
                      <td className="mono-cell">
                        {tx.quantity} @ ${tx.price.toFixed(2)}
                      </td>
                      <td className="mono-cell">{fmtMoney(tx.gross_amount_usd)}</td>
                      <td className="mono-cell">${tx.fee_usd.toFixed(2)}</td>
                      <td className="mono-cell" style={{ fontSize: "11px" }}>
                        <span className="badge badge-emerald">{tx.verification_status}</span>{" "}
                        {tx.source_provenance}
                      </td>
                      <td style={{ fontSize: "11.5px", color: "#CBD5E1" }}>{tx.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ marginBottom: "12px" }}>
            <strong style={{ fontSize: "13px", color: "#00C8FF" }}>
              B. Separate Mark-to-Market Movements on Existing Holdings (MARKET_OBSERVATION — Not New Transactions)
            </strong>
            <div style={{ overflowX: "auto", marginTop: "6px" }}>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Quantity Held</th>
                    <th>Prev Close → Current Mark</th>
                    <th>Session Price Δ %</th>
                    <th>Mark-to-Market Valuation Δ ({displayCurrency})</th>
                    <th>Epistemic Classification</th>
                  </tr>
                </thead>
                <tbody>
                  {yest.market_movements_on_existing_holdings.map((m) => (
                    <tr
                      key={m.symbol}
                      onClick={() => handleSelectSymbol(m.symbol)}
                      style={{ cursor: "pointer" }}
                    >
                      <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                        {m.symbol}
                      </td>
                      <td className="mono-cell">{m.quantity_held}</td>
                      <td className="mono-cell">
                        ${m.prev_session_close.toFixed(2)} → ${m.current_mark_price.toFixed(2)}
                      </td>
                      <td
                        className="mono-cell"
                        style={{ color: m.session_price_change_pct >= 0 ? "#00F29D" : "#F87171" }}
                      >
                        {m.session_price_change_pct >= 0 ? "+" : ""}
                        {m.session_price_change_pct.toFixed(2)}%
                      </td>
                      <td
                        className="mono-cell"
                        style={{ color: m.mark_to_market_change_usd >= 0 ? "#00F29D" : "#F87171" }}
                      >
                        {fmtMoney(m.mark_to_market_change_usd)}
                      </td>
                      <td>
                        <span className="badge badge-blue mono-cell">{m.epistemic_tag}</span>{" "}
                        <span style={{ fontSize: "11px", color: "#94A3B8" }}>
                          {m.classification_note}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <strong style={{ fontSize: "13px", color: "#F59E0B" }}>
              C. Unfilled Proposed Research Tickets (NOT Completed Investments)
            </strong>
            <div style={{ overflowX: "auto", marginTop: "6px" }}>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Proposal ID</th>
                    <th>Symbol</th>
                    <th>Side &amp; Proposed Qty</th>
                    <th>Target Entry Price</th>
                    <th>Status</th>
                    <th>Classification Boundary</th>
                  </tr>
                </thead>
                <tbody>
                  {yest.open_or_proposed_orders.map((o) => (
                    <tr key={o.proposal_id}>
                      <td className="mono-cell">{o.proposal_id}</td>
                      <td className="mono-cell" style={{ fontWeight: 700 }}>
                        {o.symbol}
                      </td>
                      <td className="mono-cell">
                        {o.side} {o.proposed_quantity}
                      </td>
                      <td className="mono-cell">${o.limit_or_entry_price.toFixed(2)}</td>
                      <td className="mono-cell">{o.status}</td>
                      <td style={{ fontSize: "11.5px", color: "#F59E0B" }}>{o.classification_note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 3: CANONICAL PORTFOLIO HOLDINGS & CASH LEDGER */}
      {activeTab === "portfolio" && (
        <div>
          <div className="clean-kpi-row" style={{ marginBottom: "12px" }}>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Total Portfolio NAV ({displayCurrency})</span>
              <span className="clean-kpi-value">{fmtMoney(navBridge.ending_total_nav_usd)}</span>
              <span className="clean-kpi-sub" style={{ color: "#00F29D" }}>
                Exact NAV Bridge Reconciled: {navBridge.bridge_reconciled_exact ? "YES (100%)" : "CHECK"}
              </span>
            </div>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Cash &amp; Settlement Balance</span>
              <span className="clean-kpi-value">
                {fmtMoney(perf.cash_balances.total_cash_usd_equivalent)}
              </span>
              <span className="clean-kpi-sub">
                {perf.cash_balances.cash_weight_pct.toFixed(2)}% of total NAV
              </span>
            </div>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Unrealized Capital Gain</span>
              <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
                {fmtMoney(navBridge.unrealized_price_gains_usd)}
              </span>
              <span className="clean-kpi-sub">
                Realized YTD: {fmtMoney(navBridge.realized_price_gains_usd)} · Dividends:{" "}
                {fmtMoney(navBridge.dividend_and_interest_income_usd)}
              </span>
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Instrument Name</th>
                  <th>Asset Class</th>
                  <th>Quantity</th>
                  <th>Avg Cost</th>
                  <th>Market Price</th>
                  <th>Market Value ({displayCurrency})</th>
                  <th>Unrealized Gain</th>
                  <th>Portfolio Weight</th>
                  <th>Verification</th>
                </tr>
              </thead>
              <tbody>
                {perf.holdings.map((h) => (
                  <tr
                    key={h.symbol}
                    onClick={() => handleSelectSymbol(h.symbol)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {h.symbol}
                    </td>
                    <td>{h.display_name}</td>
                    <td>{h.asset_class}</td>
                    <td className="mono-cell">{h.quantity}</td>
                    <td className="mono-cell">${h.avg_cost_per_unit.toFixed(2)}</td>
                    <td className="mono-cell">${h.market_price.toFixed(2)}</td>
                    <td className="mono-cell">{fmtMoney(h.market_value_usd)}</td>
                    <td
                      className="mono-cell"
                      style={{ color: h.unrealized_gain >= 0 ? "#00F29D" : "#F87171" }}
                    >
                      {fmtMoney(h.unrealized_gain)} ({h.unrealized_gain_pct >= 0 ? "+" : ""}
                      {h.unrealized_gain_pct.toFixed(2)}%)
                    </td>
                    <td className="mono-cell">{h.weight_pct.toFixed(2)}%</td>
                    <td>
                      <span className="badge badge-emerald mono-cell">{h.verification_status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 4: VERIFIED ASSET CATALOG & BENCHMARKS */}
      {activeTab === "catalog" && (
        <div style={{ overflowX: "auto" }}>
          <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Verified Instrument</th>
                <th>Asset Class</th>
                <th>Price (USD / CAD)</th>
                <th>1D %</th>
                <th>Equity Valuation Applicable?</th>
                <th>Primary Benchmark</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.symbol}
                  onClick={() => handleSelectSymbol(r.symbol)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                    {r.symbol}
                  </td>
                  <td>{r.name}</td>
                  <td>{r.asset_class}</td>
                  <td className="mono-cell">
                    ${r.price_usd.toLocaleString()} / CA${r.price_cad.toLocaleString()}
                  </td>
                  <td
                    className="mono-cell"
                    style={{ color: r.change_1d_pct >= 0 ? "#00F29D" : "#F87171" }}
                  >
                    {r.change_1d_pct >= 0 ? "+" : ""}
                    {r.change_1d_pct.toFixed(2)}%
                  </td>
                  <td className="mono-cell">
                    {r.equity_valuation_applicable ? (
                      <span className="badge badge-emerald">YES (SEC EDGAR P/E &amp; FCF)</span>
                    ) : (
                      <span className="badge badge-blue">
                        NO (Physical Bullion / ETF / T-Bill Pillars)
                      </span>
                    )}
                  </td>
                  <td className="mono-cell" style={{ fontSize: "11.5px", color: "#94A3B8" }}>
                    {r.asset_class === "precious_metal"
                      ? "GLD / LBMA Gold Fix"
                      : r.asset_class === "cash_equivalent"
                        ? "BIL 1-3M US T-Bill"
                        : "SPY S&P 500"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* VIEW 5: TRANSPARENT MULTIFACTOR ASSET RATINGS */}
      {activeTab === "ratings" && (
        <div>
          <div style={{ marginBottom: "10px", fontSize: "12px", color: "#CBD5E1" }}>
            <strong>Methodology {intel.provenance.rating_methodology_version}:</strong> Asset-class-specific
            pillars ensure equity valuation ratios (P/E, P/B) are never falsely applied to physical precious
            metals (Gold, Silver, Platinum, Palladium) or sovereign T-Bills.
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Asset Class</th>
                  <th>Composite Rating</th>
                  <th>Δ vs Yesterday</th>
                  <th>Equity Valuation Rule</th>
                  <th>Transparent Pillar Breakdown</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => handleSelectSymbol(r.symbol)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {r.symbol}
                    </td>
                    <td>{r.asset_class}</td>
                    <td className="mono-cell">
                      <span className="badge badge-emerald">
                        {r.composite_rating_score}/100 {r.conviction_badge}
                      </span>
                    </td>
                    <td className="mono-cell">
                      {r.delta_vs_yesterday >= 0 ? "+" : ""}
                      {r.delta_vs_yesterday} pts
                    </td>
                    <td className="mono-cell">
                      {r.equity_valuation_applicable
                        ? "Evaluated (P/E, FCF Yield, ROE)"
                        : "not_applicable_physical_or_fund"}
                    </td>
                    <td style={{ fontSize: "11.5px", color: "#CBD5E1" }}>
                      {r.top_rating_factors.map((f, i) => (
                        <div key={i}>• {f}</div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 6: RESEARCH WATCHLIST & PRIORITIZED QUESTIONS */}
      {activeTab === "watchlist" && (
        <div>
          <div style={{ marginBottom: "14px" }}>
            <strong style={{ fontSize: "13px", color: "#00F29D" }}>
              Prioritized Research Questions for Today&apos;s Session (AI_COMMENTARY Grounded in Portfolio Facts)
            </strong>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                gap: "10px",
                marginTop: "8px",
              }}
            >
              {intel.prioritized_research_questions.map((q) => (
                <div
                  key={q.question_id}
                  style={{
                    padding: "12px",
                    borderRadius: "6px",
                    background: "rgba(15, 23, 42, 0.65)",
                    border: "1px solid rgba(0, 200, 255, 0.25)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                    <span className="badge badge-emerald mono-cell">{q.priority} PRIORITY</span>
                    <span className="badge badge-blue mono-cell">{q.epistemic_tag}</span>
                  </div>
                  <div style={{ fontWeight: 600, fontSize: "12.5px", color: "#F8FAFC", marginBottom: "4px" }}>
                    {q.topic}
                  </div>
                  <div style={{ fontSize: "12px", color: "#E2E8F0", marginBottom: "6px" }}>
                    {q.question}
                  </div>
                  <div className="mono-cell" style={{ fontSize: "11px", color: "#00F29D" }}>
                    Fact Basis: {q.fact_basis}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <strong style={{ fontSize: "13px", color: "#00C8FF" }}>
              Upcoming Macroeconomic, Central Bank, ETF &amp; SEC Filing Catalysts
            </strong>
            <div style={{ overflowX: "auto", marginTop: "6px" }}>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>Catalyst Event</th>
                    <th>Window</th>
                    <th>Affected Symbols</th>
                    <th>Research Relevance</th>
                    <th>Official Source</th>
                  </tr>
                </thead>
                <tbody>
                  {intel.upcoming_catalysts.catalysts.map((c) => (
                    <tr key={c.catalyst_id}>
                      <td className="mono-cell">{c.category}</td>
                      <td style={{ fontWeight: 600, color: "#F8FAFC" }}>{c.title}</td>
                      <td className="mono-cell">{c.scheduled_window}</td>
                      <td className="mono-cell">{c.impact_scope.join(", ")}</td>
                      <td style={{ fontSize: "11.5px", color: "#CBD5E1" }}>{c.why_it_matters}</td>
                      <td>
                        <a
                          href={c.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: "#00C8FF" }}
                        >
                          Official Source ↗
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 7: HISTORICAL PERFORMANCE, TWR/MWR & STRESS SCENARIOS */}
      {activeTab === "performance" && (
        <div>
          <div className="clean-kpi-row" style={{ marginBottom: "14px" }}>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Time-Weighted Return (TWR)</span>
              <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
                +{perf.returns.time_weighted_return_pct.toFixed(2)}%
              </span>
              <span className="clean-kpi-sub">
                Chain-linked across external cash flows (isolates pure investment skill)
              </span>
            </div>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Money-Weighted Return (MWR / XIRR)</span>
              <span className="clean-kpi-value" style={{ color: "#00C8FF" }}>
                +{perf.returns.money_weighted_return_pct.toFixed(2)}%
              </span>
              <span className="clean-kpi-sub">
                Internal Rate of Return accounting for contribution timing
              </span>
            </div>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">Net Investment Gain (Ex-Flows)</span>
              <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
                {fmtMoney(navBridge.net_investment_performance_usd)}
              </span>
              <span className="clean-kpi-sub">
                On {fmtMoney(navBridge.net_external_contributions_usd)} net external capital contributed
              </span>
            </div>
            <div className="clean-kpi-card">
              <span className="clean-kpi-label">95% Daily VaR / CVaR</span>
              <span className="clean-kpi-value" style={{ color: "#F59E0B" }}>
                {fmtMoney(perf.risk_and_exposure_metrics.volatility_and_tail_risk.daily_var_95_usd)}
              </span>
              <span className="clean-kpi-sub">
                95% CVaR: {fmtMoney(perf.risk_and_exposure_metrics.volatility_and_tail_risk.daily_cvar_95_usd)} · Vol:{" "}
                {perf.risk_and_exposure_metrics.volatility_and_tail_risk.annualized_portfolio_volatility_pct}%
              </span>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
              gap: "12px",
            }}
          >
            <div>
              <strong style={{ fontSize: "13px", color: "#F8FAFC" }}>
                Benchmark Comparisons (vs Portfolio TWR +{perf.returns.time_weighted_return_pct.toFixed(2)}%)
              </strong>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px", marginTop: "6px" }}>
                <thead>
                  <tr>
                    <th>Benchmark</th>
                    <th>Return %</th>
                    <th>Active Spread vs TWR</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.benchmark_comparisons.map((b) => (
                    <tr key={b.benchmark_symbol}>
                      <td>
                        <strong>{b.benchmark_symbol}</strong> — {b.benchmark_name}
                      </td>
                      <td className="mono-cell">+{b.benchmark_return_pct.toFixed(2)}%</td>
                      <td
                        className="mono-cell"
                        style={{ color: b.active_spread_vs_twr_pct >= 0 ? "#00F29D" : "#F87171" }}
                      >
                        {b.active_spread_vs_twr_pct >= 0 ? "+" : ""}
                        {b.active_spread_vs_twr_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div>
              <strong style={{ fontSize: "13px", color: "#F8FAFC" }}>
                Historical Multi-Asset Stress Scenarios
              </strong>
              <table className="clean-table" style={{ width: "100%", fontSize: "12px", marginTop: "6px" }}>
                <thead>
                  <tr>
                    <th>Stress Scenario</th>
                    <th>Estimated P&amp;L ({displayCurrency})</th>
                    <th>Portfolio Impact %</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.stress_scenarios.map((s) => (
                    <tr key={s.scenario_id}>
                      <td>{s.title}</td>
                      <td
                        className="mono-cell"
                        style={{ color: s.estimated_pnl_usd >= 0 ? "#00F29D" : "#F87171" }}
                      >
                        {fmtMoney(s.estimated_pnl_usd)}
                      </td>
                      <td
                        className="mono-cell"
                        style={{ color: s.estimated_return_pct >= 0 ? "#00F29D" : "#F87171" }}
                      >
                        {s.estimated_return_pct >= 0 ? "+" : ""}
                        {s.estimated_return_pct.toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* VIEW 8: MACHINE LEARNING INSIGHTS (BASELINES VS WALK-FORWARD ENSEMBLE) */}
      {activeTab === "ml_insights" && (
        <div>
          <div style={{ marginBottom: "10px", fontSize: "12px", color: "#CBD5E1" }}>
            <strong>Model Version {intel.provenance.model_version}:</strong> Purged &amp; embargoed walk-forward
            time-series cross-validation (4 folds, 2-bar embargo, 6.0 bps round-trip transaction cost) comparing
            Frequency, EWMA-Momentum, and Ridge-ARX baselines before promoting the Calibrated Walk-Forward Ensemble.
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Champion Ensemble P(up)</th>
                  <th>Expected Value E[R]</th>
                  <th>Market Regime</th>
                  <th>5-Day Return Cone [p10 / p50 / p90]</th>
                  <th>Leakage &amp; Drift Guard</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.symbol}
                    onClick={() => handleSelectSymbol(r.symbol)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {r.symbol}
                    </td>
                    <td className="mono-cell" style={{ color: "#00C8FF", fontWeight: 600 }}>
                      {(r.ml_p_up * 100).toFixed(1)}%
                    </td>
                    <td
                      className="mono-cell"
                      style={{ color: r.ml_expected_value_r >= 0 ? "#00F29D" : "#F87171" }}
                    >
                      {r.ml_expected_value_r >= 0 ? "+" : ""}
                      {r.ml_expected_value_r.toFixed(2)}R
                    </td>
                    <td className="mono-cell">{r.ml_regime}</td>
                    <td className="mono-cell">
                      {r.ml_return_cone_5d
                        ? `[${r.ml_return_cone_5d.p10_pct.toFixed(2)}% / ${r.ml_return_cone_5d.p50_pct.toFixed(2)}% / +${r.ml_return_cone_5d.p90_pct.toFixed(2)}%]`
                        : "—"}
                    </td>
                    <td className="mono-cell" style={{ color: "#00F29D", fontSize: "11px" }}>
                      PURGED_CV_OK · PSI_STABLE
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* VIEW 9: PORTFOLIO RISK & CATALYST ALERTS */}
      {activeTab === "alerts" && (
        <div style={{ display: "grid", gap: "10px" }}>
          {perf.risk_alerts.map((a) => (
            <div
              key={a.alert_id}
              style={{
                padding: "12px 14px",
                borderRadius: "6px",
                background: "rgba(15, 23, 42, 0.7)",
                border: "1px solid rgba(0, 242, 157, 0.28)",
              }}
            >
              <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "4px" }}>
                <span className="badge badge-emerald mono-cell">{a.severity}</span>
                <strong className="mono-cell" style={{ fontSize: "12px", color: "#00C8FF" }}>
                  {a.category}
                </strong>
              </div>
              <div style={{ fontSize: "12.5px", color: "#F8FAFC" }}>{a.message}</div>
            </div>
          ))}
        </div>
      )}

      {/* VIEW 10: BRIEF ARCHIVE, POINT-IN-TIME REGENERATION & CASL/PIPEDA CONSENT */}
      {activeTab === "archive" && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: "14px",
          }}
        >
          <div
            style={{
              padding: "14px",
              borderRadius: "6px",
              background: "rgba(15, 23, 42, 0.65)",
              border: "1px solid rgba(148, 163, 184, 0.22)",
            }}
          >
            <strong style={{ fontSize: "13px", color: "#00C8FF" }}>
              Point-in-Time Historical Brief Regeneration (Zero Future Leakage)
            </strong>
            <p style={{ fontSize: "12px", color: "#CBD5E1", marginTop: "6px" }}>
              Regenerate any historical daily brief strictly using transactions and market bars available at or
              before 23:59:59 UTC on the selected date:
            </p>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginTop: "10px", flexWrap: "wrap" }}>
              <input
                type="date"
                value={asOfDate}
                onChange={(e) => setAsOfDate(e.target.value)}
                aria-label="Point in time date"
                style={{
                  padding: "6px 10px",
                  borderRadius: "6px",
                  border: "1px solid rgba(148, 163, 184, 0.3)",
                  background: "#070A0F",
                  color: "#F8FAFC",
                  fontSize: "12px",
                }}
              />
              <button
                type="button"
                className="clean-tf-btn active"
                style={{ padding: "6px 12px", fontSize: "12px" }}
                onClick={() => void fetchIntelligenceBrief(asOfDate)}
              >
                Load Point-in-Time Brief ({asOfDate})
              </button>
              <button
                type="button"
                className="clean-tf-btn"
                style={{ padding: "6px 10px", fontSize: "12px" }}
                onClick={() => {
                  setAsOfDate("2026-09-30");
                  void fetchIntelligenceBrief("2026-09-30");
                }}
              >
                Test 2026-09-30 Cutoff
              </button>
            </div>
          </div>

          <div
            style={{
              padding: "14px",
              borderRadius: "6px",
              background: "rgba(15, 23, 42, 0.65)",
              border: "1px solid rgba(0, 242, 157, 0.25)",
            }}
          >
            <strong style={{ fontSize: "13px", color: "#00F29D" }}>
              Delivery Preferences &amp; Explicit CASL / PIPEDA Notification Consent
            </strong>
            <div style={{ fontSize: "12px", color: "#CBD5E1", marginTop: "8px" }}>
              <div>Schedule Cron: <code className="mono-cell">{intel.user_preferences.schedule_cron}</code> (07:30 ET Weekdays)</div>
              <div style={{ marginTop: "8px" }}>
                <label style={{ display: "flex", gap: "8px", alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={consentOptIn}
                    onChange={(e) => void handleToggleConsent(e.target.checked)}
                  />
                  <span>
                    I explicitly consent (CASL / PIPEDA Opt-In) to receive scheduled Daily Investment Brief
                    notifications.
                  </span>
                </label>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Provenance & Canadian NI 31-103 Footer */}
      <div
        style={{
          marginTop: "12px",
          paddingTop: "10px",
          borderTop: "1px solid rgba(148, 163, 184, 0.16)",
          fontSize: "11px",
          color: "#94A3B8",
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <span>
          <strong>Source &amp; Governance:</strong> {intel.provenance.actual_transaction_source} ·{" "}
          {intel.provenance.uncertainty_disclosures[2]}
        </span>
        <span className="mono-cell">
          Cutoff: {intel.provenance.portfolio_data_cutoff_utc}
        </span>
      </div>
    </div>
  );
}

export function AiDailyInvestmentBriefWorkspace() {
  const [selectedSymbol, setSelectedSymbol] = useState<string>("AAPL");
  return (
    <div style={{ padding: "12px 16px" }}>
      <AiDailyInvestmentBriefPanel
        selectedSymbol={selectedSymbol}
        onSelectSymbol={setSelectedSymbol}
        defaultTab="today"
      />
    </div>
  );
}
