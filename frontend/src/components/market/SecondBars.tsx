"use client";

import { useEffect, useRef, useState } from "react";
import { ColorType, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";

export type Bar = { timestamp: string; open: number; high: number; low: number; close: number };
export type Tape = { candles?: Bar[]; chart_source?: string; feed_origin?: string; notice?: string; feed_health?: { connection?: string; trade_age_seconds?: number; delay_status?: string } };

export function SecondBars({ symbol, bucketSeconds, intervalLabel, onOpenMinute, snapshot, snapshotError = "" }: {
  symbol: string; bucketSeconds: number; intervalLabel: string; onOpenMinute?: () => void; snapshot?: Tape | null; snapshotError?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const last = useRef(0);
  const first = useRef(0);
  const [polledTape, setTape] = useState<Tape>({});
  const [pollError, setError] = useState("");
  const externallyControlled = snapshot !== undefined;
  const tape = externallyControlled ? snapshot ?? {} : polledTape;
  const error = externallyControlled ? snapshotError : pollError;
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    const api = createChart(element, {
      width: Math.max(1, element.clientWidth), height: Math.max(1, element.clientHeight),
      layout: { background: { type: ColorType.Solid, color: "#0B0F17" }, textColor: "#A9BDCE" },
      grid: { vertLines: { color: "#182431" }, horzLines: { color: "#182431" } },
      timeScale: { timeVisible: true, secondsVisible: bucketSeconds < 60, rightOffset: 3 },
      rightPriceScale: { borderColor: "#263848", scaleMargins: { top: 0.12, bottom: 0.12 } },
    });
    chart.current = api;
    series.current = api.addCandlestickSeries({ upColor: "#34d399", downColor: "#fb7185", borderVisible: false, wickUpColor: "#34d399", wickDownColor: "#fb7185" });
    const observer = new ResizeObserver(() => api.applyOptions({ width: Math.max(1, element.clientWidth), height: Math.max(1, element.clientHeight) }));
    observer.observe(element);
    return () => { observer.disconnect(); api.remove(); chart.current = null; series.current = null; };
  }, []);
  useEffect(() => {
    setTape({}); setError(""); last.current = 0; first.current = 0; series.current?.setData([]);
    if (externallyControlled) return;
    const controller = new AbortController();
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch(`/api/market/second-tape?symbol=${encodeURIComponent(symbol)}&bucket_seconds=${bucketSeconds}&sampling=true`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`Live feed returned ${response.status}`);
        const body = await response.json();
        if (!controller.signal.aborted) { setTape(body); setError(""); }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Live feed unavailable");
      } finally { pending = false; }
    };
    void poll(); const timer = window.setInterval(poll, 400);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [symbol, bucketSeconds, externallyControlled]);
  useEffect(() => { chart.current?.applyOptions({ timeScale: { secondsVisible: bucketSeconds < 60 } }); }, [bucketSeconds]);
  useEffect(() => {
    const target = series.current;
    if (!target) return;
    const points = [...new Map((["public_last_trade", "public_market_candles"].includes(tape.chart_source ?? "") ? tape.candles ?? [] : []).map(bar => {
      const time = Math.floor(Date.parse(bar.timestamp) / 1000) as UTCTimestamp;
      return [time, { time, open: bar.open, high: bar.high, low: bar.low, close: bar.close }] as const;
    })).values()].filter(point => Number.isFinite(point.time) && [point.open, point.high, point.low, point.close].every(Number.isFinite)).sort((a, b) => a.time - b.time);
    if (!points.length) { target.setData([]); last.current = 0; first.current = 0; return; }
    const initial = !last.current;
    if (initial || bucketSeconds >= 60 || first.current !== points[0].time) target.setData(points);
    else points.filter(point => point.time >= last.current).forEach(point => target.update(point));
    const price = points[points.length - 1].close;
    const precision = price >= 100 ? 2 : price >= 1 ? 4 : 8;
    target.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
    first.current = points[0].time; last.current = points[points.length - 1].time;
    if (initial) chart.current?.timeScale().fitContent();
  }, [tape, bucketSeconds]);
  const available = ["public_last_trade", "public_market_candles"].includes(tape.chart_source ?? "") && Boolean(tape.candles?.length);
  return <section className="realtime-tape" aria-label={`${symbol} ${intervalLabel} chart`} style={{ display: "flex", flexDirection: "column", minHeight: 0, minWidth: 0, overflow: "hidden" }}>
    <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
      <div ref={host} className="realtime-chart-host" style={{ position: "absolute", inset: 0 }} />
      {!available && <div className="realtime-empty" role="status"><strong>{symbol}: {error ? "Feed unavailable" : tape.chart_source === "withheld" ? "Market data unavailable" : "Connecting to market data"}</strong><span>{error || tape.notice || "Loading the public market API. This chart renders received prices directly."}</span>{onOpenMinute && <button type="button" onClick={onOpenMinute}>Open TradingView chart</button>}</div>}
    </div>
    <p style={{ margin: "6px 0 0", fontSize: 11, color: "#94a3b8" }}>{error || tape.notice || `Native ${bucketSeconds === 1 ? "1-second" : `${bucketSeconds / 60}-minute`} candles from the market API.`} {tape.feed_origin && `Source: ${tape.feed_origin}. `}{tape.feed_health?.connection && `Feed: ${tape.feed_health.connection}. `}<a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer">Charts by TradingView Lightweight Charts</a></p>
  </section>;
}
