"use client";

/** Multi-agent research view: parallel analysts, bounded bull/bear debate, research manager,
 *  trader candidate, three risk perspectives and a deterministic control-plane dry run.
 *  Research only: this panel cannot submit an order. Unavailable evidence is shown as unavailable. */
import { useEffect, useState } from "react";
import {
  ActionButton, ActionResult, Async, Badge, Card, DataTable, EmptyState, useAction, useApi,
  type Tone,
} from "../primitives";

type R = Record<string, unknown>;
type Evidence = { source_id: string; source_type: string; available_at: string; untrusted: boolean };
type Analyst = {
  analyst_type: string; status: string; stance: string; confidence_label: string; thesis: string;
  horizon: string; supporting_evidence: Evidence[]; contradicting_evidence: Evidence[];
  missing_data: string[]; uncertainties: string[];
};
type DebateRound = { round: number; bull_argument: string; bear_argument: string; round_edge: number };
type Run = {
  run_id: string; instrument_id: string; timeframe: string; status: string; current_node: string | null;
  as_of: string; created_at: string; updated_at: string; recommendation?: string;
  data_snapshot_id: string | null; errors: string[]; execution_permission: "none";
  snapshot: null | {
    snapshot_id: string; as_of: string; bars_count: number; last_close: number | null;
    freshness: R; missing_data: string[]; prompt_injection_flags: string[];
  };
  analyst_reports: Analyst[];
  reconciliation: null | {
    agreements: string[]; missing_information: string[]; data_quality_issues: string[];
    contradictions: { topic: string; detail: string; analyst_types: string[] }[];
    prompt_injection_flags: string[];
  };
  debate: null | {
    rounds_completed: number; rounds_max: number; bull_score: number; bear_score: number; net_score: number;
    bull_case_summary: string; bear_case_summary: string; unresolved: string[]; stopped_reason: string;
    rounds: DebateRound[];
  };
  research_decision: null | {
    outcome: string; thesis: string; strongest_bull: string; strongest_bear: string;
    unresolved: string[]; confidence_label: string; evidence_ids: string[]; abstention_reason?: string | null;
  };
  trade_proposal: null | {
    action: string; side: string | null; instrument_id: string; notional_usd: number | null; entry_price: number | null;
    stop_price: number | null; target_price: number | null; stop_distance_bps: number | null;
    reward_risk: number | null; supporting_evidence_ids: string[]; rejection_reasons: string[];
  };
  risk_reviews: { perspective: string; verdict: string; concerns: string[]; favorable_factors: string[]; severity: string }[];
  portfolio_review: null | { outcome: string; reasons: string[]; constraints: string[]; portfolio_context_available: boolean };
  deterministic_decision: null | {
    outcome: string; authorized: boolean; violations: string[]; authority: string; submitted: boolean; notes: string[];
  };
};
type RunRow = {
  run_id: string; instrument_id: string; timeframe: string; status: string; as_of: string;
  recommendation: string | null; deterministic_outcome: string | null; analyst_count: number;
};
type Status = {
  store: { runs: number; completed_runs: number; reflections: number; checkpoints: number };
  llm_provider_injected: boolean; dependencies_injected: boolean;
  authority: string; execution_permission: "none";
};
type Evolution = {
  completed_runs: number; reflected_runs: number;
  research_directional_accuracy: number | null; research_abstention_rate: number | null;
  baselines: { name: string; status: string; observations: number; directional_accuracy: number | null; abstention_rate: number | null; note: string }[];
  cost_notes: string[];
};

const f = (v: unknown, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : v === null || v === undefined ? "—" : String(v));
const pctf = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "—");
const toneFor = (stance: string): Tone => stance === "bullish" ? "good" : stance === "bearish" ? "bad" : stance === "neutral" ? "info" : "warn";
const toneForOutcome = (outcome: string | null): Tone => !outcome ? "neutral" : outcome.includes("BULL") || outcome === "PAPER_REVIEW_AUTHORIZED" || outcome === "RECOMMEND_FOR_RISK_REVIEW" ? "good" : outcome.includes("BEAR") || outcome.includes("REJECT") ? "bad" : "warn";
const list = (items: string[]) => items.length ? <ul className="ux-list">{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : <span className="ux-muted">None recorded.</span>;

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"];

export function MultiAgentView() {
  const [instrument, setInstrument] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("15m");
  const [asOf, setAsOf] = useState("");
  const [notional, setNotional] = useState(1000);
  const [rounds, setRounds] = useState(2);
  const [llm, setLlm] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [outcomePrice, setOutcomePrice] = useState(0);

  const status = useApi<Status>("/api/multi-agent/status", 30000);
  const runs = useApi<{ runs: RunRow[] }>("/api/multi-agent/runs?limit=25", 15000);
  const detail = useApi<{ run: Run }>(selected ? `/api/multi-agent/runs/${encodeURIComponent(selected)}` : null, 10000);
  const audit = useApi<{ events: R[]; verification: { valid: boolean; records: number } }>(
    selected ? `/api/multi-agent/runs/${encodeURIComponent(selected)}/audit` : null, 30000);
  const evolution = useApi<{ report: Evolution }>("/api/multi-agent/evolution", 60000);

  const create = useAction<{ run: Run }>("/api/multi-agent/runs");
  const resume = useAction<{ run: Run }>(selected ? `/api/multi-agent/runs/${encodeURIComponent(selected)}/resume` : "");
  const cancel = useAction<{ cancel_requested: boolean }>(selected ? `/api/multi-agent/runs/${encodeURIComponent(selected)}/cancel` : "");
  const reflect = useAction<{ reflection: R }>(selected ? `/api/multi-agent/runs/${encodeURIComponent(selected)}/reflect` : "");

  const run = detail.data?.run ?? null;
  const body = {
    instrument_id: instrument,
    timeframe,
    notional_usd: notional,
    debate_rounds: rounds,
    enable_llm: llm,
    as_of: asOf ? new Date(asOf).toISOString() : undefined,
  };


  useEffect(() => {
    const id = create.result?.run?.run_id;
    if (id) {
      setSelected(id);
      runs.reload();
    }
    // Only react to a completed create action; reload identity is intentionally omitted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [create.result]);

  return (
    <div className="ux-layout">
      <Card title="Multi-agent research" span="full"
        subtitle="Analysts run in parallel, disagreement is preserved through a bounded bull/bear debate, and only the deterministic control plane can authorize a paper review. Research never submits an order.">
        <Async state={status} label="Checking multi-agent service">{(s) => (
          <p>
            <Badge tone="good">service {s.store.completed_runs} completed</Badge>{" "}
            <Badge>{s.store.runs} runs</Badge>{" "}
            <Badge>{s.store.reflections} reflections</Badge>{" "}
            <Badge tone={s.llm_provider_injected ? "info" : "neutral"}>{s.llm_provider_injected ? "LLM provider injected" : "deterministic team only"}</Badge>{" "}
            <span className="ux-muted">Authority: {s.authority}. Permission: {s.execution_permission}.</span>
          </p>
        )}</Async>
        <div className="ux-form-grid">
          <label className="ux-form-row">Instrument{" "}
            <input aria-label="Instrument" value={instrument} onChange={(e) => setInstrument(e.target.value.toUpperCase())} style={{ width: 140 }} /></label>
          <label className="ux-form-row">Timeframe{" "}
            <select aria-label="Timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
            </select></label>
          <label className="ux-form-row">As of (optional){" "}
            <input aria-label="As of" type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
          <label className="ux-form-row">Review notional{" "}
            <input aria-label="Review notional" type="number" min={1} step="1" value={notional} onChange={(e) => setNotional(Number(e.target.value))} style={{ width: 120 }} /></label>
          <label className="ux-form-row">Debate rounds{" "}
            <input aria-label="Debate rounds" type="number" min={0} max={5} step="1" value={rounds} onChange={(e) => setRounds(Number(e.target.value))} style={{ width: 80 }} /></label>
          <label className="ux-form-row">
            <input type="checkbox" checked={llm} onChange={(e) => setLlm(e.target.checked)} /> Allow optional LLM synthesis
          </label>
        </div>
        <ActionButton action={create} body={body} tone="primary">Run research</ActionButton>
        <ActionResult action={create} success={create.result?.run ? `Run ${create.result.run.run_id} finished with ${create.result.run.status}.` : undefined} />
        {llm && status.data && !status.data.llm_provider_injected ? (
          <p className="ux-muted">No LLM provider is configured; the run will record that honest gap and continue with deterministic analysts.</p>
        ) : null}
      </Card>

      <Card title="Run history" span={1} subtitle="Select a run to inspect its evidence, debate, risk reviews and dry-run decision.">
        <Async state={runs} label="Loading runs">{(d) => (
          <DataTable rows={d.runs as unknown as R[]} empty={<EmptyState title="No research runs yet">Start one above.</EmptyState>}
            columns={[
              { key: "run_id", label: "Run", render: (r) => <button type="button" className="ux-link-btn" onClick={() => setSelected(String(r.run_id))}>{String(r.run_id).slice(-18)}</button> },
              { key: "instrument_id", label: "Instrument" },
              { key: "status", label: "Status" },
              { key: "recommendation", label: "Research", render: (r) => r.recommendation ? <Badge tone={toneForOutcome(String(r.recommendation))}>{String(r.recommendation)}</Badge> : "—" },
              { key: "deterministic_outcome", label: "Gate", render: (r) => r.deterministic_outcome ? <Badge tone={toneForOutcome(String(r.deterministic_outcome))}>{String(r.deterministic_outcome)}</Badge> : "—" },
            ]} />
        )}</Async>
      </Card>

      <Card title="Selected run" span={2} subtitle="The decision is advisory. A dry-run authorization is not an order and never books a position.">
        {!selected ? <EmptyState title="No run selected">Pick a run from the history or start a new one.</EmptyState> : (
          <Async state={detail} label="Loading run">{(d) => {
            const r = d.run;
            return <>
              <p>
                <Badge tone={r.status === "completed" ? "good" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Badge>{" "}
                {r.instrument_id} {r.timeframe} as of {new Date(r.as_of).toLocaleString()}{" "}
                <span className="ux-muted">node {r.current_node ?? "—"} · permission {r.execution_permission}</span>
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
                <ActionButton action={resume} onDone={() => { detail.reload(); runs.reload(); }}>Resume</ActionButton>
                <ActionButton action={cancel} tone="danger" confirm="Request cancellation of this research run?" onDone={() => { detail.reload(); runs.reload(); }}>Cancel</ActionButton>
                <ActionResult action={resume} success="Resumed." />
                <ActionResult action={cancel} success="Cancellation requested." />
              </div>
              {r.errors.length ? <div className="ux-action-msg" data-tone="warn" role="status">Run notes: {r.errors.join("; ")}</div> : null}

              <h3 className="ux-h3">Evidence snapshot</h3>
              {!r.snapshot ? <p>No snapshot recorded.</p> : <>
                <p>{r.snapshot.bars_count} bars · last close {f(r.snapshot.last_close, 4)} · freshness {String(r.snapshot.freshness?.label ?? "—")}</p>
                <p className="ux-muted">Missing: {r.snapshot.missing_data.join(", ") || "none recorded"}.</p>
                {r.snapshot.prompt_injection_flags.length ? <p><Badge tone="bad">Untrusted instruction patterns</Badge> {r.snapshot.prompt_injection_flags.join(", ")}</p> : null}
              </>}

              <h3 className="ux-h3">Analysts</h3>
              <DataTable rows={r.analyst_reports as unknown as R[]} empty={<EmptyState title="No analyst reports" />}
                columns={[
                  { key: "analyst_type", label: "Analyst" },
                  { key: "status", label: "Status" },
                  { key: "stance", label: "Stance", render: (x) => <Badge tone={toneFor(String(x.stance))}>{String(x.stance)}</Badge> },
                  { key: "confidence_label", label: "Confidence" },
                  { key: "horizon", label: "Horizon" },
                  { key: "missing_data", label: "Missing", render: (x) => (Array.isArray(x.missing_data) ? x.missing_data.length : 0) },
                ]} />
              <div className="ux-layout" style={{ marginTop: 8 }}>
                {r.analyst_reports.filter((a) => a.status === "ok").map((a) => (
                  <Card key={a.analyst_type} title={a.analyst_type.replaceAll("_", " ")} subtitle={`${a.stance} · ${a.confidence_label} · evidence ${a.supporting_evidence.length}+/${a.contradicting_evidence.length}-`}>
                    <p>{a.thesis}</p>
                    {a.uncertainties.length ? <><h4 className="ux-h4">Uncertainties</h4>{list(a.uncertainties)}</> : null}
                    {a.missing_data.length ? <><h4 className="ux-h4">Missing data</h4>{list(a.missing_data)}</> : null}
                  </Card>
                ))}
              </div>

              <h3 className="ux-h3">Reconciliation</h3>
              {!r.reconciliation ? <p>No reconciliation recorded.</p> : <>
                <p>Agreements: {r.reconciliation.agreements.join("; ") || "none recorded"}.</p>
                <p>Contradictions: {r.reconciliation.contradictions.length ? "" : "none recorded."}</p>
                {r.reconciliation.contradictions.length ? <DataTable rows={r.reconciliation.contradictions as unknown as R[]}
                  columns={[{ key: "topic", label: "Topic" }, { key: "detail", label: "Detail" }, { key: "analyst_types", label: "Analysts", render: (x) => Array.isArray(x.analyst_types) ? x.analyst_types.join(", ") : "" }]} /> : null}
                {r.reconciliation.missing_information.length ? <><h4 className="ux-h4">Missing information</h4>{list(r.reconciliation.missing_information)}</> : null}
                {r.reconciliation.data_quality_issues.length ? <><h4 className="ux-h4">Data-quality issues</h4>{list(r.reconciliation.data_quality_issues)}</> : null}
              </>}

              <h3 className="ux-h3">Debate</h3>
              {!r.debate ? <p>No debate recorded.</p> : <>
                <p>Bull {f(r.debate.bull_score)} vs bear {f(r.debate.bear_score)} · net {f(r.debate.net_score)} · {r.debate.rounds_completed}/{r.debate.rounds_max} rounds · {r.debate.stopped_reason}</p>
                <p><strong>Bull case:</strong> {r.debate.bull_case_summary || "none"}</p>
                <p><strong>Bear case:</strong> {r.debate.bear_case_summary || "none"}</p>
                {r.debate.rounds.length ? <DataTable rows={r.debate.rounds as unknown as R[]}
                  columns={[{ key: "round", label: "Round" }, { key: "bull_argument", label: "Bull" }, { key: "bear_argument", label: "Bear" }, { key: "round_edge", label: "Edge", align: "right", render: (x) => f(x.round_edge) }]} /> : null}
                {r.debate.unresolved.length ? <><h4 className="ux-h4">Unresolved</h4>{list(r.debate.unresolved)}</> : null}
              </>}

              <h3 className="ux-h3">Research decision</h3>
              {!r.research_decision ? <p>No research decision recorded.</p> : <>
                <p><Badge tone={toneForOutcome(r.research_decision.outcome)}>{r.research_decision.outcome}</Badge> confidence {r.research_decision.confidence_label}</p>
                <p>{r.research_decision.thesis}</p>
                <p><strong>Strongest bull:</strong> {r.research_decision.strongest_bull || "none"}</p>
                <p><strong>Strongest bear:</strong> {r.research_decision.strongest_bear || "none"}</p>
                {r.research_decision.abstention_reason ? <p className="ux-muted">Abstention: {r.research_decision.abstention_reason}</p> : null}
              </>}

              <h3 className="ux-h3">Trader candidate and risk</h3>
              {!r.trade_proposal ? <p>No trader candidate.</p> : <>
                <p><Badge>{r.trade_proposal.action}</Badge> {r.trade_proposal.side ?? "—"} {r.trade_proposal.instrument_id} notional ${f(r.trade_proposal.notional_usd, 0)}</p>
                <p>Entry {f(r.trade_proposal.entry_price, 4)} · stop {f(r.trade_proposal.stop_price, 4)} · target {f(r.trade_proposal.target_price, 4)} · R:R {f(r.trade_proposal.reward_risk)} · stop {f(r.trade_proposal.stop_distance_bps, 0)} bps</p>
                {r.trade_proposal.rejection_reasons.length ? <p className="ux-muted">Open issues: {r.trade_proposal.rejection_reasons.join("; ")}.</p> : null}
              </>}
              <DataTable rows={r.risk_reviews as unknown as R[]}
                columns={[
                  { key: "perspective", label: "Perspective" },
                  { key: "verdict", label: "Verdict", render: (x) => <Badge tone={String(x.verdict).includes("support") ? "good" : String(x.verdict).includes("object") ? "bad" : "warn"}>{String(x.verdict)}</Badge> },
                  { key: "severity", label: "Severity" },
                  { key: "concerns", label: "Concerns", render: (x) => Array.isArray(x.concerns) ? x.concerns.join("; ") : "" },
                ]} />
              {r.portfolio_review ? <>
                <h3 className="ux-h3">Portfolio review</h3>
                <p><Badge tone={toneForOutcome(r.portfolio_review.outcome)}>{r.portfolio_review.outcome}</Badge> {r.portfolio_review.reasons.join("; ")}</p>
                <p className="ux-muted">Context supplied: {r.portfolio_review.portfolio_context_available ? "yes" : "no"}. {r.portfolio_review.constraints.join("; ")}</p>
              </> : null}

              <h3 className="ux-h3">Deterministic gate</h3>
              {!r.deterministic_decision ? <p>No deterministic decision recorded.</p> : <>
                <p><Badge tone={toneForOutcome(r.deterministic_decision.outcome)}>{r.deterministic_decision.outcome}</Badge>{" "}
                  authorized {r.deterministic_decision.authorized ? "yes (paper review only)" : "no"} · submitted {r.deterministic_decision.submitted ? "yes" : "no"}</p>
                <p className="ux-muted">Authority: {r.deterministic_decision.authority}</p>
                {r.deterministic_decision.violations.length ? <><h4 className="ux-h4">Violations</h4>{list(r.deterministic_decision.violations)}</> : null}
                {r.deterministic_decision.notes.length ? <p className="ux-muted">{r.deterministic_decision.notes.join("; ")}</p> : null}
              </>}

              <h3 className="ux-h3">Audit</h3>
              <Async state={audit} label="Loading audit">{(a) => (
                <p>
                  <Badge tone={a.verification.valid ? "good" : "bad"}>{a.verification.valid ? "hash chain valid" : "hash chain broken"}</Badge>{" "}
                  {a.verification.records} records ·{" "}
                  <span className="ux-muted">observable outputs only; no hidden reasoning.</span>
                </p>
              )}</Async>

              <h3 className="ux-h3">Reflect</h3>
              <p className="ux-muted">Record the observed outcome price. This never changes the original decision or its hash.</p>
              <div className="ux-form-grid">
                <label className="ux-form-row">Outcome price{" "}
                  <input aria-label="Outcome price" type="number" min={0} step="any" value={outcomePrice} onChange={(e) => setOutcomePrice(Number(e.target.value))} style={{ width: 140 }} /></label>
              </div>
              <ActionButton action={reflect} body={{ outcome_price: outcomePrice }} disabled={!outcomePrice || outcomePrice <= 0}
                onDone={() => evolution.reload()}>Record reflection</ActionButton>
              <ActionResult action={reflect} success="Reflection recorded." />
            </>;
          }}</Async>
        )}
      </Card>

      <Card title="Evolution and baselines" span="full" subtitle="Reflections only; no automatic promotion, retraining or live execution. Directional accuracy is not calibration.">
        <Async state={evolution} label="Loading evolution">{(d) => <>
          <p>{d.report.completed_runs} completed runs · {d.report.reflected_runs} reflected · research accuracy {pctf(d.report.research_directional_accuracy)} · abstention {pctf(d.report.research_abstention_rate)}</p>
          <DataTable rows={d.report.baselines as unknown as R[]}
            columns={[
              { key: "name", label: "Baseline" },
              { key: "status", label: "Status" },
              { key: "observations", label: "Observations", align: "right" },
              { key: "directional_accuracy", label: "Directional accuracy", align: "right", render: (x) => pctf(x.directional_accuracy) },
              { key: "abstention_rate", label: "Abstention", align: "right", render: (x) => pctf(x.abstention_rate) },
              { key: "note", label: "Note" },
            ]} />
          {list(d.report.cost_notes)}
        </>}</Async>
      </Card>
    </div>
  );
}
