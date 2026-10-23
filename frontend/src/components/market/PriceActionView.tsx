"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { Card, DataTable, EmptyState, ErrorState } from "../../ui/primitives";
import { createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";

type Zone = {
  zone_id: string; zone_type: string; direction: string; lower_bound: number; upper_bound: number;
  formed_at: number; confirmed_at: number | null; invalidated_at: number | null; expired_at: number | null;
  status: string; touch_count: number;
};
type Candidate = { candidate_id: string; direction: string; detected_at: number; entry_reference: number; proposed_stop: number; proposed_target: number; invalidation_level: number };
type Payload = { zones: Zone[]; candidates: Candidate[]; bars?: number[][]; bars_used?: number; feed_origin?: unknown; note?: string; proposals?: unknown[] };

const OVERLAYS = ["opening_range", "dual_band_breakout", "wick_reversal"] as const;
// Okabe-Ito colourblind-safe palette
const COLORS: Record<string, string> = { opening_range: "#0072B2", dual_band_breakout: "#E69F00", wick_reversal: "#CC79A7" };

export function PriceActionView() {
  const [symbol, setSymbol] = useState("SPY");
  const [resolution, setResolution] = useState("60");
  const [session, setSession] = useState("us_equity_rth");
  const [query, setQuery] = useState({ symbol: "SPY", resolution: "60", session: "us_equity_rth", n: 0 });
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [on, setOn] = useState<Record<string, boolean>>({ opening_range: true, dual_band_breakout: false, wick_reversal: false });
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = new URLSearchParams({ symbol: query.symbol, resolution: query.resolution, session: query.session });
    setError(null); setBusy(true);
    let alive = true;
    fetch(`/api/quant/setups?${q}`).then(async r => (r.ok ? r.json() : Promise.reject(new Error((await r.json().catch(() => null))?.detail ?? `HTTP ${r.status}`))))
      .then((p: Payload) => { if (alive) setData(p); }).catch((e: Error) => { if (alive) { setData(null); setError(e.message); } })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [query]);

  useEffect(() => {
    if (!box.current || !data?.bars?.length) return;
    const css = getComputedStyle(document.documentElement);
    const chart: IChartApi = createChart(box.current, { autoSize: true, layout: { textColor: css.getPropertyValue("--c-muted").trim() || "#98A3B3", background: { color: "transparent" } },
      grid: { vertLines: { color: "rgba(128,128,128,.12)" }, horzLines: { color: "rgba(128,128,128,.12)" } } });
    const candles = chart.addCandlestickSeries({ upColor: "#009E73", downColor: "#D55E00", wickUpColor: "#009E73", wickDownColor: "#D55E00", borderVisible: false });
    const bars = data.bars;
    candles.setData(bars.map(r => ({ time: r[0] as UTCTimestamp, open: r[1], high: r[2], low: r[3], close: r[4] })));
    const lastT = bars[bars.length - 1][0];
    for (const z of data.zones) {
      if (!on[z.zone_type]) continue;
      const start = z.formed_at;
      const end = z.invalidated_at ?? z.expired_at ?? lastT;
      const pts = bars.filter(r => r[0] >= start && r[0] <= end).map(r => r[0] as UTCTimestamp);
      if (pts.length < 1) continue;
      for (const level of [z.upper_bound, z.lower_bound]) {
        const s = chart.addLineSeries({ color: COLORS[z.zone_type] ?? "#999", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        s.setData(pts.map(t => ({ time: t, value: level })));
      }
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, on]);

  const zones = data ? data.zones.filter(z => on[z.zone_type]).slice(-30) : [];
  return (
    <div className="ux-layout">
      <Card title="Analyze" span="full" subtitle="Pick a symbol, bar size and session, then run the backend analysis on confirmed bars.">
        <form className="ux-form-row" onSubmit={e => { e.preventDefault(); setQuery({ symbol: symbol.trim() || "SPY", resolution, session, n: query.n + 1 }); }}>
          <label className="ux-field" data-size="sm"><span>Symbol</span><input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} maxLength={20} /></label>
          <label className="ux-field" data-size="sm"><span>Bar size</span>
            <select value={resolution} onChange={e => setResolution(e.target.value)}>{["5", "15", "60"].map(r => <option key={r} value={r}>{r} min</option>)}</select>
          </label>
          <label className="ux-field"><span>Session</span>
            <select value={session} onChange={e => setSession(e.target.value)}>{["us_equity_rth", "london_cash", "tokyo_cash"].map(s => <option key={s}>{s}</option>)}</select>
          </label>
          <button type="submit" className="ux-btn" data-variant="primary" disabled={busy} aria-busy={busy}>{busy ? "Analyzing…" : "Analyze"}</button>
        </form>
        <fieldset className="ux-chips"><legend className="ux-muted">Overlays</legend>
          {OVERLAYS.map(k => (
            <label key={k} className="ux-chip"><input type="checkbox" checked={!!on[k]} onChange={e => setOn({ ...on, [k]: e.target.checked })} />
              <span className="ux-swatch" style={{ background: COLORS[k] }} aria-hidden /> {k.replace(/_/g, " ")}</label>
          ))}
        </fieldset>
        {error ? <ErrorState title="Could not load setups" detail={error} onRetry={() => setQuery({ ...query, n: query.n + 1 })} /> : null}
        {data ? (
          <p className="ux-muted">
            {data.bars_used ?? 0} closed bars · feed: {String(data.feed_origin ?? "unknown")} · {data.zones.length} zones · {data.candidates.length} setup candidates
            {data.note ? ` · ${data.note}` : ""}. Candidates are proposals for the control plane (execution permission: none), not trades.
          </p>
        ) : null}
        {data && !data.bars?.length ? <EmptyState title="No confirmed bars for this symbol">Try another symbol or bar size.</EmptyState> : null}
        <div ref={box} className="ux-chart" hidden={!data?.bars?.length} />
      </Card>
      <Card title="Setup candidates" subtitle="Detected patterns awaiting the control plane.">
        {data?.candidates.length ? (
          <DataTable rows={data.candidates as unknown as Record<string, unknown>[]} columns={[
            { key: "candidate_id", label: "Candidate" }, { key: "direction", label: "Side" },
            { key: "entry_reference", label: "Entry ref", align: "right" }, { key: "proposed_stop", label: "Stop", align: "right" },
            { key: "proposed_target", label: "Target", align: "right" }, { key: "invalidation_level", label: "Invalidation", align: "right" },
          ]} />
        ) : <EmptyState title="No candidates">Nothing qualifies on these bars.</EmptyState>}
      </Card>
      <Card title="Zones" subtitle="Most recent 30 for the selected overlays.">
        {zones.length ? (
          <DataTable rows={zones as unknown as Record<string, unknown>[]} columns={[
            { key: "zone_type", label: "Type", render: r => String(r.zone_type).replace(/_/g, " ") }, { key: "direction", label: "Dir" },
            { key: "lower_bound", label: "Lower", align: "right", render: r => Number(r.lower_bound).toFixed(4) },
            { key: "upper_bound", label: "Upper", align: "right", render: r => Number(r.upper_bound).toFixed(4) },
            { key: "status", label: "Status" }, { key: "touch_count", label: "Touches", align: "right" },
          ]} />
        ) : <EmptyState title="No zones">Turn on an overlay or analyze another symbol.</EmptyState>}
      </Card>
      <ReplayPanel symbol={query.symbol} resolution={query.resolution} session={query.session} />
    </div>
  );
}

type Replay = Record<string, unknown> & { trades?: Record<string, unknown>[]; note?: string; feed_origin?: unknown };

function ReplayPanel(props: { symbol: string; resolution: string; session: string }) {
  const [cost, setCost] = useState(0);
  const [hold, setHold] = useState(8);
  const [res, setRes] = useState<Replay | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr("");
    const q = new URLSearchParams({ symbol: props.symbol, resolution: props.resolution, session: props.session, cost_per_unit: String(cost), max_hold_bars: String(hold) });
    try {
      const r = await fetch(`/api/quant/replay?${q}`);
      const j = await r.json().catch(() => null);
      if (!r.ok) throw new Error(j?.detail ? String(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : `HTTP ${r.status}`);
      setRes(j);
    } catch (e) { setRes(null); setErr((e as Error).message); } finally { setBusy(false); }
  };
  const summary = res ? Object.entries(res).filter(([, v]) => typeof v === "number" || typeof v === "string").slice(0, 14) : [];
  const trades = res?.trades ?? [];
  return (
    <Card title={`Paper replay · ${props.symbol}`} span="full" subtitle="Conservative OHLC replay of the live detection path on confirmed bars. Descriptive only, not a performance estimate.">
      <form className="ux-form-row" onSubmit={e => { e.preventDefault(); void run(); }}>
        <label className="ux-field" data-size="sm"><span>Cost per unit</span><input type="number" step="0.01" min={0} value={cost} onChange={e => setCost(Math.max(0, Number(e.target.value) || 0))} /></label>
        <label className="ux-field" data-size="sm"><span>Max hold (bars)</span><input type="number" min={1} max={500} value={hold} onChange={e => setHold(Math.min(500, Math.max(1, Number(e.target.value) || 8)))} /></label>
        <button type="submit" className="ux-btn" data-variant="primary" disabled={busy} aria-busy={busy}>{busy ? "Running…" : "Run replay"}</button>
      </form>
      {err ? <ErrorState title="Replay failed" detail={err} onRetry={run} /> : null}
      {res ? (
        <>
          <dl className="ux-dl">{summary.map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{typeof v === "number" && !Number.isInteger(v) ? v.toFixed(4) : String(v)}</dd></Fragment>)}</dl>
          {trades.length ? <DataTable rows={trades.slice(-50)} maxHeight={360} columns={Object.keys(trades[0]).slice(0, 8).map(k => ({
            key: k, label: k.replace(/_/g, " "), render: (r: Record<string, unknown>) => typeof r[k] === "number" ? (Number.isInteger(r[k]) ? String(r[k]) : (r[k] as number).toFixed(4)) : typeof r[k] === "object" ? JSON.stringify(r[k]) : String(r[k] ?? "—"),
          }))} /> : <EmptyState title="No replay trades">No setup on these bars reached an entry.</EmptyState>}
        </>
      ) : !err ? <p className="ux-muted">Not run yet.</p> : null}
    </Card>
  );
}
