"use client";

import { useEffect, useState } from "react";

type Setup = { detector?: string; direction?: string; entry?: number | null; stop?: number | null; target?: number | null; risk_bps?: number | null; cost_bps?: number | null };
type Sig = {
  instrument: string; asset_class: string; provider: string; action: string; model_status: string; decision_t?: number | null;
  p_win_after_cost?: number | null; ev_r?: number | null; conformal_take?: boolean | null; reasons?: string[]; setup?: Setup | null;
  data?: { age_s?: number };
};
type Payload = {
  label?: string; execution_permission?: string; mode?: string; latest?: Sig[]; latest_at?: number | null;
  models?: Array<{ model_key: string; asset_class: string; status?: string; failed_gates?: string[]; hold_bars?: number }>;
  tick?: { state?: string; pid?: number; command?: string; last_tick_at?: number; ticks?: number; note?: string };
  shadow?: { n_logged?: number; n_setups?: number; n_resolved?: number; shadow_weeks?: number; brier?: number; brier_baseline?: number; mean_r_taken?: number | null; n_taken_resolved?: number };
  note?: string;
};

const fmt = (v?: number | null, d = 3) => typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-US", { maximumFractionDigits: d }) : "n/a";
const when = (s?: number | null) => typeof s === "number" ? new Date(s * 1000).toLocaleString() : "n/a";

export function Signal15Panel() {
  const [body, setBody] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let closed = false;
    const pull = async () => {
      const request = new AbortController();
      const timeout = window.setTimeout(() => request.abort(), 10000);
      try {
        const response = await fetch("/api/ml/v1/signals", { cache: "no-store", signal: request.signal });
        if (!response.ok) throw new Error(`Signals returned HTTP ${response.status}.`);
        const json = await response.json() as Payload;
        if (!closed) { setBody(json); setError(""); }
      } catch (cause) {
        if (!closed) setError(cause instanceof Error ? cause.message : "Signals are unavailable.");
      } finally {
        window.clearTimeout(timeout);
      }
    };
    void pull();
    const timer = window.setInterval(pull, 60000);
    return () => { closed = true; window.clearInterval(timer); };
  }, []);

  const sh = body?.shadow;
  return <section className="clean-card" aria-label="15 minute predicted signals">
    <div className="clean-card-header">
      <div>
        <h2 className="clean-card-title">15-minute signals</h2>
        <p className="clean-card-subtitle"><strong>Predicted signal, not advice.</strong> Paper and shadow only. Execution permission: {body?.execution_permission ?? "none"}. HOLD is the default; BUY or SELL is only a model flag on a real closed 15-minute bar.</p>
      </div>
      <span className="badge">{error ? "Unavailable" : body ? `Tick: ${(body.tick?.state ?? "never_run").replaceAll("_", " ")}` : "Loading"}</span>
    </div>
    {error ? <p role="status" className="model-flow-warning">{error}</p> : null}
    {body?.tick?.state === "stale" ? <p role="status" className="model-flow-warning">{body.tick.note}</p> : null}
    {body?.models?.length ? <p className="clean-card-subtitle" style={{ margin: "8px 0" }}>
      Models: {body.models.map(m => `${m.model_key} ${m.status ?? "unknown"}${m.failed_gates?.length ? ` (failed: ${m.failed_gates.join(", ")})` : ""}`).join(" / ")}. A model needs every pre-declared gate, including 4 shadow weeks, before it counts.
    </p> : null}
    {sh ? <p className="clean-card-subtitle" style={{ margin: "8px 0" }}>
      Shadow log: {fmt(sh.n_logged, 0)} decision bars / {fmt(sh.n_setups, 0)} setups / {fmt(sh.n_resolved, 0)} resolved against real bars / {fmt(sh.shadow_weeks, 2)} weeks.
      {sh.brier != null ? ` Brier ${fmt(sh.brier, 4)} vs base-rate ${fmt(sh.brier_baseline, 4)}.` : ""}
      {sh.mean_r_taken != null ? ` Mean R of flagged setups ${fmt(sh.mean_r_taken, 3)} over ${fmt(sh.n_taken_resolved, 0)}.` : ""}
    </p> : null}
    <div style={{ maxWidth: "100%", overflowX: "auto" }} tabIndex={0} role="region" aria-label="Latest predicted signals">
      <table className="clean-table" style={{ minWidth: 820 }}>
        <thead><tr><th>Instrument</th><th>Predicted flag</th><th>P(win after cost)</th><th>EV (R)</th><th>Setup</th><th>Why / data</th></tr></thead>
        <tbody>{body?.latest?.length ? body.latest.map(s => <tr key={`${s.asset_class}-${s.instrument}`}>
          <td><strong>{s.instrument}</strong><div className="clean-card-subtitle">{s.provider} / {s.model_status.replaceAll("_", " ")}</div></td>
          <td><strong>{s.action}</strong><div className="clean-card-subtitle">predicted</div></td>
          <td>{fmt(s.p_win_after_cost)}</td>
          <td>{fmt(s.ev_r)}</td>
          <td>{s.setup ? `${s.setup.detector} ${s.setup.direction}, risk ${fmt(s.setup.risk_bps, 1)} bp, cost ${fmt(s.setup.cost_bps, 1)} bp` : "no setup"}</td>
          <td>{(s.reasons ?? []).join("; ") || "ok"}{s.decision_t ? <div className="clean-card-subtitle">bar end {when(s.decision_t)}</div> : null}</td>
        </tr>) : <tr><td colSpan={6}>{body ? "No tick has produced signals yet." : "Loading."}</td></tr>}</tbody>
      </table>
    </div>
    <p className="clean-card-subtitle" style={{ margin: "12px 0 0" }}>{body?.note ?? "Predicted from real closed bars only."} Stocks arrive T+1, so their rows are usually HOLD for stale data. Last tick {when(body?.tick?.last_tick_at)}; scored {when(body?.latest_at)}.</p>
  </section>;
}
