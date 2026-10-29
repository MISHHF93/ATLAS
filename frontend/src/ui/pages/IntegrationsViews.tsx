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
            { key: "signup", label: "Official 3rd-Party Link", render: (r) => r.signup ? <a className="ux-link" href={String(r.signup)} target="_blank" rel="noopener noreferrer">Official portal / docs ↗</a> : "—" },
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
  const [symbol, setSymbol] = useState("GC");
  return (
    <Card title="Paper account chart" span="full" subtitle="Bars from the ATLAS provider router (Alpaca first, free fallbacks), tagged with provider and latency. No orders from this chart."
      actions={<select aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
        <optgroup label="Gold & Silver (Futures + Bullion ETFs)">
          {["GC", "MGC", "SI", "GLD", "SLV"].map((x) => <option key={x} value={x}>{x}</option>)}
        </optgroup>
        <optgroup label="Authentic ETFs (Index, Treasury/Bond & Sector)">
          {["SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "TLT", "IEF", "SHY", "AGG", "BND", "LQD", "HYG", "XLK", "XLF", "XLE", "XLV", "XLI", "SOXX", "SMH", "VNQ"].map((x) => <option key={x} value={x}>{x}</option>)}
        </optgroup>
        <optgroup label="CME Futures & Spot FX">
          {["ES", "NQ", "YM", "RTY", "CL", "NG", "ZN", "ZB", "6E", "6J", "EUR_USD", "USD_CAD"].map((x) => <option key={x} value={x}>{x}</option>)}
        </optgroup>
        <optgroup label="US Stocks">
          {["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "JPM", "GS", "LLY", "XOM"].map((x) => <option key={x} value={x}>{x}</option>)}
        </optgroup>
        <optgroup label="Major Crypto">
          {["BTCUSDT", "ETHUSDT", "SOLUSDT"].map((x) => <option key={x} value={x}>{x}</option>)}
        </optgroup>
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


/* ---------- Data coverage: every catalog asset, which source serves it, last bar (Toronto time) and why it is empty ---------- */
type CovProv = { provider: string; usable: boolean; why: string; env: string[]; register: string; cost: string };
type CovAsset = { instrument: string; asset_class: string; status: string; served_by: string | null; intervals: string[]; daily_only: boolean; delayed: boolean;
  chain: CovProv[]; last_bar_interval: string | null; last_bar_provider: string | null; last_bar_toronto: string | null; fix: string; label: string };
type CovClass = { asset_class: string; label: string; count: number; by_status: Record<string, number>; served_by: Record<string, number>; needs: string[] };
type CovProxy = { symbol: string; proxy: string; label: string; proxy_status: string };
type Coverage = { as_of_toronto: string; status_counts: Record<string, number>; classes: CovClass[]; assets: CovAsset[]; proxies: CovProxy[] };

const COV_TONE: Record<string, Tone> = { ok: "good", daily_only: "warn", awaiting_data: "neutral", needs_key: "warn", policy_blocked: "bad", no_provider: "bad" };
const COV_TEXT: Record<string, string> = { ok: "serving", daily_only: "daily only", awaiting_data: "ready, no bars yet", needs_key: "needs a free key",
  policy_blocked: "paid / unofficial only", no_provider: "no provider" };

export function CoverageCard() {
  const [all, setAll] = useState(false);
  const cov = useApi<Coverage>("/api/feeds/catalog-health", 60000);
  return (
    <Card title="Data coverage" span="full"
      subtitle="Every asset on the desk: which free source serves it, how fresh the last stored bar is (Toronto time) and, if a chart is empty, exactly why. Only free, official sources are used; paid or unofficial endpoints stay off.">
      <Async state={cov} label="Checking sources">{(c) => {
        const rows = (all ? c.assets : c.assets.filter((a) => a.status !== "ok" || ["AAPL", "SPY", "QQQ", "GLD", "EUR_USD", "USD_CAD", "BTCUSDT", "GC"].includes(a.instrument)));
        return (
          <>
            <p>Checked {c.as_of_toronto}. {Object.entries(c.status_counts).map(([k, v]) => `${v} ${COV_TEXT[k] ?? k}`).join(" · ")}</p>
            <DataTable rows={c.classes as unknown as R[]} columns={[
              { key: "label", label: "Asset class" },
              { key: "count", label: "Assets" },
              { key: "served_by", label: "Served by", render: (r) => Object.keys((r as unknown as CovClass).served_by).join(", ") || "nothing yet" },
              { key: "by_status", label: "Status", render: (r) => Object.entries((r as unknown as CovClass).by_status).map(([k, v]) => <Badge key={k} tone={COV_TONE[k] ?? "neutral"}>{v} {COV_TEXT[k] ?? k}</Badge>) },
              { key: "needs", label: "Free key that unlocks it", render: (r) => (r as unknown as CovClass).needs.join(" | ") || "none needed" },
            ]} />
            <h4>{all ? "All assets" : "Key assets and everything that needs attention"}</h4>
            <button type="button" className="ux-btn" onClick={() => setAll((v) => !v)}>{all ? "Show fewer" : `Show all ${c.assets.length}`}</button>
            <DataTable rows={rows as unknown as R[]} columns={[
              { key: "instrument", label: "Asset" },
              { key: "asset_class", label: "Class" },
              { key: "status", label: "Status", render: (r) => { const a = r as unknown as CovAsset; return <Badge tone={COV_TONE[a.status] ?? "neutral"}>{COV_TEXT[a.status] ?? a.status}</Badge>; } },
              { key: "served_by", label: "Source", render: (r) => { const a = r as unknown as CovAsset; return a.served_by ? `${a.served_by}${a.daily_only ? " (daily only)" : a.delayed ? " (delayed)" : ""}` : "none"; } },
              { key: "intervals", label: "Timeframes", render: (r) => (r as unknown as CovAsset).intervals.join(" ") || "none" },
              { key: "last_bar_toronto", label: "Last bar (Toronto)", render: (r) => { const a = r as unknown as CovAsset; return a.last_bar_toronto ? `${a.last_bar_toronto} · ${a.last_bar_interval}` : "no stored bars"; } },
              { key: "fix", label: "What to do", render: (r) => { const a = r as unknown as CovAsset; return a.fix || a.label || "nothing"; } },
            ]} />
            <h4>Labelled stand-ins</h4>
            <DataTable rows={c.proxies as unknown as R[]} columns={[
              { key: "symbol", label: "Name" }, { key: "proxy", label: "Free stand-in" }, { key: "label", label: "Why" },
              { key: "proxy_status", label: "Stand-in status", render: (r) => { const a = r as unknown as CovProxy; return <Badge tone={COV_TONE[a.proxy_status] ?? "neutral"}>{COV_TEXT[a.proxy_status] ?? a.proxy_status}</Badge>; } },
            ]} />
          </>
        );
      }}</Async>
    </Card>
  );
}
