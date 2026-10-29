"use client";
/** Pass-5 intelligence views: research lab, regimes, memory & governance, grounded assistant, microstructure, Four-Box,
 *  portfolio risk and track rulebooks. All read-only research surfaces: execution_permission is "none" everywhere and
 *  only the deterministic control plane can approve or size an order. Every card shows the payload's freshness label. */
import { useState } from "react";
import { AiResearchMemoryAndHandoffBench, DynamicPositionSizingBench } from "./ResearchIntegrationViews";
import type { Fresh } from "../FreshBadge";
import { Async, Badge, Card, Command, DataTable, EmptyState, useApi } from "../primitives";

type R = Record<string, unknown>;
type WithFresh = { freshness?: Fresh; status?: string; execution_permission?: string };
const f = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : v === null || v === undefined ? "—" : String(v));
const ts = (t: unknown) => (typeof t === "number" ? new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "—");
const SYMS = ["GC", "SI", "SPY", "ES", "BTCUSDT"];
const fr = (s: { data: WithFresh | null }) => (s.data?.freshness ?? null) as Fresh | null;

function SymbolPick({ sym, set }: { sym: string; set: (s: string) => void }) {
  return (
    <label className="ux-form-row">Symbol{" "}
      <select value={sym} onChange={(e) => set(e.target.value)} aria-label="Symbol">{SYMS.map((s) => <option key={s}>{s}</option>)}</select>
      {" "}<span className="ux-muted">15-minute bars from the local feed</span>
    </label>
  );
}
const noData = (d: WithFresh) => d.status === "no_data";
const NoData = <EmptyState title="No bars in the feed for this symbol">Nothing is estimated or filled in.</EmptyState>;

/* ---------- Research lab ---------- */
type Run = { report_id: string; name: string; instrument: string; bars: number; created_at: string; code_sha: string; seed: number;
  deflated_sharpe?: { best_variant: string; dsr: number; n_trials: number } | null; pbo?: { pbo: number; n_combinations: number } | null; pbo_note?: string | null;
  variants: Record<string, { n_trades: number; zero_trade_reason?: string | null; mean_r: number | null; win_rate: number | null; bootstrap_mean_r?: { lo: number; hi: number; p_mean_le_0: number } | null;
    cost_sensitivity: { cost_mult: number; mean_r: number | null }[] }>; data_label?: string };

export function LabView() {
  const runs = useApi<{ runs: Run[] } & WithFresh>("/api/intel/lab/runs?limit=20", 60000);
  const [sel, setSel] = useState(0);
  return (
    <div className="ux-layout">
      <Card title="Experiment runs" span="full" fresh={fr(runs)}
        subtitle="Each run replays the same bars under several strategy variants, after venue costs. The report ID is a hash of data, code and settings, so re-running gives the same ID."
        footer={<>New run (paper research only): <Command text="PYTHONPATH=src python -c &quot;from atlas.intel.lab import *&quot;  # or POST /api/intel/lab/run?symbol=GC" /></>}>
        <Async state={runs} label="Loading runs" isEmpty={(d) => !d.runs.length} empty={<EmptyState title="No experiments recorded yet">POST /api/intel/lab/run to record one.</EmptyState>}>
          {(d) => <DataTable rows={d.runs.map((r, i) => ({ i, id: r.report_id, name: r.name, inst: r.instrument, bars: r.bars, at: r.created_at.slice(0, 16),
              best: r.deflated_sharpe?.best_variant, dsr: r.deflated_sharpe?.dsr, pbo: r.pbo?.pbo, sha: r.code_sha.slice(0, 8) })) as R[]} columns={[
            { key: "id", label: "Report" }, { key: "name", label: "Name" }, { key: "inst", label: "Symbol" }, { key: "bars", label: "Bars", align: "right" },
            { key: "at", label: "Created (UTC)" }, { key: "best", label: "Best variant" },
            { key: "dsr", label: "Deflated Sharpe", align: "right", render: (r) => f(r.dsr) }, { key: "pbo", label: "PBO", align: "right", render: (r) => f(r.pbo) },
            { key: "sha", label: "Code" },
            { key: "i", label: "", render: (r) => <button type="button" className="ux-link-btn" aria-pressed={sel === r.i} onClick={() => setSel(Number(r.i))}>Open</button> }]} />}
        </Async>
      </Card>
      {runs.data?.runs[sel] ? <RunDetail run={runs.data.runs[sel]} fresh={fr(runs)} /> : null}
    </div>
  );
}

function RunDetail({ run, fresh }: { run: Run; fresh: Fresh | null }) {
  const rows = Object.entries(run.variants).map(([v, s]) => ({ v, n: s.n_trades, why: s.zero_trade_reason ?? "", mean: s.mean_r, win: s.win_rate,
    ci: s.bootstrap_mean_r ? `${f(s.bootstrap_mean_r.lo)} … ${f(s.bootstrap_mean_r.hi)}` : "too few trades",
    p0: s.bootstrap_mean_r?.p_mean_le_0, ...Object.fromEntries(s.cost_sensitivity.map((c) => [`c${c.cost_mult}`, c.mean_r])) }));
  return (
    <Card title={`Report ${run.report_id}`} span="full" fresh={fresh}
      subtitle={`Seed ${run.seed}. DSR deflates the best variant's Sharpe for ${run.deflated_sharpe?.n_trials ?? "—"} trials; PBO is the probability the in-sample winner underperforms out of sample (${run.pbo?.n_combinations ?? 0} splits). ${run.pbo_note ?? ""}`}>
      <DataTable rows={rows as R[]} columns={[
        { key: "v", label: "Variant" }, { key: "n", label: "Trades", align: "right" }, { key: "why", label: "Why 0 trades" },
        { key: "mean", label: "Mean R", align: "right", render: (r) => f(r.mean) }, { key: "win", label: "Win rate", align: "right", render: (r) => f(r.win, 2) },
        { key: "ci", label: "Bootstrap 95% CI (mean R)" }, { key: "p0", label: "P(mean ≤ 0)", align: "right", render: (r) => f(r.p0, 2) },
        { key: "c0", label: "0× cost", align: "right", render: (r) => f(r.c0) }, { key: "c1", label: "1×", align: "right", render: (r) => f(r.c1) },
        { key: "c2", label: "2×", align: "right", render: (r) => f(r.c2) }, { key: "c3", label: "3×", align: "right", render: (r) => f(r.c3) }]} />
      <p className="ux-muted">Variants with 0 trades produced no fills on these bars; they are reported, not hidden. A positive point estimate with a CI spanning zero is not evidence of an edge.</p>
    </Card>
  );
}

/* ---------- Regimes ---------- */
type Regimes = WithFresh & { current?: { label: string; trend_z: number; atr_pct: number; t: number }; distribution?: Record<string, number>;
  recent?: { t: number; label: string }[]; by_strategy?: { detector: string; regime: string; n: number; mean_r: number | null; win_rate: number | null; total_r: number; sufficient_n: boolean }[]; method?: string };

export function RegimesView() {
  const [sym, setSym] = useState("GC");
  const s = useApi<Regimes>(`/api/intel/regimes?symbol=${sym}`, 120000);
  return (
    <div className="ux-layout">
      <Card title="Current regime" fresh={fr(s)} subtitle="Causal: each label uses only bars at or before it." actions={<SymbolPick sym={sym} set={setSym} />}>
        <Async state={s} label="Loading regime" isEmpty={noData} empty={NoData}>
          {(d) => <><p><Badge tone="info">{d.current?.label}</Badge> trend z {f(d.current?.trend_z, 2)}, ATR percentile {f(d.current?.atr_pct, 2)} at {ts(d.current?.t)}</p>
            <p className="ux-muted">{d.method}</p></>}
        </Async>
      </Card>
      <Card title="Time in each regime" fresh={fr(s)}>
        <Async state={s} label="Loading distribution" isEmpty={noData} empty={NoData}>
          {(d) => <DataTable rows={Object.entries(d.distribution ?? {}).map(([k, v]) => ({ k, v })) as R[]} columns={[{ key: "k", label: "Regime" }, { key: "v", label: "Bars", align: "right" }]} />}
        </Async>
      </Card>
      <Card title="Strategy results by regime" span="full" fresh={fr(s)} subtitle="Replay trades after costs, grouped by the regime at entry. Cells under 20 trades are flagged as too small to read.">
        <Async state={s} label="Loading strategy table" isEmpty={(d) => noData(d) || !d.by_strategy?.length} empty={<EmptyState title="No resolved replay trades" />}>
          {(d) => <DataTable rows={(d.by_strategy ?? []) as R[]} columns={[
            { key: "detector", label: "Detector" }, { key: "regime", label: "Regime" }, { key: "n", label: "Trades", align: "right" },
            { key: "mean_r", label: "Mean R", align: "right", render: (r) => f(r.mean_r) }, { key: "win_rate", label: "Win", align: "right", render: (r) => f(r.win_rate, 2) },
            { key: "total_r", label: "Total R", align: "right", render: (r) => f(r.total_r, 2) },
            { key: "sufficient_n", label: "Sample", render: (r) => <Badge tone={r.sufficient_n ? "good" : "warn"}>{r.sufficient_n ? "n ≥ 20" : "small"}</Badge> }]} />}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Memory & governance ---------- */
type Bucket = { key: string; n: number; mean_r: number | null; total_r: number };
type Memory = WithFresh & { n_memory?: number; attribution?: Record<string, Bucket[] | number>; latest_analogues?: { query_candidate: string; status: string; n_eligible: number;
  analogues: R[]; analogue_mean_r: number | null; analogue_win_rate: number | null; note: string }; governance?: R };

export function MemoryView() {
  const [sym, setSym] = useState("GC");
  const s = useApi<Memory>(`/api/intel/memory?symbol=${sym}`, 120000);
  const dims = ["by_detector", "by_regime", "by_direction", "by_outcome", "by_hour_utc"];
  return (
    <div className="ux-layout">
      <Card title="Outcome attribution" span="full" fresh={fr(s)} actions={<SymbolPick sym={sym} set={setSym} />}
        subtitle="Where replay R came from. Each breakdown sums to the same total.">
        <Async state={s} label="Loading attribution" isEmpty={(d) => noData(d) || !d.n_memory} empty={<EmptyState title="No resolved trades in memory" />}>
          {(d) => <div className="ux-layout">{dims.map((k) => <div key={k}><h4>{k.replace("by_", "By ").replace("_utc", " (UTC)")}</h4>
            <DataTable rows={((d.attribution?.[k] as Bucket[]) ?? []) as unknown as R[]} columns={[{ key: "key", label: "Bucket" }, { key: "n", label: "n", align: "right" },
              { key: "mean_r", label: "Mean R", align: "right", render: (r) => f(r.mean_r) }, { key: "total_r", label: "Total R", align: "right", render: (r) => f(r.total_r, 2) }]} /></div>)}</div>}
        </Async>
      </Card>
      <Card title="Closest past setups" span={2} fresh={fr(s)} subtitle="Nearest resolved setups to the latest one, using only trades that had finished before it.">
        <Async state={s} label="Loading analogues" isEmpty={(d) => !d.latest_analogues} empty={<EmptyState title="No query setup" />}>
          {(d) => <><p>{d.latest_analogues?.query_candidate}: {d.latest_analogues?.status}, {d.latest_analogues?.n_eligible} eligible; analogue mean R {f(d.latest_analogues?.analogue_mean_r)}.</p>
            <DataTable rows={(d.latest_analogues?.analogues ?? []) as R[]} columns={[{ key: "candidate_id", label: "Setup" }, { key: "detector", label: "Detector" },
              { key: "distance", label: "Distance", align: "right", render: (r) => f(r.distance) }, { key: "outcome", label: "Outcome" }, { key: "r_multiple", label: "R", align: "right", render: (r) => f(r.r_multiple) }]} />
            <p className="ux-muted">{d.latest_analogues?.note}</p></>}
        </Async>
      </Card>
      <AiResearchMemoryAndHandoffBench />
      <Card title="Model governance" fresh={fr(s)} subtitle="Retraining, promotion and rollback go through the gated model registry. This view is read-only.">
        <Async state={s} label="Loading governance">
          {(d) => <DataTable rows={Object.entries(d.governance ?? {}).map(([k, v]) => ({ k, v: typeof v === "object" ? JSON.stringify(v) : String(v) })) as R[]}
            columns={[{ key: "k", label: "Field" }, { key: "v", label: "Value" }]} />}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Assistant ---------- */
type Ask = WithFresh & { answer: { text: string; evidence: string[] }[]; evidence: { id: string; cite: string; heading: string; snippet: string; score: number }[];
  llm: { state: string; used: boolean }; note?: string | null; mode: string };

export function AssistantView() {
  const [q, setQ] = useState("");
  const [sq, setSq] = useState<string | null>(null);
  const s = useApi<Ask>(sq ? `/api/intel/assistant?q=${encodeURIComponent(sq)}` : null, 3600000);
  return (
    <div className="ux-layout">
      <Card title="Research assistant" span="full" fresh={s.data ? fr(s) : null}
        subtitle="Answers are extracted sentences from the docs and lab reports, each tied to an evidence ID. No model writes text; it cannot trade.">
        <form className="ux-form-row" onSubmit={(e) => { e.preventDefault(); if (q.trim().length > 1) setSq(q.trim()); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. minimum stop distance" aria-label="Question" />{" "}
          <button type="submit" className="ux-btn">Ask</button>
        </form>
        {sq ? <Async state={s} label="Searching">
          {(d) => <>
            <p className="ux-muted">Mode: {d.mode}. Language model: <Badge tone="neutral">{d.llm.state.replaceAll("_", " ")}</Badge> (used: {String(d.llm.used)})</p>
            {d.answer.length ? <ul>{d.answer.map((a, i) => <li key={i}>{a.text} {a.evidence.map((e) => <code key={e}>[{e}]</code>)}</li>)}</ul>
              : <EmptyState title="No supporting evidence found">{d.note ?? "The assistant does not answer without evidence."}</EmptyState>}
            <DataTable rows={d.evidence as unknown as R[]} columns={[{ key: "id", label: "Evidence" }, { key: "cite", label: "Source" }, { key: "heading", label: "Section" },
              { key: "score", label: "Score", align: "right", render: (r) => f(r.score, 2) }, { key: "snippet", label: "Snippet" }]} />
          </>}
        </Async> : null}
      </Card>
    </div>
  );
}

/* ---------- Microstructure ---------- */
type Micro = WithFresh & { tiers?: Record<string, boolean>; highest_tier?: string; metrics?: { metric: string; tier: string; status: string; value?: number; kind?: string; reason?: string }[] };

export function MicrostructureView() {
  const [sym, setSym] = useState("GC");
  const s = useApi<Micro>(`/api/intel/microstructure?symbol=${sym}`, 120000);
  return (
    <div className="ux-layout">
      <Card title="Microstructure" span="full" fresh={fr(s)} actions={<SymbolPick sym={sym} set={setSym} />}
        subtitle="Metrics are gated by the data tier the feed actually has. Bar-based numbers are estimates; order-flow metrics stay blank until quote or trade data exists.">
        <Async state={s} label="Loading microstructure" isEmpty={noData} empty={NoData}>
          {(d) => <><p>Data tiers: {Object.entries(d.tiers ?? {}).map(([k, v]) => <Badge key={k} tone={v ? "good" : "neutral"}>{k}{v ? "" : " (none)"}</Badge>)}</p>
            <DataTable rows={(d.metrics ?? []) as unknown as R[]} columns={[{ key: "metric", label: "Metric" }, { key: "tier", label: "Needs tier" },
              { key: "status", label: "Status", render: (r) => <Badge tone={r.status === "ok" ? "good" : "neutral"}>{String(r.status)}</Badge> },
              { key: "value", label: "Value", align: "right", render: (r) => f(r.value, 4) }, { key: "kind", label: "Kind" }, { key: "reason", label: "Why blank" }]} /></>}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Four-Box ---------- */
type Box = { box: string; detector: string; status: string; reason?: string; n_candidates: number; n_zones?: number; latest: R[]; latest_zones?: R[] };
type FourBox = WithFresh & { session?: string | null; bars?: number; boxes?: Box[]; session_note?: string };

export function FourBoxView() {
  const [sym, setSym] = useState("GC");
  const s = useApi<FourBox>(`/api/intel/fourbox?symbol=${sym}`, 120000);
  return (
    <div className="ux-layout">
      <Card title="Four-Box" span="full" fresh={fr(s)} actions={<SymbolPick sym={sym} set={setSym} />}
        subtitle="Opening = opening-range retest, Breakout = dual Bollinger, Anchor = wick reversal. Event stays off until a verified event calendar is connected. Setups are research only.">
        <Async state={s} label="Loading boxes" isEmpty={noData} empty={NoData}>
          {(d) => <><p className="ux-muted">Session: {d.session ?? "none (24/7)"} · {d.bars} bars. {d.session_note ?? ""}</p>
            <DataTable rows={(d.boxes ?? []).map((b) => ({ ...b, last: b.latest[0] ? `${String(b.latest[0].direction)} @ ${f(b.latest[0].entry, 2)}` :
              b.latest_zones?.length ? `${String(b.latest_zones.at(-1)!.direction)} zone ${f(b.latest_zones.at(-1)!.low, 2)}–${f(b.latest_zones.at(-1)!.high, 2)}` : "—" })) as unknown as R[]} columns={[
              { key: "box", label: "Box" }, { key: "detector", label: "Detector" },
              { key: "status", label: "Status", render: (r) => <Badge tone={r.status === "enabled" ? "good" : "neutral"} title={r.reason ? String(r.reason) : undefined}>{String(r.status)}</Badge> },
              { key: "n_candidates", label: "Setups", align: "right" }, { key: "n_zones", label: "Zones", align: "right" }, { key: "last", label: "Latest" },
              { key: "reason", label: "Note" }]} /></>}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Portfolio risk ---------- */
type Port = WithFresh & { positions: R[]; exposure: { gross_usd: number; net_usd: number; by_class: Record<string, R> }; per_instrument: R[];
  correlation: { symbols: string[]; matrix: (number | null)[][]; note: string }; book: { status: string; unpriced_positions: string[]; var95_usd: number | null; cvar95_usd: number | null; var99_usd: number | null;
    stress: { scenario: string; kind: string; pnl_usd: number | null }[] }; note: string; positions_source?: string };

export function PortfolioRiskView() {
  const s = useApi<Port>("/api/intel/portfolio", 60000);
  return (
    <div className="ux-layout">
      <Card title="Book risk" span={2} fresh={fr(s)} subtitle="Historical-simulation VaR/CVaR from daily feed closes. Positions without a price series are listed, not guessed.">
        <Async state={s} label="Loading book">
          {(d) => <><p>Gross ${f(d.exposure.gross_usd, 0)} · net ${f(d.exposure.net_usd, 0)} · status <Badge tone={d.book.status === "ok" ? "good" : "warn"}>{d.book.status}</Badge></p>
            {(d.book.unpriced_positions ?? []).length ? <p>Unpriced: {(d.book.unpriced_positions ?? []).join(", ")}. VaR for the book is not computed.</p> : null}
            <p>VaR95 ${f(d.book.var95_usd, 0)} · CVaR95 ${f(d.book.cvar95_usd, 0)} · VaR99 ${f(d.book.var99_usd, 0)}</p>
            <p className="ux-muted">{d.positions_source}</p>
            <DataTable rows={d.positions ?? []} columns={[{ key: "position_id", label: "Position" }, { key: "track", label: "Track" }, { key: "instrument_id", label: "Instrument" },
              { key: "side", label: "Side" }, { key: "notional_usd", label: "Notional", align: "right" }]} /></>}
        </Async>
      </Card>
      <Card title="Stress" fresh={fr(s)} subtitle="Historical worst days and labelled hypothetical shocks.">
        <Async state={s} label="Loading stress">
          {(d) => <DataTable rows={(d.book.stress ?? []) as unknown as R[]} columns={[{ key: "scenario", label: "Scenario" }, { key: "kind", label: "Kind" },
            { key: "pnl_usd", label: "P&L $", align: "right", render: (r) => f(r.pnl_usd, 0) }]} />}
        </Async>
      </Card>
      <Card title="Per-instrument tail risk (per $10k long)" span="full" fresh={fr(s)}>
        <Async state={s} label="Loading instruments">
          {(d) => <DataTable rows={d.per_instrument ?? []} columns={[{ key: "symbol", label: "Symbol" }, { key: "asset_class", label: "Class" }, { key: "n_days", label: "Days", align: "right" },
            { key: "var95_per_10k", label: "VaR95", align: "right", render: (r) => f(r.var95_per_10k, 0) }, { key: "cvar95_per_10k", label: "CVaR95", align: "right", render: (r) => f(r.cvar95_per_10k, 0) },
            { key: "var99_per_10k", label: "VaR99", align: "right", render: (r) => f(r.var99_per_10k, 0) }, { key: "worst_day_pct", label: "Worst day %", align: "right", render: (r) => f(r.worst_day_pct, 2) }]} />}
        </Async>
      </Card>
      <DynamicPositionSizingBench />
      <Card title="Daily return correlation" span="full" fresh={fr(s)}>
        <Async state={s} label="Loading correlation">
          {(d) => <><DataTable rows={d.correlation.symbols.map((a, i) => ({ a, ...Object.fromEntries(d.correlation.symbols.map((b, j) => [b, d.correlation.matrix[i][j]])) })) as R[]}
            columns={[{ key: "a", label: "" }, ...d.correlation.symbols.map((b) => ({ key: b, label: b, align: "right" as const, render: (r: R) => f(r[b], 2) }))]} />
            <p className="ux-muted">{d.correlation.note}</p></>}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Tracks ---------- */
type Tracks = WithFresh & { rows: { field: string; competition: string; open_market: string; differs: boolean }[]; active_track: string; note: string;
  probes: { id: string; why: string; competition: R; open_market: R }[] };

type ContractRow = { instrument_id: string; exchange: string; multiplier: number; tick_size: number; tick_value: number;
  cost_per_contract_rt_usd: number; cost_source: string; verified: boolean; front: string; roll_date: string };
type Contracts = { contracts: ContractRow[]; source: string; all_verified: boolean };
type Reentry = { rows: { rule: string; code_default: number | null; effective: number | null; tightened: boolean }[];
  overlay: string; notes: string[]; feedback: string };
const RULE_LABEL: Record<string, string> = { per_level: "Entries per level per day", per_day: "Entries per setup family per day",
  cooldown_s: "Cooldown between entries (s)", max_loss_r_per_family_day: "Max loss per family per day (R)",
  max_loss_r_per_day: "Max loss per day, all families (R)", max_consecutive_losses: "Max consecutive losses per family" };

export function TracksView() {
  const s = useApi<Tracks>("/api/intel/tracks", 120000);
  const re = useApi<Reentry>("/api/intel/reentry", 120000);
  const ct = useApi<Contracts>("/api/intel/contracts", 300000);
  return (
    <div className="ux-layout">
      <Card title="Re-entry loss caps" subtitle="Tighten-only overlay on the deterministic re-entry rules. Realized paper results feed these caps; a looser value is ignored.">
        <Async state={re} label="Loading re-entry caps">
          {(d) => <><DataTable rows={d.rows.map((r) => ({ rule: RULE_LABEL[r.rule] ?? r.rule, base: r.code_default ?? "none", eff: r.effective ?? "none", t: r.tightened })) as unknown as R[]}
            columns={[{ key: "rule", label: "Rule" }, { key: "eff", label: "Effective" }, { key: "base", label: "Code default" },
              { key: "t", label: "", render: (r) => r.t ? <Badge tone="info">tightened</Badge> : null }]} />
            <p className="ux-muted">{d.feedback}. Overlay: {d.overlay}.{d.notes.length ? ` Ignored: ${d.notes.join("; ")}` : ""}</p></>}
        </Async>
      </Card>
      <Card title="Contract specs" subtitle="One source for sizing, replay costs and this view. Costs are research assumptions.">
        <Async state={ct} label="Loading contract specs">
          {(d) => <><DataTable rows={d.contracts.map((c) => ({ c: c.instrument_id, front: c.front, tv: `$${c.tick_value} / ${c.tick_size}`,
              mult: c.multiplier, cost: `$${c.cost_per_contract_rt_usd}`, roll: c.roll_date, v: c.verified })) as unknown as R[]}
            columns={[{ key: "c", label: "Contract" }, { key: "front", label: "Front" }, { key: "mult", label: "Multiplier" }, { key: "tv", label: "Tick value / size" },
              { key: "cost", label: "Round-trip cost" }, { key: "roll", label: "Roll" },
              { key: "v", label: "", render: (r) => r.v ? <Badge tone="good">verified</Badge> : <Badge tone="warn">unverified</Badge> }]} />
            {!d.all_verified && <p className="ux-muted">Unverified specs come from published exchange pages and have not been confirmed by a broker.</p>}</>}
        </Async>
      </Card>
      <Card title="Competition vs open market rulebooks" span={2} subtitle="Rule configuration, not market data (no freshness label applies). Each track has its own rulebook; the control plane picks it from the ticket's track.">
        <Async state={s} label="Loading rulebooks">
          {(d) => <><p>Active track: <Badge tone="info">{d.active_track}</Badge></p>
            <DataTable rows={d.rows as unknown as R[]} columns={[{ key: "field", label: "Rule" }, { key: "competition", label: "Competition" }, { key: "open_market", label: "Open market" },
              { key: "differs", label: "", render: (r) => r.differs ? <Badge tone="warn">differs</Badge> : null }]} /></>}
        </Async>
      </Card>
      <Card title="Enforcement probes" subtitle="The same paper ticket checked against both tracks on throwaway engines.">
        <Async state={s} label="Loading probes">
          {(d) => <><DataTable rows={d.probes.map((p) => ({ id: p.id, why: p.why, comp: String(p.competition.decision ?? ""), open: String(p.open_market.decision ?? "") })) as R[]}
            columns={[{ key: "id", label: "Probe" }, { key: "comp", label: "Competition" }, { key: "open", label: "Open market" }, { key: "why", label: "What it tests" }]} />
            <p className="ux-muted">{d.note}</p></>}
        </Async>
      </Card>
    </div>
  );
}

/* ---------- Model evolution ---------- */
type EvoM = { status: string; reason?: string; fitness?: number; ev_r_per_opportunity?: number; brier_skill?: number; stability?: number;
  n_oos?: number; n_taken?: number; take_all_ev?: number; beats_baseline?: boolean; auc?: number | null;
  strict_gate?: { passed: boolean; failed: string[]; values?: Record<string, number | null> } };
type EvoRow = { genome_id: string; genome: Record<string, string>; generation: number; parent: string | null; mutation: string; metrics: EvoM };
type Evo = WithFresh & { run_id?: string; decision?: string; no_model_beats_baseline?: boolean; leaderboard?: EvoRow[];
  by_bar_type?: Record<string, { best_genome: string; fitness: number; ev: number; brier_skill: number }>;
  folds?: { fold: number; n_train: number; n_test: number; test_from: number; test_to: number }[]; data?: { n_rows?: number; series?: { instrument: string; interval: string; n_rows: number }[] };
  champion?: EvoRow | null; created_at?: number; no_model_passes_strict_gate?: boolean; gate_version?: string;
  strict_gate_rules?: { min_trades_per_fold: number; dsr_min: number; bonferroni_alpha: number };
  demoted?: { run_id: string; genome_id: string; status: string; reason?: string }[] };

export function EvolutionView() {
  const s = useApi<Evo>("/api/intel/evolution", 120000);
  return (
    <div className="ux-layout">
      <Card title="Model evolution" span="full" fresh={fr(s)}
        subtitle="Each genome is a model type, a feature set, a regime option and a bar type. All genomes use the same rows, the same purged walk-forward folds and real-price fills and costs. Fitness = out-of-sample R per opportunity after costs + Brier skill vs the base rate + a small stability term."
        footer={<>Run again (research only, nothing is promoted): <Command text="PYTHONPATH=src python scripts/evolve_models.py --generations 3" /></>}>
        <Async state={s} label="Loading evolution runs" isEmpty={(d) => d.status === "no_runs"} empty={<EmptyState title="No evolution run recorded yet">Run scripts/evolve_models.py.</EmptyState>}>
          {(d) => (<>
            <p>{d.no_model_beats_baseline
              ? <><Badge tone="warn">No model beats baseline</Badge> No genome had positive out-of-sample R per opportunity after costs together with positive Brier skill. The baseline is taking nothing (0 R); taking every setup averaged {f(d.leaderboard?.[0]?.metrics.take_all_ev)} R.</>
              : d.champion
                ? <><Badge tone="good">Research champion</Badge> {d.champion.genome_id}. It passed the strict gate. It is not promoted to trading; ML has no execution permission.</>
                : <><Badge tone="warn">No research champion</Badge> At least one genome beats the baseline, but none passes the strict gate. The gate needs at least {d.strict_gate_rules?.min_trades_per_fold ?? 20} trades in every fold, a positive result in most folds, DSR ≥ {d.strict_gate_rules?.dsr_min ?? 0.95}, and a Bonferroni p ≤ {d.strict_gate_rules?.bonferroni_alpha ?? 0.05} across every genome tried.</>}</p>
            {(d.demoted ?? []).map((x) => <p key={x.run_id} className="ux-muted"><Badge tone="warn">Demoted to research-only</Badge> Run {x.run_id} ({x.genome_id}): {x.reason}</p>)}
            <p className="ux-muted">Run {d.run_id} · {d.data?.n_rows ?? 0} out-of-sample rows from {(d.data?.series ?? []).map((x) => `${x.instrument} ${x.interval}`).join(", ")} · {d.folds?.length ?? 0} folds · decision: {d.decision}</p>
            <DataTable rows={(d.leaderboard ?? []).map((v, i) => ({ rank: i + 1, gen: v.generation, model: v.genome.model, feats: v.genome.features, reg: v.genome.regime,
                bar: v.genome.bar_type, st: v.metrics.status === "ok" ? "" : `${v.metrics.status}: ${v.metrics.reason ?? ""}`, fit: v.metrics.fitness, ev: v.metrics.ev_r_per_opportunity,
                bss: v.metrics.brier_skill, stab: v.metrics.stability, taken: v.metrics.n_taken, beats: v.metrics.beats_baseline ? "yes" : "no",
                gate: v.metrics.strict_gate ? (v.metrics.strict_gate.passed ? "pass" : `fail: ${v.metrics.strict_gate.failed.join(", ")}`) : "not run",
                parent: v.parent ? v.mutation : "seed" })) as R[]} columns={[
              { key: "rank", label: "#", align: "right" }, { key: "gen", label: "Gen", align: "right" }, { key: "model", label: "Model" }, { key: "feats", label: "Features" },
              { key: "reg", label: "Regime" }, { key: "bar", label: "Bar type" }, { key: "fit", label: "Fitness", align: "right", render: (r) => f(r.fit) },
              { key: "ev", label: "OOS R / opp.", align: "right", render: (r) => f(r.ev, 4) }, { key: "bss", label: "Brier skill", align: "right", render: (r) => f(r.bss, 4) },
              { key: "stab", label: "Stable folds", align: "right", render: (r) => f(r.stab, 2) }, { key: "taken", label: "Taken", align: "right" },
              { key: "beats", label: "Beats baseline" }, { key: "gate", label: "Strict gate" }, { key: "parent", label: "Lineage" }, { key: "st", label: "Status" }]} />
          </>)}
        </Async>
      </Card>
      <Card title="Best result per bar type" span={2} fresh={fr(s)} subtitle="Bar types only change features. Heikin-Ashi prices are never used for fills; tick bars are unavailable because the feed has no trade prints.">
        <Async state={s} label="Loading" isEmpty={(d) => !d.by_bar_type || !Object.keys(d.by_bar_type).length}>
          {(d) => <DataTable rows={Object.entries(d.by_bar_type ?? {}).map(([k, v]) => ({ k, g: v.best_genome.split("|")[0], fit: v.fitness, ev: v.ev, bss: v.brier_skill })) as R[]} columns={[
            { key: "k", label: "Bar type" }, { key: "g", label: "Best model" }, { key: "fit", label: "Fitness", align: "right", render: (r) => f(r.fit) },
            { key: "ev", label: "OOS R / opp.", align: "right", render: (r) => f(r.ev, 4) }, { key: "bss", label: "Brier skill", align: "right", render: (r) => f(r.bss, 4) }]} />}
        </Async>
      </Card>
      <Card title="Walk-forward folds" span={2} fresh={fr(s)} subtitle="Purged and embargoed by one day. Every genome is scored on exactly these test blocks.">
        <Async state={s} label="Loading" isEmpty={(d) => !d.folds?.length}>
          {(d) => <DataTable rows={(d.folds ?? []).map((x) => ({ k: x.fold, tr: x.n_train, te: x.n_test, from: ts(x.test_from), to: ts(x.test_to) })) as R[]} columns={[
            { key: "k", label: "Fold", align: "right" }, { key: "tr", label: "Train rows", align: "right" }, { key: "te", label: "Test rows", align: "right" },
            { key: "from", label: "Test from" }, { key: "to", label: "Test to" }]} />}
        </Async>
      </Card>
    </div>
  );
}
