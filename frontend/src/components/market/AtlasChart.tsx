"use client";
/** ATLAS chart: the one primary chart on every surface. Real feed bars (free providers only) drawn with
 *  TradingView Lightweight Charts (Apache-2.0), plus every ATLAS research layer from ONE read-only endpoint,
 *  /api/ai/chart/overlays. Each layer reports its own status; nothing is drawn that ATLAS did not compute.
 *  Paper only. ML execution_permission is "none": markers and probabilities are research, never orders. */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNowcast, ageText, NOWCAST_LABEL } from "./nowcast";
import { NowcastOnly, nowcastBannerText } from "./NowcastOnly";
import { HorizonChips } from "./HorizonChips";
import { createChart, type CandlestickData, type IChartApi, type ISeriesApi, type UTCTimestamp, type WhitespaceData, LineStyle } from "lightweight-charts";
import type { LiveSnapshot } from "./liveTypes";
import { deskTimeOptions } from "./lwTime";
import { MARKER_CLASSES, altToCandles, type OppMarker } from "./opportunityMarkers";
import { orderedChartPoints } from "./chartSeries";
import { useFeedQuotes } from "../../lib/feedQuotes";
import { NavLink } from "../../nav/NavLink";

export const CHART_INTERVALS = ["live", "1m", "5m", "15m", "1h", "4h", "1d"] as const;
export type ChartInterval = (typeof CHART_INTERVALS)[number];
export const CHART_BAR_TYPES = [
  { id: "time", label: "Time" }, { id: "heikin_ashi", label: "Heikin-Ashi" }, { id: "renko_atr", label: "Renko" },
  { id: "range_atr", label: "Range" }, { id: "volume", label: "Volume" }, { id: "dollar", label: "Dollar" },
  { id: "tick", label: "Tick" }, { id: "kagi_atr", label: "Kagi" }, { id: "pnf_atr", label: "Point & Figure" },
] as const;
const LAYERS = [
  { id: "ml_markers", label: "ML buy/sell" }, { id: "ml_probability", label: "ML probability" },
  { id: "setups", label: "Setups" }, { id: "zones", label: "Zones" }, { id: "vwap", label: "Session VWAP" }, { id: "anchored_vwap", label: "Anchored VWAP" },
  { id: "sessions", label: "Sessions" },
  { id: "volume_profile", label: "Volume profile" }, { id: "regimes", label: "Regime" },
  { id: "conviction", label: "Conviction" }, { id: "predictions", label: "Predictions" },
  { id: "marker_details", label: "Marker details" }, { id: "trade_lines", label: "Trade lines" },
  { id: "prediction_zone", label: "Prediction zone" }, { id: "outcomes", label: "Outcomes" },
  // evo-14: ten server-side layers, all OFF by default. Each reports its own status and reason; their numbers are also model training features.
  { id: "conformal_bands", label: "Conformal bands" }, { id: "mtf_confluence", label: "Multi-timeframe confluence" },
  { id: "events", label: "Economic events" }, { id: "market_clock", label: "Market clock" },
  { id: "cross_corr", label: "Cross-asset correlation" }, { id: "vol_cone", label: "Volatility cone" },
  { id: "liquidity", label: "Liquidity & spread cost" }, { id: "model_disagreement", label: "Model disagreement" },
  { id: "account_size", label: "Account-aware size" }, { id: "drift_alert", label: "Drift alert" },
  // Layer 26: official filings and unverified headlines for this ticker, each linked to its source. Context only; OFF by default.
  { id: "news", label: "News & filings" },
  // evo-15 layers 27-33. 27-32 are model training features too (same code path); 33 (FRED yield curve and credit spreads) is DISPLAY ONLY, never a feature.
  { id: "breadth", label: "Market breadth" }, { id: "overnight_intraday", label: "Overnight vs intraday" }, { id: "gap_stats", label: "Gap statistics" },
  { id: "seasonality", label: "Seasonality" }, { id: "implied_vol", label: "Implied volatility (VIX)" }, { id: "usd_proxy", label: "US-dollar proxy" },
  { id: "macro_risk", label: "Yield curve & credit (FRED)" },
] as const;
/** Every layer is ON by default (26 -> 33). The Layers popover groups them by what they describe. */
const LAYER_GROUPS: { title: string; ids: readonly LayerIdName[] }[] = [
  { title: "Model", ids: ["ml_markers", "ml_probability", "predictions", "prediction_zone", "outcomes", "trade_lines", "marker_details", "conviction", "model_disagreement"] },
  { title: "Price structure", ids: ["setups", "zones", "vwap", "anchored_vwap", "sessions", "volume_profile", "regimes"] },
  { title: "Risk & volatility", ids: ["conformal_bands", "vol_cone", "drift_alert", "liquidity", "account_size"] },
  { title: "Trend & context", ids: ["mtf_confluence", "cross_corr", "breadth", "usd_proxy", "implied_vol", "macro_risk"] },
  { title: "Calendar & flow", ids: ["events", "market_clock", "seasonality", "overnight_intraday", "gap_stats"] },
  { title: "News", ids: ["news"] },
];
const NEW_LAYER_IDS = ["conformal_bands", "mtf_confluence", "events", "market_clock", "cross_corr", "vol_cone", "liquidity", "model_disagreement", "account_size", "drift_alert", "news",
  "breadth", "overnight_intraday", "gap_stats", "seasonality", "implied_vol", "usd_proxy", "macro_risk"] as const;
type NewLayerId = (typeof NEW_LAYER_IDS)[number];
type LayerId = (typeof LAYERS)[number]["id"];
type LayerIdName = LayerId;
const DUR: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 };
const ZONE_COLORS: Record<string, string> = { sr: "#56B4E9", fourbox: "#CC79A7", orb: "#E69F00", prior_day: "#98A3B3" };
const REGIME_COLORS: Record<string, string> = { up: "rgba(46,184,138,0.10)", down: "rgba(240,128,60,0.10)", range: "rgba(152,163,179,0.06)" };

export type ModelPrediction = Status & {
  gate_status: "gate_passed" | "research_below_gate" | "no_model"; label: string; symbol?: string; interval?: string; execution_permission?: string;
  direction?: "up" | "down" | "neutral"; probability?: number; p_long?: number; p_short?: number; ev_r?: number; setup?: string; conformal_take?: boolean;
  as_of_bar?: number; as_of_end?: number; as_of_toronto?: string; computed_at?: number; computed_at_toronto?: string; meaning?: string;
  model?: { id?: string; version?: string; group?: string; calibrator?: string; created_at?: string; gates_failed?: string[]; gates_total?: number; uses_vwap?: boolean;
    metrics?: Record<string, number | null> };
};
export type DirectionalPrediction = Status & {
  label: string; kind?: string; direction?: "up" | "down" | "neutral"; probability?: number; conformal_set?: number[]; conformal_alpha?: number; take?: boolean;
  horizon_bars?: number; band?: { p10?: number; p50?: number; p90?: number }; as_of_end?: number; execution_permission?: string; meaning?: string;
  gates?: { gate: string; passed: boolean }[]; metrics?: { n_oos?: number | null; brier?: number | null; brier_baseline?: number | null; auc?: number | null };
};
export type NewLayer = Status & { meaning?: string; features?: Record<string, number | null>; [k: string]: unknown };
export type ConformalBands = NewLayer & { alpha?: number; horizon_bars?: number; forward?: { upper: number; lower: number; as_of_end: number }; points?: { time: number; upper: number; lower: number }[]; realised_coverage_64?: number | null };
export type NewsItem = { time: number; source: string; tier: number; tier_label: string; url: string; title?: string; event_type?: string | null;
  sentiment?: number | null; materiality?: number | null; grounded?: boolean; hype_flags?: string[]; kind?: string; analyzer?: string | null };
export type NewsLayer = NewLayer & { items?: NewsItem[]; coverage?: unknown; llm?: { enabled?: boolean; reason?: string }; reviewer_mode?: string };
export type RunningCal = { status: string; n: number; mean_p?: number | null; hit_rate?: number | null; brier?: number | null; brier_base_rate?: number | null; taken_hit_rate?: number | null };
type Bar = { time: number; open: number; high: number; low: number; close: number; volume: number };
type Status = { status: string; reason?: string; note?: string };
export type Overlays = {
  status: string; reason?: string; cause?: string; symbol: string; interval: string; bar_type: string; execution_permission: string;
  provider: { provider: string | null; providers: string[]; realtime: boolean | null; delay_s?: number | null; delay_label: string; delay_note?: string | null; built: string };
  market_session?: {
    symbol: string; venue_id: string; venue_name: string; status: string; status_label: string;
    is_open: boolean; countdown: string; schedule_summary: string; reason: string;
  };
  bars: Bar[];
  display?: Status & { kind: string; bars?: { time: number; start: number; open: number; high: number; low: number; close: number }[] };
  layers: {
    ml_markers?: Status & { items: OppMarker[] }; setups?: Status & { items: OppMarker[]; classes?: Record<string, { count: number; note: string }> };
    ml_probability?: Status & { points: { time: number; value: number; take: boolean }[] };
    zones?: Status & { items: { kind: string; label: string; low: number; high: number; from: number }[]; notes?: string[] };
    vwap?: Status & { points: { time: number; value: number; session?: number | null }[]; reset?: string; session_kind?: string;
      anchored?: Status & { points?: { time: number; value: number }[]; anchor?: { time: number; kind: string; price: number; confirmed_at: number }; method?: string };
      sessions?: Status & { spans: { key: number; from: number; to: number; shade: number }[]; kind: string; label: string } };
    model_prediction?: ModelPrediction;
    directional_prediction?: DirectionalPrediction;
    conformal_bands?: ConformalBands;
    mtf_confluence?: NewLayer; events?: NewLayer; market_clock?: NewLayer; cross_corr?: NewLayer; vol_cone?: NewLayer;
    liquidity?: NewLayer; model_disagreement?: NewLayer; account_size?: NewLayer; drift_alert?: NewLayer; news?: NewsLayer;
    breadth?: NewLayer; overnight_intraday?: NewLayer; gap_stats?: NewLayer; seasonality?: NewLayer; implied_vol?: NewLayer; usd_proxy?: NewLayer; macro_risk?: NewLayer;
    anchored_vwap?: Status; sessions?: Status;
    volume_profile?: Status & { bins: { low: number; high: number; volume: number }[]; poc: number; window_bars: number };
    regimes?: Status & { spans: { from: number; to: number; trend: string; label: string }[]; current: string | null };
    conviction?: Status & { score?: number; label?: string; components?: { rule: string; points: number; why: string }[]; personas?: string };
    predictions?: Status & { items: { time: number; p: number; take: boolean; outcome: string; calibrator: string; hit?: boolean | null; id?: string }[];
      calibration: { brier: number; brier_baseline: number; brier_skill?: number; ece: number; auc: number; ev_r_per_opportunity?: number; take_all_ev?: number; mean_r_taken?: number; stability?: number; fitness?: number } | null; running_calibration?: RunningCal };
    marker_details?: Status & { n: number; fields: string[] };
    forward?: Status & { label: string; as_of_bar?: number; as_of_close?: number; horizon_bars?: number; horizon_end?: number; atr?: number;
      band?: { p10: number; p25: number; p50: number; p75: number; p90: number }; n_samples?: number; method?: string;
      active_candidates?: { id: string; setup: string; direction: string; class: string; p_win: number | null; ev_r?: number | null; calibrated: boolean; threshold: number | null }[];
      no_active_candidate?: string | null };
  };
  ml_panel: null | {
    execution_permission: string;
    can_buy?: boolean;
    can_sell?: boolean;
    research_hand?: null | {
      genome_id?: string | null;
      stance?: string;
      stance_reason?: string | null;
      can_buy?: boolean;
      can_sell?: boolean;
      strict_gate_passed?: boolean;
      research_champion?: boolean;
    };
    evolution: null | { run_id: string; created_at: number; decision: string; no_model_beats_baseline: boolean; challenger: string;
      metrics: Record<string, number | boolean | null>;
      symbol_live_metrics?: Record<string, number | boolean | null> | null };
    champion: null | Record<string, unknown>;
    current_model: null | { version: string; status: string; calibrator: string; brier: number; brier_baseline: number; auc: number; ece: number };
    why: { id: string; time: number; class: OppMarker["class"]; strategy: string; direction: string; probability: string; ev_r: number | null; risk: string; model: string }[];
  };
};

/** Desk symbols (BTC-USD, 1D) -> feed symbols (BTCUSDT, 1d). */
export function chartSymbol(s: string) { const u = s.toUpperCase(); return u.endsWith("-USD") ? `${u.slice(0, -4)}USDT` : u.replace(/^[A-Z]+:/, ""); }
export function chartInterval(tf: string): ChartInterval {
  const t = tf.toLowerCase(); return (CHART_INTERVALS as readonly string[]).includes(t) ? (t as ChartInterval) : t === "1s" || t === "real time" ? "live" : "15m";
}
export function tradingViewUrl(sym: string) {
  const s = chartSymbol(sym);
  const tv = s.endsWith("USDT") ? `BINANCE:${s}` : s.includes("=") ? s.replace("=F", "1!") : s;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tv)}`;
}

function useOverlays(symbol: string, interval: string, barType: string, live: boolean) {
  const [d, setD] = useState<Overlays | null>(null);
  const [barsRev, setBarsRev] = useState<Bar[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const seen = useRef<string | null>(null);
  useEffect(() => {
    let alive = true;
    seen.current = null;
    const pull = (initial: boolean) => {
      if (initial) { setLoading(true); setErr(null); }
      fetch(`/api/ai/chart/overlays?symbol=${encodeURIComponent(symbol)}&interval=${interval}&bar_type=${barType}&limit=600`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((p: Overlays) => {
          if (!alive) return;
          // Bar polls must not rebuild the chart. Layers refresh on the first load, the live minute tick, and whenever a new bar
          // (or a new model read) arrives on ANY timeframe: the key below changes once per bar close, not once per poll.
          const key = `${p.bars?.[p.bars.length - 1]?.time ?? 0}|${p.layers?.model_prediction?.as_of_bar ?? 0}|${p.layers?.model_prediction?.model?.version ?? ""}`;
          const changed = seen.current !== null && seen.current !== key;
          seen.current = key;
          if (initial || changed) setD(p);
          if (Array.isArray(p.bars)) setBarsRev(p.bars);
        })
        .catch((e: Error) => { if (alive && initial) { if (!live) setD(null); setErr(e.message); } })
        .finally(() => { if (alive && initial) setLoading(false); });
    };
    pull(true);
    // Closed bars arrive after the provider bar ends. Poll so a 15m/1h chart moves without a reload.
    const timer = window.setInterval(() => pull(false), 20_000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [symbol, interval, barType, live, tick]);
  // Live: every layer is recomputed on bar CLOSE only. Refetch a few seconds after each minute closes.
  useEffect(() => {
    if (!live) return;
    let t = 0;
    const arm = () => { const ms = 60_000 - (Date.now() % 60_000) + 3_000; t = window.setTimeout(() => { setTick((n) => n + 1); arm(); }, ms); };
    arm();
    return () => window.clearTimeout(t);
  }, [live]);
  return { data: d, barsRev, error: err, loading, refresh: () => setTick((n) => n + 1) };
}

/** Live tape: /api/market/live-view (genuine public candles only), polled at the server's refresh cadence. */
function useLiveTape(symbol: string, enabled: boolean, onSnapshot?: (s: LiveSnapshot) => void) {
  const [snap, setSnap] = useState<LiveSnapshot | null>(null);
  const [err, setErr] = useState("");
  const cb = useRef(onSnapshot); cb.current = onSnapshot;
  useEffect(() => {
    setSnap(null); setErr("");
    if (!enabled) return;
    const ctl = new AbortController();
    let timer = 0, every = 1;
    const poll = async () => {
      try {
        const r = await fetch(`/api/market/live-view?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store", signal: ctl.signal });
        if (!r.ok) throw new Error(`Market API returned ${r.status}`);
        const b = (await r.json()) as LiveSnapshot;
        if (ctl.signal.aborted) return;
        if (typeof b.symbol !== "string" || b.symbol.toUpperCase() !== symbol.toUpperCase() || !Array.isArray(b.candles)) throw new Error("invalid live snapshot for this symbol");
        every = Number.isFinite(b.refresh_seconds) ? Math.max(0.4, b.refresh_seconds) : 10;
        setSnap(b); setErr(""); cb.current?.(b);
      } catch (e) {
        if (ctl.signal.aborted) return;
        setErr(e instanceof Error ? e.message : "live feed unavailable"); every = Math.max(2, every);
      } finally { if (!ctl.signal.aborted) timer = window.setTimeout(() => void poll(), every * 1000); }
    };
    void poll();
    return () => { ctl.abort(); window.clearTimeout(timer); };
  }, [symbol, enabled]);
  return { snap, err };
}

const torontoStamp = (v: string | number | null | undefined) => {
  if (v == null || v === "") return "—";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (!Number.isFinite(d.getTime())) return "—";
  const f = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: "America/Toronto", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" }).formatToParts(d).map((x) => [x.type, x.value]));
  return `${f.month}-${f.day} ${f.hour}:${f.minute} ${f.timeZoneName ?? "ET"}`;
};
const fmt = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");
const fmtSigned = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(d)}` : "—");
const px = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? (Math.abs(v) >= 100 ? v.toFixed(2) : Math.abs(v) >= 1 ? v.toFixed(4) : v.toPrecision(4)) : "—");
const OUTCOME_TEXT: Record<string, { text: string; badge: string; tone: string }> = {
  hit_target: { text: "Hit target", badge: "✓", tone: "win" }, stopped_out: { text: "Stopped out", badge: "✗", tone: "loss" },
  timed_out: { text: "Timed out", badge: "◷", tone: "flat" }, open: { text: "Open", badge: "•", tone: "open" },
  not_filled: { text: "Not filled", badge: "–", tone: "flat" },
};
const CLASS_TEXT: Record<OppMarker["class"], string> = { ml_suggested: "Taken (ML)", ml_skip: "ML-skipped", risk_rejected: "Risk-rejected", rule_only: "Rule only" };
const outcomeOf = (m: OppMarker) => m.outcome_label ?? (m.outcome === "target" ? "hit_target" : m.outcome === "stop" ? "stopped_out" : m.outcome === "timeout" ? "timed_out" : "open");

/** Client-side PNG capture: lightweight-charts canvas + the HTML overlays (volume profile, prediction zone, marker chips) + a header strip. */
function captureChartPng(chart: IChartApi, stage: HTMLElement, meta: { symbol: string; timeframe: string; barType: string }) {
  const shot = chart.takeScreenshot();
  const dpr = shot.width / Math.max(1, stage.querySelector(".atlas-chart-canvas")?.getBoundingClientRect().width || shot.width);
  const head = Math.round(30 * dpr);
  const out = document.createElement("canvas");
  out.width = shot.width; out.height = shot.height + head;
  const g = out.getContext("2d");
  if (!g) return;
  const now = new Date();
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: "America/Toronto", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short" }).formatToParts(now).map((x) => [x.type, x.value]));
  const stamp = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ${parts.timeZoneName ?? "ET"}`;
  g.fillStyle = "#0b1118"; g.fillRect(0, 0, out.width, head);
  g.fillStyle = "#E8EEF5"; g.font = `${Math.round(13 * dpr)}px system-ui, sans-serif`; g.textBaseline = "middle";
  g.fillText(`ATLAS  ${meta.symbol}  ·  ${meta.timeframe}  ·  ${meta.barType} bars  ·  ${stamp}  ·  Paper / research only`, 10 * dpr, head / 2);
  g.drawImage(shot, 0, head);
  const base = (stage.querySelector(".atlas-chart-canvas") ?? stage).getBoundingClientRect();
  const sel = ".atlas-chart-vp-bin, .atlas-pz-outer, .atlas-pz-inner, .atlas-pz-mid, .atlas-chip";
  stage.querySelectorAll<HTMLElement>(sel).forEach((el) => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width && !r.height) return;
    const x = (r.left - base.left) * dpr, y = (r.top - base.top) * dpr + head, w = Math.max(1, r.width * dpr), h = Math.max(1, r.height * dpr);
    g.save(); g.globalAlpha = Number(cs.opacity) || 1;
    if (cs.backgroundColor && cs.backgroundColor !== "rgba(0, 0, 0, 0)") { g.fillStyle = cs.backgroundColor; g.fillRect(x, y, w, h); }
    if (cs.borderTopStyle !== "none" && parseFloat(cs.borderTopWidth) > 0) { g.strokeStyle = cs.borderTopColor; g.lineWidth = parseFloat(cs.borderTopWidth) * dpr; g.strokeRect(x, y, w, h); }
    const txt = el.classList.contains("atlas-chip") ? (el.textContent ?? "").trim() : "";
    if (txt) { g.fillStyle = cs.color; g.font = `${Math.round(parseFloat(cs.fontSize || "11") * dpr)}px system-ui, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(txt, x + w / 2, y + h / 2); }
    g.restore();
  });
  const fn = `ATLAS_${meta.symbol.replace(/[^A-Za-z0-9_-]/g, "")}_${meta.timeframe}_${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}.png`;
  out.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = fn; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, "image/png");
}

/** One-chart-per-symbol registry: a page must mount at most one full chart for a symbol. Dev builds shout. */
const MOUNTED = new Map<string, number>();
export function mountedChartCount(sym: string) { return MOUNTED.get(sym) ?? 0; }

type Geo = { chips: { m: OppMarker; x: number; y: number }[]; band: null | { x0: number; x1: number; y10: number; y25: number; y50: number; y75: number; y90: number } };

export function AtlasChart({ symbol, timeframe = "15m", height = 460, showPanel = true, allLayers = false, fill = false, details, onTimeframe, onLiveSnapshot, liveExtras }: {
  symbol: string; timeframe?: string; height?: number; showPanel?: boolean; allLayers?: boolean;
  /** Fill the parent (flex) instead of a fixed height. Layers, the footer, the model panel and `details` move to popovers. */
  fill?: boolean; details?: ReactNode;
  onTimeframe?: (tf: string) => void; onLiveSnapshot?: (s: LiveSnapshot) => void; liveExtras?: (s: LiveSnapshot | null, err: string) => ReactNode;
}) {
  const sym = chartSymbol(symbol);
  const [interval, setInterval_] = useState<ChartInterval>(chartInterval(timeframe));
  useEffect(() => setInterval_(chartInterval(timeframe)), [timeframe]);
  const pick = (iv: ChartInterval) => { setInterval_(iv); onTimeframe?.(iv === "live" ? "1s" : iv === "1d" ? "1D" : iv); };
  const live = interval === "live";
  const [barType, setBarType] = useState("time");
  const [on, setOn] = useState<Record<LayerId, boolean>>(() => Object.fromEntries(LAYERS.map((l) => [l.id,
    true])) as Record<LayerId, boolean>);   // all layers on by default; allLayers is kept for callers that pass it
  const { data, barsRev, error, loading, refresh } = useOverlays(sym, live ? "1m" : interval, live ? "time" : barType, live);
  const quote = useFeedQuotes([symbol])[symbol];
  const tape = useLiveTape(symbol, live, onLiveSnapshot);
  const [showNc, setShowNc] = useState(true);
  const nowcast = useNowcast(sym, live ? "1m" : interval, showNc);
  const box = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ReturnType<IChartApi["addHistogramSeries"]> | null>(null);
  const [geo, setGeo] = useState<Geo>({ chips: [], band: null });
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const relayout = useRef<() => void>(() => {});
  const [layersOpen, setLayersOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const savedRange = useRef<{ key: string; range: { from: number; to: number } | null } | null>(null);

  useEffect(() => {
    const n = (MOUNTED.get(sym) ?? 0) + 1; MOUNTED.set(sym, n);
    if (n > 1 && process.env.NODE_ENV !== "production") console.error(`[ATLAS] ${n} full charts mounted for ${sym}; a page must render exactly one AtlasChart per symbol.`);
    return () => { const k = (MOUNTED.get(sym) ?? 1) - 1; if (k > 0) MOUNTED.set(sym, k); else MOUNTED.delete(sym); };
  }, [sym]);
  useEffect(() => setSel(null), [sym, interval]);

  const visibleMarkers = useMemo(() => {
    if (!data) return [] as OppMarker[];
    const out: OppMarker[] = [];
    if (on.ml_markers) out.push(...(data.layers.ml_markers?.items ?? []));
    if (on.setups) out.push(...(data.layers.setups?.items ?? []));
    return out;
  }, [data, on.ml_markers, on.setups]);
  const fwd = data?.layers.forward;
  const preds = data?.layers.predictions;
  const bars = useMemo(() => orderedChartPoints(barsRev ?? data?.bars ?? []), [barsRev, data]);
  const barsRef = useRef(bars);
  barsRef.current = bars;

  useEffect(() => {
    const el = box.current;
    if (!el || !data || !bars.length) {
      // evo-11: an empty chart must not keep the previous symbol's volume profile, marker chips or prediction band
      if (profileRef.current) profileRef.current.innerHTML = "";
      setGeo({ chips: [], band: null });
      return;
    }
    const css = getComputedStyle(el);
    const text = css.getPropertyValue("--c-muted").trim() || "#98A3B3";
    const grid = css.getPropertyValue("--c-border").trim() || "#27303D";
    const chart = createChart(el, { ...deskTimeOptions, height, autoSize: true,
      layout: { ...deskTimeOptions.layout, background: { color: "transparent" }, textColor: text, fontSize: 11 },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } }, rightPriceScale: { borderColor: grid },
      timeScale: { ...deskTimeOptions.timeScale, borderColor: grid, rightOffset: 4, secondsVisible: live } });
    chartRef.current = chart;
    const probOn = on.ml_probability && !!data.layers.ml_probability?.points.length;
    const bottom = probOn ? 0.3 : 0.12;
    const dur = DUR[data.interval] ?? 900;
    if (on.regimes && data.layers.regimes?.spans.length) {
      const rg = chart.addHistogramSeries({ priceScaleId: "regime", lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("regime").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      const pts: { time: UTCTimestamp; value: number; color: string }[] = [];
      for (const s of data.layers.regimes.spans) for (const b of bars) if (b.time >= s.from && b.time <= s.to)
        pts.push({ time: b.time as UTCTimestamp, value: 1, color: REGIME_COLORS[s.trend] ?? "transparent" });
      rg.setData(orderedChartPoints(pts));
    }
    const sess = data.layers.vwap?.sessions;
    if (on.sessions && sess?.status === "ok" && sess.spans.length) {
      // Alternating session bands (UTC day / US cash session / CME day). Out-of-session bars (equity pre/post market) stay unshaded.
      const sh = chart.addHistogramSeries({ priceScaleId: "sess", lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("sess").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
      const pts: { time: UTCTimestamp; value: number; color: string }[] = [];
      for (const sp of sess.spans) for (const b of bars) if (b.time >= sp.from && b.time < sp.to)
        pts.push({ time: b.time as UTCTimestamp, value: 1, color: sp.shade ? "rgba(152,163,179,0.07)" : "rgba(86,180,233,0.045)" });
      sh.setData(orderedChartPoints(pts));
    }
    const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    volRef.current = vol;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 1 - bottom - 0.1, bottom }, visible: false });
    vol.setData(bars.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "rgba(46,184,138,0.35)" : "rgba(240,128,60,0.35)" })));
    const candles: ISeriesApi<"Candlestick"> = chart.addCandlestickSeries({ upColor: "#2EB88A", downColor: "#F0803C", borderVisible: false,
      wickUpColor: "#2EB88A", wickDownColor: "#F0803C" });
    candlesRef.current = candles;
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.06, bottom: bottom + 0.02 } });
    const alt = !live && data.display?.kind !== "time" && data.display?.status === "ok" && data.display.bars?.length
      ? altToCandles(data.display.bars.map((a) => ({ ...a, completed_at: a.time })), dur) : null;
    const series: (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] =
      alt ?? bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close }));
    // Prediction horizon: whitespace (no fabricated candles) out to horizon_end so the band has room at the right edge.
    if (on.prediction_zone && !alt && fwd?.status === "ok" && fwd.horizon_end) {
      const last = bars[bars.length - 1].time;
      for (let t = last + dur; t <= fwd.horizon_end + dur; t += dur) series.push({ time: t as UTCTimestamp });
    }
    candles.setData(orderedChartPoints(series));
    // Past predictions as hit/miss (resolved only), native markers under the bar.
    const times = new Set(bars.map((b) => b.time));
    const nativeMarks: { time: UTCTimestamp; position: "belowBar" | "aboveBar"; shape: "circle" | "arrowDown" | "arrowUp"; size: number; color: string; text: string }[] = [];
    if (on.predictions && preds?.items.length) {
      nativeMarks.push(...preds.items.filter((p) => p.hit != null && times.has(p.time)).map((p) => ({
        time: p.time as UTCTimestamp, position: "belowBar" as const, shape: "circle" as const, size: 0.6,
        color: p.hit ? "#2EB88A" : "#F0803C", text: `${p.hit ? "hit" : "miss"} ${Math.round(p.p * 100)}%` })));
    }
    const vwl = data.layers.vwap;
    if (on.vwap && vwl?.points?.length) {
      // One line per session: the VWAP resets at each session open, so lines are never joined across the reset.
      const bySession = new Map<string, { time: UTCTimestamp; value: number }[]>();
      for (const q of vwl.points) { const k = String(q.session ?? "x"); (bySession.get(k) ?? bySession.set(k, []).get(k)!).push({ time: q.time as UTCTimestamp, value: q.value }); }
      const groups = [...bySession.values()].slice(-24);
      groups.forEach((g, i) => {
        const vw = chart.addLineSeries({ color: "#F0E442", lineWidth: 1, lastValueVisible: i === groups.length - 1, priceLineVisible: false, crosshairMarkerVisible: false, title: i === groups.length - 1 ? "VWAP" : "" });
        vw.setData(orderedChartPoints(g));
      });
    }
    const av = vwl?.anchored;
    if (on.anchored_vwap && av?.status === "ok" && av.points?.length) {
      const al = chart.addLineSeries({ color: "#CC79A7", lineWidth: 2, lineStyle: LineStyle.Dashed, lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false, title: "AVWAP" });
      al.setData(orderedChartPoints(av.points.map((q) => ({ time: q.time as UTCTimestamp, value: q.value }))));
      if (av.anchor && times.has(av.anchor.time)) {
        const hi = av.anchor.kind === "swing_high";
        nativeMarks.push({ time: av.anchor.time as UTCTimestamp, position: hi ? "aboveBar" : "belowBar", shape: hi ? "arrowDown" : "arrowUp", size: 0.7, color: "#CC79A7", text: `AVWAP ${hi ? "swing high" : "swing low"}` });
      }
    }
    const nl = data.layers.news;
    if (on.news && nl?.status === "ok" && nl.items?.length) {
      const bt = bars.map((b) => b.time);
      for (const it of nl.items.slice(-40)) {
        let k = -1; for (let j = bt.length - 1; j >= 0; j--) { if (bt[j] <= it.time) { k = j; break; } }
        if (k < 0) continue;
        nativeMarks.push({ time: bt[k] as UTCTimestamp, position: "aboveBar", shape: "circle", size: 0.5, color: it.hype_flags?.length ? "#D55E00" : it.tier === 1 ? "#56B4E9" : "#98A3B3", text: it.hype_flags?.length ? "hype?" : (it.event_type ? it.event_type.replace(/_/g, " ") : "news") });
      }
    }
    if (nativeMarks.length) candles.setMarkers(nativeMarks.sort((a, b) => a.time - b.time));
    // Forward path: empirical median of the 8-bar forward return (not model-conditioned) from the last closed bar to the horizon.
    if (on.prediction_zone && !alt && fwd?.status === "ok" && fwd.band && fwd.as_of_bar && fwd.horizon_end && fwd.as_of_close != null) {
      const lastT = bars[bars.length - 1].time;
      const path = chart.addLineSeries({ color: "#E8EEF5", lineWidth: 2, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, title: "median path" });
      const endT = Math.max(fwd.horizon_end, lastT + dur);
      path.setData([{ time: lastT as UTCTimestamp, value: bars[bars.length - 1].close }, { time: endT as UTCTimestamp, value: fwd.band.p50 }]);
    }
    // Conformal band: the 80% band issued at each closed bar for the H-bar move (no future bars are drawn).
    const cb = data.layers.conformal_bands;
    if (on.conformal_bands && !alt && cb?.status === "ok" && cb.points?.length) {
      for (const k of ["upper", "lower"] as const) {
        const ln = chart.addLineSeries({ color: "#56B4E9", lineWidth: 1, lineStyle: LineStyle.Dotted, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, title: k === "upper" ? "80% band" : "" });
        ln.setData(orderedChartPoints(cb.points.map((q) => ({ time: q.time as UTCTimestamp, value: q[k] }))));
      }
    }
    if (on.zones) for (const z of data.layers.zones?.items ?? []) {
      const color = ZONE_COLORS[z.kind] ?? "#98A3B3";
      candles.createPriceLine({ price: z.high, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: z.label });
      if (z.low !== z.high) candles.createPriceLine({ price: z.low, color, lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    }
    if (probOn) {
      const pr = chart.addLineSeries({ priceScaleId: "left", color: "#56B4E9", lineWidth: 1, pointMarkersVisible: true, lastValueVisible: true,
        priceLineVisible: false, title: "ML p(win)" });
      chart.priceScale("left").applyOptions({ scaleMargins: { top: 0.74, bottom: 0.02 }, visible: true, borderColor: grid });
      pr.setData(orderedChartPoints(data.layers.ml_probability!.points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value, color: p.take ? "#0072B2" : "#98A3B3" }))));
    }
    const layout = () => {
      const ts = chart.timeScale();
      const chips = visibleMarkers.map((m) => {
        const x = ts.timeToCoordinate(m.time as UTCTimestamp);
        const b = bars.find((r) => r.time === m.time);
        const y = candles.priceToCoordinate(b ? (m.direction === "short" ? b.high : b.low) : m.price);
        return x == null || y == null ? null : { m, x, y };
      }).filter(Boolean) as Geo["chips"];
      let band: Geo["band"] = null;
      if (on.prediction_zone && fwd?.status === "ok" && fwd.band && fwd.as_of_bar && fwd.horizon_end) {
        const x0 = ts.timeToCoordinate(fwd.as_of_bar as UTCTimestamp), x1 = ts.timeToCoordinate(fwd.horizon_end as UTCTimestamp);
        const q = fwd.band, c = (v: number) => candles.priceToCoordinate(v);
        const ys = [c(q.p10), c(q.p25), c(q.p50), c(q.p75), c(q.p90)];
        if (x0 != null && x1 != null && ys.every((v) => v != null)) band = { x0, x1, y10: ys[0]!, y25: ys[1]!, y50: ys[2]!, y75: ys[3]!, y90: ys[4]! };
      }
      setGeo({ chips, band });
      const pf = profileRef.current;
      if (!pf) return;
      pf.innerHTML = "";
      const vp = data.layers.volume_profile;
      if (!on.volume_profile || !vp || vp.status !== "ok") return;
      const max = Math.max(...vp.bins.map((b) => b.volume), 1);
      for (const b of vp.bins) {
        const y1 = candles.priceToCoordinate(b.high), y2 = candles.priceToCoordinate(b.low);
        if (y1 == null || y2 == null) continue;
        const d = document.createElement("div");
        d.className = "atlas-chart-vp-bin";
        d.style.top = `${y1}px`; d.style.height = `${Math.max(1, y2 - y1 - 1)}px`; d.style.width = `${(b.volume / max) * 100}%`;
        if (vp.poc >= b.low && vp.poc <= b.high) d.dataset.poc = "1";
        pf.appendChild(d);
      }
    };
    let raf = 0;
    relayout.current = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(layout); };
    const keep = savedRange.current;
    if (keep && keep.key === `${sym}|${data.interval}|${live}|${barType}` && keep.range) { try { chart.timeScale().setVisibleLogicalRange(keep.range); } catch { /* fall through to default */ } }
    else if (live) chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, series.length - 150), to: series.length + 2 });
    else chart.timeScale().fitContent();
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => relayout.current());
    const ro = new ResizeObserver(() => relayout.current()); ro.observe(el);
    const t = setTimeout(() => relayout.current(), 60);
    return () => { clearTimeout(t); cancelAnimationFrame(raf); ro.disconnect();
      try { savedRange.current = { key: `${sym}|${data.interval}|${live}|${barType}`, range: chart.timeScale().getVisibleLogicalRange() }; } catch { /* chart already gone */ }
      chart.remove(); chartRef.current = null; candlesRef.current = null; volRef.current = null; relayout.current = () => {}; };
  }, [data, on, visibleMarkers, height, fwd, preds, live]);

  // evo-16 M4: the predicted path and its interval band. Dashed + dotted lavender, never candles; a forecast from the last REAL print.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !showNc || !nowcast || nowcast.status !== "ok" || !nowcast.path?.length || !bars.length) return;
    const last = bars[bars.length - 1];
    const pts = nowcast.path.filter((q) => q.t > last.time);
    if (!pts.length) return;
    const COL = "#B8A1FF";
    const mk = (style: LineStyle, w: 1 | 2, title: string) => chart.addLineSeries({ color: COL, lineWidth: w, lineStyle: style, lastValueVisible: !!title, priceLineVisible: false, crosshairMarkerVisible: false, title });
    const made: ISeriesApi<"Line">[] = [];
    try {
      const mid = mk(LineStyle.Dashed, 2, "Predicted"), hi = mk(LineStyle.Dotted, 1, ""), lo = mk(LineStyle.Dotted, 1, "");
      made.push(mid, hi, lo);
      const head = { time: last.time as UTCTimestamp, value: last.close };
      mid.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.mid }))]);
      hi.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.hi }))]);
      lo.setData([head, ...pts.map((q) => ({ time: q.t as UTCTimestamp, value: q.lo }))]);
    } catch { /* a series that cannot take future points is skipped; nothing is invented */ }
    return () => { try { made.forEach((m) => chart.removeSeries(m)); } catch { /* chart already gone */ } };
  }, [nowcast, bars, showNc, data, on, visibleMarkers, height, fwd, preds, live]);

  // Newer closed bars replace the candle series in place. The chart is not rebuilt, and a user who is at the
  // right edge keeps following the latest bar.
  const drawnRev = useRef<Bar[] | null>(null);
  useEffect(() => {
    const c = candlesRef.current, v = volRef.current, chart = chartRef.current;
    if (!c || !chart || !barsRev?.length || drawnRev.current === barsRev) return;
    const alt = !live && data?.display?.kind && data.display.kind !== "time" && data.display.status === "ok";
    if (alt) { drawnRev.current = barsRev; return; }
    const points = orderedChartPoints(barsRev.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    if (!points.length) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    const prev = drawnRev.current?.length ?? points.length;
    drawnRev.current = barsRev;
    try { c.setData(points); } catch { return; }
    if (v) {
      try {
        v.setData(orderedChartPoints(barsRev.map((b) => ({ time: b.time as UTCTimestamp, value: b.volume, color: b.close >= b.open ? "rgba(46,184,138,0.35)" : "rgba(240,128,60,0.35)" }))));
      } catch { /* series already removed */ }
    }
    const added = points.length - prev;
    if (range && Number.isFinite(added)) {
      const follow = range.to >= prev - 1.5;
      chart.timeScale().setVisibleLogicalRange(follow ? { from: range.from + added, to: range.to + added } : range);
    }
  }, [barsRev, data, live]);

  // Last print from the feed store moves the forming candle between bar closes.
  useEffect(() => {
    const c = candlesRef.current;
    if (!c || !quote || quote.price == null || quote.observed_at == null) return;
    if (quote.status === "stale" || quote.status === "no_data" || quote.status === "market_closed") return;
    if (!quote.source || quote.source === "yahoo") return;
    if (Date.now() / 1000 - quote.observed_at > 20 * 60) return;
    if (!live && barType !== "time") return;
    const dur = DUR[live ? "1m" : interval] ?? 900;
    const stamp = Math.floor(quote.observed_at);
    const bucket = (stamp - (stamp % dur)) as UTCTimestamp;
    const last = barsRef.current[barsRef.current.length - 1];
    if (!last || bucket < last.time || bucket > last.time + dur) return;
    const price = quote.price;
    const same = bucket === last.time;
    try {
      c.update({ time: bucket, open: same ? last.open : price, high: same ? Math.max(last.high, price) : price, low: same ? Math.min(last.low, price) : price, close: price });
    } catch { /* the series has no bar this update can follow */ }
  }, [quote, live, interval, barType]);

  // Live: update the forming minute from genuine public candles only. Layers stay on closed bars.
  useEffect(() => {
    const c = candlesRef.current, s = tape.snap;
    if (!live || !c || !bars.length || !s) return;
    if (!["public_last_trade", "public_market_candles"].includes(s.chart_source ?? "")) return;
    const lastClosed = bars[bars.length - 1].time;
    const byMin = new Map<number, { time: UTCTimestamp; open: number; high: number; low: number; close: number }>();
    for (const b of s.candles ?? []) {
      const t = Math.floor(Date.parse(b.timestamp) / 1000);
      if (!Number.isFinite(t) || ![b.open, b.high, b.low, b.close].every(Number.isFinite)) continue;
      const m = t - (t % 60);
      if (m <= lastClosed) continue;
      const cur = byMin.get(m);
      byMin.set(m, cur ? { ...cur, high: Math.max(cur.high, b.high), low: Math.min(cur.low, b.low), close: b.close } : { time: m as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close });
    }
    try { [...byMin.values()].sort((a, b) => a.time - b.time).forEach((p) => c.update(p)); } catch { /* whitespace ahead: skip */ }
  }, [tape.snap, live, data, bars]);

  const all = useMemo(() => [...(data?.layers.ml_markers?.items ?? []), ...(data?.layers.setups?.items ?? [])], [data]);
  const selected = all.find((m) => m.id === sel) ?? null;
  const shown = all.find((m) => m.id === (hover ?? sel)) ?? null;

  // Trade geometry for the selected marker: entry/stop/target and the resolution path.
  useEffect(() => {
    const chart = chartRef.current, c = candlesRef.current;
    if (!chart || !c || !selected || !on.trade_lines) return;
    const lines = [
      c.createPriceLine({ price: selected.price, color: "#56B4E9", lineWidth: 2, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "entry" }),
      c.createPriceLine({ price: selected.stop, color: "#F0803C", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "stop" }),
      c.createPriceLine({ price: selected.target, color: "#2EB88A", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "target" }),
    ];
    const path = orderedChartPoints(selected.resolution_path ?? []);
    const ps = path.length > 1 ? chart.addLineSeries({ color: "#E8EEF5", lineWidth: 2, lineStyle: LineStyle.Dotted, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false }) : null;
    ps?.setData(path.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    return () => { try { lines.forEach((l) => c.removePriceLine(l)); if (ps) chart.removeSeries(ps); } catch { /* chart already gone */ } };
  }, [selected, on.trade_lines, data, on]);

  const p = data?.provider;
  const ms = data?.market_session;
  const badge = p?.realtime === true ? "real-time" : p?.realtime === false ? p.delay_label : "delay not tagged";
  const unavailable = data ? LAYERS.filter((l) => on[l.id] && isOff(data, l.id)) : [];
  const rc = preds?.running_calibration;
  const mp = data?.layers.model_prediction;
  const tapeOk = live && tape.snap && ["public_last_trade", "public_market_candles"].includes(tape.snap.chart_source ?? "");
  return (
    <section className={`ux-card atlas-chart${fill ? " is-fill" : ""}`} aria-label={`ATLAS chart ${sym}`} data-atlas-chart={sym} data-interval={interval}>
      <header className="atlas-chart-bar">
        <strong className="atlas-chart-sym">{sym}</strong>
        <div className="atlas-chart-seg" role="group" aria-label="Timeframe">
          {CHART_INTERVALS.map((iv) => <button key={iv} type="button" aria-pressed={iv === interval} onClick={() => pick(iv)}>{iv === "1d" ? "1D" : iv === "live" ? "Live" : iv}</button>)}
        </div>
        {!live && <label className="atlas-chart-select">Bars
          <select value={barType} onChange={(e) => setBarType(e.target.value)} aria-label="Bar type">
            {CHART_BAR_TYPES.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </select>
        </label>}
        <span className={`atlas-chart-badge${p?.realtime || tapeOk ? " is-live" : ""}`} title={p ? `${p.built}; providers: ${p.providers.join(", ") || "none"}` : ""}>
          {live ? (tapeOk ? `live · ${tape.snap!.feed_origin ?? "public feed"}` : tape.err ? "live feed unavailable" : "connecting…") : p?.provider ? `${p.provider} · ${badge}` : loading ? "loading…" : "no provider"}
        </span>
        {ms && !fill && (
          <span
            className={`atlas-chart-badge${ms.is_open ? " is-live" : ""}`}
            title={`${ms.venue_name} · ${ms.schedule_summary} · ${ms.reason}`}
            style={{
              borderColor: ms.is_open ? "rgba(46,184,138,0.45)" : "rgba(240,128,60,0.45)",
              color: ms.is_open ? "#2EB88A" : "#F0803C",
            }}
          >
            {ms.is_open ? "● " : "○ "}{ms.venue_name}: {ms.status_label} · {ms.countdown}
          </span>
        )}
        <button type="button" className="atlas-chart-badge" aria-pressed={showNc} data-testid="nowcast-toggle" onClick={() => setShowNc((v) => !v)}
          title={nowcast?.status === "ok" ? `${NOWCAST_LABEL}. Zero-drift random-walk path with a split-conformal ${Math.round((nowcast.level ?? 0.8) * 100)}% band that widens with time since the last real print. Never written to the bar store, never a training label. ${nowcast.reason ?? ""}` : (nowcast?.reason ?? NOWCAST_LABEL)}
          style={{ borderColor: "#B8A1FF", color: showNc ? "#B8A1FF" : undefined, borderStyle: "dashed" }}>
          {showNc ? "▪ " : "▫ "}{NOWCAST_LABEL}{showNc && nowcast?.status === "ok" && nowcast.anchor ? ` · last real ${nowcast.anchor.source === "quote" ? "quote" : "print"} ${ageText(nowcast.anchor.age_s)} ago${nowcast.mode === "end_of_day" ? " · end-of-day data" : ""}` : showNc && nowcast && nowcast.status !== "ok" ? ` · ${nowcast.status.replace(/_/g, " ")}` : ""}
        </button>
        {showNc && <HorizonChips nc={nowcast} />}
        {p?.built?.startsWith("resampled") && !fill ? <span className="atlas-chart-badge" title={p.built}>{interval} resampled</span> : null}
        <ModelChip mp={mp} loading={loading} noBars={data?.status === "no_data"} />
        <span className="atlas-chart-badge is-safe" title="ML output is advisory research. It can never place an order.">{fill ? "exec: " : "execution_permission: "}{data?.execution_permission ?? "none"}</span>
        <button type="button" className="atlas-chart-capture" title="Save chart as PNG" aria-label="Save chart as PNG"
          disabled={!data?.bars.length}
          onClick={() => { const c = chartRef.current, st = stageRef.current; if (c && st) captureChartPng(c, st, { symbol: sym, timeframe: live ? "live-1m" : interval, barType: live ? "time" : barType }); }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" /><circle cx="12" cy="13" r="4" /></svg>
        </button>
        {fill ? (
          <span className="atlas-chart-links">
            <button type="button" className="atlas-chart-pop-btn" aria-expanded={layersOpen} onClick={() => { setLayersOpen((v) => !v); setDrawerOpen(false); }}>Layers {Object.values(on).filter(Boolean).length}/{LAYERS.length}</button>
            <button type="button" className="atlas-chart-pop-btn" aria-expanded={drawerOpen} onClick={() => { setDrawerOpen((v) => !v); setLayersOpen(false); }}>Details {drawerOpen ? "▾" : "▴"}</button>
          </span>
        ) : (
          <span className="atlas-chart-links">
            <a href={tradingViewUrl(sym)} target="_blank" rel="noopener noreferrer">Open in TradingView ↗</a>
            <NavLink to="markets.scan">Pine v5 export</NavLink>
          </span>
        )}
      </header>
      {(!fill || layersOpen) && <div className={`atlas-chart-layers${fill ? " is-pop" : ""}`} role="group" aria-label="Layers">
        <div className="atlas-chart-layers-head">
          <strong>Layers {Object.values(on).filter(Boolean).length}/{LAYERS.length}</strong>
          <button type="button" onClick={() => setOn(Object.fromEntries(LAYERS.map((l) => [l.id, true])) as Record<LayerId, boolean>)}>all</button>
          <button type="button" onClick={() => setOn(Object.fromEntries(LAYERS.map((l) => [l.id, false])) as Record<LayerId, boolean>)}>none</button>
          {data && <span className="atlas-chart-layers-n">{LAYERS.filter((l) => isOff(data, l.id)).length} unavailable here: hover a struck-through chip for the reason</span>}
        </div>
        <div className="atlas-chart-layers-grid">
          {LAYER_GROUPS.map((g) => (
            <div key={g.title} className="atlas-chart-layers-group" data-layer-group={g.title}>
              <h6>{g.title}</h6>
              <div className="atlas-chart-layers-chips">
                {g.ids.map((id) => {
                  const l = LAYERS.find((x) => x.id === id)!;
                  const off = isOff(data, l.id);
                  return (
                    <label key={l.id} className={`atlas-chart-chip${on[l.id] ? " is-on" : ""}${off ? " is-off" : ""}`} data-layer-chip={l.id} title={off ? `${l.label}: ${layerReason(data, l.id)}` : l.label}>
                      <input type="checkbox" checked={on[l.id]} onChange={(e) => setOn({ ...on, [l.id]: e.target.checked })} />{l.label}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>}
      <div ref={stageRef} className="atlas-chart-stage" style={fill ? { flex: "1 1 0", minHeight: 120 } : { height }}>
        <div ref={box} className="atlas-chart-canvas" />
        <div ref={profileRef} className="atlas-chart-vp" aria-hidden />
        {geo.band && (() => { const b = geo.band; const w = Math.max(8, b.x1 - b.x0); return (
          <div className="atlas-pz" aria-hidden style={{ left: b.x0, width: w }}>
            <div className="atlas-pz-outer" style={{ top: b.y90, height: Math.max(1, b.y10 - b.y90) }} />
            <div className="atlas-pz-inner" style={{ top: b.y75, height: Math.max(1, b.y25 - b.y75) }} />
            <div className="atlas-pz-mid" style={{ top: b.y50 }} />
          </div>); })()}
        <div className="atlas-chips">
          {geo.chips.map(({ m, x, y }) => {
            const short = m.direction === "short", o = OUTCOME_TEXT[outcomeOf(m)];
            const op = m.probability == null ? 0.85 : 0.45 + 0.55 * Math.min(1, Math.max(0, m.probability));
            return (
              <button key={m.id} type="button" className={`atlas-chip is-${m.class} is-${short ? "sell" : "buy"}${sel === m.id ? " is-sel" : ""}`}
                style={{ left: x, top: short ? y - 6 : y + 6, opacity: op }} data-marker-id={m.id}
                aria-label={`${short ? "Sell" : "Buy"} ${CLASS_TEXT[m.class]} ${m.strategy}`}
                title={markerTitle(m, short)}
                onMouseEnter={() => on.marker_details && setHover(m.id)} onMouseLeave={() => setHover(null)}
                onClick={() => setSel(sel === m.id ? null : m.id)}>
                <span className="atlas-chip-arrow">{short ? "▼" : "▲"}</span>
                {on.outcomes && o && <span className={`atlas-chip-out is-${o.tone}`}>{o.badge}</span>}
              </button>
            );
          })}
        </div>
        {on.prediction_zone && data?.status === "ok" && <PredictionCard fwd={fwd} rc={rc} mp={mp} dp={data?.layers.directional_prediction} />}
        {NEW_LAYER_IDS.some((k) => on[k]) && data?.status === "ok" && <LayersCard data={data} on={on} />}
        {on.marker_details && shown && <MarkerCard m={shown} onClose={() => { setSel(null); setHover(null); }} pinned={shown.id === sel} />}
        {(error || (data && data.status !== "ok")) && !data?.bars.length && (showNc && nowcast?.status === "ok" && nowcast.path?.length && nowcast.anchor ? (
          <>
            <NowcastOnly nc={nowcast} height={fill ? "100%" : height} sym={sym} interval={live ? "1m" : interval} />
            <div className="atlas-chart-info" role="status" data-testid="nowcast-info-banner">
              {nowcastBannerText(nowcast, live ? "1m" : interval, sym)}
              {nowcast.proxy_candidate && <> {nowcast.proxy_candidate.label}: {nowcast.proxy_candidate.status === "active" ? "active (proxy, not the asset)" : "needs verification, inactive"}.</>}
            </div>
          </>
        ) : (
          <div className="atlas-chart-empty" role="status" data-testid="chart-no-bars-info">
            {error ? `Chart data unavailable (${error}).` : `No ${data?.interval} bars are stored for ${sym} yet.`}{" "}
            {data?.reason ? `${data.reason} ` : nowcast && nowcast.status !== "ok" ? `No forecast either: ${nowcast.reason ?? nowcast.status.replace(/_/g, " ")} ` : ""}
            {data?.cause ? <span data-testid="chart-no-data-cause" data-cause={data.cause} /> : null}A price is never invented: a forecast needs one real print to start from.
          </div>
        ))}
      </div>
      {!fill && (
      <footer className="atlas-chart-foot">
        {live && <span>Live: forming minute from {tapeOk ? `${tape.snap!.feed_origin ?? "public"} ticks` : "no genuine public tape yet"}{tape.err ? ` (${tape.err})` : ""}. Markers and predictions update on 1m bar close only.</span>}
        {p?.delay_note && <span data-testid="chart-delay-note">Stock data freshness: {p.delay_note}</span>}
        {!live && data?.display && data.display.status !== "ok" && <span>{data.display.kind}: {data.display.reason}</span>}
        {!live && data?.display?.note && data.display.status === "ok" && <span>{data.display.note}.</span>}
        {!fill && unavailable.map((l) => <span key={l.id}>{l.label}: {layerReason(data, l.id)}</span>)}
        {on.regimes && data?.layers.regimes?.current && <span>Regime now: {data.layers.regimes.current.replace(/_/g, " ")}</span>}
        {on.conviction && data?.layers.conviction?.status === "ok" && <span>Conviction {data.layers.conviction.score} · {data.layers.conviction.label}</span>}
        <span>Data: ATLAS feed ({p?.built ?? "—"}), free sources only. Rendering: <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a>. Times America/Toronto. Paper only.</span>
      </footer>
      )}
      {fill && (
      <footer className="atlas-chart-foot is-line" title="Open Details for the full data, layer and model notes.">
        {live
          ? <span>Live: forming minute from {tapeOk ? `${tape.snap!.feed_origin ?? "public"} ticks` : "no genuine public tape yet"}{tape.err ? ` (${tape.err})` : ""}. Markers and predictions update on 1m bar close only. </span>
          : <span>Data: ATLAS feed ({p?.built ?? "—"}), free sources only. Times America/Toronto. Paper only. {p?.delay_note ? `Freshness: ${p.delay_label}. ` : ""}</span>}
        {unavailable.length > 0 && <span>· {unavailable.length} layer{unavailable.length === 1 ? "" : "s"} without data (see Details). </span>}
        {!live && data?.display && data.display.status !== "ok" && <span>· {data.display.kind}: {data.display.reason}</span>}
      </footer>
      )}
      {fill && drawerOpen && (
        <div className="atlas-drawer" role="dialog" aria-label="Chart details">
          {ms && <div className="atlas-drawer-row"><span className={`atlas-chart-badge${ms.is_open ? " is-live" : ""}`} title={`${ms.venue_name} · ${ms.schedule_summary} · ${ms.reason}`}>{ms.is_open ? "● " : "○ "}{ms.venue_name}: {ms.status_label} · {ms.countdown}</span>
            {p?.built?.startsWith("resampled") ? <span className="atlas-chart-badge" title={p.built}>{interval} resampled</span> : null}
            <span className="atlas-chart-links"><a href={tradingViewUrl(sym)} target="_blank" rel="noopener noreferrer">Open in TradingView ↗</a><NavLink to="markets.scan">Pine v5 export</NavLink></span></div>}
          <div className="atlas-chart-foot">
        {live && <span>Live: forming minute from {tapeOk ? `${tape.snap!.feed_origin ?? "public"} ticks` : "no genuine public tape yet"}{tape.err ? ` (${tape.err})` : ""}. Markers and predictions update on 1m bar close only.</span>}
        {p?.delay_note && <span data-testid="chart-delay-note">Stock data freshness: {p.delay_note}</span>}
        {!live && data?.display && data.display.status !== "ok" && <span>{data.display.kind}: {data.display.reason}</span>}
        {!live && data?.display?.note && data.display.status === "ok" && <span>{data.display.note}.</span>}
        {unavailable.map((l) => <span key={l.id}>{l.label}: {data!.layers[l.id as keyof Overlays["layers"]]!.reason ?? data!.layers[l.id as keyof Overlays["layers"]]!.note ?? "no data for this symbol/interval"}</span>)}
        {on.regimes && data?.layers.regimes?.current && <span>Regime now: {data.layers.regimes.current.replace(/_/g, " ")}</span>}
        {on.conviction && data?.layers.conviction?.status === "ok" && <span>Conviction {data.layers.conviction.score} · {data.layers.conviction.label}</span>}
        <span>Data: ATLAS feed ({p?.built ?? "—"}), free sources only. Rendering: <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a>. Times America/Toronto. Paper only.</span>
          </div>
          {live && liveExtras?.(tape.snap, tape.err)}
          {details}
          {showPanel && data && <AtlasMlPanel data={data} showConviction={on.conviction} showPredictions={on.predictions} onRefresh={refresh} />}
        </div>
      )}
      {!fill && live && liveExtras?.(tape.snap, tape.err)}
      {!fill && showPanel && data && <AtlasMlPanel data={data} showConviction={on.conviction} showPredictions={on.predictions} onRefresh={refresh} />}
    </section>
  );
}

function markerTitle(m: OppMarker, short: boolean) {
  const i = m.indicators;
  return [`${short ? "SELL" : "BUY"} · ${m.setup ?? m.strategy.replace(/_/g, " ")} · ${CLASS_TEXT[m.class]}`,
    `Confidence: ${m.probability == null ? "rule only, no model verdict" : `p(win) ${fmt(m.probability, 2)}${m.threshold != null ? ` vs ${fmt(m.threshold, 2)} threshold` : ""}`}`,
    `RSI ${fmt(i?.rsi, 1)} · ADX ${fmt(i?.adx, 1)} · MACD hist ${fmt(i?.macd_hist, 2)} · VWAP dist ${i?.vwap_dist_atr == null ? "—" : `${fmt(i.vwap_dist_atr, 2)} ATR`} · regime ${i?.regime ?? "—"}`].join("\n");
}

function MarkerCard({ m, onClose, pinned }: { m: OppMarker; onClose: () => void; pinned: boolean }) {
  const i = m.indicators, o = OUTCOME_TEXT[outcomeOf(m)];
  const rows: [string, string][] = [
    ["Setup", m.setup ?? m.strategy.replace(/_/g, " ")],
    ["Confidence", m.probability == null ? "rule only, no model verdict" : `p(win) ${fmt(m.probability, 2)} vs ${fmt(m.threshold, 2)} thr`],
    ["Expected Value", m.ev_r == null ? "—" : `${fmtSigned(m.ev_r, 2)}R`],
    ["RSI", fmt(i?.rsi, 1)], ["ADX", fmt(i?.adx, 1)], ["MACD hist", fmt(i?.macd_hist, 2)],
    ["VWAP dist", i?.vwap_dist_atr == null ? "—" : `${fmt(i.vwap_dist_atr, 2)} ATR`], ["ATR", px(i?.atr)],
    ["Regime", i?.regime ?? "—"], ["Zone", m.zone_touched ?? "—"],
    ["Entry", px(m.price)], ["Stop", px(m.stop)], ["Target", px(m.target)],
    ["LLM review", m.llm_review ? (m.llm_review.status === "ok" ? `${m.llm_review.verdict.replace(/_/g, " ")} (${m.llm_review.mode}${m.llm_review.applied ? ", applied" : ", not applied"})` : `no opinion: ${m.llm_review.reason ?? m.llm_review.status}`) : "not reviewed"],
    ["Outcome", `${o?.text ?? m.outcome}${m.r != null ? ` · ${m.r >= 0 ? "+" : ""}${m.r.toFixed(2)}R` : ""}`],
  ];
  return (
    <aside className={`atlas-mcard is-${m.class}`} role="dialog" aria-label="Marker details">
      <header><span className={`atlas-mcard-dir is-${m.direction === "short" ? "sell" : "buy"}`}>{m.direction === "short" ? "SELL" : "BUY"}</span>
        <strong>{m.setup ?? m.strategy.replace(/_/g, " ")}</strong>
        <span className="atlas-mcard-cls">{CLASS_TEXT[m.class]}</span>
        {pinned && <button type="button" aria-label="Close" onClick={onClose}>×</button>}</header>
      <dl>{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {m.llm_review?.status === "ok" && <p className="atlas-mcard-why" data-llm-review>{m.llm_review.reason}{m.llm_review.sources?.length ? " · " : ""}{(m.llm_review.sources ?? []).filter((u) => u.url).slice(0, 4).map((u, i) => <a key={u.url}  className="ux-link" href={u.url ?? undefined} target="_blank" rel="noopener noreferrer">{i ? ", " : ""}{u.title || `source ${i + 1}`}</a>)}</p>}
      <p className="atlas-mcard-why">{m.why ?? m.risk_status}{m.gate_reasons?.length ? ` · ${m.gate_reasons.join("; ")}` : ""}</p>
      <p className="atlas-mcard-note">Causal values at the confirmation bar. Advisory only, execution_permission none.</p>
    </aside>
  );
}

/** Compact model status: which model, whether every validation gate passed, and when it last read a bar (Toronto). */
function ModelChip({ mp, loading, noBars }: { mp: ModelPrediction | undefined; loading: boolean; noBars?: boolean }) {
  if (!mp && noBars && !loading) return <span className="atlas-chart-badge atlas-model-chip is-none" data-gate="no_bars" title="The ATLAS feed holds no stored bars for this symbol and timeframe, so there is nothing to build features from. No prediction is drawn. Stocks, ETFs and gold need a free data key (Settings, Connectors shows the exact reason per asset).">model: no stored bars for this scope</span>;
  if (!mp) return <span className="atlas-chart-badge atlas-model-chip is-none" data-gate="loading">{loading ? "model: loading…" : "model: no read"}</span>;
  const m = mp.model;
  const arrow = mp.direction === "up" ? "▲" : mp.direction === "down" ? "▼" : "◆";
  const title = mp.status === "ok"
    ? [`Model ${m?.id ?? "?"} ${m?.version ?? ""} (${m?.calibrator ?? "uncalibrated"}, trained ${torontoStamp(m?.created_at)})`,
       `Gate: ${mp.label}${m?.gates_failed?.length ? `. Failed: ${m.gates_failed.join(", ")} (of ${m.gates_total ?? "?"})` : ""}`,
       `Last closed bar ${mp.as_of_toronto ?? "—"}; scored ${mp.computed_at_toronto ?? "—"}`,
       `P(target before stop) long ${fmt(mp.p_long, 2)} / short ${fmt(mp.p_short, 2)}; setup ${mp.setup ?? "—"}; ${m?.uses_vwap ? "uses VWAP regime features" : "trained before the VWAP features"}`,
       "Research only: execution_permission none"].join("\n")
    : `${mp.label}. ${mp.reason ?? ""}`;
  return (
    <span className={`atlas-chart-badge atlas-model-chip is-${mp.gate_status}`} data-gate={mp.gate_status} data-status={mp.status} title={title}>
      <span className="atlas-model-chip__name">{mp.status === "ok" ? (m?.id ?? "model") : "model"}</span>
      <span className="atlas-model-chip__gate">{mp.status === "ok" || mp.gate_status === "no_model" ? mp.label : `${mp.label} (${mp.status.replace(/_/g, " ")})`}</span>
      {mp.status === "ok" && <span className="atlas-model-chip__read">{arrow} {mp.direction} {typeof mp.probability === "number" ? `${Math.round(mp.probability * 100)}%` : ""}</span>}
      {mp.status === "ok" && <span className="atlas-model-chip__time">bar {torontoStamp(mp.as_of_end)}</span>}
    </span>
  );
}

/** Where a layer's own status lives in the payload. Layers that are drawn from another layer inherit that layer's status. */
function layerStatus(d: Overlays | null, id: string): Status | undefined {
  if (!d) return undefined;
  const L = d.layers as Record<string, any>;
  switch (id) {
    case "anchored_vwap": return L.anchored_vwap ?? L.vwap?.anchored ?? L.vwap;
    case "sessions": return L.sessions ?? L.vwap?.sessions ?? L.vwap;
    case "prediction_zone": return L.forward;
    case "trade_lines": case "outcomes": return L.ml_markers;
    default: return L[id];
  }
}
function isOff(d: Overlays | null, id: string): boolean { const st = layerStatus(d, id); return !!st && st.status !== "ok"; }
function layerReason(d: Overlays | null, id: string): string {
  const st = layerStatus(d, id);
  return st?.reason ?? st?.note ?? "no data for this symbol/interval";
}
function pct(v: unknown, d = 0): string { return typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : "n/a"; }
function num(v: unknown, d = 2): string { return typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "n/a"; }
function layerLine(id: NewLayerId, L: NewLayer): string {
  const a = L as Record<string, any>;
  switch (id) {
    case "conformal_bands": return `${pct(1 - (a.alpha ?? 0.2))} band for ${a.horizon_bars}-bar move: ${px(a.forward?.lower)}–${px(a.forward?.upper)}; held ${pct(a.realised_coverage_64)} of the last 64`;
    case "mtf_confluence": return `${a.bias} · score ${num(a.score, 2)} (1 = all horizons up) · ${a.n_up} of 4 horizons up`;
    case "events": return a.next ? `next: ${a.next.title} ${a.next.when}` : "no scheduled release ahead in window";
    case "market_clock": return `${a.n_open} exchange(s) open · ${a.now_local}`;
    case "cross_corr": return (a.proxies ?? []).map((q: any) => `${q.proxy} ${num(q.corr_64, 2)}`).join(" · ") || "no proxies";
    case "vol_cone": return (a.cone ?? []).map((q: any) => `${q.horizon_bars}b p${Math.round((q.percentile ?? 0) * 100)}`).join(" · ");
    case "liquidity": return `est. spread ${num(a.est_spread_bps, 1)} bps · cost ${num(a.cost_in_R, 2)}R (assumed ${a.assumed_cost_bps} bps)`;
    case "model_disagreement": return `rule experts ${pct(a.agree_frac)} agree, net vote ${num(a.net_vote, 2)}${a.learned_spread != null ? `, learned spread ${num(a.learned_spread, 2)}` : ""}`;
    case "account_size": return `${a.broker}: ideal notional ${num(a.ideal_notional, 2)} at ${pct(a.risk_fraction, 1)} risk, stop ${pct(a.stop_frac, 2)} · fits minimum: ${a.min_order_fits == null ? "n/a" : a.min_order_fits ? "yes" : "no"}`;
    case "news": {
      const it: NewsItem[] = a.items ?? [];
      const off = it.filter((x) => x.tier === 1).length, hype = it.filter((x) => x.hype_flags?.length).length;
      return `${it.length} items (${off} official filings/releases, ${it.length - off} unverified headlines)${hype ? ` · ${hype} with hype/scam flags` : ""} · AI scoring ${a.llm?.enabled ? "on" : "off"} · reviewer ${a.reviewer_mode ?? "shadow"}`;
    }
    case "drift_alert": return `${a.level}${a.triggers?.length ? `: ${a.triggers.join("; ")}` : ""}`;
    case "breadth": { const f = a.features ?? {}; return `${pct(f.br_pct_above_50)} of stored stocks above 50d, ${pct(f.br_pct_above_200)} above 200d, ${pct(f.br_adv_share_10)} advancing (10d) · ${a.tone}`; }
    case "overnight_intraday": { const f = a.features ?? {}; return `20-session overnight ${num(f.oi_on_20, 2)} vs intraday ${num(f.oi_id_20, 2)} (daily-vol units) · today's gap z ${num(f.oi_gap_z, 1)}`; }
    case "gap_stats": { const f = a.features ?? {}; return `gap ${num(f.gp_size_atr, 2)} ATR · ${f.gp_filled === 1 ? "filled" : "not filled yet"} · ${pct(f.gp_fill_rate_20)} of the last 20 filled same day`; }
    case "seasonality": { const f = a.features ?? {}; return `business day ${pct(f.sea_bdom_frac)} through the month · ${f.sea_turn_of_month === 1 ? "turn-of-month window" : "outside turn-of-month"}${f.sea_qtr_end === 1 ? " · quarter-end week" : ""}`; }
    case "implied_vol": { const f = a.features ?? {}; return `VIX ${num(a.vix, 1)} (z ${num(f.iv_vix_z_252, 1)} vs 1y) · 5-day change ${pct(f.iv_vix_chg_5, 0)} · variance gap ${num(f.iv_vrp, 1)} vol pts`; }
    case "usd_proxy": { const f = a.features ?? {}; return `EUR+CAD dollar proxy ${pct(f.usd_ret_64, 2)} over 64 bars (z ${num(f.usd_z_64, 1)}); not the DXY`; }
    case "macro_risk": return `${(a.series ?? []).map((q: any) => `${q.series} ${num(q.value, 2)}`).join(" · ")}${a.curve_inverted ? " · curve inverted" : ""} · display only, never a model input`;
  }
}
function LayersCard({ data, on }: { data: Overlays; on: Record<string, boolean> }) {
  const [open, setOpen] = useState(false);
  const ids = NEW_LAYER_IDS.filter((k) => on[k]);
  const rows = ids.map((k) => ({ k, L: data.layers[k] as NewLayer | undefined, meta: LAYERS.find((l) => l.id === k)! }));
  const ok = rows.filter((r) => r.L?.status === "ok"), off = rows.filter((r) => r.L?.status !== "ok");
  return (
    <aside className={`atlas-lcard${open ? " is-open" : ""}`} aria-label="Layer readouts" data-layer-readouts>
      <button type="button" className="atlas-lcard-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Readouts: {ok.length} ok{off.length ? ` · ${off.length} unavailable` : ""} {open ? "▾" : "▸"}
      </button>
      <div className={open ? "atlas-lcard-grid" : "atlas-lcard-peek"}>
        {(open ? ok : ok.slice(0, 2)).map(({ k, L, meta }) => <p key={k} data-layer={k} title={`${L!.reason ?? ""} ${L!.meaning ?? ""}`}><strong>{meta.label}</strong> · {layerLine(k, L!)}</p>)}
      </div>
      {open && off.length > 0 && (
        <div className="atlas-lcard-off" data-layer-unavailable>
          <h6>Unavailable here, and why</h6>
          {off.map(({ k, L, meta }) => <p key={k} data-layer={k} className="is-off"><strong>{meta.label}</strong> {L ? L.reason ?? "no reason reported" : "not returned by the server"}</p>)}
        </div>
      )}
    </aside>
  );
}

function PredictionCard({ fwd, rc, mp, dp }: { fwd: Overlays["layers"]["forward"]; rc: RunningCal | undefined; mp?: ModelPrediction; dp?: DirectionalPrediction }) {
  return (
    <aside className="atlas-pcard" aria-label="Prediction zone" tabIndex={0}>
      <h5>Prediction zone <span>{fwd?.label ?? "model estimate, not a forecast guarantee"}</span></h5>
      {mp && (mp.status === "ok"
        ? <p className={`atlas-pcard-model is-${mp.gate_status}`}><strong>{mp.direction === "up" ? "▲" : mp.direction === "down" ? "▼" : "◆"} Model: {mp.direction}</strong> · P(target before stop) {fmt(mp.probability, 2)} ({mp.setup?.replace(/_/g, " ")}, EV {fmtSigned(mp.ev_r, 2)}R) · {mp.label} · bar {torontoStamp(mp.as_of_end)}</p>
        : <p className={`atlas-pcard-model is-${mp.gate_status}`}><strong>Model: {mp.label}.</strong> {mp.reason}</p>)}
      {dp && (dp.status === "ok"
        ? <p className={`atlas-pcard-model is-${dp.label.startsWith("research") ? "research_below_gate" : "gate_passed"}`} data-directional-research>
          <strong>{dp.direction === "up" ? "▲" : dp.direction === "down" ? "▼" : "◆"} Directional research: {dp.direction}</strong> · P(up barrier first) {fmt(dp.probability, 2)} · conformal set {`{${(dp.conformal_set ?? []).map((v) => (v === 1 ? "up" : "down")).join(", ")}}`}{dp.band ? ` · ${dp.horizon_bars}-bar p10–p90 ${px(dp.band.p10)}–${px(dp.band.p90)}` : ""} · {dp.label}{dp.metrics?.n_oos ? ` · OOS n ${dp.metrics.n_oos}, AUC ${fmt(dp.metrics.auc, 2)}, Brier ${fmt(dp.metrics.brier, 3)} vs base ${fmt(dp.metrics.brier_baseline, 3)}` : ""} · bar {torontoStamp(dp.as_of_end)}</p>
        : <p className="atlas-pcard-model is-no_model" data-directional-research><strong>Directional research: {dp.label}.</strong> {dp.reason}</p>)}
      {fwd?.status === "ok" ? <>
        {fwd.active_candidates?.length
          ? <ul>{fwd.active_candidates.map((c) => <li key={c.id}>{c.direction === "short" ? "▼" : "▲"} {c.setup}: {c.p_win == null ? "rule only, no model p(win)" : `${c.calibrated ? "calibrated " : ""}p(win) ${fmt(c.p_win, 2)}`}{c.threshold != null ? ` vs ${fmt(c.threshold, 2)}` : ""}{c.ev_r != null ? ` · EV ${fmtSigned(c.ev_r, 2)}R` : ""}</li>)}</ul>
          : <p>{fwd.no_active_candidate}</p>}
        <p>{fwd.horizon_bars}-bar band p10–p90 {px(fwd.band?.p10)}–{px(fwd.band?.p90)}, median {px(fwd.band?.p50)}</p>
      </> : <p>{fwd?.reason ?? "Not enough closed bars for a band."}</p>}
      <p className="atlas-pcard-cal">{rc?.status === "ok" && rc.n
        ? `In view: ${rc.n} resolved predictions · mean p ${fmt(rc.mean_p, 2)} vs hit rate ${fmt(rc.hit_rate, 2)} · Brier ${fmt(rc.brier, 3)} (base ${fmt(rc.brier_base_rate, 3)})`
        : "No resolved predictions in view for calibration."}</p>
    </aside>
  );
}

export function AtlasMlPanel({ data, showConviction, showPredictions, onRefresh }: { data: Overlays; showConviction: boolean; showPredictions: boolean; onRefresh?: () => void }) {
  const ml = data.ml_panel;
  const ev = ml?.evolution;
  const m = ev?.metrics ?? {};
  const cm = ml?.current_model;
  const conv = data.layers.conviction;
  const cal = data.layers.predictions?.calibration;
  const preds = data.layers.predictions?.items ?? [];
  const [evolving, setEvolving] = useState(false);
  const [evolveNote, setEvolveNote] = useState<string>("");
  const [liveIntel, setLiveIntel] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/ml/evolution-intelligence?symbol=${encodeURIComponent(data.symbol)}&interval=${encodeURIComponent(data.interval)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d && typeof d === "object") setLiveIntel(d as Record<string, unknown>);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [data.symbol, data.interval]);

  const handleEvolveNow = async () => {
    setEvolving(true);
    setEvolveNote(`Running walk-forward genetic evolution on ${data.symbol} (${data.interval})…`);
    try {
      const r = await fetch(`/api/intel/evolution/run?symbol=${encodeURIComponent(data.symbol)}&interval=${encodeURIComponent(data.interval)}&generations=2`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const res = await r.json();
      const ch = res?.challenger?.oos ?? {};
      setEvolveNote(
        `Run ${res.run_id ?? "done"}: ${String(res.decision ?? "").replace(/_/g, " ")} · EV/opp ${fmtSigned(ch.ev_r_per_opportunity, 3)}R (base ${fmtSigned(ch.take_all_ev, 3)}R) · Brier ${fmt(ch.brier, 3)} · Fitness ${fmtSigned(res?.challenger?.fitness, 3)}`
      );
      onRefresh?.();
    } catch (e) {
      setEvolveNote(`Evolution run failed: ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setEvolving(false);
    }
  };

  const lp = (liveIntel?.live_prediction ?? null) as Record<string, unknown> | null;
  const lpEv = (lp?.expected_value ?? null) as Record<string, unknown> | null;
  const ph = (liveIntel?.prediction_health ?? null) as Record<string, unknown> | null;
  const evMon = (liveIntel?.ev_evolution ?? null) as Record<string, unknown> | null;

  return (
    <div className="atlas-ml-panel" aria-label="ML panel">
      <div className="atlas-ml-cell">
        <h4>Model &amp; Evolution</h4>
        <span className="atlas-chart-badge is-safe">execution_permission: {ml?.execution_permission ?? "none"}</span>
        <dl>
          <dt>Current model</dt><dd>{cm ? `${cm.version} (${cm.status})` : "none registered for this market"}</dd>
          <dt>Evolution run</dt><dd>{ev ? ev.run_id : "no run yet"}</dd>
          <dt>Decision</dt><dd>{ev ? ev.decision.replace(/_/g, " ") : "—"}</dd>
          <dt>Research hand</dt><dd>{ml?.research_hand?.genome_id ?? "not linked"} · stance {ml?.research_hand?.stance ?? "abstain"} · cannot buy or sell</dd>
          <dt>Champion</dt><dd>{ml?.champion ? String((ml.champion as { genome_id?: string }).genome_id ?? "set") : "none (strict gate has not passed)"}</dd>
        </dl>
        <div style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "4px" }}>
          <button
            type="button"
            disabled={evolving}
            onClick={() => void handleEvolveNow()}
            style={{
              padding: "5px 10px",
              borderRadius: "6px",
              border: "1px solid rgba(86, 180, 233, 0.45)",
              background: evolving ? "rgba(86, 180, 233, 0.08)" : "rgba(86, 180, 233, 0.16)",
              color: "#56B4E9",
              fontSize: "11px",
              fontWeight: 700,
              cursor: evolving ? "wait" : "pointer",
              textAlign: "left",
            }}
          >
            {evolving ? `Evolving ${data.symbol} (${data.interval})…` : `↻ Evolve Model (+EV) on ${data.symbol} ${data.interval}`}
          </button>
          {evolveNote && <p className="atlas-ml-note" style={{ margin: 0 }}>{evolveNote}</p>}
        </div>
      </div>
      <div className="atlas-ml-cell">
        <h4>Baseline vs challenger (EV &amp; Calibration)</h4>
        {ev ? (
          <table className="atlas-ml-table"><thead><tr><th /><th>Baseline</th><th>Challenger</th></tr></thead><tbody>
            <tr><th>EV / opp (R)</th><td>{fmtSigned(m.take_all_ev ?? cal?.take_all_ev)}R</td><td><strong>{fmtSigned(m.ev_r_per_opportunity ?? cal?.ev_r_per_opportunity)}R</strong></td></tr>
            <tr><th>Mean taken R</th><td>—</td><td>{fmtSigned(m.mean_r_taken ?? cal?.mean_r_taken)}R</td></tr>
            <tr><th>Brier</th><td>{fmt(m.brier_baseline)}</td><td>{fmt(m.brier)}</td></tr>
            <tr><th>Brier Skill (BSS)</th><td>0.000</td><td>{fmtSigned(m.brier_skill ?? cal?.brier_skill)}</td></tr>
            <tr><th>AUC</th><td>0.500</td><td>{fmt(m.auc)}</td></tr>
            <tr><th>ECE</th><td>—</td><td>{fmt(m.ece)}</td></tr>
            <tr><th>Fold stability</th><td>—</td><td>{fmt(m.stability ?? cal?.stability)}</td></tr>
            <tr><th>Fitness (EV+BSS)</th><td>—</td><td><strong>{fmtSigned(m.fitness ?? cal?.fitness)}</strong></td></tr>
            <tr><th>OOS n</th><td colSpan={2}>{String(m.n_oos ?? "—")} predictions, {String(m.n_taken ?? "—")} taken</td></tr>
          </tbody></table>
        ) : <p>No evolution run on this server.</p>}
        <p className="atlas-ml-note" title="EV_R = p_cal * R_win - (1 - p_cal) * 1R - cost_R. Fitness = EV_R/opp + BrierSkill + 0.1*(stability - 0.5)">
          {ev?.challenger}{m.beats_baseline === false ? " — does not beat the baseline, so it stays research only." : ""}
          {" · Formula: EV_R = p_cal·R_win − (1−p_cal)·1R − cost_R"}
        </p>
      </div>
      {showPredictions && (
        <div className="atlas-ml-cell">
          <h4>Predictions &amp; calibration</h4>
          {preds.length ? <>
            <p>{preds.length} out-of-sample predictions in view; {preds.filter((x) => x.take).length} above the take threshold.</p>
            <p>Calibration ({data.symbol} {data.interval}): Brier {fmt(cal?.brier)} vs {fmt(cal?.brier_baseline)} base rate (BSS {fmtSigned(cal?.brier_skill)}), ECE {fmt(cal?.ece)}, AUC {fmt(cal?.auc)}. Calibrator: {preds[0].calibrator || "—"}.</p>
            <p className="atlas-ml-note">EV/opp in view: {fmtSigned(cal?.ev_r_per_opportunity)}R vs take-all baseline {fmtSigned(cal?.take_all_ev)}R · Mean taken R: {fmtSigned(cal?.mean_r_taken)}R.</p>
          </> : <p>No predictions for {data.symbol} {data.interval} in the latest run.</p>}
        </div>
      )}
      {showConviction && (
        <div className="atlas-ml-cell">
          <h4>Dossier conviction</h4>
          {conv?.status === "ok" ? <>
            <p><strong>{conv.score}</strong> · {conv.label}</p>
            <ul>{(conv.components ?? []).slice(0, 5).map((c) => <li key={c.rule}>{c.rule.replace(/_/g, " ")}: {c.why}</li>)}</ul>
            <p className="atlas-ml-note">Personas: {conv.personas}</p>
          </> : <p>{conv?.reason ?? "Unavailable."}</p>}
        </div>
      )}
      {lp && (
        <div className="atlas-ml-cell">
          <h4>Live ML Prediction &amp; Health</h4>
          <p className="atlas-ml-note" style={{ marginBottom: 6 }}>
            <strong>Status:</strong> {String(lp.prediction_status ?? "—")} · <strong>Health:</strong> {String(ph?.health_classification ?? "HEALTHY")} ({fmt(ph?.inference_latency_ms as number | undefined, 1)}ms) · <strong>Market:</strong> {String(lp.market_status ?? "—")}
          </p>
          <dl>
            <dt>P(Target &lt; Stop)</dt><dd><strong>{lp.probability_target_before_stop != null ? `${(Number(lp.probability_target_before_stop) * 100).toFixed(1)}%` : "—"}</strong> (±{fmt(lp.uncertainty as number | undefined, 2)})</dd>
            <dt>P(Up / Down / Flat)</dt><dd>{lp.probability_up != null ? `${(Number(lp.probability_up) * 100).toFixed(1)}% / ${(Number(lp.probability_down) * 100).toFixed(1)}% / ${(Number(lp.probability_neutral) * 100).toFixed(1)}%` : "—"}</dd>
            <dt>Net EV after costs</dt><dd><strong>{fmtSigned(lp.expected_return_after_costs as number | undefined, 3)}R</strong> ({lpEv ? `+${fmt(lpEv.expected_gain_r as number | undefined, 2)}R / -${fmt(lpEv.expected_loss_r as number | undefined, 2)}R · cost ${fmt(lpEv.estimated_total_cost_r as number | undefined, 3)}R` : "—"})</dd>
            <dt>EV Est vs Realized</dt><dd>{evMon ? `${fmtSigned(evMon.EV_ESTIMATED_AT_SIGNAL as number | undefined, 3)}R vs ${fmtSigned(evMon.EV_REALIZED_AFTER_OUTCOME as number | undefined, 3)}R (err ${fmtSigned(evMon.EV_ESTIMATION_ERROR as number | undefined, 3)}R)` : "—"}</dd>
            <dt>Calibration</dt><dd>{String(lp.calibration_version ?? "—")}</dd>
          </dl>
        </div>
      )}
      <div className="atlas-ml-cell atlas-ml-why">
        <h4>Why each marker fired</h4>
        {ml?.why.length ? (
          <ul>{ml.why.slice().reverse().map((w) => (
            <li key={w.id}><span className="atlas-ml-dot" style={{ background: MARKER_CLASSES[w.class]?.color }} />
              {MARKER_CLASSES[w.class]?.label}: {w.strategy.replace(/_/g, " ")} {w.direction}. {w.probability}. {w.risk}{w.ev_r != null ? `. EV ${w.ev_r >= 0 ? "+" : ""}${w.ev_r.toFixed(2)}R` : ""}.</li>
          ))}</ul>
        ) : <p>No markers in view.</p>}
      </div>
    </div>
  );
}
