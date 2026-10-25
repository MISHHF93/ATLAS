"use client";
/** Integrations status card (Settings) and the Alpaca paper account reconciliation view (Trade). Paper only. Read-only:
 *  nothing here places an order, and no secret value is ever fetched or shown (the API returns names and booleans). */
import { useEffect, useRef, useState } from "react";
import { ColorType, createChart, type UTCTimestamp } from "lightweight-charts";
import { deskTimeOptions } from "../../components/market/lwTime";
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

type Src = { id: string; label: string; available: boolean; reason: string | null };
type ABars = { status: string; reason?: string; provider?: string; bars: { time: number; open: number; high: number; low: number; close: number }[] };

/** Alpaca as a selectable chart source (IEX stock/ETF bars once paper keys are set; crypto history is keyless).
 *  Display and research only: execution_permission none. */
export function AlpacaChartCard() {
  const srcs = useApi<{ sources: Src[] }>("/api/integrations/chart/sources", 60000);
  const [source, setSource] = useState("alpaca_crypto");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [tf, setTf] = useState("15m");
  const [data, setData] = useState<ABars | null>(null);
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let live = true;
    fetch(`/api/integrations/chart/bars?source=${source}&symbol=${encodeURIComponent(symbol)}&tf=${tf}&limit=300`)
      .then((r) => r.json()).then((j: ABars) => { if (live) setData(j); }).catch((e) => { if (live) setData({ status: "error", reason: String(e), bars: [] }); });
    return () => { live = false; };
  }, [source, symbol, tf]);
  useEffect(() => {
    const el = host.current;
    if (!el || !data?.bars.length) return;
    const api = createChart(el, { ...deskTimeOptions, width: Math.max(1, el.clientWidth), height: 320,
      layout: { attributionLogo: true, background: { type: ColorType.Solid, color: "#0B0F17" }, textColor: "#A9BDCE" },
      grid: { vertLines: { color: "#182431" }, horzLines: { color: "#182431" } } });
    const s = api.addCandlestickSeries({ upColor: "#34d399", downColor: "#fb7185", borderVisible: false, wickUpColor: "#34d399", wickDownColor: "#fb7185" });
    s.setData(data.bars.map((b) => ({ time: b.time as UTCTimestamp, open: b.open, high: b.high, low: b.low, close: b.close })));
    api.timeScale().fitContent();
    return () => api.remove();
  }, [data]);
  const opts = srcs.data?.sources.filter((x) => x.id !== "atlas") ?? [];
  const cur = opts.find((x) => x.id === source);
  return (
    <Card title="Alpaca market data" span="full" subtitle={`Source: ${data?.provider ?? source}. Bars are tagged with their provider. Display and research only; no orders.`}
      actions={<span style={{ display: "flex", gap: 8 }}>
        <select aria-label="Chart source" value={source} onChange={(e) => { setSource(e.target.value); setSymbol(e.target.value === "alpaca" ? "SPY" : "BTCUSDT"); }}>
          {opts.map((o) => <option key={o.id} value={o.id} disabled={!o.available}>{o.label}{o.available ? "" : " (add keys)"}</option>)}
        </select>
        <select aria-label="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {(source === "alpaca" ? ["SPY", "QQQ", "IWM", "AAPL", "NVDA"] : ["BTCUSDT", "ETHUSDT", "SOLUSDT"]).map((x) => <option key={x}>{x}</option>)}
        </select>
        <select aria-label="Timeframe" value={tf} onChange={(e) => setTf(e.target.value)}>{["1m", "5m", "15m", "1h", "1d"].map((x) => <option key={x}>{x}</option>)}</select>
      </span>}>
      {cur && !cur.available ? <EmptyState title="Alpaca stock bars not configured">{cur.reason ?? ""}</EmptyState>
        : data && data.status !== "ok" ? <EmptyState title={`Alpaca bars ${data.status.replace(/_/g, " ")}`}>{data.reason ?? ""}</EmptyState>
        : <div ref={host} style={{ width: "100%", height: 320 }} />}
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
