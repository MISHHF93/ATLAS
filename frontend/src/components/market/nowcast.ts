/** evo-16 M4: the prediction service's nowcast for one asset/timeframe. Always a forecast, never market data. */
"use client";
import { useEffect, useState } from "react";

export type NcPoint = { t: number; t_end: number; mid: number; lo: number; hi: number; k: number; forming?: boolean };
export type HzLive = { n: number; pinball_bps: number | null; crps_q3_bps: number | null; coverage_80: number | null; hit_rate: number | null; hit_n: number };
export type HzRow = { h: string; interval: string; status: string; reason?: string; applied?: boolean; label?: string; transfer?: { kind: string; note: string } | null;
  median?: number; lo?: number; hi?: number; base_px?: number; target_end?: number; weights?: { weights: Record<string, number>; basis: string };
  live?: { asset: HzLive; pool: HzLive }; gate?: { applied: boolean; rule: string; n: number; needs_n: number }; members?: Record<string, unknown> };
export type Horizons = { status?: string; reason?: string; horizons?: HzRow[]; label?: string; execution_permission?: string; note?: string;
  models?: Record<string, { available: boolean; reason?: string }> };
export type Nowcast = {
  horizons?: Horizons; ensemble_applied?: string[];
  status: string; label: string; reason?: string; mode?: "live" | "end_of_day"; interval: string; symbol: string; computed_at?: number; level?: number;
  anchor?: { t: number; price: number; source: string; provider?: string | null; age_s: number; age_toronto?: string };
  base_interval?: string;
  proxy_candidate?: { instrument: string; status: string; label: string; note: string } | null;
  path?: NcPoint[]; now?: NcPoint | null; inputs?: { input: string; detail?: string }[]; execution_permission?: string;
};

export const NOWCAST_LABEL = "Predicted (not market data)";

/** Polls /api/ai/predictions/nowcast (the service caches it for 10 s; the chart asks every 20 s). */
export function useNowcast(symbol: string, interval: string, enabled = true): Nowcast | null {
  const [nc, setNc] = useState<Nowcast | null>(null);
  useEffect(() => {
    setNc(null);
    if (!enabled || !symbol) return;
    let alive = true;
    const pull = () => fetch(`/api/ai/predictions/nowcast?symbol=${encodeURIComponent(symbol)}&interval=${interval}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null)).then((j: Nowcast | null) => { if (alive && j) setNc(j); }).catch(() => { /* keep the last forecast; the age label shows how old the real data is */ });
    pull();
    const t = window.setInterval(pull, 20_000);
    return () => { alive = false; window.clearInterval(t); };
  }, [symbol, interval, enabled]);
  return nc;
}

export function ageText(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "unknown";
  const a = Math.max(0, Math.round(s));
  return a < 120 ? `${a}s` : a < 7200 ? `${Math.round(a / 60)}m` : a < 172800 ? `${Math.round(a / 3600)}h` : `${Math.round(a / 86400)}d`;
}
