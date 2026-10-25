"use client";
/** Integrations status card (Settings) and the Alpaca paper account reconciliation view (Trade). Paper only. Read-only:
 *  nothing here places an order, and no secret value is ever fetched or shown (the API returns names and booleans). */
import { useEffect, useRef, useState } from "react";
import { AtlasChart } from "../../components/market/AtlasChart";
import { Async, Badge, Card, DataTable, EmptyState, StatTile, useApi, type Tone } from "../primitives";

type R = Record<string, unknown>;
type Svc = { id: string; title: string; category: string; cost: string; configured: boolean; required_vars: Record<string, boolean>;
  mode: string; reachable: boolean | null; detail: string; probe_available: boolean; signup: string };
type Prov = { asset_class: string; example: string; priority: string[]; active: string | null; fallbacks: string[]; needs_keys: string[]; excluded?: string[]; sources?: Record<string, { cost?: string; latency?: string; limits?: string }> };
type Status = { services: Svc[]; probed: boolean; data_providers?: Prov[]; summary: { total: number; configured: number; live_refused: string[] } };

const modeTone = (m: string): Tone => (m === "live_refused" ? "bad" : m === "paper" || m === "practice" || m === "sandbox" ? "good" : "neutral");
const reachText = (s: Svc) => (s.reachable === true ? "reachable" : s.reachable === false ? "unreachable" : s.probe_available ? "not checked" : "no test");

export function IntegrationsStatusCard() {
  const [probe, setProbe] = useState(false);
  const st = useApi<Status>(`/api/integrations/status${probe ? "?probe=true" : ""}`, 60000);
  return (
    <Card title="Integrations" span="full"
      subtitle="Every third-party service ATLAS can use. Configured means its keys are in the local .env; secret values are never shown. Alpaca is paper only and a live endpoint is refused."
      actions={<button type="button" className="ux-btn" onClick={() => { setProbe(true); st.reload(); }}>Test connections (read-only)</button>}>
      <Async state={st} label="Checking">{(s) => (
        <>
          <p>{s.summary.configured} of {s.summary.total} configured{s.summary.live_refused.length ? ` · live refused: ${s.summary.live_refused.join(", ")}` : ""}</p>
          <DataTable rows={s.services as unknown as R[]} columns={[
            { key: "title", label: "Service" },
            { key: "configured", label: "Keys", render: (r) => <Badge tone={r.configured ? "good" : "neutral"}>{r.configured ? "configured" : "not configured"}</Badge> },
            { key: "reachable", label: "Connection", render: (r) => { const v = r as unknown as Svc; return <Badge tone={v.reachable === true ? "good" : v.reachable === false ? "bad" : "neutral"} title={v.detail}>{reachText(v)}</Badge>; } },
            { key: "mode", label: "Mode", render: (r) => <Badge tone={modeTone(String(r.mode))}>{String(r.mode).replace(/_/g, " ")}</Badge> },
            { key: "cost", label: "Cost", render: (r) => String(r.cost).replace(/_/g, " ") },
            { key: "required_vars", label: "Missing", render: (r) => Object.entries(r.required_vars as Record<string, boolean>).filter(([, ok]) => !ok).map(([k]) => k).join(", ") || "—" },
          ]} />
          <h4>Data provider choice</h4>
          <p>Alpaca is preferred for US stocks, ETFs (IEX feed, needs paper keys) and crypto (history is keyless). Public sources are automatic fallbacks and cover gold/futures, forex and indices. Every bar is tagged with its provider. TradingView widgets are display only: ATLAS never reads prices from them.</p>
          <DataTable rows={(s.data_providers ?? []) as unknown as R[]} columns={[
            { key: "asset_class", label: "Asset class" },
            { key: "active", label: "In use", render: (r) => <Badge tone={r.active ? "good" : "neutral"}>{String(r.active ?? "none")}</Badge> },
            { key: "fallbacks", label: "Fallbacks", render: (r) => (r.fallbacks as string[]).join(", ") || "—" },
            { key: "needs_keys", label: "Needs keys", render: (r) => (r.needs_keys as string[]).join(", ") || "—" },
            { key: "latency", label: "Free / latency / limits", render: (r) => { const a = r.active as string | null; const s = a ? (r.sources as Prov["sources"])?.[a] : undefined; return s ? `${s.cost} · ${s.latency} · ${s.limits}` : "—"; } },
            { key: "excluded", label: "Excluded (paid/unofficial)", render: (r) => ((r.excluded as string[] | undefined) ?? []).join(", ") || "—" },
          ]} />
        </>
      )}</Async>
    </Card>
  );
}

type Recon = { status: string; reason?: string; account: R | null; positions: R[]; orders: R[]; fills: R[];
  checks: { check: string; ok: boolean | null; detail: string }[] };
const money = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-US", { style: "currency", currency: "USD" }) : "—");

/** Paper-account chart: the one ATLAS chart (AtlasChart). Bars come from the free provider router, which prefers
 *  Alpaca (IEX stocks/ETFs once paper keys are set; keyless crypto history) and falls back to other free sources.
 *  Each bar carries its provider and real-time/delayed tag. Display and research only: execution_permission none. */
export function AlpacaChartCard() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  return (
    <Card title="Paper account chart" span="full" subtitle="Bars from the ATLAS provider router (Alpaca first, free fallbacks), tagged with provider and latency. No orders from this chart."
      actions={<select aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
        {["BTCUSDT", "ETHUSDT", "SOLUSDT", "SPY", "QQQ", "IWM"].map((x) => <option key={x}>{x}</option>)}
      </select>}>
      <AtlasChart symbol={symbol} timeframe="15m" height={360} />
    </Card>
  );
}

export function PaperAccountView() {
  const rc = useApi<Recon>("/api/ext/alpaca/reconcile", 30000);
  return (
    <div className="ux-layout">
      <AlpacaChartCard />
      <Async state={rc} label="Loading paper account">{(d) => d.status !== "ok" && d.status !== "partial" ? (
        <Card title="Alpaca paper account" span="full">
          <EmptyState title={`Paper account ${d.status.replace(/_/g, " ")}`}>{d.reason ?? ""} Add the Alpaca paper keys to the local .env and restart the server. Settings → Broker & alerts shows what is missing.</EmptyState>
        </Card>
      ) : (
        <>
          <Card title="Alpaca paper account" span="full" subtitle="Reconciled from the Alpaca paper API. Every ATLAS order passes the control plane first; orders placed elsewhere are flagged.">
            <div className="ux-layout">
              <StatTile label="Equity" value={money(d.account?.equity)} />
              <StatTile label="Cash" value={money(d.account?.cash)} />
              <StatTile label="Buying power" value={money(d.account?.buying_power)} />
              <StatTile label="Account" value={String(d.account?.account_number ?? "—")} hint="Paper (PA…) accounts only" />
            </div>
          </Card>
          <Card title="Reconciliation checks" span="full">
            <DataTable rows={d.checks as unknown as R[]} columns={[
              { key: "check", label: "Check", render: (r) => String(r.check).replace(/_/g, " ") },
              { key: "ok", label: "Result", render: (r) => <Badge tone={r.ok === true ? "good" : r.ok === false ? "warn" : "neutral"}>{r.ok === true ? "ok" : r.ok === false ? "attention" : "n/a"}</Badge> },
              { key: "detail", label: "Detail" },
            ]} />
          </Card>
          <Card title="Positions" span="full">
            <DataTable rows={d.positions} empty={<EmptyState title="No open paper positions" />} columns={[
              { key: "symbol", label: "Symbol" }, { key: "side", label: "Side" }, { key: "qty", label: "Qty", align: "right" },
              { key: "avg_entry_price", label: "Avg entry", align: "right", render: (r) => money(r.avg_entry_price) },
              { key: "market_value", label: "Market value", align: "right", render: (r) => money(r.market_value) },
              { key: "unrealized_pl", label: "Unrealized P/L", align: "right", render: (r) => money(r.unrealized_pl) },
            ]} />
          </Card>
          <Card title="Orders" span="full">
            <DataTable rows={d.orders} empty={<EmptyState title="No paper orders yet" />} maxHeight={360} columns={[
              { key: "submitted_at", label: "Submitted" }, { key: "symbol", label: "Symbol" }, { key: "side", label: "Side" },
              { key: "qty", label: "Qty", align: "right" }, { key: "filled_qty", label: "Filled", align: "right" }, { key: "status", label: "Status" },
              { key: "origin", label: "Origin", render: (r) => <Badge tone={r.origin === "atlas_control_plane" ? "good" : "warn"}>{r.origin === "atlas_control_plane" ? "control plane" : "outside ATLAS"}</Badge> },
            ]} />
          </Card>
          <Card title="Fills" span="full">
            <DataTable rows={d.fills} empty={<EmptyState title="No fills yet" />} maxHeight={360} columns={[
              { key: "time", label: "Time" }, { key: "symbol", label: "Symbol" }, { key: "side", label: "Side" },
              { key: "qty", label: "Qty", align: "right" }, { key: "price", label: "Price", align: "right", render: (r) => money(r.price) },
            ]} />
          </Card>
        </>
      )}</Async>
    </div>
  );
}
