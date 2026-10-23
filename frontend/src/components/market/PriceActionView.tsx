"use client";

import { useEffect, useRef, useState } from "react";
import { ColorType, createChart, LineStyle, type IChartApi, type SeriesMarker, type UTCTimestamp } from "lightweight-charts";
import { deskTimeOptions, freshness } from "./lwTime";
import { TvProvenance } from "./TvFrame";

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
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [on, setOn] = useState<Record<string, boolean>>({ opening_range: true, dual_band_breakout: false, wick_reversal: false });
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = new URLSearchParams({ symbol, resolution, session });
    setError(null);
    fetch(`/api/quant/setups?${q}`).then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p: Payload) => setData(p)).catch((e: Error) => { setData(null); setError(e.message); });
  }, [symbol, resolution, session]);

  useEffect(() => {
    if (!box.current || !data?.bars?.length) return;
    const element = box.current;
    const chart: IChartApi = createChart(element, {
      ...deskTimeOptions,
      width: Math.max(1, element.clientWidth),
      height: 360,
      layout: { attributionLogo: true, textColor: "#CBD5E1", background: { type: ColorType.Solid, color: "#0B0F17" } },
      grid: { vertLines: { color: "#182431" }, horzLines: { color: "#182431" } },
    });
    // Okabe-Ito bluish green / vermillion for up / down
    const candles = chart.addCandlestickSeries({ upColor: "#009E73", downColor: "#D55E00", borderVisible: false, wickUpColor: "#009E73", wickDownColor: "#D55E00" });
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
    // Setup candidates exactly as the backend detector emitted them (detected_at is a bar time).
    const barTimes = new Set(bars.map(r => r[0]));
    const markers: SeriesMarker<UTCTimestamp>[] = data.candidates
      .filter(c => barTimes.has(c.detected_at))
      .map(c => ({
        time: c.detected_at as UTCTimestamp,
        position: c.direction === "short" ? "aboveBar" : "belowBar",
        shape: c.direction === "short" ? "arrowDown" : "arrowUp",
        color: c.direction === "short" ? "#D55E00" : "#009E73",
        text: c.candidate_id.split(":").slice(-1)[0]?.slice(0, 12) ?? "setup",
      }));
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    candles.setMarkers(markers);
    const latest = data.candidates[data.candidates.length - 1];
    if (latest) {
      candles.createPriceLine({ price: latest.entry_reference, title: "entry ref", color: "#56B4E9", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true });
      candles.createPriceLine({ price: latest.proposed_stop, title: "proposed stop", color: "#D55E00", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true });
      candles.createPriceLine({ price: latest.proposed_target, title: "proposed target", color: "#009E73", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true });
    }
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(() => chart.applyOptions({ width: Math.max(1, element.clientWidth) }));
    observer.observe(element);
    return () => { observer.disconnect(); chart.remove(); };
  }, [data, on]);

  return (
    <section style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input aria-label="Symbol" value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} style={{ width: 110 }} />
        <select aria-label="Resolution" value={resolution} onChange={e => setResolution(e.target.value)}>
          {["5", "15", "60"].map(r => <option key={r} value={r}>{r}m</option>)}
        </select>
        <select aria-label="Session" value={session} onChange={e => setSession(e.target.value)}>
          {["us_equity_rth", "london_cash", "tokyo_cash"].map(s => <option key={s}>{s}</option>)}
        </select>
        {OVERLAYS.map(k => (
          <label key={k} style={{ color: COLORS[k] }}>
            <input type="checkbox" checked={!!on[k]} onChange={e => setOn({ ...on, [k]: e.target.checked })} /> {k.replace(/_/g, " ")}
          </label>
        ))}
      </div>
      {error && <p role="alert">Could not load setups: {error}</p>}
      {data && (() => {
        const last = data.bars?.length ? data.bars[data.bars.length - 1][0] : null;
        const fresh = freshness(last, Number(resolution) * 60);
        return (
          <p data-freshness={fresh.stale ? "stale" : "fresh"} style={{ margin: 0, fontSize: 12, color: fresh.stale ? "#E69F00" : "var(--text-secondary)" }}>
            <TvProvenance kind="atlas" /> Same confirmed bars the detectors read (/api/quant/setups) · {fresh.label}{fresh.stale ? " · stale" : ""}
          </p>
        );
      })()}
      {data && (
        <p style={{ color: "var(--text-secondary)" }}>
          {data.bars_used ?? 0} closed bars · feed: {String(data.feed_origin ?? "unknown")} · {data.zones.length} zones · {data.candidates.length} setup candidates
          {data.note ? ` · ${data.note}` : ""}. Candidates are proposals for the control plane (execution permission: none), not trades.
        </p>
      )}
      <div ref={box} style={{ width: "100%", minHeight: 360 }} />
      <p style={{ margin: 0, fontSize: 11, color: "#64748B" }}>
        Chart rendering: <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a> (Apache-2.0). Data: ATLAS, not TradingView. Times America/Toronto.
      </p>
      {data && data.candidates.length > 0 && (
        <table>
          <thead><tr><th>Candidate</th><th>Side</th><th>Entry ref</th><th>Proposed stop</th><th>Proposed target</th><th>Invalidation</th></tr></thead>
          <tbody>{data.candidates.map(c => (
            <tr key={c.candidate_id}><td>{c.candidate_id}</td><td>{c.direction}</td><td>{c.entry_reference}</td><td>{c.proposed_stop}</td><td>{c.proposed_target}</td><td>{c.invalidation_level}</td></tr>
          ))}</tbody>
        </table>
      )}
      {data && data.zones.length > 0 && (
        <table>
          <thead><tr><th>Zone</th><th>Type</th><th>Dir</th><th>Lower</th><th>Upper</th><th>Status</th><th>Touches</th></tr></thead>
          <tbody>{data.zones.filter(z => on[z.zone_type]).slice(-30).map(z => (
            <tr key={z.zone_id}><td>{z.zone_id}</td><td>{z.zone_type}</td><td>{z.direction}</td><td>{z.lower_bound.toFixed(4)}</td><td>{z.upper_bound.toFixed(4)}</td><td>{z.status}</td><td>{z.touch_count}</td></tr>
          ))}</tbody>
        </table>
      )}
    </section>
  );
}
