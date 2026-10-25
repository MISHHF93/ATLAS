"use client";
/** Opportunity marker types shared by AtlasChart (the one ATLAS chart). Markers come from /api/ai/chart/overlays
 *  (unified candidate engine + gate, and the evolution loop's out-of-sample predictions). They sit on the
 *  confirmation bar only, at real timestamps and real entry prices. Research signal, paper only, not advice.
 *  Alt bar types are display only: fills and P&L always use real time bars, drawn when each alt bar completed. */
import type { UTCTimestamp } from "lightweight-charts";

export type OppMarker = { id: string; source: string; strategy: string; direction: string; time: number; detected_at: number; price: number;
  stop: number; target: number; probability: number | null; probability_label: string; uncertainty: string | null; ev_r: number | null;
  model_version: string; risk_status: string; class: "ml_suggested" | "ml_skip" | "rule_only" | "risk_rejected"; outcome: string; r: number | null;
  /** chart-2 marker_details layer: causal values at the confirmation bar (server computed, closed bars only). */
  indicators?: { bar_time: number; close: number; rsi: number | null; adx: number | null; atr: number | null; macd_hist: number | null;
    vwap: number | null; vwap_dist_atr: number | null; vwap_dist_pct: number | null; regime: string | null };
  threshold?: number | null; outcome_label?: string; why?: string; setup?: string; zone_touched?: string | null; gate_reasons?: string[];
  filled_at?: number | null; exit_at?: number | null; exit_price?: number | null; resolution_path?: { time: number; value: number; exit?: boolean }[] };
export const MARKER_CLASSES: Record<OppMarker["class"], { label: string; color: string; shape: "arrowUp" | "circle" | "square" }> = {
  ml_suggested: { label: "ML take (out-of-sample)", color: "#0072B2", shape: "arrowUp" },
  ml_skip: { label: "ML skip (out-of-sample)", color: "#666666", shape: "square" },
  rule_only: { label: "Rule setup, no model verdict", color: "#E69F00", shape: "arrowUp" },
  risk_rejected: { label: "Gate rejected (geometry/costs)", color: "#999999", shape: "circle" },
};
export type AltBar = { start: number; completed_at: number; open: number; high: number; low: number; close: number };
export function altToCandles(alt: AltBar[], dur: number) {
  const out: { time: UTCTimestamp; open: number; high: number; low: number; close: number }[] = [];
  for (const a of alt) {
    const t = (a.completed_at - dur) as UTCTimestamp;
    const last = out[out.length - 1];
    if (last && last.time === t) { last.high = Math.max(last.high, a.high); last.low = Math.min(last.low, a.low); last.close = a.close; }
    else if (!last || t > last.time) out.push({ time: t, open: a.open, high: a.high, low: a.low, close: a.close });
  }
  return out;
}
