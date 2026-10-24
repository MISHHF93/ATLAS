"use client";
/** Pass-5 intelligence views: research lab, regimes, memory & governance, grounded assistant, microstructure, Four-Box,
 *  portfolio risk and track rulebooks. All read-only research surfaces: execution_permission is "none" everywhere and
 *  only the deterministic control plane can approve or size an order. Every card shows the payload's freshness label. */
import { useState } from "react";
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
  variants: Record<string, { n_trades: number; mean_r: number | null; win_rate: number | null; bootstrap_mean_r?: { lo: number; hi: number; p_mean_le_0: number } | null;
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
  const rows = Object.entries(run.variants).map(([v, s]) => ({ v, n: s.n_trades, mean: s.mean_r, win: s.win_rate,
    ci: s.bootstrap_mean_r ? `${f(s.bootstrap_mean_r.lo)} … ${f(s.bootstrap_mean_r.hi)}` : "too few trades",
    p0: s.bootstrap_mean_r?.p_mean_le_0, ...Object.fromEntries(s.cost_sensitivity.map((c) => [`c${c.cost_mult}`, c.mean_r])) }));
  return (
    <Card title={`Report ${run.report_id}`} span="full" fresh={fresh}
      subtitle={`Seed ${run.seed}. DSR deflates the best variant's Sharpe for ${run.deflated_sharpe?.n_trials ?? "—"} trials; PBO is the probability the in-sample winner underperforms out of sample (${run.pbo?.n_combinations ?? 0} splits). ${run.pbo_note ?? ""}`}>
      <DataTable rows={rows as R[]} columns={[
        { key: "v", label: "Variant" }, { key: "n", label: "Trades", align: "right" },
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
            {d.book.unpriced_positions.length ? <p>Unpriced: {d.book.unpriced_positions.join(", ")}. VaR for the book is not computed.</p> : null}
            <p>VaR95 ${f(d.book.var95_usd, 0)} · CVaR95 ${f(d.book.cvar95_usd, 0)} · VaR99 ${f(d.book.var99_usd, 0)}</p>
            <p className="ux-muted">{d.positions_source}</p>
            <DataTable rows={d.positions} columns={[{ key: "position_id", label: "Position" }, { key: "track", label: "Track" }, { key: "instrument_id", label: "Instrument" },
              { key: "side", label: "Side" }, { key: "notional_usd", label: "Notional", align: "right" }]} /></>}
        </Async>
      </Card>
      <Card title="Stress" fresh={fr(s)} subtitle="Historical worst days and labelled hypothetical shocks.">
        <Async state={s} label="Loading stress">
          {(d) => <DataTable rows={d.book.stress as unknown as R[]} columns={[{ key: "scenario", label: "Scenario" }, { key: "kind", label: "Kind" },
            { key: "pnl_usd", label: "P&L $", align: "right", render: (r) => f(r.pnl_usd, 0) }]} />}
        </Async>
      </Card>
      <Card title="Per-instrument tail risk (per $10k long)" span="full" fresh={fr(s)}>
        <Async state={s} label="Loading instruments">
          {(d) => <DataTable rows={d.per_instrument} columns={[{ key: "symbol", label: "Symbol" }, { key: "asset_class", label: "Class" }, { key: "n_days", label: "Days", align: "right" },
            { key: "var95_per_10k", label: "VaR95", align: "right", render: (r) => f(r.var95_per_10k, 0) }, { key: "cvar95_per_10k", label: "CVaR95", align: "right", render: (r) => f(r.cvar95_per_10k, 0) },
            { key: "var99_per_10k", label: "VaR99", align: "right", render: (r) => f(r.var99_per_10k, 0) }, { key: "worst_day_pct", label: "Worst day %", align: "right", render: (r) => f(r.worst_day_pct, 2) }]} />}
        </Async>
      </Card>
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

export function TracksView() {
  const s = useApi<Tracks>("/api/intel/tracks", 120000);
  return (
    <div className="ux-layout">
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
