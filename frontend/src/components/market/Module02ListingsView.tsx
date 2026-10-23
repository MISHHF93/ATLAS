"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CLIENT_ROLE_PROFILES,
  RoleProvider,
  useRoleContext,
  type ClientRoleId,
} from "../../context/RoleContext";
import { AtlasLogo } from "../shell/AtlasLogo";
import { AppNav } from "../shell/AppNav";
import { AssetMarkLegend, GuideIcon, markColor, markForSymbol } from "../shell/guideIcons";
import { type LiveCandlePoint } from "./LiveChartEngine";
import { TradingViewStockInfo } from "./TradingViewChart";
import { DeskChart } from "./DeskChart";
import { TradingViewMarkets } from "./TradingViewMarkets";

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
    price: 584.2,
    prevPrice: 583.95,
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
    price: 142.1,
    prevPrice: 141.8,
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
    price: 231.45,
    prevPrice: 231.2,
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
    price: 428.9,
    prevPrice: 428.65,
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
    price: 498.6,
    prevPrice: 498.1,
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
    price: 254.3,
    prevPrice: 254.85,
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
    price: 68410.0,
    prevPrice: 68365.0,
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
    price: 2645.5,
    prevPrice: 2641.2,
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
    price: 176.8,
    prevPrice: 176.1,
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
  // Live data fetches from backend API on mount; pollModule02Stream refreshes every 2.5s
  useEffect(() => {
    void pollModule02Stream();
  }, []);
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
          `${mode} feed A� ${origin} A� buffer ${data.gateway?.ring_buffer_size ?? "?"} / ${data.gateway?.ring_buffer_maxlen ?? 10000} A� venue sessions ${data.gateway?.venue_sessions ?? "unconfigured"} A� execution_permission none`
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
      <AppNav />
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
            {killSwitchEngaged ? "Resume paper trading" : "Halt paper trading"}
          </button>
        </div>
      </header>

      <div className="clean-main-scroll" style={{ padding: "18px 24px" }}>
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

        <div className="clean-card selected-market-viewer">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <strong>{activeListing.symbol} - chart and model inputs</strong>
            {(["1s", "1m", "5m", "15m", "1h", "1D"] as const).map(interval => <button key={interval} type="button" className={`clean-tf-btn${chartTimeframe === interval ? " is-active" : ""}`} aria-pressed={chartTimeframe === interval} onClick={() => setChartTimeframe(interval)}>{interval === "1s" ? "Real time" : interval}</button>)}
          </div>
          <DeskChart symbol={activeListing.symbol} modelSymbol={activeListing.symbol} timeframe={chartTimeframe} frameClassName="desk-chart-frame" onOpenMinute={() => setChartTimeframe("1m")} />
        </div>

        <TradingViewStockInfo symbol={activeListing.symbol} timeframe={chartTimeframe} />

        <TradingViewMarkets />

        {/* Dual-Track Filter Bar & Stream Controls (Task D.1) */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "10px",
            marginBottom: "14px",
          }}
        >
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "all" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "12.5px" }}
              onClick={() => setTrackFilter("all")}
            >
              <GuideIcon name="all" />
              All Dual-Track Listings (9)
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "open_market" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "12.5px" }}
              onClick={() => {
                setTrackFilter("open_market");
                setSelectedSymbol("NVDA");
              }}
            >
              <GuideIcon name="equity" color={trackFilter === "open_market" ? "#FFFFFF" : markColor("equity")} />
              Open-Market Equities · NYSE/SIP (6)
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${trackFilter === "competition" ? "active" : ""}`}
              style={{ padding: "7px 14px", fontSize: "12.5px" }}
              onClick={() => {
                setTrackFilter("competition");
                setSelectedSymbol("BTC-USD");
              }}
            >
              <GuideIcon name="crypto" color={trackFilter === "competition" ? "#FFFFFF" : markColor("crypto")} />
              Prop Competition Crypto Perps · 24/7 (3)
            </button>
          </div>
          <AssetMarkLegend />

          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span className="badge badge-emerald">⚡ ZERO-TOUCH STREAMING ACTIVE (2.5s)</span>
          </div>
        </div>

        {/* Real-Time Ticker Cards Grid with Green/Red Flash & Live VPIN/OFI/Kyle's Lambda Badges */}
        <div className="clean-grid-3" style={{ marginBottom: "18px" }}>
          {filteredListings.map((item) => {
            const isSelected = item.symbol === selectedSymbol;
            const flashBorder =
              item.flash === "up"
                ? "rgba(0, 242, 157, 0.45)"
                : item.flash === "down"
                ? "rgba(255, 59, 105, 0.45)"
                : "rgba(255, 255, 255, 0.08)";
            return (
              <div
                key={item.symbol}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedSymbol(item.symbol)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedSymbol(item.symbol);
                }}
                className="clean-card"
                style={{
                  cursor: "pointer",
                  padding: "14px 16px",
                  borderColor: isSelected ? "#00C8FF" : flashBorder,
                  background:
                    item.flash === "up"
                      ? "linear-gradient(135deg, rgba(0, 242, 157, 0.07) 0%, #121722 65%)"
                      : item.flash === "down"
                      ? "linear-gradient(135deg, rgba(255, 59, 105, 0.07) 0%, #121722 65%)"
                      : "#121722",
                  transition: "all 0.25s ease",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <GuideIcon name={markForSymbol(item.symbol)} color={markColor(markForSymbol(item.symbol))} />
                      <strong
                        style={{
                          fontSize: "16px",
                          color: "#F8FAFC",
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {item.symbol}
                      </strong>
                      <span
                        className={`badge ${
                          item.track === "open_market" ? "badge-blue" : "badge-emerald"
                        }`}
                      >
                        {item.track === "open_market" ? "OPEN-MARKET" : "PROP PERP"}
                      </span>
                      <span className="clean-meta-tag" style={{ fontSize: "10px" }}>
                        {item.regime}
                      </span>
                    </div>
                    <div style={{ fontSize: "11.5px", color: "#94A3B8", marginTop: "3px" }}>
                      {item.name} · {item.venue}
                    </div>
                  </div>

                  <div style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>
                    <div
                      style={{
                        fontSize: "17px",
                        fontWeight: 800,
                        color: item.flash === "up" ? "#00F29D" : item.flash === "down" ? "#FF3B69" : "#F8FAFC",
                      }}
                    >
                      ${item.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </div>
                    <div
                      style={{
                        fontSize: "11.5px",
                        color: item.changePct >= 0 ? "#00F29D" : "#FF3B69",
                      }}
                    >
                      {item.changePct >= 0 ? "▲ +" : "▼ "}
                      {item.changePct.toFixed(2)}% · {item.latencyMs.toFixed(1)}ms
                    </div>
                  </div>
                </div>

                {/* Live VPIN, Multi-Level OFI, and Kyle's Lambda Gauge Badges */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                    gap: "6px",
                    marginTop: "12px",
                  }}
                >
                  <div
                    style={{
                      background: "#070A0F",
                      padding: "6px 8px",
                      borderRadius: "6px",
                      border: "1px solid rgba(255,255,255,0.06)",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748B" }}>ROLLING VPIN</div>
                    <div
                      className="mono-cell"
                      style={{
                        fontSize: "12px",
                        fontWeight: 700,
                        color: item.vpin > 0.4 ? "#F59E0B" : "#00F29D",
                      }}
                    >
                      {(item.vpin * 100).toFixed(1)}%
                    </div>
                  </div>

                  <div
                    style={{
                      background: "#070A0F",
                      padding: "6px 8px",
                      borderRadius: "6px",
                      border: "1px solid rgba(255,255,255,0.06)",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748B" }}>TOP-5 L2 OFI</div>
                    <div
                      className="mono-cell"
                      style={{
                        fontSize: "12px",
                        fontWeight: 700,
                        color: item.ofi >= 0 ? "#00F29D" : "#FF3B69",
                      }}
                    >
                      {item.ofi >= 0 ? "+" : ""}
                      {item.ofi.toFixed(3)}
                    </div>
                  </div>

                  <div
                    style={{
                      background: "#070A0F",
                      padding: "6px 8px",
                      borderRadius: "6px",
                      border: "1px solid rgba(255,255,255,0.06)",
                    }}
                  >
                    <div style={{ fontSize: "10px", color: "#64748B" }}>KYLE&apos;S λ IMPACT</div>
                    <div className="mono-cell" style={{ fontSize: "12px", fontWeight: 700, color: "#00C8FF" }}>
                      {item.kylesLambda.toFixed(4)}
                    </div>
                  </div>
                </div>

                {/* Autonomous Whale Policy Signal & Control Plane Bracket Strip */}
                <div
                  style={{
                    marginTop: "8px",
                    paddingTop: "8px",
                    borderTop: "1px solid rgba(255,255,255,0.06)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: "11px",
                  }}
                >
                  <span
                    className="mono-cell"
                    style={{
                      fontWeight: 700,
                      color: item.ofi >= 0 ? "#00F29D" : "#FF3B69",
                    }}
                  >
                    {item.ofi >= 0 ? "Buy imbalance" : "Sell imbalance"} · OFI {item.ofi.toFixed(2)} · fixture
                  </span>
                  <span className="mono-cell" style={{ color: "#94A3B8" }}>
                    ATR Stop {item.vpin > 0.35 ? "1.5× Widened" : "Armed"} · perm: none
                  </span>
                </div>
              </div>
            );
          })}
        </div>


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

