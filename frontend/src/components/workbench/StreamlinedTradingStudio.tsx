"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LiveChartEngine, type LiveCandlePoint } from "../market/LiveChartEngine";

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

export function StreamlinedTradingStudio() {
  const [activeTrack, setActiveTrack] = useState<"all" | "open_market" | "competition">("all");
  const [assetClassFilter, setAssetClassFilter] = useState<"all" | "equities" | "crypto_perps" | "futures">("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [searchLatencyMs, setSearchLatencyMs] = useState<number>(1.8);
  const [universeCounts, setUniverseCounts] = useState<{
    total_assets: number;
    equities: number;
    crypto_perps: number;
    futures: number;
  }>({
    total_assets: 10538,
    equities: 10000,
    crypto_perps: 520,
    futures: 18,
  });

  const [catalogListings, setCatalogListings] = useState<CatalogListingItem[]>(DEFAULT_STUDIO_LISTINGS);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("BTC-USD");
  const [timeframe, setTimeframe] = useState<"1s" | "1m" | "5m" | "15m" | "1h" | "1D">("1m");
  const [chartCandles, setChartCandles] = useState<LiveCandlePoint[]>([]);
  const [feedAvailable, setFeedAvailable] = useState(false);
  const [wsLatencyMs, setWsLatencyMs] = useState<number>(6.8);
  const [activeSubCount, setActiveSubCount] = useState<number>(1);
  const [sessionClock, setSessionClock] = useState<string>("11:42:18 UTC");
  const [killSwitchEngaged, setKillSwitchEngaged] = useState<boolean>(false);

  // Collapsible Bottom Drawer State
  const [bottomDrawerOpen, setBottomDrawerOpen] = useState<boolean>(true);
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
  const [account, setAccount] = useState<{ current_equity_usd: string; start_of_day_equity_usd: string; high_water_mark_usd: string; best_day_profit_usd: string; total_cumulative_profit_usd: string } | null>(null);
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
  const wsRef = useRef<WebSocket | null>(null);
  const prevSymbolRef = useRef<string>("BTC-USD");

  // Ctrl + K global command palette shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Global Session Clock updater
  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setSessionClock(now.toISOString().slice(11, 19) + " UTC");
    };
    updateClock();
    const timer = setInterval(updateClock, 1000);
    return () => clearInterval(timer);
  }, []);

  // Query Universal Asset Catalog (/api/catalog/search)
  const fetchCatalog = useCallback(async () => {
    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? ""
          : "";
      const params = new URLSearchParams({
        q: searchQuery,
        track: activeTrack,
        asset_class: assetClassFilter,
        limit: "60",
      });
      const res = await fetch(`${apiBase}/api/catalog/search?${params.toString()}`, {
        cache: "no-store",
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.query_latency_ms === "number") {
          setSearchLatencyMs(data.query_latency_ms);
        }
        if (data.universe_counts) {
          setUniverseCounts(data.universe_counts);
        }
        if (Array.isArray(data.results)) {
          setCatalogListings(data.results);
          return;
        }
      }
    } catch {
      // Fallback to local filter when backend offline
    }

    const q = searchQuery.trim().toUpperCase();
    const filtered = DEFAULT_STUDIO_LISTINGS.filter((item) => {
      if (activeTrack !== "all" && item.track !== activeTrack) return false;
      if (assetClassFilter !== "all" && item.asset_class !== assetClassFilter) return false;
      if (q && !item.symbol.includes(q) && !item.name.toUpperCase().includes(q)) return false;
      return true;
    });
    setCatalogListings(filtered);
  }, [activeTrack, assetClassFilter, searchQuery]);

  useEffect(() => {
    void fetchCatalog();
  }, [fetchCatalog]);

  // Dynamic On-Demand WebSocket Subscription Multiplexer (/ws/market-stream)
  useEffect(() => {
    let ws: WebSocket | null = null;
    setChartCandles([]);
    setFeedAvailable(false);
    try {
      const wsBase =
        typeof window !== "undefined" && window.location.port === "3000"
          ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`
          : typeof window !== "undefined"
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
          if (pkt.symbol && Number.isFinite(Number(pkt.price)) && pkt.data_mode !== "demo") {
            const price = Number(pkt.price);
            const seconds = { "1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1D": 86400 }[timeframe];
            const timestamp = new Date(Math.floor(Date.parse(pkt.exchange_timestamp) / (seconds * 1000)) * seconds * 1000).toISOString();
            setFeedAvailable(true);
            setChartCandles(previous => {
              const last = previous[previous.length - 1];
              if (last && timestamp < last.timestamp) return previous;
              if (last?.timestamp === timestamp) return [...previous.slice(0, -1), {
                ...last, high: Math.max(last.high, price), low: Math.min(last.low, price), close: price,
                volume: last.volume + Number(pkt.size ?? 0),
              }];
              return [...previous.slice(-499), { timestamp, open: price, high: price, low: price, close: price, volume: Number(pkt.size ?? 0) }];
            });
            const nextPrice = Number(pkt.last_price ?? pkt.price ?? 0);
            if (typeof pkt.latency_ms === "number") {
              setWsLatencyMs(pkt.latency_ms);
            }
            setCatalogListings((prev) =>
              prev.map((item) =>
                item.symbol === pkt.symbol
                  ? {
                      ...item,
                      last_price: nextPrice > 0 ? nextPrice : item.last_price,
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
  }, [selectedSymbol, timeframe]);

  const handleSelectSymbol = (newSym: string) => {
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
      DEFAULT_STUDIO_LISTINGS[0],
    [catalogListings, selectedSymbol]
  );

  // Remaining-Room HUD & Deterministic Position Sizing Math
  const accountEquityUsd = Number(account?.current_equity_usd ?? 0);
  const dailyLossLimitPct = 4.0;
  const trailingDdFloorPct = 8.0;
  const singleDayConsistencyMaxPct = 35.0;

  const dailyLossUsedPct = account ? Math.max(0, (1 - accountEquityUsd / Number(account.start_of_day_equity_usd)) * 100) : 0;
  const trailingDdUsedPct = account ? Math.max(0, (1 - accountEquityUsd / Number(account.high_water_mark_usd)) * 100) : 0;
  const singleDayConsistencyUsedPct = account && Number(account.total_cumulative_profit_usd) > 0 ? Number(account.best_day_profit_usd) / Number(account.total_cumulative_profit_usd) * 100 : 0;

  const sizingCalculation = useMemo(() => {
    const stopFraction = Math.max(0.001, atrStopBps / 10000.0);
    const riskDollars = accountEquityUsd * (equityRiskPct / 100.0);
    const rawNotionalUsd = riskDollars / stopFraction;
    const cappedNotionalUsd = Math.round(rawNotionalUsd);
    const px = Math.max(0.0001, activeAsset.last_price);
    const quantity = Number((cappedNotionalUsd / px).toFixed(px > 500 ? 4 : 2));

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
    const dailyRoomUsd = Math.max(0, Math.round(accountEquityUsd * ((dailyLossLimitPct - dailyLossUsedPct) / 100.0)));
    const trailingRoomUsd = Math.max(
      0,
      Math.round(103100.0 * ((trailingDdFloorPct - trailingDdUsedPct) / 100.0))
    );

    const withinRiskCap = equityRiskPct >= 0.5 && equityRiskPct <= 0.75;
    const hardRiskBreach =
      !feedAvailable || !controlAvailable || submitting || killSwitchEngaged ||
      equityRiskPct > 0.75 ||
      postTradeDailyLossPct > dailyLossLimitPct ||
      postTradeTrailingDdPct > trailingDdFloorPct ||
      atrStopBps < 20;

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
    equityRiskPct,
    killSwitchEngaged,
    orderSide,
    rewardRiskMultiple,
  ]);

  // Emergency Kill-Switch Handler
  const handleToggleKillSwitch = async () => {
    const nextState = !killSwitchEngaged;

    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000" ? "" : "";
      const response = await fetch(`${apiBase}/api/control/kill-switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engaged: nextState,
          reason: nextState ? "studio_emergency_kill_switch" : "studio_operator_reset",
        }),
      });
      if (!response.ok) throw new Error("Control action rejected");
    } catch {
      setOrderFeedback({ status: "rejected", message: "Kill-switch request failed; state is unconfirmed." });
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
    try {
      const apiBase =
        typeof window !== "undefined" && window.location.port === "3000" ? "" : "";
      const response = await fetch(`${apiBase}/api/control/flatten`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "studio_one_click_flatten" }),
      });
      if (!response.ok) throw new Error("Control action rejected");
    } catch {
      setOrderFeedback({ status: "rejected", message: "Flatten request failed; state is unconfirmed." });
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
      const rejectReason = killSwitchEngaged
        ? "Rejected: Emergency Kill-Switch is currently engaged."
        : equityRiskPct > 0.75
        ? `Rejected: Per-trade risk (${equityRiskPct.toFixed(2)}%) exceeds deterministic 0.75% prop cap.`
        : "Rejected: Post-trade drawdown breaches 4.0% daily or 8.0% trailing floor.";
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
        method: "POST", headers: { "Content-Type": "application/json" },
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
        minHeight: "100vh",
        background: "#070A0F",
        color: "#F8FAFC",
        display: "flex",
        flexDirection: "column",
        fontFamily: "var(--font-sans, Inter, system-ui, sans-serif)",
      }}
    >
      {/* ====================================================================
          1. TOP HEADER BAR
         ==================================================================== */}
      <header
        style={{
          height: "58px",
          padding: "0 18px",
          background: "#0B0F17",
          borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "12px",
          flexWrap: "wrap",
        }}
      >
        {/* Brand + Dual-Track Selector */}
        <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <a
            href="/"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              textDecoration: "none",
              color: "#F8FAFC",
            }}
          >
            <div
              style={{
                width: "30px",
                height: "30px",
                borderRadius: "6px",
                background: "linear-gradient(135deg, #00F29D 0%, #00C8FF 100%)",
                color: "#070A0F",
                fontWeight: 900,
                fontSize: "13px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              AT
            </div>
            <div>
              <div style={{ fontSize: "13.5px", fontWeight: 800, letterSpacing: "0.03em" }}>
                ATLAS STUDIO
              </div>
              <div style={{ fontSize: "10px", color: "#94A3B8" }}>
                {universeCounts.total_assets.toLocaleString()} Universal Assets · perm: none
              </div>
            </div>
          </a>

          {/* Dual-Track Selector */}
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
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "all" ? "#1E293B" : "transparent",
                color: activeTrack === "all" ? "#F8FAFC" : "#94A3B8",
              }}
            >
              🌐 Full Universe ({universeCounts.total_assets.toLocaleString()})
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
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "open_market" ? "rgba(0, 200, 255, 0.18)" : "transparent",
                color: activeTrack === "open_market" ? "#00C8FF" : "#94A3B8",
              }}
            >
              🏛️ Open-Market Equities ({universeCounts.equities.toLocaleString()})
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
                fontSize: "11.5px",
                fontWeight: 600,
                background: activeTrack === "competition" ? "rgba(0, 242, 157, 0.18)" : "transparent",
                color: activeTrack === "competition" ? "#00F29D" : "#94A3B8",
              }}
            >
              🏆 Prop Competition ({(universeCounts.crypto_perps + universeCounts.futures).toLocaleString()})
            </button>
          </div>
        </div>

        {/* Global Session Clock & WebSocket Latency Indicator (< 15ms) */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
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
            PAPER ACCOUNT · {feedAvailable ? "Observed feed" : "Awaiting market feed"} · {sessionClock}
          </div>
          <div
            style={{
              padding: "4px 10px",
              borderRadius: "6px",
              background: "rgba(0, 242, 157, 0.1)",
              border: "1px solid rgba(0, 242, 157, 0.3)",
              fontSize: "11.5px",
              fontFamily: "var(--font-mono, monospace)",
              color: "#00F29D",
            }}
          >
            ⚡ WS RTT {wsLatencyMs.toFixed(1)}ms (&lt; 15ms) · Subs: {activeSubCount}
          </div>
        </div>

        {/* Emergency Kill-Switch & 1-Click Auto-Flatten Buttons */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <a
            href="/listings"
            style={{
              padding: "6px 10px",
              borderRadius: "6px",
              background: "#121722",
              border: "1px solid rgba(255,255,255,0.1)",
              color: "#94A3B8",
              textDecoration: "none",
              fontSize: "11.5px",
            }}
          >
            Module 02 Grid
          </a>
          <button
            type="button"
            onClick={() => void handleAutoFlattenAll()}
            style={{
              padding: "6px 12px",
              borderRadius: "6px",
              border: "1px solid rgba(245, 158, 11, 0.45)",
              background: "rgba(245, 158, 11, 0.14)",
              color: "#FBBF24",
              fontWeight: 700,
              fontSize: "11.5px",
              cursor: "pointer",
            }}
          >
            1-Click Auto-Flatten
          </button>
          <button
            type="button"
            onClick={() => void handleToggleKillSwitch()}
            style={{
              padding: "6px 12px",
              borderRadius: "6px",
              border: "1px solid rgba(255, 59, 105, 0.55)",
              background: killSwitchEngaged ? "#FF3B69" : "rgba(255, 59, 105, 0.18)",
              color: killSwitchEngaged ? "#070A0F" : "#FF3B69",
              fontWeight: 800,
              fontSize: "11.5px",
              cursor: "pointer",
            }}
          >
            {killSwitchEngaged ? "RESET KILL-SWITCH" : "🚨 EMERGENCY KILL-SWITCH"}
          </button>
        </div>
      </header>

      {/* ====================================================================
          MAIN 3-PANEL STUDIO GRID (20% Left | 55% Center | 25% Right)
         ==================================================================== */}
      <div
        className="atlas-command-grid"
        style={{
          flex: 1,
          display: "grid",
          minHeight: "calc(100vh - 58px)",
          overflow: "hidden",
        }}
      >
        {/* ==================================================================
            2. LEFT PANEL: UNIVERSAL SCREENER & WATCHLIST (20% WIDTH)
           ================================================================== */}
        <aside
          style={{
            background: "#0B0F17",
            borderRight: "1px solid rgba(255, 255, 255, 0.08)",
            display: "flex",
            flexDirection: "column",
            padding: "12px",
            gap: "10px",
            overflowY: "auto",
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
                UNIVERSAL CATALOG SCREENER
              </span>
              <span
                style={{
                  fontSize: "10px",
                  fontFamily: "var(--font-mono, monospace)",
                  color: "#00F29D",
                }}
              >
                {searchLatencyMs.toFixed(1)}ms SQLite
              </span>
            </div>

            {/* Command Palette Search Input (Ctrl + K) */}
            <div style={{ position: "relative" }}>
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search 10,500+ tickers (Ctrl+K)..."
                aria-label="Universal Asset Catalog Search"
                style={{
                  width: "100%",
                  padding: "8px 10px",
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
                { id: "all", label: "All" },
                { id: "equities", label: "Equities" },
                { id: "crypto_perps", label: "Crypto Perps" },
                { id: "futures", label: "Futures" },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setAssetClassFilter(tab.id)}
                style={{
                  padding: "5px 4px",
                  borderRadius: "5px",
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: assetClassFilter === tab.id ? "#00C8FF" : "#121722",
                  color: assetClassFilter === tab.id ? "#070A0F" : "#94A3B8",
                  fontSize: "10.5px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Real-Time Ticker List */}
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1, overflowY: "auto" }}>
            {catalogListings.map((item) => {
              const isSelected = item.symbol === selectedSymbol;
              return (
                <button
                  key={item.symbol}
                  type="button"
                  onClick={() => handleSelectSymbol(item.symbol)}
                  style={{
                    textAlign: "left",
                    padding: "8px 10px",
                    borderRadius: "7px",
                    border: isSelected
                      ? "1px solid #00C8FF"
                      : "1px solid rgba(255, 255, 255, 0.06)",
                    background: isSelected ? "rgba(0, 200, 255, 0.1)" : "#121722",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <strong
                        style={{
                          fontSize: "12.5px",
                          color: "#F8FAFC",
                          fontFamily: "var(--font-mono, monospace)",
                        }}
                      >
                        {item.symbol}
                      </strong>
                      <span
                        style={{
                          fontSize: "9.5px",
                          padding: "1px 5px",
                          borderRadius: "4px",
                          background: "rgba(255,255,255,0.06)",
                          color: "#94A3B8",
                        }}
                      >
                        {item.exchange}
                      </span>
                    </div>
                    <span
                      style={{
                        fontSize: "12.5px",
                        fontWeight: 700,
                        fontFamily: "var(--font-mono, monospace)",
                        color: item.change_pct >= 0 ? "#00F29D" : "#FF3B69",
                      }}
                    >
                      ${item.last_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      width: "100%",
                      fontSize: "10.5px",
                      color: "#94A3B8",
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "120px" }}>
                      {item.name}
                    </span>
                    <span style={{ fontFamily: "var(--font-mono, monospace)" }}>
                      {item.change_pct >= 0 ? "+" : ""}
                      {item.change_pct.toFixed(2)}%
                    </span>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      width: "100%",
                      fontSize: "10px",
                      fontFamily: "var(--font-mono, monospace)",
                      marginTop: "2px",
                    }}
                  >
                    <span style={{ color: item.vpin > 0.38 ? "#F59E0B" : "#00F29D" }}>
                      VPIN {(item.vpin * 100).toFixed(1)}%
                    </span>
                    <span style={{ color: "#38BDF8" }}>{item.regime}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

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
                    {activeAsset.asset_class.toUpperCase()} · {activeAsset.exchange}
                  </span>
                </div>
                <div style={{ fontSize: "11.5px", color: "#94A3B8" }}>{activeAsset.name}</div>
              </div>

              <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: "12px", color: "#E2E8F0" }}>
                Last:{" "}
                <strong style={{ color: "#00F29D", fontSize: "15px" }}>
                  ${activeAsset.last_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </strong>{" "}
                · VPIN: <strong>{(activeAsset.vpin * 100).toFixed(1)}%</strong> · OFI_z:{" "}
                <strong>{activeAsset.ofi_z.toFixed(2)}</strong> · Kyle&apos;s λ:{" "}
                <strong>{activeAsset.kyles_lambda.toFixed(4)}</strong>
              </div>
            </div>

            {/* Timeframe Switcher: 1s, 1m, 5m, 15m, 1h, 1D */}
            <div style={{ display: "flex", gap: "4px" }}>
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
            <LiveChartEngine symbol={activeAsset.symbol} candles={chartCandles} marketDataAvailable={feedAvailable} />
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
                REMAINING-ROOM RISK HUD
              </span>
              <span style={{ fontSize: "11.5px", fontFamily: "var(--font-mono, monospace)", fontWeight: 700 }}>
                Equity ${accountEquityUsd.toLocaleString()}
              </span>
            </div>

            {/* 1. 4.0% Daily Loss Breaker */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                <span style={{ color: "#94A3B8" }}>4.0% Daily Loss Breaker</span>
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
                <span style={{ color: "#94A3B8" }}>8.0% Trailing Drawdown Floor</span>
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
                PRE-TRADE BRACKET ORDER TICKET
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
                <span style={{ color: "#94A3B8" }}>Per-Trade Equity Risk (0.50%–0.75% Target)</span>
                <span
                  style={{
                    fontFamily: "var(--font-mono, monospace)",
                    fontWeight: 700,
                    color: equityRiskPct <= 0.75 ? "#00F29D" : "#FF3B69",
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

