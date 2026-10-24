"use client";
/** Feed-bar chart with the model/strategy opportunity markers (the TradingView widget on the desk cannot take
 *  ATLAS markers, so this chart sits under it). Real-time-axis, causal markers; research signal, paper only. */
import { useEffect, useRef, useState } from "react";
import { ColorType, createChart, type IChartApi, type UTCTimestamp } from "lightweight-charts";
import { deskTimeOptions } from "./lwTime";
import { MarkerControls, altToCandles, attachMarkerTooltip, toSeriesMarkers, useAltBars, useMarkers, type DisplayType } from "./opportunityMarkers";

const FEED_SYM: Record<string, string> = { "BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "SOL-USD": "SOLUSDT" };
const TF: Record<string, string> = { "1s": "15m", "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1D": "1d" };

export function OpportunityChart({ symbol, timeframe, height = 320 }: { symbol: string; timeframe: string; height?: number }) {
  const sym = FEED_SYM[symbol] ?? symbol.replace(/-USD$/, "USDT");
  const [tf, setTf] = useState(TF[timeframe] ?? "15m");
  useEffect(() => { setTf(TF[timeframe] ?? "15m"); }, [timeframe]);
  const [open, setOpen] = useState(false);
  const [mOn, setMOn] = useState(true);
  const [show, setShow] = useState<Record<string, boolean>>({});
  const [display, setDisplay] = useState<DisplayType>("candles");
  const base = useAltBars(open ? sym : "", tf, "time" as DisplayType);
  const alt = useAltBars(open ? sym : "", tf, display);
  const mk = useMarkers(sym, tf, open && mOn);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    const bars = base?.bars ?? [];
    if (!open || !el || bars.length < 2) return;
    const dur = bars[1].completed_at - bars[0].completed_at || 60;
    const chart: IChartApi = createChart(el, { ...deskTimeOptions, width: Math.max(1, el.clientWidth), height,
      layout: { attributionLogo: true, textColor: "#CBD5E1", background: { type: ColorType.Solid, color: "#0B0F17" } },
      grid: { vertLines: { color: "#182431" }, horzLines: { color: "#182431" } } });
    const s = chart.addCandlestickSeries({ upColor: "#009E73", downColor: "#D55E00", borderVisible: false, wickUpColor: "#009E73", wickDownColor: "#D55E00" });
    const real = bars.map((b) => ({ time: b.start as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close }));
    const altOk = display !== "candles" && alt?.status === "ok" && alt.bars.length > 0;
    s.setData(altOk ? altToCandles(alt!.bars, dur) : real);
    const ms = mOn && mk.data?.markers ? mk.data.markers : [];
    const times = new Set(real.map((r) => r.time as number));
    s.setMarkers(toSeriesMarkers(ms, times, show));
    chart.timeScale().fitContent();
    const untip = attachMarkerTooltip(chart, el, () => ms.filter((m) => show[m.class] !== false));
    const ro = new ResizeObserver(() => chart.applyOptions({ width: Math.max(1, el.clientWidth) }));
    ro.observe(el);
    return () => { untip(); ro.disconnect(); chart.remove(); };
  }, [open, base, alt, display, mk.data, mOn, show, height]);
  return (
    <section className="ux-card" aria-label="Model opportunities chart" style={{ marginTop: 8 }}>
      <div className="ux-form-row" style={{ justifyContent: "space-between" }}>
        <strong>Model opportunities · {sym} {tf}</strong>
        {open ? <label className="ux-field" data-size="sm"><span>Bar size</span>
          <select value={tf} onChange={(e) => setTf(e.target.value)} aria-label="Opportunity bar size">
            {["1m", "15m", "1h", "1d"].map((t) => <option key={t} value={t}>{t}</option>)}</select></label> : null}
        <button type="button" className="ux-btn" data-size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show opportunities"}</button>
      </div>
      {open ? (<>
        <MarkerControls on={mOn} setOn={setMOn} show={show} setShow={setShow} payload={mk.data} error={mk.error} display={display} setDisplay={setDisplay}
          altStatus={display === "candles" ? null : alt?.status === "ok" ? "Alternative bars are display only, drawn when each one completed." : alt ? `Unavailable: ${alt.reason ?? "no data"}.` : "Loading…"} />
        {base && base.status !== "ok" ? <p className="ux-muted">No feed bars for {sym} {tf}: {base.reason ?? "unavailable"}.</p> : null}
        <div ref={box} className="ux-chart" style={{ height }} hidden={!base?.bars?.length} />
        <p className="ux-muted" style={{ fontSize: 11 }}>ATLAS feed bars (not the TradingView picture above). Chart: TradingView Lightweight Charts™ (Apache-2.0).</p>
      </>) : null}
    </section>
  );
}
