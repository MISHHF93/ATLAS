"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type LiveCandlePoint } from "../market/LiveChartEngine";
import { WhaleOnChart } from "../market/WhaleOnChart";
import { DeskChart } from "../market/DeskChart";
import { AppNav } from "../shell/AppNav";
import { AssetMarkLegend, GuideIcon, markColor, markForAsset, markLabel, type GuideIconName } from "../shell/guideIcons";
import { CLIENT_ROLE_PROFILES, useRoleContext, type ClientRoleId } from "../../context/RoleContext";
import { fetchLibraryQuotes, libraryQuoteSymbols } from "../../lib/libraryQuotes";
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
  execution_permission: "none";
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
    last_price: 68410.0,
    change_pct: 1.42,
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
    last_price: 2645.5,
    change_pct: 2.15,
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
    last_price: 176.8,
    change_pct: 3.18,
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
    last_price: 142.1,
    change_pct: 2.14,
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
    last_price: 584.2,
    change_pct: 0.42,
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
    last_price: 231.45,
    change_pct: 0.65,
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
    last_price: 5882.5,
    change_pct: 0.45,
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
    last_price: 20545.25,
    change_pct: 0.92,
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
    last_price: 71.45,
    change_pct: -1.15,
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
    last_price: 2738.6,
    change_pct: 0.88,
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
  const [assetClassFilter, setAssetClassFilter] = useState<"all" | "equities" | "crypto_perps" | "futures">("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchLatencyMs, setSearchLatencyMs] = useState<number | null>(null);
  const [universeCounts, setUniverseCounts] = useState<{
    total_assets: number;
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
  const [timeframe, setTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("1m");
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
  const [killSwitchEngaged, setKillSwitchEngaged] = useState<boolean>(false);

  // Collapsible Bottom Drawer State
  const [bottomDrawerOpen, setBottomDrawerOpen] = useState<boolean>(false);
  const [notesOpen, setNotesOpen] = useState(false);
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
      "ActionableControlPlaneEngine Ready · Strict 0.50%–0.75% Equity Risk Sizing · Mandatory ATR Bracket Armed.",
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
  } | null>(null);
  const [controlAvailable, setControlAvailable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/control/state", { cache: "no-store" });
        if (!response.ok) throw new Error("Control plane unavailable");
        const state = await response.json();
        if (active) { setAccount(state.account); setKillSwitchEngaged(state.kill_switch_engaged); setControlAvailable(true); }
      } catch { if (active) setControlAvailable(false); }
    };
    void refresh();
    const timer = setInterval(refresh, 2000);
    return () => { active = false; clearInterval(timer); };
  }, []);

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const catalogListRef = useRef<HTMLDivElement | null>(null);
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
  const prevSymbolRef = useRef<string>("BTC-USD");
  selectedSymbolRef.current = selectedSymbol;

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
              return {
                ...item,
                last_price: quote.price,
                change_pct: quote.change_pct ?? item.change_pct,
                quote_origin: quote.feed_origin,
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

  useEffect(() => {
    catalogListRef.current?.scrollTo({ top: 0 });
  }, [searchQuery, activeTrack, assetClassFilter]);

  useEffect(() => {
    if (!symbolsOpen) return;
    const el = catalogListRef.current;
    if (!el || catalogLoading) return;
    const total = catalogTotalRef.current;
    if (total == null || catalogOffsetRef.current >= total) return;
    if (el.scrollHeight <= el.clientHeight + 8) loadCatalogPage(false);
  }, [symbolsOpen, catalogListings.length, catalogLoading, loadCatalogPage]);

  const onCatalogScroll = useCallback(() => {
    const el = catalogListRef.current;
    if (!el || catalogLoadingRef.current) return;
    const total = catalogTotalRef.current;
    if (total != null && catalogOffsetRef.current >= total) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 72) loadCatalogPage(false);
  }, [loadCatalogPage]);

  // Dynamic On-Demand WebSocket Subscription Multiplexer (/ws/market-stream).
  // History comes from /api/market/bars. The socket only moves the right edge.
  const timeframeRef = useRef(timeframe);
  useEffect(() => {
    timeframeRef.current = timeframe;
  }, [timeframe]);

  useEffect(() => {
    const requestId = barsRequestRef.current + 1;
    barsRequestRef.current = requestId;
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
            setDemoFeedActive(pkt.data_mode !== "observed");
            const tickSymbol = String(pkt.symbol).toUpperCase();
            if (tickSymbol === selectedSymbolRef.current.toUpperCase()) {
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
                      last_price: item.quote_origin && demoPrint ? item.last_price : nextPrice > 0 ? nextPrice : item.last_price,
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
        if (tick.data_mode === "observed") setDemoFeedActive(false);
        else if (gateway.demo_mode || tick.data_mode === "demo") setDemoFeedActive(true);
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
    () =>
      catalogListings.find((item) => item.symbol === selectedSymbol) ??
      DEFAULT_STUDIO_LISTINGS.find((item) => item.symbol === selectedSymbol) ??
      placeholderListing(selectedSymbol, publicClose ?? 0),
    [catalogListings, publicClose, selectedSymbol]
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
      ? { background: "#121722", border: "1px solid rgba(255,255,255,0.07)", color: "#94A3B8", label: "Socket —" }
      : wsLatencyMs < 15
      ? { background: "rgba(0, 242, 157, 0.1)", border: "1px solid rgba(0, 242, 157, 0.3)", color: "#00F29D", label: `${wsLatencyMs.toFixed(0)} ms` }
      : wsLatencyMs < 50
      ? { background: "rgba(245, 158, 11, 0.12)", border: "1px solid rgba(245, 158, 11, 0.45)", color: "#FBBF24", label: `${wsLatencyMs.toFixed(0)} ms` }
      : { background: "rgba(255, 59, 105, 0.12)", border: "1px solid rgba(255, 59, 105, 0.45)", color: "#FF3B69", label: `${wsLatencyMs.toFixed(0)} ms` };
  const drawdownMeterLabel =
    deskTrack === "open_market"
      ? `${trailingDdFloorPct.toFixed(1)}% Static Drawdown Floor`
      : `${trailingDdFloorPct.toFixed(1)}% Trailing Drawdown Floor`;

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setSessionClock(deskTrack === "open_market" ? nyseSessionCountdown(now) : "24/7 continuous");
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, [deskTrack]);

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

    const withinRiskCap = equityRiskPct >= 0.5 && equityRiskPct <= riskCapPct;
    const hardRiskBreach =
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
    };
  }, [
    account, accountEquityUsd, controlAvailable, feedAvailable, submitting, dailyLossUsedPct, trailingDdUsedPct,
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

  // Emergency Kill-Switch Handler
  const handleToggleKillSwitch = async () => {
    if (!profile.canTriggerKillSwitch) {
      setOrderFeedback({
        status: "rejected",
        message: "Kill-switch is limited to prop_firm_admin. This role cannot engage or reset it.",
      });
      return;
    }
    const nextState = !killSwitchEngaged;

    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000" ? "" : "";
      const response = await fetch(`${apiBase}/api/control/kill-switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Atlas-Role": role },
        body: JSON.stringify({
          engaged: nextState,
          reason: nextState ? "studio_emergency_kill_switch" : "studio_operator_reset",
        }),
      });
      if (!response.ok) throw new Error(response.status === 403 ? "Role is not authorized to trigger the kill switch." : "Kill-switch request failed; state is unconfirmed.");
    } catch (error) {
      setOrderFeedback({
        status: "rejected",
        message: error instanceof Error ? error.message : "Kill-switch request failed; state is unconfirmed.",
      });
      return;
    }
    setKillSwitchEngaged(nextState);
    if (nextState) {
      setPositions((prev) => prev.map((p) => ({ ...p, status: "FLATTENED" })));
      setOrderFeedback({
        status: "rejected",
        message: "EMERGENCY KILL-SWITCH ENGAGED · Paper positions flattened · Order intake locked.",
      });
    } else {
      setOrderFeedback({
        status: "nominal",
        message: "Kill-Switch reset by operator · ActionableControlPlaneEngine nominal.",
      });
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
    } catch (error) {
      setOrderFeedback({
        status: "rejected",
        message: error instanceof Error ? error.message : "Flatten request failed; state is unconfirmed.",
      });
      return;
    }
    setPositions((prev) => prev.map((p) => ({ ...p, status: "FLATTENED" })));
    setOrderFeedback({
      status: "authorized",
      message: "1-CLICK AUTO-FLATTEN EXECUTED · Paper positions closed; no broker orders sent.",
    });
    setAuditLogs((prev) => [
      `${new Date().toISOString()} | control_plane | 1-Click Auto-Flatten closed all active positions | status=FLATTENED`,
      ...prev.slice(0, 24),
    ]);
  };

  // Submit Pre-Trade Bracket Order to ActionableControlPlaneEngine
  const handleSubmitBracketOrder = async () => {
    if (sizingCalculation.hardRiskBreach) {
      const rejectReason = !profile.canExecuteTraderOrders
        ? "Rejected: this role cannot submit orders. Research output stays execution_permission none."
        : activeAsset.last_price <= 0
        ? "Rejected: this name has no quote. Nothing was sent."
        : killSwitchEngaged
        ? "Rejected: Emergency Kill-Switch is currently engaged."
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
          execution_permission: "none", telemetry: { vpin: activeAsset.vpin },
        }),
      });
      if (!response.ok) throw new Error(`Control plane returned HTTP ${response.status}`);
      intake = await response.json();
      if (intake.decision.control_plane_decision !== "authorized_and_executed") {
        throw new Error(intake.decision.violations.join("; "));
      }
    } catch (error) {
      setOrderFeedback({ status: "rejected", message: error instanceof Error ? error.message : "Order status unavailable. Check the control plane before retrying." });
      return;
    } finally { setSubmitting(false); }

    const newOrderId = intake.order_id;
    const authReason = `Authorized by ActionableControlPlaneEngine (${equityRiskPct.toFixed(
      2
    )}% risk = $${sizingCalculation.riskDollars} · SL $${sizingCalculation.stopLossPrice} · TP $${
      sizingCalculation.takeProfitPrice
    })`;

    setOrderFeedback({
      status: "authorized",
      message: `PAPER ${newOrderId} AUTHORIZED: ${orderSide} ${sizingCalculation.quantity} ${
        activeAsset.symbol
      } ($${sizingCalculation.notionalUsd.toLocaleString()}) via ${executionTactic}`,
    });

    setWorkingOrders((prev) => [
      {
        orderId: newOrderId,
        submittedAt: sessionClock,
        symbol: activeAsset.symbol,
        side: orderSide,
        orderType: executionTactic,
        notionalUsd: sizingCalculation.notionalUsd,
        riskPct: equityRiskPct,
        entryPrice: activeAsset.last_price,
        stopLossPrice: sizingCalculation.stopLossPrice,
        takeProfitPrice: sizingCalculation.takeProfitPrice,
        status: executionTactic === "ALMGREN_CHRISS_TWAP" ? "WORKING_TWAP_CHILD" : "AUTHORIZED_FILLED",
        reason: authReason,
      },
      ...prev,
    ]);

    setPositions((prev) => [
      {
        positionId: `POS-${Date.now().toString().slice(-3)}`,
        symbol: activeAsset.symbol,
        track: activeAsset.track,
        side: orderSide === "BUY" ? "LONG" : "SHORT",
        quantity: sizingCalculation.quantity,
        notionalUsd: sizingCalculation.notionalUsd,
        entryPrice: activeAsset.last_price,
        markPrice: activeAsset.last_price,
        stopLossPrice: sizingCalculation.stopLossPrice,
        takeProfitPrice: sizingCalculation.takeProfitPrice,
        unrealizedPnlUsd: 0.0,
        tactic: executionTactic,
        status: "OPEN",
      },
      ...prev,
    ]);

    setAuditLogs((prev) => [
      `${new Date().toISOString()} | control_plane | Authorized ${newOrderId} ${orderSide} ${
        activeAsset.symbol
      } notional=$${sizingCalculation.notionalUsd} risk=${equityRiskPct.toFixed(2)}% | execution_permission=none`,
      ...prev.slice(0, 24),
    ]);
  };

  return (
    <div
      style={{
        height: "100vh",
        maxHeight: "100vh",
        overflow: "hidden",
        background: "#070A0F",
        color: "#F8FAFC",
        display: "flex",
        flexDirection: "column",
        fontFamily: "var(--font-sans, Inter, system-ui, sans-serif)",
      }}
    >
      <AppNav />
      {/* ====================================================================
          1. TOP HEADER BAR
         ==================================================================== */}
      <header
        style={{
          minHeight: "48px",
          padding: "6px 14px",
          background: "#0B0F17",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
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
              border: "1px solid rgba(255,255,255,0.12)",
              background: symbolsOpen ? "#1E293B" : "transparent",
              color: "#E2E8F0",
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
              background: "#121722",
              padding: "3px",
              borderRadius: "8px",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              gap: "4px",
            }}
          >
            <button
              type="button"
              onClick={() => setActiveTrack("all")}
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
                background: activeTrack === "all" ? "#1E293B" : "transparent",
                color: activeTrack === "all" ? "#F8FAFC" : "#94A3B8",
              }}
            >
              <GuideIcon name="all" />
              All
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("open_market");
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
                background: activeTrack === "open_market" ? "rgba(0, 200, 255, 0.18)" : "transparent",
                color: activeTrack === "open_market" ? "#00C8FF" : "#94A3B8",
              }}
            >
              <GuideIcon name="equity" color={activeTrack === "open_market" ? "#00C8FF" : markColor("equity")} />
              Equities
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTrack("competition");
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
                background: activeTrack === "competition" ? "rgba(0, 242, 157, 0.18)" : "transparent",
                color: activeTrack === "competition" ? "#00F29D" : "#94A3B8",
              }}
            >
              <GuideIcon name="competition" color={activeTrack === "competition" ? "#00F29D" : markColor("competition")} />
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
                color: selectedSymbol === "MUB" ? "#F4C460" : "#94A3B8",
              }}
            >
              <GuideIcon name="reserve" color={selectedSymbol === "MUB" ? "#F4C460" : markColor("reserve")} />
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
              background: "#121722",
              border: "1px solid rgba(255, 255, 255, 0.07)",
              fontSize: "11.5px",
              fontFamily: "var(--font-mono, monospace)",
              color: "#E2E8F0",
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

        {/* Emergency Kill-Switch & 1-Click Auto-Flatten Buttons */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "5px 10px",
              borderRadius: "8px",
              border: "1px solid rgba(0, 242, 157, 0.35)",
              background: "rgba(0, 242, 157, 0.08)",
            }}
          >
            <select
              aria-label="Active role selector"
              value={role}
              onChange={(e) => setRole(e.target.value as ClientRoleId)}
              style={{
                padding: "5px 8px",
                borderRadius: "6px",
                border: "1px solid rgba(255,255,255,0.14)",
                background: "#121722",
                color: "#F8FAFC",
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
          <button
            type="button"
            onClick={() => void handleAutoFlattenAll()}
            disabled={!profile.canExecuteTraderOrders}
            title={profile.canExecuteTraderOrders ? "Flatten paper positions through the control plane" : "This role cannot submit execution actions"}
            style={{
              padding: "6px 12px",
              borderRadius: "6px",
              border: "1px solid rgba(245, 158, 11, 0.45)",
              background: "rgba(245, 158, 11, 0.14)",
              color: "#FBBF24",
              fontWeight: 700,
              fontSize: "11.5px",
              cursor: profile.canExecuteTraderOrders ? "pointer" : "not-allowed",
              opacity: profile.canExecuteTraderOrders ? 1 : 0.45,
            }}
          >
            {profile.canExecuteTraderOrders ? "Flatten" : "Flatten locked"}
          </button>
          <button
            type="button"
            onClick={() => void handleToggleKillSwitch()}
            disabled={!profile.canTriggerKillSwitch}
            title={profile.canTriggerKillSwitch ? "Engage or reset the platform kill switch" : "Kill-switch is limited to prop_firm_admin"}
            style={{
              padding: "6px 12px",
              borderRadius: "6px",
              border: "1px solid rgba(255, 59, 105, 0.55)",
              background: killSwitchEngaged ? "#FF3B69" : "rgba(255, 59, 105, 0.18)",
              color: killSwitchEngaged ? "#070A0F" : "#FF3B69",
              fontWeight: 800,
              fontSize: "11.5px",
              cursor: profile.canTriggerKillSwitch ? "pointer" : "not-allowed",
              opacity: profile.canTriggerKillSwitch ? 1 : 0.45,
            }}
          >
            {!profile.canTriggerKillSwitch ? "Kill locked" : killSwitchEngaged ? "Reset kill" : "Kill"}
          </button>
        </div>
      </header>
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
            background: "#0B0F17",
            borderRight: "1px solid rgba(255, 255, 255, 0.08)",
            display: "flex",
            flexDirection: "column",
            padding: "12px",
            gap: "10px",
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
                marginBottom: "6px",
              }}
            >
              <span style={{ fontSize: "11px", fontWeight: 700, color: "#94A3B8", letterSpacing: "0.05em" }}>
                {catalogTotal == null
                  ? "Symbols"
                  : `Showing ${catalogListings.length.toLocaleString()} of ${catalogTotal.toLocaleString()}`}
              </span>
              <span
                style={{
                  fontSize: "10px",
                  fontFamily: "var(--font-mono, monospace)",
                  color: "#00F29D",
                }}
              >
                {searchLatencyMs == null ? "Catalog —" : `${searchLatencyMs.toFixed(1)} ms`}
              </span>
            </div>

            {/* Command Palette Search Input (Ctrl + K) */}
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: "8px", top: "9px", color: "#00C8FF" }}>
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
                  background: "#070A0F",
                  color: "#F8FAFC",
                  fontSize: "12px",
                }}
              />
            </div>
          </div>

          {/* Asset Class Filter Tabs: All, Equities, Crypto Perps, Futures */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "4px" }}>
            {(
              [
                { id: "all", label: "All", mark: "all" },
                { id: "equities", label: "Equities", mark: "equity" },
                { id: "crypto_perps", label: "Crypto", mark: "crypto" },
                { id: "futures", label: "Futures", mark: "futures" },
              ] as const satisfies ReadonlyArray<{ id: "all" | "equities" | "crypto_perps" | "futures"; label: string; mark: GuideIconName }>
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
                  padding: "5px 2px",
                  borderRadius: "5px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: on ? "#00C8FF" : "#121722",
                  color: on ? "#070A0F" : "#94A3B8",
                  fontSize: "10.5px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                <GuideIcon name={tab.mark} size={12} color={on ? "#070A0F" : markColor(tab.mark)} />
                {tab.label}
              </button>
              );
            })}
          </div>
          <AssetMarkLegend />

          <div style={{ fontSize: "10.5px", color: "#64748B", lineHeight: 1.4 }}>
            {universeCounts ? `Directory ${universeCounts.total_assets.toLocaleString()}. ` : ""}
            {catalogNotice}
            {" "}
            Prices on this page are public last prints when a feed answers. Yahoo stock and futures prints can be delayed. Unlisted names stay without a quote.
          </div>

          {/* Real-Time Ticker List */}
          <div
            ref={catalogListRef}
            onScroll={onCatalogScroll}
            style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1, minHeight: 0, overflowY: "auto" }}
          >
            {catalogListings.map((item) => {
              const isSelected = item.symbol === selectedSymbol;
              const mark = markForAsset(item.asset_class, item.exchange);
              return (
                <button
                  key={item.symbol}
                  type="button"
                  onClick={() => handleSelectSymbol(item.symbol)}
                  title={`${markLabel(mark)} · ${item.name} · ${item.exchange} · VPIN ${(item.vpin * 100).toFixed(1)}% · ${item.regime}`}
                  style={{
                    textAlign: "left",
                    padding: "6px 8px",
                    borderRadius: "6px",
                    border: isSelected ? "1px solid #00C8FF" : "1px solid transparent",
                    background: isSelected ? "rgba(0, 200, 255, 0.1)" : "transparent",
                    cursor: "pointer",
                    display: "grid",
                    gridTemplateColumns: "1fr auto auto",
                    gap: "8px",
                    alignItems: "center",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
                    <GuideIcon name={mark} color={markColor(mark)} />
                    <span style={{ minWidth: 0 }}>
                    <strong
                      style={{
                        display: "block",
                        fontSize: "12px",
                        color: "#F8FAFC",
                        fontFamily: "var(--font-mono, monospace)",
                      }}
                    >
                      {item.symbol}
                    </strong>
                    <span
                      style={{
                        display: "block",
                        fontSize: "10.5px",
                        color: "#94A3B8",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {item.name}
                    </span>
                    </span>
                  </span>
                  {item.exchange === "UNLISTED" ? (
                    <span style={{ gridColumn: "2 / span 2", fontSize: "11px", color: "#94A3B8" }}>Not listed</span>
                  ) : item.last_price <= 0 ? (
                    <span style={{ gridColumn: "2 / span 2", fontSize: "11px", color: "#94A3B8" }}>No quote</span>
                  ) : (
                    <>
                      <span
                        style={{
                          fontSize: "11px",
                          fontFamily: "var(--font-mono, monospace)",
                          color: item.change_pct >= 0 ? "#00F29D" : "#FF3B69",
                        }}
                      >
                        {item.change_pct >= 0 ? "+" : ""}
                        {item.change_pct.toFixed(2)}%
                      </span>
                      <span
                        style={{
                          fontSize: "12px",
                          fontWeight: 700,
                          fontFamily: "var(--font-mono, monospace)",
                          color: "#E2E8F0",
                        }}
                      >
                        {item.last_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </>
                  )}
                </button>
              );
            })}
            <div style={{ fontSize: "10.5px", color: "#94A3B8", padding: "8px 4px" }}>
              {catalogLoading
                ? "Loading the next page…"
                : catalogTotal != null && catalogListings.length >= catalogTotal
                  ? "End of this filter."
                  : "Scroll to load the rest."}
            </div>
          </div>
        </aside>
        ) : null}

        {/* ==================================================================
            3. CENTER PANEL: DEEP CHART & CANVAS + BOTTOM BLOTTER (55% WIDTH)
           ================================================================== */}
        <main
          style={{
            background: "#070A0F",
            display: "flex",
            flexDirection: "column",
            padding: "12px 16px",
            gap: "12px",
            overflowY: "auto",
          }}
        >
          {/* Instrument Telemetry & Timeframe Switcher Bar */}
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "8px",
              background: "#0B0F17",
              border: "1px solid rgba(255,255,255,0.08)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
              <div>
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
                          : "rgba(0, 242, 157, 0.16)",
                      color: activeAsset.track === "open_market" ? "#00C8FF" : "#00F29D",
                      fontWeight: 700,
                    }}
                  >
                    {activeAsset.asset_class.toUpperCase()} · {activeAsset.exchange === "UNLISTED" ? "Not listed" : activeAsset.exchange}
                  </span>
                </div>
                <div style={{ fontSize: "11.5px", color: "#94A3B8" }}>{activeAsset.name}</div>
              </div>

              <div
                title={`VPIN ${(activeAsset.vpin * 100).toFixed(1)}% · OFI ${activeAsset.ofi_z.toFixed(2)} · Kyle λ ${activeAsset.kyles_lambda.toFixed(4)}`}
                style={{ fontFamily: "var(--font-mono, monospace)", fontSize: "15px", color: activeAsset.last_price > 0 ? "#00F29D" : "#94A3B8", fontWeight: 700 }}
              >
                {activeAsset.last_price > 0
                  ? activeAsset.last_price.toLocaleString(undefined, { minimumFractionDigits: 2 })
                  : "No quote"}
              </div>
            </div>

            {/* Timeframe Switcher: 1s, 1m, 5m, 15m, 1h, 1D */}
            <div style={{ display: "flex", gap: "4px", flexWrap: "wrap", alignItems: "center" }}>
              {(["1s", "1m", "5m", "15m", "1h", "1D"] as const).map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTimeframe(tf)}
                  style={{
                    padding: "5px 9px",
                    borderRadius: "5px",
                    border: "1px solid rgba(255,255,255,0.1)",
                    background: timeframe === tf ? "#00F29D" : "#121722",
                    color: timeframe === tf ? "#070A0F" : "#94A3B8",
                    fontSize: "11px",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  {tf}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setNotesOpen((open) => !open)}
                style={{
                  padding: "5px 9px",
                  borderRadius: "5px",
                  border: "1px solid rgba(255,255,255,0.1)",
                  background: notesOpen ? "#1E293B" : "#121722",
                  color: "#94A3B8",
                  fontSize: "11px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {notesOpen ? "Hide notes" : "Notes"}
              </button>

            </div>
          </div>

          {/* High-Performance Candlestick + Volume Profile (POC/VAH/VAL) + Forecast Fan Canvas */}
          <div
            style={{
              background: "#0B0F17",
              borderRadius: "8px",
              border: "1px solid rgba(255,255,255,0.08)",
              padding: "10px",
            }}
          >
            {notesOpen ? (
              <div style={{ fontSize: "11px", color: "#64748B", marginBottom: "8px", lineHeight: 1.45 }}>
                <div>{modelGap ?? (chartRead ? `${chartRead.active.chart_source} · ${chartRead.active.feed_origin} · execution_permission ${chartRead.execution_permission}` : "Model is waiting to read this chart.")}</div>
                {chartRead ? (
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
                          border: "1px solid rgba(255,255,255,0.08)",
                          background: selectedSymbol === row.symbol ? "rgba(244, 196, 96, 0.16)" : "#121722",
                          color: "#E2E8F0",
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
            <div style={{ fontSize: "11px", color: "#64748B", lineHeight: 1.45, marginBottom: "8px" }}>
              <div>{gardenNote}</div>
              <div>{reserveNote}</div>
            </div>
            <DeskChart
              symbol={chartSymbol ?? activeAsset.symbol}
              timeframe={timeframe}
              frameClassName="desk-chart-frame"
              gap={modelGap}
              onOpenMinute={() => setTimeframe("1m")}
            >
              <WhaleOnChart
                symbol={selectedSymbol}
                bucketSeconds={TIMEFRAME_SECONDS[timeframe]}
                gap={modelGap}
              />
            </DeskChart>
          </div>

          {/* Collapsible Bottom Drawer: Active Positions Blotter, Working Orders & Audit History */}
          <div
            style={{
              background: "#0B0F17",
              borderRadius: "8px",
              border: "1px solid rgba(255,255,255,0.08)",
              padding: "10px 14px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: bottomDrawerOpen ? "10px" : "0",
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
                    background: bottomTab === "positions" ? "#1E293B" : "transparent",
                    color: bottomTab === "positions" ? "#00F29D" : "#94A3B8",
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
                    background: bottomTab === "orders" ? "#1E293B" : "transparent",
                    color: bottomTab === "orders" ? "#00C8FF" : "#94A3B8",
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
                    background: bottomTab === "audit" ? "#1E293B" : "transparent",
                    color: bottomTab === "audit" ? "#F8FAFC" : "#94A3B8",
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
                  color: "#94A3B8",
                  cursor: "pointer",
                  fontSize: "11.5px",
                }}
              >
                {bottomDrawerOpen ? "Collapse Drawer ▾" : "Expand Drawer ▴"}
              </button>
            </div>

            {bottomDrawerOpen && (
              <div style={{ maxHeight: "190px", overflowY: "auto" }}>
                {bottomTab === "positions" && (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11.5px" }}>
                    <thead>
                      <tr style={{ color: "#94A3B8", borderBottom: "1px solid rgba(255,255,255,0.08)", textAlign: "left" }}>
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
                      {positions.map((pos) => (
                        <tr key={pos.positionId} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                          <td style={{ padding: "6px", fontWeight: 700, fontFamily: "var(--font-mono, monospace)" }}>
                            {pos.symbol}
                          </td>
                          <td style={{ padding: "6px", color: pos.side === "LONG" ? "#00F29D" : "#FF3B69", fontWeight: 700 }}>
                            {pos.side}
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)" }}>
                            {pos.quantity} (${pos.notionalUsd.toLocaleString()})
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)" }}>
                            ${pos.entryPrice.toLocaleString()} / ${pos.markPrice.toLocaleString()}
                          </td>
                          <td style={{ padding: "6px", fontFamily: "var(--font-mono, monospace)", color: "#94A3B8" }}>
                            SL ${pos.stopLossPrice} · TP ${pos.takeProfitPrice}
                          </td>
                          <td
                            style={{
                              padding: "6px",
                              fontFamily: "var(--font-mono, monospace)",
                              color: pos.unrealizedPnlUsd >= 0 ? "#00F29D" : "#FF3B69",
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
                                  pos.status === "OPEN" ? "rgba(0,242,157,0.15)" : "rgba(255,59,105,0.15)",
                                color: pos.status === "OPEN" ? "#00F29D" : "#FF3B69",
                              }}
                            >
                              {pos.status}
                            </span>
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
                          background: "#121722",
                          border: "1px solid rgba(255,255,255,0.06)",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          fontSize: "11.5px",
                        }}
                      >
                        <div>
                          <strong style={{ fontFamily: "var(--font-mono, monospace)", color: "#F8FAFC" }}>
                            {ord.orderId} · {ord.side} {ord.symbol} (${ord.notionalUsd.toLocaleString()})
                          </strong>{" "}
                          <span style={{ color: "#94A3B8" }}>
                            via {ord.orderType} · Risk {ord.riskPct.toFixed(2)}% · SL ${ord.stopLossPrice} / TP $
                            {ord.takeProfitPrice}
                          </span>
                          <div style={{ fontSize: "10.5px", color: "#94A3B8", marginTop: "2px" }}>{ord.reason}</div>
                        </div>
                        <span
                          style={{
                            fontSize: "10px",
                            fontWeight: 700,
                            padding: "2px 7px",
                            borderRadius: "4px",
                            background:
                              ord.status === "REJECTED" ? "rgba(255,59,105,0.18)" : "rgba(0,242,157,0.16)",
                            color: ord.status === "REJECTED" ? "#FF3B69" : "#00F29D",
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
                      color: "#94A3B8",
                    }}
                  >
                    {auditLogs.map((log, i) => (
                      <div key={i} style={{ padding: "4px 6px", background: "#121722", borderRadius: "4px" }}>
                        {log}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </main>

        {/* ==================================================================
            4. RIGHT PANEL: ORDER DESK & REMAINING-ROOM HUD (25% WIDTH)
           ================================================================== */}
        <aside
          style={{
            background: "#0B0F17",
            borderLeft: "1px solid rgba(255, 255, 255, 0.08)",
            padding: "14px",
            display: "flex",
            flexDirection: "column",
            gap: "14px",
            overflowY: "auto",
          }}
        >
          {/* Prop Risk Remaining-Room Gauge */}
          <div
            style={{
              padding: "12px",
              borderRadius: "8px",
              background: "#121722",
              border: "1px solid rgba(0, 200, 255, 0.25)",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "11px", fontWeight: 800, color: "#00C8FF", letterSpacing: "0.04em" }}>
                Risk room
              </span>
              <span style={{ fontSize: "11.5px", fontFamily: "var(--font-mono, monospace)", fontWeight: 700 }}>
                Equity ${accountEquityUsd.toLocaleString()}
              </span>
            </div>

            {/* 1. 4.0% Daily Loss Breaker */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "#94A3B8" }}>{dailyLossLimitPct.toFixed(1)}% Daily Loss Breaker</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "#00F29D" }}>
                  ${sizingCalculation.dailyRoomUsd.toLocaleString()} cushion (
                  {(dailyLossLimitPct - dailyLossUsedPct).toFixed(2)}% left)
                </span>
              </div>
              <div style={{ height: "6px", background: "#070A0F", borderRadius: "4px", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(100, (sizingCalculation.postTradeDailyLossPct / dailyLossLimitPct) * 100)}%`,
                    height: "100%",
                    background:
                      sizingCalculation.postTradeDailyLossPct > dailyLossLimitPct ? "#FF3B69" : "#00F29D",
                  }}
                />
              </div>
            </div>

            {/* 2. 8.0% Max Trailing Drawdown Floor */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "#94A3B8" }}>{drawdownMeterLabel}</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "#00C8FF" }}>
                  ${sizingCalculation.trailingRoomUsd.toLocaleString()} cushion (
                  {(trailingDdFloorPct - trailingDdUsedPct).toFixed(2)}% left)
                </span>
              </div>
              <div style={{ height: "6px", background: "#070A0F", borderRadius: "4px", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(100, (sizingCalculation.postTradeTrailingDdPct / trailingDdFloorPct) * 100)}%`,
                    height: "100%",
                    background: "#00C8FF",
                  }}
                />
              </div>
            </div>

            {/* 3. 35% Single-Day Profit Consistency Gate */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "#94A3B8" }}>35% Single-Day Consistency Gate</span>
                <span style={{ fontFamily: "var(--font-mono, monospace)", color: "#E2E8F0" }}>
                  {singleDayConsistencyUsedPct.toFixed(1)}% / {singleDayConsistencyMaxPct.toFixed(1)}% PASS
                </span>
              </div>
              <div style={{ height: "6px", background: "#070A0F", borderRadius: "4px", overflow: "hidden" }}>
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
            style={{
              padding: "12px",
              borderRadius: "8px",
              background: "#121722",
              border: "1px solid rgba(255, 255, 255, 0.08)",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
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
                  color: "#00F29D",
                }}
              >
                Control Plane Gated
              </span>
            </div>

            {/* BUY / SELL Selector */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
              <button
                type="button"
                onClick={() => setOrderSide("BUY")}
                style={{
                  padding: "8px",
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 800,
                  fontSize: "12.5px",
                  background: orderSide === "BUY" ? "#00F29D" : "#070A0F",
                  color: orderSide === "BUY" ? "#070A0F" : "#94A3B8",
                }}
              >
                BUY / LONG {activeAsset.symbol}
              </button>
              <button
                type="button"
                onClick={() => setOrderSide("SELL")}
                style={{
                  padding: "8px",
                  borderRadius: "6px",
                  border: "none",
                  cursor: "pointer",
                  fontWeight: 800,
                  fontSize: "12.5px",
                  background: orderSide === "SELL" ? "#FF3B69" : "#070A0F",
                  color: orderSide === "SELL" ? "#070A0F" : "#94A3B8",
                }}
              >
                SELL / SHORT {activeAsset.symbol}
              </button>
            </div>

            {/* Execution Tactic Selector: Market / Limit / Almgren-Chriss TWAP */}
            <div>
              <label style={{ fontSize: "11px", color: "#94A3B8", display: "block", marginBottom: "4px" }}>
                Execution Tactic
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "4px" }}>
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
                      padding: "6px 4px",
                      borderRadius: "5px",
                      border: "1px solid rgba(255,255,255,0.08)",
                      background: executionTactic === tac.id ? "#00C8FF" : "#070A0F",
                      color: executionTactic === tac.id ? "#070A0F" : "#94A3B8",
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
                <span style={{ color: "#94A3B8" }}>Per-Trade Equity Risk (0.50%–{riskCapPct.toFixed(2)}% Cap)</span>
                <span
                  style={{
                    fontFamily: "var(--font-mono, monospace)",
                    fontWeight: 700,
                    color: equityRiskPct >= 0.5 && equityRiskPct <= riskCapPct ? "#00F29D" : "#FF3B69",
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
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
              <div>
                <label style={{ fontSize: "10.5px", color: "#94A3B8", display: "block", marginBottom: "3px" }}>
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
                    background: "#070A0F",
                    border: "1px solid rgba(255,255,255,0.12)",
                    color: "#F8FAFC",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "12px",
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: "10.5px", color: "#94A3B8", display: "block", marginBottom: "3px" }}>
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
                    background: "#070A0F",
                    border: "1px solid rgba(255,255,255,0.12)",
                    color: "#F8FAFC",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "12px",
                  }}
                />
              </div>
            </div>

            {/* Auto-Calculated Position Size & Bracket Summary */}
            <div
              style={{
                padding: "9px 10px",
                borderRadius: "6px",
                background: "#070A0F",
                border: "1px solid rgba(255,255,255,0.06)",
                fontFamily: "var(--font-mono, monospace)",
                fontSize: "11px",
                display: "flex",
                flexDirection: "column",
                gap: "4px",
              }}
            >
              {activeAsset.last_price <= 0 ? (
                <div style={{ color: "#94A3B8" }}>No quote is stored for this name. Size stays at zero. Nothing is sent.</div>
              ) : null}
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#94A3B8" }}>Auto-Sized Notional:</span>
                <strong style={{ color: "#F8FAFC" }}>${sizingCalculation.notionalUsd.toLocaleString()}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#94A3B8" }}>Auto-Sized Quantity:</span>
                <strong style={{ color: "#00C8FF" }}>
                  {sizingCalculation.quantity} {activeAsset.symbol}
                </strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#94A3B8" }}>ATR Stop-Loss Bracket:</span>
                <strong style={{ color: "#FF3B69" }}>${sizingCalculation.stopLossPrice}</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#94A3B8" }}>Take-Profit Bracket:</span>
                <strong style={{ color: "#00F29D" }}>${sizingCalculation.takeProfitPrice}</strong>
              </div>
            </div>

            {/* Submit Button to ActionableControlPlaneEngine */}
            <button
              type="button"
              onClick={() => void handleSubmitBracketOrder()}
              style={{
                width: "100%",
                padding: "10px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
                fontWeight: 800,
                fontSize: "12.5px",
                background: sizingCalculation.hardRiskBreach
                  ? "rgba(255, 59, 105, 0.25)"
                  : orderSide === "BUY"
                  ? "#00F29D"
                  : "#FF3B69",
                color: sizingCalculation.hardRiskBreach ? "#FF3B69" : "#070A0F",
              }}
            >
              {sizingCalculation.hardRiskBreach
                ? "⚠️ RISK GATE BLOCKED (CLICK TO INSPECT)"
                : `SUBMIT ${orderSide} BRACKET (${executionTactic})`}
            </button>

            {/* Real-Time Control Plane Feedback Banner */}
            <div
              style={{
                padding: "8px 10px",
                borderRadius: "6px",
                fontSize: "11px",
                fontFamily: "var(--font-mono, monospace)",
                background:
                  orderFeedback.status === "rejected"
                    ? "rgba(255, 59, 105, 0.12)"
                    : orderFeedback.status === "authorized"
                    ? "rgba(0, 242, 157, 0.12)"
                    : "#070A0F",
                border:
                  orderFeedback.status === "rejected"
                    ? "1px solid rgba(255, 59, 105, 0.4)"
                    : orderFeedback.status === "authorized"
                    ? "1px solid rgba(0, 242, 157, 0.4)"
                    : "1px solid rgba(255, 255, 255, 0.08)",
                color:
                  orderFeedback.status === "rejected"
                    ? "#FF3B69"
                    : orderFeedback.status === "authorized"
                    ? "#00F29D"
                    : "#94A3B8",
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

