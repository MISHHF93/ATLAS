"use client";
/** evo-16 hotfix: a timeframe with no stored bars still gets a chart. Only the forecast is drawn (dashed mid, dotted 80% band) from ONE real
 *  point, the last real bar of a coarser interval. Never candles, never fabricated bars; the forecast is never stored as market data. */
import { useEffect, useRef } from "react";
import { createChart, LineStyle, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { deskTimeOptions } from "./lwTime";
import { ageText, NOWCAST_LABEL, type Nowcast } from "./nowcast";

const COL = "#B8A1FF";

export function nowcastBannerText(nc: Nowcast, interval: string, sym: string): string {
  const a = nc.anchor;
  const ivTxt = nc.base_interval ? `${nc.base_interval} ` : "";
  return `No ${interval} bars are stored for ${sym} yet. Showing ${NOWCAST_LABEL}, anchored to the last real ${ivTxt}${a?.source === "quote" ? "quote" : "bar"}`
    + `${a ? ` (${ageText(a.age_s)} old${a.age_toronto ? `, ${a.age_toronto}` : ""})` : ""}`
    + `${nc.mode === "end_of_day" ? " from end-of-day data" : ""}. It is a forecast with an ${Math.round((nc.level ?? 0.8) * 100)}% band, not market data, and no candles are drawn for it.`;
}

export function NowcastOnly({ nc, height, sym, interval }: { nc: Nowcast; height: number | string; sym: string; interval: string }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (!el || !nc.path?.length || !nc.anchor) return;
    const css = getComputedStyle(el);
    const text = css.getPropertyValue("--c-muted").trim() || "#98A3B3";
    const grid = css.getPropertyValue("--c-border").trim() || "#27303D";
    const chart = createChart(el, { ...deskTimeOptions, autoSize: true,
      layout: { ...deskTimeOptions.layout, background: { color: "transparent" }, textColor: text, fontSize: 11 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } }, rightPriceScale: { borderColor: grid },
      timeScale: { ...deskTimeOptions.timeScale, borderColor: grid, rightOffset: 4, secondsVisible: interval === "1m" } });
    const mk = (style: LineStyle, w: 1 | 2, title: string): ISeriesApi<"Line"> =>
      chart.addLineSeries({ color: COL, lineWidth: w, lineStyle: style, lastValueVisible: !!title, priceLineVisible: false, crosshairMarkerVisible: false, title });
    try {
      const head = { time: nc.anchor.t as UTCTimestamp, value: nc.anchor.price };
      const pts = nc.path.filter((q) => q.t > nc.anchor!.t);
      const mid = mk(LineStyle.Dashed, 2, "Predicted"), hi = mk(LineStyle.Dotted, 1, ""), lo = mk(LineStyle.Dotted, 1, "");
      mid.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.mid }))]);
      hi.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.hi }))]);
      lo.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.lo }))]);
      mid.setMarkers([{ time: head.time, position: "inBar", shape: "circle", color: COL, text: `last real ${nc.base_interval ?? ""} ${nc.anchor.source === "quote" ? "quote" : "close"}` }]);
      chart.timeScale().fitContent();
    } catch { /* nothing is invented when a point cannot be drawn */ }
    return () => { try { chart.remove(); } catch { /* already gone */ } };
  }, [nc, interval]);
  return <div ref={box} data-testid="nowcast-only-chart" aria-label={`${NOWCAST_LABEL} for ${sym}, ${interval}`} style={{ position: "absolute", inset: 0, height: typeof height === "number" ? height : undefined }} />;
}
