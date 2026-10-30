"use client";
/** Prediction health (evo-16): for every catalog asset, the last real data time, the last prediction time, the model version and
 *  the reason when there is no prediction. Predictions are research display only; they are never market data. */
import { useMemo, useState } from "react";
import { ActionButton, ActionResult, Async, Badge, Card, DataTable, StatTile, useAction, useApi, type Tone } from "../primitives";

type Cell = { interval: string; bars: number; last_real_age: string; stale: boolean; status: string; reason: string; model_version: string | null;
  last_prediction_at: number | null; direction: string | null; probability: number | null };
type Row = { instrument: string; asset_class: string; pool: string; status: string; primary_interval: string; last_real_toronto: string | null;
  last_real_age: string; eod_only: boolean; last_prediction_toronto: string | null; model_version: string | null; label: string | null; reason: string;
  intervals: Record<string, Cell> };
type Body = { as_of_toronto: string; n_assets: number; status_counts: Record<string, number>; store_present: boolean;
  pools: { pool: string; label: string; assets: number; predicted: number; with_data: number }[]; assets: Row[];
  sweep: { running: boolean; result: { done: number; ok: number; skipped: number; failed: number } | null; error: string | null } };

type HzLive = { n: number; pinball_bps: number | null; crps_q3_bps: number | null; coverage_80: number | null; hit_rate: number | null; hit_n: number };
type HzCell = { pool: string; h: string; interval: string; trained: boolean; trained_at: number | null; n_train: number | null; n_test: number | null;
  layers_with_any_data: number | null; layers_total: number | null; weights: Record<string, number>; weights_basis: string;
  gate: { applied: boolean; n: number; needs_n: number; ensemble_pinball_bps: number | null; naive_pinball_bps: number | null; rule: string };
  members: Record<string, { live: HzLive; oos: { status?: string; reason?: string; pinball_bps?: number; coverage_80?: number } | null }>; ensemble_live: HzLive };
type HzBody = { cells: HzCell[]; models: Record<string, { available: boolean; reason?: string }>; gate_rule: string; note: string };
const pctF = (v: number | null | undefined) => (v == null ? "n/a" : `${(v * 100).toFixed(0)}%`);
const TONE: Record<string, Tone> = { predicted: "good", not_yet_run: "info", no_model: "warn", no_licensed_data: "warn", not_in_pool: "warn", insufficient_history: "warn", no_data: "bad", error: "bad" };
const WORDS: Record<string, string> = { predicted: "predicted", not_yet_run: "ready, not run", no_model: "no model", no_licensed_data: "no licensed data", not_in_pool: "not in model pool",
  insufficient_history: "short history", no_data: "no data", error: "error" };

export function PredictionHealthView() {
  const s = useApi<Body>("/api/ai/predictions/coverage", 30000);
  const hz = useApi<HzBody>("/api/ai/predictions/horizons/status", 60000);
  const sweep = useAction("/api/ai/predictions/sweep?intervals=1d,1h,15m");
  const [pool, setPool] = useState("all");
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  return (
    <div className="ux-layout">
      <Card title="Prediction coverage" span="full"
        subtitle="Every catalog asset gets a prediction or an explicit reason. Predictions are research display only (no orders) and are never stored as market data.">
        <Async state={s} label="Loading coverage">
          {(d) => (
            <>
              <div className="ux-grid" style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
                <StatTile label="Catalog assets" value={String(d.n_assets)} />
                {Object.entries(d.status_counts).sort().map(([k, v]) => <StatTile key={k} label={WORDS[k] ?? k} value={String(v)} />)}
              </div>
              <DataTable rows={d.pools as unknown as Record<string, unknown>[]} caption="Coverage by asset class" columns={[
                { key: "label", label: "Class" }, { key: "assets", label: "Assets", align: "right" },
                { key: "with_data", label: "With real data", align: "right" }, { key: "predicted", label: "Predicted", align: "right" }]} />
              <p className="ux-muted">As of {d.as_of_toronto}. Sweep: {d.sweep.running ? "running…" : d.sweep.result ? `${d.sweep.result.ok} predicted, ${d.sweep.result.skipped} skipped (no model or short history), ${d.sweep.result.failed} failed` : "not run since the server started"}
                {d.sweep.error ? ` (error: ${d.sweep.error})` : ""}.</p>
              <ActionButton action={sweep} onDone={() => s.reload()}>Run prediction sweep</ActionButton>
              <ActionResult action={sweep} success="Sweep started; refresh in a minute." />
            </>
          )}
        </Async>
      </Card>
      <Card title="Multi-horizon research ensemble" span="full"
        subtitle="Next-bar return forecasts at 1m, 5m, 15m, 60m and 1d: LightGBM / XGBoost quantile models, Prophet and a no-change baseline, each with a conformal 80% band. Weights follow each model's rolling live pinball loss. Research only; execution_permission none.">
        <Async state={hz} label="Loading ensemble scores">
          {(d) => <HorizonPanel d={d} />}
        </Async>
      </Card>
      <Card title="Every asset" span="full" subtitle="Last real data is the end of the newest stored bar. Last prediction is when the research model last scored this asset.">
        <Async state={s} label="Loading assets">
          {(d) => <AssetTable rows={d.assets} pools={d.pools} pool={pool} setPool={setPool} status={status} setStatus={setStatus} q={q} setQ={setQ} />}
        </Async>
      </Card>
    </div>
  );
}

function AssetTable({ rows, pools, pool, setPool, status, setStatus, q, setQ }: { rows: Row[]; pools: Body["pools"]; pool: string; setPool: (v: string) => void;
  status: string; setStatus: (v: string) => void; q: string; setQ: (v: string) => void }) {
  const shown = useMemo(() => rows.filter((r) => (pool === "all" || r.pool === pool) && (status === "all" || r.status === status)
    && (!q || r.instrument.toLowerCase().includes(q.toLowerCase()))), [rows, pool, status, q]);
  return (
    <>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        <select aria-label="Asset class" value={pool} onChange={(e) => setPool(e.target.value)}>
          <option value="all">All classes</option>{pools.map((p) => <option key={p.pool} value={p.pool}>{p.label}</option>)}
        </select>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">All statuses</option>{Object.keys(WORDS).map((k) => <option key={k} value={k}>{WORDS[k]}</option>)}
        </select>
        <input aria-label="Filter symbol" placeholder="Filter symbol" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="ux-muted">{shown.length} of {rows.length}</span>
      </div>
      <DataTable maxHeight={560} caption="Prediction coverage per asset" rows={shown as unknown as Record<string, unknown>[]} columns={[
        { key: "instrument", label: "Asset", render: (r) => <><strong>{String(r.instrument)}</strong> <span className="ux-muted">{String(r.asset_class)}</span></> },
        { key: "status", label: "Status", render: (r) => <Badge tone={TONE[String(r.status)] ?? "neutral"}>{WORDS[String(r.status)] ?? String(r.status)}</Badge> },
        { key: "last_real_toronto", label: "Last real data", render: (r) => r.last_real_toronto ? <>{String(r.last_real_toronto)} <span className="ux-muted">({String(r.last_real_age)} ago{r.eod_only ? ", end-of-day only" : ""})</span></> : <span className="ux-muted">none stored</span> },
        { key: "last_prediction_toronto", label: "Last prediction", render: (r) => r.last_prediction_toronto ? String(r.last_prediction_toronto) : <span className="ux-muted">never</span> },
        { key: "model_version", label: "Model version", render: (r) => r.model_version ? <><code className="ux-code">{String(r.model_version)}</code>{String(r.model_version).endsWith("+transfer") ? <> <Badge tone="warn">transfer</Badge></> : null}</> : <span className="ux-muted">none</span> },
        { key: "reason", label: "Reason / label", render: (r) => r.reason ? String(r.reason) : <span className="ux-muted">{String(r.label ?? "")}</span> }]} />
    </>
  );
}

const MODEL_ORDER = ["lgbm", "xgb", "prophet", "naive"];

function HorizonPanel({ d }: { d: HzBody }) {
  const [pool, setPool] = useState("all");
  const pools = Array.from(new Set(d.cells.map((c) => c.pool)));
  const rows = d.cells.filter((c) => pool === "all" || c.pool === pool);
  return (
    <>
      <p className="ux-muted">
        Models on this host: {MODEL_ORDER.map((m) => `${m} ${d.models[m]?.available ? "available" : `unavailable (${d.models[m]?.reason ?? "n/a"})`}`).join("; ")}. {d.gate_rule}. {d.note}
      </p>
      <select aria-label="Ensemble pool" value={pool} onChange={(e) => setPool(e.target.value)}>
        <option value="all">All pools</option>{pools.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      <DataTable maxHeight={520} caption="Ensemble weights and per-model live scores (pinball and CRPS in bps of return, coverage of the 80% band, direction hit rate)"
        rows={rows as unknown as Record<string, unknown>[]} columns={[
          { key: "pool", label: "Pool / horizon", render: (r) => <><strong>{String(r.pool)}</strong> {String(r.h)} {r.trained ? null : <Badge tone="warn">no trained model</Badge>}</> },
          { key: "weights", label: "Weights", render: (r) => <>{Object.entries(r.weights as Record<string, number>).map(([m, w]) => `${m} ${Math.round(w * 100)}%`).join(" · ")} <span className="ux-muted">({String(r.weights_basis)})</span></> },
          ...MODEL_ORDER.map((m) => ({ key: m, label: `${m} live`, render: (r: Record<string, unknown>) => {
            const x = (r.members as HzCell["members"])[m]?.live;
            return !x || !x.n ? <span className="ux-muted">{m === "prophet" ? "unavailable" : "no scores"}</span>
              : <span title={`n=${x.n}; CRPS(3-quantile approx) ${x.crps_q3_bps} bps`}>{x.pinball_bps} bps · cov {pctF(x.coverage_80)} · hit {pctF(x.hit_rate)} · n={x.n}</span>;
          } })),
          { key: "gate", label: "Moves dashed line?", render: (r) => { const g = r.gate as HzCell["gate"]; return g.applied ? <Badge tone="good">yes (gate passed)</Badge> : <span className="ux-muted">no · {g.n}/{g.needs_n} live scores</span>; } },
        ]} />
    </>
  );
}
