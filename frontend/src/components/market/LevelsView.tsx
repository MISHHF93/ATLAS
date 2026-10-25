"use client";

import { Fragment, useEffect, useState } from "react";
import { Card, DataTable, EmptyState, ErrorState } from "../../ui/primitives";
import { AtlasChart } from "./AtlasChart";
import { TvProvenance } from "./TvProvenance";
import { FreshBadge, type Fresh } from "../../ui/FreshBadge";

export { FreshBadge };

type Level = { id: string; source_type: string; kind: string; price: number; available_ts: number; expires_ts: number | null; state: string; touch_count: number; label: string };
type LevelEvent = { level_id: string; event_id: string; kind: string; at: number; side: number; post_accept: boolean; extreme: number; detail: string };
type Zone = { zone_id: string; zone_type: string; lower_bound: number; upper_bound: number; formed_at: number; confirmed_at: number | null; expired_at: number | null; status: string };
type Cand = Record<string, unknown> & { candidate_id: string; detector: string; direction: string; detected_at: number; entry_reference: number; proposed_stop: number; proposed_target: number };
type Strategy = { id: string; family: string; scope: string; status: string; enabled: boolean; description: string };
type Payload = {
  instrument: string; calendar: string; gold_rules_applied: boolean; label: string; levels: Level[]; events: LevelEvent[]; zones: Zone[];
  candidates: Cand[]; no_trades: Record<string, unknown>[]; htf: Record<string, unknown>; strategies: Strategy[]; bars: number[][];
  bars_used: number; feed_origin: unknown; data_gaps: Record<string, string>; overlays?: Overlays;
};
type SEvent = { event_id: string; kind: string; direction: string; event_ts: number; confirmation_ts: number; reference_price: number };
type Win = { high: number; low: number; coverage: number; n: number; expected: number } | null;
type GoldDay = { day: string; asian: Win; early: Win; premarket_orb: Win; opening_orb: Win; orb_alignment?: { overlap_ratio: number } | null; insufficient?: string[] | null };
type Overlays = { freshness: Fresh; series: Record<string, number[][]>; structure: SEvent[];
  gold_sessions: { status: string; reason?: string; gap_policy?: string; days?: GoldDay[]; freshness?: Fresh }; provenance?: string };

const IND: Record<string, { label: string; color: string; keys: string[] }> = {
  sma: { label: "SMA 50 / 200", color: "#999999", keys: ["sma50", "sma200"] },
  trend: { label: "Trend band (EMA20 ± ATR)", color: "#009E73", keys: ["trend_upper", "trend_lower"] },
  donchian: { label: "Donchian 20", color: "#56B4E9", keys: ["donchian_upper", "donchian_lower"] },
  structure: { label: "Structure (BOS / CHoCH)", color: "#F0E442", keys: [] },
};


// Okabe-Ito colourblind-safe palette
const GROUPS: Record<string, { label: string; color: string; match: (s: string) => boolean }> = {
  prior: { label: "Prior day / week / month", color: "#0072B2", match: s => s.startsWith("prev_") },
  session: { label: "Session highs / lows", color: "#56B4E9", match: s => ["asia", "london", "ny"].some(p => s.startsWith(p)) },
  swing: { label: "Swing highs / lows", color: "#CC79A7", match: s => s === "swing" },
  equal: { label: "Equal highs / lows", color: "#F0E442", match: s => s.startsWith("equal") },
  box: { label: "Gold opening boxes", color: "#E69F00", match: s => s.startsWith("gold_box") || s === "box" },
};

export function LevelsView() {
  const [symbol, setSymbol] = useState("GC");
  const [resolution, setResolution] = useState("15");
  const [query, setQuery] = useState({ symbol: "GC", resolution: "15", n: 0 });
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [on, setOn] = useState<Record<string, boolean>>({ prior: true, session: false, swing: false, equal: false, box: true, sma: false, trend: false, donchian: false, structure: false });
  const [pick, setPick] = useState<Cand | null>(null);
  const tfq = query.resolution === "60" ? "1h" : `${query.resolution}m`;

  useEffect(() => {
    const q = new URLSearchParams({ symbol: query.symbol, resolution: query.resolution });
    let alive = true;
    setBusy(true); setError(null);
    fetch(`/api/quant/levels?${q}`).then(async r => (r.ok ? r.json() : Promise.reject(new Error((await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`))))
      .then((p: Payload) => { if (alive) { setData(p); setPick(null); } }).catch((e: Error) => { if (alive) { setData(null); setError(e.message); } })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [query]);

  const toggle = async (id: string, enabled: boolean) => {
    const r = await fetch(`/api/quant/strategies/${id}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }) });
    if (!r.ok) { setError(((await r.json().catch(() => null))?.detail as string) ?? `HTTP ${r.status}`); return; }
    setQuery(q => ({ ...q, n: q.n + 1 }));
  };


  const evs = pick ? data?.events.filter(e => JSON.stringify(pick).includes(`"${e.level_id}"`)) ?? [] : [];
  return (
    <div className="ux-layout">
      <Card title="Levels & sweeps" fresh={data?.overlays?.freshness ?? null} span="full" subtitle="Potential liquidity reference levels, how price interacted with them, and the setups that followed. Research only.">
        <form className="ux-form-row" onSubmit={e => { e.preventDefault(); setQuery({ symbol: symbol.trim() || "GC", resolution, n: query.n + 1 }); }}>
          <label className="ux-field" data-size="sm"><span>Symbol</span><input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} maxLength={20} /></label>
          <label className="ux-field" data-size="sm"><span>Bar size</span>
            <select value={resolution} onChange={e => setResolution(e.target.value)}>{["5", "15", "60"].map(r => <option key={r} value={r}>{r} min</option>)}</select>
          </label>
          <button type="submit" className="ux-btn" data-variant="primary" disabled={busy} aria-busy={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
        </form>
        <fieldset className="ux-chips"><legend className="ux-muted">Overlays</legend>
          {Object.entries(GROUPS).map(([k, g]) => (
            <label key={k} className="ux-chip"><input type="checkbox" checked={!!on[k]} onChange={e => setOn({ ...on, [k]: e.target.checked })} />
              <span className="ux-swatch" style={{ background: g.color }} aria-hidden /> {g.label}</label>
          ))}
          {Object.entries(IND).map(([k, g]) => (
            <label key={k} className="ux-chip"><input type="checkbox" checked={!!on[k]} onChange={e => setOn({ ...on, [k]: e.target.checked })} />
              <span className="ux-swatch" style={{ background: g.color }} aria-hidden /> {g.label}</label>
          ))}
        </fieldset>
        {error ? <ErrorState title="Could not load levels" detail={error} onRetry={() => setQuery({ ...query, n: query.n + 1 })} /> : null}
        {data ? (
          <p className="ux-muted">
            {data.bars_used} closed bars · calendar {data.calendar} · {data.levels.length} levels · {data.candidates.length} candidates · {data.no_trades.length} no-trade decisions ·
            daily bias: {String(data.htf?.bias ?? "insufficient")} · gold rules {data.gold_rules_applied ? "on (gold futures)" : "off"} · order flow: {data.data_gaps?.order_flow}.
            {" "}Lines start when each level became knowable. Candidates are proposals (execution permission: none), not trades.
          </p>
        ) : null}
        {data && !data.bars?.length ? <EmptyState title="No confirmed bars for this symbol">Try another symbol or bar size.</EmptyState> : null}
        {data?.bars?.length ? <p className="ux-muted"><TvProvenance kind="atlas" /> {data.label} · feed: {String(data.feed_origin ?? "unknown")} · data: <FreshBadge f={data.overlays?.freshness} /></p> : null}
        {/* chart-2: the one ATLAS chart for this symbol (levels/markers/predictions come from the shared overlay engine) */}
        <AtlasChart symbol={query.symbol} timeframe={tfq} height={400} showPanel={false} />
      </Card>
      <Card title="Gold session ranges" fresh={data?.overlays?.gold_sessions?.freshness ?? null} subtitle="Asian, early, 08:00 and 08:20 New York boxes from 1-minute feed bars. Gold futures only.">
        {data?.overlays?.gold_sessions?.days?.length ? (
          <>
            <p className="ux-muted">Data: <FreshBadge f={data.overlays.gold_sessions.freshness} /> · {data.overlays.gold_sessions.gap_policy}</p>
            <DataTable rows={data.overlays.gold_sessions.days.map(d => ({
              day: d.day,
              ...Object.fromEntries((["asian", "early", "premarket_orb", "opening_orb"] as const).map(w => [w, d[w] ? `${d[w]!.low.toFixed(1)}–${d[w]!.high.toFixed(1)} (${Math.round(d[w]!.coverage * 100)}%)` : "not enough data"])),
              overlap: d.orb_alignment ? d.orb_alignment.overlap_ratio.toFixed(2) : "—",
            })) as unknown as Record<string, unknown>[]} columns={[
              { key: "day", label: "Day (NY)" }, { key: "asian", label: "Asian" }, { key: "early", label: "Early" },
              { key: "premarket_orb", label: "08:00 box" }, { key: "opening_orb", label: "08:20 box" }, { key: "overlap", label: "Box overlap", align: "right" },
            ]} />
          </>
        ) : <EmptyState title={data?.overlays?.gold_sessions?.status === "NOT_APPLICABLE" ? "Not a gold symbol" : "No session data"}>{data?.overlays?.gold_sessions?.reason ?? "Load GC to see gold sessions."}</EmptyState>}
      </Card>
      <Card title="Strategies" subtitle="Choose which techniques run. Switching one on never lets it place an order.">
        {data?.strategies?.length ? (
          <ul className="ux-list">
            {data.strategies.map(s => (
              <li key={s.id}>
                <label className="ux-chip">
                  <input type="checkbox" checked={s.enabled} disabled={s.status !== "implemented"} onChange={e => void toggle(s.id, e.target.checked)} />
                  {" "}{s.description} <span className="ux-muted">({s.scope}{s.status !== "implemented" ? ", not built yet" : ""})</span>
                </label>
              </li>
            ))}
          </ul>
        ) : <EmptyState title="No strategy list">Load a symbol first.</EmptyState>}
      </Card>
      <Card title="Candidates" fresh={data?.overlays?.freshness ?? null} subtitle="Pick a row to inspect it.">
        {data?.candidates.length ? (
          <DataTable rows={data.candidates} columns={[
            { key: "candidate_id", label: "", render: r => <button type="button" className="ux-btn" data-size="sm" onClick={() => setPick(r as Cand)}>Inspect</button> },
            { key: "detector", label: "Technique" }, { key: "direction", label: "Side" },
            { key: "entry_reference", label: "Entry ref", align: "right" }, { key: "proposed_stop", label: "Stop", align: "right" },
            { key: "proposed_target", label: "Target", align: "right" },
          ]} />
        ) : <EmptyState title="No candidates">None qualified, or the technique is switched off.</EmptyState>}
      </Card>
      <Card title="Inspect" fresh={data?.overlays?.freshness ?? null} span="full" subtitle="What was observed, what was inferred, and what could not be checked.">
        {pick ? (
          <>
            <dl className="ux-dl">{Object.entries(pick).filter(([, v]) => typeof v !== "object").map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></Fragment>)}</dl>
            <pre className="ux-pre" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(pick.feature_snapshot ?? {}, null, 1)}</pre>
            {evs.length ? <DataTable rows={evs as unknown as Record<string, unknown>[]} columns={[{ key: "kind", label: "Event" }, { key: "at", label: "Bar end (unix)" }, { key: "extreme", label: "Extreme", align: "right" }, { key: "detail", label: "Detail" }]} /> : null}
          </>
        ) : <EmptyState title="Nothing selected">Pick a candidate.</EmptyState>}
      </Card>
      <Card title="No-trade decisions" fresh={data?.overlays?.freshness ?? null} span="full" subtitle="Most recent 50, with the reason each setup was refused.">
        {data?.no_trades.length ? <DataTable rows={data.no_trades.slice(-50)} maxHeight={320} columns={Object.keys(data.no_trades[0]).slice(0, 6).map(k => ({ key: k, label: k.replace(/_/g, " "), render: (r: Record<string, unknown>) => typeof r[k] === "object" ? JSON.stringify(r[k]) : String(r[k] ?? "—") }))} />
          : <EmptyState title="No refusals">Nothing was refused on these bars.</EmptyState>}
      </Card>
    </div>
  );
}
