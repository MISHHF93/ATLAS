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

const TONE: Record<string, Tone> = { predicted: "good", not_yet_run: "info", no_model: "warn", not_in_pool: "warn", insufficient_history: "warn", no_data: "bad", error: "bad" };
const WORDS: Record<string, string> = { predicted: "predicted", not_yet_run: "ready, not run", no_model: "no model", not_in_pool: "not in model pool",
  insufficient_history: "short history", no_data: "no data", error: "error" };

export function PredictionHealthView() {
  const s = useApi<Body>("/api/ai/predictions/coverage", 30000);
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
        { key: "model_version", label: "Model version", render: (r) => r.model_version ? <code className="ux-code">{String(r.model_version)}</code> : <span className="ux-muted">none</span> },
        { key: "reason", label: "Reason / label", render: (r) => r.reason ? String(r.reason) : <span className="ux-muted">{String(r.label ?? "")}</span> }]} />
    </>
  );
}
