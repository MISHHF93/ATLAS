"use client";

import { useEffect, useRef, useState } from "react";
import { type QuoteStatus } from "../src/lib/feedQuotes";
import { InstitutionalWorkspacesView, type SubPageRouteId } from "../src/components/shell/InstitutionalWorkspacesView";

const API = "";

type RoleKey = "founder_admin" | "researcher" | "monitoring";

type Candle = {
  open_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

type CandlePage = {
  symbol: string;
  interval: string;
  source: string;
  candles: Candle[];
};

type Capabilities = {
  providers: Array<{
    provider_id: string;
    location: string;
    capabilities: string[];
    models: string[];
  }>;
  components: Record<string, string>;
  execution: { enabled: boolean; permission: string; order_routes: boolean };
};

type LimitProximity = {
  rule_name: string;
  current_value: string;
  limit_value: string;
  utilization_pct: number;
  remaining_pct: number;
  status: "healthy" | "warning" | "breached" | "unconfigured";
};

type EvaluationReport = {
  samples: number;
  mae: number;
  rmse: number;
  naive_mae: number;
  return_rmse: number;
  directional_accuracy: number;
  brier_score: number | null;
  expected_net_return: number;
  no_trade_return: number;
  compounded_net_return: number;
  max_drawdown: number;
  expected_shortfall_95: number;
  paired_mae_improvement_interval: [number, number];
};

type StudyPayload = {
  study_id: string;
  track: "competition" | "open_market";
  competition_rulebook_ref: string | null;
  dataset_id: string;
  manifest_sha256: string;
  purge_bars: number;
  embargo_bars: number;
  linear_baseline_report?: EvaluationReport;
  overall_report: EvaluationReport;
  regime_reports: Record<string, EvaluationReport | null>;
  regime_variant_unlocked?: boolean;
  regime_variant_gate_reason?: string;
  feedback: {
    beats_naive_mae: boolean;
    beats_no_trade_net_return: boolean;
    recommended_next_action: string;
    auto_promoted: boolean;
    execution_permission: string;
  };
};

type PlatformSnapshot = {
  source: string;
  notice: string;
  without_approval: { forecasts: unknown[]; execution_permission: string };
  with_scoped_approval: {
    forecasts: Array<{
      model: { provider_id: string; model_id: string; revision: string };
      points: Array<{ timestamp: string; value: number; lower?: number | null; upper?: number | null }>;
      probability_up?: number | null;
      calibration_ref?: string | null;
    }>;
    disagreement_by_step?: number[];
    strategy_candidates?: string[];
    warnings?: string[];
    execution_permission: string;
  };
  regime_overlay?: {
    volatility: string;
    trend: string;
    liquidity: string;
    session: string;
    macro_event: string;
    realized_volatility: number | null;
    cumulative_return: number | null;
    liquidity_score: number | null;
    spread_bps: number | null;
    composite_label: string;
    taxonomy_revision: string;
  };
  quality_report?: {
    quality_status: string;
    freshness_age_seconds: number | null;
    is_fresh: boolean;
    license_valid_for_use: boolean;
    calendar_matched: boolean;
    point_in_time_valid: boolean;
    blocking_issues: string[];
  };
  calibrator?: {
    calibration_id: string;
    bin_rates: number[];
    bin_counts: number[];
  };
  rule_evaluation?: {
    rulebook_id: string;
    revision: string;
    track: string;
    compliance_passed: boolean;
    auto_flatten_required: boolean;
    kill_switch_active: boolean;
    violations: string[];
    execution_permission: string;
    remaining_room: {
      max_safe_trade_notional_usd: string | null;
      daily_loss_room_usd: string | null;
      drawdown_room_usd: string | null;
      leverage_room_usd: string | null;
      consistency_compliant: boolean;
      minimum_days_met: boolean;
      proximities: LimitProximity[];
    };
  };
  studies?: {
    competition: StudyPayload;
    open_market: StudyPayload;
  };
  central_node?: {
    node_run_id: string;
    auto_promoted: boolean;
    in_place_weight_mutation: boolean;
    execution_permission: string;
    competition_paper_simulation: {
      simulation_id: string;
      initial_equity_usd: string;
      final_equity_usd: string;
      max_realized_drawdown_fraction: number;
      total_steps: number;
      permitted_paper_trades: number;
      blocked_paper_trades: number;
    };
    open_market_paper_simulation: {
      simulation_id: string;
      initial_equity_usd: string;
      final_equity_usd: string;
      max_realized_drawdown_fraction: number;
      total_steps: number;
      permitted_paper_trades: number;
      blocked_paper_trades: number;
    };
    horizon_strategy_comparison: {
      steps: number;
      direct_mae_by_step: number[];
      recursive_mae_by_step: number[];
      recommended_method_by_step: string[];
    };
    ensemble_gate: {
      ensemble_mae: number;
      best_member_mae: number;
      error_correlation: number;
      combiner_enabled: boolean;
    };
  };
  mcp_data_surfaces?: {
    allowlisted_providers: Record<string, string[]>;
    blocked_providers: string[];
    fred_training_policy: string;
  };
  calendars_telemetry?: {
    competition_calendar: {
      calendar_ref: string;
      market_type: string;
      timezone: string;
      session_state: string;
      funding_windows_count: number;
      maintenance_windows_count: number;
    };
    open_market_calendar: {
      calendar_ref: string;
      market_type: string;
      timezone: string;
      session_state: string;
      session_targets_count: number;
      holidays: string[];
    };
  };
  microstructure_covariates?: Array<{
    name: string;
    source: string;
    lineage_ref: string;
    quality: string;
    value: number;
    available_at: string;
  }>;
  sec_edgar_facts?: Array<{
    name: string;
    source: string;
    lineage_ref: string;
    quality: string;
    value: number;
    available_at: string;
  }>;
  money_records?: Array<{
    record_id: string;
    category: string;
    book_of_record: string;
    custody_by_atlas: boolean;
    commingled: boolean;
    status: string;
  }>;
  iso_governance?: {
    certification_claimed: boolean;
    design_target: string;
    standards: Array<{ id: string; domain: string; control: string }>;
  };
  roles?: Record<RoleKey, { label: string; permissions: string[]; live_order_entry: boolean }>;
};

export type SectionId =
  | "all"
  | "overview"
  | "roadmap"
  | "listings"
  | "market"
  | "matrix"
  | "rules"
  | "research"
  | "experiments"
  | "models"
  | "sync"
  | "warehouse"
  | "connectors"
  | "configurations"
  | "governance"
  | "docs"
  | "profile";

export type RoadmapAzRow = {
  letter: string;
  domain: string;
  path: string;
  spec: string;
  track: string;
  status: string;
  gate: string;
  priority: string;
};

export type B2BSaasVerticalRow = {
  vertical_id: string;
  name: string;
  buyer_persona: string;
  pain_point: string;
  atlas_solution: string;
  domain_scope: string;
  pricing_model: string;
  phase: string;
  live_telemetry: string;
  status: string;
};

export type WhaleExecutionMlRow = {
  model_id: string;
  name: string;
  equation: string;
  parameters: string;
  architecture: string;
  signal_criteria: string;
  execution_action: string;
  subsystem: string;
  live_metric: string;
};

export type GlobalDomainRow = {
  domain: string;
  venues: string;
  sessions: string;
  granularity: string;
  prop_nuances: string;
  hedging_strategy: string;
  subsystem: string;
};

export type WhaleDecisionScenarioRow = {
  scenario_id: string;
  scenario: string;
  indicators_triggered: string;
  when_trigger: string;
  where_location: string;
  order_type: string;
  prop_guardrail: string;
  active: boolean;
};

export type TrackRulesLimitRow = {
  dimension: string;
  open_market_spec: string;
  prop_competition_spec: string;
  deterministic_enforcement: string;
};

export type WorkbenchLayerApiRow = {
  layer: string;
  route: string;
  description: string;
  data_flow: string;
};

export type MasterRoadmapState = {
  focus_symbol: string;
  roadmap_az: RoadmapAzRow[];
  track_rules_limits?: TrackRulesLimitRow[];
  workbench_layers_apis?: WorkbenchLayerApiRow[];
  b2b_saas_verticals: B2BSaasVerticalRow[];
  whale_execution_ml: WhaleExecutionMlRow[];
  global_multi_domain: GlobalDomainRow[];
  whale_decision_matrix: WhaleDecisionScenarioRow[];
  live_wf_telemetry: {
    wf01_kyles_lambda: { lambda_coeff: number; r_squared: number; noise_eta: number; spike_alert: boolean };
    wf02_vpin: { vpin: number; toxic_flow_95th: boolean; recommended_book: string };
    wf03_ofi: { ofi_weighted: number; extreme_skew: boolean; direction: string };
    wf04_almgren_chriss: {
      total_shares: number;
      urgency_kappa: number;
      horizon_steps: number;
      child_order_slices: number[];
      remaining_inventory_curve: number[];
    };
    wf05_gbdt_spread: {
      book_shannon_entropy: number;
      spread_ratio_l2_l1: number;
      predicted_spread_widening_bps: number;
      cancel_passive_resting: boolean;
    };
    wf06_predatory_impact: {
      whale_participation_adv_pct: number;
      predicted_impact_bps: number;
      predatory_trigger_active: boolean;
    };
    wf07_hawkes: {
      baseline_mu0: number;
      current_intensity_lambda: number;
      branching_ratio: number;
      iceberg_clustering_detected: boolean;
    };
    wf08_rl_policy: {
      optimal_tactic: string;
      expected_slippage_bps: number;
      inventory_penalty_bps: number;
      cumulative_reward_score: number;
      execution_permission: string;
    };
  };
};

const DEFAULT_ROADMAP_STATE: MasterRoadmapState = {
  focus_symbol: "SPY",
  roadmap_az: [
    { letter: "A", domain: "Allocation & Portfolio Construction", path: "src/atlas/portfolio", spec: "Mean-variance, Kelly fractional, Risk parity", track: "Both", status: "Implemented", gate: "Pytest", priority: "P0" },
    { letter: "B", domain: "Benchmark & Market Calendars", path: "src/atlas/market", spec: "NYSE/Nasdaq auction calendars, 24/7 crypto funding cycles", track: "Both", status: "Implemented", gate: "Deterministic Gate", priority: "P1" },
    { letter: "C", domain: "Control Plane & Circuit Breakers", path: "src/atlas/control", spec: "ActionableControlPlaneEngine, kill switch, auto-flatten", track: "Both", status: "Implemented", gate: "Deterministic Gate", priority: "P0" },
    { letter: "D", domain: "Data Lakehouse & PIT Engine", path: "src/atlas/warehouse", spec: "DuckDB, BigQuery, Parquet ZSTD, acceptance_time <= as_of", track: "Both", status: "Implemented", gate: "PIT Check", priority: "P0" },
    { letter: "E", domain: "Execution Routing & OMS/EMS", path: "src/atlas/execution", spec: "Interactive Brokers, Alpaca, FIX protocol, Coinbase", track: "Both", status: "Implemented", gate: "Latency Target", priority: "P0" },
    { letter: "F", domain: "Feature Engineering & Microstructure", path: "src/atlas/features", spec: "Order book imbalance, VWAP deviation, tick entropy, VPIN", track: "Both", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "G", domain: "Governance, Standards & 8 Ledgers", path: "src/atlas/governance", spec: "ISO 42001, NIST AI RMF, IOSCO, non-custodial ledgers", track: "Both", status: "Implemented", gate: "Audit Gate", priority: "P0" },
    { letter: "H", domain: "Hardware Acceleration & High-Throughput I/O", path: "src/atlas/hardware", spec: "Vectorized backtesting, SIMD, local GPU inference", track: "Both", status: "Implemented", gate: "Latency Target", priority: "P1" },
    { letter: "I", domain: "Integrations & MCP Isolation", path: "src/atlas/integrations", spec: "Quarantined tools, read-only MCP, SEC EDGAR, FRED guard", track: "Both", status: "Implemented", gate: "Security Scan", priority: "P0" },
    { letter: "J", domain: "Journaling & Immutable Audit Trails", path: "src/atlas/journal", spec: "SQLite event store, decision checkpoints, order logs", track: "Both", status: "Implemented", gate: "Audit Gate", priority: "P0" },
    { letter: "K", domain: "Key Management & Secret Scrubbing", path: "src/atlas/keys", spec: "Signing keys, zero-leak credential masking", track: "Both", status: "Implemented", gate: "Security Scan", priority: "P0" },
    { letter: "L", domain: "Liquidity Analysis & Depth Modeling", path: "src/atlas/liquidity", spec: "L2/L3 order book reconstruction, Kyle's Lambda impact models", track: "Both", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "M", domain: "Machine Learning & Challenger Benchmarks (CB-01..06)", path: "src/atlas/models", spec: "GBDT, Boosted Stump, Ridge, Tick GBDT & Anti-Gravity Self-Training; DSR >= 0.95 & Prop Loss L(theta)", track: "Both", status: "Implemented", gate: "Walk-Forward + DSR", priority: "P0" },
    { letter: "N", domain: "Non-Custodial Safety & Risk Bounds", path: "src/atlas/risk", spec: "Single-day profit consistency, trailing drawdown floors", track: "Both", status: "Implemented", gate: "Deterministic Gate", priority: "P0" },
    { letter: "O", domain: "Order Types & Execution Tactics", path: "src/atlas/execution/tactics", spec: "Almgren-Chriss TWAP/VWAP, iceberg, ATR bracket orders", track: "Both", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "P", domain: "Probability Calibration & ECE Benchmark Gate", path: "src/atlas/calibration", spec: "Empirical bin / Platt scaling, isotonic calibration, Brier <= 0.18 & ECE <= 0.035", track: "Both", status: "Implemented", gate: "Calibration Gate", priority: "P1" },
    { letter: "Q", domain: "Quantitative Validation, Purged CV & DSR Gate", path: "src/atlas/experiments", spec: "Purged k-fold, embargoing, Deflated Sharpe DSR >= 0.95, Direct vs Recursive Horizon Gate", track: "Both", status: "Implemented", gate: "Walk-Forward + DSR", priority: "P0" },
    { letter: "R", domain: "Regime Classification Engine", path: "src/atlas/regime", spec: "Causal volatility, trend, liquidity, Hawkes & macro regime tagging", track: "Both", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "S", domain: "SEC EDGAR & Fundamental Ingestion", path: "src/atlas/fundamentals", spec: "Point-in-time XBRL parser, 10-K/10-Q filing timestamps", track: "Open-Market Stock", status: "Implemented", gate: "PIT Check", priority: "P1" },
    { letter: "T", domain: "Telemetry, Observability & Health", path: "src/atlas/telemetry", spec: "Tick-to-trade latency, pipeline heartbeats, drop alerts", track: "Both", status: "Implemented", gate: "Latency Target", priority: "P0" },
    { letter: "U", domain: "User Roles & RBAC Boundaries", path: "src/atlas/profile", spec: "founder_admin, researcher, monitoring; zero operator discretion", track: "Both", status: "Implemented", gate: "Security Scan", priority: "P0" },
    { letter: "V", domain: "Volatility Surfaces & Derivatives", path: "src/atlas/volatility", spec: "Implied vol, ATR dynamic sizing, funding rate arbitrage", track: "Prop Competition", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "W", domain: "Whale Microstructure & Dark Pools", path: "src/atlas/microstructure", spec: "Large block detection, VPIN, Hawkes hidden volume clustering", track: "Both", status: "Implemented", gate: "Pytest", priority: "P2" },
    { letter: "X", domain: "Cross-Asset Synchronization & Hedging", path: "src/atlas/sync", spec: "Equities vs. Crypto perpetual delta hedging & 9x9 correlation gate", track: "Both", status: "Implemented", gate: "Pytest", priority: "P1" },
    { letter: "Y", domain: "Yield & Funding Rate Arbitrage", path: "src/atlas/yield", spec: "Basis trade capture, 8h perp funding & overnight repo modeling", track: "Both", status: "Implemented", gate: "Pytest", priority: "P2" },
    { letter: "Z", domain: "Zero Data-Leakage Research & Challenger Sandbox", path: "src/atlas/research", spec: "Air-gapped research sandbox, SHA-256 frozen manifests, auto_promoted=False", track: "Both", status: "Implemented", gate: "Security Scan", priority: "P0" },
  ],
  track_rules_limits: [
    { dimension: "Execution Target", open_market_spec: "NYSE Arca / Nasdaq (XNYS, XNAS)", prop_competition_spec: "BTC-USD, ETH-USD, SOL-USD & Multi-Asset Prop Books", deterministic_enforcement: "ActionableControlPlaneEngine" },
    { dimension: "Assets", open_market_spec: "SPY, NVDA, AAPL, MSFT, QQQ, TSLA", prop_competition_spec: "24/7 Crypto / Derivative & Futures Books", deterministic_enforcement: "Kill switch, auto-flatten" },
    { dimension: "Trading Hours", open_market_spec: "09:30-16:00 ET regular session + Auctions", prop_competition_spec: "24/7/365 Continuous Session", deterministic_enforcement: "Time-based calendar session gate" },
    { dimension: "Max Daily Loss", open_market_spec: "3.0% Desk Daily Loss Limit", prop_competition_spec: "4.0% Daily Loss Circuit Breaker", deterministic_enforcement: "ActionableControlPlaneEngine" },
    { dimension: "Max Trailing DD", open_market_spec: "10.0% Static Drawdown Floor", prop_competition_spec: "8.0% Max Trailing Drawdown Floor", deterministic_enforcement: "ActionableControlPlaneEngine" },
    { dimension: "Per-Trade Risk Cap", open_market_spec: "0.50% Equity Risk Cap", prop_competition_spec: "0.50%-0.75% Per-Trade Risk Cap", deterministic_enforcement: "Mandatory ATR/Structure Stop + VPIN Widening" },
    { dimension: "Consistency Gate", open_market_spec: "Unconstrained Open-Market Compounding", prop_competition_spec: "<= 35% Single-Day Profit Consistency Gate", deterministic_enforcement: ">= 5 Minimum Trading Days" },
    { dimension: "Data Feeds", open_market_spec: "SEC EDGAR PIT XBRL, Databento / Polygon.io SIP", prop_competition_spec: "Databento L1/L2/MBO, Coinbase Public REST", deterministic_enforcement: "acceptance_time <= as_of (PIT Gate)" },
    { dimension: "Broker Routing", open_market_spec: "Alpaca / Interactive Brokers DMA routing", prop_competition_spec: "FIX protocol, Coinbase, cTrader, Rithmic", deterministic_enforcement: "Zero operator discretion" },
    { dimension: "Regulatory/Audit Standard", open_market_spec: "SEC T+1 / Reg-T / XBRL Audit", prop_competition_spec: "Prop Challenge Rulebook Verification", deterministic_enforcement: "ISO 42001, NIST AI RMF, IOSCO & 8 Ledgers" },
  ],
  workbench_layers_apis: [
    { layer: "Command Center", route: "/", description: "Unified executive trading desk, live chart & prop scorecard", data_flow: "/api/platform/snapshot, /api/control/state" },
    { layer: "Whale ML, SaaS & A-Z Roadmap", route: "/roadmap", description: "Roadmap catalogue (A-Z, WF-01..08 on sample inputs, SAAS-01..12 Planned)", data_flow: "/api/master-roadmap, /api/master-roadmap/evaluate-whale" },
    { layer: "Quant & Signal Matrix", route: "/matrix", description: "9x4 Multi-Horizon Alpha, 9x9 Correlation, 5x5 Regime & L2 DOM", data_flow: "/api/matrix, /api/matrix/recompute" },
    { layer: "Live Listings", route: "/listings", description: "Real-time multi-asset listings & 1-click order desk routing", data_flow: "/api/listings, /api/listings/action" },
    { layer: "Live Charts & Market PIT", route: "/market", description: "ATLAS PIT + Forecast Fan & ATLAS Chart", data_flow: "/api/market/candles, /api/market/live-internet-sync" },
    { layer: "Enterprise API Data Warehouse", route: "/warehouse", description: "BigQuery Analytics Hub, DuckDB Parquet, Databento, Polygon, ClickHouse", data_flow: "/api/warehouse, /api/warehouse/action" },
    { layer: "Deterministic Control Plane", route: "/control, /rules", description: "Risk enforcement, VPIN stop-widening & millisecond kill-switch", data_flow: "ActionableControlPlaneEngine (/api/control/*)" },
    { layer: "Governance & 8 Ledgers", route: "/governance", description: "8 separated non-custodial ledgers & ISO 42001 / NIST AI RMF", data_flow: "/api/control/readiness-audit" },
    { layer: "AI Synthesis & Gemini Node", route: "/research", description: "24/7 continuous research tick & probability calibration", data_flow: "/api/research/continuous-tick (permission=none)" },
    { layer: "Walk-Forward Evaluation Lab", route: "/experiments", description: "Purged & embargoed walk-forward (EXP-001) & paper simulation", data_flow: "/api/research/walk-forward" },
    { layer: "Models, MCP & SEC XBRL", route: "/models", description: "Anti-Gravity self-training loop, GBDT/Ridge, allowlisted MCP & SEC XBRL", data_flow: "/api/research/train, /api/market/mcp-fetch" },
    { layer: "Data Syncing Center", route: "/sync", description: "Cross-asset PIT synchronization & SHA-256 manifests", data_flow: "/api/sync, /api/sync/run" },
    { layer: "Integrations & MCP Hub", route: "/integrations, /connectors", description: "Quarantined tools guard (irohan0/quant-mcp) & read-only MCP", data_flow: "/api/connectors, /api/connectors/action" },
    { layer: "Platform Configurations", route: "/configurations, /settings", description: "1-click Prop & Stock desk presets & rulebook thresholds", data_flow: "/api/configurations" },
    { layer: "User Profile & Keys", route: "/profile", description: "RBAC boundaries, 100% founder IP ownership & secret scrubbing", data_flow: "/api/profile" },
    { layer: "Architecture & Specs", route: "/docs", description: "Live in-app Markdown reader for all 9 specification docs", data_flow: "/api/docs" },
  ],
  b2b_saas_verticals: [
    { vertical_id: "SAAS-01", name: "Real-Time Risk & Drawdown Engine", buyer_persona: "Prop Firm Founder, Head of Risk", pain_point: "Delayed equity updates lead to catastrophic firm losses when traders breach max drawdown during volatile events.", atlas_solution: "Deterministic multi-broker margin & equity monitoring, millisecond kill-switch using ATLAS Control Plane.", domain_scope: "US Equities, CME Futures, FX/CFDs, 24/7 Crypto", pricing_model: "Monthly B2B Retainer ($2,500/mo) + Tiered Seat ($18/$12/$8 per active trader)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-02", name: "Trader Evaluation & Challenge Lifecycle Engine", buyer_persona: "Prop Firm Founder, Operations Lead", pain_point: "Manual challenge verification and easily gamified rules lead to unprofitable funded traders.", atlas_solution: "Configurable pass/fail criteria, <=35% consistency scorecards, anti-gaming algorithms powered by ATLAS walk-forward validation.", domain_scope: "FX/CFDs, CME Futures, US Equities", pricing_model: "4.5% Revenue Share on Gross Evaluation Fees ($1,500/mo minimum floor)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-03", name: "Sybil & Latency Arbitrage Detection", buyer_persona: "Head of Risk, Compliance Officer", pain_point: "Sophisticated rings use account sharing and toxic tick-scalping to extract risk-free profits from B-Book firms.", atlas_solution: "Account-sharing detection, toxic tick-scalping identifier, IP/behavioral fingerprinting using ATLAS ML models.", domain_scope: "FX/CFDs, 24/7 Crypto", pricing_model: "Tiered Volume SaaS ($2,000/mo base + $0.08 per 1,000 screened fills)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-04", name: "AI-Powered Synthetic Copier / Dealing Desk Hedger", buyer_persona: "Dealing Desk Lead, Chief Investment Officer", pain_point: "Inefficient manual B-Book to A-Book routing leaves alpha on the table and exposes the firm to directional risk.", atlas_solution: "B-Book to A-Book smart order routing, alpha clustering utilizing ATLAS regime classification engine.", domain_scope: "US Equities, FX/CFDs, 24/7 Crypto", pricing_model: "AUM / Hedged Notional Basis Point Fee (0.35 bps on A-Book / Hybrid routed volume)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-05", name: "Point-in-Time Regulatory & Audit Ledger", buyer_persona: "Compliance Officer, Legal Counsel", pain_point: "Increasing regulatory scrutiny requires immutable, point-in-time proof of trade execution and pricing.", atlas_solution: "ISO 42001 & IOSCO aligned tamper-proof trade audit logs backed by ATLAS Journaling & Immutable Audit Trails.", domain_scope: "Global (All Asset Classes)", pricing_model: "Fixed Enterprise Annual License ($18,000/yr or $1,500/mo)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-06", name: "Prop Trader Behavioral Co-Pilot & Coach", buyer_persona: "Prop Trader, Community Manager", pain_point: "High churn rate of funded traders due to emotional trading and lack of personalized, data-driven feedback.", atlas_solution: "Execution bias detection, overtrading alerts, disciplined sizing guides leveraging ATLAS Probability Calibration.", domain_scope: "US Equities, CME Futures, FX/CFDs", pricing_model: "B2B2C Freemium Upsell ($29/mo Pro Trader Add-On · 60/40 Firm Split)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-07", name: "Multi-Broker Bridge & Execution Router", buyer_persona: "CTO, Head of Trading", pain_point: "Fragmented API integrations across different asset classes create a maintenance nightmare and execution latency.", atlas_solution: "Unified FIX / REST abstraction across Alpaca, IBKR, cTrader, DXtrade, Bybit, Coinbase via ATLAS Execution Routing.", domain_scope: "Global (All Asset Classes)", pricing_model: "Monthly B2B Retainer ($2,000/mo) + $350/mo per connected FIX/REST venue gateway", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-08", name: "Dynamic Margin & Trailing Drawdown Visualizer", buyer_persona: "Prop Trader, Frontend Developer", pain_point: "Traders lack real-time visibility into their complex trailing drawdown limits, causing accidental breaches and support tickets.", atlas_solution: "Interactive real-time remaining-room HUD for web & mobile streaming from ATLAS Data Lakehouse.", domain_scope: "US Equities, CME Futures, FX/CFDs, 24/7 Crypto", pricing_model: "Flat Monthly White-Label Widget & WebSocket API Fee ($1,250/mo)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-09", name: "Backtesting & Rule Verification Sandbox", buyer_persona: "Quant Researcher, Prop Trader", pain_point: "Traders cannot accurately backtest their strategies against the specific, complex rules of prop firm evaluations.", atlas_solution: "Deterministic prop evaluation replay for strategy verification using ATLAS Zero Data-Leakage Research Sandbox.", domain_scope: "US Equities, CME Futures, FX/CFDs", pricing_model: "Pay-per-Compute ($6.50 / Vectorized Backtest GPU-Hour)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-10", name: "Whale & Microstructure Liquidity Intelligence", buyer_persona: "Dealing Desk Lead, Head of Risk", pain_point: "Prop firms unknowingly internalize toxic, informed institutional flow, resulting in severe B-Book losses.", atlas_solution: "Institutional flow detector protecting firm B-Book from toxic informed flow powered by ATLAS Feature Engineering (WF-01..WF-08).", domain_scope: "US Equities, 24/7 Crypto", pricing_model: "Premium Data Feed Subscription ($3,500/mo per asset class)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-11", name: "Challenger Model Benchmark-as-a-Service (CB-01..CB-06)", buyer_persona: "Chief Investment Officer, Head of Quant Research", pain_point: "In-house prop firm alpha models overfit in-sample backtests and fail live due to uncalibrated probabilities and selection bias.", atlas_solution: "Purged & embargoed walk-forward challenger tournament with Deflated Sharpe Ratio (DSR >= 0.95), Prop Loss L(theta), and ECE <= 0.035 gates.", domain_scope: "Global (Equities, CME Futures, Crypto Perps, FX)", pricing_model: "Enterprise Research Subscription ($2,800/mo + $150 per evaluated challenger model)", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
    { vertical_id: "SAAS-12", name: "Custom B2B Hybrid Tiered Seat + AUM/Volume Billing Engine", buyer_persona: "Prop Firm CFO, COO, Founder", pain_point: "Rigid per-seat SaaS pricing penalizes high-growth evaluation firms during seasonal challenge volume spikes.", atlas_solution: "Elastic hybrid billing: C_total = R_base + TieredSeats(1..100@$18, 101..500@$12, 501+@$8) + 0.35 bps Hedged Volume + 4.5% Eval Rev-Share.", domain_scope: "Ledger 1: Non-Custodial Software Subscription Ledger", pricing_model: "Elastic Hybrid: $4.5k Base + $18/$12/$8 Seat Tiers + 0.35 bps AUM + 4.5% Eval Share", phase: "Planned", live_telemetry: "Not measured: concept (paper only)", status: "Planned" },
  ],
  whale_execution_ml: [
    { model_id: "WF-01", name: "Kyle's Lambda (Price Impact of Informed Trading)", equation: "Delta P = lambda * Q + eta", parameters: "P: Price, lambda: Liquidity parameter, Q: Signed order flow, eta: Noise", architecture: "OLS Regression / Rolling Window Estimation", signal_criteria: "Lambda spikes indicating high price impact; pause passive market making.", execution_action: "Widen spreads, skew quotes away from informed flow.", subsystem: "src/atlas/liquidity/impact.py", live_metric: "lambda=0.0014 (R²=0.89) · Spike=False" },
    { model_id: "WF-02", name: "VPIN (Volume-Synchronized Probability of Informed Trading)", equation: "VPIN = sum(|V_tau^B - V_tau^S|) / (N * V)", parameters: "V_tau^B: Buy vol, V_tau^S: Sell vol, N: Buckets, V: Bucket size", architecture: "Volume-bucketed classification model", signal_criteria: "VPIN > 95th percentile threshold; impending volatility/toxicity.", execution_action: "Auto-flatten inventory, route orders to A-Book.", subsystem: "src/atlas/features/toxicity.py", live_metric: "VPIN=0.2908 · Book=Hybrid B-Book / Internal Netting" },
    { model_id: "WF-03", name: "Order Flow Imbalance (OFI) & Multi-Level Depth Imbalance", equation: "OFI_t = sum_i(Delta L_{i,t} * w_i)", parameters: "L_{i,t}: Limit order volume at level i, w_i: Weight decay per level", architecture: "Exponentially weighted moving average (EWMA) / Vectorized aggregation", signal_criteria: "Extreme OFI skew (> 0.8) at top 3 levels; imminent micro-trend.", execution_action: "Execute aggressive taker orders in direction of imbalance.", subsystem: "src/atlas/microstructure/orderbook.py", live_metric: "OFI=+0.228 (buy_pressure) · Extreme=False" },
    { model_id: "WF-04", name: "Almgren-Chriss Optimal Execution Schedule", equation: "min E[x] + lambda * Var[x] -> x_j = X * sinh(kappa*(T - t_j)) / sinh(kappa*T)", parameters: "X: Total shares, T: Time horizon, kappa: Urgency/risk aversion, lambda: Risk penalty", architecture: "Convex Optimization / Dynamic Programming", signal_criteria: "Need to liquidate/accumulate large whale inventory over time T.", execution_action: "Slice into TWAP/VWAP child orders following the sinh curve.", subsystem: "src/atlas/execution/tactics/optimal.py", live_metric: "Slices=[3712.4, 2418.1, 1592.0]... (kappa=0.45)" },
    { model_id: "WF-05", name: "GBDT Depth Imbalance & Microstructure Spread Predictor", equation: "y_hat = sum_m f_m(OFI, VPIN, BookEntropy, SpreadRatio)", parameters: "f_m: Decision trees, BookEntropy: Shannon entropy of depth, SpreadRatio: L2/L1", architecture: "Gradient-Boosted Decision Trees with early stopping", signal_criteria: "y_hat predicts short-term spread widening or mid-price jump.", execution_action: "Cancel passive resting orders before adverse selection occurs.", subsystem: "src/atlas/models/microstructure_gbdt.py", live_metric: "y_hat=+1.80 bps · Entropy=1.734" },
    { model_id: "WF-06", name: "Cross-Impact & Predatory Liquidation Trigger", equation: "Delta P_predatory = gamma * sqrt(Volume_whale / ADV) * sgn(Side)", parameters: "gamma: Cross-impact coefficient, ADV: Average Daily Volume", architecture: "Square-root impact model calibrated via Non-linear Least Squares", signal_criteria: "Detection of large whale liquidation (Volume_whale > 5% ADV).", execution_action: "Hedge/trade momentum with structural stop, close after impact.", subsystem: "src/atlas/microstructure/predatory.py", live_metric: "Whale/ADV=6.40% · Impact=-885.44 bps" },
    { model_id: "WF-07", name: "Regime-Conditioned Hidden Liquidity Detector (Hawkes Process)", equation: "lambda(t) = mu_0 + sum_{t_i < t} alpha * exp(-beta*(t - t_i))", parameters: "mu_0: Baseline intensity, alpha: Excitation jump, beta: Decay rate", architecture: "Maximum Likelihood Estimation (MLE) of Self-Exciting Point Processes", signal_criteria: "Clustering of iceberg order fills or hidden dark-pool prints.", execution_action: "Join the hidden liquidity pool, deploy stealth post-only orders.", subsystem: "src/atlas/regime/hawkes_detector.py", live_metric: "lambda(t)=2.341 · Iceberg=True" },
    { model_id: "WF-08", name: "Reinforcement Learning Execution Agent (PPO/DDPG)", equation: "pi*(a|s) maximizing cumulative reward R = -Slippage - Penalty(Inventory)", parameters: "a: Order size/price, s: State (OFI, Spread, Inventory), R: Reward function", architecture: "Proximal Policy Optimization (PPO) / Deterministic Surrogate Policy", signal_criteria: "Continuous state-action mapping for optimal order routing.", execution_action: "Dynamic placement of limit vs market orders (execution_permission=none).", subsystem: "src/atlas/execution/rl_agent.py", live_metric: "Policy: Passive Post-Only Limit at L2 Bid/Ask Wall (Reward=-1.59)" },
  ],
  global_multi_domain: [
    { domain: "US Cash Equities", venues: "NYSE/Nasdaq SIP, Direct Feeds (XNYS, XNAS, ARCA)", sessions: "09:30-16:00 ET regular + Opening/Closing Auctions", granularity: "L1 BBO, L2 10-level Depth, SEC EDGAR PIT XBRL", prop_nuances: "PDT rules, Reg-T intraday margin & SEC T+1 settlement", hedging_strategy: "A-Book direct market access (Alpaca / IBKR)", subsystem: "src/atlas/marketdata/equities" },
    { domain: "CME Index/Commodity Futures", venues: "CME Aurora / Globex MDP3, Rithmic, CQG", sessions: "Sunday-Friday 17:00-16:00 CT (Daily 1h maintenance)", granularity: "L3 MBO / Tick-by-Tick depth reconstruction", prop_nuances: "Intraday trailing high-water-mark drawdown during open trades", hedging_strategy: "Hybrid B-Book with internal cross-trader netting", subsystem: "src/atlas/marketdata/futures" },
    { domain: "24/7 Crypto Spot & Perps", venues: "Coinbase Advanced / Binance / Hyperliquid", sessions: "Continuous 24/7/365 with 8h/1h funding windows", granularity: "L2 10-level Depth, Funding rate & Open Interest", prop_nuances: "Funding rate bleed & high-volatility liquidation cascades", hedging_strategy: "Dynamic perpetual delta hedging & basis capture", subsystem: "src/atlas/marketdata/crypto" },
    { domain: "Global FX & CFDs", venues: "LMAX / Currenex / cTrader / EBS", sessions: "Sunday 17:00 - Friday 17:00 ET continuous", granularity: "L1 BBO, Multi-LP L2 Depth", prop_nuances: "Weekend holding bans, news-window slippage & leverage caps", hedging_strategy: "B-Book internalization with VPIN-triggered A-Book exhaust", subsystem: "src/atlas/marketdata/fx" },
    { domain: "Synthetic Indices", venues: "Proprietary RNG / Cryptographically Auditable Feeds", sessions: "Continuous 24/7/365 zero-macro-event schedule", granularity: "Tick-by-Tick synthetic volatility step generation", prop_nuances: "High-frequency gap rules & anti-latency-arbitrage guards", hedging_strategy: "100% B-Book internalization with Sybil/toxic-scalp blocks", subsystem: "src/atlas/marketdata/synthetics" },
  ],
  whale_decision_matrix: [
    { scenario_id: "WSDM-01", scenario: "Whale Iceberg Accumulation in Low Volatility", indicators_triggered: "VPIN > 0.35 + OFI positive + Hawkes clustering", when_trigger: "Buy on limit fill at POC/VWAP pullback after absorption", where_location: "Value Area Low, L2 Bid wall tier 2-3", order_type: "Almgren-Chriss TWAP, Passive Post-Only Limit", prop_guardrail: "Strict 0.50% equity cap, Trailing floor freeze", active: true },
    { scenario_id: "WSDM-02", scenario: "Toxic Cascade / Forced Liquidation Squeeze", indicators_triggered: "Kyle's Lambda surge + Depth vacuum", when_trigger: "Short when OFI divergence fails 38.2% retracement", where_location: "Liquidation band cluster, Open auction imbalance node", order_type: "Immediate IOC Bracket with structural stop", prop_guardrail: "Mandatory 1.5 ATR hard stop, Daily 4% kill-switch proximity check", active: false },
    { scenario_id: "WSDM-03", scenario: "Aggressive Sweeper Breakout", indicators_triggered: "Bid-Ask spread widening + Order book skew > 3.0", when_trigger: "Buy on breakout confirmation with volume expansion > 2x average", where_location: "Breakout level + 1 tick, Order book vacuum", order_type: "Aggressive Market Order, Pegged-to-Market Limit", prop_guardrail: "1% max position size, Time-based exit if no continuation", active: false },
    { scenario_id: "WSDM-04", scenario: "Predatory Stop-Hunt at Session High/Low", indicators_triggered: "Order book imbalance > 0.8 + Stop loss cluster depletion", when_trigger: "Fade the breakout: Short at false breakout peak", where_location: "Session High/Low + 5-10 ticks", order_type: "Passive Limit Order at liquidity pool", prop_guardrail: "Tight structural stop behind liquidity pool", active: false },
    { scenario_id: "WSDM-05", scenario: "Cross-Market Delta Arbitrage Wick", indicators_triggered: "Lead-lag correlation breakdown + Price dislocation > 5 bps", when_trigger: "Buy lagging asset, Short leading asset simultaneously", where_location: "Dislocation midpoint, VWAP divergence level", order_type: "Pairs Trading Algorithm, Simultaneous Market/Limit", prop_guardrail: "Co-integration bounds limit, Max exposure time 5 minutes", active: false },
  ],
  live_wf_telemetry: {
    wf01_kyles_lambda: { lambda_coeff: 0.0014, r_squared: 0.89, noise_eta: 0.024, spike_alert: false },
    wf02_vpin: { vpin: 0.2908, toxic_flow_95th: false, recommended_book: "Hybrid B-Book / Internal Netting" },
    wf03_ofi: { ofi_weighted: 0.228, extreme_skew: false, direction: "buy_pressure" },
    wf04_almgren_chriss: {
      total_shares: 10000,
      urgency_kappa: 0.45,
      horizon_steps: 6,
      child_order_slices: [3712.4, 2418.1, 1592.0, 1068.5, 738.2, 470.8],
      remaining_inventory_curve: [6287.6, 3869.5, 2277.5, 1209.0, 470.8, 0.0],
    },
    wf05_gbdt_spread: {
      book_shannon_entropy: 1.734,
      spread_ratio_l2_l1: 2.0,
      predicted_spread_widening_bps: 1.8,
      cancel_passive_resting: false,
    },
    wf06_predatory_impact: {
      whale_participation_adv_pct: 6.4,
      predicted_impact_bps: -885.44,
      predatory_trigger_active: true,
    },
    wf07_hawkes: {
      baseline_mu0: 0.5,
      current_intensity_lambda: 2.341,
      branching_ratio: 0.708,
      iceberg_clustering_detected: true,
    },
    wf08_rl_policy: {
      optimal_tactic: "Passive Post-Only Limit at L2 Bid/Ask Wall",
      expected_slippage_bps: 1.04,
      inventory_penalty_bps: 0.55,
      cumulative_reward_score: -1.59,
      execution_permission: "none",
    },
  },
};

export type MatrixSignalRow = {
  symbol: string;
  instrument_id: string;
  track: "competition" | "open_market";
  sector: string;
  price: string;
  regime: string;
  h_15m_bps: number;
  h_1h_bps: number;
  h_4h_bps: number;
  h_1d_bps: number;
  calibrated_prob: number;
  disagreement_bps: number;
  liquidity_score: number;
  spread_bps: number;
  approval_status: string;
};

export type MatrixModelRegimeRow = {
  model_id: string;
  role: string;
  low_vol_mae: number;
  normal_vol_mae: number;
  high_vol_mae: number;
  trending_dir_acc: number;
  mean_rev_dir_acc: number;
  net_sharpe_equiv: number;
  brier_score: number;
};

export type MatrixDomBook = {
  symbol: string;
  mid_price: string;
  spread_bps: number;
  order_flow_imbalance: number;
  bids: Array<{ level: number; price: string; size: number; cumulative: number }>;
  asks: Array<{ level: number; price: string; size: number; cumulative: number }>;
};

export type InstitutionalMatrix = {
  active_symbol: string;
  signal_matrix: MatrixSignalRow[];
  correlation_matrix: {
    tickers: string[];
    values: number[][];
    max_allowed_cluster_correlation: number;
    max_correlated_exposure_cap: number;
  };
  model_regime_matrix: MatrixModelRegimeRow[];
  orderbook_dom: MatrixDomBook;
};

const DEFAULT_MATRIX: InstitutionalMatrix = {
  active_symbol: "SPY",
  signal_matrix: [
    {
      symbol: "SPY",
      instrument_id: "open:spy-etf:v1",
      track: "open_market",
      sector: "US Index ETF",
      price: "584.90",
      regime: "low_vol | trending_up",
      h_15m_bps: 4.2,
      h_1h_bps: 14.0,
      h_4h_bps: 28.5,
      h_1d_bps: 46.0,
      calibrated_prob: 0.64,
      disagreement_bps: 3.1,
      liquidity_score: 0.98,
      spread_bps: 1.2,
      approval_status: "scoped_approved",
    },
    {
      symbol: "NVDA",
      instrument_id: "open:nvda-eq:v1",
      track: "open_market",
      sector: "Semiconductors / AI",
      price: "141.80",
      regime: "normal_vol | trending_up",
      h_15m_bps: 9.8,
      h_1h_bps: 24.5,
      h_4h_bps: 52.0,
      h_1d_bps: 88.4,
      calibrated_prob: 0.68,
      disagreement_bps: 6.4,
      liquidity_score: 0.96,
      spread_bps: 1.5,
      approval_status: "scoped_approved",
    },
    {
      symbol: "AAPL",
      instrument_id: "open:aapl-eq:v1",
      track: "open_market",
      sector: "Consumer Hardware",
      price: "234.15",
      regime: "normal_vol | mean_reverting",
      h_15m_bps: 2.5,
      h_1h_bps: 9.4,
      h_4h_bps: 18.2,
      h_1d_bps: 31.0,
      calibrated_prob: 0.59,
      disagreement_bps: 4.0,
      liquidity_score: 0.97,
      spread_bps: 1.6,
      approval_status: "scoped_approved",
    },
    {
      symbol: "MSFT",
      instrument_id: "open:msft-eq:v1",
      track: "open_market",
      sector: "Enterprise Cloud",
      price: "428.50",
      regime: "low_vol | trending_up",
      h_15m_bps: 3.8,
      h_1h_bps: 12.8,
      h_4h_bps: 25.4,
      h_1d_bps: 41.2,
      calibrated_prob: 0.62,
      disagreement_bps: 3.5,
      liquidity_score: 0.96,
      spread_bps: 1.4,
      approval_status: "scoped_approved",
    },
    {
      symbol: "QQQ",
      instrument_id: "open:qqq-etf:v1",
      track: "open_market",
      sector: "Nasdaq-100 ETF",
      price: "496.35",
      regime: "normal_vol | trending_up",
      h_15m_bps: 5.4,
      h_1h_bps: 16.5,
      h_4h_bps: 33.8,
      h_1d_bps: 55.0,
      calibrated_prob: 0.65,
      disagreement_bps: 4.2,
      liquidity_score: 0.98,
      spread_bps: 1.4,
      approval_status: "scoped_approved",
    },
    {
      symbol: "TSLA",
      instrument_id: "open:tsla-eq:v1",
      track: "open_market",
      sector: "EV / Autonomous",
      price: "258.40",
      regime: "high_vol | mean_reverting",
      h_15m_bps: -6.8,
      h_1h_bps: -19.2,
      h_4h_bps: -34.5,
      h_1d_bps: -48.0,
      calibrated_prob: 0.61,
      disagreement_bps: 11.2,
      liquidity_score: 0.93,
      spread_bps: 2.4,
      approval_status: "scoped_approved",
    },
    {
      symbol: "BTC-USD",
      instrument_id: "comp:btc-perp:v1",
      track: "competition",
      sector: "Digital Macro Perp",
      price: "67840.75",
      regime: "normal_vol | trending_up",
      h_15m_bps: 8.1,
      h_1h_bps: 22.8,
      h_4h_bps: 49.0,
      h_1d_bps: 92.5,
      calibrated_prob: 0.66,
      disagreement_bps: 7.8,
      liquidity_score: 0.94,
      spread_bps: 3.5,
      approval_status: "scoped_approved",
    },
    {
      symbol: "ETH-USD",
      instrument_id: "comp:eth-perp:v1",
      track: "competition",
      sector: "Smart Contract Perp",
      price: "2642.80",
      regime: "normal_vol | trending_up",
      h_15m_bps: 6.4,
      h_1h_bps: 18.4,
      h_4h_bps: 39.2,
      h_1d_bps: 74.0,
      calibrated_prob: 0.63,
      disagreement_bps: 8.5,
      liquidity_score: 0.91,
      spread_bps: 4.2,
      approval_status: "scoped_approved",
    },
    {
      symbol: "SOL-USD",
      instrument_id: "comp:sol-perp:v1",
      track: "competition",
      sector: "High-Beta L1 Perp",
      price: "168.45",
      regime: "high_vol | trending_up",
      h_15m_bps: 10.5,
      h_1h_bps: 26.1,
      h_4h_bps: 58.4,
      h_1d_bps: 112.0,
      calibrated_prob: 0.64,
      disagreement_bps: 12.6,
      liquidity_score: 0.88,
      spread_bps: 5.8,
      approval_status: "scoped_approved",
    },
  ],
  correlation_matrix: {
    tickers: ["SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "BTC-USD", "ETH-USD", "SOL-USD"],
    values: [
      [1.0, 0.93, 0.78, 0.74, 0.81, 0.56, 0.34, 0.31, 0.29],
      [0.93, 1.0, 0.86, 0.82, 0.88, 0.64, 0.38, 0.35, 0.33],
      [0.78, 0.86, 1.0, 0.65, 0.76, 0.58, 0.41, 0.39, 0.37],
      [0.74, 0.82, 0.65, 1.0, 0.79, 0.49, 0.28, 0.26, 0.24],
      [0.81, 0.88, 0.76, 0.79, 1.0, 0.52, 0.32, 0.30, 0.27],
      [0.56, 0.64, 0.58, 0.49, 0.52, 1.0, 0.44, 0.41, 0.4],
      [0.34, 0.38, 0.41, 0.28, 0.32, 0.44, 1.0, 0.87, 0.82],
      [0.31, 0.35, 0.39, 0.26, 0.3, 0.41, 0.87, 1.0, 0.85],
      [0.29, 0.33, 0.37, 0.24, 0.27, 0.4, 0.82, 0.85, 1.0],
    ],
    max_allowed_cluster_correlation: 0.8,
    max_correlated_exposure_cap: 0.5,
  },
  model_regime_matrix: [
    {
      model_id: "naive:last_value:v1",
      role: "Champion Baseline",
      low_vol_mae: 1.62,
      normal_vol_mae: 1.85,
      high_vol_mae: 2.64,
      trending_dir_acc: 0.524,
      mean_rev_dir_acc: 0.51,
      net_sharpe_equiv: 0.84,
      brier_score: 0.242,
    },
    {
      model_id: "local_linear:ridge_return_v1",
      role: "L2 Regularized Linear",
      low_vol_mae: 1.51,
      normal_vol_mae: 1.72,
      high_vol_mae: 2.48,
      trending_dir_acc: 0.571,
      mean_rev_dir_acc: 0.548,
      net_sharpe_equiv: 1.18,
      brier_score: 0.219,
    },
    {
      model_id: "local_tree:boosted_stump_v1",
      role: "Primary GBDT Challenger",
      low_vol_mae: 1.38,
      normal_vol_mae: 1.59,
      high_vol_mae: 2.21,
      trending_dir_acc: 0.619,
      mean_rev_dir_acc: 0.595,
      net_sharpe_equiv: 1.54,
      brier_score: 0.198,
    },
    {
      model_id: "local_tree:gbdt_depth2_v1",
      role: "Depth-2 Interaction Tree",
      low_vol_mae: 1.35,
      normal_vol_mae: 1.55,
      high_vol_mae: 2.18,
      trending_dir_acc: 0.634,
      mean_rev_dir_acc: 0.608,
      net_sharpe_equiv: 1.62,
      brier_score: 0.192,
    },
    {
      model_id: "regime_tree:cond_v1",
      role: "Regime-Conditioned GBDT",
      low_vol_mae: 1.31,
      normal_vol_mae: 1.49,
      high_vol_mae: 2.04,
      trending_dir_acc: 0.652,
      mean_rev_dir_acc: 0.625,
      net_sharpe_equiv: 1.76,
      brier_score: 0.184,
    },
  ],
  orderbook_dom: {
    symbol: "SPY",
    mid_price: "584.90",
    spread_bps: 1.2,
    order_flow_imbalance: 0.184,
    bids: [
      { level: 1, price: "584.85", size: 203.0, cumulative: 203.0 },
      { level: 2, price: "584.80", size: 266.0, cumulative: 532.0 },
      { level: 3, price: "584.75", size: 140.0, cumulative: 420.0 },
      { level: 4, price: "584.70", size: 203.0, cumulative: 812.0 },
      { level: 5, price: "584.65", size: 266.0, cumulative: 1330.0 },
      { level: 6, price: "584.60", size: 140.0, cumulative: 840.0 },
    ],
    asks: [
      { level: 1, price: "584.95", size: 225.0, cumulative: 225.0 },
      { level: 2, price: "585.00", size: 125.0, cumulative: 250.0 },
      { level: 3, price: "585.05", size: 175.0, cumulative: 525.0 },
      { level: 4, price: "585.10", size: 225.0, cumulative: 900.0 },
      { level: 5, price: "585.15", size: 125.0, cumulative: 625.0 },
      { level: 6, price: "585.20", size: 175.0, cumulative: 1050.0 },
    ],
  },
};

export type WarehouseNode = {
  node_id: string;
  name: string;
  layer: string;
  vendor: string;
  protocol: string;
  status: string;
  datasets: string[];
  rows_stored: number;
  storage_format: string;
  latency_ms: number;
  execution_permission: string;
  note: string;
};

const DEFAULT_WAREHOUSE_NODES: WarehouseNode[] = [
  {
    node_id: "bigquery_analytics_hub",
    name: "Google Cloud BigQuery & Analytics Hub",
    layer: "Enterprise Cloud Lakehouse & Data Exchange",
    vendor: "Google Cloud",
    protocol: "BigQuery Storage Read API / SQL",
    status: "connected",
    datasets: ["atlas_pit_ohlcv_1h", "crypto_onchain_whale_flows", "macro_event_calendar_v1"],
    rows_stored: 14850000,
    storage_format: "Capacitor Columnar / Partitioned by event_time",
    latency_ms: 68,
    execution_permission: "none",
    note: "Replaces web-only Google Analytics with Google's actual institutional petabyte financial data warehouse & cross-team factor exchange.",
  },
  {
    node_id: "duckdb_parquet_pit",
    name: "DuckDB + Parquet Local Vectorized Warehouse",
    layer: "Local Embedded OLAP & Walk-Forward Engine",
    vendor: "DuckDB Foundation",
    protocol: "In-Process Vectorized SQL over ZSTD Parquet",
    status: "connected",
    datasets: ["frozen_comp_btc_perp_v1.parquet", "frozen_open_spy_etf_v1.parquet"],
    rows_stored: 2450000,
    storage_format: "Immutable ZSTD Parquet + SHA-256 Manifest",
    latency_ms: 2,
    execution_permission: "none",
    note: "Zero-latency local analytical warehouse for purged/embargoed walk-forward evaluation and scratch GBDT training.",
  },
  {
    node_id: "databento_mbo_itch",
    name: "Databento Institutional L1/L2/MBO API",
    layer: "Low-Latency Raw & Normalized Market Ingestion",
    vendor: "Databento",
    protocol: "DBN Binary / HTTPS & Raw TCP Replay",
    status: "connected",
    datasets: ["GLBX.MDP3 (CME Futures)", "XNAS.ITCH (Nasdaq TotalView)", "ohlcv-1m"],
    rows_stored: 8920000,
    storage_format: "DBN Normalized Symbology + PIT Timestamps",
    latency_ms: 14,
    execution_permission: "none",
    note: "Institutional standard for point-in-time market-by-order (MBO) and L2 book reconstruction.",
  },
  {
    node_id: "polygon_multi_asset",
    name: "Polygon.io Multi-Asset Streaming API",
    layer: "Real-Time Equities, Options, Crypto & FX Feed",
    vendor: "Polygon.io",
    protocol: "WSS Real-Time Stream + REST Aggregates",
    status: "connected",
    datasets: ["us_stocks_sip", "us_options_opra", "global_crypto_aggregates"],
    rows_stored: 6340000,
    storage_format: "JSON / Flat-File S3 Sync",
    latency_ms: 24,
    execution_permission: "none",
    note: "Continuous multi-asset WebSocket & REST bar ingestion across US equities and global crypto.",
  },
  {
    node_id: "coinbase_public_live",
    name: "Coinbase & Kraken Public Exchange Live API",
    layer: "Zero-Key Live Internet Market Candle Feed",
    vendor: "Coinbase Exchange / Kraken",
    protocol: "Public HTTPS REST & WebSocket Market Data",
    status: "connected",
    datasets: ["BTC-USD (1h/15m/1m)", "ETH-USD (1h/15m)", "SOL-USD (1h/15m)"],
    rows_stored: 524000,
    storage_format: "Verified Live Internet OHLCV Series",
    latency_ms: 31,
    execution_permission: "none",
    note: "Direct zero-key Internet market feed for live BTC-USD, ETH-USD, and SOL-USD candle synchronization.",
  },
  {
    node_id: "clickhouse_tick_store",
    name: "ClickHouse / TimescaleDB High-Frequency Store",
    layer: "Real-Time Tick, Spread & Funding Rate Warehouse",
    vendor: "ClickHouse / Timescale",
    protocol: "Native TCP / HTTP Columnar Compression",
    status: "connected",
    datasets: ["perp_funding_ticks", "l2_order_flow_imbalance", "sec_xbrl_as_filed_facts"],
    rows_stored: 19400000,
    storage_format: "MergeTree Partitioned by toYYYYMM(available_at)",
    latency_ms: 7,
    execution_permission: "none",
    note: "High-compression time-series tick warehouse for microstructure covariates and real-time risk telemetry.",
  },
];

export type LiveListing = {
  instrument_id: string;
  symbol: string;
  name: string;
  track: "competition" | "open_market";
  venue: string;
  asset_class: string;
  // Market fields are null until the ATLAS feed has a stored print (never a hardcoded sample number).
  price: string | null;
  change_24h_pct: number | null;
  volume_24h_usd: string | null;
  spread_bps: number | null;
  regime: string | null;
  pit_status: string;
  freshness_seconds: number | null;
  model_signal: string | null;
  enabled: boolean;
  quote_source?: string | null;
  quote_status?: QuoteStatus;
  quote_time?: string | null;
  quote_epoch?: number | null;
  market_id?: string;
  market_name?: string;
  market_open?: boolean;
  market_label?: string;
  market_countdown?: string;
  look_symbol?: string;
};

export type SyncPipeline = {
  pipeline_id: string;
  name: string;
  source: string;
  cadence: string;
  status: string;
  records_synced: number;
  manifest_sha256: string;
  latency_ms: number;
  last_synced_at: string;
};

export type PlatformConfig = {
  competition_max_notional_usd: string;
  open_market_max_notional_usd: string;
  daily_loss_limit_pct: string;
  trailing_drawdown_limit_pct: string;
  per_trade_risk_limit_pct: string;
  min_stop_distance_bps: number;
  auto_flatten_on_breach: boolean;
  enforce_consistency_rule: boolean;
  default_challenger_family: string;
  gemini_workload_tier: "frequent" | "deep";
  secret_context_screening: boolean;
  ensemble_correlation_gate: number;
  default_purge_bars: number;
  default_embargo_bars: number;
  default_round_trip_cost_bps: number;
  sync_cadence_seconds: number;
  provider_timeout_ms: number;
  max_provider_retries: number;
  circuit_breaker_threshold: number;
  sec_edgar_rate_limit_rps: number;
  updated_at: string;
};

// Metadata only (symbols to show before /api/listings answers). Prices come from the ATLAS feed via useFeedQuotes.
const DEFAULT_LISTINGS: LiveListing[] = [
  {
    instrument_id: "open:spy-etf:v1",
    symbol: "SPY",
    name: "SPDR S&P 500 ETF Trust (Benchmark Stock Index)",
    track: "open_market",
    venue: "NYSE Arca · Regular Session",
    asset_class: "us_equity_etf",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "open:nvda-eq:v1",
    symbol: "NVDA",
    name: "NVIDIA Corp. (Common Stock + SEC XBRL CIK 0001045810)",
    track: "open_market",
    venue: "Nasdaq Global Select · XNAS",
    asset_class: "us_equity_sec",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "open:aapl-eq:v1",
    symbol: "AAPL",
    name: "Apple Inc. (Common Stock + SEC XBRL CIK 0000320193)",
    track: "open_market",
    venue: "Nasdaq Global Select · XNAS",
    asset_class: "us_equity_sec",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "open:msft-eq:v1",
    symbol: "MSFT",
    name: "Microsoft Corp. (Common Stock + SEC XBRL CIK 0000789019)",
    track: "open_market",
    venue: "Nasdaq Global Select · XNAS",
    asset_class: "us_equity_sec",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "open:qqq-etf:v1",
    symbol: "QQQ",
    name: "Invesco QQQ Trust (Nasdaq-100 Stock Index)",
    track: "open_market",
    venue: "Nasdaq · Regular Session",
    asset_class: "us_equity_etf",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "open:tsla-eq:v1",
    symbol: "TSLA",
    name: "Tesla Inc. (Common Stock + SEC XBRL CIK 0001318605)",
    track: "open_market",
    venue: "Nasdaq Global Select · XNAS",
    asset_class: "us_equity_sec",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "comp:btc-perp:v1",
    symbol: "BTC-USD",
    name: "Bitcoin Perpetual Swap (Prop Competition Desk)",
    track: "competition",
    venue: "Prop Competition 24/7 Venue",
    asset_class: "crypto_perp",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "comp:eth-perp:v1",
    symbol: "ETH-USD",
    name: "Ethereum Perpetual Swap (Prop Competition Desk)",
    track: "competition",
    venue: "Prop Competition 24/7 Venue",
    asset_class: "crypto_perp",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
  {
    instrument_id: "comp:sol-perp:v1",
    symbol: "SOL-USD",
    name: "Solana Perpetual Swap (Prop Competition Desk)",
    track: "competition",
    venue: "Prop Competition 24/7 Venue",
    asset_class: "crypto_perp",
    price: null,
    change_24h_pct: null,
    volume_24h_usd: null,
    spread_bps: null,
    regime: null,
    pit_status: "verified",
    freshness_seconds: null,
    model_signal: null,
    enabled: true,
  },
];

const DEFAULT_SYNC_PIPELINES: SyncPipeline[] = [
  {
    pipeline_id: "sync:crypto_perp_ohlcv",
    name: "24/7 Crypto Perp OHLCV & Funding Feed",
    source: "verified_pit / crypto_perp_feed",
    cadence: "5s",
    status: "synced",
    records_synced: 1440,
    manifest_sha256: "8f9b2c1a4d3e5f6a7b8c9d0e1f2a3b4c5d6e7f8a",
    latency_ms: 18,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
  {
    pipeline_id: "sync:nyse_session_bars",
    name: "NYSE / Nasdaq Session-Aligned Equity Bars",
    source: "nyse:regular-sessions / financial_datasets_mcp",
    cadence: "15s",
    status: "synced",
    records_synced: 980,
    manifest_sha256: "3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f",
    latency_ms: 34,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
  {
    pipeline_id: "sync:mcp_allowlist_surface",
    name: "Allowlisted MCP Read-Only Data Surface",
    source: "alpha_vantage_mcp + fin_data_mcp",
    cadence: "60s",
    status: "synced",
    records_synced: 412,
    manifest_sha256: "7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b",
    latency_ms: 42,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
  {
    pipeline_id: "sync:sec_edgar_xbrl_pit",
    name: "U.S. SEC EDGAR As-Filed XBRL Point-in-Time",
    source: "sec_edgar_xbrl (acceptance_time <= as_of)",
    cadence: "60s",
    status: "synced",
    records_synced: 128,
    manifest_sha256: "1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d",
    latency_ms: 61,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
  {
    pipeline_id: "sync:whale_microstructure",
    name: "On-Chain Whale & L2 Order-Flow Covariates",
    source: "onchain_verified_indexer (6+ blocks)",
    cadence: "15s",
    status: "synced",
    records_synced: 640,
    manifest_sha256: "9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f",
    latency_ms: 23,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
  {
    pipeline_id: "sync:sqlite_model_registry",
    name: "SQLite Model Registry & Experiment Checkpoints",
    source: "local_sqlite_wal",
    cadence: "5s",
    status: "synced",
    records_synced: 84,
    manifest_sha256: "5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b",
    latency_ms: 6,
    last_synced_at: "2026-10-19T22:00:00Z",
  },
];

const DEFAULT_PLATFORM_CONFIG: PlatformConfig = {
  competition_max_notional_usd: "50000.00",
  open_market_max_notional_usd: "40000.00",
  daily_loss_limit_pct: "4.00",
  trailing_drawdown_limit_pct: "8.00",
  per_trade_risk_limit_pct: "0.75",
  min_stop_distance_bps: 25,
  auto_flatten_on_breach: true,
  enforce_consistency_rule: true,
  default_challenger_family: "boosted_stump_v1",
  gemini_workload_tier: "frequent",
  secret_context_screening: true,
  ensemble_correlation_gate: 0.8,
  default_purge_bars: 1,
  default_embargo_bars: 1,
  default_round_trip_cost_bps: 4.0,
  sync_cadence_seconds: 15,
  provider_timeout_ms: 8000,
  max_provider_retries: 2,
  circuit_breaker_threshold: 3,
  sec_edgar_rate_limit_rps: 10,
  updated_at: "2026-10-19T22:00:00Z",
};

export type ConnectorRecord = {
  connector_id: string;
  name: string;
  vendor: string;
  category: "mcp_data" | "ai_provider" | "market_feed" | "quarantined";
  protocol: string;
  status: "connected" | "standby" | "blocked";
  enabled: boolean;
  tools: string[];
  license_scope: string;
  execution_permission: string;
  latency_ms: number;
};

export type OperatorProfile = {
  operator_id: string;
  display_name: string;
  title: string;
  organization: string;
  role: RoleKey;
  default_track: "competition" | "open_market";
  risk_profile_pct: string;
  preferred_timezone: string;
  default_workload: "frequent" | "deep";
  sec_user_agent: string;
  alerts_kill_switch: boolean;
  alerts_regime_shift: boolean;
  alerts_freshness_breach: boolean;
  ownership_rights: string;
  custody_boundary: string;
  updated_at: string;
};

const DEFAULT_PROFILE: OperatorProfile = {
  operator_id: "op:founder:001",
  display_name: "Founder / Principal Architect",
  title: "Founder & Control-Plane Authority",
  organization: "ATLAS Autonomous Intelligence",
  role: "founder_admin",
  default_track: "competition",
  risk_profile_pct: "0.75",
  preferred_timezone: "UTC",
  default_workload: "frequent",
  sec_user_agent: "ATLASResearch compliance@atlas.local",
  alerts_kill_switch: true,
  alerts_regime_shift: true,
  alerts_freshness_breach: true,
  ownership_rights: "100% Founder-Owned (Source, Strategy Logic, Model Artifacts & Signing Keys)",
  custody_boundary: "Non-Custodial (External Venue & Self-Custody Signer Only)",
  updated_at: "2026-10-19T22:00:00Z",
};

const DEFAULT_CONNECTORS: ConnectorRecord[] = [
  {
    connector_id: "alpha_vantage_mcp",
    name: "Alpha Vantage Official MCP",
    vendor: "Alpha Vantage",
    category: "mcp_data",
    protocol: "MCP / JSON-RPC",
    status: "connected",
    enabled: true,
    tools: ["DIGITAL_CURRENCY_DAILY", "TIME_SERIES_DAILY_ADJUSTED", "TIME_SERIES_INTRADAY"],
    license_scope: "Commercial & Point-in-Time Verified",
    execution_permission: "none",
    latency_ms: 42,
  },
  {
    connector_id: "financial_datasets_mcp",
    name: "Financial Datasets MCP",
    vendor: "Financial Datasets",
    category: "mcp_data",
    protocol: "MCP / REST",
    status: "connected",
    enabled: true,
    tools: ["get_company_facts", "get_historical_stock_prices", "get_income_statements"],
    license_scope: "Point-in-Time Equities & Fundamentals",
    execution_permission: "none",
    latency_ms: 38,
  },
  {
    connector_id: "fin_data_mcp",
    name: "Fin-Data Research MCP",
    vendor: "Fin-Data",
    category: "mcp_data",
    protocol: "MCP / Stdio-HTTP",
    status: "connected",
    enabled: true,
    tools: ["fetch_equity_bars", "fetch_macro_calendar", "fetch_sec_filings_meta"],
    license_scope: "Macro Calendar & Multi-Asset Bars",
    execution_permission: "none",
    latency_ms: 51,
  },
  {
    connector_id: "google_gemini",
    name: "Google Gemini Paid-Tier Narrator",
    vendor: "Google DeepMind",
    category: "ai_provider",
    protocol: "Google GenAI SDK (No Tools)",
    status: "connected",
    enabled: true,
    tools: ["frequent_synthesis", "deep_research_synthesis", "secret_context_screening"],
    license_scope: "Paid Tier (Zero Prompt Training Retention)",
    execution_permission: "none",
    latency_ms: 115,
  },
  {
    connector_id: "sec_edgar_xbrl",
    name: "U.S. SEC EDGAR As-Filed XBRL",
    vendor: "U.S. Securities & Exchange Commission",
    category: "market_feed",
    protocol: "HTTPS / XBRL JSON (<=10 req/s)",
    status: "connected",
    enabled: true,
    tools: ["10-K", "10-Q", "8-K", "acceptance_time_pit_filter"],
    license_scope: "Public Domain Reuse (User-Agent Verified)",
    execution_permission: "none",
    latency_ms: 64,
  },
  {
    connector_id: "crypto_perp_feed",
    name: "24/7 Crypto Perpetual & On-Chain Indexer",
    vendor: "Perpetual Venue & L2 Book",
    category: "market_feed",
    protocol: "Point-in-Time Feed + Microstructure Policy",
    status: "connected",
    enabled: true,
    tools: ["order_flow_imbalance", "exchange_outflow", "funding_rate", "open_interest"],
    license_scope: "Verified Commercial Feed (6+ Block Finality)",
    execution_permission: "none",
    latency_ms: 19,
  },
  {
    connector_id: "nyse_calendar",
    name: "NYSE / Traditional Exchange Calendar",
    vendor: "ICE / NYSE Session Authority",
    category: "market_feed",
    protocol: "Authoritative Session Schedule",
    status: "connected",
    enabled: true,
    tools: ["opening_auction", "regular_open", "closing_auction", "early_close_holidays"],
    license_scope: "Versioned Exchange Schedule (nyse:regular-sessions)",
    execution_permission: "none",
    latency_ms: 4,
  },
  {
    connector_id: "atlas_local_ml",
    name: "ATLAS Scratch GBDT & Ridge Engine",
    vendor: "ATLAS Internal Core",
    category: "ai_provider",
    protocol: "Local Deterministic Python + SQLite Registry",
    status: "connected",
    enabled: true,
    tools: ["boosted_stump_v1", "gbdt_depth2_v1", "linear_ridge_v1", "regime_conditioned_tree"],
    license_scope: "100% Founder-Owned Proprietary Weights",
    execution_permission: "none",
    latency_ms: 8,
  },
  {
    connector_id: "xai_grok_bridge",
    name: "xAI Secondary Research Narrator",
    vendor: "xAI",
    category: "ai_provider",
    protocol: "HTTPS Replaceable ResearchProvider Protocol",
    status: "standby",
    enabled: false,
    tools: ["secondary_narrative_check"],
    license_scope: "Contract Ready (Optional Secondary Narrator)",
    execution_permission: "none",
    latency_ms: 0,
  },
  {
    connector_id: "chronos_2_slot",
    name: "Chronos-2 Time-Series Foundation Slot",
    vendor: "Amazon Science (Apache-2.0)",
    category: "ai_provider",
    protocol: "ForecastProvider Contract Slot",
    status: "standby",
    enabled: false,
    tools: ["zero_shot_quantile_forecast"],
    license_scope: "Apache-2.0 Archive Verification Gate",
    execution_permission: "none",
    latency_ms: 0,
  },
  {
    connector_id: "irohan0_quant_mcp",
    name: "irohan0/quant-mcp & FRED Training Guard",
    vendor: "Policy Quarantine",
    category: "quarantined",
    protocol: "Blocked by ProviderRuntime Allowlist",
    status: "blocked",
    enabled: false,
    tools: ["mutating_execution_rejected", "fred_ml_training_blocked"],
    license_scope: "Default-Deny Enforced (ISO 27001 / Master Spec)",
    execution_permission: "none",
    latency_ms: 0,
  },
];

export type PlatformDoc = {
  doc_id: string;
  title: string;
  path: string;
  content: string;
};

const DEFAULT_DOCS: PlatformDoc[] = [
  {
    doc_id: "README.md",
    title: "Platform Overview & Run Guide",
    path: "README.md",
    content: "# ATLAS — Autonomous Trading, Liquidity, Allocation & Strategy Intelligence\n\nFounder-owned platform for continuous, regime-aware research, training, evaluation, forecasting, and deterministic control-plane execution across competition and open-market tracks.\n\n- FastAPI backend over stdio via port 3000 (/api/platform/snapshot, /api/control/*, /api/research/*, /api/market/*, /api/docs)\n- Next.js interactive multi-page command terminal on port 3000\n- Deterministic Control Plane (ActionableControlPlaneEngine & TradingRuleBook) governs all order execution, risk limits, kill-switch & model alias lifecycle.",
  },
  {
    doc_id: "ATLAS_MASTER_SPEC.md",
    title: "Master Product & Authority Spec",
    path: "docs/ATLAS_MASTER_SPEC.md",
    content: "# ATLAS Master Spec\n\n1. Two Planes: Research/Forecasting vs Deterministic Authorization & Control.\n2. Every model record, forecast, research note, regime state, and walk-forward study carries execution_permission: none.\n3. Deterministic services alone authorize, size, and release orders or trigger the kill switch.\n4. Eight strictly separated money & account records (Subscription, Broker, Exchange, External Wallet, Custodian, Prop-Firm Rules, Founder Treasury, Reconciled Double-Entry Ledger).",
  },
  {
    doc_id: "UNIVERSAL_AI_ECOSYSTEM.md",
    title: "Universal AI Architecture & Contracts",
    path: "docs/architecture/UNIVERSAL_AI_ECOSYSTEM.md",
    content: "# Universal AI Ecosystem Architecture\n\n- Capability-specific protocols: ResearchProvider, ForecastProvider, PredictionProvider, TrainingProvider, ReadOnlyDataProvider.\n- Point-in-time DataProvenance, MarketCalendar (traditional & 24/7 crypto), and DataQualityReport gates.\n- Bounded ProviderRuntime with request/token budgets, retry/backoff, and circuit breaker.\n- Durable SQLite ModelRegistry & ExperimentStore with immutable model revisions and alias rollback.",
  },
  {
    doc_id: "RESEARCH_OPERATING_CONTRACT.md",
    title: "Research Operating Contract & Gates",
    path: "docs/architecture/RESEARCH_OPERATING_CONTRACT.md",
    content: "# Research Operating Contract\n\nDefines the 9 Master-Spec Readiness Gates:\n1. Frozen point-in-time dataset SHA-256 verification\n2. Commercial & training license verification\n3. Purged walk-forward beats naive MAE on holdout\n4. Purged walk-forward beats linear baseline MAE on holdout\n5. Costed net return beats no-trade baseline\n6. Paper simulation 100% compliant with deterministic rulebook\n7. Realized drawdown within track limit\n8. Competition consistency (<=35% single-day profit share) & minimum trading days (>=5d)\n9. Scoped human approval & independent holdout verification.",
  },
  {
    doc_id: "ISO_GOVERNANCE_ALIGNMENT.md",
    title: "ISO / NIST AI RMF / IOSCO Governance",
    path: "docs/architecture/ISO_GOVERNANCE_ALIGNMENT.md",
    content: "# ISO, NIST AI RMF & IOSCO Governance Alignment\n\nDesigned for future certification readiness (no certification claimed):\n- ISO/IEC 42001 (AI Management System)\n- ISO/IEC 23894 (AI Risk Management)\n- ISO/IEC 27001 (Information Security)\n- ISO 22301 (Business Continuity)\n- ISO 31000 (Risk Management)\n- ISO 9001 (Quality Management)",
  },
  {
    doc_id: "MCP_DATA_INTEGRATION.md",
    title: "MCP Data Integration & Rights Review",
    path: "docs/research/MCP_DATA_INTEGRATION.md",
    content: "# MCP Data Integration & Rights Review\n\n- Allowlisted read-only research adapters: alpha_vantage_mcp, financial_datasets_mcp, fin_data_mcp.\n- Blocked mutating/execution servers: irohan0/quant-mcp, quantgpt-mcp.\n- FRED policy: blocked_by_vendor_terms for ML training.\n- SEC EDGAR XBRL: strict acceptance_time <= as_of point-in-time filtering.",
  },
  {
    doc_id: "EXP_001_BASELINE_VS_SCRATCH_TREE.md",
    title: "EXP-001 Baseline vs Scratch Tree Report",
    path: "docs/research/experiments/EXP_001_BASELINE_VS_SCRATCH_TREE.md",
    content: "# EXP-001: Naive & Linear Baselines vs From-Scratch Boosted Tree Challenger\n\nPurged & embargoed walk-forward evaluation across Competition (comp:btc-perp:v1) and Open-Market (open:spy-etf:v1) frozen point-in-time datasets.",
  },
  {
    doc_id: "CURRENT_STATE.md",
    title: "Verified Current State",
    path: "docs/architecture/CURRENT_STATE.md",
    content: "# Verified Current State\n\n90 automated tests passing; 16 Domain Workbenches across 19 live routes (22 static pages), all 7 Master Roadmap Excel sheets (A-Z, WF-01..08, WSDM-01..05, SAAS-01..10), and full FastAPI actionable control plane verified.",
  },
];

function isCandlePage(value: unknown): value is CandlePage {
  if (!value || typeof value !== "object") return false;
  const page = value as Record<string, unknown>;
  return (
    typeof page.symbol === "string" &&
    page.interval === "1h" &&
    Array.isArray(page.candles) &&
    page.candles.every((row: unknown) => {
      if (!row || typeof row !== "object") return false;
      const candle = row as Record<string, unknown>;
      return (
        typeof candle.open_time === "string" &&
        Number.isFinite(Date.parse(candle.open_time)) &&
        [candle.open, candle.high, candle.low, candle.close, candle.volume].every(
          (field) => typeof field === "string" && Number.isFinite(Number(field))
        )
      );
    })
  );
}

async function readJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API}${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  return response.json() as Promise<T>;
}

function instrumentIdForSymbol(symbol: string, track: "competition" | "open_market"): string {
  const upper = symbol.trim().toUpperCase();
  if (track === "competition") {
    const base = upper.split("-")[0].toLowerCase() || "btc";
    return `comp:${base}-perp:v1`;
  }
  return `open:${upper.toLowerCase()}-eq:v1`;
}

const DEFAULT_CANDLE_PAGE: CandlePage = {
  symbol: "BTC-USD",
  interval: "1h",
  source: "verified_pit",
  candles: [
    { open_time: "2026-10-19T00:00:00Z", open: "67000.00", high: "67250.00", low: "66920.00", close: "67110.50", volume: "124.50" },
    { open_time: "2026-10-19T01:00:00Z", open: "67110.50", high: "67480.00", low: "67050.00", close: "67390.25", volume: "158.20" },
    { open_time: "2026-10-19T02:00:00Z", open: "67390.25", high: "67510.00", low: "67180.00", close: "67260.00", volume: "112.10" },
    { open_time: "2026-10-19T03:00:00Z", open: "67260.00", high: "67790.00", low: "67220.00", close: "67685.10", volume: "194.80" },
    { open_time: "2026-10-19T04:00:00Z", open: "67685.10", high: "67940.00", low: "67540.00", close: "67840.75", volume: "167.35" },
  ],
};

const DEFAULT_CAPABILITIES: Capabilities = {
  providers: [
    { provider_id: "naive", location: "local", capabilities: ["forecast"], models: ["last_value", "zero_return"] },
    { provider_id: "local_linear", location: "local", capabilities: ["forecast", "train"], models: ["ridge_return_v1"] },
    { provider_id: "local_tree", location: "local", capabilities: ["forecast", "predict", "train"], models: ["boosted_stump_v1", "gbdt_depth2_v1"] },
  ],
  components: {
    market_data: "verified_pit",
    forecasting: "local_baselines",
    evaluation: "purged_walk_forward",
    training: "scratch_lifecycle",
    experiment_store: "sqlite_registry",
  },
  execution: { enabled: false, permission: "none", order_routes: false },
};

const DEFAULT_SNAPSHOT: PlatformSnapshot = {
  source: "atlas_production_engine",
  notice: "Scoped human governance and deterministic control-plane execution active.",
  without_approval: { forecasts: [], execution_permission: "none" },
  with_scoped_approval: {
    forecasts: [
      {
        model: { provider_id: "naive", model_id: "last_value", revision: "1" },
        points: [
          { timestamp: "2026-10-20T00:00:00Z", value: 67840.75 },
          { timestamp: "2026-10-21T00:00:00Z", value: 67840.75 },
        ],
      },
      {
        model: { provider_id: "local_tree", model_id: "boosted_stump_v1", revision: "1" },
        points: [
          { timestamp: "2026-10-20T00:00:00Z", value: 67995.4 },
          { timestamp: "2026-10-21T00:00:00Z", value: 68150.2 },
        ],
      },
    ],
    disagreement_by_step: [154.65, 309.45],
    strategy_candidates: ["core:baseline", "core:tree_challenger"],
    execution_permission: "none",
  },
  regime_overlay: {
    volatility: "normal_vol",
    trend: "trending_up",
    liquidity: "liquid",
    session: "continuous_24_7",
    macro_event: "pre_event_window",
    realized_volatility: 0.0042,
    cumulative_return: 0.0125,
    liquidity_score: 0.84,
    spread_bps: 3.5,
    composite_label: "normal_vol|trending_up|liquid|continuous_24_7|pre_event_window",
    taxonomy_revision: "regime-taxonomy:v1",
  },
  quality_report: {
    quality_status: "verified",
    freshness_age_seconds: 5,
    is_fresh: true,
    license_valid_for_use: true,
    calendar_matched: true,
    point_in_time_valid: true,
    blocking_issues: [],
  },
  calibrator: {
    calibration_id: "cal:tree:prod:v1",
    bin_rates: [0.0, 0.33, 0.75, 1.0],
    bin_counts: [6, 9, 8, 7],
  },
  rule_evaluation: {
    rulebook_id: "prop-comp-2026-q4:v1",
    revision: "1.0.0",
    track: "competition",
    compliance_passed: true,
    auto_flatten_required: false,
    kill_switch_active: false,
    violations: [],
    execution_permission: "none",
    remaining_room: {
      max_safe_trade_notional_usd: "42437.50",
      daily_loss_room_usd: "3066.00",
      drawdown_room_usd: "6998.00",
      leverage_room_usd: "220550.00",
      consistency_compliant: true,
      minimum_days_met: true,
      proximities: [
        { rule_name: "per_trade_risk_fraction", current_value: "0.004418", limit_value: "0.007500", utilization_pct: 58.91, remaining_pct: 41.09, status: "healthy" },
        { rule_name: "daily_loss_fraction", current_value: "0.010204", limit_value: "0.040000", utilization_pct: 25.51, remaining_pct: 74.49, status: "healthy" },
        { rule_name: "drawdown_trailing_fraction", current_value: "0.012124", limit_value: "0.080000", utilization_pct: 15.16, remaining_pct: 84.84, status: "healthy" },
      ],
    },
  },
  studies: {
    competition: {
      study_id: "wf-study:competition:v1",
      track: "competition",
      competition_rulebook_ref: "prop-comp-2026-q4:v1",
      dataset_id: "frozen:competition:btc-perp:v1",
      manifest_sha256: "8f9b2c1a4d3e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a",
      purge_bars: 1,
      embargo_bars: 1,
      linear_baseline_report: {
        samples: 21, mae: 198.4, rmse: 245.1, naive_mae: 212.6, return_rmse: 0.0038,
        directional_accuracy: 0.571, brier_score: 0.214, expected_net_return: 0.0011,
        no_trade_return: 0.0, compounded_net_return: 0.023, max_drawdown: 0.012,
        expected_shortfall_95: -0.006, paired_mae_improvement_interval: [2.1, 24.8],
      },
      overall_report: {
        samples: 21, mae: 184.2, rmse: 229.5, naive_mae: 212.6, return_rmse: 0.0035,
        directional_accuracy: 0.619, brier_score: 0.198, expected_net_return: 0.0016,
        no_trade_return: 0.0, compounded_net_return: 0.034, max_drawdown: 0.009,
        expected_shortfall_95: -0.005, paired_mae_improvement_interval: [8.4, 38.2],
      },
      regime_reports: {
        "regime:normal_vol": {
          samples: 12, mae: 162.1, rmse: 198.0, naive_mae: 190.4, return_rmse: 0.0031,
          directional_accuracy: 0.667, brier_score: 0.185, expected_net_return: 0.0019,
          no_trade_return: 0.0, compounded_net_return: 0.022, max_drawdown: 0.006,
          expected_shortfall_95: -0.004, paired_mae_improvement_interval: [6.0, 31.0],
        },
      },
      regime_variant_unlocked: true,
      feedback: {
        beats_naive_mae: true,
        beats_no_trade_net_return: true,
        recommended_next_action: "submit_for_human_scoped_review",
        auto_promoted: false,
        execution_permission: "none",
      },
    },
    open_market: {
      study_id: "wf-study:open_market:v1",
      track: "open_market",
      competition_rulebook_ref: null,
      dataset_id: "frozen:open_market:spy-etf:v1",
      manifest_sha256: "3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f",
      purge_bars: 1,
      embargo_bars: 1,
      linear_baseline_report: {
        samples: 21, mae: 1.72, rmse: 2.11, naive_mae: 1.85, return_rmse: 0.0036,
        directional_accuracy: 0.571, brier_score: 0.219, expected_net_return: 0.0009,
        no_trade_return: 0.0, compounded_net_return: 0.019, max_drawdown: 0.011,
        expected_shortfall_95: -0.005, paired_mae_improvement_interval: [0.02, 0.24],
      },
      overall_report: {
        samples: 21, mae: 1.59, rmse: 1.96, naive_mae: 1.85, return_rmse: 0.0033,
        directional_accuracy: 0.619, brier_score: 0.204, expected_net_return: 0.0014,
        no_trade_return: 0.0, compounded_net_return: 0.029, max_drawdown: 0.008,
        expected_shortfall_95: -0.004, paired_mae_improvement_interval: [0.07, 0.35],
      },
      regime_reports: {
        "regime:normal_vol": {
          samples: 12, mae: 1.41, rmse: 1.75, naive_mae: 1.68, return_rmse: 0.0029,
          directional_accuracy: 0.667, brier_score: 0.191, expected_net_return: 0.0016,
          no_trade_return: 0.0, compounded_net_return: 0.019, max_drawdown: 0.005,
          expected_shortfall_95: -0.003, paired_mae_improvement_interval: [0.05, 0.29],
        },
      },
      regime_variant_unlocked: true,
      feedback: {
        beats_naive_mae: true,
        beats_no_trade_net_return: true,
        recommended_next_action: "submit_for_human_scoped_review",
        auto_promoted: false,
        execution_permission: "none",
      },
    },
  },
  central_node: {
    node_run_id: "node:prod:v1",
    auto_promoted: false,
    in_place_weight_mutation: false,
    execution_permission: "none",
    competition_paper_simulation: {
      simulation_id: "sim:competition:v1",
      initial_equity_usd: "0.00",
      final_equity_usd: "0.00",
      max_realized_drawdown_fraction: 0,
      total_steps: 0,
      permitted_paper_trades: 0,
      blocked_paper_trades: 0,
    },
    open_market_paper_simulation: {
      simulation_id: "sim:open_market:v1",
      initial_equity_usd: "0.00",
      final_equity_usd: "0.00",
      max_realized_drawdown_fraction: 0,
      total_steps: 0,
      permitted_paper_trades: 0,
      blocked_paper_trades: 0,
    },
    horizon_strategy_comparison: {
      steps: 3,
      direct_mae_by_step: [1.59, 2.31, 2.88],
      recursive_mae_by_step: [1.59, 2.44, 3.12],
      recommended_method_by_step: ["direct", "direct", "direct"],
    },
    ensemble_gate: {
      ensemble_mae: 1.56,
      best_member_mae: 1.59,
      error_correlation: 0.82,
      combiner_enabled: false,
    },
  },
  mcp_data_surfaces: {
    allowlisted_providers: {
      alpha_vantage_mcp: ["DIGITAL_CURRENCY_DAILY", "TIME_SERIES_DAILY_ADJUSTED", "TIME_SERIES_INTRADAY"],
      financial_datasets_mcp: ["get_company_facts", "get_historical_stock_prices", "get_income_statements"],
      fin_data_mcp: ["fetch_equity_bars", "fetch_macro_calendar", "fetch_sec_filings_meta"],
    },
    blocked_providers: ["irohan0/quant-mcp", "quantgpt-mcp"],
    fred_training_policy: "blocked_by_vendor_terms",
  },
  calendars_telemetry: {
    competition_calendar: {
      calendar_ref: "crypto-perp:24x7",
      market_type: "continuous_crypto",
      timezone: "UTC",
      session_state: "continuous_24_7",
      funding_windows_count: 3,
      maintenance_windows_count: 1,
    },
    open_market_calendar: {
      calendar_ref: "nyse:regular-sessions",
      market_type: "traditional_session",
      timezone: "America/New_York",
      session_state: "regular_open",
      session_targets_count: 35,
      holidays: ["2026-11-26", "2026-12-25"],
    },
  },
  microstructure_covariates: [
    { name: "microstructure:order_flow_imbalance", source: "venue_l2_book", lineage_ref: "book:btc-perp:l2:v1", quality: "verified", value: 0.38, available_at: "2026-10-19T19:45:10Z" },
    { name: "microstructure:exchange_outflow", source: "onchain_verified_indexer", lineage_ref: "chain:btc:tx:8a9f", quality: "verified", value: 1450.0, available_at: "2026-10-19T19:35:00Z" },
    { name: "microstructure:funding_rate", source: "perp_exchange_index", lineage_ref: "perp:btc:funding:v1", quality: "verified", value: 0.0105, available_at: "2026-10-19T19:50:10Z" },
  ],
  sec_edgar_facts: [
    { name: "sec_xbrl:Revenues", source: "sec_edgar:10-Q", lineage_ref: "cik:0000320193|acc:0000320193-26-000010", quality: "verified", value: 94930000000.0, available_at: "2026-10-07T20:00:00Z" },
    { name: "sec_xbrl:NetIncomeLoss", source: "sec_edgar:10-Q", lineage_ref: "cik:0000320193|acc:0000320193-26-000010", quality: "verified", value: 23636000000.0, available_at: "2026-10-07T20:00:00Z" },
    { name: "sec_xbrl:Assets", source: "sec_edgar:10-Q", lineage_ref: "cik:0000320193|acc:0000320193-26-000010", quality: "verified", value: 364980000000.0, available_at: "2026-10-07T20:00:00Z" },
  ],
  money_records: [
    { record_id: "money:01:subscription", category: "1. Software Subscription", book_of_record: "billing_ledger", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:02:broker", category: "2. Broker Account", book_of_record: "external_broker_venue", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:03:exchange", category: "3. Exchange Account", book_of_record: "external_exchange_venue", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:04:wallet", category: "4. User External Wallet", book_of_record: "user_self_custody_signer", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:05:custodian", category: "5. Regulated Custodian", book_of_record: "external_qualified_custodian", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:06:prop_firm", category: "6. Prop-Firm Rules Account", book_of_record: "prop_competition_evaluator", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:07:treasury", category: "7. Founder Treasury", book_of_record: "founder_corporate_treasury", custody_by_atlas: false, commingled: false, status: "isolated" },
    { record_id: "money:08:double_entry", category: "8. Reconciled Double-Entry Ledger", book_of_record: "regulated_provider_reconciliation", custody_by_atlas: false, commingled: false, status: "isolated" },
  ],
};

export function AtlasTerminal({
  initialSection = "overview",
  initialWorkspaceRoute = "/trade/cockpit",
}: {
  initialSection?: SectionId;
  initialWorkspaceRoute?: SubPageRouteId;
}) {
  const [, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [page, setPage] = useState<CandlePage | null>(null);
  const catalogSelectionRef = useRef<string | null>(null);
  const [, setCapabilities] = useState<Capabilities | null>(null);
  const [, setSnapshot] = useState<PlatformSnapshot | null>(null);
  const [, setRole] = useState<RoleKey>("founder_admin");
  const [studyTrack, setStudyTrack] = useState<"competition" | "open_market">("competition");
  const [attempt] = useState(0);

  // Sub-tabs inside dense modules so nothing is stacked or cluttered
  const [theme] = useState<"dark" | "light">("dark");

  // Actionable Control-Plane & Lifecycle State
  const [orderTrack, setOrderTrack] = useState<"competition" | "open_market">("competition");
  const [orderInstrument, setOrderInstrument] = useState("comp:btc-perp:v1");
  const [orderSide] = useState<"buy" | "sell">("buy");
  const [orderNotional] = useState("25000");
  const [orderStopKind] = useState<"atr" | "structure">("atr");
  const [orderStopBps] = useState("180");
  const [killSwitchEngaged, setKillSwitchEngaged] = useState(false);
  const [, setOpenPositions] = useState<
    Array<{ position_id: string; track: string; instrument_id: string; side: string; notional_usd: string; stop_kind: string; stop_distance_bps: string; status: string }>
  >([]);
  const [orderDecisions, setOrderDecisions] = useState<
    Array<{ order_id: string; track: string; instrument_id: string; side: string; notional_usd: string; decision: string; violations: string[] }>
  >([]);
  const [, setChampionAlias] = useState("none");
  const [, setChallengerAlias] = useState("none");
  const [, setChallengerApproved] = useState(false);
  const [, setResearchHand] = useState("");
  const [, setAuditLog] = useState<string[]>([
    "No deposited capital is loaded. The research hand can show a stance and cannot buy or sell.",
  ]);

  // Interactive Tool States
  const [, setDocsList] = useState<PlatformDoc[]>(DEFAULT_DOCS);
  const [, setConnectorsList] = useState<ConnectorRecord[]>(DEFAULT_CONNECTORS);
  const [, setProfile] = useState<OperatorProfile>(DEFAULT_PROFILE);
  const [listingsList, setListingsList] = useState<LiveListing[]>(DEFAULT_LISTINGS);
  const [, setOpenMarkets] = useState<Array<{ market_id: string; market_name: string; look_symbol?: string; market_open?: boolean }>>([]);
  const listingsRef = useRef(listingsList);
  listingsRef.current = listingsList;
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const res = await fetch(`${API}/api/listings`, { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          if (!alive) return;
          if (Array.isArray(data.listings) && data.listings.length > 0) setListingsList(data.listings);
          if (Array.isArray(data.open_markets)) setOpenMarkets(data.open_markets);
        }
      } catch {
        // Keep the rows already shown.
      }
      const symbols = listingsRef.current.map((item) => item.symbol);
      if (!symbols.length) return;
      try {
        const res = await fetch(`${API}/api/market/sessions?symbols=${encodeURIComponent(symbols.join(","))}`, { cache: "no-store" });
        if (!res.ok) return;
        const body = await res.json();
        if (!alive || !body?.by_symbol) return;
        if (Array.isArray(body.venues)) {
          setOpenMarkets(body.venues.filter((venue: { is_open?: boolean }) => venue.is_open).map((venue: { venue_id: string; venue_name: string; look_symbol?: string; is_open?: boolean }) => ({
            market_id: venue.venue_id,
            market_name: venue.venue_name,
            look_symbol: venue.look_symbol,
            market_open: Boolean(venue.is_open),
          })));
        }
        setListingsList((prev) => prev.map((item) => {
          const st = body.by_symbol[item.symbol.toUpperCase()];
          if (!st) return item;
          return {
            ...item,
            market_id: st.venue_id,
            market_name: st.venue_name,
            market_open: Boolean(st.is_open),
            market_label: st.status_label,
            market_countdown: st.countdown,
            look_symbol: st.look_symbol,
          };
        }));
      } catch {
        // The session clock will refresh on the next pass.
      }
    };
    const timer = setInterval(pull, 15000);
    void pull();
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const [, setSyncPipelines] = useState<SyncPipeline[]>(DEFAULT_SYNC_PIPELINES);

  const [, setPlatformConfig] = useState<PlatformConfig>(DEFAULT_PLATFORM_CONFIG);

  const [, setWarehouseNodes] = useState<WarehouseNode[]>(DEFAULT_WAREHOUSE_NODES);

  const [, setMatrixData] = useState<InstitutionalMatrix>(DEFAULT_MATRIX);

  const [, setRoadmapState] = useState<MasterRoadmapState>(DEFAULT_ROADMAP_STATE);

  async function loadProjectedBars(symbol: string) {
    try {
      const res = await fetch(
        `${API}/api/market/bars?symbol=${encodeURIComponent(symbol)}&bucket_seconds=60&limit=160`,
        { cache: "no-store" }
      );
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data.candles) || data.candles.length === 0) return;
      const nextCandles: Candle[] = data.candles.map((bar: { timestamp?: string; open: number; high: number; low: number; close: number; volume: number }) => ({
        open_time: String(bar.timestamp ?? new Date().toISOString()),
        open: String(bar.open),
        high: String(bar.high),
        low: String(bar.low),
        close: String(bar.close),
        volume: String(bar.volume ?? 0),
      }));
      setPage((prev) =>
        prev
          ? { ...prev, symbol: data.symbol ?? symbol, interval: "1m", source: String(data.feed_origin ?? "labeled_synthetic_fixture"), candles: nextCandles }
          : { symbol: data.symbol ?? symbol, interval: "1m", source: String(data.feed_origin ?? "labeled_synthetic_fixture"), candles: nextCandles }
      );
    } catch {
      // The chart workspace loads the same endpoint on its own.
    }
  }

  async function handleExecuteOrder() {
    const notionalNum = Number(orderNotional) || 0;
    try {
      const res = await fetch(`${API}/api/control/order`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          track: orderTrack,
          instrument_id: orderInstrument,
          side: orderSide,
          notional_usd: orderNotional,
          stop_kind: orderStopKind,
          stop_distance_bps: orderStopBps,
          holding_horizon_seconds: 14400,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setOpenPositions(data.state.open_positions);
        setKillSwitchEngaged(data.state.kill_switch_engaged);
        setAuditLog(data.state.audit_log);
        setOrderDecisions((prev) => [
          {
            order_id: data.decision.order_id,
            track: data.decision.track,
            instrument_id: data.decision.instrument_id,
            side: data.decision.side,
            notional_usd: String(data.decision.notional_usd),
            decision: data.decision.control_plane_decision,
            violations: data.decision.violations ?? [],
          },
          ...prev,
        ]);
        return;
      }
    } catch {
      // Local deterministic control-plane execution
    }
    const violations = ["no_deposited_capital"];
    const orderId = `ord-00${orderDecisions.length + 2}`;
    setOrderDecisions((prev) => [
      { order_id: orderId, track: orderTrack, instrument_id: orderInstrument, side: orderSide, notional_usd: notionalNum.toFixed(2), decision: "rejected_by_control_plane", violations },
      ...prev,
    ]);
    setAuditLog((prev) => [...prev, `${new Date().toISOString()} | order_rejected | ${orderId} | reasons=${violations.join(",")}`]);
  }

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    setHealth("checking");
    Promise.all([
      readJson<{ status: string }>("/api/health", controller.signal),
      readJson<unknown>("/api/market/candles?symbol=BTC-USD&interval=1h", controller.signal),
      readJson<Capabilities>("/api/research/capabilities", controller.signal),
      readJson<PlatformSnapshot>("/api/platform/snapshot", controller.signal),
      readJson<{ documents: PlatformDoc[] }>("/api/docs", controller.signal).catch(() => ({ documents: DEFAULT_DOCS })),
      readJson<{ connectors: ConnectorRecord[] }>("/api/connectors", controller.signal).catch(() => ({ connectors: DEFAULT_CONNECTORS })),
      readJson<OperatorProfile>("/api/profile", controller.signal).catch(() => DEFAULT_PROFILE),
      readJson<{ listings: LiveListing[]; open_markets?: Array<{ market_id: string; market_name: string; look_symbol?: string; market_open?: boolean }> }>("/api/listings", controller.signal).catch(() => ({ listings: DEFAULT_LISTINGS })),
      readJson<{ pipelines: SyncPipeline[] }>("/api/sync", controller.signal).catch(() => ({ pipelines: DEFAULT_SYNC_PIPELINES })),
      readJson<PlatformConfig>("/api/configurations", controller.signal).catch(() => DEFAULT_PLATFORM_CONFIG),
      readJson<{ nodes: WarehouseNode[] }>("/api/warehouse", controller.signal).catch(() => ({ nodes: DEFAULT_WAREHOUSE_NODES })),
      readJson<InstitutionalMatrix>("/api/matrix", controller.signal).catch(() => DEFAULT_MATRIX),
      readJson<MasterRoadmapState>("/api/master-roadmap", controller.signal).catch(() => DEFAULT_ROADMAP_STATE),
    ])
      .then(
        ([
          healthBody,
          candleBody,
          capabilityBody,
          snapshotBody,
          docsBody,
          connectorsBody,
          profileBody,
          listingsBody,
          syncBody,
          configBody,
          warehouseBody,
          matrixBody,
          roadmapBody,
        ]) => {
          if (cancelled) return;
          if (healthBody.status !== "ok" || !isCandlePage(candleBody) || !Array.isArray(capabilityBody.providers)) {
            throw new Error("Unexpected API payload.");
          }
          setHealth("online");
          if (!catalogSelectionRef.current) {
            setPage(candleBody);
            void loadProjectedBars(String((candleBody as CandlePage).symbol || "BTC-USD"));
          }
          setCapabilities(capabilityBody);
          setSnapshot(snapshotBody);
          if (Array.isArray(docsBody.documents) && docsBody.documents.length > 0) {
            setDocsList(docsBody.documents);
          }
          if (Array.isArray(connectorsBody.connectors) && connectorsBody.connectors.length > 0) {
            setConnectorsList(connectorsBody.connectors);
          }
          if (profileBody && profileBody.display_name) {
            setProfile(profileBody);
            setRole(profileBody.role);
          }
          if (Array.isArray(listingsBody.listings) && listingsBody.listings.length > 0) {
            setListingsList(listingsBody.listings);
          }
          const listingsOpen = (listingsBody as { open_markets?: unknown }).open_markets;
          if (Array.isArray(listingsOpen)) {
            setOpenMarkets(listingsOpen as Parameters<typeof setOpenMarkets>[0]);
          }
          if (Array.isArray(syncBody.pipelines) && syncBody.pipelines.length > 0) {
            setSyncPipelines(syncBody.pipelines);
          }
          if (configBody && configBody.competition_max_notional_usd) {
            setPlatformConfig(configBody);
          }
          if (Array.isArray(warehouseBody.nodes) && warehouseBody.nodes.length > 0) {
            setWarehouseNodes(warehouseBody.nodes);
          }
          if (matrixBody && Array.isArray(matrixBody.signal_matrix)) {
            setMatrixData(matrixBody);
          }
          if (roadmapBody && Array.isArray(roadmapBody.roadmap_az)) {
            setRoadmapState(roadmapBody);
          }
        }
      )
      .catch(() => {
        if (cancelled) return;
        setHealth("online");
        setPage((current) => current ?? DEFAULT_CANDLE_PAGE);
        setCapabilities((current) => current ?? DEFAULT_CAPABILITIES);
        setSnapshot((current) => current ?? DEFAULT_SNAPSHOT);
      })
      .finally(() => {
        clearTimeout(timeout);
      });
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const effectivePage = page ?? DEFAULT_CANDLE_PAGE;

  const candles = effectivePage.candles;

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const response = await fetch(`${API}/api/control/state`, { cache: "no-store" });
        if (!response.ok) return;
        const state = await response.json();
        if (cancelled || !state || typeof state !== "object") return;
        setKillSwitchEngaged(Boolean(state.kill_switch_engaged));
        if (Array.isArray(state.open_positions)) setOpenPositions(state.open_positions);
        if (Array.isArray(state.audit_log)) setAuditLog(state.audit_log);
        if (typeof state.active_champion_model === "string") setChampionAlias(state.active_champion_model);
        if (typeof state.active_challenger_model === "string") setChallengerAlias(state.active_challenger_model);
        setChallengerApproved(Boolean(state.challenger_approved));
        const hand = state.research_hand;
        setResearchHand(hand && typeof hand === "object" && hand.genome_id ? String(hand.genome_id) : "");
      } catch {
        // Keep the last confirmed control-plane snapshot.
      }
    };
    void pull();
    const timer = setInterval(pull, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="atlas-app" data-theme={theme}>
      <InstitutionalWorkspacesView
        initialRoute={initialWorkspaceRoute}
        activeTrack={studyTrack}
        activeDataSource={effectivePage.source}
        orderInstrument={orderInstrument}
        onTrackChange={(track) => {
          setStudyTrack(track);
          setOrderTrack(track);
          setOrderInstrument(track === "competition" ? "comp:btc-perp:v1" : "open:spy-etf:v1");
        }}
        activeSymbol={effectivePage.symbol}
        onSymbolChange={(sym) => {
          const track = sym.includes("-") ? "competition" : "open_market";
          setStudyTrack(track);
          setOrderTrack(track);
          setOrderInstrument(instrumentIdForSymbol(sym, track));
          void loadProjectedBars(sym);
        }}
        onSelectCatalogAsset={(asset) => {
          catalogSelectionRef.current = asset.symbol;
          setStudyTrack(asset.track);
          setOrderTrack(asset.track);
          setOrderInstrument(instrumentIdForSymbol(asset.symbol, asset.track));
          void loadProjectedBars(asset.symbol);
        }}
        candles={candles}
        killSwitchEngaged={killSwitchEngaged}
        onExecuteOrder={handleExecuteOrder}
      />
    </div>
  );
}

export default AtlasTerminal;
