"use client";
/** Opportunity markers + display bar types shared by the Levels chart and the main trade chart.
 *  Markers come from /api/intel/markers (unified candidate engine + gate, and the evolution loop's out-of-sample
 *  predictions). They sit on the confirmation bar only, at real timestamps and real entry prices. Research signal,
 *  paper only, not advice. Alt bar types come from /api/intel/bars_alt and are display only: fills and P&L always
 *  use real time bars, and each alt bar is drawn at the time it completed. */
import { useEffect, useState } from "react";
import type { IChartApi, SeriesMarker, UTCTimestamp } from "lightweight-charts";

export type OppMarker = { id: string; source: string; strategy: string; direction: string; time: number; detected_at: number; price: number;
  stop: number; target: number; probability: number | null; probability_label: string; uncertainty: string | null; ev_r: number | null;
  model_version: string; risk_status: string; class: "ml_suggested" | "ml_skip" | "rule_only" | "risk_rejected"; outcome: string; r: number | null };
export type MarkerPayload = { status: string; markers: OppMarker[]; counts?: Record<string, number>;
  classes?: Record<string, { count: number; applicable: boolean; note: string }>; disclaimer: string;
  evolution?: { run_id: string; genome: string; no_model_beats_baseline: boolean } | null };

export const MARKER_CLASSES: Record<OppMarker["class"], { label: string; color: string; shape: "arrowUp" | "circle" | "square" }> = {
  ml_suggested: { label: "ML take (out-of-sample)", color: "#0072B2", shape: "arrowUp" },
  ml_skip: { label: "ML skip (out-of-sample)", color: "#666666", shape: "square" },
  rule_only: { label: "Rule setup, no model verdict", color: "#E69F00", shape: "arrowUp" },
  risk_rejected: { label: "Gate rejected (geometry/costs)", color: "#999999", shape: "circle" },
};
export const DISPLAY_TYPES = [
  { id: "candles", label: "Candles" }, { id: "heikin_ashi", label: "Heikin-Ashi" }, { id: "renko_atr", label: "Renko (ATR)" },
  { id: "range_atr", label: "Range (ATR)" }, { id: "kagi_atr", label: "Kagi (ATR)" }, { id: "pnf_atr", label: "Point & Figure (ATR, 3-box)" },
  { id: "volume", label: "Volume bars" },
] as const;
export type DisplayType = (typeof DISPLAY_TYPES)[number]["id"];

export function useMarkers(symbol: string, tf: string, enabled: boolean) {
  const [d, setD] = useState<MarkerPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || !symbol) { setD(null); return; }
    let alive = true;
    setErr(null);
    fetch(`/api/intel/markers?symbol=${encodeURIComponent(symbol)}&tf=${tf}&limit=600`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p: MarkerPayload) => { if (alive) setD(p); }).catch((e: Error) => { if (alive) { setD(null); setErr(e.message); } });
    return () => { alive = false; };
  }, [symbol, tf, enabled]);
  return { data: d, error: err };
}

export type AltBar = { start: number; completed_at: number; open: number; high: number; low: number; close: number };
export function useAltBars(symbol: string, tf: string, kind: DisplayType) {
  const [d, setD] = useState<{ status: string; bars: AltBar[]; reason?: string } | null>(null);
  useEffect(() => {
    if (kind === "candles" || !symbol) { setD(null); return; }
    let alive = true;
    fetch(`/api/intel/bars_alt?symbol=${encodeURIComponent(symbol)}&tf=${tf}&kind=${kind}&limit=3000`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p) => { if (alive) setD(p); }).catch(() => { if (alive) setD({ status: "unavailable", bars: [], reason: "request failed" }); });
    return () => { alive = false; };
  }, [symbol, tf, kind]);
  return d;
}

/** Alt bars -> candle points on the REAL time axis: each bar sits on the source bar during which it completed
 *  (completed_at - dur). Several bricks completing in one source bar are merged into one candle for display. */
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

export function toSeriesMarkers(ms: OppMarker[], times: Set<number>, show: Record<string, boolean>): SeriesMarker<UTCTimestamp>[] {
  return ms.filter((m) => show[m.class] !== false && times.has(m.time)).sort((a, b) => a.time - b.time).map((m) => {
    const c = MARKER_CLASSES[m.class];
    const short = m.direction === "short";
    const shape = c.shape === "arrowUp" ? (short ? "arrowDown" : "arrowUp") : c.shape;
    const tag = m.class === "ml_suggested" ? "ML " : m.class === "risk_rejected" ? "✕ " : "";
    return { time: m.time as UTCTimestamp, position: short ? "aboveBar" : "belowBar", shape, color: c.color,
      text: `${tag}${short ? "S" : "B"}`, id: m.id } as SeriesMarker<UTCTimestamp>;
  });
}

const fmt = (v: number | null | undefined, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "—");

/** Hover tooltip: subscribes to the chart crosshair and shows every marker on the hovered bar. */
export function attachMarkerTooltip(chart: IChartApi, el: HTMLElement, getMarkers: () => OppMarker[]) {
  const tip = document.createElement("div");
  tip.className = "ux-chart-tip";
  tip.setAttribute("role", "tooltip");
  tip.style.cssText = "position:absolute;z-index:5;pointer-events:none;display:none;max-width:320px;padding:8px;border-radius:6px;background:#111827;color:#E5E7EB;border:1px solid #374151;font-size:12px;line-height:1.35;white-space:normal";
  if (getComputedStyle(el).position === "static") el.style.position = "relative";
  el.appendChild(tip);
  const h = (p: { time?: unknown; point?: { x: number; y: number } }) => {
    const hit = p.time !== undefined ? getMarkers().filter((m) => m.time === p.time) : [];
    if (!hit.length || !p.point) { tip.style.display = "none"; return; }
    tip.innerHTML = "";
    for (const m of hit.slice(0, 3)) {
      const row = document.createElement("div");
      row.style.marginBottom = "6px";
      const lines = [
        `${m.strategy.replaceAll("_", " ")} · ${m.direction === "short" ? "sell" : "buy"} @ ${fmt(m.price, 2)} (${MARKER_CLASSES[m.class].label})`,
        `Probability: ${m.probability_label}${m.uncertainty ? ` · ${m.uncertainty}` : ""}`,
        `EV after costs: ${m.ev_r === null ? "not computed (no calibrated probability)" : `${fmt(m.ev_r, 3)} R`}`,
        `Model: ${m.model_version}`,
        `Risk: ${m.risk_status}`,
        `Outcome: ${m.outcome}${m.r !== null ? ` (${fmt(m.r, 2)} R)` : ""} · stop ${fmt(m.stop)} · target ${fmt(m.target)}`,
      ];
      for (const l of lines) { const d = document.createElement("div"); d.textContent = l; row.appendChild(d); }
      tip.appendChild(row);
    }
    const foot = document.createElement("div");
    foot.style.cssText = "color:#9CA3AF;font-style:italic";
    foot.textContent = "Research signal, paper only, not advice.";
    tip.appendChild(foot);
    tip.style.display = "block";
    const x = Math.min(Math.max(0, p.point.x + 12), Math.max(0, el.clientWidth - 330));
    tip.style.left = `${x}px`;
    tip.style.top = `${Math.max(0, p.point.y - 20)}px`;
  };
  chart.subscribeCrosshairMove(h as never);
  return () => { chart.unsubscribeCrosshairMove(h as never); tip.remove(); };
}

export function MarkerControls({ on, setOn, show, setShow, payload, error, display, setDisplay, altStatus }: {
  on: boolean; setOn: (v: boolean) => void; show: Record<string, boolean>; setShow: (v: Record<string, boolean>) => void;
  payload: MarkerPayload | null; error: string | null; display?: DisplayType; setDisplay?: (d: DisplayType) => void; altStatus?: string | null }) {
  return (
    <div className="ux-form-row" style={{ flexWrap: "wrap", gap: 8 }}>
      {setDisplay ? (
        <label className="ux-field" data-size="sm"><span>Bar type</span>
          <select value={display} onChange={(e) => setDisplay(e.target.value as DisplayType)} aria-label="Display bar type">
            {DISPLAY_TYPES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
      ) : null}
      <fieldset className="ux-chips"><legend className="ux-muted">Opportunity markers</legend>
        <label className="ux-chip"><input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} /> Show markers</label>
        {on ? (Object.keys(MARKER_CLASSES) as OppMarker["class"][]).map((k) => {
          const c = payload?.classes?.[k];
          const na = c ? !c.applicable : false;
          const n = c ? c.count : payload?.counts?.[k];
          return (
            <label key={k} className="ux-chip" title={c?.note} style={na ? { opacity: 0.6 } : undefined}>
              <input type="checkbox" disabled={na} checked={!na && show[k] !== false} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
              <span className="ux-swatch" style={{ background: MARKER_CLASSES[k].color }} aria-hidden /> {MARKER_CLASSES[k].label} ({na ? "n/a" : n ?? "…"})</label>
          );
        }) : null}
      </fieldset>
      {on ? <p className="ux-muted" style={{ fontSize: 12, margin: 0 }}>
        Research signal, paper only, not advice. Markers sit on the bar that confirmed the setup; past markers show their real outcome.
        {payload?.evolution?.no_model_beats_baseline ? " ML markers come from the best evolution genome, which does not beat the baseline." : ""}
        {error ? ` Markers unavailable: ${error}.` : !payload ? " Loading markers (the first load can take up to a minute)…" : ""}
        {altStatus ? ` ${altStatus}` : ""}
      </p> : null}
    </div>
  );
}
