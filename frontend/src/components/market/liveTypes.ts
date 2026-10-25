/** Shared live-market data types (the old LiveChartEngine component was removed in chart-2; AtlasChart is the one chart). */
export type LiveTickStreamFrame = {
  symbol: string;
  track?: "competition" | "open_market";
  provider?: "databento" | "polygon" | "ccxt_pro" | "coinbase";
  price: number;
  last_price?: number;
  size: number;
  vpin: number;
  ofi: number;
  spread: number;
  spread_bps?: number;
  bid_depth: number[];
  ask_depth: number[];
  bid_depth_top5?: Array<{ level: number; price: number; size: number }>;
  ask_depth_top5?: Array<{ level: number; price: number; size: number }>;
  latency_ms: number;
  regime?: string;
  timestamp?: string;
  exchange_timestamp?: string;
  system_receipt_timestamp?: string;
  execution_permission?: "none";
};

export type LiveCandlePoint = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type AiHorizonPredictionPoint = {
  horizon: string;
  expectedReturnBps: number;
  p10Price: number;
  p50Price: number;
  p90Price: number;
};

export type LockedWhaleOpportunityData = {
  opportunityLocked: boolean;
  scenarioId: "WSDM-01" | "WSDM-02" | "WSDM-03" | "WSDM-04" | "WSDM-05";
  scenarioName: string;
  action: "BUY" | "SELL";
  conviction: number;
  entryPrice: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  stopDistanceBps: number;
  expectedMoveBps: number;
  riskRewardRatio: number;
  executionTactic: "ALMGREN_CHRISS" | "LIMIT" | "TWAP";
  triggerSummary: string;
  propGuardrailNote: string;
};

export type TradingFactorAttributionPoint = {
  factorCode: string;
  factorName: string;
  category: string;
  rawValue: number;
  normalizedZscore: number;
  importanceWeight: number;
  signalContributionBps: number;
  interpretation: string;
};

export type BracketIntent = {
  stopLossPrice: number;
  takeProfitPrice: number;
  riskUsd: number;
};


import type { ModelRead } from "./ModelFlowPanel";
/** A candle from /api/market/live-view (ISO timestamp). */
export type LiveBar = { timestamp: string; open: number; high: number; low: number; close: number };
export type LiveTape = { candles?: LiveBar[]; chart_source?: string; feed_origin?: string; notice?: string; feed_health?: { connection?: string; trade_age_seconds?: number; delay_status?: string } };
export type LiveSnapshot = ModelRead & LiveTape & { symbol: string; status: string; bucket_seconds: number; refresh_seconds: number };
