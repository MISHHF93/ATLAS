"use client";
/** ATLAS chart: the one primary chart on every surface. Real feed bars (free providers only) drawn with
 *  TradingView Lightweight Charts (Apache-2.0), plus every ATLAS research layer from ONE read-only endpoint,
 *  /api/ai/chart/overlays. Each layer reports its own status; nothing is drawn that ATLAS did not compute.
 *  Paper only. ML execution_permission is "none": markers and probabilities are research, never orders. */
import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, type IChartApi, type ISeriesApi, type IPriceLine, type UTCTimestamp, LineStyle } from "lightweight-charts";
import { deskTimeOptions } from "./lwTime";
import { MARKER_CLASSES, altToCandles, attachMarkerTooltip, toSeriesMarkers, type OppMarker } from "./opportunityMarkers";

export const CHART_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
export type ChartInterval = (typeof CHART_INTERVALS)[number];
export const CHART_BAR_TYPES = [
  { id: "time", label: "Time" }, { id: "heikin_ashi", label: "Heikin-Ashi" }, { id: "renko_atr", label: "Renko" },
  { id: "range_atr", label: "Range" }, { id: "volume", label: "Volume" }, { id: "dollar", label: "Dollar" },
  { id: "tick", label: "Tick" }, { id: "kagi_atr", label: "Kagi" }, { id: "pnf_atr", label: "Point & Figure" },
] as const;
const LAYERS = [
  { id: "ml_markers", label: "ML buy/sell" }, { id: "ml_probability", label: "ML probability" },
  { id: "setups", label: "Setups" }, { id: "zones", label: "Zones" }, { id: "vwap", label: "VWAP" },
  { id: "volume_profile", label: "Volume profile" }, { id: "regimes", label: "Regime" },
  { id: "conviction", label: "Conviction" }, { id: "predictions", label: "Predictions" },
] as const;
type LayerId = (typeof LAYERS)[number]["id"];
const DUR: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const ZONE_COLORS: Record<string, string> = { sr: "#56B4E9", fourbox: "#CC79A7", orb: "#E69F00", prior_day: "#98A3B3" };
const REGIME_COLORS: Record<string, string> = { up: "rgba(46,184,138,0.10)", down: "rgba(240,128,60,0.10)", range: "rgba(152,163,179,0.06)" };

type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };
type Status = { status: string; reason?: string; note?: string };
export type Overlays = {
  status: string; symbol: string; interval: string; bar_type: string; execution_permission: string;
  provider: { provider: string | null; providers: string[]; realtime: boolean | null; delay_s?: number | null; delay_label: string; built: string };
  bars: Bar[];
  display?: Status & { kind: string; bars?: { time: number; start: number; open: number; high: number; low: number; close: number }[] };
  layers: {
    ml_markers?: Status & { items: OppMarker[] }; setups?: Status & { items: OppMarker[]; classes?: Record<string, { count: number; note: string }> };
    ml_probability?: Status & { points: { time: number; value: number; take: boolean }[] };
    zones?: Status & { items: { kind: string; label: string; low: number; high: number; from: number }[]; notes?: string[] };
    vwap?: Status & { points: { time: number; value: number }[] };
    volume_profile?: Status & { bins: { low: number; high: number; volume: number }[]; poc: number; window_bars: number };
    regimes?: Status & { spans: { from: number; to: number; trend: string; label: string }[]; current: string | null };
    conviction?: Status & { score?: number; label?: string; components?: { rule: string; points: number; why: string }[]; personas?: string };
    predictions?: Status & { items: { time: number; p: number; take: boolean; outcome: string; calibrator: string }[];
      calibration: { brier: number; brier_baseline: number; ece: number; auc: number } | null };
  };
  ml_panel: null | {
    execution_permission: string;
    evolution: null | { run_id: string; created_at: number; decision: string; no_model_beats_baseline: boolean; challenger: string;
      metrics: Record<string, number | boolean | null> };
    champion: null | Record<string, unknown>;
    current_model: null | { version: string; status: string; calibrator: string; brier: number; brier_baseline: number; auc: number; ece: number };
    why: { id: string; time: number; class: OppMarker["class"]; strategy: string; direction: string; probability: string; ev_r: number | null; risk: string; model: string }[];
  };
};

/** Desk symbols (BTC-USD, 1D) -> feed symbols (BTCUSDT, 1d). */
export function chartSymbol(s: string) { const u = s.toUpperCase(); return u.endsWith("-USD") ? `${u.slice(0, -4)}USDT` : u.replace(/^[A-Z]+:/, ""); }
export function chartInterval(tf: string): ChartInterval {
  const t = tf.toLowerCase(); return (CHART_INTERVALS as readonly string[]).includes(t) ? (t as ChartInterval) : t === "1s" ? "1m" : "15m";
}
export function tradingViewUrl(sym: string) {
  const s = chartSymbol(sym);
  const tv = s.endsWith("USDT") ? `BINANCE:${s}` : s.includes("=") ? s.replace("=F", "1!") : s;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tv)}`;
}

function useOverlays(symbol: string, interval: string, barType: string) {
  const [d, setD] = useState<Overlays | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true); setErr(null);
    fetch(`/api/ai/chart/overlays?symbol=${encodeURIComponent(symbol)}&interval=${interval}&bar_type=${barType}&limit=600`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p: Overlays) => { if (alive) setD(p); })
      .catch((e: Error) => { if (alive) { setD(null); setErr(e.message); } })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [symbol, interval, barType]);
  return { data: d, error: err, loading };
}

const fmt = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");

export function AtlasChart({ symbol, timeframe = "15m", height = 460, showPanel = true, allLayers = false }: {
  symbol: string; timeframe?: string; height?: number; showPanel?: boolean; allLayers?: boolean;
}) {
  const sym = chartSymbol(symbol);
  const [interval, setInterval_] = useState<ChartInterval>(chartInterval(timeframe));
  useEffect(() => setInterval_(chartInterval(timeframe)), [timeframe]);
  const [barType, setBarType] = useState("time");
  const [on, setOn] = useState<Record<LayerId, boolean>>(() => Object.fromEntries(LAYERS.map((l) => [l.id,
    allLayers || ["ml_markers", "setups", "zones", "vwap"].includes(l.id)])) as Record<LayerId, boolean>);
  const { data, error, loading } = useOverlays(sym, interval, barType);
  const box = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const markersRef = useRef<OppMarker[]>([]);

  const visibleMarkers = useMemo(() => {
    if (!data) return [] as OppMarker[];
    const out: OppMarker[] = [];
    if (on.ml_markers) out.push(...(data.layers.ml_markers?.items ?? []));
    if (on.setups) out.push(...(data.layers.setups?.items ?? []));
    return out;
  }, [data, on.ml_markers, on.setups]);

  useEffect(() => {
    const el = box.current;
    if (!el || !data || !data.bars.length) return;
    const css = getComputedStyle(el);
    const text = css.getPropertyValue("--c-muted").trim() || "#98A3B3";
    const grid = css.getPropertyValue("--c-border").trim() || "#27303D";
    const chart = createChart(el, { ...deskTimeOptions, height, autoSize: true,
      layout: { ...deskTimeOptions.layout, background: { color: "transparent" }, textColor: text, fontSize: 11 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } }, rightPriceScale: { borderColor: grid },
      timeScale: { ...deskTimeOptions.timeScale, borderColor: grid } });
    chartRef.current = chart;
    const probOn = on.ml_probability && !!data.layers.ml_probability?.points.length;
    const bottom = probOn ? 0.3 : 0.12;
    const dur = DUR[data.interval] ?? 900;
    // regime shading: full-height histogram on its own hidden scale
    if (on.regimes && data.layers.regimes?.spans.length) {
      const rg = chart.addHistogramSeries({ priceScaleId: "regime", lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("regime").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      const pts: { time: UTCTimestamp; value: number; color: string }[] = [];
      for (const s of data.layers.regimes.spans) for (const b of data.bars) if (b.time >= s.from && b.time <= s.to)
        pts.push({ time: b.time as UTCTimestamp, value: 1, color: REGIME_COLORS[s.trend] ?? "transparent" });
      rg.setData(pts);
    }
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 1 - bottom - 0.1, bottom }, visible: false });
    vol.setData(data.bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "rgba(46,184,138,0.35)" : "rgba(240,128,60,0.35)" })));
    const candles: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({ upColor: "#2EB88A", downColor: "#F0803C", borderVisible: false,
      wickUpColor: "#2EB88A", wickDownColor: "#F0803C" });
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.06, bottom: bottom + 0.02 } });
    const alt = data.display?.kind !== "time" && data.display?.status === "ok" && data.display.bars?.length
      ? altToCandles(data.display.bars.map((a) => ({ ...a, completed_at: a.time })), dur) : null;
    candles.setData(alt ?? data.bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    const times = new Set((alt ?? data.bars).map((b) => b.time as number));
    markersRef.current = visibleMarkers;
    candles.setMarkers(toSeriesMarkers(visibleMarkers, times, {}));
    if (on.vwap && data.layers.vwap?.points.length) {
      const vw = chart.addLineSeries({ color: "#F0E442", lineWidth: 1, lastValueVisible: false, priceLineVisible: false, title: "VWAP" });
      vw.setData(data.layers.vwap.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    }
    const lines: IPriceLine[] = [];
    if (on.zones) for (const z of data.layers.zones?.items ?? []) {
      const color = ZONE_COLORS[z.kind] ?? "#98A3B3";
      lines.push(candles.createPriceLine({ price: z.high, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: z.label }));
      if (z.low !== z.high) lines.push(candles.createPriceLine({ price: z.low, color, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" }));
    }
    if (probOn) {
      const pr = chart.addLineSeries({ priceScaleId: "left", color: "#56B4E9", lineWidth: 1, pointMarkersVisible: true, lastValueVisible: true,
        priceLineVisible: false, title: "ML p(win)" });
      chart.priceScale("left").applyOptions({ scaleMargins: { top: 0.74, bottom: 0.02 }, visible: true, borderColor: grid });
      pr.setData(data.layers.ml_probability!.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value, color: p.take ? "#0072B2" : "#98A3B3" })));
    }
    const detach = attachMarkerTooltip(chart, el, () => markersRef.current);
    const drawProfile = () => {
      const pf = profileRef.current;
      if (!pf) return;
      pf.innerHTML = "";
      const vp = data.layers.volume_profile;
      if (!on.volume_profile || !vp || vp.status !== "ok") return;
      const max = Math.max(...vp.bins.map((b) => b.volume), 1);
      for (const b of vp.bins) {
        const y1 = candles.priceToCoordinate(b.high), y2 = candles.priceToCoordinate(b.low);
        if (y1 == null || y2 == null) continue;
        const d = document.createElement("div");
        d.className = "atlas-chart-vp-bin";
        d.style.top = `${y1}px`; d.style.height = `${Math.max(1, y2 - y1 - 1)}px`; d.style.width = `${(b.volume / max) * 100}%`;
        if (vp.poc >= b.low && vp.poc <= b.high) d.dataset.poc = "1";
        pf.appendChild(d);
      }
    };
    chart.timeScale().fitContent();
    chart.timeScale().subscribeVisibleLogicalRangeChange(drawProfile);
    const t = setTimeout(drawProfile, 60);
    return () => { clearTimeout(t); if (typeof detach === "function") detach(); lines.length = 0; chart.remove(); chartRef.current = null; };
  }, [data, on, visibleMarkers, height]);

  const p = data?.provider;
  const badge = p?.realtime === true ? "real-time" : p?.realtime === false ? p.delay_label : "delay not tagged";
  const unavailable = data ? LAYERS.filter((l) => on[l.id] && data.layers[l.id] && data.layers[l.id]!.status !== "ok") : [];
  return (
    <section className="ux-card atlas-chart" aria-label={`ATLAS chart ${sym}`}>
      <header className="atlas-chart-bar">
        <strong className="atlas-chart-sym">{sym}</strong>
        <div className="atlas-chart-seg" role="group" aria-label="Timeframe">
          {CHART_INTERVALS.map((iv) => <button key={iv} type="button" aria-pressed={iv === interval} onClick={() => setInterval_(iv)}>{iv === "1d" ? "1D" : iv}</button>)}
        </div>
        <label className="atlas-chart-select">Bars
          <select value={barType} onChange={(e) => setBarType(e.target.value)} aria-label="Bar type">
            {CHART_BAR_TYPES.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </select>
        </label>
        <span className={`atlas-chart-badge${p?.realtime ? " is-live" : ""}`} title={p ? `${p.built}; providers: ${p.providers.join(", ") || "none"}` : ""}>
          {p?.provider ? `${p.provider} · ${badge}` : loading ? "loading…" : "no provider"}
        </span>
        <span className="atlas-chart-badge is-safe" title="ML output is advisory research. It can never place an order.">execution_permission: {data?.execution_permission ?? "none"}</span>
        <span className="atlas-chart-links">
          <a href={tradingViewUrl(sym)} target="_blank" rel="noopener noreferrer">Open in TradingView ↗</a>
          <a href="/research?tab=scan">Pine v5 export</a>
        </span>
      </header>
      <div className="atlas-chart-layers" role="group" aria-label="Layers">
        {LAYERS.map((l) => {
          const st = data?.layers[l.id]?.status;
          return (
            <label key={l.id} className={`atlas-chart-chip${on[l.id] ? " is-on" : ""}${st && st !== "ok" ? " is-off" : ""}`}>
              <input type="checkbox" checked={on[l.id]} onChange={(e) => setOn({ ...on, [l.id]: e.target.checked })} />{l.label}
            </label>
          );
        })}
      </div>
      <div className="atlas-chart-stage" style={{ height }}>
        <div ref={box} className="atlas-chart-canvas" />
        <div ref={profileRef} className="atlas-chart-vp" aria-hidden />
        {(error || (data && data.status !== "ok")) && (
          <div className="atlas-chart-empty">{error ? `Chart data unavailable (${error}).` : `No ${data?.interval} feed bars for ${sym} yet. Nothing is drawn rather than guessed.`}</div>
        )}
      </div>
      <footer className="atlas-chart-foot">
        {data?.display && data.display.status !== "ok" && <span>{data.display.kind}: {data.display.reason}</span>}
        {data?.display?.note && data.display.status === "ok" && <span>{data.display.note}.</span>}
        {unavailable.map((l) => <span key={l.id}>{l.label}: {data!.layers[l.id]!.reason ?? data!.layers[l.id]!.note ?? "no data for this symbol/interval"}</span>)}
        {on.regimes && data?.layers.regimes?.current && <span>Regime now: {data.layers.regimes.current.replace(/_/g, " ")}</span>}
        {on.conviction && data?.layers.conviction?.status === "ok" && <span>Conviction {data.layers.conviction.score} · {data.layers.conviction.label}</span>}
        <span>Data: ATLAS feed ({p?.built ?? "—"}), free sources only. Rendering: <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a>. Times America/Toronto. Paper only.</span>
      </footer>
      {showPanel && data && <AtlasMlPanel data={data} showConviction={on.conviction} showPredictions={on.predictions} />}
    </section>
  );
}

export function AtlasMlPanel({ data, showConviction, showPredictions }: { data: Overlays; showConviction: boolean; showPredictions: boolean }) {
  const ml = data.ml_panel;
  const ev = ml?.evolution;
  const m = ev?.metrics ?? {};
  const cm = ml?.current_model;
  const conv = data.layers.conviction;
  const cal = data.layers.predictions?.calibration;
  const preds = data.layers.predictions?.items ?? [];
  return (
    <div className="atlas-ml-panel" aria-label="ML panel">
      <div className="atlas-ml-cell">
        <h4>Model</h4>
        <span className="atlas-chart-badge is-safe">execution_permission: {ml?.execution_permission ?? "none"}</span>
        <dl>
          <dt>Current model</dt><dd>{cm ? `${cm.version} (${cm.status})` : "none registered for this market"}</dd>
          <dt>Evolution run</dt><dd>{ev ? ev.run_id : "no run yet"}</dd>
          <dt>Decision</dt><dd>{ev ? ev.decision.replace(/_/g, " ") : "—"}</dd>
          <dt>Champion</dt><dd>{ml?.champion ? String((ml.champion as { genome_id?: string }).genome_id ?? "set") : "none (baseline stays)"}</dd>
        </dl>
      </div>
      <div className="atlas-ml-cell">
        <h4>Baseline vs challenger</h4>
        {ev ? (
          <table className="atlas-ml-table"><thead><tr><th /><th>Baseline</th><th>Challenger</th></tr></thead><tbody>
            <tr><th>Brier</th><td>{fmt(m.brier_baseline)}</td><td>{fmt(m.brier)}</td></tr>
            <tr><th>AUC</th><td>0.500</td><td>{fmt(m.auc)}</td></tr>
            <tr><th>ECE</th><td>—</td><td>{fmt(m.ece)}</td></tr>
            <tr><th>OOS n</th><td colSpan={2}>{String(m.n_oos ?? "—")} predictions, {String(m.n_taken ?? "—")} taken</td></tr>
          </tbody></table>
        ) : <p>No evolution run on this server.</p>}
        <p className="atlas-ml-note">{ev?.challenger}{m.beats_baseline === false ? " — does not beat the baseline, so it stays research only." : ""}</p>
      </div>
      {showPredictions && (
        <div className="atlas-ml-cell">
          <h4>Predictions &amp; calibration</h4>
          {preds.length ? <>
            <p>{preds.length} out-of-sample predictions in view; {preds.filter((x) => x.take).length} above the take threshold.</p>
            <p>Calibration (run): Brier {fmt(cal?.brier)} vs {fmt(cal?.brier_baseline)} base rate, ECE {fmt(cal?.ece)}, AUC {fmt(cal?.auc)}. Calibrator: {preds[0].calibrator || "—"}.</p>
          </> : <p>No predictions for {data.symbol} {data.interval} in the latest run.</p>}
        </div>
      )}
      {showConviction && (
        <div className="atlas-ml-cell">
          <h4>Dossier conviction</h4>
          {conv?.status === "ok" ? <>
            <p><strong>{conv.score}</strong> · {conv.label}</p>
            <ul>{(conv.components ?? []).slice(0, 5).map((c) => <li key={c.rule}>{c.rule.replace(/_/g, " ")}: {c.why}</li>)}</ul>
            <p className="atlas-ml-note">Personas: {conv.personas}</p>
          </> : <p>{conv?.reason ?? "Unavailable."}</p>}
        </div>
      )}
      <div className="atlas-ml-cell atlas-ml-why">
        <h4>Why each marker fired</h4>
        {ml?.why.length ? (
          <ul>{ml.why.slice().reverse().map((w) => (
            <li key={w.id}><span className="atlas-ml-dot" style={{ background: MARKER_CLASSES[w.class]?.color }} />
              {MARKER_CLASSES[w.class]?.label}: {w.strategy.replace(/_/g, " ")} {w.direction}. {w.probability}. {w.risk}{w.ev_r != null ? `. EV ${w.ev_r.toFixed(2)}R` : ""}.</li>
          ))}</ul>
        ) : <p>No markers in view.</p>}
      </div>
    </div>
  );
}
