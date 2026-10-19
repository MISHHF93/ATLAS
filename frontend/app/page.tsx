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
  overall_report: EvaluationReport;
  regime_reports: Record<string, EvaluationReport | null>;
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
      .catch((reason: unknown) => {
        if (!cancelled) {
          setHealth("offline");
          setError(reason instanceof Error ? reason.message : "Cannot verify the API connection.");
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
          <span className="authority-state"><i /> Research only</span>
          <p>Model output cannot authorize or submit orders. Permission: none.</p>
        </div>
      </aside>

      <main className="main-panel" id="overview">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>ATLAS</span><b>/</b><strong>24/7 Regime-Aware Research</strong>
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
              <i />{health === "online" ? "API connected" : health === "checking" ? "Checking API" : "API offline"}
            </span>
            <button className="refresh-button" onClick={() => setAttempt((value) => value + 1)} disabled={loading}>
              {loading ? "Loading" : "Refresh data"}
            </button>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <p className="eyebrow">RESEARCH / WORKSPACE 01 · ROLE: {role.toUpperCase()}</p>
              <h1>Market research, <em>regime-aware &amp; deterministic.</em></h1>
              <p className="heading-copy">
                Continuous research, causal regime detection, deterministic rule remaining-room, and walk-forward evaluation across competition and open-market tracks.
              </p>
            </div>
            <div className="read-only-stamp">
              <span>EXECUTION GATE</span>
              <strong>PERMISSION: NONE</strong>
              <small>Live order entry disabled</small>
            </div>
          </section>

          {error ? <div className="error-banner" role="alert">API connection failed: {error}. Refresh to retry.</div> : null}

          <section className="summary-grid" aria-label="Workspace status">
            <article className="summary-cell">
              <span className="summary-label">CAUSAL REGIME STATE</span>
              <strong>{regime ? `${regime.volatility.toUpperCase()}` : "--"}</strong>
              <small>{regime ? `${regime.trend} · ${regime.session}` : "BTC-USD / 1h · invented data"}</small>
            </article>
            <article className="summary-cell">
              <span className="summary-label">DATA QUALITY &amp; FRESHNESS</span>
              <strong>{quality ? quality.quality_status.toUpperCase() : "--"}</strong>
              <small>{quality ? `PIT verified · License valid: ${quality.license_valid_for_use ? "Yes" : "No"}` : "Point-in-time gates"}</small>
            </article>
            <article className="summary-cell">
              <span className="summary-label">RULE REMAINING ROOM</span>
              <strong>{ruleEval?.remaining_room.daily_loss_room_usd ? `$${formatPrice(ruleEval.remaining_room.daily_loss_room_usd)}` : "--"}</strong>
              <small>Daily loss buffer · Kill switch: {ruleEval?.kill_switch_active ? "ACTIVE" : "OFF"}</small>
            </article>
            <article className="summary-cell summary-authority">
              <span className="summary-label">EXECUTION AUTHORITY</span>
              <strong>NONE</strong>
              <small>Deterministic control plane only</small>
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
                  <span className="state-pill state-simulated">READ ONLY</span>
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
                  Kill Switch: <strong>{ruleEval?.kill_switch_active ? "ENGAGED" : "STANDBY"}</strong> · Auto-Flatten: <strong>{ruleEval?.auto_flatten_required ? "REQUIRED" : "NOT TRIGGERED"}</strong> · Unknown policy fields default-deny.
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
                      <span>CHALLENGER MAE / NAIVE MAE</span>
                      <strong>{activeStudy.overall_report.mae.toFixed(2)} / {activeStudy.overall_report.naive_mae.toFixed(2)}</strong>
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
                    Next action: <strong>{activeStudy.feedback.recommended_next_action}</strong> · Execution permission: <strong>{activeStudy.feedback.execution_permission}</strong>
                  </div>
                </article>
              </div>
            ) : null}
          </section>

          <section className="section-block" id="models">
            <div className="section-heading">
              <div><p className="eyebrow">05 / MODEL REGISTRY &amp; READ-ONLY MCP SURFACES</p><h2>Registered providers &amp; allowlisted data adapters</h2></div>
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
                  <div><strong>{mcpId}</strong><small>read-only MCP contract · ProviderRuntime</small></div>
                  <span className="capability-label">DATA_SOURCE</span>
                  <div><strong>{tools.length} allowlisted read-only tools</strong><small>{tools.slice(0, 3).join(", ")}…</small></div>
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
                { id: "ISO/IEC 27001", domain: "Information Security", control: "Secret screening & read-only MCP allowlists" },
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
            <span>ATLAS / REGIME-AWARE RESEARCH TERMINAL</span>
            <span>Invented fixture data · No live trading connection · Execution permission: none · No ISO certification claimed</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
