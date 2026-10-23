"use client";

import React, { useEffect, useState } from "react";
import { LiveChartEngine, type LiveCandlePoint } from "./LiveChartEngine";
import { freshness } from "./lwTime";
import { TvProvenance } from "./TvFrame";

const RESOLUTION: Record<string, string> = {
  "1m": "1",
  "5m": "5",
  "15m": "15",
  "1h": "60",
  "1D": "D",
};

const RESOLUTION_SECONDS: Record<string, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "1D": 86400,
};

type UdfHistory = {
  s: string;
  t?: number[];
  o?: number[];
  h?: number[];
  l?: number[];
  c?: number[];
  v?: number[];
  errmsg?: string;
  feed_origin?: string;
  execution_permission?: "none";
};

type BracketIntent = {
  stopLossPrice: number;
  takeProfitPrice: number;
  riskUsd: number;
};

type TapeProps = {
  symbol: string;
  timeframe: "1s" | "1m" | "5m" | "15m" | "1h" | "1D";
  height?: number;
  bracketStop?: number | null;
  bracketTarget?: number | null;
  quantity?: number;
  onBracketIntent?: (intent: BracketIntent) => void;
};

type ChartWindow = Window & {
  TradingView?: { widget?: new (options: Record<string, unknown>) => { remove?: () => void } };
  Datafeeds?: { UDFCompatibleDatafeed?: new (url: string) => unknown };
};

export function AtlasUdfTape({
  symbol,
  timeframe,
  height = 520,
  bracketStop = null,
  bracketTarget = null,
  quantity = 1,
  onBracketIntent,
}: TapeProps) {
  const [candles, setCandles] = useState<LiveCandlePoint[]>([]);
  const [note, setNote] = useState("Reading closed bars from /api/udf.");
  const [origin, setOrigin] = useState("");
  const [loading, setLoading] = useState(false);
  const resolution = RESOLUTION[timeframe];

  useEffect(() => {
    if (!resolution) return;
    const controller = new AbortController();
    let active = true;
    const to = Math.floor(Date.now() / 1000);
    const from = to - RESOLUTION_SECONDS[timeframe] * 240;
    setLoading(true);
    fetch(
      `/api/udf/history?symbol=${encodeURIComponent(symbol)}&resolution=${resolution}&from=${from}&to=${to}`,
      { signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return (await response.json()) as UdfHistory;
      })
      .then((body) => {
        if (!active) return;
        setOrigin(body.feed_origin ?? "");
        if (body.s !== "ok" || !body.t?.length) {
          setCandles([]);
          setNote(body.s === "no_data" ? "No closed bars in this window." : body.errmsg ?? "UDF history unavailable.");
          return;
        }
        setCandles(
          body.t.map((stamp, index) => ({
            timestamp: new Date(stamp * 1000).toISOString(),
            open: body.o?.[index] ?? 0,
            high: body.h?.[index] ?? 0,
            low: body.l?.[index] ?? 0,
            close: body.c?.[index] ?? 0,
            volume: body.v?.[index] ?? 0,
          })),
        );
        setNote("");
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
        setCandles([]);
        setNote("The UDF history request failed.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [resolution, symbol, timeframe]);

  useEffect(() => {
    if (!resolution) return;
    const view = window as ChartWindow;
    const Widget = view.TradingView?.widget;
    const Feed = view.Datafeeds?.UDFCompatibleDatafeed;
    if (!Widget || !Feed) return;
    const widget = new Widget({
      container: "tv_chart_container",
      datafeed: new Feed("/api/udf"),
      symbol,
      interval: resolution,
      locale: "en",
      autosize: true,
      disabled_features: ["use_localstorage_for_settings"],
    });
    return () => widget.remove?.();
  }, [resolution, symbol]);

  return (
    <div data-atlas-tape="udf">
      {timeframe === "1s" ? (
        <p style={{ margin: 0, color: "#94A3B8", fontSize: "12px", lineHeight: 1.45 }}>
          This feed has no 1-second bars. Resolutions are 1, 5, 15, 60, and D. One-second bars belong to the
          TradingView Charting Library, and that script is not bundled.
        </p>
      ) : (
        <LiveChartEngine
          variant="tape"
          symbol={symbol}
          candles={candles}
          timeframe={timeframe}
          chartHeight={height}
          loading={loading && candles.length === 0}
          marketDataAvailable={candles.length > 0}
          bracketStop={bracketStop}
          bracketTarget={bracketTarget}
          bracketQuantity={quantity}
          onBracketIntent={onBracketIntent}
        />
      )}
      {note ? (
        <p style={{ margin: "8px 0 0", color: "#94A3B8", fontSize: "12px" }}>{note}</p>
      ) : null}
      {(() => {
        const last = candles.length ? Math.floor(Date.parse(candles[candles.length - 1].timestamp) / 1000) : null;
        const fresh = freshness(last, RESOLUTION_SECONDS[timeframe] ?? 60);
        return (
          <p data-freshness={fresh.stale ? "stale" : "fresh"} style={{ margin: "6px 0 0", color: fresh.stale ? "#E69F00" : "#64748B", fontSize: "11px" }}>
            <TvProvenance kind="atlas" /> {origin ? `${origin} · ` : ""}{fresh.label}{fresh.stale ? " · stale" : ""} · execution_permission none · closed bars only ·
            rendered with <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener noreferrer" style={{ color: "#64748B" }}>TradingView Lightweight Charts™</a>
          </p>
        );
      })()}
      <div
        id="tv_chart_container"
        data-udf-url="/api/udf"
        data-symbol={symbol}
        style={{
          marginTop: "8px",
          padding: "8px 10px",
          borderRadius: "6px",
          border: "1px dashed rgba(255,255,255,0.14)",
          color: "#64748B",
          fontSize: "11px",
          lineHeight: 1.45,
        }}
      >
        TradingView Charting Library is not bundled. This container is bound to /api/udf and mounts the library
        widget only when window.TradingView and the UDF datafeed script are already on the page.
      </div>
    </div>
  );
}
