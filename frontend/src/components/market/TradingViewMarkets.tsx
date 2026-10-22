"use client";

import React, { useEffect, useState } from "react";

type MarketPane = {
  id: string;
  title: string;
  embed_url: string;
  page_url: string;
  note: string;
  height?: number;
  feeds_model: boolean;
  execution_permission: "none";
};

type MarketsSpec = {
  note: string;
  widgets: MarketPane[];
  origin_accepted: boolean;
  feeds_model: boolean;
  execution_permission: "none";
};

export function TradingViewMarkets() {
  const [spec, setSpec] = useState<MarketsSpec | null>(null);
  const [typed, setTyped] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const origin = window.location.origin;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/market/tradingview/markets?origin=${encodeURIComponent(origin)}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("markets unavailable");
        const body = (await response.json()) as MarketsSpec;
        if (active) setSpec(body);
      } catch {
        if (active) setFailed(true);
      }
    };
    void pull();
    return () => {
      active = false;
    };
  }, []);

  const openListing = (raw: string) => {
    const value = raw.trim().toUpperCase();
    if (!value) return;
    window.location.assign(`/?tvwidgetsymbol=${encodeURIComponent(value)}`);
  };

  return (
    <section style={{ marginBottom: "18px" }}>
      <div className="clean-card" style={{ marginBottom: "12px" }}>
        <div style={{ fontSize: "13px", fontWeight: 700, color: "#F8FAFC", marginBottom: "6px" }}>
          TradingView catalog
        </div>
        <div style={{ fontSize: "12px", color: "#94A3B8", lineHeight: 1.5, marginBottom: "10px" }}>
          This page calls TradingView&apos;s iframe catalog: stock, crypto, and forex screeners, the three
          heatmaps, the economic calendar, forex cross rates and heat map, US hot lists, market overview,
          market quotes, a static ticker strip, and top stories. US stock widgets are delayed. Forex and
          crypto widgets are TradingView&apos;s real-time feed. None of them feed the model. A click opens
          the desk only when that widget documents a chart link. Seasonal Chart, World Market Summary,
          Market Summary, Economic Map, and Ticker Tag are Web Components outside the iframe registry, so
          they are not embedded. execution_permission none
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            openListing(typed);
          }}
          style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}
        >
          <input
            type="text"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="NASDAQ:AAPL, COINBASE:ETHUSD, AMEX:SPY, CME_MINI:ES1!"
            aria-label="Open a TradingView listing on the desk"
            style={{
              flex: "1 1 280px",
              padding: "8px 10px",
              borderRadius: "6px",
              border: "1px solid rgba(0, 200, 255, 0.3)",
              background: "#070A0F",
              color: "#F8FAFC",
              fontSize: "12px",
            }}
          />
          <button type="submit" className="clean-tf-btn active" style={{ padding: "8px 14px", fontSize: "12px" }}>
            Open on the desk
          </button>
        </form>
      </div>
      {failed ? (
        <div style={{ color: "#94A3B8", fontSize: "12px", padding: "8px 2px" }}>
          TradingView catalog is unavailable. No substitute universe is drawn. execution_permission none
        </div>
      ) : null}
      {!spec && !failed ? (
        <div style={{ color: "#94A3B8", fontSize: "12px", padding: "8px 2px" }}>Loading the TradingView catalog</div>
      ) : null}
      {spec
        ? spec.widgets.map((pane) => (
            <section key={pane.id} className="clean-card" style={{ marginTop: "12px" }}>
              <div style={{ fontSize: "11px", color: "#94A3B8", lineHeight: 1.45, marginBottom: "6px" }}>
                {pane.note} execution_permission {pane.execution_permission}
              </div>
              <iframe
                title={pane.title}
                src={pane.embed_url}
                style={{
                  width: "100%",
                  height: pane.height ?? 540,
                  border: 0,
                  borderRadius: "6px",
                  background: "#0B0F17",
                }}
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
          ))
        : null}
    </section>
  );
}

export default TradingViewMarkets;
