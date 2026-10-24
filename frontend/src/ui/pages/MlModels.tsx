"use client";
/** Meta-label models: registry with gate results, OOS metrics, calibration plot, drift, shadow and cited explanations.
 *  Read-only. Nothing here trains, promotes or trades; a model reaches the autopilot only if every gate passes. */
import { useState } from "react";
import { Async, Badge, Card, Command, DataTable, EmptyState, useApi } from "../primitives";

type Summary = { version: string; group: string; status: string; created_at: string; n_oos?: number; brier_skill?: number; auc?: number;
  ece?: number; n_taken?: number; mean_r_taken?: number | null; dsr?: number; pbo?: number | null; failed_gates: string[] };
type Gate = { gate: string; passed: boolean; value: unknown; threshold: string };
type Rel = { bin_lo: number; bin_hi: number; mean_p: number | null; hit_rate: number | null; n: number };
type Manifest = { version: string; status: string; gates: Gate[]; data_hash: string; code_sha: string; features: string[];
  metrics: { reliability?: Rel[]; per_instrument?: Record<string, Record<string, Record<string, unknown>>>; take_all?: Record<string, number>;
    variants?: Record<string, Record<string, unknown>> } };
type Drift = { psi: { status: string; max_psi: number | null; features: { feature: string; psi: number; level: string }[] };
  adwin_brier?: { drift: boolean; detections: number[]; n: number }; adwin_hit?: { drift: boolean; detections: number[]; n: number } };
type Cite = { cite: string; heading: string; snippet: string; score: number };

const f = (v: unknown, d = 3) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : v === null || v === undefined ? "—" : String(v));

function CalibrationPlot({ bins }: { bins: Rel[] }) {
  const S = 220, P = 28, sc = (v: number) => P + v * (S - 2 * P), y = (v: number) => S - sc(v);
  const pts = bins.filter((b) => b.n > 0 && b.mean_p !== null && b.hit_rate !== null);
  const maxN = Math.max(1, ...pts.map((b) => b.n));
  return (
    <svg width={S} height={S} role="img" aria-label="Reliability diagram: predicted probability versus observed hit rate">
      <rect x={P} y={P} width={S - 2 * P} height={S - 2 * P} fill="none" stroke="currentColor" opacity={0.25} />
      <line x1={sc(0)} y1={y(0)} x2={sc(1)} y2={y(1)} stroke="currentColor" strokeDasharray="4 3" opacity={0.5} />
      <polyline fill="none" stroke="var(--c-accent)" strokeWidth={2} points={pts.map((b) => `${sc(b.mean_p!)},${y(b.hit_rate!)}`).join(" ")} />
      {pts.map((b, i) => <circle key={i} cx={sc(b.mean_p!)} cy={y(b.hit_rate!)} r={2 + 5 * Math.sqrt(b.n / maxN)} fill="var(--c-accent)" opacity={0.7}>
        <title>{`p≈${f(b.mean_p, 2)} hit ${f(b.hit_rate, 2)} n=${b.n}`}</title></circle>)}
      <text x={S / 2} y={S - 6} fontSize={10} textAnchor="middle" fill="currentColor">predicted p</text>
      <text x={10} y={S / 2} fontSize={10} textAnchor="middle" fill="currentColor" transform={`rotate(-90 10 ${S / 2})`}>observed</text>
    </svg>
  );
}

function Detail({ version }: { version: string }) {
  const m = useApi<Manifest>(`/api/ml/models/${encodeURIComponent(version)}`, 600000);
  const d = useApi<Drift>(`/api/ml/models/${encodeURIComponent(version)}/drift`, 600000);
  const e = useApi<{ summary: string; citations: Cite[] }>(`/api/ml/explain?version=${encodeURIComponent(version)}`, 600000);
  return (
    <>
      <Card title="Gates" subtitle="Pre-declared before training. Eligible only if every row passes." span={2}>
        <Async state={m} label="Loading gates">
          {(x) => <DataTable rows={x.gates as unknown as Record<string, unknown>[]} columns={[
            { key: "gate", label: "Gate" }, { key: "passed", label: "Result", render: (r) => <Badge tone={r.passed ? "good" : "bad"}>{r.passed ? "pass" : "fail"}</Badge> },
            { key: "value", label: "Value", align: "right", render: (r) => Array.isArray(r.value) ? r.value.map((v) => f(v, 4)).join(" vs ") : f(r.value, 4) },
            { key: "threshold", label: "Needs" }]} />}
        </Async>
      </Card>
      <Card title="Calibration (OOS)" subtitle="Dashed line = perfect calibration; dot size = sample count.">
        <Async state={m} label="Loading calibration">{(x) => x.metrics.reliability?.length ? <CalibrationPlot bins={x.metrics.reliability} /> : <EmptyState title="No OOS bins" />}</Async>
      </Card>
      <Card title="Per instrument (OOS, after costs)" span="full">
        <Async state={m} label="Loading instruments">
          {(x) => <DataTable rows={Object.entries(x.metrics.per_instrument ?? {}).map(([inst, v]) => ({ inst, ...(v.hgb_conformal ?? {}) })) as Record<string, unknown>[]} columns={[
            { key: "inst", label: "Instrument" }, { key: "n_oos", label: "OOS setups", align: "right" },
            { key: "brier_skill", label: "Brier skill", align: "right", render: (r) => f(r.brier_skill, 4) }, { key: "auc", label: "AUC", align: "right", render: (r) => f(r.auc) },
            { key: "n_taken", label: "Taken", align: "right" }, { key: "mean_r_taken", label: "Mean R taken", align: "right", render: (r) => f(r.mean_r_taken) },
            { key: "mean_r_all", label: "Mean R all", align: "right", render: (r) => f(r.mean_r_all) }]} />}
        </Async>
      </Card>
      <Card title="Drift" subtitle="PSI: last 30 days vs earlier history (>0.25 significant). ADWIN on OOS error stream." span={2}>
        <Async state={d} label="Loading drift">
          {(x) => <>
            <p>Status <Badge tone={x.psi.status === "stable" ? "good" : x.psi.status === "moderate" ? "warn" : "bad"}>{x.psi.status}</Badge>{" "}
              ADWIN Brier: {x.adwin_brier ? (x.adwin_brier.drift ? `change at ${x.adwin_brier.detections.join(", ")} of ${x.adwin_brier.n}` : "no change") : "—"}</p>
            <DataTable maxHeight={220} rows={x.psi.features.slice(0, 12) as unknown as Record<string, unknown>[]} columns={[
              { key: "feature", label: "Feature" }, { key: "psi", label: "PSI", align: "right" }, { key: "level", label: "Level" }]} />
          </>}
        </Async>
      </Card>
      <Card title="Why (cited)" subtitle="BM25 over docs/, evidence and this model card.">
        <Async state={e} label="Loading explanation">
          {(x) => <><p>{x.summary}</p><ul className="ux-list">{x.citations.map((c) => <li key={c.cite}><code>{c.cite}</code> {c.heading ? <strong>{c.heading}</strong> : null}<br /><span className="ux-muted">{c.snippet}</span></li>)}</ul></>}
        </Async>
      </Card>
    </>
  );
}

export function MlModelsView() {
  const reg = useApi<{ latest: Summary[]; n_eligible: number; policy: string }>("/api/ml/registry", 60000);
  const shadow = useApi<{ n_observed: number; n_resolved: number }>("/api/ml/shadow", 60000);
  const [pick, setPick] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sq, setSq] = useState<string | null>(null);
  const search = useApi<{ results: Cite[] }>(sq ? `/api/ml/search?q=${encodeURIComponent(sq)}` : null, 600000);
  return (
    <div className="ux-layout">
      <Card title="Meta-label models" span="full" subtitle="Latest version per group. Purged walk-forward OOS, after venue costs."
        footer={<>Refresh (paper only): <Command text="PYTHONPATH=src python scripts/ml_refresh.py --backfill" /></>}>
        <Async state={reg} label="Loading registry" isEmpty={(d) => !d.latest.length}
          empty={<EmptyState title="No trained versions yet">Run the refresh command below.</EmptyState>}>
          {(d) => <>
            <p>{d.n_eligible} eligible. {d.policy}. Shadow: {shadow.data ? `${shadow.data.n_observed} forward predictions, ${shadow.data.n_resolved} resolved` : "—"}.</p>
            <DataTable rows={d.latest as unknown as Record<string, unknown>[]} columns={[
              { key: "group", label: "Group" },
              { key: "status", label: "Status", render: (r) => <Badge tone={r.status === "eligible" ? "good" : "warn"}>{String(r.status).replace("_", " ")}</Badge> },
              { key: "n_oos", label: "OOS", align: "right" }, { key: "brier_skill", label: "Brier skill", align: "right", render: (r) => f(r.brier_skill, 4) },
              { key: "auc", label: "AUC", align: "right", render: (r) => f(r.auc) }, { key: "ece", label: "ECE", align: "right", render: (r) => f(r.ece) },
              { key: "n_taken", label: "Taken", align: "right" }, { key: "mean_r_taken", label: "Mean R", align: "right", render: (r) => f(r.mean_r_taken) },
              { key: "dsr", label: "DSR", align: "right", render: (r) => f(r.dsr) }, { key: "pbo", label: "PBO", align: "right", render: (r) => f(r.pbo) },
              { key: "version", label: "", render: (r) => <button type="button" className="ux-link-btn" aria-pressed={pick === r.version} onClick={() => setPick(String(r.version))}>Details</button> }]} />
          </>}
        </Async>
      </Card>
      {pick ? <Detail key={pick} version={pick} /> : null}
      <Card title="Search docs & evidence" span="full">
        <form className="ux-form-row" onSubmit={(ev) => { ev.preventDefault(); if (q.trim().length > 1) setSq(q.trim()); }}>
          <input value={q} onChange={(ev) => setQ(ev.target.value)} placeholder="e.g. purged walk-forward embargo" aria-label="Search query" />{" "}
          <button type="submit" className="ux-btn">Search</button>
        </form>
        {sq ? <Async state={search} label="Searching">{(x) => <ul className="ux-list">{x.results.map((c) => <li key={c.cite}><code>{c.cite}</code> {c.heading}<br /><span className="ux-muted">{c.snippet}</span></li>)}</ul>}</Async> : null}
      </Card>
    </div>
  );
}
