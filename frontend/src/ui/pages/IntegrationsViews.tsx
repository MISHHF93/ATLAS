"use client";
/** Integrations status card (Settings) and the Alpaca paper account reconciliation view (Trade). Paper only. Read-only:
 *  nothing here places an order, and no secret value is ever fetched or shown (the API returns names and booleans). */
import { useEffect, useRef, useState } from "react";
import { AtlasChart } from "../../components/market/AtlasChart";
import { Async, Badge, Card, DataTable, EmptyState, StatTile, money as fmtMoney, useApi, type Tone } from "../primitives";
import { api } from "./acct";

type R = Record<string, unknown>;
type Verif = { state: string; detail: string; verified_at: number | null; key_present: boolean };
type Svc = { id: string; title: string; category: string; cost: string; configured: boolean; required_vars: Record<string, boolean>;
  mode: string; reachable: boolean | null; detail: string; probe_available: boolean; signup: string; verification?: Verif };
type StockProv = { setting: string; primary: string; default_primary: string; warning: string | null; chain: string[];
  providers: { id: string; title: string; canada: string; signup: string; free_limits: string; terms: string; restricted: boolean; env_keys: string[] }[] };
type Prov = { asset_class: string; example: string; priority: string[]; active: string | null; fallbacks: string[]; needs_keys: string[]; excluded?: string[]; sources?: Record<string, { cost?: string; latency?: string; limits?: string }> };
type Status = { services: Svc[]; probed: boolean; data_providers?: Prov[]; stock_provider?: StockProv;
  summary: { total: number; configured: number; live_refused: string[]; needs_verification?: string[]; verified?: string[] } };

/* Every key starts as "Needs verification". Verify makes ONE read-only call with the key you entered (paper / practice / test endpoints only),
 * records the result without storing the key, and a changed key goes back to "Needs verification". */
const VERIF: Record<string, { tone: Tone; text: string }> = {
  needs_verification: { tone: "warn", text: "Needs verification" }, verified: { tone: "good", text: "Verified" }, failed: { tone: "bad", text: "Verification failed" },
  format_only: { tone: "info", text: "Format checked only" }, keyless: { tone: "neutral", text: "No key needed" },
};
export function VerifyCell({ id, v, onDone }: { id: string; v?: Verif; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const st = VERIF[v?.state ?? "needs_verification"] ?? VERIF.needs_verification;
  const can = v?.state !== "keyless";
  return (
    <span className="ux-form-row" data-tight>
      <Badge tone={st.tone} title={note || v?.detail}>{st.text}</Badge>
      {can ? <button type="button" className="ux-btn" disabled={busy || !v?.key_present} title={v?.key_present ? "One read-only check with the key you entered" : "Enter the key in Settings → Setup first"}
        onClick={async () => { setBusy(true); setNote(""); const r = await api<{ detail?: string }>("/api/integrations/verify", { service: id }); setBusy(false); setNote(r.ok ? String(r.data.detail ?? "") : r.message); onDone(); }}>{busy ? "Verifying…" : "Verify"}</button> : null}
      {note ? <span className="ux-small">{note}</span> : null}
    </span>
  );
}

const modeTone = (m: string): Tone => (m === "live_refused" ? "bad" : m === "paper" || m === "practice" || m === "sandbox" ? "good" : "neutral");
const reachText = (s: Svc) => (s.reachable === true ? "reachable" : s.reachable === false ? "unreachable" : s.probe_available ? "not checked" : "no test");

/** The stock/ETF source: ATLAS_STOCK_PROVIDER picks the primary; the others are automatic fallbacks. Alpaca is optional (not offered to Canadian residents). */
export function StockProviderNote({ sp }: { sp?: StockProv }) {
  if (!sp) return null;
  const by = Object.fromEntries(sp.providers.map((p) => [p.id, p]));
  const prim = by[sp.primary];
  return (
    <p>
      <strong>Stock &amp; ETF source:</strong> {prim?.title ?? sp.primary} ({sp.setting}={sp.primary}{sp.primary === sp.default_primary ? ", default" : ""}). Order: {sp.chain.join(" → ")}.
      {prim ? <> {prim.free_limits}. <a className="ux-link" href={prim.signup} target="_blank" rel="noopener noreferrer">Free signup ↗</a></> : null}
      {" "}Alpaca is optional and not offered to Canadian residents. Free plans cover personal use; showing data to other people needs a business data licence.
      {sp.warning ? <span className="ux-action-msg" data-tone="warn" role="status"> {sp.warning}</span> : null}
    </p>
  );
}

export function IntegrationsStatusCard() {
  const [probe, setProbe] = useState(false);
  const st = useApi<Status>(`/api/integrations/status${probe ? "?probe=true" : ""}`, 60000);
  return (
    <Card title="Integrations" span="full"
      subtitle="Every third-party service ATLAS can use. No key is set for you: each one reads Needs verification until you enter it and press Verify. Secret values are never shown or stored by Verify. Paper / practice / test endpoints only."
      actions={<button type="button" className="ux-btn" onClick={() => { setProbe(true); st.reload(); }}>Test connections (read-only)</button>}>
      <Async state={st} label="Checking">{(s) => (
        <>
          <p>{s.summary.verified?.length ?? 0} verified · {s.summary.needs_verification?.length ?? 0} need verification · {s.summary.configured} of {s.summary.total} have keys entered{s.summary.live_refused.length ? ` · live refused: ${s.summary.live_refused.join(", ")}` : ""}</p>
          <DataTable rows={s.services as unknown as R[]} columns={[
            { key: "title", label: "Service" },
            { key: "verification", label: "Verification", render: (r) => { const v = r as unknown as Svc; return <VerifyCell id={v.id} v={v.verification} onDone={st.reload} />; } },
            { key: "reachable", label: "Connection", render: (r) => { const v = r as unknown as Svc; return <Badge tone={v.reachable === true ? "good" : v.reachable === false ? "bad" : "neutral"} title={v.detail}>{reachText(v)}</Badge>; } },
            { key: "mode", label: "Mode", render: (r) => <Badge tone={modeTone(String(r.mode))}>{String(r.mode).replace(/_/g, " ")}</Badge> },
            { key: "required_vars", label: "Missing", render: (r) => Object.entries(r.required_vars as Record<string, boolean>).filter(([, ok]) => !ok).map(([k]) => k).join(", ") || "—" },
            { key: "signup", label: "Official 3rd-Party Link", render: (r) => r.signup ? <a className="ux-link" href={String(r.signup)} target="_blank" rel="noopener noreferrer">Official portal / docs ↗</a> : "—" },
          ]} />
          <h4>Data provider choice</h4>
          <StockProviderNote sp={s.stock_provider} />
          <p>Crypto history is keyless. Gold/futures, forex and indices use official free public sources as automatic fallbacks. Every bar is tagged with its provider. TradingView widgets are display only: ATLAS never reads prices from them.</p>
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
 *  the stock provider chain (Massive daily bars by default once its key verifies; keyless crypto history) and falls back to other free sources.
 *  Each bar carries its provider and real-time/delayed tag. Display and research only: execution_permission none. */
export function AlpacaChartCard() {
  const [symbol, setSymbol] = useState("GC");
  return (
    <Card title="Paper account chart" span="full" subtitle="Bars from the ATLAS provider router (the ATLAS_STOCK_PROVIDER primary, Massive by default, with free fallbacks), tagged with provider and latency. No orders from this chart."
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


type Snap = { snapshot: { broker: string; environment: string; status: string; reason: string; as_of: string; currency: string | null; account_ref: string | null;
    balances: Record<string, number | null>; positions: unknown[]; open_orders: unknown[]; warnings: string[];
    rules: { min_order_notional: number | null; fractional: boolean | null; pdt_applies: boolean | null; margin_enabled: boolean | null; notes: string[] };
    fees: { commission_per_order: number | null; notes: string[] }; market: { is_open: boolean | null; source: string | null } };
  sizing: { ideal_notional: number | null; min_order_notional: number | null; feasible: boolean | null; forced_risk_fraction: number | null; min_equity_for_policy: number | null };
  brokers: { broker: string; environment: string; state: string; detail: string }[]; context: string };

const yn = (v: boolean | null | undefined) => (v === null || v === undefined ? "unknown" : v ? "yes" : "no");

/** Read-only broker account snapshot (cash, buying power, positions, orders, minimum order, fees, market state) for ATLAS paper sim,
 *  Alpaca paper and OANDA practice. A broker is read only after its key is verified. The ML reads this; it grants no execution. */
export function AccountSnapshotCard() {
  const [broker, setBroker] = useState("paper_sim");
  const [eq, setEq] = useState("100");
  const q = broker === "paper_sim" && Number(eq) >= 0.5 ? `&sim_equity=${encodeURIComponent(eq)}` : "";
  const st = useApi<Snap>(`/api/account/snapshot?broker=${broker}${q}`, 30000);
  return (
    <Card title="Broker account snapshot" span="full" subtitle="What the ML is allowed to know about the account: balances, constraints and fees. Read-only; sizing stays with the control plane."
      actions={<>
        <select aria-label="Broker" value={broker} onChange={(e) => setBroker(e.target.value)}>
          <option value="paper_sim">ATLAS paper (simulated)</option>
          <option value="alpaca">Alpaca paper</option>
          <option value="oanda">OANDA practice</option>
        </select>
        {broker === "paper_sim" && <input aria-label="Simulated starting equity" type="number" min={0.5} step="any" value={eq} onChange={(e) => setEq(e.target.value)} style={{ width: 90 }} />}
      </>}>
      <Async state={st} label="Reading account snapshot">{(d) => {
        const s = d.snapshot, b = s.balances, c = s.currency ?? "USD";
        if (s.status !== "ok") {
          const v = d.brokers.find((x) => x.broker === broker);
          return <EmptyState title={`${s.broker} ${s.environment}: ${s.status.replace(/_/g, " ")}`}>{s.reason} {v && v.state === "needs_verification" ? "Settings → Setup shows the Verify action." : ""}</EmptyState>;
        }
        return (
          <div className="ux-layout">
            <StatTile label="Equity" value={fmtMoney(b.equity, c)} hint={`${s.environment}${s.account_ref ? " · " + s.account_ref : ""}`} />
            <StatTile label="Cash" value={fmtMoney(b.cash, c)} />
            <StatTile label="Buying power" value={fmtMoney(b.buying_power, c)} hint={b.leverage_max ? `up to ${b.leverage_max.toFixed(0)}× leverage` : "no margin"} />
            <StatTile label="Positions / open orders" value={`${s.positions.length} / ${s.open_orders.length}`} />
            <StatTile label="Minimum order" value={s.rules.min_order_notional === null ? "unknown" : fmtMoney(s.rules.min_order_notional, c)} hint={`fractional: ${yn(s.rules.fractional)}`} />
            <StatTile label="Fee per order" value={s.fees.commission_per_order === null ? "unknown" : fmtMoney(s.fees.commission_per_order, c)} hint={`margin: ${yn(s.rules.margin_enabled)} · PDT flag: ${yn(s.rules.pdt_applies)}`} />
            <StatTile label="Market" value={s.market.is_open === null ? "not reported" : s.market.is_open ? "open" : "closed"} hint={s.market.source ?? ""} />
            <StatTile label="Policy-sized trade fits?" value={d.sizing.feasible === null ? "unknown" : d.sizing.feasible ? "yes" : "no"}
              hint={d.sizing.feasible === false && d.sizing.min_equity_for_policy !== null ? `needs about ${fmtMoney(d.sizing.min_equity_for_policy, c)} at 0.5% risk, 2% stop; waiting beats oversizing` : "0.5% risk, 2% stop (illustrative)"} />
            {s.warnings.length > 0 && <p className="ux-small">{s.warnings.join(" · ")}</p>}
          </div>
        );
      }}</Async>
    </Card>
  );
}

export function PaperAccountView() {
  const rc = useApi<Recon>("/api/ext/alpaca/reconcile", 30000);
  return (
    <div className="ux-layout">
      <AccountSnapshotCard />
      <AlpacaChartCard />
      <Async state={rc} label="Loading paper account">{(d) => d.status !== "ok" && d.status !== "partial" ? (
        <Card title="Alpaca paper account" span="full">
          <EmptyState title={`Paper account ${d.status.replace(/_/g, " ")}`}>{d.reason ?? ""} Alpaca is optional (not offered to Canadian residents): add its paper keys in Settings → Setup and press Verify. Settings → Broker & alerts shows what is missing.</EmptyState>
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
type Coverage = { as_of_toronto: string; status_counts: Record<string, number>; classes: CovClass[]; assets: CovAsset[]; proxies: CovProxy[]; stock_provider?: StockProv };

const COV_TONE: Record<string, Tone> = { ok: "good", daily_only: "warn", awaiting_data: "neutral", needs_key: "warn", policy_blocked: "bad", no_provider: "bad" };
const COV_TEXT: Record<string, string> = { ok: "serving", daily_only: "daily only", awaiting_data: "ready, no bars yet", needs_key: "needs verification",
  policy_blocked: "paid / unofficial only", no_provider: "no provider" };

/** The primary stock source's key state with a Verify button, right where the empty stock charts are explained. */
function StockVerifyRow({ sp }: { sp?: StockProv }) {
  const st = useApi<Status>("/api/integrations/status", 60000);
  if (!sp || !st.data) return null;
  const svc = st.data.services.find((x) => x.id === sp.primary);
  if (!svc) return null;
  return <p className="ux-form-row" data-tight><span>{svc.title}:</span><VerifyCell id={svc.id} v={svc.verification} onDone={st.reload} /></p>;
}

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
            <StockProviderNote sp={c.stock_provider} />
            <StockVerifyRow sp={c.stock_provider} />
            <DataTable rows={c.classes as unknown as R[]} columns={[
              { key: "label", label: "Asset class" },
              { key: "count", label: "Assets" },
              { key: "served_by", label: "Served by", render: (r) => Object.keys((r as unknown as CovClass).served_by).join(", ") || "nothing yet" },
              { key: "by_status", label: "Status", render: (r) => Object.entries((r as unknown as CovClass).by_status).map(([k, v]) => <Badge key={k} tone={COV_TONE[k] ?? "neutral"}>{v} {COV_TEXT[k] ?? k}</Badge>) },
              { key: "needs", label: "Free key to enter, then Verify", render: (r) => (r as unknown as CovClass).needs.join(" | ") || "none needed" },
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
