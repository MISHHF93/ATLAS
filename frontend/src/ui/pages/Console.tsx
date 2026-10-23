"use client";
/** Functional owner-console pages: setup autopilot, Safe stop, shadow weeks, API keys, approvals, models & evidence.
 * Every write goes to a real backend endpoint and shows loading / success / error. Nothing here can approve
 * the autopilot, approve a trade, reset the Safe stop or move money: those stay on the owner CLI with step-up. */
import { useState } from "react";
import { useSafeStop } from "../AppShell";
import {
  ActionButton, ActionResult, Async, Badge, Card, Command, CopyButton, DataTable, EmptyState, ago, useAction, useApi,
} from "../primitives";

type Req = { id: string; actor?: string; note?: string; channel?: string; at: number; expires: number };
type Autopilot = {
  on: boolean; switch?: { by?: string; reason?: string; at?: number }; pending_requests: Req[]; approve_with?: string[];
  streams: { symbol: string; timeframe: number; session?: string | null }[]; open_paper_positions: number; pending_entries: number;
  recent_decisions: Record<string, unknown>[]; registry_models: number; last_tick?: unknown; risk?: Record<string, unknown>;
};
type Week = Record<string, unknown> & { week: string };

const ts = (s: number | undefined | null) => (s ? new Date(s * 1000).toLocaleString("en-CA") : "—");

/* ----------------------------------------------------------------- Safe stop */

export function SafeStopCard() {
  const ss = useSafeStop();
  const [reason, setReason] = useState("manual_owner_halt");
  const engage = useAction("/api/founder/safe-stop");
  return (
    <Card title="Safe stop" subtitle="Engaging halts every new paper order immediately. Releasing needs the owner CLI with step-up."
      actions={ss.engaged === null ? <Badge>unknown</Badge> : ss.engaged ? <Badge tone="bad">active</Badge> : <Badge tone="good">armed</Badge>}>
      {ss.engaged ? (
        <>
          <p className="ux-muted">Active{ss.reason ? `: ${ss.reason.replaceAll("_", " ")}` : ""}{ss.since ? ` since ${ss.since}` : ""}. Release on the owner machine:</p>
          <Command text="atlas-owner reset-kill-switch" />
        </>
      ) : (
        <form className="ux-form-row" onSubmit={(e) => { e.preventDefault(); }}>
          <label className="ux-field"><span>Reason</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={120} />
          </label>
          <ActionButton action={engage} body={{ reason: reason || "manual_owner_halt" }} tone="danger"
            confirm="Engage Safe stop? New paper orders will be rejected until the owner releases it from the CLI." onDone={ss.reload}>
            Engage Safe stop
          </ActionButton>
        </form>
      )}
      <ActionResult action={engage} success="Safe stop engaged. Release stays CLI-only: atlas-owner reset-kill-switch" />
    </Card>
  );
}

/* ----------------------------------------------------------------- Autopilot */

export function AutopilotView() {
  const st = useApi<Autopilot>("/api/console/autopilot", 10000);
  const [note, setNote] = useState("");
  const on = useAction<Req & { approve_with: string }>("/api/console/autopilot/request-on");
  const off = useAction("/api/console/autopilot/off");
  return (
    <div className="ux-layout">
      <Card title="Paper setup autopilot" span="full"
        subtitle="Trades proposed price-action setups on paper only. The UI can only file a start request; the owner approves it with passphrase + TOTP."
        actions={st.data ? (st.data.on ? <Badge tone="good">on</Badge> : <Badge>off</Badge>) : null}>
        <Async state={st} label="Loading autopilot">
          {(d) => (
            <div className="ux-layout">
              <dl className="ux-dl">
                <dt>Switch</dt><dd>{d.on ? "On" : "Off"}{d.switch?.by ? ` · by ${d.switch.by}` : ""}{d.switch?.reason ? ` · ${d.switch.reason}` : ""}{d.switch?.at ? ` · ${ts(d.switch.at)}` : ""}</dd>
                <dt>Streams</dt><dd>{d.streams.map((s) => `${s.symbol} ${s.timeframe / 60}m${s.session ? ` (${s.session})` : ""}`).join(", ") || "none"}</dd>
                <dt>Open paper positions</dt><dd>{d.open_paper_positions}</dd>
                <dt>Waiting entries</dt><dd>{d.pending_entries}</dd>
                <dt>Registered models</dt><dd>{d.registry_models} {d.registry_models === 0 ? "(no validated model: every setup abstains)" : ""}</dd>
              </dl>
              <div className="ux-form-row">
                {!d.on ? (
                  <>
                    <label className="ux-field"><span>Note for the owner (optional)</span>
                      <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="why start now" />
                    </label>
                    <ActionButton action={on} body={{ note }} tone="primary" onDone={st.reload}>Request start</ActionButton>
                  </>
                ) : null}
                <ActionButton action={off} body={{ reason: "switched_off_from_console" }} tone="danger" onDone={st.reload}>Switch off now</ActionButton>
              </div>
              <ActionResult action={off} success="Switched off. The loop stops before its next order." />
              <ActionResult action={on} success={on.result ? <>Request <strong>{on.result.id}</strong> filed. Approve on the owner machine:</> : null} />
              {on.result ? <Command text={on.result.approve_with} /> : null}
              <h3 className="ux-h3">Pending start requests</h3>
              {d.pending_requests.length ? (
                <DataTable rows={d.pending_requests.map((r, i) => ({ ...r, cmd: d.approve_with?.[i] ?? "" }))} columns={[
                  { key: "id", label: "Request" },
                  { key: "channel", label: "From", render: (r) => `${r.channel ?? ""} ${r.actor ?? ""}` },
                  { key: "note", label: "Note" },
                  { key: "expires", label: "Expires", render: (r) => ts(r.expires as number) },
                  { key: "cmd", label: "Approve with", render: (r) => <CopyButton text={String(r.cmd)} label="Copy CLI command" /> },
                ]} />
              ) : <p className="ux-muted">No pending requests.</p>}
              <h3 className="ux-h3">Recent decisions</h3>
              {d.recent_decisions.length ? (
                <DataTable rows={d.recent_decisions.slice().reverse()} columns={Object.keys(d.recent_decisions[0]).slice(0, 6).map((k) => ({
                  key: k, label: k.replaceAll("_", " "), render: (r: Record<string, unknown>) => typeof r[k] === "object" ? JSON.stringify(r[k]) : String(r[k] ?? "—"),
                }))} />
              ) : <p className="ux-muted">No decisions yet. The loop records one per tick once it is on.</p>}
            </div>
          )}
        </Async>
      </Card>
      <SafeStopCard />
      <ShadowWeeks />
    </div>
  );
}

export function ShadowWeeks() {
  const st = useApi<{ weeks: Week[]; rule: string }>("/api/console/shadow", 60000);
  return (
    <Card title="Shadow weeks" subtitle="Every setup the autopilot saw, scored afterwards under conservative OHLC rules. Read-only." span="full">
      <Async state={st} isEmpty={(d) => !d.weeks.length} label="Loading shadow stats"
        empty={<EmptyState title="No shadow records yet">Records appear once the autopilot has observed setups. Rule: conservative_ohlc_v1.</EmptyState>}>
        {(d) => <DataTable rows={d.weeks} columns={Object.keys(d.weeks[0]).map((k) => ({
          key: k, label: k.replaceAll("_", " "), align: typeof d.weeks[0][k] === "number" ? "right" as const : "left" as const,
          render: (r: Week) => { const v = r[k]; return typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(3)) : v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v); },
        }))} />}
      </Async>
    </Card>
  );
}

/* ------------------------------------------------------------------ API keys */

type KeyRec = { key_id: string; name: string; scope: string; created_at: number; revoked_at?: number | null; rate_per_min: number };

export function ApiKeysView() {
  const st = useApi<{ keys: KeyRec[]; ui_scopes: string[]; paper_trade_with: string }>("/api/console/keys", 30000);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("read");
  const [rate, setRate] = useState(60);
  const create = useAction<{ key: string; record: KeyRec }>("/api/console/keys");
  return (
    <div className="ux-layout">
      <Card title="Create a key" subtitle="Keys are hashed at rest. The plaintext is shown once, right here. read / research only; paper-trade keys are created on the owner CLI.">
        <form className="ux-form-row" onSubmit={async (e) => { e.preventDefault(); if (await create.run({ name, scope, rate_per_min: rate })) { setName(""); st.reload(); } }}>
          <label className="ux-field"><span>Name</span><input required value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="claude-desktop" /></label>
          <label className="ux-field"><span>Scope</span>
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="read">read: market, zones, setups, status</option>
              <option value="research">research: adds replay and evidence</option>
            </select>
          </label>
          <label className="ux-field" data-size="sm"><span>Requests / min</span><input type="number" min={1} max={6000} value={rate} onChange={(e) => setRate(Number(e.target.value) || 60)} /></label>
          <button type="submit" className="ux-btn" data-variant="primary" disabled={create.busy || !name.trim()} aria-busy={create.busy}>Create key</button>
        </form>
        <ActionResult action={create} />
        {create.result ? (
          <div className="ux-callout" data-tone="warn" role="status">
            <strong>Copy this key now. It will not be shown again.</strong>
            <Command text={create.result.key} />
          </div>
        ) : null}
        {st.data ? <><p className="ux-muted">Paper-trade scope (owner machine):</p><Command text={st.data.paper_trade_with} /></> : null}
      </Card>
      <Card title="Keys" span="full">
        <Async state={st} isEmpty={(d) => !d.keys.length} label="Loading keys" empty={<EmptyState title="No API keys yet">Create one above for an agent or MCP client.</EmptyState>}>
          {(d) => <DataTable rows={d.keys.slice().sort((a, b) => b.created_at - a.created_at)} columns={[
            { key: "name", label: "Name" },
            { key: "key_id", label: "Key id" },
            { key: "scope", label: "Scope", render: (r) => <Badge tone={r.scope === "paper-trade" ? "warn" : "info"}>{r.scope}</Badge> },
            { key: "rate_per_min", label: "Rate / min", align: "right" },
            { key: "created_at", label: "Created", render: (r) => ts(r.created_at) },
            { key: "revoked_at", label: "Status", render: (r) => r.revoked_at ? <Badge>revoked</Badge> : <RevokeButton id={r.key_id} onDone={st.reload} /> },
          ]} />}
        </Async>
      </Card>
    </div>
  );
}

function RevokeButton({ id, onDone }: { id: string; onDone: () => void }) {
  const a = useAction(`/api/console/keys/${encodeURIComponent(id)}/revoke`);
  return <><ActionButton action={a} tone="danger" confirm={`Revoke key ${id}? Clients using it stop working immediately.`} onDone={onDone}>Revoke</ActionButton><ActionResult action={a} /></>;
}

/* ----------------------------------------------------------------- approvals */

type Approval = { approval_id: string; symbol: string; side: string; qty: number | string; status: string };

export function ApprovalsCard() {
  const st = useApi<{ pending: Approval[]; decide_with: string }>("/api/founder/approvals", 10000);
  return (
    <Card title="Proposed paper trades" span="full"
      subtitle="Reject here at any time. Approving needs the owner CLI with step-up, so the command is shown to copy.">
      <Async state={st} isEmpty={(d) => !d.pending.length} label="Loading approvals"
        empty={<EmptyState title="No paper trades waiting">Proposals from the control plane appear here and expire if nobody decides.</EmptyState>}>
        {(d) => <DataTable rows={d.pending} columns={[
          { key: "approval_id", label: "Approval" },
          { key: "symbol", label: "Symbol" },
          { key: "side", label: "Side", render: (r) => <Badge tone={r.side === "buy" ? "good" : "bad"}>{r.side}</Badge> },
          { key: "qty", label: "Qty", align: "right" },
          { key: "act", label: "Decide", render: (r) => <ApprovalActions id={r.approval_id} onDone={st.reload} /> },
        ]} />}
      </Async>
    </Card>
  );
}

function ApprovalActions({ id, onDone }: { id: string; onDone: () => void }) {
  const reject = useAction(`/api/console/approvals/${encodeURIComponent(id)}/reject`);
  return (
    <div className="ux-form-row" data-tight>
      <ActionButton action={reject} tone="danger" onDone={onDone}>Reject</ActionButton>
      <CopyButton text={`atlas-owner approve ${id}`} label="Copy approve command" />
      <ActionResult action={reject} />
    </div>
  );
}

/* ---------------------------------------------------------- models & evidence */

type Evidence = { name: string; generated_at?: unknown; method?: unknown; pbo?: unknown; n_trials?: unknown; configs?: unknown };
/** Evidence files are free-form JSON; never hand an object straight to React. */
const show = (v: unknown, empty = "—"): string =>
  v === null || v === undefined || v === "" ? empty : typeof v === "object" ? Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : String(x)}`).join(" · ") : String(v);

export function EvidenceView() {
  const models = useApi<{ versions: string[]; policy: string }>("/api/console/models", 60000);
  const files = useApi<{ files: string[] }>("/api/console/evidence", 60000);
  const [pick, setPick] = useState<string | null>(null);
  const detail = useApi<Evidence>(pick ? `/api/console/evidence?name=${encodeURIComponent(pick)}` : null, 600000);
  return (
    <div className="ux-layout">
      <Card title="Model registry" subtitle="Setup models the autopilot may use. With none registered, every setup abstains.">
        <Async state={models} label="Loading registry">
          {(d) => d.versions.length ? <ul className="ux-list">{d.versions.map((v) => <li key={v}><code>{v}</code></li>)}</ul>
            : <EmptyState title="No validated model registered">{d.policy}. Nothing is traded on an unvalidated model.</EmptyState>}
        </Async>
      </Card>
      <Card title="Evidence files" subtitle="Walk-forward and selection studies in docs/spec/evidence.">
        <Async state={files} isEmpty={(d) => !d.files.length} label="Loading evidence" empty={<EmptyState title="No evidence files" />}>
          {(d) => <ul className="ux-list">{d.files.map((f) => (
            <li key={f}><button type="button" className="ux-link-btn" aria-pressed={pick === f} onClick={() => setPick(f)}>{f}</button></li>
          ))}</ul>}
        </Async>
      </Card>
      {pick ? (
        <Card title={pick} span="full" subtitle="Summary of the selected evidence file.">
          <Async state={detail} label="Loading file">
            {(d) => (
              <dl className="ux-dl">
                <dt>Generated</dt><dd>{show(d.generated_at)}</dd>
                <dt>Method</dt><dd>{show(d.method)}</dd>
                <dt>PBO</dt><dd>{show(d.pbo, "not reported")}</dd>
                <dt>Trials</dt><dd>{show(d.n_trials)}</dd>
                <dt>Configs</dt><dd><pre className="ux-md-pre">{JSON.stringify(d.configs ?? null, null, 1)?.slice(0, 4000)}</pre></dd>
              </dl>
            )}
          </Async>
        </Card>
      ) : null}
    </div>
  );
}

export { ago };
