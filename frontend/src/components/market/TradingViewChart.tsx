"use client";

import React, { useEffect, useState } from "react";

type TradingViewPane = {
  id: string;
  title: string;
  embed_url: string;
  page_url: string;
  note: string;
  feeds_model: boolean;
  execution_permission: "none";
};

type TradingViewSpec = {
  symbol: string;
  timeframe: string;
  tradingview_symbol: string | null;
  interval: string | null;
  available: boolean;
  reason_text: string;
  embed_url: string | null;
  chart_page_url: string | null;
  widgets?: TradingViewPane[];
  symbol_artifacts?: TradingViewPane[];
  information_page?: "stock" | "listing" | "none";
  execution_permission: "none";
};

type TapeSpec = {
  embed_url: string;
  page_url: string;
  note: string;
  execution_permission: "none";
};

const PANE_HEIGHT: Record<string, number> = {
  "symbol-info": 128,
  "technical-analysis": 400,
  "symbol-profile": 390,
  financials: 460,
  timeline: 460,
  "symbol-overview": 420,
  "mini-symbol-overview": 220,
  "single-quote": 126,
};

function TradingViewPaneFrame({
  pane,
  height,
  quiet = false,
}: {
  pane: TradingViewPane;
  height: number;
  quiet?: boolean;
}) {
  return (
    <section style={{ minWidth: 0 }}>
      {quiet ? null : (
        <div style={{ fontSize: "11px", color: "#94A3B8", lineHeight: 1.45, marginBottom: "6px" }}>
          {pane.note} execution_permission {pane.execution_permission}
        </div>
      )}
      <iframe
        title={pane.title}
        src={pane.embed_url}
        style={{ width: "100%", height, border: 0, borderRadius: "6px", background: "#0B0F17" }}
      />
      <a
        href={pane.page_url}
        target="_blank"
        rel="noopener nofollow"
        style={{ display: "inline-block", marginTop: "6px", color: "#38bdf8", fontSize: "11px" }}
      >
        {pane.title} by TradingView
      </a>
    </section>
  );
}

export function TradingViewChart({
  symbol,
  timeframe,
  height = 520,
  showTape = false,
  showCompanions = true,
  showChart = true,
  quiet = false,
  fill = false,
}: {
  symbol: string;
  timeframe: string;
  height?: number;
  showTape?: boolean;
  showCompanions?: boolean;
  showChart?: boolean;
  quiet?: boolean;
  fill?: boolean;
}) {
  const [spec, setSpec] = useState<TradingViewSpec | null>(null);
  const [tape, setTape] = useState<TapeSpec | null>(null);
  const [failed, setFailed] = useState(false);
  const [frameLoaded, setFrameLoaded] = useState(false);

  useEffect(() => {
    if (!showChart) return;
    let active = true;
    setFailed(false);
    setSpec(null);
    setFrameLoaded(false);
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/market/tradingview?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("tradingview map unavailable");
        const body = (await response.json()) as TradingViewSpec;
        if (active) setSpec(body);
      } catch {
        if (active) {
          setSpec(null);
          setFailed(true);
        }
      }
    };
    void pull();
    return () => {
      active = false;
    };
  }, [showChart, symbol, timeframe]);

  useEffect(() => {
    if (!showTape) return;
    let active = true;
    const pull = async () => {
      try {
        const origin = window.location.origin;
        const response = await fetch(
          `/api/market/tradingview/tape?origin=${encodeURIComponent(origin)}`,
          { cache: "no-store" }
        );
        if (!response.ok) return;
        const body = (await response.json()) as TapeSpec;
        if (active) setTape(body);
      } catch {
        if (active) setTape(null);
      }
    };
    void pull();
    return () => {
      active = false;
    };
  }, [showTape]);

  if (showChart && failed) {
    return (
      <div style={{ height: fill ? "100%" : undefined, minHeight: 160, color: "#94A3B8", fontSize: "12px", padding: "12px 4px" }}>
        TradingView chart map is unavailable. No substitute candles are drawn. execution_permission none
      </div>
    );
  }
  if (showChart && !spec) {
    return (
      <div style={{ height: fill ? "100%" : height, minHeight: fill ? 0 : undefined, color: "#94A3B8", fontSize: "12px", padding: "12px 4px" }}>
        Loading the TradingView chart for {symbol}
      </div>
    );
  }

  const panes = spec && Array.isArray(spec.widgets) ? spec.widgets : [];
  const quote = panes.find((pane) => pane.id === "symbol-info");
  const companions = panes.filter((pane) => pane.id !== "symbol-info");
  const artifacts = spec && Array.isArray(spec.symbol_artifacts) ? spec.symbol_artifacts : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px", height: fill ? "100%" : undefined, minHeight: fill ? 0 : undefined }}>
      {showTape && tape ? (
        <section>
          {quiet ? null : (
            <div style={{ fontSize: "11px", color: "#94A3B8", marginBottom: "6px" }}>
              {tape.note} execution_permission {tape.execution_permission}
            </div>
          )}
          <iframe
            title="TradingView ticker tape"
            src={tape.embed_url}
            style={{ width: "100%", height: 74, border: 0, borderRadius: "6px", background: "#0B0F17" }}
          />
          <a href={tape.page_url} target="_blank" rel="noopener nofollow" style={{ color: "#38bdf8", fontSize: "11px" }}>
            Both books by TradingView
          </a>
        </section>
      ) : null}
      {showCompanions && quote ? (
        <TradingViewPaneFrame pane={quote} height={PANE_HEIGHT["symbol-info"]} quiet={quiet} />
      ) : null}
      {showChart && spec && spec.available && spec.embed_url ? (
        <section style={fill ? { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" } : undefined}>
          <iframe
            key={`${spec.tradingview_symbol}:${spec.interval}`}
            onLoad={() => setFrameLoaded(true)}
            onError={() => setFailed(true)}
            title={`TradingView ${spec.tradingview_symbol} ${spec.interval}`}
            src={spec.embed_url}
            scrolling="no"
            style={{
              width: "100%",
              height: fill ? "100%" : height,
              flex: fill ? 1 : undefined,
              minHeight: fill ? 0 : undefined,
              border: 0,
              borderRadius: "6px",
              background: "#0B0F17",
            }}
            allowFullScreen
          />
          <div style={{ color: "#94A3B8", fontSize: "11px", marginTop: "4px" }}>
            {frameLoaded ? "TradingView frame loaded · chart contents are provided by TradingView" : "Loading TradingView frame…"}
          </div>
          <a
            href={spec.chart_page_url ?? "https://www.tradingview.com/"}
            target="_blank"
            rel="noopener nofollow"
            style={{ display: "inline-block", marginTop: "6px", color: "#38bdf8", fontSize: "11px" }}
          >
            {spec.tradingview_symbol} chart by TradingView
          </a>
        </section>
      ) : showChart && spec ? (
        <div style={{ minHeight: 120, color: "#94A3B8", fontSize: "12px", lineHeight: 1.5 }}>
          {spec.reason_text} execution_permission {spec.execution_permission}
        </div>
      ) : null}
      {showCompanions && companions.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px" }}>
          {companions.map((pane) => (
            <TradingViewPaneFrame key={pane.id} pane={pane} height={PANE_HEIGHT[pane.id] ?? 400} quiet={quiet} />
          ))}
        </div>
      ) : null}
      {showCompanions && artifacts.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px" }}>
          {artifacts.map((pane) => (
            <TradingViewPaneFrame key={pane.id} pane={pane} height={PANE_HEIGHT[pane.id] ?? 400} quiet={quiet} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

const STOCK_PAGE_ORDER = [
  "symbol-info",
  "symbol-profile",
  "financials",
  "technical-analysis",
  "timeline",
  "single-quote",
  "mini-symbol-overview",
  "symbol-overview",
];

export function TradingViewStockInfo({ symbol, timeframe }: { symbol: string; timeframe: string }) {
  const [spec, setSpec] = useState<TradingViewSpec | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    setSpec(null);
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/market/tradingview?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("tradingview map unavailable");
        const body = (await response.json()) as TradingViewSpec;
        if (active) setSpec(body);
      } catch {
        if (active) {
          setSpec(null);
          setFailed(true);
        }
      }
    };
    void pull();
    return () => {
      active = false;
    };
  }, [symbol, timeframe]);

  const stock = spec?.information_page === "stock";
  const panes = [...(spec?.widgets ?? []), ...(spec?.symbol_artifacts ?? [])].sort(
    (left, right) => STOCK_PAGE_ORDER.indexOf(left.id) - STOCK_PAGE_ORDER.indexOf(right.id)
  );

  return (
    <section className="clean-card" style={{ marginBottom: "12px" }}>
      <div style={{ fontSize: "13px", fontWeight: 700, color: "#F8FAFC", marginBottom: "6px" }}>
        {stock ? "Stock information" : "Symbol information"}
      </div>
      <div style={{ fontSize: "12px", color: "#94A3B8", lineHeight: 1.5, marginBottom: "10px" }}>
        {stock
          ? "TradingView's stock page for this listing: Symbol Info, Company Profile, Fundamental Data, Technical Analysis, and Top Stories, plus the single ticker, mini chart, and symbol overview. US stock widgets are delayed."
          : "TradingView's symbol page for this listing: quote, profile, fundamental data, technical rating, and news, plus the single ticker, mini chart, and symbol overview."}{" "}
        None of these panes feed the model. execution_permission none
      </div>
      {failed ? (
        <div style={{ color: "#94A3B8", fontSize: "12px" }}>
          TradingView symbol page is unavailable. No substitute company data is drawn. execution_permission none
        </div>
      ) : null}
      {!spec && !failed ? (
        <div style={{ color: "#94A3B8", fontSize: "12px" }}>Loading TradingView symbol information for {symbol}</div>
      ) : null}
      {spec && panes.length === 0 ? (
        <div style={{ color: "#94A3B8", fontSize: "12px", lineHeight: 1.5 }}>
          {spec.reason_text} execution_permission {spec.execution_permission}
        </div>
      ) : null}
      {panes.map((pane) => (
        <div key={pane.id} style={{ marginTop: "12px" }}>
          <TradingViewPaneFrame pane={pane} height={PANE_HEIGHT[pane.id] ?? 420} />
        </div>
      ))}
    </section>
  );
}

export default TradingViewChart;
