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
import { type LiveCandlePoint } from "./liveTypes";
import { tradingViewUrl } from "./AtlasChart";
import { DeskChart } from "./DeskChart";
import { SafeStopReleaseCli } from "../safety/SafeStopReleaseCli";
import { useFeedQuotes } from "../../lib/feedQuotes";
import { AssetCard, AssetTable } from "./AssetCard";

export type AuthenticAssetCategory = "metals" | "etfs" | "futures" | "fx" | "stocks" | "crypto";

export interface Module02ListingPacket {
  symbol: string;
  name: string;
  track: "open_market" | "competition";
  category: AuthenticAssetCategory;
  subCategory: string;
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

function makePacket(
  symbol: string,
  name: string,
  category: AuthenticAssetCategory,
  subCategory: string,
  venue: string,
  track: "open_market" | "competition" = "open_market",
  provider: Module02ListingPacket["provider"] = "databento",
  spreadBps = 1.4
): Module02ListingPacket {
  return {
    symbol,
    name,
    track,
    category,
    subCategory,
    provider,
    venue,
    price: 0, // displayed price comes from the ATLAS feed
    prevPrice: 0,
    changePct: 0,
    vpin: 0.24,
    ofi: 0.16,
    kylesLambda: 0.0012,
    spreadBps,
    latencyMs: 6.8,
    regime: "Compression",
    bidDepthTop5: [150, 120, 95, 80, 60],
    askDepthTop5: [130, 105, 88, 72, 54],
    flash: "none",
    executionPermission: "none",
  };
}

const INITIAL_MODULE02_LISTINGS: Module02ListingPacket[] = [
  // Gold & Silver (Precious Metals Futures & Physical Trust ETFs)
  makePacket("GC", "Gold Futures — COMEX Front Month (XAU/USD)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 0.8),
  makePacket("MGC", "Micro Gold Futures — COMEX (10 troy oz)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 1.0),
  makePacket("SI", "Silver Futures — COMEX Front Month (XAG/USD)", "metals", "Precious Metals Future", "CME Globex · COMEX Metals", "open_market", "databento", 1.2),
  makePacket("GLD", "SPDR Gold Shares Physical Bullion Trust ETF", "metals", "Physical Gold ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.0),
  makePacket("SLV", "iShares Silver Trust Physical Bullion ETF", "metals", "Physical Silver ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.4),

  // Authentic ETFs — Broad Equity Index, Treasury/Bond, Sector, Semiconductor & Real Estate
  makePacket("SPY", "SPDR S&P 500 ETF Trust", "etfs", "US Broad Index ETF", "NYSE Arca · SIP L2", "open_market", "databento", 0.9),
  makePacket("QQQ", "Invesco QQQ Trust (Nasdaq-100)", "etfs", "US Broad Index ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.1),
  makePacket("IWM", "iShares Russell 2000 Small-Cap ETF", "etfs", "US Broad Index ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.3),
  makePacket("DIA", "SPDR Dow Jones Industrial Average ETF", "etfs", "US Broad Index ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("VOO", "Vanguard S&P 500 ETF", "etfs", "US Broad Index ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.0),
  makePacket("VTI", "Vanguard Total Stock Market ETF", "etfs", "US Broad Index ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.1),
  makePacket("TLT", "iShares 20+ Year US Treasury Bond ETF", "etfs", "Treasury & Bond ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.1),
  makePacket("IEF", "iShares 7-10 Year US Treasury Bond ETF", "etfs", "Treasury & Bond ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.1),
  makePacket("SHY", "iShares 1-3 Year US Treasury Bond ETF", "etfs", "Treasury & Bond ETF", "Nasdaq · SIP L2", "open_market", "databento", 0.9),
  makePacket("AGG", "iShares Core US Aggregate Bond ETF", "etfs", "Treasury & Bond ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.0),
  makePacket("BND", "Vanguard Total Bond Market ETF", "etfs", "Treasury & Bond ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.0),
  makePacket("LQD", "iShares iBoxx Investment Grade Corporate Bond ETF", "etfs", "Corporate Bond ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("HYG", "iShares iBoxx High Yield Corporate Bond ETF", "etfs", "High-Yield Bond ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.4),
  makePacket("XLK", "Technology Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("XLF", "Financial Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("XLE", "Energy Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.3),
  makePacket("XLV", "Health Care Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("XLI", "Industrial Select Sector SPDR Fund ETF", "etfs", "US Sector ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.2),
  makePacket("SOXX", "iShares Semiconductor ETF", "etfs", "Semiconductor ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.5),
  makePacket("SMH", "VanEck Semiconductor ETF", "etfs", "Semiconductor ETF", "Nasdaq · SIP L2", "open_market", "databento", 1.4),
  makePacket("VNQ", "Vanguard Real Estate Index Fund ETF", "etfs", "Real Estate REIT ETF", "NYSE Arca · SIP L2", "open_market", "databento", 1.4),
  makePacket("ARKK", "ARK Innovation Active ETF", "etfs", "Thematic Growth ETF", "NYSE Arca · SIP L2", "open_market", "databento", 2.0),

  // CME Globex Futures — Equity Index, Energy, Treasury Rates & Currency Futures
  makePacket("ES", "E-mini S&P 500 Futures (Front Month)", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 0.5),
  makePacket("NQ", "E-mini Nasdaq-100 Futures (Front Month)", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 0.6),
  makePacket("YM", "E-mini Dow ($5) Futures", "futures", "CME Equity Index Future", "CME Globex · CBOT", "open_market", "databento", 0.8),
  makePacket("RTY", "E-mini Russell 2000 Futures", "futures", "CME Equity Index Future", "CME Globex · GLBX.MDP3", "open_market", "databento", 1.0),
  makePacket("CL", "WTI Light Sweet Crude Oil Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 0.9),
  makePacket("MCL", "Micro WTI Crude Oil Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 1.1),
  makePacket("NG", "Henry Hub Natural Gas Futures", "futures", "NYMEX Energy Future", "CME Globex · NYMEX", "open_market", "databento", 1.6),
  makePacket("ZN", "10-Year US Treasury Note Futures", "futures", "CBOT Treasury Rate Future", "CME Globex · CBOT", "open_market", "databento", 0.6),
  makePacket("ZB", "30-Year US Treasury Bond Futures", "futures", "CBOT Treasury Rate Future", "CME Globex · CBOT", "open_market", "databento", 0.8),
  makePacket("6E", "Euro FX Futures (CME Globex)", "futures", "CME Currency Future", "CME Globex · FX", "open_market", "databento", 0.7),
  makePacket("6J", "Japanese Yen Futures (CME Globex)", "futures", "CME Currency Future", "CME Globex · FX", "open_market", "databento", 0.8),

  // Official Central-Bank & Interbank Spot FX
  makePacket("EUR_USD", "Euro / US Dollar Spot FX (ECB & Interbank)", "fx", "G10 Spot FX", "ECB SDMX & Global FX", "open_market", "databento", 0.6),
  makePacket("USD_CAD", "US Dollar / Canadian Dollar Spot FX (BoC Valet)", "fx", "G10 Spot FX", "Bank of Canada & Global FX", "open_market", "databento", 0.7),

  // SEC-Verified US Equities
  makePacket("NVDA", "NVIDIA Corp. (SEC CIK 0001045810)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.5),
  makePacket("AAPL", "Apple Inc. (SEC CIK 0000320193)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "databento", 1.2),
  makePacket("MSFT", "Microsoft Corp. (SEC CIK 0000789019)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.2),
  makePacket("AMZN", "Amazon.com Inc.", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.3),
  makePacket("META", "Meta Platforms Inc.", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.4),
  makePacket("GOOGL", "Alphabet Inc. Class A", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.3),
  makePacket("TSLA", "Tesla Inc. (SEC CIK 0001318605)", "stocks", "US Large-Cap Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 2.0),
  makePacket("AMD", "Advanced Micro Devices Inc.", "stocks", "US Semiconductor Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.7),
  makePacket("AVGO", "Broadcom Inc.", "stocks", "US Semiconductor Equity", "Nasdaq Global Select · XNAS", "open_market", "polygon", 1.6),
  makePacket("JPM", "JPMorgan Chase & Co.", "stocks", "US Money-Center Bank", "NYSE · Regular Session", "open_market", "databento", 1.2),
  makePacket("GS", "The Goldman Sachs Group Inc.", "stocks", "US Investment Bank", "NYSE · Regular Session", "open_market", "databento", 1.4),
  makePacket("LLY", "Eli Lilly and Company", "stocks", "US Pharmaceuticals", "NYSE · Regular Session", "open_market", "databento", 1.5),
  makePacket("XOM", "Exxon Mobil Corporation", "stocks", "US Integrated Energy", "NYSE · Regular Session", "open_market", "databento", 1.2),

  // Major Liquid Crypto (24/7 Spot & Prop Desk)
  makePacket("BTC-USD", "Bitcoin Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "ccxt_pro", 2.5),
  makePacket("ETH-USD", "Ethereum Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 3.0),
  makePacket("SOL-USD", "Solana Spot / Perpetual Benchmark", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "hyperliquid", 3.8),
  makePacket("AVAX-USD", "Avalanche Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.2),
  makePacket("LINK-USD", "Chainlink Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.0),
  makePacket("AAVE-USD", "Aave Protocol Spot / Perpetual", "crypto", "Major Liquid Crypto", "24/7 Coinbase / Binance / Kraken", "competition", "coinbase", 4.5),
];

function Module02InnerWorkbench() {
  const { role, setRole, profile } = useRoleContext();
  const [categoryFilter, setCategoryFilter] = useState<"all" | AuthenticAssetCategory>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("GC");
  const [chartTimeframe, setChartTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("15m");
  const [listings, setListings] = useState<Module02ListingPacket[]>(INITIAL_MODULE02_LISTINGS);
  const feedSymbols = useMemo(() => listings.map((l) => l.symbol), [listings]);
  const feedQuotes = useFeedQuotes(feedSymbols);
  // Live data fetches from backend API on mount; pollModule02Stream refreshes every 2.5s
  useEffect(() => {
    void pollModule02Stream();
  }, []);
  const [catalogView, setCatalogView] = useState<"cards" | "list">("cards");
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

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: listings.length, metals: 0, etfs: 0, futures: 0, fx: 0, stocks: 0, crypto: 0 };
    for (const item of listings) {
      counts[item.category] = (counts[item.category] ?? 0) + 1;
    }
    return counts;
  }, [listings]);

  const filteredListings = useMemo(() => {
    const q = searchQuery.trim().toUpperCase();
    return listings.filter((l) => {
      if (categoryFilter !== "all" && l.category !== categoryFilter) return false;
      if (!q) return true;
      return (
        l.symbol.toUpperCase().includes(q) ||
        l.name.toUpperCase().includes(q) ||
        l.subCategory.toUpperCase().includes(q) ||
        l.venue.toUpperCase().includes(q)
      );
    });
  }, [listings, categoryFilter, searchQuery]);

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
            <div className="clean-brand-title">ATLAS Authentic Assets Catalog</div>
            <div className="clean-brand-sub">
              Gold &amp; Silver, ETFs (Index, Treasury/Bond, Sector), CME Futures, Spot FX, SEC Stocks &amp; Major Crypto · execution_permission none
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
        <div className="asset-toolbar" style={{ flexWrap: "wrap", gap: "10px" }}>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "all" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => setCategoryFilter("all")}
            >
              <GuideIcon name="all" />
              All Authentic ({categoryCounts.all})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "metals" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("metals");
                setSelectedSymbol("GC");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "metals" ? "#FFFFFF" : markColor("futures")} />
              Gold &amp; Silver ({categoryCounts.metals})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "etfs" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("etfs");
                setSelectedSymbol("SPY");
              }}
            >
              <GuideIcon name="equity" color={categoryFilter === "etfs" ? "#FFFFFF" : markColor("equity")} />
              ETFs ({categoryCounts.etfs})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "futures" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("futures");
                setSelectedSymbol("ES");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "futures" ? "#FFFFFF" : markColor("futures")} />
              CME Futures ({categoryCounts.futures})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "fx" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("fx");
                setSelectedSymbol("EUR_USD");
              }}
            >
              <GuideIcon name="futures" color={categoryFilter === "fx" ? "#FFFFFF" : markColor("futures")} />
              Spot FX ({categoryCounts.fx})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "stocks" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("stocks");
                setSelectedSymbol("NVDA");
              }}
            >
              <GuideIcon name="equity" color={categoryFilter === "stocks" ? "#FFFFFF" : markColor("equity")} />
              US Stocks ({categoryCounts.stocks})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${categoryFilter === "crypto" ? "active" : ""}`}
              style={{ padding: "7px 12px", fontSize: "12.5px" }}
              onClick={() => {
                setCategoryFilter("crypto");
                setSelectedSymbol("BTC-USD");
              }}
            >
              <GuideIcon name="crypto" color={categoryFilter === "crypto" ? "#FFFFFF" : markColor("crypto")} />
              Major Crypto ({categoryCounts.crypto})
            </button>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter Gold, Silver, ETF, Future, FX, Stock..."
              aria-label="Filter authentic assets"
              style={{
                padding: "6px 12px",
                fontSize: "12.5px",
                borderRadius: "6px",
                border: "1px solid rgba(148, 163, 184, 0.28)",
                background: "rgba(15, 23, 42, 0.65)",
                color: "#F8FAFC",
                minWidth: "240px",
              }}
            />
            <div className="seg" role="group" aria-label="Catalog view">
              <button type="button" className={`clean-tf-btn ${catalogView === "cards" ? "active" : ""}`} aria-pressed={catalogView === "cards"} style={{ padding: "7px 12px", fontSize: "13px" }} onClick={() => setCatalogView("cards")}>Cards</button>
              <button type="button" className={`clean-tf-btn ${catalogView === "list" ? "active" : ""}`} aria-pressed={catalogView === "list"} style={{ padding: "7px 12px", fontSize: "13px" }} onClick={() => setCatalogView("list")}>List</button>
            </div>
          </div>
        </div>

        {catalogView === "cards" ? (
          <div className="asset-grid">
            {filteredListings.map((item) => (
              <AssetCard
                key={item.symbol}
                symbol={item.symbol}
                name={item.name.replace(/ \(SEC CIK \d+\)$/, "")}
                kind={item.subCategory}
                venue={item.venue}
                quote={feedQuotes[item.symbol]}
                selected={item.symbol === selectedSymbol}
                onSelect={() => setSelectedSymbol(item.symbol)}
              />
            ))}
          </div>
        ) : (
          <AssetTable
            rows={filteredListings.map((i) => ({ symbol: i.symbol, name: i.name.replace(/ \(SEC CIK \d+\)$/, ""), kind: i.subCategory }))}
            quotes={feedQuotes}
            selected={selectedSymbol}
            onSelect={setSelectedSymbol}
          />
        )}

        <div className="clean-card selected-market-viewer">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <strong>{activeListing.symbol} - chart and model inputs</strong>
          </div>
          <DeskChart symbol={activeListing.symbol} modelSymbol={activeListing.symbol} timeframe={chartTimeframe} frameClassName="desk-chart-frame" onTimeframe={(tf) => { if (["1s", "1m", "5m", "15m", "1h", "1D"].includes(tf)) setChartTimeframe(tf as typeof chartTimeframe); }} />
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

        <p className="ux-collapse-hint" style={{ margin: "4px 0" }}>
          Watchlist scan (pivots, Fibonacci, zones, VWAP, volume profile): <a href="/research?tab=scan">Scan &amp; Pine</a>.{" "}
          <a href={tradingViewUrl(activeListing.symbol)} target="_blank" rel="noopener noreferrer">Open {activeListing.symbol} in TradingView ↗</a>
        </p>
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

