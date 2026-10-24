"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CLIENT_ROLE_PROFILES,
  RoleProvider,
  useRoleContext,
  type ClientRoleId,
} from "../../context/RoleContext";
import { AtlasLogo } from "../shell/AtlasLogo";
import { AssetMarkLegend, GuideIcon, markColor } from "../shell/guideIcons";
import { type LiveCandlePoint } from "./LiveChartEngine";
import { TradingViewStockInfo } from "./TradingViewChart";
import { DeskChart } from "./DeskChart";
import { TradingViewMarkets } from "./TradingViewMarkets";
import { SafeStopReleaseCli } from "../safety/SafeStopReleaseCli";
import { useFeedQuotes } from "../../lib/feedQuotes";
import { AssetCard, AssetTable } from "./AssetCard";

export interface Module02ListingPacket {
  symbol: string;
  name: string;
  track: "open_market" | "competition";
  provider: "databento" | "polygon" | "ccxt_pro" | "coinbase" | "hyperliquid";
  venue: string;
  price: number;
  prevPrice: number;
  changePct: number;
  vpin: number;
  ofi: number;
  kylesLambda: number;
  spreadBps: number;
  latencyMs: number;
  regime: string;
  bidDepthTop5: number[];
  askDepthTop5: number[];
  flash: "up" | "down" | "none";
  executionPermission: "none";
}

const INITIAL_MODULE02_LISTINGS: Module02ListingPacket[] = [
  {
    symbol: "SPY",
    name: "SPDR S&P 500 ETF Trust",
    track: "open_market",
    provider: "databento",
    venue: "NYSE Arca · SIP L2",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0.42,
    vpin: 0.242,
    ofi: 0.185,
    kylesLambda: 0.0012,
    spreadBps: 1.2,
    latencyMs: 6.4,
    regime: "Compression",
    bidDepthTop5: [150, 120, 95, 80, 60],
    askDepthTop5: [130, 105, 88, 72, 54],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp. (SEC CIK 0001045810)",
    track: "open_market",
    provider: "polygon",
    venue: "Nasdaq Global Select · XNAS",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 2.14,
    vpin: 0.368,
    ofi: 0.312,
    kylesLambda: 0.0016,
    spreadBps: 1.5,
    latencyMs: 7.8,
    regime: "Expansion",
    bidDepthTop5: [185, 140, 110, 85, 68],
    askDepthTop5: [140, 115, 92, 74, 58],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "AAPL",
    name: "Apple Inc. (SEC CIK 0000320193)",
    track: "open_market",
    provider: "databento",
    venue: "Nasdaq Global Select · XNAS",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0.65,
    vpin: 0.214,
    ofi: 0.142,
    kylesLambda: 0.0011,
    spreadBps: 1.4,
    latencyMs: 6.9,
    regime: "Compression",
    bidDepthTop5: [160, 125, 98, 76, 62],
    askDepthTop5: [145, 118, 90, 72, 59],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "MSFT",
    name: "Microsoft Corp. (SEC CIK 0000789019)",
    track: "open_market",
    provider: "polygon",
    venue: "Nasdaq Global Select · XNAS",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0.31,
    vpin: 0.225,
    ofi: 0.164,
    kylesLambda: 0.0013,
    spreadBps: 1.3,
    latencyMs: 8.1,
    regime: "Compression",
    bidDepthTop5: [140, 112, 89, 71, 55],
    askDepthTop5: [128, 104, 84, 68, 52],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "QQQ",
    name: "Invesco QQQ Trust (Nasdaq-100)",
    track: "open_market",
    provider: "databento",
    venue: "Nasdaq · SIP L2",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0.88,
    vpin: 0.289,
    ofi: 0.238,
    kylesLambda: 0.0014,
    spreadBps: 1.4,
    latencyMs: 7.2,
    regime: "Expansion",
    bidDepthTop5: [170, 134, 108, 84, 66],
    askDepthTop5: [148, 119, 94, 76, 60],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "TSLA",
    name: "Tesla Inc. (SEC CIK 0001318605)",
    track: "open_market",
    provider: "polygon",
    venue: "Nasdaq Global Select · XNAS",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: -1.12,
    vpin: 0.432,
    ofi: -0.264,
    kylesLambda: 0.0021,
    spreadBps: 2.2,
    latencyMs: 9.1,
    regime: "Auction",
    bidDepthTop5: [110, 92, 74, 60, 48],
    askDepthTop5: [155, 128, 102, 82, 65],
    flash: "down",
    executionPermission: "none",
  },
  {
    symbol: "BTC-USD",
    name: "Bitcoin Perpetual Swap (Prop Desk)",
    track: "competition",
    provider: "ccxt_pro",
    venue: "24/7 Prop Perp · CCXT Pro",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 1.42,
    vpin: 0.312,
    ofi: 0.245,
    kylesLambda: 0.0015,
    spreadBps: 3.2,
    latencyMs: 8.4,
    regime: "Expansion",
    bidDepthTop5: [195, 152, 124, 96, 74],
    askDepthTop5: [162, 130, 104, 82, 64],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "ETH-USD",
    name: "Ethereum Perpetual Swap (Prop Desk)",
    track: "competition",
    provider: "coinbase",
    venue: "24/7 Prop Perp · Coinbase",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 2.15,
    vpin: 0.278,
    ofi: 0.212,
    kylesLambda: 0.0014,
    spreadBps: 3.8,
    latencyMs: 9.6,
    regime: "Expansion",
    bidDepthTop5: [175, 138, 112, 88, 69],
    askDepthTop5: [148, 120, 96, 77, 61],
    flash: "up",
    executionPermission: "none",
  },
  {
    symbol: "SOL-USD",
    name: "Solana Perpetual Swap (Prop Desk)",
    track: "competition",
    provider: "hyperliquid",
    venue: "24/7 Prop Perp · Hyperliquid",
    price: 0, // sample price removed: the displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 3.18,
    vpin: 0.354,
    ofi: 0.289,
    kylesLambda: 0.0018,
    spreadBps: 4.5,
    latencyMs: 8.9,
    regime: "Expansion",
    bidDepthTop5: [182, 144, 115, 91, 72],
    askDepthTop5: [145, 116, 92, 74, 58],
    flash: "up",
    executionPermission: "none",
  },
];

function Module02InnerWorkbench() {
  const { role, setRole, profile } = useRoleContext();
  const [trackFilter, setTrackFilter] = useState<"all" | "open_market" | "competition">("all");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("BTC-USD");
  const [chartTimeframe, setChartTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("1s");
  const [listings, setListings] = useState<Module02ListingPacket[]>(INITIAL_MODULE02_LISTINGS);
  const feedSymbols = useMemo(() => listings.map((l) => l.symbol), [listings]);
  const feedQuotes = useFeedQuotes(feedSymbols);
  // Live data fetches from backend API on mount; pollModule02Stream refreshes every 2.5s
  useEffect(() => {
    void pollModule02Stream();
  }, []);
  const [catalogView, setCatalogView] = useState<"cards" | "list">("cards");
  const [infoOpen, setInfoOpen] = useState(false);
  const [streamPaused, setStreamPaused] = useState<boolean>(false);
  const [ringBufferSize, setRingBufferSize] = useState<number>(64);
  const [killSwitchEngaged, setKillSwitchEngaged] = useState<boolean>(false);
  const [rbacBanner, setRbacBanner] = useState<string>(
    "Fixture stream · 9 symbols · labeled synthetic · venue sessions unconfigured · execution_permission: none"
  );
  const [, setFixtureTicks] = useState<LiveCandlePoint[]>([]);
  const fixtureSymbolRef = useRef(selectedSymbol);
  const [feedNote, setFeedNote] = useState("Fixture stream starting");
  const [remainingRoomHud, setRemainingRoomHud] = useState<{
    currentEquityUsd: number;
    startOfDayUsd: number;
    referenceUsd: number;
    dailyFloorUsd: number;
    trailingFloorUsd: number;
    dailyLossLimitPct: number;
    drawdownLimitPct: number;
    drawdownMode: string;
    dailyLossRoomUsd: number;
    dailyLossRoomPct: number;
    trailingDdRoomUsd: number;
    trailingDdRoomPct: number;
  }>({
    currentEquityUsd: 101850.0,
    startOfDayUsd: 102900.0,
    referenceUsd: 103100.0,
    dailyFloorUsd: 98784.0,
    trailingFloorUsd: 94852.0,
    dailyLossLimitPct: 4,
    drawdownLimitPct: 8,
    drawdownMode: "trailing",
    dailyLossRoomUsd: 3066.0,
    dailyLossRoomPct: 2.98,
    trailingDdRoomUsd: 7098.0,
    trailingDdRoomPct: 6.88,
  });

  const pollModule02Stream = useCallback(async () => {
    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? ""
          : "";
      const res = await fetch(`${apiBase}/api/market/module02-snapshot?track=all`, {
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.gateway?.ring_buffer_size === "number") {
          setRingBufferSize(data.gateway.ring_buffer_size);
        }
        if (data.remaining_room_hud) {
          const hud = data.remaining_room_hud;
          setRemainingRoomHud({
            currentEquityUsd: Number(hud.current_equity_usd ?? 101850),
            startOfDayUsd: Number(hud.start_of_day_equity_usd ?? 102900),
            referenceUsd: Number(hud.high_water_mark_usd ?? 103100),
            dailyFloorUsd: Number(hud.daily_floor_usd ?? 0),
            trailingFloorUsd: Number(hud.trailing_floor_usd ?? 0),
            dailyLossLimitPct: Number(hud.daily_loss_limit_pct ?? 4),
            drawdownLimitPct: Number(hud.drawdown_limit_pct ?? 8),
            drawdownMode: String(hud.drawdown_mode ?? "trailing"),
            dailyLossRoomUsd: Number(hud.daily_loss_room_usd ?? 0),
            dailyLossRoomPct: Number(hud.daily_loss_room_pct ?? 0),
            trailingDdRoomUsd: Number(hud.trailing_dd_room_usd ?? 0),
            trailingDdRoomPct: Number(hud.trailing_dd_room_pct ?? 0),
          });
        }
        const origin = String(data.gateway?.feed_origin ?? "labeled_synthetic_fixture");
        const mode = String(data.data_mode ?? (data.gateway?.demo_mode ? "synthetic" : "observed"));
        setFeedNote(
          `${mode} feed · ${origin} · buffer ${data.gateway?.ring_buffer_size ?? "?"} / ${data.gateway?.ring_buffer_maxlen ?? 10000} · venue sessions ${data.gateway?.venue_sessions ?? "unconfigured"} · execution_permission none`
        );
        if (Array.isArray(data.listings) && data.listings.length > 0) {
          setListings((prev) =>
            prev.map((item) => {
              const incoming = data.listings.find(
                (u: { symbol: string }) => String(u.symbol).toUpperCase() === item.symbol
              );
              if (!incoming) return item;
              const nextPrice = Number(incoming.last_price ?? incoming.price ?? item.price);
              const flash: "up" | "down" | "none" =
                nextPrice > item.price ? "up" : nextPrice < item.price ? "down" : item.flash;
              return {
                ...item,
                prevPrice: item.price,
                price: nextPrice,
                vpin: Number(incoming.vpin ?? item.vpin),
                ofi: Number(incoming.ofi ?? item.ofi),
                kylesLambda: Number(incoming.kyles_lambda ?? item.kylesLambda),
                spreadBps: Number(incoming.spread_bps ?? item.spreadBps),
                latencyMs: Number(incoming.latency_ms ?? item.latencyMs),
                regime: String(incoming.regime ?? item.regime),
                bidDepthTop5: Array.isArray(incoming.bid_depth_top5)
                  ? incoming.bid_depth_top5
                  : item.bidDepthTop5,
                askDepthTop5: Array.isArray(incoming.ask_depth_top5)
                  ? incoming.ask_depth_top5
                  : item.askDepthTop5,
                flash,
              };
            })
          );
          return;
        }
      }
    } catch {
      setFeedNote(
        "The market snapshot is unavailable. Prices are frozen at the last received values; no client-side ticks are invented. execution_permission none"
      );
    }
  }, []);

  useEffect(() => {
    void pollModule02Stream();
    if (streamPaused) return;
    const id = setInterval(() => {
      void pollModule02Stream();
    }, 2500);

    let ws: WebSocket | null = null;
    try {
      const wsBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : typeof window !== "undefined"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : "";
      ws = new WebSocket(`${wsBase}/ws/market-stream?symbol=${encodeURIComponent(selectedSymbol)}`);
      ws.onmessage = (evt) => {
        try {
          const incoming = JSON.parse(evt.data);
          if (!incoming || !incoming.symbol) return;
          setListings((prev) =>
            prev.map((item) => {
              if (item.symbol !== String(incoming.symbol).toUpperCase()) return item;
              const nextPrice = Number(incoming.last_price ?? incoming.price ?? item.price);
              const flash: "up" | "down" | "none" =
                nextPrice > item.price ? "up" : nextPrice < item.price ? "down" : item.flash;
              return {
                ...item,
                prevPrice: item.price,
                price: nextPrice,
                vpin: Number(incoming.vpin ?? item.vpin),
                ofi: Number(incoming.ofi ?? item.ofi),
                kylesLambda: Number(incoming.kyles_lambda ?? item.kylesLambda),
                spreadBps: Number(incoming.spread_bps ?? item.spreadBps),
                latencyMs: Number(incoming.latency_ms ?? item.latencyMs),
                regime: String(incoming.regime ?? item.regime),
                bidDepthTop5: Array.isArray(incoming.bid_depth_top5)
                  ? incoming.bid_depth_top5
                  : item.bidDepthTop5,
                askDepthTop5: Array.isArray(incoming.ask_depth_top5)
                  ? incoming.ask_depth_top5
                  : item.askDepthTop5,
                flash,
              };
            })
          );
          if (incoming.remaining_room_hud) {
            const hud = incoming.remaining_room_hud;
            setRemainingRoomHud({
              currentEquityUsd: Number(hud.current_equity_usd ?? 101850),
              startOfDayUsd: Number(hud.start_of_day_equity_usd ?? 102900),
              referenceUsd: Number(hud.high_water_mark_usd ?? 103100),
              dailyFloorUsd: Number(hud.daily_floor_usd ?? 0),
              trailingFloorUsd: Number(hud.trailing_floor_usd ?? 0),
              dailyLossLimitPct: Number(hud.daily_loss_limit_pct ?? 4),
              drawdownLimitPct: Number(hud.drawdown_limit_pct ?? 8),
              drawdownMode: String(hud.drawdown_mode ?? "trailing"),
              dailyLossRoomUsd: Number(hud.daily_loss_room_usd ?? 0),
              dailyLossRoomPct: Number(hud.daily_loss_room_pct ?? 0),
              trailingDdRoomUsd: Number(hud.trailing_dd_room_usd ?? 0),
              trailingDdRoomPct: Number(hud.trailing_dd_room_pct ?? 0),
            });
          }
        } catch {
          // Ignore malformed frame
        }
      };
    } catch {
      // Fallback to HTTP snapshot polling if WebSocket unavailable
    }

    return () => {
      clearInterval(id);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [pollModule02Stream, selectedSymbol, streamPaused]);

  const filteredListings = useMemo(() => {
    if (trackFilter === "all") return listings;
    return listings.filter((l) => l.track === trackFilter);
  }, [listings, trackFilter]);

  const activeListing = useMemo(
    () => listings.find((l) => l.symbol === selectedSymbol) ?? listings[0],
    [listings, selectedSymbol]
  );

  useEffect(() => {
    const price = activeListing.price;
    const symbol = activeListing.symbol;
    const changed = fixtureSymbolRef.current !== symbol;
    fixtureSymbolRef.current = symbol;
    const stamp = new Date().toISOString();
    setFixtureTicks((prev) => {
      const history = changed ? [] : prev;
      const last = history[history.length - 1];
      if (last && Math.abs(last.close - price) < 1e-9) return history;
      const open = last?.close ?? price;
      return [...history, {
        timestamp: stamp,
        open,
        high: Math.max(open, price),
        low: Math.min(open, price),
        close: price,
        volume: 1,
      }].slice(-120);
    });
  }, [activeListing.symbol, activeListing.price]);

  return (
    <div className="institutional-shell">
      {/* Persistent Top Command Header */}
      <header className="clean-top-bar">
        <div className="clean-brand">
          <AtlasLogo size={30} />
          <div>
            <div className="clean-brand-title">ATLAS Markets</div>
            <div className="clean-brand-sub">
              Stocks, crypto, ETFs, and forex · execution_permission none
            </div>
          </div>
        </div>

        {/* Role-Gated Kill Switch */}
        <div className="clean-top-actions">
          <span className="badge badge-emerald">Ring Buffer: {ringBufferSize.toLocaleString()} / 10,000</span>
          {killSwitchEngaged ? (
            <SafeStopReleaseCli compact />
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-outline"
              disabled={!profile.canTriggerKillSwitch}
              aria-pressed={killSwitchEngaged}
              title={killSwitchEngaged ? "Turn the paper desk back on." : "Turn the paper desk off. New orders stop."}
              onClick={() => {
                if (!profile.canTriggerKillSwitch) {
                  setRbacBanner("Only the admin role can turn the desk off.");
                  return;
                }
                const next = !killSwitchEngaged;
                void fetch("/api/control/kill-switch", {
                  method: "POST",
                  headers: { "Content-Type": "application/json", "X-Atlas-Role": role },
                  body: JSON.stringify({
                    engaged: next,
                    reason: next ? "listings_emergency_kill_switch" : "listings_operator_reset",
                  }),
                }).then(async (response) => {
                  if (!response.ok) {
                    setRbacBanner("The desk did not change. The control plane state is unchanged.");
                    return;
                  }
                  const state = await response.json();
                  setKillSwitchEngaged(Boolean(state.kill_switch_engaged));
                  setRbacBanner(
                    state.kill_switch_engaged
                      ? "The desk is off. Open paper positions were closed."
                      : "The desk is on. Paper orders can be submitted again."
                  );
                }).catch(() => {
                  setRbacBanner("The desk did not change. State is unconfirmed.");
                });
              }}
            >
              Engage Safe stop
            </button>
          )}
        </div>
      </header>

      <div className="clean-main-scroll" style={{ padding: "18px 24px" }}>
        {/* Asset catalog first: the cards are the page's main job. */}
        <div className="asset-toolbar">
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "all" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "13px" }}
              onClick={() => setTrackFilter("all")}
            >
              <GuideIcon name="all" />
              All (9)
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "open_market" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "13px" }}
              onClick={() => {
                setTrackFilter("open_market");
                setSelectedSymbol("NVDA");
              }}
            >
              <GuideIcon name="equity" color={trackFilter === "open_market" ? "#FFFFFF" : markColor("equity")} />
              Stocks & ETFs (6)
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "competition" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "13px" }}
              onClick={() => {
                setTrackFilter("competition");
                setSelectedSymbol("BTC-USD");
              }}
            >
              <GuideIcon name="crypto" color={trackFilter === "competition" ? "#FFFFFF" : markColor("crypto")} />
              Crypto perps (3)
            </button>
          </div>
          <div className="seg" role="group" aria-label="Catalog view">
            <button type="button" className={`clean-tf-btn ${catalogView === "cards" ? "active" : ""}`} aria-pressed={catalogView === "cards"} style={{ padding: "7px 12px", fontSize: "13px" }} onClick={() => setCatalogView("cards")}>Cards</button>
            <button type="button" className={`clean-tf-btn ${catalogView === "list" ? "active" : ""}`} aria-pressed={catalogView === "list"} style={{ padding: "7px 12px", fontSize: "13px" }} onClick={() => setCatalogView("list")}>List</button>
          </div>
        </div>

        {catalogView === "cards" ? (
          <div className="asset-grid">
            {filteredListings.map((item) => (
              <AssetCard
                key={item.symbol}
                symbol={item.symbol}
                name={item.name.replace(/ \(SEC CIK \d+\)$/, "")}
                kind={item.track === "open_market" ? "Stock / ETF" : "Crypto perp"}
                venue={item.venue}
                quote={feedQuotes[item.symbol]}
                selected={item.symbol === selectedSymbol}
                onSelect={() => setSelectedSymbol(item.symbol)}
                details={[
                  { label: "Regime", value: item.regime, tone: "info" },
                  { label: "Rolling VPIN", value: `${(item.vpin * 100).toFixed(1)}%`, tone: item.vpin > 0.4 ? "warn" : "up" },
                  { label: "Top-5 L2 OFI", value: `${item.ofi >= 0 ? "+" : ""}${item.ofi.toFixed(3)}`, tone: item.ofi >= 0 ? "up" : "down" },
                  { label: "Kyle's λ", value: item.kylesLambda.toFixed(4), tone: "info" },
                  { label: "ATR stop", value: item.vpin > 0.35 ? "1.5× widened" : "Armed", tone: "info" },
                ]}
                footnote={`Microstructure figures are from the ${feedNote.split(" · ")[0] || "fixture"} snapshot, not the quote feed. execution_permission none`}
              />
            ))}
          </div>
        ) : (
          <AssetTable
            rows={filteredListings.map((i) => ({ symbol: i.symbol, name: i.name.replace(/ \(SEC CIK \d+\)$/, ""), kind: i.track === "open_market" ? "Stock / ETF" : "Crypto perp" }))}
            quotes={feedQuotes}
            selected={selectedSymbol}
            onSelect={setSelectedSymbol}
          />
        )}

        <div className="clean-card selected-market-viewer">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <strong>{activeListing.symbol} - chart and model inputs</strong>
            {(["1s", "1m", "5m", "15m", "1h", "1D"] as const).map(interval => <button key={interval} type="button" className={`clean-tf-btn${chartTimeframe === interval ? " is-active" : ""}`} aria-pressed={chartTimeframe === interval} onClick={() => setChartTimeframe(interval)}>{interval === "1s" ? "Real time" : interval}</button>)}
          </div>
          <DeskChart symbol={activeListing.symbol} modelSymbol={activeListing.symbol} timeframe={chartTimeframe} frameClassName="desk-chart-frame" onOpenMinute={() => setChartTimeframe("1m")} />
        </div>


        {/* Real-Time Remaining-Room HUD (Task C & Task D.2) */}
        <div className="clean-kpi-row" style={{ marginBottom: "16px" }}>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Mark-to-Market Open Equity</span>
            <span className="clean-kpi-value">${remainingRoomHud.currentEquityUsd.toLocaleString()}</span>
            <span className="clean-kpi-sub" style={{ color: "#00F29D" }}>
              SOD ${remainingRoomHud.startOfDayUsd.toLocaleString()} · reference ${remainingRoomHud.referenceUsd.toLocaleString()}
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Daily Loss Cushion ({remainingRoomHud.dailyLossLimitPct.toFixed(1)}%)</span>
            <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
              ${remainingRoomHud.dailyLossRoomUsd.toLocaleString()}
            </span>
            <span className="clean-kpi-sub">
              {remainingRoomHud.dailyLossRoomPct.toFixed(2)}% buffer remaining before auto-flatten
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">
              {remainingRoomHud.drawdownMode === "static" ? "Static" : "Trailing"} Drawdown Cushion ({remainingRoomHud.drawdownLimitPct.toFixed(1)}%)
            </span>
            <span className="clean-kpi-value" style={{ color: "#00C8FF" }}>
              ${remainingRoomHud.trailingDdRoomUsd.toLocaleString()}
            </span>
            <span className="clean-kpi-sub">
              {remainingRoomHud.trailingDdRoomPct.toFixed(2)}% buffer remaining above ${remainingRoomHud.trailingFloorUsd.toLocaleString()} floor
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">500ms Feed Freshness Breaker</span>
            <span className="clean-kpi-value" style={{ color: "#00F29D" }}>
              {activeListing.latencyMs.toFixed(1)}ms
            </span>
            <span className="clean-kpi-sub">
              Competition freshness gate 500ms · fixture venue label {activeListing.provider}
            </span>
          </div>
        </div>


        <details className="ux-collapse">
          <summary>Desk context<span className="ux-collapse-hint">role, feed origin, ring buffer</span></summary>
          <div className="ux-collapse-body">
        {/* RBAC Client Segment Selector Strip (Section 2) */}
        <div className="clean-card" style={{ marginBottom: "16px", padding: "14px 18px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ minWidth: 0, width: "100%" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <span className="badge badge-blue">RBAC CLIENT SEGMENT SEGREGATION</span>
                <strong style={{ fontSize: "14px", color: "#F8FAFC" }}>{profile.title}</strong>
                <span className="mono-cell" style={{ fontSize: "11.5px", color: "#00F29D" }}>
                  execution_permission: {profile.executionPermission}
                </span>
              </div>
              <div style={{ fontSize: "12px", color: "#94A3B8", marginTop: "4px" }}>{profile.focusSummary}</div>
            </div>

            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {(Object.keys(CLIENT_ROLE_PROFILES) as ClientRoleId[]).map((rKey) => {
                const rMeta = CLIENT_ROLE_PROFILES[rKey];
                return (
                  <button
                    key={rKey}
                    type="button"
                    className={`clean-tf-btn ${role === rKey ? "active" : ""}`}
                    style={{ padding: "6px 12px", fontSize: "12px" }}
                    onClick={() => {
                      setRole(rKey);
                      setRbacBanner(
                        `Switched RBAC Client Context to '${rKey}' (${rMeta.title}) · execution_permission=${rMeta.executionPermission}`
                      );
                    }}
                  >
                    {rKey} · {rMeta.segment.split(" ")[0]}
                  </button>
                );
              })}
            </div>
          </div>

          <div
            className="mono-cell"
            style={{
              marginTop: "10px",
              padding: "8px 12px",
              borderRadius: "6px",
              background: "#070A0F",
              border: "1px solid rgba(0, 200, 255, 0.25)",
              fontSize: "11.5px",
              color: "#00C8FF",
            }}
          >
            {rbacBanner}
            <div style={{ marginTop: 4, color: "#94A3B8" }}>{feedNote}</div>
          </div>
        </div>

          <AssetMarkLegend />
          </div>
        </details>

        <details className="ux-collapse" onToggle={(e) => setInfoOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>{activeListing.symbol} profile<span className="ux-collapse-hint">TradingView symbol info (loads when opened)</span></summary>
          <div className="ux-collapse-body">{infoOpen ? <TradingViewStockInfo symbol={activeListing.symbol} timeframe={chartTimeframe} /> : null}</div>
        </details>

        <TradingViewMarkets />
      </div>
    </div>
  );
}

export function Module02ListingsView() {
  return (
    <RoleProvider initialRole="prop_firm_admin">
      <Module02InnerWorkbench />
    </RoleProvider>
  );
}

export default Module02ListingsView;

