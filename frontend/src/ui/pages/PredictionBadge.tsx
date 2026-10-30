"use client";
/** evo-16 M4: one prediction service, three readers. The chart header, the News reviewer and the go-live panel all read /api/ai/predictions/*.
 *  Everything shown here is a forecast: never market data, never an order. */
import { Async, Badge, useApi, type Tone } from "../primitives";

type Asset = {
  symbol: string; label: string; execution_permission: string;
  coverage: { status: string; reason: string; pool: string; model_version: string | null; label: string | null; last_real_toronto: string | null; last_real_age: string;
    last_prediction_toronto: string | null; eod_only: boolean; primary_interval: string };
  nowcast: { status: string; interval: string; mode?: string; reason?: string; anchor?: { age_s: number; price: number; source: string };
    now?: { mid: number; lo: number; hi: number } | null };
  calibration: { n_scored: number; coverage_80: number | null; target: number };
};
const TONE: Record<string, Tone> = { predicted: "good", not_yet_run: "info", no_model: "warn", insufficient_history: "warn", no_data: "bad", error: "bad" };
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);
const num = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(2) : v.toPrecision(5));

/** Compact status line for one symbol (used by the News reviewer). */
export function PredictionBadge({ symbol }: { symbol: string }) {
  const s = useApi<Asset>(symbol ? `/api/ai/predictions/asset?symbol=${encodeURIComponent(symbol)}` : null, 30000);
  if (!symbol) return null;
  return (
    <div data-testid="prediction-badge" className="ux-small">
      <Async state={s} label="Reading the prediction service">
        {(d) => {
          const c = d.coverage, n = d.nowcast;
          return (
            <p>
              Prediction service for {d.symbol}: <Badge tone={TONE[c.status] ?? "neutral"}>{c.status.replace(/_/g, " ")}</Badge>{" "}
              {c.label ? <span>{c.label}{c.model_version ? ` · ${c.model_version}` : ""}</span> : <span>{c.reason}</span>}
              {" · "}last real data {c.last_real_toronto ?? "none"} ({c.last_real_age} ago){c.eod_only ? ", end-of-day source" : ""}
              {n.status === "ok" && n.now ? <> · predicted now {num(n.now.mid)} (80% band {num(n.now.lo)}–{num(n.now.hi)}), <em>Predicted, not market data</em></> : n.reason ? <> · nowcast: {n.reason}</> : null}
            </p>
          );
        }}
      </Async>
    </div>
  );
}

/** Go-live panel line: how many catalog assets have a prediction and how well the nowcast has been calibrated live so far. */
export function PredictionReadinessLine() {
  const cov = useApi<{ n_assets: number; status_counts: Record<string, number> }>("/api/ai/predictions/coverage", 60000);
  const cal = useApi<{ n_scored: number; n_issued: number; coverage_80: number | null; target: number }>("/api/ai/predictions/nowcast/calibration", 60000);
  return (
    <div data-testid="golive-predictions" className="ux-small">
      <Async state={cov} label="Reading prediction coverage">
        {(d) => (
          <p>
            Prediction service: {d.status_counts.predicted ?? 0} of {d.n_assets} catalog assets predicted; the rest carry an explicit reason (Research, Lab, Predictions tab).
            {" "}Nowcast live calibration: {cal.data ? (cal.data.n_scored ? `${cal.data.n_scored} scored, 80% band covered ${pct(cal.data.coverage_80)} (target 80%)` : `${cal.data.n_issued} issued, none scored yet`) : "loading"}.
            {" "}All models are research / below gate; nothing here enables trading.
          </p>
        )}
      </Async>
    </div>
  );
}
