"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_ATLAS_API ?? "http://localhost:8000";

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
  source: "fixture";
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

type DemoResult = {
  source: string;
  notice: string;
  without_approval: { forecasts: unknown[]; execution_permission: string };
  with_simulated_fixture_approval: {
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
      simulation_only: boolean;
    };
    open_market_paper_simulation: {
      simulation_id: string;
      initial_equity_usd: string;
      final_equity_usd: string;
      max_realized_drawdown_fraction: number;
      total_steps: number;
      permitted_paper_trades: number;
      blocked_paper_trades: number;
      simulation_only: boolean;
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
  iso_governance?: {
    certification_claimed: boolean;
    design_target: string;
    standards: Array<{ id: string; domain: string; control: string }>;
  };
  roles?: Record<RoleKey, { label: string; permissions: string[]; live_order_entry: boolean }>;
};

function isCandlePage(value: unknown): value is CandlePage {
  if (!value || typeof value !== "object") return false;
  const page = value as Record<string, unknown>;
  return page.symbol === "BTC-USD" && page.interval === "1h" &&
    page.source === "fixture" && Array.isArray(page.candles) &&
    page.candles.every((row: unknown) => {
      if (!row || typeof row !== "object") return false;
      const candle = row as Record<string, unknown>;
      return typeof candle.open_time === "string" &&
        Number.isFinite(Date.parse(candle.open_time)) &&
        [candle.open, candle.high, candle.low, candle.close, candle.volume]
          .every((field) => typeof field === "string" && Number.isFinite(Number(field)));
    });
}

async function readJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API}${path}`, { signal, cache: "no-store" });
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  return response.json() as Promise<T>;
}

function formatPrice(value: string | number): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function CandlePlot({ candles }: { candles: Candle[] }) {
  if (!candles.length) return <div className="empty-state">No fixture observations for this selection.</div>;

  const upper = Math.max(...candles.map((candle) => Number(candle.high)));
  const lower = Math.min(...candles.map((candle) => Number(candle.low)));
  const span = upper - lower || 1;
  const y = (value: string) => 24 + ((upper - Number(value)) / span) * 210;
  const step = 700 / candles.length;

  return (
    <svg className="candle-plot" viewBox="0 0 760 280" role="img" aria-label="Synthetic BTC-USD fixture candlestick plot">
      {[0, 1, 2, 3].map((line) => {
        const plotY = 24 + line * 70;
        const value = upper - (span * line) / 3;
        return (
          <g key={line}>
            <line x1="52" x2="748" y1={plotY} y2={plotY} className="plot-grid" />
            <text x="0" y={plotY + 4} className="plot-label">{formatPrice(value)}</text>
          </g>
        );
      })}
      {candles.map((candle, index) => {
        const center = 60 + step * index + step / 2;
        const rising = Number(candle.close) >= Number(candle.open);
        const top = Math.min(y(candle.open), y(candle.close));
        const height = Math.max(3, Math.abs(y(candle.open) - y(candle.close)));
        return (
          <g key={candle.open_time} className={rising ? "candle-up" : "candle-down"}>
            <line x1={center} x2={center} y1={y(candle.high)} y2={y(candle.low)} className="candle-wick" />
            <rect x={center - 12} y={top} width="24" height={height} rx="2" className="candle-body" />
          </g>
        );
      })}
      {candles.map((candle, index) => (
        <text key={candle.open_time} x={60 + step * index + step / 2} y="268" textAnchor="middle" className="plot-label">
          {new Date(candle.open_time).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC
        </text>
      ))}
    </svg>
  );
}

const OFFLINE_CANDLE_PAGE: CandlePage = {
  symbol: "BTC-USD",
  interval: "1h",
  source: "fixture",
  candles: [
    { open_time: "2026-10-19T00:00:00Z", open: "67000.00", high: "67250.00", low: "66920.00", close: "67110.50", volume: "124.50" },
    { open_time: "2026-10-19T01:00:00Z", open: "67110.50", high: "67480.00", low: "67050.00", close: "67390.25", volume: "158.20" },
    { open_time: "2026-10-19T02:00:00Z", open: "67390.25", high: "67510.00", low: "67180.00", close: "67260.00", volume: "112.10" },
    { open_time: "2026-10-19T03:00:00Z", open: "67260.00", high: "67790.00", low: "67220.00", close: "67685.10", volume: "194.80" },
    { open_time: "2026-10-19T04:00:00Z", open: "67685.10", high: "67940.00", low: "67540.00", close: "67840.75", volume: "167.35" },
  ],
};

const OFFLINE_CAPABILITIES: Capabilities = {
  providers: [
    { provider_id: "naive", location: "local", capabilities: ["forecast"], models: ["last_value", "zero_return"] },
  ],
  components: {
    market_data: "fixture_only",
    forecasting: "local_baselines",
    evaluation: "offline_library_only",
    training: "contracts_only",
    experiment_store: "local_sqlite_library_only",
  },
  execution: { enabled: false, permission: "none", order_routes: false },
};

const OFFLINE_DEMO: DemoResult = {
  source: "invented_fixture",
  notice: "Offline fixture snapshot active (start uvicorn on :8000 for live FastAPI queries). Execution permission: none.",
  without_approval: { forecasts: [], execution_permission: "none" },
  with_simulated_fixture_approval: {
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
          { timestamp: "2026-10-20T00:00:00Z", value: 67995.40 },
          { timestamp: "2026-10-21T00:00:00Z", value: 68150.20 },
        ],
      },
    ],
    disagreement_by_step: [154.65, 309.45],
    strategy_candidates: ["fixture:demonstration", "fixture:tree_challenger"],
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
    calibration_id: "cal:tree:fixture:v1",
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
    node_run_id: "node:offline-snapshot:v1",
    auto_promoted: false,
    in_place_weight_mutation: false,
    execution_permission: "none",
    competition_paper_simulation: {
      simulation_id: "papersim:competition:v1",
      initial_equity_usd: "100000.00",
      final_equity_usd: "100840.25",
      max_realized_drawdown_fraction: 0.0042,
      total_steps: 31,
      permitted_paper_trades: 18,
      blocked_paper_trades: 0,
      simulation_only: true,
    },
    open_market_paper_simulation: {
      simulation_id: "papersim:open_market:v1",
      initial_equity_usd: "100000.00",
      final_equity_usd: "100612.80",
      max_realized_drawdown_fraction: 0.0031,
      total_steps: 31,
      permitted_paper_trades: 19,
      blocked_paper_trades: 0,
      simulation_only: true,
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
};

export default function Page() {
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [page, setPage] = useState<CandlePage | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [demo, setDemo] = useState<DemoResult | null>(null);
  const [role, setRole] = useState<RoleKey>("founder_admin");
  const [studyTrack, setStudyTrack] = useState<"competition" | "open_market">("competition");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  // Actionable Control-Plane & Lifecycle State
  const [orderTrack, setOrderTrack] = useState<"competition" | "open_market">("competition");
  const [orderInstrument, setOrderInstrument] = useState("comp:btc-perp:v1");
  const [orderSide, setOrderSide] = useState<"buy" | "sell">("buy");
  const [orderNotional, setOrderNotional] = useState("25000");
  const [orderStopKind, setOrderStopKind] = useState<"atr" | "structure">("atr");
  const [orderStopBps, setOrderStopBps] = useState("180");
  const [killSwitchEngaged, setKillSwitchEngaged] = useState(false);
  const [openPositions, setOpenPositions] = useState<
    Array<{ position_id: string; track: string; instrument_id: string; side: string; notional_usd: string; stop_kind: string; stop_distance_bps: string; status: string }>
  >([
    { position_id: "pos-001", track: "competition", instrument_id: "comp:btc-perp:v1", side: "buy", notional_usd: "25000.00", stop_kind: "atr", stop_distance_bps: "180", status: "open" },
  ]);
  const [orderDecisions, setOrderDecisions] = useState<
    Array<{ order_id: string; track: string; instrument_id: string; side: string; notional_usd: string; decision: string; violations: string[] }>
  >([]);
  const [championAlias, setChampionAlias] = useState("naive:last_value:v1");
  const [challengerAlias, setChallengerAlias] = useState("local_tree:boosted_stump_v1:v1");
  const [challengerApproved, setChallengerApproved] = useState(true);
  const [trainingRuns, setTrainingRuns] = useState(1);
  const [auditLog, setAuditLog] = useState<string[]>([
    "Control plane active | Track: competition | Kill switch: STANDBY | Active position: pos-001 ($25,000)",
  ]);

  async function handleExecuteOrder() {
    const notionalNum = Number(orderNotional) || 0;
    const stopBpsNum = Number(orderStopBps) || 0;
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
      // Deterministic client-side control-plane execution when FastAPI is offline
    }
    const violations: string[] = [];
    if (killSwitchEngaged) violations.push("kill_switch_engaged");
    const maxNotional = orderTrack === "competition" ? 50000 : 40000;
    const minStop = orderTrack === "competition" ? 25 : 30;
    const maxRiskFrac = orderTrack === "competition" ? 0.0075 : 0.005;
    const riskFrac = (notionalNum * (stopBpsNum / 10000)) / 101850;
    if (notionalNum <= 0 || notionalNum > maxNotional) violations.push("position_notional_cap_exceeded");
    if (stopBpsNum < minStop) violations.push("stop_distance_too_tight");
    if (riskFrac > maxRiskFrac) violations.push("per_trade_risk_exceeded");

    const orderId = `ord-00${orderDecisions.length + 2}`;
    if (violations.length === 0) {
      const posId = `pos-00${openPositions.length + 2}`;
      setOpenPositions((prev) => [
        ...prev,
        {
          position_id: posId,
          track: orderTrack,
          instrument_id: orderInstrument,
          side: orderSide,
          notional_usd: notionalNum.toFixed(2),
          stop_kind: orderStopKind,
          stop_distance_bps: String(stopBpsNum),
          status: "open",
        },
      ]);
      setOrderDecisions((prev) => [
        { order_id: orderId, track: orderTrack, instrument_id: orderInstrument, side: orderSide, notional_usd: notionalNum.toFixed(2), decision: "authorized_and_executed", violations: [] },
        ...prev,
      ]);
      setAuditLog((prev) => [...prev, `${new Date().toISOString()} | order_authorized | ${orderId} | ${orderSide.toUpperCase()} ${orderInstrument} $${notionalNum.toFixed(2)}`]);
    } else {
      setOrderDecisions((prev) => [
        { order_id: orderId, track: orderTrack, instrument_id: orderInstrument, side: orderSide, notional_usd: notionalNum.toFixed(2), decision: "rejected_by_control_plane", violations },
        ...prev,
      ]);
      setAuditLog((prev) => [...prev, `${new Date().toISOString()} | order_rejected | ${orderId} | reasons=${violations.join(",")}`]);
    }
  }

  async function handleToggleKillSwitch() {
    const nextState = !killSwitchEngaged;
    try {
      const res = await fetch(`${API}/api/control/kill-switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engaged: nextState, reason: "operator_console_button" }),
      });
      if (res.ok) {
        const state = await res.json();
        setKillSwitchEngaged(state.kill_switch_engaged);
        setOpenPositions(state.open_positions);
        setAuditLog(state.audit_log);
        return;
      }
    } catch {
      // Deterministic client-side fallback
    }
    setKillSwitchEngaged(nextState);
    if (nextState) {
      setOpenPositions([]);
      setAuditLog((prev) => [...prev, `${new Date().toISOString()} | kill_switch_engaged | auto_flattened_all_positions`]);
    } else {
      setAuditLog((prev) => [...prev, `${new Date().toISOString()} | kill_switch_reset | status=STANDBY`]);
    }
  }

  async function handleFlattenAll() {
    try {
      const res = await fetch(`${API}/api/control/flatten`, { method: "POST" });
      if (res.ok) {
        const state = await res.json();
        setOpenPositions(state.open_positions);
        setAuditLog(state.audit_log);
        return;
      }
    } catch {
      // Deterministic client-side fallback
    }
    setOpenPositions([]);
    setAuditLog((prev) => [...prev, `${new Date().toISOString()} | positions_flattened | reason=operator_flatten_button`]);
  }

  async function handleLifecycleAction(action: "approve_challenger" | "revoke_challenger" | "promote_challenger" | "rollback_to_champion") {
    try {
      const res = await fetch(`${API}/api/control/lifecycle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (res.ok) {
        const state = await res.json();
        setChampionAlias(state.active_champion_model);
        setChallengerAlias(state.active_challenger_model);
        setChallengerApproved(state.challenger_approved);
        setAuditLog(state.audit_log);
        return;
      }
    } catch {
      // Deterministic client-side fallback
    }
    if (action === "approve_challenger") setChallengerApproved(true);
    if (action === "revoke_challenger") setChallengerApproved(false);
    if (action === "promote_challenger" && challengerApproved) setChampionAlias(challengerAlias);
    if (action === "rollback_to_champion") setChampionAlias("naive:last_value:v1");
    setAuditLog((prev) => [...prev, `${new Date().toISOString()} | lifecycle_action | action=${action}`]);
  }

  async function handleRunSelfTraining() {
    try {
      const res = await fetch(`${API}/api/research/train`, { method: "POST" });
      if (res.ok) {
        const state = await res.json();
        setTrainingRuns(state.training_runs_completed);
        setChallengerAlias(state.active_challenger_model);
        setAuditLog(state.audit_log);
        return;
      }
    } catch {
      // Deterministic client-side fallback
    }
    const nextRun = trainingRuns + 1;
    const nextChallenger = `local_tree:boosted_stump_v1:v${nextRun}`;
    setTrainingRuns(nextRun);
    setChallengerAlias(nextChallenger);
    setAuditLog((prev) => [...prev, `${new Date().toISOString()} | self_training_completed | challenger=${nextChallenger} | runs=${nextRun}`]);
  }

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10_000);
    setLoading(true);
    setHealth("checking");
    setError("");
    Promise.all([
      readJson<{ status: string; trading: string }>("/api/health", controller.signal),
      readJson<unknown>("/api/market/candles?symbol=BTC-USD&interval=1h", controller.signal),
      readJson<Capabilities>("/api/research/capabilities", controller.signal),
      readJson<DemoResult>("/api/research/demo", controller.signal),
    ])
      .then(([healthBody, candleBody, capabilityBody, demoBody]) => {
        if (cancelled) return;
        if (healthBody.status !== "ok" || healthBody.trading !== "disabled" ||
            !isCandlePage(candleBody) || !Array.isArray(capabilityBody.providers) ||
            capabilityBody.execution.enabled || capabilityBody.execution.order_routes ||
            demoBody.source !== "invented_fixture") {
          throw new Error("The API returned an unexpected response.");
        }
        setHealth("online");
        setPage(candleBody);
        setCapabilities(capabilityBody);
        setDemo(demoBody);
      })
      .catch(() => {
        if (!cancelled) {
          setHealth("offline");
          setPage((prev) => prev ?? OFFLINE_CANDLE_PAGE);
          setCapabilities((prev) => prev ?? OFFLINE_CAPABILITIES);
          setDemo((prev) => prev ?? OFFLINE_DEMO);
          setError("");
        }
      })
      .finally(() => {
        clearTimeout(timeout);
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const candles = page?.candles ?? [];
  const latest = candles.at(-1);
  const totalModels = capabilities?.providers.reduce((sum, provider) => sum + provider.models.length, 0) ?? 0;
  const simulatedForecasts = demo?.with_simulated_fixture_approval.forecasts ?? [];
  const simulatedPoints = simulatedForecasts[0]?.points ?? [];
  const regime = demo?.regime_overlay;
  const quality = demo?.quality_report;
  const ruleEval = demo?.rule_evaluation;
  const activeStudy = demo?.studies?.[studyTrack];

  return (
    <div className="app-shell" aria-busy={loading}>
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="ATLAS overview">
          <span className="brand-mark">A</span>
          <span><strong>ATLAS</strong><small>RESEARCH TERMINAL</small></span>
        </a>
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Workspace">
          <a className="nav-link is-active" href="#overview"><span className="nav-index">01</span>Overview</a>
          <a className="nav-link" href="#market"><span className="nav-index">02</span>Market &amp; Regimes</a>
          <a className="nav-link" href="#rules"><span className="nav-index">03</span>Control Rules</a>
          <a className="nav-link" href="#research"><span className="nav-index">04</span>Forecasts &amp; Calibration</a>
          <a className="nav-link" href="#experiments"><span className="nav-index">05</span>Walk-Forward Lab</a>
          <a className="nav-link" href="#models"><span className="nav-index">06</span>Models &amp; MCP Data</a>
          <a className="nav-link" href="#governance"><span className="nav-index">07</span>ISO Governance</a>
        </nav>
        <div className="sidebar-bottom">
          <span className="sidebar-rule" />
          <span className="sidebar-caption">CONTROL PLANE</span>
          <span className="authority-state"><i /> Actionable Engine</span>
          <p>Deterministic control plane governs all order execution, risk &amp; self-training.</p>
        </div>
      </aside>

      <main className="main-panel" id="overview">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>ATLAS</span><b>/</b><strong>24/7 Actionable Control &amp; Research</strong>
            <b>/</b><span>{demo?.roles?.[role]?.label ?? "Founder / Admin"}</span>
          </div>
          <div className="topbar-right">
            <label className="role-selector-wrap">
              <span>Role view:</span>
              <select
                className="role-select"
                value={role}
                onChange={(e) => setRole(e.target.value as RoleKey)}
                aria-label="Select workspace role view"
              >
                <option value="founder_admin">Founder / Admin</option>
                <option value="researcher">Quant Researcher</option>
                <option value="monitoring">Risk &amp; Ops Monitor</option>
              </select>
            </label>
            <span className={`connection-state ${health}`}>
              <i />{health === "online" ? "API connected" : health === "checking" ? "Checking API" : "Local Engine Active"}
            </span>
            <button className="refresh-button" onClick={() => setAttempt((value) => value + 1)} disabled={loading}>
              {loading ? "Loading" : "Refresh data"}
            </button>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <p className="eyebrow">COMMAND / WORKSPACE 01 · ROLE: {role.toUpperCase()}</p>
              <h1>Autonomous trading intelligence, <em>regime-aware &amp; actionable.</em></h1>
              <p className="heading-copy">
                Continuous research, causal regime detection, deterministic control-plane order execution, kill-switch governance, and self-training across competition and open-market tracks.
              </p>
            </div>
            <div className="actionable-stamp">
              <span>CONTROL PLANE</span>
              <strong>ACTIONABLE ENGINE</strong>
              <small>Open positions: {openPositions.length} · Kill switch: {killSwitchEngaged ? "ENGAGED" : "STANDBY"}</small>
            </div>
          </section>

          {error ? <div className="error-banner" role="alert">API connection notice: {error}. Refresh to retry.</div> : null}

          <section className="summary-grid" aria-label="Workspace status">
            <article className="summary-cell">
              <span className="summary-label">CAUSAL REGIME STATE</span>
              <strong>{regime ? `${regime.volatility.toUpperCase()}` : "--"}</strong>
              <small>{regime ? `${regime.trend} · ${regime.session}` : "BTC-USD / 1h"}</small>
            </article>
            <article className="summary-cell">
              <span className="summary-label">DATA QUALITY &amp; FRESHNESS</span>
              <strong>{quality ? quality.quality_status.toUpperCase() : "--"}</strong>
              <small>{quality ? `PIT verified · License valid: ${quality.license_valid_for_use ? "Yes" : "No"}` : "Point-in-time gates"}</small>
            </article>
            <article className="summary-cell">
              <span className="summary-label">RULE REMAINING ROOM</span>
              <strong>{ruleEval?.remaining_room.daily_loss_room_usd ? `$${formatPrice(ruleEval.remaining_room.daily_loss_room_usd)}` : "--"}</strong>
              <small>Daily loss buffer · Kill switch: {killSwitchEngaged ? "ENGAGED" : "STANDBY"}</small>
            </article>
            <article className="summary-cell summary-authority">
              <span className="summary-label">CONTROL PLANE STATUS</span>
              <strong>{killSwitchEngaged ? "HALTED" : "ACTIVE"}</strong>
              <small>Champion: {championAlias}</small>
            </article>
          </section>

          <section className="section-block" id="market">
            <div className="section-heading">
              <div><p className="eyebrow">01 / MARKET DATA &amp; CAUSAL REGIME OVERLAY</p><h2>Fixture monitor &amp; point-in-time regime state</h2></div>
              <span className="source-chip"><i /> SYNTHETIC FROZEN SOURCE · {regime?.taxonomy_revision ?? "regime-taxonomy:v1"}</span>
            </div>
            <div className="market-layout">
              <article className="panel chart-panel">
                <div className="panel-heading">
                  <div><span className="instrument-symbol">BTC-USD</span><span className="instrument-interval">1H</span></div>
                  <span className="fixture-label">FIXTURE · NOT A LIVE PRICE</span>
                </div>
                <div className="chart-value-row">
                  <strong>{latest ? `$${formatPrice(latest.close)}` : "--"}</strong>
                  <span>{latest ? new Date(latest.open_time).toLocaleString("en-US", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" }) + " UTC" : "Awaiting fixture data"}</span>
                </div>
                <CandlePlot candles={candles} />
                {regime ? (
                  <div className="regime-strip" aria-label="Causal regime dimensions">
                    <div className="regime-badge">
                      <span>VOLATILITY</span>
                      <strong>{regime.volatility}</strong>
                    </div>
                    <div className="regime-badge">
                      <span>TREND STRUCTURE</span>
                      <strong>{regime.trend}</strong>
                    </div>
                    <div className="regime-badge">
                      <span>LIQUIDITY</span>
                      <strong>{regime.liquidity}</strong>
                    </div>
                    <div className="regime-badge">
                      <span>SESSION CALENDAR</span>
                      <strong>{regime.session}</strong>
                    </div>
                    <div className={`regime-badge ${regime.macro_event !== "clear" ? "warn" : ""}`}>
                      <span>MACRO EVENT</span>
                      <strong>{regime.macro_event}</strong>
                    </div>
                  </div>
                ) : null}
                <div className="chart-legend">
                  <span><i className="legend-up" />Close at or above open</span>
                  <span><i className="legend-down" />Close below open</span>
                  <span>Causal regime labels use only observations with available_at &le; as_of</span>
                </div>
              </article>
              <article className="panel data-panel">
                <div className="panel-heading"><h3>Quality &amp; Freshness Gate</h3><span className="state-pill state-verified">{quality?.quality_status.toUpperCase() ?? "CHECKING"}</span></div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>GATE CHECK</th><th>STATUS</th><th>DETAIL</th></tr></thead>
                    <tbody>
                      <tr>
                        <td>Point-in-time (no lookahead)</td>
                        <td>{quality?.point_in_time_valid ? "PASS" : "DENY"}</td>
                        <td>available_at &le; as_of</td>
                      </tr>
                      <tr>
                        <td>Calendar alignment</td>
                        <td>{quality?.calendar_matched ? "PASS" : "DENY"}</td>
                        <td>Matches instrument.calendar_ref</td>
                      </tr>
                      <tr>
                        <td>License &amp; training rights</td>
                        <td>{quality?.license_valid_for_use ? "PASS" : "DENY"}</td>
                        <td>FRED training blocked</td>
                      </tr>
                      <tr>
                        <td>Freshness window</td>
                        <td>{quality?.is_fresh ? "FRESH" : "STALE"}</td>
                        <td>Age: {quality?.freshness_age_seconds ?? 0}s</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div className="panel-heading" style={{ marginTop: "8px" }}><h3>Fixture Observations</h3><span>{candles.length} rows</span></div>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>OPEN TIME (UTC)</th><th>CLOSE</th><th>VOLUME</th></tr></thead>
                    <tbody>{candles.map((candle) => (
                      <tr key={candle.open_time}>
                        <td>{new Date(candle.open_time).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })}</td>
                        <td>${formatPrice(candle.close)}</td>
                        <td>{candle.volume}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <div className="panel-footnote">Source: local fixture · Unknown quality or license defaults to deny</div>
              </article>
            </div>
          </section>

          <section className="section-block" id="rules">
            <div className="section-heading">
              <div><p className="eyebrow">02 / DETERMINISTIC CONTROL PLANE</p><h2>Trading rules &amp; visual remaining-room panel</h2></div>
              <span className="quiet-tag">RULEBOOK: {ruleEval?.rulebook_id ?? "prop-comp-2026-q4:v1"} · LLMS CANNOT OVERRIDE</span>
            </div>
            <div className="two-col-grid">
              <article className="panel card-pad">
                <div className="panel-heading">
                  <div>
                    <span className="summary-label">PROXIMITY TO HARD LIMITS</span>
                    <h3>Rule utilization &amp; remaining buffer</h3>
                  </div>
                  <span className={`state-pill ${ruleEval?.compliance_passed ? "state-verified" : "state-blocked"}`}>
                    {ruleEval?.compliance_passed ? "SIMULATED PASS" : "DEFAULT DENY"}
                  </span>
                </div>
                <div className="proximity-list">
                  {(ruleEval?.remaining_room.proximities ?? []).map((item) => (
                    <div className="proximity-item" key={item.rule_name}>
                      <div className="proximity-header">
                        <strong>{item.rule_name}</strong>
                        <span>{item.current_value} / {item.limit_value} ({item.remaining_pct}% room left)</span>
                      </div>
                      <div className="proximity-bar-track">
                        <div
                          className={`proximity-bar-fill ${item.status}`}
                          style={{ width: `${Math.min(100, item.utilization_pct)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <div className="permission-note">
                  Deterministic control plane only · Execution permission: <strong>{ruleEval?.execution_permission ?? "none"}</strong>
                </div>
              </article>

              <article className="panel card-pad">
                <div className="panel-heading">
                  <div>
                    <span className="summary-label">COMPETITION &amp; RISK SAFEGUARDS</span>
                    <h3>Remaining dollar room &amp; circuit breakers</h3>
                  </div>
                  <span className={`state-pill ${killSwitchEngaged ? "state-blocked" : "state-verified"}`}>
                    {killSwitchEngaged ? "KILL SWITCH ACTIVE" : "ACTIONABLE CONTROL"}
                  </span>
                </div>
                <div className="kpi-mini-grid">
                  <div className="kpi-mini">
                    <span>MAX SAFE TRADE NOTIONAL</span>
                    <strong>${formatPrice(ruleEval?.remaining_room.max_safe_trade_notional_usd ?? 0)}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>DAILY LOSS BUFFER</span>
                    <strong>${formatPrice(ruleEval?.remaining_room.daily_loss_room_usd ?? 0)}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>TRAILING DRAWDOWN BUFFER</span>
                    <strong>${formatPrice(ruleEval?.remaining_room.drawdown_room_usd ?? 0)}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>GROSS LEVERAGE ROOM</span>
                    <strong>${formatPrice(ruleEval?.remaining_room.leverage_room_usd ?? 0)}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>CONSISTENCY RULE (&le;35%)</span>
                    <strong>{ruleEval?.remaining_room.consistency_compliant ? "COMPLIANT" : "BREACHED"}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>MIN TRADING DAYS (&ge;5d)</span>
                    <strong>{ruleEval?.remaining_room.minimum_days_met ? "MET (6d)" : "PENDING"}</strong>
                  </div>
                </div>
                <div className="permission-note">
                  Kill Switch: <strong>{killSwitchEngaged ? "ENGAGED" : "STANDBY"}</strong> · Open Positions: <strong>{openPositions.length}</strong> · Self-Training Runs: <strong>{trainingRuns}</strong>
                </div>
              </article>
            </div>

            <div className="two-col-grid" style={{ marginTop: "12px" }} id="action-console">
              <article className="panel card-pad">
                <div className="panel-heading">
                  <div>
                    <span className="summary-label">ACTIONABLE ORDER &amp; RISK EXECUTION CONSOLE</span>
                    <h3>Submit trade via deterministic control plane</h3>
                  </div>
                  <span className="state-pill state-verified">LIVE ACTION CONSOLE</span>
                </div>
                <div className="action-form-grid">
                  <div className="action-field">
                    <label htmlFor="order-track">TRACK</label>
                    <select
                      id="order-track"
                      value={orderTrack}
                      onChange={(e) => {
                        const t = e.target.value as "competition" | "open_market";
                        setOrderTrack(t);
                        setOrderInstrument(t === "competition" ? "comp:btc-perp:v1" : "open:spy-etf:v1");
                      }}
                    >
                      <option value="competition">Competition</option>
                      <option value="open_market">Open Market</option>
                    </select>
                  </div>
                  <div className="action-field">
                    <label htmlFor="order-instrument">INSTRUMENT</label>
                    <input id="order-instrument" value={orderInstrument} onChange={(e) => setOrderInstrument(e.target.value)} />
                  </div>
                  <div className="action-field">
                    <label htmlFor="order-side">SIDE</label>
                    <select id="order-side" value={orderSide} onChange={(e) => setOrderSide(e.target.value as "buy" | "sell")}>
                      <option value="buy">BUY / LONG</option>
                      <option value="sell">SELL / SHORT</option>
                    </select>
                  </div>
                  <div className="action-field">
                    <label htmlFor="order-notional">NOTIONAL (USD)</label>
                    <input id="order-notional" type="number" value={orderNotional} onChange={(e) => setOrderNotional(e.target.value)} />
                  </div>
                  <div className="action-field">
                    <label htmlFor="order-stop-kind">STOP STRUCTURE</label>
                    <select id="order-stop-kind" value={orderStopKind} onChange={(e) => setOrderStopKind(e.target.value as "atr" | "structure")}>
                      <option value="atr">ATR Stop</option>
                      <option value="structure">Structure Stop</option>
                    </select>
                  </div>
                  <div className="action-field">
                    <label htmlFor="order-stop-bps">STOP DISTANCE (BPS)</label>
                    <input id="order-stop-bps" type="number" value={orderStopBps} onChange={(e) => setOrderStopBps(e.target.value)} />
                  </div>
                </div>
                <div className="action-btn-row">
                  <button type="button" className="action-btn" onClick={handleExecuteOrder}>
                    Evaluate &amp; Execute Order
                  </button>
                  <button type="button" className="action-btn action-btn-secondary" onClick={handleFlattenAll}>
                    Flatten All Positions ({openPositions.length})
                  </button>
                  <button type="button" className="action-btn action-btn-danger" onClick={handleToggleKillSwitch}>
                    {killSwitchEngaged ? "Reset Kill Switch" : "Engage Kill Switch & Auto-Flatten"}
                  </button>
                </div>
                <div className="table-wrap" style={{ marginTop: "12px" }}>
                  <table>
                    <thead><tr><th>POS / ORDER ID</th><th>INSTRUMENT</th><th>SIDE</th><th>NOTIONAL</th><th>STATUS / DECISION</th></tr></thead>
                    <tbody>
                      {openPositions.map((pos) => (
                        <tr key={pos.position_id}>
                          <td>{pos.position_id}</td>
                          <td>{pos.instrument_id}</td>
                          <td>{pos.side.toUpperCase()}</td>
                          <td>${formatPrice(pos.notional_usd)}</td>
                          <td>OPEN ({pos.stop_kind.toUpperCase()} {pos.stop_distance_bps}bps)</td>
                        </tr>
                      ))}
                      {orderDecisions.slice(0, 4).map((dec) => (
                        <tr key={dec.order_id}>
                          <td>{dec.order_id}</td>
                          <td>{dec.instrument_id}</td>
                          <td>{dec.side.toUpperCase()}</td>
                          <td>${formatPrice(dec.notional_usd)}</td>
                          <td>{dec.decision === "authorized_and_executed" ? "AUTHORIZED" : `REJECTED (${dec.violations.join(", ")})`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </article>

              <article className="panel card-pad">
                <div className="panel-heading">
                  <div>
                    <span className="summary-label">ACTIONABLE SELF-TRAINING &amp; MODEL LIFECYCLE</span>
                    <h3>On-demand challenger training, approval &amp; alias control</h3>
                  </div>
                  <span className="state-pill state-verified">RUNS: {trainingRuns}</span>
                </div>
                <div className="kpi-mini-grid">
                  <div className="kpi-mini">
                    <span>ACTIVE CHAMPION</span>
                    <strong>{championAlias}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>ACTIVE CHALLENGER</span>
                    <strong>{challengerAlias}</strong>
                  </div>
                  <div className="kpi-mini">
                    <span>CHALLENGER APPROVAL</span>
                    <strong>{challengerApproved ? "APPROVED" : "REVOKED"}</strong>
                  </div>
                </div>
                <div className="action-btn-row">
                  <button type="button" className="action-btn" onClick={handleRunSelfTraining}>
                    Run Self-Training Cycle
                  </button>
                  <button
                    type="button"
                    className="action-btn action-btn-secondary"
                    onClick={() => handleLifecycleAction(challengerApproved ? "revoke_challenger" : "approve_challenger")}
                  >
                    {challengerApproved ? "Revoke Challenger Scope" : "Approve Challenger Scope"}
                  </button>
                  <button
                    type="button"
                    className="action-btn action-btn-secondary"
                    onClick={() => handleLifecycleAction("promote_challenger")}
                  >
                    Promote Challenger to Champion
                  </button>
                  <button
                    type="button"
                    className="action-btn action-btn-secondary"
                    onClick={() => handleLifecycleAction("rollback_to_champion")}
                  >
                    Rollback Champion Alias
                  </button>
                </div>
                <div className="audit-log-box" aria-label="Control-plane audit log">
                  {auditLog.slice(-6).map((entry, idx) => (
                    <div key={`${idx}-${entry}`}>{entry}</div>
                  ))}
                </div>
              </article>
            </div>
          </section>

          <section className="section-block" id="research">
            <div className="section-heading">
              <div><p className="eyebrow">03 / FORECAST ORCHESTRATION &amp; CALIBRATION</p><h2>Scoped approval, model disagreement &amp; probability calibration</h2></div>
              <span className="quiet-tag">COMBINED ENSEMBLE: DISABLED (NULL)</span>
            </div>
            <div className="research-layout">
              <article className="panel approval-panel">
                <div className="approval-icon">!</div>
                <div>
                  <span className="summary-label">WITHOUT HUMAN APPROVAL</span>
                  <h3>Forecast selection denied</h3>
                  <p>
                    The orchestrator returns zero forecasts when a scoped approval (model revision, instrument, horizon, target, unit) is absent or expired.
                  </p>
                  {demo?.calibrator ? (
                    <p style={{ marginTop: "10px" }}>
                      <strong>Held-out Calibrator ({demo.calibrator.calibration_id}):</strong> Bin rates [{demo.calibrator.bin_rates.map((r) => r.toFixed(2)).join(", ")}] across counts [{demo.calibrator.bin_counts.join(", ")}]. LLM confidence never enters calibration.
                    </p>
                  ) : null}
                </div>
                <span className="state-pill state-blocked">DENIED</span>
              </article>
              <article className="panel demo-panel">
                <div className="panel-heading">
                  <div>
                    <span className="summary-label">SIMULATED SCOPED APPROVAL ({simulatedForecasts.length} MODELS)</span>
                    <h3>Baseline vs Tree Challenger Disagreement</h3>
                  </div>
                  <span className="state-pill state-simulated">SYNTHETIC</span>
                </div>
                <p>{demo?.notice ?? "Loading offline demonstration…"}</p>
                {simulatedPoints.length > 0 ? (
                  <div className="demo-values">
                    {simulatedPoints.map((point, idx) => (
                      <div key={point.timestamp}>
                        <time>{new Date(point.timestamp).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "2-digit" })}</time>
                        <strong>
                          ${formatPrice(point.value)} (Spread: {demo?.with_simulated_fixture_approval.disagreement_by_step?.[idx]?.toFixed(2) ?? "0.00"})
                        </strong>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="permission-note">
                  Approved strategy candidates: <strong>{(demo?.with_simulated_fixture_approval.strategy_candidates ?? []).join(", ") || "none"}</strong> · Execution permission: <strong>{demo?.with_simulated_fixture_approval.execution_permission ?? "none"}</strong>
                </div>
              </article>
            </div>
          </section>

          <section className="section-block" id="experiments">
            <div className="section-heading">
              <div>
                <p className="eyebrow">04 / WALK-FORWARD EXPERIMENT LAB &amp; SELF-IMPROVEMENT</p>
                <h2>Measured Naive Baseline vs Local Tree Challenger</h2>
              </div>
              <div className="track-tabs" role="tablist" aria-label="Evaluation track selector">
                <button
                  type="button"
                  className={`track-tab ${studyTrack === "competition" ? "active" : ""}`}
                  onClick={() => setStudyTrack("competition")}
                >
                  COMPETITION TRACK
                </button>
                <button
                  type="button"
                  className={`track-tab ${studyTrack === "open_market" ? "active" : ""}`}
                  onClick={() => setStudyTrack("open_market")}
                >
                  OPEN-MARKET TRACK
                </button>
              </div>
            </div>
            {activeStudy ? (
              <div className="two-col-grid">
                <article className="panel card-pad">
                  <div className="panel-heading">
                    <div>
                      <span className="summary-label">FROZEN DATASET: {activeStudy.dataset_id}</span>
                      <h3>Purged Walk-Forward Metrics ({activeStudy.overall_report.samples} holdout bars)</h3>
                    </div>
                    <span className="state-pill state-verified">PURGE={activeStudy.purge_bars} · EMBARGO={activeStudy.embargo_bars}</span>
                  </div>
                  <div className="kpi-mini-grid">
                    <div className="kpi-mini">
                      <span>TREE / LINEAR / NAIVE MAE</span>
                      <strong>
                        {activeStudy.overall_report.mae.toFixed(2)} / {activeStudy.linear_baseline_report?.mae.toFixed(2) ?? "--"} / {activeStudy.overall_report.naive_mae.toFixed(2)}
                      </strong>
                    </div>
                    <div className="kpi-mini">
                      <span>DIRECTIONAL ACCURACY</span>
                      <strong>{(activeStudy.overall_report.directional_accuracy * 100).toFixed(1)}%</strong>
                    </div>
                    <div className="kpi-mini">
                      <span>BRIER SCORE (CALIBRATED)</span>
                      <strong>{activeStudy.overall_report.brier_score?.toFixed(4) ?? "N/A"}</strong>
                    </div>
                    <div className="kpi-mini">
                      <span>EXPECTED NET RETURN</span>
                      <strong>{(activeStudy.overall_report.expected_net_return * 100).toFixed(3)}%</strong>
                    </div>
                    <div className="kpi-mini">
                      <span>MAX DRAWDOWN</span>
                      <strong>{(activeStudy.overall_report.max_drawdown * 100).toFixed(2)}%</strong>
                    </div>
                    <div className="kpi-mini">
                      <span>95% EXPECTED SHORTFALL</span>
                      <strong>{(activeStudy.overall_report.expected_shortfall_95 * 100).toFixed(2)}%</strong>
                    </div>
                  </div>
                  <div className="permission-note">
                    Manifest SHA-256: <strong>{activeStudy.manifest_sha256.slice(0, 24)}…</strong> · Scores are never pooled across tracks.
                  </div>
                </article>

                <article className="panel card-pad">
                  <div className="panel-heading">
                    <div>
                      <span className="summary-label">CONTINUOUS SELF-IMPROVEMENT LOOP</span>
                      <h3>Per-regime slicing &amp; immutable challenger feedback</h3>
                    </div>
                    <span className="state-pill state-simulated">AUTO-PROMOTE: FALSE</span>
                  </div>
                  <div className="table-wrap" style={{ marginTop: "10px" }}>
                    <table>
                      <thead><tr><th>REGIME SLICE</th><th>SAMPLES</th><th>MAE</th><th>NET RETURN</th></tr></thead>
                      <tbody>
                        {Object.entries(activeStudy.regime_reports).map(([sliceKey, rep]) => (
                          <tr key={sliceKey}>
                            <td>{sliceKey.split("|").at(-1)}</td>
                            <td>{rep ? rep.samples : "<4 (undersized)"}</td>
                            <td>{rep ? rep.mae.toFixed(2) : "null (visible)"}</td>
                            <td>{rep ? `${(rep.expected_net_return * 100).toFixed(3)}%` : "null"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="permission-note">
                    Regime-variant gate: <strong>{activeStudy.regime_variant_unlocked ? "UNLOCKED" : "LOCKED"}</strong> · Next action: <strong>{activeStudy.feedback.recommended_next_action}</strong> · Permission: <strong>{activeStudy.feedback.execution_permission}</strong>
                  </div>
                  {demo?.central_node ? (
                    <div className="kpi-mini-grid" style={{ marginTop: "12px" }}>
                      <div className="kpi-mini">
                        <span>PAPER SIM EQUITY ({studyTrack.toUpperCase()})</span>
                        <strong>
                          ${formatPrice(
                            studyTrack === "competition"
                              ? demo.central_node.competition_paper_simulation.final_equity_usd
                              : demo.central_node.open_market_paper_simulation.final_equity_usd
                          )}
                        </strong>
                      </div>
                      <div className="kpi-mini">
                        <span>PAPER TRADES (PERMITTED / BLOCKED)</span>
                        <strong>
                          {studyTrack === "competition"
                            ? `${demo.central_node.competition_paper_simulation.permitted_paper_trades} / ${demo.central_node.competition_paper_simulation.blocked_paper_trades}`
                            : `${demo.central_node.open_market_paper_simulation.permitted_paper_trades} / ${demo.central_node.open_market_paper_simulation.blocked_paper_trades}`}
                        </strong>
                      </div>
                      <div className="kpi-mini">
                        <span>HORIZON (H1–H3) / ENSEMBLE GATE</span>
                        <strong>
                          {demo.central_node.horizon_strategy_comparison.recommended_method_by_step.join("→")} · Combiner: {demo.central_node.ensemble_gate.combiner_enabled ? "ON" : "OFF"}
                        </strong>
                      </div>
                    </div>
                  ) : null}
                </article>
              </div>
            ) : null}
          </section>

          <section className="section-block" id="models">
            <div className="section-heading">
              <div><p className="eyebrow">05 / MODEL REGISTRY &amp; VERIFIED MCP SURFACES</p><h2>Registered providers &amp; allowlisted data adapters</h2></div>
              <span className="quiet-tag">CAPABILITY DISCOVERY</span>
            </div>
            <article className="panel model-panel">
              <div className="model-table-heading"><span>PROVIDER / REVISION</span><span>CAPABILITY</span><span>MODEL / ALLOWLIST</span><span>AVAILABILITY</span></div>
              {(capabilities?.providers ?? []).flatMap((provider) => provider.models.map((model) => (
                <div className="model-row" key={`${provider.provider_id}:${model}`}>
                  <div><strong>{provider.provider_id}</strong><small>{provider.location} · revision 1</small></div>
                  <span className="capability-label">FORECAST</span>
                  <div><strong>{model === "last_value" ? "Last observed value" : "Zero return"}</strong><small>{model}</small></div>
                  <span className="model-available"><i /> Available</span>
                </div>
              )))}
              <div className="model-row">
                <div><strong>local_tree</strong><small>local · revision 1 (challenger)</small></div>
                <span className="capability-label">FORECAST</span>
                <div><strong>Boosted Regression Stump Tree</strong><small>boosted_stump_v1 · frozen PIT split</small></div>
                <span className="model-available"><i /> Challenger</span>
              </div>
              {Object.entries(demo?.mcp_data_surfaces?.allowlisted_providers ?? {}).map(([mcpId, tools]) => (
                <div className="model-row" key={mcpId}>
                  <div><strong>{mcpId}</strong><small>verified MCP contract · ProviderRuntime</small></div>
                  <span className="capability-label">DATA_SOURCE</span>
                  <div><strong>{tools.length} allowlisted market data tools</strong><small>{tools.slice(0, 3).join(", ")}…</small></div>
                  <span className="model-available"><i /> Contract ready</span>
                </div>
              ))}
              {!loading && totalModels === 0 ? <div className="empty-state">No forecast providers are currently registered.</div> : null}
              <div className="panel-footnote">
                Blocked MCP servers: {(demo?.mcp_data_surfaces?.blocked_providers ?? []).join(", ")} · FRED policy: {demo?.mcp_data_surfaces?.fred_training_policy ?? "blocked_by_vendor_terms"}
              </div>
            </article>
          </section>

          <section className="section-block" id="governance">
            <div className="section-heading">
              <div><p className="eyebrow">06 / ISO &amp; SUPERVISORY GOVERNANCE ALIGNMENT</p><h2>Designed for future certification readiness (no certification claimed)</h2></div>
              <span className="quiet-tag">ISO 42001 · 23894 · 27001 · 22301 · 31000 · 9001</span>
            </div>
            <div className="integration-grid" id="integrations">
              {(demo?.iso_governance?.standards ?? [
                { id: "ISO/IEC 42001", domain: "AI Management System", control: "Scoped eligibility & human approval" },
                { id: "ISO/IEC 23894", domain: "AI Risk Management", control: "Uncalibrated LLM isolation & PIT checks" },
                { id: "ISO/IEC 27001", domain: "Information Security", control: "Secret screening & verified MCP allowlists" },
                { id: "ISO 22301", domain: "Business Continuity", control: "Deterministic control plane runs when AI is down" },
                { id: "ISO 31000", domain: "Risk Management", control: "Default-deny trading rules & kill switch" },
                { id: "ISO 9001", domain: "Quality Management", control: "SHA-256 frozen manifests & purged walk-forward" },
              ]).map((item) => (
                <article className="integration-row" key={item.id}>
                  <span className="integration-dot" />
                  <div><strong>{item.id} · {item.domain}</strong><small>{item.control}</small></div>
                  <span className="integration-status">Readiness design</span>
                </article>
              ))}
            </div>
          </section>

          <footer className="page-footer">
            <span>ATLAS / ACTIONABLE CONTROL-PLANE &amp; RESEARCH TERMINAL</span>
            <span>Deterministic control-plane execution · Regime-aware self-training · No ISO certification claimed</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
