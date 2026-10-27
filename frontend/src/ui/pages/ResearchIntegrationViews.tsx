"use client";
/** Section 22 Frontend Workbenches:
 *  1. StrategyAndPineResearchBench (Strategy Discovery, 19-Strategy Knowledge Base, Pine v5/v6 Static Analyzer, StrategyIR, Python Parity & Realistic Walk-Forward Backtest)
 *  2. BrokerIntelligenceBench (Provider-Neutral Broker MCP Registry, Capability Separation & Broker-Reported vs ATLAS-Calculated Reconciliation)
 *  3. DynamicPositionSizingBench (Fixed-Fractional, ATR-Based, Quarter-Kelly & 10-Constraint Control-Plane Cascade)
 *  4. AiResearchMemoryAndHandoffBench (Immutable Content-Hashed Research Memory, Source-Aware Explainer & Cross-Session AI Handoffs)
 */
import { useState } from "react";
import { ActionButton, ActionResult, Async, Badge, Card, DataTable, EmptyState, StatTile, useAction, useApi } from "../primitives";

type R = Record<string, unknown>;
const f = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : v === null || v === undefined ? "—" : String(v));

/* ---------- 1. Strategy Discovery, Pine Research & Realistic Backtest ---------- */
export function StrategyAndPineResearchBench() {
  const kb = useApi<{ count: number; lifecycle_stages: string[]; strategies: R[] }>("/api/research-integration/strategies", 60000);
  const [sid, setSid] = useState("sfp");
  const [sym, setSym] = useState("GC");
  const [tf, setTf] = useState("15m");
  const parity = useApi<R>(`/api/research-integration/pine/parity/${sid}?symbol=${sym}&timeframe=${tf}`, 60000);
  const explain = useApi<R>(`/api/research-integration/strategies/${sid}/explain?symbol=${sym}&timeframe=${tf}`, 60000);
  const btAction = useAction<R>("/api/research-integration/backtest");
  const wfAction = useAction<R>("/api/research-integration/workflow-run");

  const [pineCode, setPineCode] = useState(
    `//@version=5\nstrategy("ATLAS Custom ORB", overlay=true, default_qty_type=strategy.fixed, default_qty_value=1)\nlen = input.int(20, "Length")\nrr = input.float(2.0, "Reward:Risk")\nbasis = ta.sma(close, len)\nsd = ta.stdev(close, len)\nlongSig = ta.crossover(close, basis + 2.0 * sd)\nif longSig and strategy.position_size == 0\n    strategy.entry("L", strategy.long)\n    strategy.exit("Lx", "L", stop=basis, limit=close + rr * (close - basis))`
  );
  const [lic, setLic] = useState("MIT");
  const pineAnalyze = useAction<R>("/api/research-integration/pine/analyze");

  return (
    <div className="ux-layout">
      <Card
        title="Strategy discovery & knowledge base (19 canonical & open-source strategies)"
        span="full"
        subtitle="Governed strategy registry with SHA-256 source provenance, license validation, repainting/lookahead screening, and 8-stage lifecycle tracking. Live TradingView scraping is disabled by policy."
      >
        <Async state={kb} label="Loading strategy knowledge base">
          {(d) => (
            <DataTable
              caption="Strategy Knowledge Base"
              rows={d.strategies}
              maxHeight={340}
              columns={[
                { key: "strategy_id", label: "ID" },
                { key: "strategy_name", label: "Strategy" },
                { key: "strategy_family", label: "Family" },
                { key: "origin_kind", label: "Origin" },
                { key: "evidence_classification", label: "Evidence", render: (r) => <Badge tone="info">{String(r.evidence_classification ?? "")}</Badge> },
                { key: "source_license", label: "License" },
                { key: "repainting_risk", label: "Repaint", render: (r) => <Badge tone={r.repainting_risk === "LOW" ? "good" : "bad"}>{String(r.repainting_risk)}</Badge> },
                { key: "lookahead_risk", label: "Lookahead", render: (r) => <Badge tone={r.lookahead_risk === "LOW" ? "good" : "bad"}>{String(r.lookahead_risk)}</Badge> },
                { key: "lifecycle_stage", label: "Stage", render: (r) => <Badge tone={r.lifecycle_stage === "RESEARCH_REJECTED" ? "bad" : "good"}>{String(r.lifecycle_stage)}</Badge> },
              ]}
            />
          )}
        </Async>
      </Card>

      <Card
        title="Pine v5/v6 static analyzer & Canonical StrategyIR compiler"
        span={2}
        subtitle="Validates Pine syntax, extracts indicator dependencies and entry/exit/stop rules, detects unshifted lookahead_on or repainting constructs, and compiles to language-neutral StrategyIR."
      >
        <div className="ux-form-grid">
          <label className="ux-form-row">
            License{" "}
            <select value={lic} onChange={(e) => setLic(e.target.value)} aria-label="Source license">
              {["MIT", "APACHE-2.0", "BSD-3-CLAUSE", "ATLAS-INTERNAL", "PROPRIETARY_UNAPPROVED"].map((x) => (
                <option key={x} value={x}>{x}</option>
              ))}
            </select>
          </label>
          <ActionButton
            action={pineAnalyze}
            body={{ source_code: pineCode, strategy_id: "custom_pine_check", source_license: lic, timeframe: tf }}
            tone="primary"
          >
            Validate Pine &amp; Compile IR
          </ActionButton>
        </div>
        <textarea
          aria-label="Pine Script source code"
          value={pineCode}
          onChange={(e) => setPineCode(e.target.value)}
          rows={6}
          style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 12, background: "var(--c-surface-3)", color: "var(--c-text)", border: "1px solid var(--c-border)", borderRadius: 6, padding: 8, marginBottom: 8 }}
        />
        <ActionResult action={pineAnalyze} />
        {pineAnalyze.result ? (
          <div>
            <p>
              Status: <Badge tone={pineAnalyze.result.valid ? "good" : "bad"}>{String(pineAnalyze.result.status)}</Badge>
              {" · "}Pine v{String(pineAnalyze.result.pine_version ?? "—")}
              {" · "}Repainting: <strong>{String(pineAnalyze.result.repainting_risk)}</strong>
              {" · "}Lookahead: <strong>{String(pineAnalyze.result.lookahead_risk)}</strong>
              {" · "}Hash: <code>{String(pineAnalyze.result.source_hash ?? "").slice(0, 12)}</code>
            </p>
            <pre className="ux-pre">{JSON.stringify(pineAnalyze.result.canonical_ir, null, 2)}</pre>
          </div>
        ) : null}
      </Card>

      <Card
        title="Pine-to-Python parity & realistic walk-forward backtest"
        subtitle="Verifies 1-to-1 signal equivalence between Pine IR and Python detectors, then runs purged walk-forward OOS replay."
      >
        <div className="ux-form-grid">
          <label className="ux-form-row">
            Strategy{" "}
            <select value={sid} onChange={(e) => setSid(e.target.value)} aria-label="Parity strategy">
              {["sfp", "orb_retest", "dual_band_breakout", "wick_reversal", "prior_day_range_reversal"].map((x) => (
                <option key={x} value={x}>{x}</option>
              ))}
            </select>
          </label>
          <label className="ux-form-row">
            Symbol{" "}
            <select value={sym} onChange={(e) => setSym(e.target.value)} aria-label="Parity symbol">
              {["GC", "SPY", "BTCUSDT", "ES"].map((x) => (
                <option key={x} value={x}>{x}</option>
              ))}
            </select>
          </label>
          <ActionButton action={btAction} body={{ strategy_id: sid, symbol: sym, timeframe: tf, cost_multiplier: 1.0, purge_bars: 4, embargo_bars: 4 }} tone="primary">
            Run Realistic Backtest
          </ActionButton>
          <ActionButton action={wfAction} body={{ strategy_id: sid, symbol: sym, timeframe: tf, track: "competition", risk_fraction: 0.005 }}>
            Run Full 13-Stage Workflow
          </ActionButton>
        </div>
        <Async state={parity} label="Checking Pine-to-Python parity">
          {(p) => (
            <p>
              Parity: <Badge tone={p.parity_passed ? "good" : "warn"}>{String(p.status)}</Badge>
              {" · "}Match rate: <strong>{f(Number(p.match_rate ?? 0) * 100, 1)}%</strong>
              {" · "}Signals: {String(p.python_signal_count ?? 0)} Python / {String(p.pine_ir_signal_count ?? 0)} Pine
              {" · "}Golden hash: <code>{String(p.golden_dataset_hash ?? "—")}</code>
            </p>
          )}
        </Async>
        <Async state={explain} label="Checking source-aware recommendation">
          {(ex) => (
            <p className="ux-muted">
              {String(ex.origin_explanation ?? "")} · {String(ex.legal_license_status ?? "")} · Paper approved: <strong>{String(ex.approved_for_paper_trading)}</strong>
            </p>
          )}
        </Async>
        {btAction.result ? (
          <p>
            Backtest <code>{String(btAction.result.backtest_id)}</code>: trades {String(btAction.result.n_trades)} · Net R {f(btAction.result.net_profit_r, 2)} · EV {f(btAction.result.expected_value_r, 3)} R · Sharpe {f(btAction.result.sharpe_ratio, 2)} · Sortino {f(btAction.result.sortino_ratio, 2)} · CVaR95 {f(btAction.result.tail_risk_cvar95_r, 2)} R · OOS EV {f((btAction.result.walk_forward_oos as R | undefined)?.out_of_sample_ev_r, 3)} R
          </p>
        ) : null}
        {wfAction.result ? <pre className="ux-pre">{JSON.stringify(wfAction.result.stages, null, 2)}</pre> : null}
      </Card>
    </div>
  );
}

/* ---------- 2. Broker Intelligence & Capability Separation ---------- */
export function BrokerIntelligenceBench() {
  const bi = useApi<R>("/api/research-integration/broker-intelligence", 30000);
  return (
    <Card
      title="Broker MCP intelligence & source-tagged reconciliation"
      span="full"
      subtitle="Distinguishes BROKER_REPORTED, ATLAS_CALCULATED, ESTIMATED, and STALE figures across Alpaca Paper & IBKR MCP. Enforces BROKER_READ_ONLY vs BROKER_PAPER_EXECUTION separation; BROKER_LIVE_EXECUTION is permanently disabled."
    >
      <Async state={bi} label="Loading broker intelligence">
        {(d) => {
          const m = (d.metrics ?? {}) as Record<string, R>;
          const metricRows = Object.entries(m).map(([k, v]) => ({
            metric: k.replace(/_usd$/, "").replaceAll("_", " "),
            broker_reported: v.broker_reported !== null && v.broker_reported !== undefined ? `$${Number(v.broker_reported).toLocaleString()}` : "unconfigured (not fabricated)",
            atlas_calculated: `$${Number(v.atlas_calculated ?? 0).toLocaleString()}`,
            discrepancy: v.discrepancy_usd !== null && v.discrepancy_usd !== undefined ? `$${f(v.discrepancy_usd, 2)}` : "—",
            source_tag: v.source_tag,
          }));
          const mcpRows = Object.entries((d.mcp_registry ?? {}) as Record<string, R>).map(([id, spec]) => ({
            id,
            provider: spec.provider,
            endpoint: spec.package_or_endpoint,
            policy: spec.order_operations_policy,
            live_status: spec.live_execution_status,
            docs: spec.official_docs_url,
          }));
          return (
            <>
              <DataTable
                caption="Broker vs ATLAS-Calculated Reconciliation"
                rows={metricRows}
                columns={[
                  { key: "metric", label: "Account Metric" },
                  { key: "broker_reported", label: "Broker Reported", align: "right" },
                  { key: "atlas_calculated", label: "ATLAS Control Plane", align: "right" },
                  { key: "discrepancy", label: "Discrepancy", align: "right" },
                  { key: "source_tag", label: "Provenance Tag", render: (r) => <Badge tone={r.source_tag === "BROKER_REPORTED" ? "good" : "info"}>{String(r.source_tag)}</Badge> },
                ]}
              />
              <h4>Official Broker MCP Capability Registry</h4>
              <DataTable
                caption="Official Broker MCP Integrations"
                rows={mcpRows}
                columns={[
                  { key: "provider", label: "Broker" },
                  { key: "endpoint", label: "MCP Server / Endpoint" },
                  { key: "policy", label: "Capability Guard Policy" },
                  { key: "live_status", label: "Live Execution", render: (r) => <Badge tone="bad">{String(r.live_status)}</Badge> },
                  { key: "docs", label: "Official Reference", render: (r) => <a className="ux-link" href={String(r.docs)} target="_blank" rel="noopener noreferrer">Official MCP Docs ↗</a> },
                ]}
              />
            </>
          );
        }}
      </Async>
    </Card>
  );
}

/* ---------- 3. Dynamic Position-Sizing Research & Risk Cascade ---------- */
export function DynamicPositionSizingBench() {
  const [sym, setSym] = useState("GC");
  const [entry, setEntry] = useState(2750);
  const [atr, setAtr] = useState(12.5);
  const [atrMult, setAtrMult] = useState(1.5);
  const [riskFrac, setRiskFrac] = useState(0.005);
  const [winProb, setWinProb] = useState<number | null>(null); // no default: enter a calibrated probability or leave blank
  const [track, setTrack] = useState("competition");
  const sizer = useAction<R>("/api/research-integration/position-sizing");

  return (
    <Card
      title="Dynamic position-sizing research & 10-constraint control-plane cascade"
      span="full"
      subtitle="Computes Fixed-Fractional, ATR-Based, and Uncertainty-Penalized Quarter-Kelly sizing aligned to CME/equity contract multipliers. The strictest portfolio constraint prevails and only ActionableControlPlaneEngine can approve final quantity."
    >
      <div className="ux-form-grid">
        <label className="ux-form-row">
          Symbol{" "}
          <select value={sym} onChange={(e) => setSym(e.target.value)} aria-label="Sizing symbol">
            {["GC", "MGC", "SI", "ES", "NQ", "SPY", "QQQ", "BTC-USD"].map((x) => (
              <option key={x} value={x}>{x}</option>
            ))}
          </select>
        </label>
        <label className="ux-form-row">
          Track{" "}
          <select value={track} onChange={(e) => setTrack(e.target.value)} aria-label="Sizing track">
            <option value="competition">competition (0.5% cap)</option>
            <option value="open_market">open_market (1.0% cap)</option>
          </select>
        </label>
        <label className="ux-form-row">
          Entry <input type="number" step="any" value={entry} onChange={(e) => setEntry(Number(e.target.value))} style={{ width: 95 }} />
        </label>
        <label className="ux-form-row">
          ATR <input type="number" step="any" value={atr} onChange={(e) => setAtr(Number(e.target.value))} style={{ width: 80 }} />
        </label>
        <label className="ux-form-row">
          ATR× <input type="number" step="0.1" value={atrMult} onChange={(e) => setAtrMult(Number(e.target.value))} style={{ width: 70 }} />
        </label>
        <label className="ux-form-row">
          Risk frac <input type="number" step="0.001" value={riskFrac} onChange={(e) => setRiskFrac(Number(e.target.value))} style={{ width: 80 }} />
        </label>
        <label className="ux-form-row">
          Win p <input type="number" step="0.01" value={winProb ?? ""} placeholder="none" onChange={(e) => setWinProb(e.target.value === "" ? null : Number(e.target.value))} style={{ width: 75 }} />
        </label>
        <ActionButton
          action={sizer}
          body={{
            candidate_id: `ui-${sym.toLowerCase()}`,
            symbol: sym,
            track,
            entry_price: entry,
            atr_value: atr,
            atr_multiplier: atrMult,
            risk_fraction: riskFrac,
            win_probability: winProb,
            payoff_ratio_b: 2.0,
          }}
          tone="primary"
        >
          Compute Sizing Proposal
        </ActionButton>
      </div>
      <ActionResult action={sizer} />
      {sizer.result ? (
        <>
          <div className="ux-layout">
            <StatTile label="Risk Budget" value={`$${f(sizer.result.risk_budget, 2)}`} hint={`Stop ${f(sizer.result.stop_distance, 2)} (${f(sizer.result.stop_distance_bps, 1)} bps)`} />
            <StatTile label="Proposed Qty" value={String(sizer.result.proposed_quantity)} hint={`Notional $${f(sizer.result.proposed_notional_usd, 2)}`} />
            <StatTile label="Kelly (Full / Cap)" value={`${f(sizer.result.kelly_full_fraction, 3)} / ${f(sizer.result.kelly_fractional_cap, 4)}`} hint="Quarter-Kelly + ECE haircut" />
            <StatTile label="Control Plane" value={String((sizer.result.risk_engine_decision as R | undefined)?.decision ?? "—")} hint={`Binding: ${String(sizer.result.binding_constraint)}`} />
          </div>
          <DataTable
            caption="Portfolio Constraint Cascade"
            rows={(sizer.result.constraint_evaluations as R[]) ?? []}
            columns={[
              { key: "constraint", label: "Constraint" },
              { key: "max_quantity", label: "Max Allowed Qty", align: "right", render: (r) => f(r.max_quantity, 4) },
              { key: "detail", label: "Constraint Detail" },
            ]}
          />
        </>
      ) : null}
    </Card>
  );
}

/* ---------- 4. AI Research Memory & Cross-Session Handoffs ---------- */
export function AiResearchMemoryAndHandoffBench() {
  const mem = useApi<{ count: number; records: R[] }>("/api/research-integration/memory", 60000);
  const ho = useApi<{ count: number; latest: R | null; handoffs: R[] }>("/api/research-integration/handoffs", 60000);
  const tm = useApi<{ total_requirements: number; verified_working_count: number; matrix: R[] }>("/api/research-integration/traceability-matrix", 120000);

  return (
    <div className="ux-layout">
      <Card
        title="Immutable research memory ledger (raw evidence separated from AI interpretation)"
        span="full"
        subtitle="Content-hashed experiment artifacts persisted in var/research/research_memory.json with reproduction commands."
      >
        <Async state={mem} label="Loading research memory" isEmpty={(d) => !d.records.length} empty={<EmptyState title="No research memory records" />}>
          {(d) => (
            <DataTable
              caption="Research Memory Records"
              rows={d.records}
              columns={[
                { key: "memory_id", label: "Memory ID" },
                { key: "experiment_identifier", label: "Experiment" },
                { key: "model_version", label: "Model Version" },
                { key: "hypothesis", label: "Hypothesis" },
                { key: "decision", label: "Decision", render: (r) => <Badge tone="good">{String(r.decision)}</Badge> },
                { key: "content_hash", label: "Content Hash" },
              ]}
            />
          )}
        </Async>
      </Card>

      <Card
        title="Cross-session AI handoff & repository consistency verifier"
        span={2}
        subtitle="Verifies referenced files on disk against the latest session handoff in var/research/session_handoffs.json."
      >
        <Async state={ho} label="Loading session handoff">
          {(d) =>
            d.latest ? (
              <>
                <p>
                  Handoff <code>{String(d.latest.handoff_id)}</code> · Objective: <strong>{String(d.latest.CURRENT_OBJECTIVE)}</strong> · Repository State:{" "}
                  <Badge tone="good">{String((d.latest.VERIFIED_REPOSITORY_STATE as R | undefined)?.consistency_status ?? "VERIFIED")}</Badge>
                </p>
                <pre className="ux-pre">{JSON.stringify(d.latest, null, 2)}</pre>
              </>
            ) : (
              <EmptyState title="No handoff generated yet" />
            )
          }
        </Async>
      </Card>

      <Card title="Requirements traceability matrix" subtitle="Runtime verification status across all 14 core platform modules.">
        <Async state={tm} label="Loading traceability matrix">
          {(d) => (
            <DataTable
              caption="Traceability Matrix"
              rows={d.matrix}
              maxHeight={300}
              columns={[
                { key: "id", label: "ID" },
                { key: "capability", label: "Capability" },
                { key: "status", label: "Status", render: (r) => <Badge tone="good">{String(r.status)}</Badge> },
              ]}
            />
          )}
        </Async>
      </Card>
    </div>
  );
}

