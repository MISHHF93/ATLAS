"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type LiveCandlePoint } from "../market/liveTypes";
import { WhaleOnChart } from "../market/WhaleOnChart";
import { DeskChart } from "../market/DeskChart";
import { type LiveSnapshot } from "../market/liveTypes";
import { AssetMarkLegend, GuideIcon, markColor, markForAsset, markLabel, type GuideIconName } from "../shell/guideIcons";
import { CLIENT_ROLE_PROFILES, useRoleContext, type ClientRoleId } from "../../context/RoleContext";
import { fetchLibraryQuotes, libraryQuoteSymbols } from "../../lib/libraryQuotes";
import type { FeedQuote } from "../../lib/feedQuotes";
import { QuoteMeta } from "../market/QuoteBadge";
import { loadMarketBars, mergeTickIntoBars } from "../../lib/marketBars";

const TIMEFRAME_SECONDS = { "1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1D": 86400 } as const;

export interface CatalogListingItem {
  symbol: string;
  name: string;
  asset_class: "equities" | "crypto_perps" | "futures";
  exchange: string;
  tick_size: number;
  lot_size: number;
  min_notional: number;
  track: "open_market" | "competition";
  is_active: boolean;
  last_price: number;
  change_pct: number;
  volume_1m: number;
  volume_24h: number;
  vpin: number;
  ofi_z: number;
  kyles_lambda: number;
  spread_bps: number;
  regime: string;
  provider: string;
  quote_origin?: string;
  // ATLAS feed quote status/source/Toronto time (never shown without them).
  quote_status?: "live" | "delayed" | "market_closed" | "stale" | "no_data";
  quote_source?: string | null;
  quote_time?: string | null;
  execution_permission: "none";
  market_id?: string;
  market_name?: string;
  market_open?: boolean;
  market_label?: string;
  market_session?: string;
  market_countdown?: string;
  market_status?: string;
}

interface BlotterPosition {
  positionId: string;
  symbol: string;
  track: "open_market" | "competition";
  side: "LONG" | "SHORT";
  quantity: number;
  notionalUsd: number;
  entryPrice: number;
  markPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  unrealizedPnlUsd: number;
  tactic: string;
  status: "OPEN" | "FLATTENED";
}

function readServerPositions(rows: unknown): BlotterPosition[] {
  if (!Array.isArray(rows)) return [];
  const out: BlotterPosition[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const item = row as Record<string, unknown>;
    if (String(item.status ?? "open") !== "open") continue;
    const notional = Number(item.notional_usd ?? 0);
    const entry = Number(item.entry_price ?? 0);
    const bps = Number(item.stop_distance_bps ?? 0);
    const side = String(item.side ?? "buy").toLowerCase() === "sell" ? "SHORT" : "LONG";
    const stop =
      entry > 0 && bps > 0 ? entry * (side === "LONG" ? 1 - bps / 10000 : 1 + bps / 10000) : 0;
    out.push({
      positionId: String(item.position_id ?? ""),
      symbol: String(item.instrument_id ?? ""),
      track: String(item.track) === "open_market" ? "open_market" : "competition",
      side,
      quantity: entry > 0 ? Number((notional / entry).toFixed(entry > 500 ? 4 : 2)) : 0,
      notionalUsd: notional,
      entryPrice: entry,
      markPrice: entry,
      stopLossPrice: Number(stop.toFixed(entry > 0 && entry < 5 ? 4 : 2)),
      takeProfitPrice: 0,
      unrealizedPnlUsd: 0,
      tactic: "paper",
      status: "OPEN",
    });
  }
  return out;
}

interface WorkingOrderItem {
  orderId: string;
  submittedAt: string;
  symbol: string;
  side: "BUY" | "SELL";
  orderType: "MARKET" | "LIMIT" | "ALMGREN_CHRISS_TWAP";
  notionalUsd: number;
  riskPct: number;
  entryPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  status: "AUTHORIZED_FILLED" | "WORKING_TWAP_CHILD" | "REJECTED";
  reason: string;
}

const DEFAULT_STUDIO_LISTINGS: CatalogListingItem[] = [
  {
    symbol: "BTC-USD",
    name: "Bitcoin Perpetual Swap",
    asset_class: "crypto_perps",
    exchange: "CCXT_PRO",
    tick_size: 0.01,
    lot_size: 0.001,
    min_notional: 10,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 32000,
    volume_24h: 48000000,
    vpin: 0.312,
    ofi_z: 0.89,
    kyles_lambda: 0.0015,
    spread_bps: 3.2,
    regime: "Expansion",
    provider: "ccxt_pro",
    execution_permission: "none",
  },
  {
    symbol: "ETH-USD",
    name: "Ethereum Perpetual Swap",
    asset_class: "crypto_perps",
    exchange: "COINBASE",
    tick_size: 0.01,
    lot_size: 0.01,
    min_notional: 10,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 28500,
    volume_24h: 36500000,
    vpin: 0.278,
    ofi_z: 1.22,
    kyles_lambda: 0.0014,
    spread_bps: 3.8,
    regime: "Expansion",
    provider: "coinbase",
    execution_permission: "none",
  },
  {
    symbol: "SOL-USD",
    name: "Solana Perpetual Swap",
    asset_class: "crypto_perps",
    exchange: "HYPERLIQUID",
    tick_size: 0.01,
    lot_size: 0.1,
    min_notional: 10,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 24100,
    volume_24h: 29400000,
    vpin: 0.354,
    ofi_z: 1.69,
    kyles_lambda: 0.0018,
    spread_bps: 4.5,
    regime: "Expansion",
    provider: "hyperliquid",
    execution_permission: "none",
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corporation",
    asset_class: "equities",
    exchange: "NASDAQ",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 100,
    track: "open_market",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 19340,
    volume_24h: 15200000,
    vpin: 0.368,
    ofi_z: 1.04,
    kyles_lambda: 0.0016,
    spread_bps: 1.5,
    regime: "Expansion",
    provider: "polygon",
    execution_permission: "none",
  },
  {
    symbol: "SPY",
    name: "SPDR S&P 500 ETF Trust",
    asset_class: "equities",
    exchange: "NYSE_ARCA",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 100,
    track: "open_market",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 18500,
    volume_24h: 14500000,
    vpin: 0.242,
    ofi_z: 0.35,
    kyles_lambda: 0.0012,
    spread_bps: 1.2,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "AAPL",
    name: "Apple Inc.",
    asset_class: "equities",
    exchange: "NASDAQ",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 100,
    track: "open_market",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 19760,
    volume_24h: 15550000,
    vpin: 0.214,
    ofi_z: 0.44,
    kyles_lambda: 0.0011,
    spread_bps: 1.4,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "ES",
    name: "E-mini S&P 500 Futures (Front Month)",
    asset_class: "futures",
    exchange: "CME",
    tick_size: 0.25,
    lot_size: 50,
    min_notional: 2500,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 9200,
    volume_24h: 8800000,
    vpin: 0.24,
    ofi_z: 0.47,
    kyles_lambda: 0.0015,
    spread_bps: 1.8,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "NQ",
    name: "E-mini Nasdaq-100 Futures (Front Month)",
    asset_class: "futures",
    exchange: "CME",
    tick_size: 0.25,
    lot_size: 20,
    min_notional: 2000,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 9510,
    volume_24h: 9010000,
    vpin: 0.265,
    ofi_z: 0.73,
    kyles_lambda: 0.0015,
    spread_bps: 1.8,
    regime: "Expansion",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "CL",
    name: "Crude Oil WTI Futures (Front Month)",
    asset_class: "futures",
    exchange: "NYMEX",
    tick_size: 0.01,
    lot_size: 1000,
    min_notional: 1000,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 10440,
    volume_24h: 9640000,
    vpin: 0.34,
    ofi_z: -0.42,
    kyles_lambda: 0.0015,
    spread_bps: 1.8,
    regime: "Volatile Auction",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "GC",
    name: "Gold Comex Futures (Front Month)",
    asset_class: "futures",
    exchange: "COMEX",
    tick_size: 0.1,
    lot_size: 100,
    min_notional: 2000,
    track: "competition",
    is_active: true,
    last_price: 0, // no hardcoded sample price: filled from the ATLAS feed
    change_pct: 0,
    volume_1m: 10750,
    volume_24h: 9850000,
    vpin: 0.365,
    ofi_z: 0.71,
    kyles_lambda: 0.0015,
    spread_bps: 1.8,
    regime: "Expansion",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "SI",
    name: "Silver Futures (COMEX Front Month)",
    asset_class: "futures",
    exchange: "COMEX",
    tick_size: 0.005,
    lot_size: 5000,
    min_notional: 2500,
    track: "competition",
    is_active: true,
    last_price: 0,
    change_pct: 0,
    volume_1m: 8400,
    volume_24h: 7200000,
    vpin: 0.34,
    ofi_z: 0.65,
    kyles_lambda: 0.0014,
    spread_bps: 1.4,
    regime: "Expansion",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "GLD",
    name: "SPDR Gold Shares Physical Bullion Trust ETF",
    asset_class: "equities",
    exchange: "NYSE_ARCA",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 10,
    track: "open_market",
    is_active: true,
    last_price: 0,
    change_pct: 0,
    volume_1m: 18500,
    volume_24h: 19500000,
    vpin: 0.22,
    ofi_z: 0.48,
    kyles_lambda: 0.0011,
    spread_bps: 1.0,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "SLV",
    name: "iShares Silver Trust Physical Bullion ETF",
    asset_class: "equities",
    exchange: "NYSE_ARCA",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 10,
    track: "open_market",
    is_active: true,
    last_price: 0,
    change_pct: 0,
    volume_1m: 22400,
    volume_24h: 24500000,
    vpin: 0.25,
    ofi_z: 0.52,
    kyles_lambda: 0.0012,
    spread_bps: 1.3,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "TLT",
    name: "iShares 20+ Year Treasury Bond ETF",
    asset_class: "equities",
    exchange: "NASDAQ",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 10,
    track: "open_market",
    is_active: true,
    last_price: 0,
    change_pct: 0,
    volume_1m: 26000,
    volume_24h: 31000000,
    vpin: 0.21,
    ofi_z: 0.34,
    kyles_lambda: 0.001,
    spread_bps: 1.1,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
  {
    symbol: "EUR_USD",
    name: "Euro / US Dollar Spot Foreign Exchange",
    asset_class: "futures",
    exchange: "FX_SPOT",
    tick_size: 0.0001,
    lot_size: 1000,
    min_notional: 1000,
    track: "open_market",
    is_active: true,
    last_price: 0,
    change_pct: 0,
    volume_1m: 15000,
    volume_24h: 18000000,
    vpin: 0.19,
    ofi_z: 0.28,
    kyles_lambda: 0.0009,
    spread_bps: 0.8,
    regime: "Compression",
    provider: "databento",
    execution_permission: "none",
  },
];

function nyseSessionCountdown(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const read = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  const weekday = read("weekday");
  const minutes = Number(read("hour")) * 60 + Number(read("minute"));
  const second = Number(read("second"));
  const open = 9 * 60 + 30;
  const close = 16 * 60;
  if (weekday === "Sat" || weekday === "Sun" || minutes < open || minutes >= close) {
    return "NYSE closed";
  }
  const remain = (close - minutes) * 60 - second;
  const hours = Math.floor(remain / 3600);
  const mins = Math.floor((remain % 3600) / 60);
  const secs = remain % 60;
  return `Cash close ${hours}h ${String(mins).padStart(2, "0")}m ${String(secs).padStart(2, "0")}s ET`;
}

function itemQuote(item: CatalogListingItem): FeedQuote {
  const has = Number(item.last_price) > 0;
  return {
    symbol: item.symbol,
    price: has ? item.last_price : null,
    change_pct: has ? item.change_pct ?? null : null,
    source: has ? item.quote_source ?? item.quote_origin ?? null : null,
    observed_at: null,
    observed_at_toronto: has ? item.quote_time ?? null : null,
    status: has ? item.quote_status ?? "stale" : "no_data",
  };
}

function placeholderListing(symbol: string, lastPrice = 0): CatalogListingItem {
  const crypto = symbol.endsWith("-USD");
  return {
    symbol,
    name: symbol,
    asset_class: crypto ? "crypto_perps" : "equities",
    exchange: crypto ? "COINBASE" : "PUBLIC",
    tick_size: 0.01,
    lot_size: 1,
    min_notional: 1,
    track: crypto ? "competition" : "open_market",
    is_active: true,
    last_price: lastPrice,
    change_pct: 0,
    volume_1m: 0,
    volume_24h: 0,
    vpin: 0,
    ofi_z: 0,
    kyles_lambda: 0,
    spread_bps: 0,
    regime: "Public listing",
    provider: "public",
    execution_permission: "none",
  };
}

export function StreamlinedTradingStudio() {
  const { role, setRole, profile } = useRoleContext();
  const [activeTrack, setActiveTrack] = useState<"all" | "open_market" | "competition">("all");
  const [assetClassFilter, setAssetClassFilter] = useState<
    "all" | "metals" | "etfs" | "futures" | "fx" | "stocks" | "equities" | "crypto_perps"
  >("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchLatencyMs, setSearchLatencyMs] = useState<number | null>(null);
  const [universeCounts, setUniverseCounts] = useState<{
    total_assets: number;
    listed_assets?: number;
    equities: number;
    crypto_perps: number;
    futures: number;
  } | null>(null);

  const [catalogListings, setCatalogListings] = useState<CatalogListingItem[]>(DEFAULT_STUDIO_LISTINGS);
  const [catalogTotal, setCatalogTotal] = useState<number | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogNotice, setCatalogNotice] = useState("Fixture directory. Not a live universe.");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("BTC-USD");
  const [tvQuery, setTvQuery] = useState("");
  const [chartSymbol, setChartSymbol] = useState<string | null>(null);
  const [modelGap, setModelGap] = useState<string | null>(null);
  const [publicClose, setPublicClose] = useState<number | null>(null);
  const [timeframe, setTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("15m");
  const [, setChartCandles] = useState<LiveCandlePoint[]>([]);
  const [barsLoading, setBarsLoading] = useState(true);
  const [barNote, setBarNote] = useState("Loading labeled bars");
  const [gardenNote, setGardenNote] = useState("Range garden has not reported yet");
  const [reserveNote, setReserveNote] = useState("Reserve sleeve has not reported yet");
  const [reserveHoldings, setReserveHoldings] = useState<
    Array<{ symbol: string; in_sweep: boolean; target_usd: string }>
  >([]);
  const [feedAvailable, setFeedAvailable] = useState(false);
  const [demoFeedActive, setDemoFeedActive] = useState(true);
  const [feedAudit, setFeedAudit] = useState("Fixture stream starting · venues unconfigured · execution_permission none");
  const [chartRead, setChartRead] = useState<{
    active: {
      symbol: string;
      track: "competition" | "open_market";
      chart_source: string;
      feed_origin: string;
      bucket_seconds: number;
      bars_read: number;
      direction: "BUY" | "SELL" | "HOLD";
      conviction: number;
      model_id: string;
      horizons: Array<{ horizon: string; expected_return_bps: number; p10_price: number; p50_price: number; p90_price: number }>;
      execution_permission: "none";
    };
    competition: Array<{ symbol: string; direction: "BUY" | "SELL" | "HOLD"; conviction: number; chart_source: string }>;
    open_market: Array<{ symbol: string; direction: "BUY" | "SELL" | "HOLD"; conviction: number; chart_source: string }>;
    tradingview?: {
      tradingview_symbol: string | null;
      interval: string | null;
      available: boolean;
      reason_text: string;
    };
    execution_permission: "none";
  } | null>(null);
  const [wsLatencyMs, setWsLatencyMs] = useState<number | null>(null);
  const [activeSubCount, setActiveSubCount] = useState<number>(1);
  const [sessionClock, setSessionClock] = useState<string>("—");
  const [marketSessions, setMarketSessions] = useState<{
    as_of_et?: string;
    venues?: Array<{
      venue_id: string;
      venue_name: string;
      status: string;
      status_label: string;
      is_open: boolean;
      countdown: string;
      schedule_summary: string;
      reason: string;
      look_symbol?: string;
    }>;
    by_symbol?: Record<string, {
      symbol: string;
      venue_id: string;
      venue_name: string;
      status: string;
      status_label: string;
      is_open: boolean;
      countdown: string;
      schedule_summary: string;
      reason: string;
      trading_session?: string;
      scheduled_market_status?: string;
    }>;
  } | null>(null);
  const [openNowOnly, setOpenNowOnly] = useState(false);
  const [killSwitchEngaged, setKillSwitchEngaged] = useState<boolean>(false);

  // Collapsible Bottom Drawer State
  const [bottomDrawerOpen, setBottomDrawerOpen] = useState<boolean>(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [ticketTab, setTicketTab] = useState<"order" | "risk">("order");
  const [symbolsOpen, setSymbolsOpen] = useState(true);

  const [bottomTab, setBottomTab] = useState<"positions" | "orders" | "audit">("positions");

  // Pre-Trade Bracket Order Ticket State
  const [orderSide, setOrderSide] = useState<"BUY" | "SELL">("BUY");
  const [executionTactic, setExecutionTactic] = useState<"MARKET" | "LIMIT" | "ALMGREN_CHRISS_TWAP">(
    "ALMGREN_CHRISS_TWAP"
  );
  const [equityRiskPct, setEquityRiskPct] = useState<number>(0.6); // 0.50% - 0.75% target band
  const [atrStopBps, setAtrStopBps] = useState<number>(120); // 1.20% stop distance
  const [rewardRiskMultiple, setRewardRiskMultiple] = useState<number>(2.2);
  const [orderFeedback, setOrderFeedback] = useState<{
    status: "nominal" | "authorized" | "rejected";
    message: string;
  }>({
    status: "nominal",
    message:
      "No deposited capital is loaded. The model can show a stance and cannot buy or sell.",
  });

  const [positions, setPositions] = useState<BlotterPosition[]>([]);
  const [workingOrders, setWorkingOrders] = useState<WorkingOrderItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<string[]>([]);
  const [account, setAccount] = useState<{
    initial_equity_usd: string;
    current_equity_usd: string;
    start_of_day_equity_usd: string;
    high_water_mark_usd: string;
    best_day_profit_usd: string;
    total_cumulative_profit_usd: string;
    cash_usd?: string;
    cash_tracked?: boolean;
  } | null>(null);
  const [researchHand, setResearchHand] = useState("");
  const [depositsLoaded, setDepositsLoaded] = useState(false);
  const [freeCashUsd, setFreeCashUsd] = useState(0);
  const [capitalAmount, setCapitalAmount] = useState("1000");
  const [capitalBusy, setCapitalBusy] = useState(false);
  const [controlAvailable, setControlAvailable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [closingPositionId, setClosingPositionId] = useState<string | null>(null);
  const applyControlState = useCallback((state: {
    account?: {
      current_equity_usd?: string;
      cash_usd?: string;
      cash_tracked?: boolean;
    };
    deposits_loaded?: boolean;
    kill_switch_engaged?: boolean;
    open_positions?: unknown;
    audit_log?: unknown;
    research_hand?: { genome_id?: string } | null;
  } | null) => {
    if (!state || typeof state !== "object") return;
    if (state.account && typeof state.account === "object") {
      setAccount(state.account as NonNullable<typeof account>);
      setDepositsLoaded(state.deposits_loaded !== false && Number(state.account.current_equity_usd ?? 0) > 0);
      setFreeCashUsd(state.account.cash_tracked ? Number(state.account.cash_usd ?? 0) : 0);
    }
    if ("kill_switch_engaged" in state) setKillSwitchEngaged(Boolean(state.kill_switch_engaged));
    if ("open_positions" in state) setPositions(readServerPositions(state.open_positions));
    if (Array.isArray(state.audit_log)) setAuditLogs(state.audit_log.map(String));
    if ("research_hand" in state) {
      const hand = state.research_hand;
      setResearchHand(hand && typeof hand === "object" && hand.genome_id ? String(hand.genome_id) : "");
    }
    setControlAvailable(true);
  }, []);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/control/state", { cache: "no-store" });
        if (!response.ok) throw new Error("Control plane unavailable");
        const state = await response.json();
        if (active) applyControlState(state);
      } catch { if (active) setControlAvailable(false); }
    };
    void refresh();
    const timer = setInterval(refresh, 2000);
    return () => { active = false; clearInterval(timer); };
  }, [applyControlState]);

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const catalogListRef = useRef<HTMLDivElement | null>(null);
  const catalogSymbolsRef = useRef<string[]>([]);
  const catalogOffsetRef = useRef(0);
  const catalogTotalRef = useRef<number | null>(null);
  const catalogLoadingRef = useRef(false);
  const catalogGenRef = useRef(0);
  const catalogAbortRef = useRef<AbortController | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const barsRef = useRef<LiveCandlePoint[]>([]);
  const barSourceRef = useRef("labeled_fixture_bars");
  const barsRequestRef = useRef(0);
  const selectedSymbolRef = useRef(selectedSymbol);
  const nativeQuoteSymbolRef = useRef<string | null>(null);
  const prevSymbolRef = useRef<string>("BTC-USD");
  selectedSymbolRef.current = selectedSymbol;
  catalogSymbolsRef.current = catalogListings.map((item) => item.symbol);

  // Ctrl + K global command palette shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSymbolsOpen(true);
        window.setTimeout(() => searchInputRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const loadCatalogPage = useCallback((reset: boolean) => {
    if (!reset) {
      if (catalogLoadingRef.current) return;
      if (catalogTotalRef.current != null && catalogOffsetRef.current >= catalogTotalRef.current) return;
    } else {
      catalogAbortRef.current?.abort();
      catalogGenRef.current += 1;
      catalogOffsetRef.current = 0;
      catalogTotalRef.current = null;
      setCatalogTotal(null);
      setCatalogListings([]);
    }
    const generation = catalogGenRef.current;
    const offset = reset ? 0 : catalogOffsetRef.current;
    const controller = new AbortController();
    catalogAbortRef.current = controller;
    catalogLoadingRef.current = true;
    setCatalogLoading(true);
    const params = new URLSearchParams({
      q: searchQuery,
      track: activeTrack,
      asset_class: assetClassFilter,
      limit: "80",
      offset: String(offset),
    });
    void fetch(`/api/catalog/search?${params.toString()}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error("catalog");
        return res.json();
      })
      .then((data: {
        query_latency_ms?: number;
        universe_counts?: {
          total_assets: number;
          listed_assets?: number;
          equities: number;
          crypto_perps: number;
          futures: number;
        };
        results?: CatalogListingItem[];
        total_matching?: number;
        source?: string;
        is_live?: boolean;
        execution_permission?: string;
        notice?: string;
      }) => {
        if (catalogGenRef.current !== generation) return;
        if (
          data.source !== "synthetic_fixture" ||
          data.is_live !== false ||
          data.execution_permission !== "none" ||
          !Array.isArray(data.results)
        ) {
          throw new Error("provenance");
        }
        if (typeof data.query_latency_ms === "number") setSearchLatencyMs(data.query_latency_ms);
        if (data.universe_counts) setUniverseCounts(data.universe_counts);
        const total = Number(data.total_matching ?? data.results.length);
        catalogTotalRef.current = total;
        setCatalogTotal(total);
        setCatalogNotice(typeof data.notice === "string" ? data.notice : "Fixture directory. Not a live universe.");
        setCatalogListings((prev) => {
          const base = reset ? [] : prev;
          const seen = new Set(base.map((item) => item.symbol));
          const next = [...base];
          for (const item of data.results ?? []) {
            if (!seen.has(item.symbol)) {
              seen.add(item.symbol);
              next.push(item);
            }
          }
          return next;
        });
        catalogOffsetRef.current = data.results.length === 0 ? total : offset + data.results.length;
      })
      .catch(() => {
        if (catalogGenRef.current !== generation) return;
        if (!reset) {
          const total = catalogTotalRef.current ?? catalogOffsetRef.current;
          catalogOffsetRef.current = total;
          setCatalogNotice("The next page did not load. The rows already shown are still the fixture directory.");
          return;
        }
        const q = searchQuery.trim().toUpperCase();
        const filtered = DEFAULT_STUDIO_LISTINGS.filter((item) => {
          if (activeTrack !== "all" && item.track !== activeTrack) return false;
          if (assetClassFilter !== "all" && item.asset_class !== assetClassFilter) return false;
          if (q && !item.symbol.includes(q) && !item.name.toUpperCase().includes(q)) return false;
          return true;
        });
        catalogTotalRef.current = filtered.length;
        catalogOffsetRef.current = filtered.length;
        setCatalogTotal(filtered.length);
        setCatalogListings(filtered);
        setCatalogNotice("Catalog request failed. Showing the short local list.");
      })
      .finally(() => {
        if (catalogGenRef.current !== generation) return;
        catalogLoadingRef.current = false;
        setCatalogLoading(false);
      });
  }, [activeTrack, assetClassFilter, searchQuery]);

  const libraryQuoteKey = libraryQuoteSymbols(catalogListings, selectedSymbol).join(",");

  useEffect(() => {
    const symbols = libraryQuoteKey.split(",").filter(Boolean);
    if (symbols.length === 0) return;
    let active = true;
    const controller = new AbortController();
    const pull = () => {
      void fetchLibraryQuotes(symbols, controller.signal)
        .then((quotes) => {
          if (!active || quotes.length === 0) return;
          const bySymbol = new Map(quotes.map((row) => [row.symbol, row]));
          setCatalogListings((prev) =>
            prev.map((item) => {
              const quote = bySymbol.get(item.symbol);
              if (!quote) return item;
              if (timeframeRef.current === "1s" && nativeQuoteSymbolRef.current === item.symbol) return item;
              return {
                ...item,
                last_price: quote.price,
                change_pct: quote.change_pct ?? 0,
                quote_origin: quote.feed_origin,
                quote_status: quote.status ?? (quote.delayed ? "delayed" : "live"),
                quote_source: quote.source ?? quote.feed_origin,
                quote_time: quote.observed_at_toronto ?? quote.observed_at ?? null,
              };
            })
          );
        })
        .catch(() => undefined);
    };
    pull();
    const timer = window.setInterval(pull, 20000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [libraryQuoteKey]);

  useEffect(() => {
    loadCatalogPage(true);
    return () => {
      catalogGenRef.current += 1;
      catalogAbortRef.current?.abort();
    };
  }, [loadCatalogPage]);

  // The symbol list is paged, not scrolled: it shows as many rows as fit the column and Prev/Next move through the catalog.
  const [listPage, setListPage] = useState(0);
  const [listCap, setListCap] = useState(6);
  useEffect(() => { setListPage(0); }, [searchQuery, activeTrack, assetClassFilter, openNowOnly]);
  useEffect(() => {
    const el = catalogListRef.current;
    if (!el || !symbolsOpen) return;
    const ROW_H = 44, PAGER_H = 34;
    const fit = () => setListCap(Math.max(3, Math.floor((el.clientHeight - PAGER_H) / ROW_H)));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [symbolsOpen]);
  useEffect(() => {
    if (!symbolsOpen || catalogLoading) return;
    const total = catalogTotalRef.current;
    if (total == null || catalogOffsetRef.current >= total) return;
    if ((listPage + 2) * listCap > catalogListings.length) loadCatalogPage(false);
  }, [symbolsOpen, listPage, listCap, catalogListings.length, catalogLoading, loadCatalogPage]);

  const listRows = useMemo(
    () => (openNowOnly ? catalogListings.filter((item) => item.market_open === true) : catalogListings),
    [catalogListings, openNowOnly],
  );
  const visibleListings = listRows.slice(listPage * listCap, (listPage + 1) * listCap);
  const hasNextListPage = (listPage + 1) * listCap < listRows.length
    || (!catalogLoading && catalogTotal != null && catalogOffsetRef.current < catalogTotal);

  // Dynamic On-Demand WebSocket Subscription Multiplexer (/ws/market-stream).
  // History comes from /api/market/bars. The socket only moves the right edge.
  const timeframeRef = useRef(timeframe);
  timeframeRef.current = timeframe;

  const handleLiveSnapshot = useCallback((snapshot: LiveSnapshot) => {
    if (timeframeRef.current !== "1s" || snapshot.symbol !== selectedSymbolRef.current) return;
    const close = snapshot.candles?.[snapshot.candles.length - 1]?.close;
    const genuine = ["public_last_trade", "public_market_candles"].includes(snapshot.chart_source ?? "")
      && Boolean(snapshot.feed_origin && snapshot.feed_origin !== "none");
    if (snapshot.feed_health?.connection !== "connected" || !genuine || typeof close !== "number" || !Number.isFinite(close) || close <= 0) {
      setFeedAvailable(false);
      return;
    }
    nativeQuoteSymbolRef.current = snapshot.symbol;
    setPublicClose(close);
    setCatalogListings(previous => previous.map(item => item.symbol === snapshot.symbol
      ? { ...item, last_price: close, quote_origin: snapshot.feed_origin } : item));
    setFeedAvailable(true);
    setDemoFeedActive(false);
  }, []);

  useEffect(() => {
    const requestId = barsRequestRef.current + 1;
    barsRequestRef.current = requestId;
    if (timeframe === "1s") {
      barsRef.current = [];
      barSourceRef.current = "native_live_view";
      setChartCandles([]);
      setFeedAvailable(false);
      setPublicClose(null);
      setBarsLoading(false);
      setBarNote("The native viewer below owns the received market candles and completed model inputs.");
      return;
    }
    let active = true;
    setBarsLoading(true);
    const bucketSeconds = TIMEFRAME_SECONDS[timeframe];
    void loadMarketBars(selectedSymbol, bucketSeconds, 160)
      .then((body) => {
        if (!active || requestId !== barsRequestRef.current) return;
        barsRef.current = body.candles;
        barSourceRef.current = body.chart_source;
        setChartCandles(body.candles);
        setFeedAvailable(body.candles.length > 0);
        setDemoFeedActive(body.feed_origin !== "provider_observed");
        setPublicClose(typeof body.last_close === "number" && body.last_close > 0 ? body.last_close : null);
        setBarNote(
          `${body.bar_count} bars · ${body.bucket_seconds}s · ${body.chart_source} · ${body.feed_origin} · execution_permission ${body.execution_permission}`
        );
        setBarsLoading(false);
      })
      .catch(() => {
        if (!active || requestId !== barsRequestRef.current) return;
        barsRef.current = [];
        setChartCandles([]);
        setFeedAvailable(false);
        setBarNote("Labeled bar history did not load");
        setBarsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedSymbol, timeframe]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    try {
      const wsBase =
        typeof window !== "undefined"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : "";
      ws = new WebSocket(`${wsBase}/ws/market-stream?symbol=${encodeURIComponent(selectedSymbol)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        ws?.send(
          JSON.stringify({
            action: "subscribe",
            symbols: [selectedSymbol],
          })
        );
      };

      ws.onmessage = (evt) => {
        try {
          const pkt = JSON.parse(evt.data);
          if (pkt.event === "subscription_update") {
            if (typeof pkt.active_symbol_count === "number") {
              setActiveSubCount(pkt.active_symbol_count);
            }
            return;
          }
          if (pkt.symbol && Number.isFinite(Number(pkt.price))) {
            if (timeframeRef.current !== "1s") setDemoFeedActive(pkt.data_mode !== "observed");
            const tickSymbol = String(pkt.symbol).toUpperCase();
            if (tickSymbol === selectedSymbolRef.current.toUpperCase() && timeframeRef.current !== "1s") {
              const lastClose = barsRef.current[barsRef.current.length - 1]?.close ?? 0;
              const print = Number(pkt.price);
              const distantPublicPrint = barSourceRef.current === "public_market_candles" && lastClose > 0 && Math.abs(print - lastClose) / lastClose > 0.03;
              if (distantPublicPrint) {
                return;
              }
              const merged = mergeTickIntoBars(
                barsRef.current,
                {
                  exchangeTimestamp: String(pkt.exchange_timestamp ?? new Date().toISOString()),
                  price: Number(pkt.price),
                  size: Number(pkt.size ?? 0),
                },
                TIMEFRAME_SECONDS[timeframeRef.current]
              );
              barsRef.current = merged;
              setChartCandles(merged);
              setFeedAvailable(merged.length > 0);
            }
            const nextPrice = Number(pkt.last_price ?? pkt.price ?? 0);
            const demoPrint = pkt.data_mode !== "observed" && pkt.data_mode !== "public_last_trade";
            if (typeof pkt.latency_ms === "number") {
              setWsLatencyMs(pkt.latency_ms);
            }
            setCatalogListings((prev) =>
              prev.map((item) =>
                item.symbol === pkt.symbol
                  ? {
                      ...item,
                      // Demo/synthetic gateway prints never become the displayed price (only observed/public prints do).
                      last_price: demoPrint ? item.last_price : nextPrice > 0 ? nextPrice : item.last_price,
                      vpin: Number(pkt.vpin ?? item.vpin),
                      ofi_z: Number(pkt.ofi_z ?? pkt.ofi ?? item.ofi_z),
                      kyles_lambda: Number(pkt.kyles_lambda ?? item.kyles_lambda),
                      regime: String(pkt.regime ?? item.regime),
                    }
                  : item
              )
            );
          }
        } catch {
          // Ignore malformed WS frame
        }
      };
    } catch {
      // Offline fallback
    }

    return () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [selectedSymbol]);

  useEffect(() => {
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch(`/api/market/live-stream?symbol=${encodeURIComponent(selectedSymbol)}`, { cache: "no-store" });
        if (!response.ok) throw new Error("stream status unavailable");
        const body = await response.json();
        if (!active) return;
        const gateway = body.gateway ?? {};
        const tick = body.tick ?? {};
        const providers = gateway.providers ?? {};
        const names = Object.keys(providers);
        const unconfigured = names.filter((name) => providers[name]?.status === "UNCONFIGURED").length;
        const origin = String(gateway.feed_origin ?? (gateway.demo_mode ? "labeled_synthetic_fixture" : "provider_observed"));
        const price = Number(tick.price ?? tick.last_price ?? 0);
        setFeedAudit(
          `${origin} · ${tick.symbol ?? selectedSymbol} ${price > 0 ? price.toLocaleString() : "waiting"} · buffer ${gateway.ring_buffer_size ?? 0}/${gateway.ring_buffer_maxlen ?? 10000} · venues unconfigured ${unconfigured}/${names.length || 0} · execution_permission ${body.execution_permission ?? "none"}`
        );
        if (timeframeRef.current !== "1s") {
          if (tick.data_mode === "observed") setDemoFeedActive(false);
          else if (gateway.demo_mode || tick.data_mode === "demo") setDemoFeedActive(true);
        }
      } catch {
        if (active) setFeedAudit("Fixture stream status unavailable · execution_permission none");
      }
    };
    void pull();
    const timer = setInterval(pull, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedSymbol]);

  useEffect(() => {
    if (timeframe === "1s") {
      setChartRead(null);
      return;
    }
    let active = true;
    const bucketSeconds = TIMEFRAME_SECONDS[timeframe];
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/ml/chart-read?symbol=${encodeURIComponent(selectedSymbol)}&bucket_seconds=${bucketSeconds}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("chart read unavailable");
        const body = await response.json();
        if (active) setChartRead(body);
      } catch {
        if (active) setChartRead(null);
      }
    };
    void pull();
    const timer = setInterval(pull, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedSymbol, timeframe]);

  useEffect(() => {
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch("/api/strategies/range-garden", { cache: "no-store" });
        if (!response.ok) throw new Error("range garden unavailable");
        const body = await response.json();
        if (!active) return;
        const symbols: Array<{ symbol?: string; action?: string; reason?: string; blocked_action?: string | null }> =
          Array.isArray(body.symbols) ? body.symbols : [];
        const row = symbols.find((item) => item.symbol === selectedSymbol) ?? symbols[0];
        const detail = row
          ? `${row.symbol} ${row.action} ${row.reason}${row.blocked_action ? ` blocked ${row.blocked_action}` : ""}`
          : body.status;
        setGardenNote(
          `${body.path_id ?? "range-garden:v1"} · ${detail} · orders ${body.orders_submitted ?? 0} · harvests ${body.harvests_closed ?? 0} · execution_permission ${body.execution_permission ?? "none"}`
        );
      } catch {
        if (active) setGardenNote("Range garden unavailable · execution_permission none");
      }
    };
    void pull();
    const timer = setInterval(pull, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedSymbol]);

  useEffect(() => {
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch("/api/strategies/reserve-yield", { cache: "no-store" });
        if (!response.ok) throw new Error("reserve sleeve unavailable");
        const body = await response.json();
        if (!active) return;
        const holdings = Array.isArray(body.holdings) ? body.holdings : [];
        setReserveHoldings(
          holdings.map((row: { symbol?: string; in_sweep?: boolean; target_usd?: string }) => ({
            symbol: String(row.symbol ?? ""),
            in_sweep: Boolean(row.in_sweep),
            target_usd: String(row.target_usd ?? "0.00"),
          }))
        );
        setReserveNote(
          `${body.path_id ?? "reserve-yield:v1"} · distributable ${body.distributable_usd ?? "0.00"} · orders ${body.orders_submitted ?? 0} · TEY ${body.yield_observation ?? "unobserved"} · execution_permission ${body.execution_permission ?? "none"}`
        );
      } catch {
        if (active) setReserveNote("Reserve sleeve unavailable · execution_permission none");
      }
    };
    void pull();
    const timer = setInterval(pull, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const raw = new URLSearchParams(window.location.search).get("tvwidgetsymbol")?.trim() ?? "";
    setTvQuery(raw);
  }, []);

  useEffect(() => {
    if (!tvQuery) {
      setChartSymbol(null);
      setModelGap(null);
      return;
    }
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/market/tradingview?symbol=${encodeURIComponent(tvQuery)}&timeframe=${encodeURIComponent(timeframe)}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("tradingview map unavailable");
        const body = (await response.json()) as {
          tradingview_symbol?: string | null;
          model_symbol?: string | null;
          reason_text?: string;
        };
        if (!active) return;
        setChartSymbol(body.tradingview_symbol ?? null);
        if (body.model_symbol) {
          setModelGap(null);
          setSelectedSymbol(body.model_symbol);
        } else if (body.tradingview_symbol) {
          setModelGap(
            `This chart is TradingView's ${body.tradingview_symbol}. The model has no public-candle series for this listing. execution_permission none`
          );
        } else {
          setModelGap(body.reason_text ?? "That symbol is not a TradingView listing. execution_permission none");
        }
      } catch {
        if (!active) return;
        setChartSymbol(null);
        setModelGap("TradingView listing map is unavailable. execution_permission none");
      }
    };
    void pull();
    return () => {
      active = false;
    };
  }, [tvQuery, timeframe]);

  const handleSelectSymbol = (newSym: string) => {
    setTvQuery("");
    setChartSymbol(null);
    setModelGap(null);
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("tvwidgetsymbol")) {
      window.history.replaceState(null, "", window.location.pathname);
    }
    const prevSym = prevSymbolRef.current;
    if (prevSym && prevSym !== newSym && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "unsubscribe", symbols: [prevSym] }));
      wsRef.current.send(JSON.stringify({ action: "subscribe", symbols: [newSym] }));
    }
    prevSymbolRef.current = newSym;
    setSelectedSymbol(newSym);
    setAuditLogs((prev) => [
      `${new Date().toISOString()} | ws_multiplexer | Unsubscribed ${prevSym} -> Subscribed ${newSym} | execution_permission=none`,
      ...prev.slice(0, 24),
    ]);
  };

  const activeAsset = useMemo(
    () => {
      const listing = catalogListings.find((item) => item.symbol === selectedSymbol) ??
      DEFAULT_STUDIO_LISTINGS.find((item) => item.symbol === selectedSymbol) ??
      placeholderListing(selectedSymbol, publicClose ?? 0);
      return timeframe === "1s" && nativeQuoteSymbolRef.current === selectedSymbol && publicClose != null
        ? { ...listing, last_price: publicClose } : listing;
    },
    [catalogListings, publicClose, selectedSymbol, timeframe]
  );

  // Remaining-Room HUD & Deterministic Position Sizing Math
  const accountEquityUsd = Number(account?.current_equity_usd ?? 0);
  const deskTrack = activeAsset.track === "open_market" ? "open_market" : "competition";
  const dailyLossLimitPct = deskTrack === "open_market" ? 3.0 : 4.0;
  const trailingDdFloorPct = deskTrack === "open_market" ? 10.0 : 8.0;
  const riskCapPct = deskTrack === "open_market" ? 0.5 : 0.75;
  const singleDayConsistencyMaxPct = 35.0;
  const drawdownReferenceUsd = account
    ? Number(deskTrack === "open_market" ? account.initial_equity_usd || account.high_water_mark_usd : account.high_water_mark_usd)
    : 0;

  const dailyLossUsedPct = account && Number(account.start_of_day_equity_usd) > 0
    ? Math.max(0, ((Number(account.start_of_day_equity_usd) - accountEquityUsd) / Number(account.start_of_day_equity_usd)) * 100)
    : 0;
  const trailingDdUsedPct = account && drawdownReferenceUsd > 0
    ? Math.max(0, ((drawdownReferenceUsd - accountEquityUsd) / drawdownReferenceUsd) * 100)
    : 0;
  const singleDayConsistencyUsedPct = account && Number(account.total_cumulative_profit_usd) > 0 ? Number(account.best_day_profit_usd) / Number(account.total_cumulative_profit_usd) * 100 : 0;
  const latencyBadge =
    wsLatencyMs == null
      ? { background: "var(--c-surface)", border: "1px solid var(--c-border)", color: "var(--c-muted)", label: "Socket —" }
      : wsLatencyMs < 15
      ? { background: "rgba(0, 158, 115, 0.1)", border: "1px solid rgba(0, 158, 115, 0.3)", color: "var(--c-good)", label: `${wsLatencyMs.toFixed(0)} ms` }
      : wsLatencyMs < 50
      ? { background: "rgba(245, 158, 11, 0.12)", border: "1px solid rgba(245, 158, 11, 0.45)", color: "#FBBF24", label: `${wsLatencyMs.toFixed(0)} ms` }
      : { background: "rgba(213, 94, 0, 0.12)", border: "1px solid rgba(213, 94, 0, 0.45)", color: "var(--c-bad)", label: `${wsLatencyMs.toFixed(0)} ms` };
  const drawdownMeterLabel =
    deskTrack === "open_market"
      ? `${trailingDdFloorPct.toFixed(1)}% Static Drawdown Floor`
      : `${trailingDdFloorPct.toFixed(1)}% Trailing Drawdown Floor`;

  useEffect(() => {
    let alive = true;
    const pullSessions = async () => {
      try {
        const symbols = catalogSymbolsRef.current.slice(0, 60);
        const selected = selectedSymbolRef.current;
        if (selected && !symbols.includes(selected)) symbols.unshift(selected);
        const query = symbols.length ? `?symbols=${encodeURIComponent(symbols.slice(0, 60).join(","))}` : "";
        const r = await fetch(`/api/market/sessions${query}`, { cache: "no-store" });
        if (!r.ok) return;
        const body = await r.json();
        if (!alive) return;
        setMarketSessions(body);
        const by = body?.by_symbol;
        if (!by || typeof by !== "object") return;
        setCatalogListings((prev) => prev.map((item) => {
          const st = by[item.symbol.toUpperCase()] ?? by[item.symbol];
          if (!st) return item;
          return {
            ...item,
            market_id: st.venue_id,
            market_name: st.venue_name,
            market_open: Boolean(st.is_open),
            market_label: st.status_label,
            market_session: st.trading_session,
            market_countdown: st.countdown,
            market_status: st.scheduled_market_status ?? st.status,
          };
        }));
      } catch {
        // fallback to local clock
      }
    };
    void pullSessions();
    const t = setInterval(pullSessions, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    const updateClock = () => {
      const symSess = marketSessions?.by_symbol?.[selectedSymbol];
      if (symSess) {
        setSessionClock(`${symSess.venue_name}: ${symSess.status_label} · ${symSess.countdown}`);
        return;
      }
      const now = new Date();
      setSessionClock(deskTrack === "open_market" ? nyseSessionCountdown(now) : "24/7 continuous");
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, [deskTrack, marketSessions, selectedSymbol]);

  const sizingCalculation = useMemo(() => {
    const stopFraction = Math.max(0.001, atrStopBps / 10000.0);
    const riskDollars = accountEquityUsd * (equityRiskPct / 100.0);
    const rawNotionalUsd = riskDollars / stopFraction;
    const hasQuote = activeAsset.last_price > 0;
    const cappedNotionalUsd = hasQuote ? Math.round(rawNotionalUsd) : 0;
    const px = hasQuote ? activeAsset.last_price : 0;
    const quantity = hasQuote ? Number((cappedNotionalUsd / px).toFixed(px > 500 ? 4 : 2)) : 0;

    const stopOffset = px * stopFraction;
    const tpOffset = stopOffset * rewardRiskMultiple;

    const stopLossPrice = Number(
      (orderSide === "BUY" ? px - stopOffset : px + stopOffset).toFixed(px < 5 ? 4 : 2)
    );
    const takeProfitPrice = Number(
      (orderSide === "BUY" ? px + tpOffset : px - tpOffset).toFixed(px < 5 ? 4 : 2)
    );

    const postTradeDailyLossPct = Number((dailyLossUsedPct + equityRiskPct).toFixed(2));
    const postTradeTrailingDdPct = Number((trailingDdUsedPct + equityRiskPct).toFixed(2));
    const startOfDayUsd = Number(account?.start_of_day_equity_usd ?? 0);
    const dailyRoomUsd = Math.max(0, Math.round(startOfDayUsd * (dailyLossLimitPct / 100) - Math.max(0, startOfDayUsd - accountEquityUsd)));
    const trailingRoomUsd = Math.max(
      0,
      Math.round(drawdownReferenceUsd * (trailingDdFloorPct / 100) - Math.max(0, drawdownReferenceUsd - accountEquityUsd))
    );

    const noDepositedCapital = !depositsLoaded || accountEquityUsd <= 0;
    const cashTracked = Boolean(account?.cash_tracked);
    const exceedsFreeCash = cashTracked && cappedNotionalUsd > freeCashUsd + 0.001;
    const withinRiskCap = equityRiskPct >= 0.5 && equityRiskPct <= riskCapPct;
    const hardRiskBreach =
      noDepositedCapital ||
      exceedsFreeCash ||
      !hasQuote ||
      !profile.canExecuteTraderOrders ||
      !feedAvailable || !controlAvailable || submitting || killSwitchEngaged ||
      equityRiskPct < 0.5 ||
      equityRiskPct > riskCapPct ||
      postTradeDailyLossPct > dailyLossLimitPct ||
      postTradeTrailingDdPct > trailingDdFloorPct ||
      atrStopBps < (deskTrack === "open_market" ? 30 : 25);

    return {
      riskDollars: Math.round(riskDollars),
      notionalUsd: cappedNotionalUsd,
      quantity,
      stopLossPrice,
      takeProfitPrice,
      postTradeDailyLossPct,
      postTradeTrailingDdPct,
      dailyRoomUsd,
      trailingRoomUsd,
      withinRiskCap,
      hardRiskBreach,
      exceedsFreeCash,
    };
  }, [
    account, accountEquityUsd, controlAvailable, depositsLoaded, feedAvailable, freeCashUsd, submitting, dailyLossUsedPct, trailingDdUsedPct,
    activeAsset.last_price,
    atrStopBps,
    dailyLossLimitPct,
    deskTrack,
    drawdownReferenceUsd,
    equityRiskPct,
    killSwitchEngaged,
    orderSide,
    profile.canExecuteTraderOrders,
    rewardRiskMultiple,
    riskCapPct,
    trailingDdFloorPct,
  ]);

  const handlePaperCapital = async (path: "deposit" | "withdraw") => {
    const amount = Number(capitalAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setOrderFeedback({ status: "rejected", message: "Enter a paper amount greater than zero." });
      return;
    }
    setCapitalBusy(true);
    try {
      const response = await fetch(`/api/capital/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount_usd: amount.toFixed(2) }),
      });
      const body = await response.json().catch(() => ({}));
      const detail = body?.detail && typeof body.detail === "object" ? body.detail : body;
      if (!response.ok) {
        const reason = String(detail?.reason || "paper_capital_refused");
        setOrderFeedback({
          status: "rejected",
          message:
            reason === "insufficient_paper_cash"
              ? "That withdrawal is larger than free paper cash."
              : reason === "no_deposited_capital"
              ? "Load paper cash before a withdrawal."
              : `Paper ${path} was refused (${reason}).`,
        });
        return;
      }
      const nextEquity = String(detail.equity_usd ?? "0");
      const nextCash = String(detail.free_cash_usd ?? "0");
      setFreeCashUsd(Number(nextCash));
      setDepositsLoaded(Boolean(detail.deposits_loaded));
      setAccount((prev) =>
        prev
          ? {
              ...prev,
              current_equity_usd: nextEquity,
              cash_usd: nextCash,
              cash_tracked: Boolean(detail.cash_tracked),
              initial_equity_usd: detail.deposits_loaded ? nextEquity : prev.initial_equity_usd,
              start_of_day_equity_usd: detail.deposits_loaded ? nextEquity : "0",
              high_water_mark_usd: detail.deposits_loaded ? nextEquity : prev.high_water_mark_usd,
            }
          : prev
      );
      setOrderFeedback({
        status: "authorized",
        message: `Paper ${path} booked. Free cash $${Number(detail.free_cash_usd ?? 0).toLocaleString()} · equity $${Number(detail.equity_usd ?? 0).toLocaleString()}. The research hand cannot buy or sell.`,
      });
    } catch {
      setOrderFeedback({ status: "rejected", message: "Paper capital request did not reach the desk." });
    } finally {
      setCapitalBusy(false);
    }
  };

  // 1-Click Auto-Flatten Handler
  const handleAutoFlattenAll = async () => {
    if (!profile.canExecuteTraderOrders) {
      setOrderFeedback({
        status: "rejected",
        message: "Flatten is an execution action. This role cannot close positions.",
      });
      return;
    }
    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000" ? "" : "";
      const response = await fetch(`${apiBase}/api/control/flatten`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Atlas-Role": role },
        body: JSON.stringify({ reason: "studio_one_click_flatten" }),
      });
      if (!response.ok) throw new Error(response.status === 403 ? "Role is not authorized to flatten." : "Flatten request failed; state is unconfirmed.");
      applyControlState(await response.json());
    } catch (error) {
      setOrderFeedback({
        status: "rejected",
        message: error instanceof Error ? error.message : "Flatten request failed; state is unconfirmed.",
      });
      return;
    }
    setOrderFeedback({
      status: "authorized",
      message: "Paper positions closed. Nothing was sent to a broker.",
    });
  };

  const handleClosePosition = async (pos: BlotterPosition) => {
    if (!profile.canExecuteTraderOrders || closingPositionId) return;
    const base = activeAsset.symbol.split("-")[0].toLowerCase();
    const chartMatches = base.length > 0 && pos.symbol.toLowerCase().includes(base);
    const exit = chartMatches && activeAsset.last_price > 0 ? activeAsset.last_price : pos.entryPrice;
    if (!(exit > 0)) {
      setOrderFeedback({ status: "rejected", message: "This paper position has no price to close against." });
      return;
    }
    setClosingPositionId(pos.positionId);
    try {
      const response = await fetch("/api/control/close", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Atlas-Role": role },
        body: JSON.stringify({
          position_id: pos.positionId,
          exit_price: exit,
          fraction: 1,
          fee_usd: "0",
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || body?.close?.status === "rejected") {
        throw new Error(body?.close?.reason || `Close returned HTTP ${response.status}`);
      }
      if (body?.state) applyControlState(body.state);
      const pnl = Number(body?.close?.paper_pnl_usd ?? 0);
      setOrderFeedback({
        status: "authorized",
        message: `Paper ${pos.positionId} closed at ${exit}. P&L $${pnl.toFixed(2)}. The research hand cannot buy or sell.`,
      });
    } catch (error) {
      setOrderFeedback({
        status: "rejected",
        message: error instanceof Error ? error.message : "Close did not reach the paper book.",
      });
    } finally {
      setClosingPositionId(null);
    }
  };

  // Submit Pre-Trade Bracket Order to ActionableControlPlaneEngine
  const handleSubmitBracketOrder = async () => {
    if (sizingCalculation.hardRiskBreach) {
      const rejectReason = accountEquityUsd <= 0 || !depositsLoaded
        ? "No deposited capital is loaded. The model can show a stance and cannot buy or sell."
        : !profile.canExecuteTraderOrders
        ? "Rejected: this role cannot submit orders. Research output stays execution_permission none."
        : activeAsset.last_price <= 0
        ? "Rejected: this name has no quote. Nothing was sent."
        : killSwitchEngaged
        ? "The desk is off. Nothing was sent."
        : sizingCalculation.exceedsFreeCash
        ? `Rejected: ticket $${sizingCalculation.notionalUsd.toLocaleString()} is above free paper cash $${freeCashUsd.toLocaleString()}.`
        : equityRiskPct > riskCapPct
        ? `Rejected: Per-trade risk (${equityRiskPct.toFixed(2)}%) exceeds the ${riskCapPct.toFixed(2)}% ${deskTrack} cap.`
        : equityRiskPct < 0.5
        ? `Rejected: Per-trade risk (${equityRiskPct.toFixed(2)}%) is below the 0.50% floor.`
        : `Rejected: Post-trade drawdown breaches the ${dailyLossLimitPct.toFixed(1)}% daily loss limit or the ${trailingDdFloorPct.toFixed(1)}% drawdown floor.`;
      setOrderFeedback({ status: "rejected", message: rejectReason });
      setWorkingOrders((prev) => [
        {
          orderId: `REJ-${Date.now().toString().slice(-4)}`,
          submittedAt: sessionClock,
          symbol: activeAsset.symbol,
          side: orderSide,
          orderType: executionTactic,
          notionalUsd: sizingCalculation.notionalUsd,
          riskPct: equityRiskPct,
          entryPrice: activeAsset.last_price,
          stopLossPrice: sizingCalculation.stopLossPrice,
          takeProfitPrice: sizingCalculation.takeProfitPrice,
          status: "REJECTED",
          reason: rejectReason,
        },
        ...prev,
      ]);
      return;
    }

    setSubmitting(true);
    let intake;
    try {
      const response = await fetch("/api/control/strategy-signal", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Atlas-Role": role },
        body: JSON.stringify({
          symbol: activeAsset.symbol, direction: orderSide,
          reference_price: activeAsset.last_price,
          suggested_stop_loss: sizingCalculation.stopLossPrice,
          suggested_take_profit: sizingCalculation.takeProfitPrice,
          execution_permission: "none",
          telemetry: { vpin: activeAsset.vpin, desired_notional_usd: sizingCalculation.notionalUsd },
        }),
      });
      if (!response.ok) throw new Error(`Control plane returned HTTP ${response.status}`);
      intake = await response.json();
      if (intake.decision.control_plane_decision !== "authorized_and_executed") {
        throw new Error((intake.decision.violations || []).join("; ") || "rejected_by_control_plane");
      }
      if (intake.state) applyControlState(intake.state);
    } catch (error) {
      setOrderFeedback({ status: "rejected", message: error instanceof Error ? error.message : "Order status unavailable. Check the control plane before retrying." });
      return;
    } finally { setSubmitting(false); }

    const newOrderId = intake.order_id;
    const bookedNotional = Number(intake.decision?.notional_usd ?? intake.sized_notional_usd ?? sizingCalculation.notionalUsd);
    const bookedPosition = intake.decision?.position_id ? String(intake.decision.position_id) : "paper";
    const authReason = `Paper book ${bookedPosition} · $${bookedNotional.toLocaleString()} · the research hand cannot buy or sell`;

    setOrderFeedback({
      status: "authorized",
      message: `PAPER ${newOrderId} booked ${bookedPosition}: ${orderSide} ${activeAsset.symbol} ($${bookedNotional.toLocaleString()}). The research hand cannot buy or sell.`,
    });

    setWorkingOrders((prev) => [
      {
        orderId: newOrderId,
        submittedAt: sessionClock,
        symbol: activeAsset.symbol,
        side: orderSide,
        orderType: executionTactic,
        notionalUsd: bookedNotional,
        riskPct: equityRiskPct,
        entryPrice: activeAsset.last_price,
        stopLossPrice: sizingCalculation.stopLossPrice,
        takeProfitPrice: sizingCalculation.takeProfitPrice,
        status: "AUTHORIZED_FILLED",
        reason: authReason,
      },
      ...prev,
    ]);
  };

  return (
    <div
      style={{
        height: "100%",
        maxHeight: "100%",
        overflow: "hidden",
        background: "var(--c-bg)",
        color: "var(--c-text)",
        display: "flex",
        flexDirection: "column",
        fontFamily: "var(--font-ui)",
      }}
    >
      {/* ====================================================================
          1. TOP HEADER BAR
         ==================================================================== */}
      <header
        className="desk-topbar"
        style={{
          minHeight: "40px",
          padding: "4px 10px",
          background: "var(--c-surface-2)",
          borderBottom: "1px solid var(--c-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "10px",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            type="button"
            onClick={() => setSymbolsOpen((open) => !open)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "5px 10px",
              borderRadius: "6px",
              border: "1px solid var(--c-border)",
              background: symbolsOpen ? "var(--c-surface-3)" : "transparent",
              color: "var(--c-text-2)",
              fontSize: "11.5px",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            <GuideIcon name="markets" />
            {symbolsOpen ? "Hide symbols" : "Symbols"}
          </button>
          <div
            style={{
              display: "flex",
              background: "var(--c-surface)",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid var(--c-border)",
              gap: "4px",
            }}
          >
            <button
              type="button"
              onClick={() => {
                setActiveTrack("all");
                setAssetClassFilter("all");
              }}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "all" && assetClassFilter === "all" ? "var(--c-surface-3)" : "transparent",
                color: activeTrack === "all" && assetClassFilter === "all" ? "var(--c-text)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="all" />
              All
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("all");
                setAssetClassFilter("metals");
                handleSelectSymbol("GC");
              }}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: assetClassFilter === "metals" ? "rgba(244, 196, 96, 0.22)" : "transparent",
                color: assetClassFilter === "metals" ? "var(--c-warn)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="futures" color={assetClassFilter === "metals" ? "var(--c-warn)" : markColor("futures")} />
              Gold &amp; Silver
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("open_market");
                setAssetClassFilter("etfs");
                handleSelectSymbol("SPY");
              }}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: assetClassFilter === "etfs" ? "rgba(0, 200, 255, 0.18)" : "transparent",
                color: assetClassFilter === "etfs" ? "var(--c-accent)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="equity" color={assetClassFilter === "etfs" ? "var(--c-accent)" : markColor("equity")} />
              ETFs
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("open_market");
                setAssetClassFilter("stocks");
                handleSelectSymbol("NVDA");
              }}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "open_market" && assetClassFilter === "stocks" ? "rgba(0, 200, 255, 0.18)" : "transparent",
                color: activeTrack === "open_market" && assetClassFilter === "stocks" ? "var(--c-accent)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="equity" color={activeTrack === "open_market" && assetClassFilter === "stocks" ? "var(--c-accent)" : markColor("equity")} />
              Stocks
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("competition");
                setAssetClassFilter("crypto_perps");
                handleSelectSymbol("BTC-USD");
              }}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "competition" ? "rgba(0, 158, 115, 0.18)" : "transparent",
                color: activeTrack === "competition" ? "var(--c-good)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="competition" color={activeTrack === "competition" ? "var(--c-good)" : markColor("competition")} />
              Competition
            </button>
            <button
              type="button"
              onClick={() => handleSelectSymbol("MUB")}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11.5px",
                fontWeight: 600,
                background: selectedSymbol === "MUB" ? "rgba(244, 196, 96, 0.18)" : "transparent",
                color: selectedSymbol === "MUB" ? "var(--c-warn)" : "var(--c-muted)",
              }}
            >
              <GuideIcon name="reserve" color={selectedSymbol === "MUB" ? "var(--c-warn)" : markColor("reserve")} />
              Reserve
            </button>
          </div>
        </div>

        {/* Global Session Clock & WebSocket Latency Indicator (< 15ms) */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            title={feedAudit}
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              background: "var(--c-surface)",
              border: "1px solid var(--c-border)",
              fontSize: "11.5px",
              fontFamily: "var(--font-mono, monospace)",
              color: "var(--c-text-2)",
            }}
          >
            {feedAvailable ? (demoFeedActive ? "Paper" : "Live print") : "Waiting"} · {sessionClock}
          </div>
          <div
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              background: latencyBadge.background,
              border: latencyBadge.border,
              fontSize: "11.5px",
              fontFamily: "var(--font-mono, monospace)",
              color: latencyBadge.color,
            }}
          >
            {latencyBadge.label}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "5px 10px",
              borderRadius: "8px",
              border: "1px solid rgba(0, 158, 115, 0.35)",
              background: "rgba(0, 158, 115, 0.08)",
            }}
          >
            <select
              aria-label="Active role selector"
              value={role}
              onChange={(e) => setRole(e.target.value as ClientRoleId)}
              style={{
                padding: "5px 8px",
                borderRadius: "6px",
                border: "1px solid var(--c-border)",
                background: "var(--c-surface)",
                color: "var(--c-text)",
                fontSize: "11px",
                cursor: "pointer",
              }}
            >
              {(Object.keys(CLIENT_ROLE_PROFILES) as ClientRoleId[]).map((rid) => (
                <option key={rid} value={rid}>
                  {CLIENT_ROLE_PROFILES[rid].title}
                </option>
              ))}
            </select>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "2px",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid var(--c-border)",
              background: "var(--c-surface)",
            }}
          >
            <button
              type="button"
              onClick={() => void handleAutoFlattenAll()}
              disabled={!profile.canExecuteTraderOrders}
              title={profile.canExecuteTraderOrders ? "Close the open paper positions. Nothing goes to a broker." : "This role cannot close positions."}
              style={{
                padding: "5px 10px",
                borderRadius: "6px",
                border: profile.canExecuteTraderOrders ? "1px solid rgba(230, 159, 0, 0.55)" : "1px solid var(--c-border)",
                background: profile.canExecuteTraderOrders ? "rgba(230, 159, 0, 0.16)" : "transparent",
                color: profile.canExecuteTraderOrders ? "var(--c-warn)" : "var(--c-muted)",
                fontWeight: 700,
                fontSize: "11.5px",
                cursor: profile.canExecuteTraderOrders ? "pointer" : "not-allowed",
              }}
            >
              Close all paper positions
            </button>
          </div>
        </div>
      </header>
      {marketSessions?.venues && marketSessions.venues.length > 0 && (
        <div
          aria-label="Global market sessions status"
          className="desk-sessions"
          style={{
            padding: "3px 10px",
            background: "var(--c-surface)",
            borderBottom: "1px solid var(--c-border)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
            flexWrap: "wrap",
            fontSize: "10.5px",
          }}
        >
          <span title={`Venue sessions as of ${marketSessions.as_of_et ?? "ET"}`} style={{ fontWeight: 700, color: "var(--c-muted)", letterSpacing: "0.03em" }}>
            MARKETS:
          </span>
          {marketSessions.venues.map((v) => (
            <span
              key={v.venue_id}
              title={`${v.schedule_summary} — ${v.reason} (${v.countdown})`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                padding: "1px 6px",
                borderRadius: "5px",
                border: v.is_open ? "1px solid rgba(46, 184, 138, 0.4)" : "1px solid rgba(240, 128, 60, 0.4)",
                background: v.is_open ? "rgba(46, 184, 138, 0.08)" : "rgba(240, 128, 60, 0.08)",
                color: v.is_open ? "#2EB88A" : "#F0803C",
                fontFamily: "var(--font-mono, monospace)",
              }}
            >
              <span>{v.is_open ? "●" : "○"}</span>
              <strong style={{ color: "var(--c-text)" }}>{v.venue_name}</strong>
              <span>{v.status_label}</span>
            </span>
          ))}
        </div>
      )}
      {activeAsset.market_open === false && (marketSessions?.venues?.length ?? 0) > 0 && (
        <div
          style={{
            padding: "4px 14px 8px",
            background: "var(--c-surface)",
            borderBottom: "1px solid var(--c-border)",
            display: "flex",
            flexWrap: "wrap",
            gap: "8px",
            alignItems: "center",
            fontSize: "12px",
            color: "#F0803C",
          }}
        >
          <span>
            {activeAsset.symbol} is {activeAsset.market_label || "closed"} on {activeAsset.market_name}.
            {activeAsset.market_countdown ? ` ${activeAsset.market_countdown}.` : ""}
          </span>
          {(marketSessions?.venues ?? []).filter((venue) => venue.is_open).map((venue) => (
            <button
              key={venue.venue_id}
              type="button"
              onClick={() => {
                if (venue.look_symbol) handleSelectSymbol(venue.look_symbol);
              }}
              style={{
                padding: "2px 8px",
                borderRadius: "5px",
                border: "1px solid rgba(46, 184, 138, 0.45)",
                background: "rgba(46, 184, 138, 0.1)",
                color: "#2EB88A",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              Look at {venue.venue_name}
            </button>
          ))}
          <span style={{ color: "var(--c-muted)" }}>The chart can move. Open positions stay open.</span>
        </div>
      )}
      {/* ====================================================================
          MAIN 3-PANEL STUDIO GRID (20% Left | 55% Center | 25% Right)
         ==================================================================== */}
      <div
        className={`atlas-command-grid${symbolsOpen ? "" : " is-chart-focus"}`}
        style={{
          flex: 1,
          display: "grid",
          minHeight: 0,
          overflow: "hidden",
          gridTemplateRows: "minmax(0, 1fr)",
        }}
      >
        {/* ==================================================================
            2. LEFT PANEL: UNIVERSAL SCREENER & WATCHLIST (20% WIDTH)
           ================================================================== */}
        {symbolsOpen ? (
        <aside
          className="desk-symbol-column"
          style={{
            background: "var(--c-surface-2)",
            borderRight: "1px solid var(--c-border)",
            display: "flex",
            flexDirection: "column",
            padding: "8px 10px",
            gap: "6px",
            minHeight: 0,
            height: "100%",
            overflow: "hidden",
          }}
        >
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "4px",
              }}
            >
              <span style={{ fontSize: "12.5px", fontWeight: 700, color: "var(--c-muted)", letterSpacing: "0.03em" }}>
                {catalogTotal == null
                  ? "Symbols"
                  : `Showing ${catalogListings.length.toLocaleString()} of ${catalogTotal.toLocaleString()}`}
              </span>
              <span
                style={{
                  fontSize: "10px",
                  fontFamily: "var(--font-mono, monospace)",
                  color: "var(--c-good)",
                }}
              >
                {searchLatencyMs == null ? "Catalog —" : `${searchLatencyMs.toFixed(1)} ms`}
              </span>
            </div>

            {/* Command Palette Search Input (Ctrl + K) */}
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: "8px", top: "9px", color: "var(--c-accent)" }}>
                <GuideIcon name="search" />
              </span>
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search (Ctrl+K)"
                aria-label="Universal Asset Catalog Search"
                style={{
                  width: "100%",
                  padding: "8px 10px 8px 28px",
                  borderRadius: "6px",
                  border: "1px solid rgba(0, 200, 255, 0.3)",
                  background: "var(--c-bg)",
                  color: "var(--c-text)",
                  fontSize: "12px",
                }}
              />
            </div>
          </div>

          {/* Asset Class Filter Tabs: All, Gold & Silver, ETFs, Futures, FX, Stocks, Crypto */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "3px" }}>
            {(
              [
                { id: "all", label: "All", mark: "all" },
                { id: "metals", label: "Metals", mark: "futures" },
                { id: "etfs", label: "ETFs", mark: "equity" },
                { id: "futures", label: "Futures", mark: "futures" },
                { id: "fx", label: "FX", mark: "futures" },
                { id: "stocks", label: "Stocks", mark: "equity" },
                { id: "crypto_perps", label: "Crypto", mark: "crypto" },
              ] as const satisfies ReadonlyArray<{
                id: "all" | "metals" | "etfs" | "futures" | "fx" | "stocks" | "crypto_perps";
                label: string;
                mark: GuideIconName;
              }>
            ).map((tab) => {
              const on = assetClassFilter === tab.id;
              return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setAssetClassFilter(tab.id)}
                title={markLabel(tab.mark)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "3px",
                  padding: "3px 2px",
                  borderRadius: "5px",
                  border: "1px solid var(--c-border)",
                  background: on ? "var(--c-accent)" : "var(--c-surface)",
                  color: on ? "var(--c-bg)" : "var(--c-muted)",
                  fontSize: "12px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                <GuideIcon name={tab.mark} size={12} color={on ? "var(--c-bg)" : markColor(tab.mark)} />
                {tab.label}
              </button>
              );
            })}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
          <button
            type="button"
            aria-pressed={openNowOnly}
            onClick={() => setOpenNowOnly((on) => !on)}
            style={{
              flex: "none",
              padding: "3px 8px",
              borderRadius: "5px",
              border: openNowOnly ? "1px solid rgba(46, 184, 138, 0.7)" : "1px solid var(--c-border)",
              background: openNowOnly ? "rgba(46, 184, 138, 0.16)" : "var(--c-surface)",
              color: openNowOnly ? "#2EB88A" : "var(--c-muted)",
              fontSize: "12px",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Open now
          </button>
          <AssetMarkLegend />
          </div>

          <details style={{ fontSize: "12px", color: "var(--c-muted)", lineHeight: 1.45 }}>
            <summary style={{ cursor: "pointer", fontSize: "12.5px" }}>
              {universeCounts ? `Directory ${(universeCounts.listed_assets ?? universeCounts.total_assets).toLocaleString()} · ` : ""}About these prices
            </summary>
            {catalogNotice}
            {" "}
            Prices on this page are public last prints when a feed answers. Yahoo stock and futures prints can be delayed. Unlisted names stay without a quote.
          </details>

          {/* Real-Time Ticker List (paged to the height of the column) */}
          <div
            ref={catalogListRef}
            className="desk-symbol-list"
            style={{ display: "flex", flexDirection: "column", gap: "3px", flex: 1, minHeight: 0, overflow: "hidden" }}
          >
            {visibleListings.map((item) => {
              const isSelected = item.symbol === selectedSymbol;
              const mark = markForAsset(item.asset_class, item.exchange);
              return (
                <button
                  key={item.symbol}
                  type="button"
                  onClick={() => handleSelectSymbol(item.symbol)}
                  title={`${markLabel(mark)} · ${item.name} · ${item.market_name ?? item.exchange} · ${item.market_open ? "Open" : "Closed"} · VPIN ${(item.vpin * 100).toFixed(1)}% · ${item.regime}`}
                  className={`watch-row${isSelected ? " is-selected" : ""}`}
                  aria-pressed={isSelected}
                  data-asset-row={item.symbol}
                >
                  <span className="watch-row-sym">
                    <GuideIcon name={mark} color={markColor(mark)} />
                    <strong>{item.symbol}</strong>
                  </span>
                  {item.exchange === "UNLISTED" ? (
                    <span className="watch-row-price is-empty">Not listed</span>
                  ) : item.last_price <= 0 ? (
                    <span className="watch-row-price is-empty">No quote</span>
                  ) : (
                    <span className="watch-row-price" data-quote-price={String(item.last_price)}>
                      {item.last_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  )}
                  <span className="watch-row-name">{item.name}</span>
                  {item.exchange !== "UNLISTED" && item.last_price > 0 ? (
                    <span className="watch-row-chg" style={{ color: (item.change_pct ?? 0) >= 0 ? "var(--c-good)" : "var(--c-bad)" }}>
                      {(item.change_pct ?? 0) >= 0 ? "+" : ""}
                      {(item.change_pct ?? 0).toFixed(2)}%
                    </span>
                  ) : <span />}
                  {item.exchange !== "UNLISTED" && item.last_price > 0 ? (
                    <span className="watch-row-meta"><QuoteMeta quote={itemQuote(item)} compact /></span>
                  ) : null}
                  {item.is_active !== false && item.market_name ? (
                    <span className="watch-row-mkt" data-market-open={item.market_open ? "1" : "0"}>
                      {item.market_open ? "Open" : "Closed"} · {item.market_name}
                      {item.market_label ? ` · ${item.market_label}` : ""}
                    </span>
                  ) : null}
                </button>
              );
            })}
            <div className="desk-symbol-pager" style={{ marginTop: "auto" }}>
              <button type="button" disabled={listPage === 0} onClick={() => setListPage((n) => Math.max(0, n - 1))} aria-label="Previous symbols">‹ Prev</button>
              <span>
                {listRows.length === 0
                  ? (catalogLoading ? "Loading…" : "No symbols")
                  : `${(listPage * listCap + 1).toLocaleString()}–${Math.min(listRows.length, (listPage + 1) * listCap).toLocaleString()} of ${(catalogTotal != null && !openNowOnly ? catalogTotal : listRows.length).toLocaleString()}`}
              </span>
              <button type="button" disabled={!hasNextListPage} onClick={() => setListPage((n) => n + 1)} aria-label="Next symbols">Next ›</button>
            </div>
          </div>
        </aside>
        ) : null}

        {/* ==================================================================
            3. CENTER PANEL: DEEP CHART & CANVAS + BOTTOM BLOTTER (55% WIDTH)
           ================================================================== */}
        <section aria-label="Chart and order book"
          style={{
            background: "var(--c-bg)",
            display: "flex",
            flexDirection: "column",
            padding: "8px 12px",
            gap: "8px",
            overflow: "hidden",
            position: "relative",
            minHeight: 0,
            height: "100%",
          }}
        >
          {/* Instrument Telemetry & Timeframe Switcher Bar */}
          <div
            className="desk-quotebar"
            style={{
              padding: "5px 10px",
              borderRadius: "8px",
              background: "var(--c-surface-2)",
              border: "1px solid var(--c-border)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "nowrap",
              gap: "10px",
              flex: "none",
              minWidth: 0,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "nowrap", minWidth: 0, overflow: "hidden" }}>
              <div style={{ minWidth: 0 }} title={activeAsset.name}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <strong style={{ fontSize: "18px", fontFamily: "var(--font-mono, monospace)" }}>
                    {activeAsset.symbol}
                  </strong>
                  <span
                    style={{
                      fontSize: "10.5px",
                      padding: "2px 7px",
                      borderRadius: "4px",
                      background:
                        activeAsset.track === "open_market"
                          ? "rgba(0, 200, 255, 0.16)"
                          : "rgba(0, 158, 115, 0.16)",
                      color: activeAsset.track === "open_market" ? "var(--c-accent)" : "var(--c-good)",
                      fontWeight: 700,
                    }}
                  >
                    {activeAsset.asset_class.toUpperCase()} · {activeAsset.exchange === "UNLISTED" ? "Not listed" : activeAsset.exchange}
                  </span>
                  {activeAsset.market_name ? (
                    <span
                      className="asset-card-market"
                      data-market-open={activeAsset.market_open ? "1" : "0"}
                    >
                      {activeAsset.market_open ? "Open" : "Closed"} · {activeAsset.market_name}
                      {activeAsset.market_label ? ` · ${activeAsset.market_label}` : ""}
                    </span>
                  ) : null}
                </div>
                <div style={{ fontSize: "11px", color: "var(--c-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "36ch" }}>{activeAsset.name}</div>
              </div>

              <div
                data-quote-price={activeAsset.last_price > 0 ? String(activeAsset.last_price) : "none"}
                title={`VPIN ${(activeAsset.vpin * 100).toFixed(1)}% · OFI ${activeAsset.ofi_z.toFixed(2)} · Kyle λ ${activeAsset.kyles_lambda.toFixed(4)}`}
                style={{ fontFamily: "var(--font-mono, monospace)", fontSize: "15px", color: activeAsset.last_price > 0 ? "var(--c-good)" : "var(--c-muted)", fontWeight: 700 }}
              >
                {activeAsset.last_price > 0
                  ? activeAsset.last_price.toLocaleString(undefined, { minimumFractionDigits: 2 })
                  : "No quote"}
                <div style={{ fontSize: "10.5px", fontWeight: 400, whiteSpace: "nowrap" }}>
                  <QuoteMeta quote={itemQuote(activeAsset)} />
                </div>
              </div>
            </div>

            {/* Notes toggle */}
            <div style={{ display: "flex", gap: "4px", flexWrap: "wrap", alignItems: "center" }}>
              {/* chart-2: the timeframe switcher (incl. Live) lives inside AtlasChart: one chart, one switcher. */}
              <button
                type="button"
                onClick={() => setNotesOpen((open) => !open)}
                style={{
                  padding: "5px 9px",
                  borderRadius: "5px",
                  border: "1px solid var(--c-border)",
                  background: notesOpen ? "var(--c-surface-3)" : "var(--c-surface)",
                  color: "var(--c-muted)",
                  fontSize: "11px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {notesOpen ? "Hide notes" : "Notes"}
              </button>

            </div>
          </div>

          {/* One chart. It takes all the height left in the column. Notes are a popover, not a pushed block. */}
          <div
            style={{
              background: "var(--c-surface-2)",
              borderRadius: "8px",
              border: "1px solid var(--c-border)",
              padding: "6px",
              flex: "1 1 0",
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
              position: "relative",
            }}
          >
            {notesOpen ? (
              <div className="desk-notes-pop" role="dialog" aria-label="Chart notes" style={{ fontSize: "11px", color: "var(--c-muted)", lineHeight: 1.45 }}>
                <div>{gardenNote}</div>
                <div>{reserveNote}</div>
                <div>{timeframe === "1s" ? "The live feed and model inputs are shown together in the native viewer below." : modelGap ?? (chartRead ? `${chartRead.active.chart_source} · ${chartRead.active.feed_origin} · execution_permission ${chartRead.execution_permission}` : "Model is waiting to read this chart.")}</div>
                {timeframe !== "1s" && chartRead ? (
                  <>
                    <div>Competition {chartRead.competition.map((row) => `${row.symbol} ${row.direction}`).join(" · ")}</div>
                    <div>Open market {chartRead.open_market.map((row) => `${row.symbol} ${row.direction}`).join(" · ")}</div>
                  </>
                ) : null}
                <div>{barNote}</div>
                {reserveHoldings.length > 0 ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginTop: "6px" }}>
                    {reserveHoldings.filter((row) => row.in_sweep).map((row) => (
                      <button
                        key={row.symbol}
                        type="button"
                        onClick={() => handleSelectSymbol(row.symbol)}
                        style={{
                          padding: "3px 7px",
                          borderRadius: "4px",
                          border: "1px solid var(--c-border)",
                          background: selectedSymbol === row.symbol ? "rgba(244, 196, 96, 0.16)" : "var(--c-surface)",
                          color: "var(--c-text-2)",
                          fontSize: "10.5px",
                          cursor: "pointer",
                        }}
                      >
                        {row.symbol} ${row.target_usd}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <DeskChart
              symbol={chartSymbol ?? activeAsset.symbol}
              timeframe={timeframe}
              frameClassName="desk-chart-frame"
              fill
              gap={modelGap}
              onOpenMinute={() => setTimeframe("1m")}
              modelSymbol={selectedSymbol}
              onSnapshot={handleLiveSnapshot}
              onTimeframe={(tf) => { if (tf in TIMEFRAME_SECONDS) setTimeframe(tf as keyof typeof TIMEFRAME_SECONDS); }}
            />
          </div>

          {/* Collapsible Bottom Drawer: Active Positions Blotter, Working Orders & Audit History */}
          <div
            style={{
              background: "var(--c-surface-2)",
              borderRadius: "8px",
              border: "1px solid var(--c-border)",
              padding: "3px 10px",
              flex: "none",
              position: "relative",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  onClick={() => {
                    setBottomTab("positions");
                    setBottomDrawerOpen(true);
                  }}
                  style={{
                    padding: "5px 10px",
                    borderRadius: "5px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    background: bottomTab === "positions" ? "var(--c-surface-3)" : "transparent",
                    color: bottomTab === "positions" ? "var(--c-good)" : "var(--c-muted)",
                  }}
                >
                  Active Positions Blotter ({positions.filter((p) => p.status === "OPEN").length})
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setBottomTab("orders");
                    setBottomDrawerOpen(true);
                  }}
                  style={{
                    padding: "5px 10px",
                    borderRadius: "5px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    background: bottomTab === "orders" ? "var(--c-surface-3)" : "transparent",
                    color: bottomTab === "orders" ? "var(--c-accent)" : "var(--c-muted)",
                  }}
                >
                  Working &amp; Bracket Orders ({workingOrders.length})
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setBottomTab("audit");
                    setBottomDrawerOpen(true);
                  }}
                  style={{
                    padding: "5px 10px",
                    borderRadius: "5px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "11.5px",
                    fontWeight: 700,
                    background: bottomTab === "audit" ? "var(--c-surface-3)" : "transparent",
                    color: bottomTab === "audit" ? "var(--c-text)" : "var(--c-muted)",
                  }}
                >
                  Execution Audit Log ({auditLogs.length})
                </button>
              </div>

              <button
                type="button"
                onClick={() => setBottomDrawerOpen((prev) => !prev)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--c-muted)",
                  cursor: "pointer",
                  fontSize: "11.5px",
                }}
              >
                {bottomDrawerOpen ? "Collapse Drawer ▾" : "Expand Drawer ▴"}
              </button>
            </div>

            {bottomDrawerOpen && (
              <div className="desk-blotter-pop">
                {bottomTab === "positions" && (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11.5px" }}>
                    <thead>
                      <tr style={{ color: "var(--c-muted)", borderBottom: "1px solid var(--c-border)", textAlign: "left" }}>
                        <th style={{ padding: "6px" }}>Symbol</th>
                        <th style={{ padding: "6px" }}>Side</th>
                        <th style={{ padding: "6px" }}>Qty / Notional</th>
                        <th style={{ padding: "6px" }}>Entry / Mark</th>
                        <th style={{ padding: "6px" }}>ATR Stop / TP</th>
                        <th style={{ padding: "6px" }}>Unrealized PnL</th>
                        <th style={{ padding: "6px" }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.length === 0 ? (
                        <tr>
                          <td colSpan={7} style={{ padding: "8px 6px", color: "var(--c-muted)" }}>
                            No open paper positions.
                          </td>
                        </tr>
                      ) : null}
                      {positions.map((pos) => (
                        <tr key={pos.positionId} style={{ borderBottom: "1px solid var(--c-border)" }}>
                          <td style={{ padding: "6px", fontWeight: 700, fontFamily: "var(--font-mono, monospace)" }}>
                            {pos.symbol}
                          </td>
                          <td style={{ padding: "6px", color: pos.side === "LONG" ? "var(--c-good)" : "var(--c-bad)", fontWeight: 700 }}>
                            {pos.side}
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)" }}>
                            {pos.quantity} (${pos.notionalUsd.toLocaleString()})
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)" }}>
                            ${pos.entryPrice.toLocaleString()} / ${pos.markPrice.toLocaleString()}
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)", color: "var(--c-muted)" }}>
                            {pos.stopLossPrice > 0 ? `SL $${pos.stopLossPrice}` : "SL —"}
                            {pos.takeProfitPrice > 0 ? ` · TP $${pos.takeProfitPrice}` : ""}
                          </td>
                          <td
                            style={{
                              padding: "6px",
                              fontFamily: "var(--font-mono, monospace)",
                              color: pos.unrealizedPnlUsd >= 0 ? "var(--c-good)" : "var(--c-bad)",
                              fontWeight: 700,
                            }}
                          >
                            {pos.unrealizedPnlUsd >= 0 ? "+" : ""}${pos.unrealizedPnlUsd.toFixed(2)}
                          </td>
                          <td style={{ padding: "6px" }}>
                            <span
                              style={{
                                fontSize: "10px",
                                padding: "2px 6px",
                                borderRadius: "4px",
                                background:
                                  pos.status === "OPEN" ? "rgba(0, 158, 115,0.15)" : "rgba(213, 94, 0,0.15)",
                                color: pos.status === "OPEN" ? "var(--c-good)" : "var(--c-bad)",
                              }}
                            >
                              {pos.status}
                            </span>
                            <button
                              type="button"
                              onClick={() => void handleClosePosition(pos)}
                              disabled={closingPositionId === pos.positionId || !profile.canExecuteTraderOrders}
                              style={{
                                marginLeft: "6px",
                                border: "1px solid var(--c-border)",
                                background: "transparent",
                                color: "var(--c-text)",
                                borderRadius: "4px",
                                padding: "2px 6px",
                                cursor: "pointer",
                                fontSize: "10px",
                                fontWeight: 700,
                              }}
                            >
                              {closingPositionId === pos.positionId ? "Closing" : "Close"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                {bottomTab === "orders" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {workingOrders.map((ord) => (
                      <div
                        key={ord.orderId}
                        style={{
                          padding: "7px 10px",
                          borderRadius: "6px",
                          background: "var(--c-surface)",
                          border: "1px solid var(--c-border)",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          fontSize: "11.5px",
                        }}
                      >
                        <div>
                          <strong style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--c-text)" }}>
                            {ord.orderId} · {ord.side} {ord.symbol} (${ord.notionalUsd.toLocaleString()})
                          </strong>{" "}
                          <span style={{ color: "var(--c-muted)" }}>
                            via {ord.orderType} · Risk {ord.riskPct.toFixed(2)}% · SL ${ord.stopLossPrice} / TP $
                            {ord.takeProfitPrice}
                          </span>
                          <div style={{ fontSize: "10.5px", color: "var(--c-muted)", marginTop: "2px" }}>{ord.reason}</div>
                        </div>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            padding: "2px 7px",
                            borderRadius: "4px",
                            background:
                              ord.status === "REJECTED" ? "rgba(213, 94, 0,0.18)" : "rgba(0, 158, 115,0.16)",
                            color: ord.status === "REJECTED" ? "var(--c-bad)" : "var(--c-good)",
                          }}
                        >
                          {ord.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {bottomTab === "audit" && (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "4px",
                      fontFamily: "var(--font-mono, monospace)",
                      fontSize: "11px",
                      color: "var(--c-muted)",
                    }}
                  >
                    {auditLogs.map((log, i) => (
                      <div key={i} style={{ padding: "4px 6px", background: "var(--c-surface)", borderRadius: "4px" }}>
                        {log}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* ==================================================================
            4. RIGHT PANEL: ORDER DESK & REMAINING-ROOM HUD (25% WIDTH)
           ================================================================== */}
        <aside
          className="desk-ticket-col"
          data-tab={ticketTab}
          style={{
            background: "var(--c-surface-2)",
            borderLeft: "1px solid var(--c-border)",
            padding: "8px 10px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            overflow: "hidden",
            minHeight: 0,
          }}
        >
          <div className="desk-ticket-tabs" role="tablist" aria-label="Order desk">
            <button type="button" role="tab" aria-selected={ticketTab === "order"} onClick={() => setTicketTab("order")}>Order</button>
            <button type="button" role="tab" aria-selected={ticketTab === "risk"} onClick={() => setTicketTab("risk")}>Risk room</button>
          </div>
          {/* Prop Risk Remaining-Room Gauge */}
          <div
            className="desk-risk-card"
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: "var(--c-surface)",
              border: "1px solid rgba(0, 200, 255, 0.25)",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "2px", minWidth: 0 }}>
              <span style={{ fontSize: "11px", fontWeight: 800, color: "var(--c-accent)", letterSpacing: "0.04em" }}>
                Risk room
              </span>
              <span style={{ fontSize: "11px", fontFamily: "var(--font-mono, monospace)", fontWeight: 600, overflowWrap: "anywhere", lineHeight: 1.35 }}>
                Equity ${accountEquityUsd.toLocaleString()} · free cash ${freeCashUsd.toLocaleString()} · {researchHand ? `hand ${researchHand}` : "hand not linked"} · watching {(marketSessions?.venues ?? []).filter((venue) => venue.is_open).map((venue) => venue.venue_name).join(", ") || "the session clock"} · scored book crypto 4h · cannot buy or sell
              </span>
            </div>
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <input
                type="number"
                min={0.01}
                step={0.01}
                value={capitalAmount}
                onChange={(event) => setCapitalAmount(event.target.value)}
                aria-label="Paper amount in USD"
                style={{
                  width: "110px",
                  padding: "6px 8px",
                  borderRadius: "5px",
                  background: "var(--c-bg)",
                  border: "1px solid var(--c-border)",
                  color: "var(--c-text)",
                  fontFamily: "var(--font-mono, monospace)",
                  fontSize: "12px",
                }}
              />
              <button
                type="button"
                disabled={capitalBusy}
                onClick={() => void handlePaperCapital("deposit")}
                style={{
                  padding: "6px 8px",
                  borderRadius: "5px",
                  border: "1px solid var(--c-border)",
                  background: "var(--c-bg)",
                  color: "var(--c-text)",
                  fontSize: "11px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Deposit paper cash
              </button>
              <button
                type="button"
                disabled={capitalBusy}
                onClick={() => void handlePaperCapital("withdraw")}
                style={{
                  padding: "6px 8px",
                  borderRadius: "5px",
                  border: "1px solid var(--c-border)",
                  background: "var(--c-bg)",
                  color: "var(--c-text)",
                  fontSize: "11px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Withdraw free cash
              </button>
            </div>
            <div style={{ fontSize: "10.5px", color: "var(--c-muted)" }}>
              Paper ledger on this desk. A deposit funds operator orders up to free cash. The research hand cannot buy or sell.
            </div>

            {/* 1. 4.0% Daily Loss Breaker */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "var(--c-muted)" }}>{dailyLossLimitPct.toFixed(1)}% Daily Loss Breaker</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--c-good)" }}>
                  ${sizingCalculation.dailyRoomUsd.toLocaleString()} cushion (
                  {(dailyLossLimitPct - dailyLossUsedPct).toFixed(2)}% left)
                </span>
              </div>
              <div style={{ height: "6px", background: "var(--c-bg)", borderRadius: "4px", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(100, (sizingCalculation.postTradeDailyLossPct / dailyLossLimitPct) * 100)}%`,
                    height: "100%",
                    background:
                      sizingCalculation.postTradeDailyLossPct > dailyLossLimitPct ? "var(--c-bad)" : "var(--c-good)",
                  }}
                />
              </div>
            </div>

            {/* 2. 8.0% Max Trailing Drawdown Floor */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "var(--c-muted)" }}>{drawdownMeterLabel}</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--c-accent)" }}>
                  ${sizingCalculation.trailingRoomUsd.toLocaleString()} cushion (
                  {(trailingDdFloorPct - trailingDdUsedPct).toFixed(2)}% left)
                </span>
              </div>
              <div style={{ height: "6px", background: "var(--c-bg)", borderRadius: "4px", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(100, (sizingCalculation.postTradeTrailingDdPct / trailingDdFloorPct) * 100)}%`,
                    height: "100%",
                    background: "var(--c-accent)",
                  }}
                />
              </div>
            </div>

            {/* 3. 35% Single-Day Profit Consistency Gate */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "var(--c-muted)" }}>35% Single-Day Consistency Gate</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "var(--c-text-2)" }}>
                  {singleDayConsistencyUsedPct.toFixed(1)}% / {singleDayConsistencyMaxPct.toFixed(1)}% PASS
                </span>
              </div>
              <div style={{ height: "6px", background: "var(--c-bg)", borderRadius: "4px", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${(singleDayConsistencyUsedPct / singleDayConsistencyMaxPct) * 100}%`,
                    height: "100%",
                    background: "#A855F7",
                  }}
                />
              </div>
            </div>
          </div>

          {/* Pre-Trade Bracket Order Ticket */}
          <div
            className="desk-order-card"
            style={{
              padding: "8px 10px",
              borderRadius: "8px",
              background: "var(--c-surface)",
              border: "1px solid var(--c-border)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ fontSize: "12px", letterSpacing: "0.03em" }}>
                Order
              </strong>
              <span
                style={{
                  fontSize: "10px",
                  fontFamily: "var(--font-mono, monospace)",
                  color: "var(--c-good)",
                }}
              >
                Control Plane Gated
              </span>
            </div>

            {/* BUY / SELL Selector */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 110px), 1fr))", gap: "6px" }}>
              <button
                type="button"
                onClick={() => setOrderSide("BUY")}
                style={{
                  padding: "6px",
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 800,
                  fontSize: "12px",
                  background: orderSide === "BUY" ? "var(--c-good)" : "var(--c-bg)",
                  color: orderSide === "BUY" ? "var(--c-bg)" : "var(--c-muted)",
                }}
              >
                BUY / LONG {activeAsset.symbol}
              </button>
              <button
                type="button"
                onClick={() => setOrderSide("SELL")}
                style={{
                  padding: "6px",
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 800,
                  fontSize: "12px",
                  background: orderSide === "SELL" ? "var(--c-bad)" : "var(--c-bg)",
                  color: orderSide === "SELL" ? "var(--c-bg)" : "var(--c-muted)",
                }}
              >
                SELL / SHORT {activeAsset.symbol}
              </button>
            </div>

            {/* Execution Tactic Selector: Market / Limit / Almgren-Chriss TWAP */}
            <div>
              <label style={{ fontSize: "10.5px", color: "var(--c-muted)", display: "block", marginBottom: "2px" }}>
                Execution Tactic
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 90px), 1fr))", gap: "4px" }}>
                {(
                  [
                    { id: "MARKET", label: "Market" },
                    { id: "LIMIT", label: "Limit" },
                    { id: "ALMGREN_CHRISS_TWAP", label: "Almgren-Chriss" },
                  ] as const
                ).map((tac) => (
                  <button
                    key={tac.id}
                    type="button"
                    onClick={() => setExecutionTactic(tac.id)}
                    style={{
                      padding: "4px 4px",
                      borderRadius: "5px",
                      border: "1px solid var(--c-border)",
                      background: executionTactic === tac.id ? "var(--c-accent)" : "var(--c-bg)",
                      color: executionTactic === tac.id ? "var(--c-bg)" : "var(--c-muted)",
                      fontSize: "10.5px",
                      fontWeight: 700,
                      cursor: "pointer",
                    }}
                  >
                    {tac.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Equity Risk % Sizing Slider (0.50% - 0.75% Institutional Rule) */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "var(--c-muted)" }}>Per-Trade Equity Risk (0.50%–{riskCapPct.toFixed(2)}% Cap)</span>
                <span
                  style={{
                    fontFamily: "var(--font-mono, monospace)",
                    fontWeight: 700,
                    color: equityRiskPct >= 0.5 && equityRiskPct <= riskCapPct ? "var(--c-good)" : "var(--c-bad)",
                  }}
                >
                  {equityRiskPct.toFixed(2)}% (${sizingCalculation.riskDollars})
                </span>
              </div>
              <input
                type="range"
                min={0.25}
                max={1.1}
                step={0.05}
                value={equityRiskPct}
                onChange={(e) => setEquityRiskPct(Number(e.target.value))}
                style={{ width: "100%" }}
              />
            </div>

            {/* Mandatory Structural ATR Stop-Loss & Reward:Risk */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 110px), 1fr))", gap: "8px" }}>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--c-muted)", display: "block", marginBottom: "3px" }}>
                  Mandatory ATR Stop (bps)
                </label>
                <input
                  type="number"
                  min={20}
                  max={500}
                  value={atrStopBps}
                  onChange={(e) => setAtrStopBps(Number(e.target.value) || 120)}
                  style={{
                    width: "100%",
                    padding: "6px 8px",
                    borderRadius: "5px",
                    background: "var(--c-bg)",
                    border: "1px solid var(--c-border)",
                    color: "var(--c-text)",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "12px",
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: "10.5px", color: "var(--c-muted)", display: "block", marginBottom: "3px" }}>
                  Take-Profit R:R Multiple
                </label>
                <input
                  type="number"
                  min={1.0}
                  max={5.0}
                  step={0.1}
                  value={rewardRiskMultiple}
                  onChange={(e) => setRewardRiskMultiple(Number(e.target.value) || 2.0)}
                  style={{
                    width: "100%",
                    padding: "6px 8px",
                    borderRadius: "5px",
                    background: "var(--c-bg)",
                    border: "1px solid var(--c-border)",
                    color: "var(--c-text)",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "12px",
                  }}
                />
              </div>
            </div>

            {/* Auto-Calculated Position Size & Bracket Summary */}
            <div
              style={{
                padding: "6px 8px",
                borderRadius: "6px",
                background: "var(--c-bg)",
                border: "1px solid var(--c-border)",
                fontFamily: "var(--font-mono, monospace)",
                fontSize: "10.5px",
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                columnGap: "12px",
                rowGap: "3px",
              }}
            >
              {activeAsset.last_price <= 0 ? (
                <div style={{ color: "var(--c-muted)", gridColumn: "1 / -1" }}>No quote is stored for this name. Size stays at zero. Nothing is sent.</div>
              ) : null}
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--c-muted)" }}>Auto-Sized Notional:</span>
                <strong style={{ color: "var(--c-text)" }}>${sizingCalculation.notionalUsd.toLocaleString()}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--c-muted)" }}>Auto-Sized Quantity:</span>
                <strong style={{ color: "var(--c-accent)" }}>
                  {sizingCalculation.quantity} {activeAsset.symbol}
                </strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--c-muted)" }}>ATR Stop-Loss Bracket:</span>
                <strong style={{ color: "var(--c-bad)" }}>${sizingCalculation.stopLossPrice}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--c-muted)" }}>Take-Profit Bracket:</span>
                <strong style={{ color: "var(--c-good)" }}>${sizingCalculation.takeProfitPrice}</strong>
              </div>
            </div>

            {/* Submit Button to ActionableControlPlaneEngine */}
            <button
              type="button"
              onClick={() => void handleSubmitBracketOrder()}
              style={{
                width: "100%",
                padding: "8px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                fontWeight: 800,
                fontSize: "12.5px",
                background: sizingCalculation.hardRiskBreach
                  ? "rgba(213, 94, 0, 0.25)"
                  : orderSide === "BUY"
                  ? "var(--c-good)"
                  : "var(--c-bad)",
                color: sizingCalculation.hardRiskBreach ? "var(--c-bad)" : "var(--c-bg)",
              }}
            >
              {accountEquityUsd <= 0 || !depositsLoaded
                ? "NO CAPITAL · CANNOT BUY OR SELL"
                : sizingCalculation.exceedsFreeCash
                ? "ABOVE FREE CASH · PAPER ONLY"
                : sizingCalculation.hardRiskBreach
                ? "⚠️ RISK GATE BLOCKED (CLICK TO INSPECT)"
                : `SUBMIT PAPER ${orderSide} BRACKET (${executionTactic})`}
            </button>

            {/* Real-Time Control Plane Feedback Banner */}
            <div
              title={orderFeedback.message}
              style={{
                padding: "5px 8px",
                borderRadius: "6px",
                fontSize: "10.5px",
                lineHeight: 1.3,
                maxHeight: "3.9em",
                overflow: "hidden",
                fontFamily: "var(--font-mono, monospace)",
                background:
                  orderFeedback.status === "rejected"
                    ? "rgba(213, 94, 0, 0.12)"
                    : orderFeedback.status === "authorized"
                    ? "rgba(0, 158, 115, 0.12)"
                    : "var(--c-bg)",
                border:
                  orderFeedback.status === "rejected"
                    ? "1px solid rgba(213, 94, 0, 0.4)"
                    : orderFeedback.status === "authorized"
                    ? "1px solid rgba(0, 158, 115, 0.4)"
                    : "1px solid var(--c-border)",
                color:
                  orderFeedback.status === "rejected"
                    ? "var(--c-bad)"
                    : orderFeedback.status === "authorized"
                    ? "var(--c-good)"
                    : "var(--c-muted)",
              }}
            >
              {orderFeedback.message}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default StreamlinedTradingStudio;

