"use client";
/** ext-1 views (seven-repo gap): options greeks/IV, DCF + SEC fundamentals + investor personas, dossier/conviction and the
 *  deterministic agent pipeline, watchlist scan + VWAP/POC + Pine export, and broker/alerts/MCP status. Research only:
 *  nothing here places an order. Unavailable data is shown as unavailable, never estimated. */
import { useState } from "react";
import type { Fresh } from "../FreshBadge";
import { ActionButton, ActionResult, Async, Badge, Card, DataTable, EmptyState, useAction, useApi } from "../primitives";

type R = Record<string, unknown>;
const f = (v: unknown, d = 2) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : v === null || v === undefined ? "—" : String(v));
const big = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—");
const fr = (s: { data: { freshness?: Fresh } | null }) => (s.data?.freshness ?? null) as Fresh | null;
const SYMS = ["BTCUSDT", "ETHUSDT", "GC", "SI", "SPY", "ES"];
const ADVISORY = "Research-only advisory. Not investment advice; cannot place or size an order.";

function Pick({ v, set, opts = SYMS, label = "Symbol" }: { v: string; set: (s: string) => void; opts?: string[]; label?: string }) {
  return <label className="ux-form-row">{label}{" "}<select style={{ minWidth: 120 }} aria-label={label} value={v} onChange={(e) => set(e.target.value)}>{opts.map((s) => <option key={s}>{s}</option>)}</select></label>;
}
function Num({ label, v, set, step = "any" }: { label: string; v: number; set: (n: number) => void; step?: string }) {
  return <label className="ux-form-row">{label}{" "}<input type="number" step={step} value={v} aria-label={label} onChange={(e) => set(Number(e.target.value))} style={{ width: 110 }} /></label>;
}
const Unavail = ({ what, why }: { what: string; why?: unknown }) => <EmptyState title={`${what} unavailable`}>{String(why ?? "No source configured.")} Nothing is estimated.</EmptyState>;

/* ---------- Options ---------- */
export function OptionsView() {
  const [p, setP] = useState({ spot: 100, strike: 100, tte: 0.25, vol: 0.2, r: 0.04, right: "call", mkt: 4.5 });
  const q = `spot=${p.spot}&strike=${p.strike}&tte_years=${p.tte}&vol=${p.vol}&r=${p.r}&right=${p.right}`;
  const g = useApi<{ price: number; greeks: Record<string, number> }>(`/api/ext/options/greeks?${q}`, 3600000);
  const iv = useApi<{ implied_vol: number | null; status: string }>(`/api/ext/options/iv?price=${p.mkt}&spot=${p.spot}&strike=${p.strike}&tte_years=${p.tte}&r=${p.r}&right=${p.right}`, 3600000);
  const ch = useApi<{ status: string; reason: string }>("/api/ext/options/chain?symbol=SPY", 3600000);
  const s = (k: keyof typeof p) => (n: number) => setP({ ...p, [k]: n });
  return (
    <div className="ux-layout">
      <Card title="Black-Scholes calculator" span={2} subtitle="European option price and greeks. Theta is per calendar day; vega and rho per 1 percentage point.">
        <div className="ux-form-grid">
          <Num label="Spot" v={p.spot} set={s("spot")} /><Num label="Strike" v={p.strike} set={s("strike")} /><Num label="Years to expiry" v={p.tte} set={s("tte")} />
          <Num label="Volatility" v={p.vol} set={s("vol")} /><Num label="Rate" v={p.r} set={s("r")} />
          <Pick label="Right" v={p.right} set={(x) => setP({ ...p, right: x })} opts={["call", "put"]} />
        </div>
        <Async state={g} label="Pricing">{(d) => <DataTable rows={[{ k: "price", v: d.price }, ...Object.entries(d.greeks).filter(([k]) => k !== "price").map(([k, v]) => ({ k, v }))] as R[]}
          columns={[{ key: "k", label: "Measure" }, { key: "v", label: "Value", align: "right", render: (r) => f(r.v, 4) }]} />}</Async>
      </Card>
      <Card title="Implied volatility" subtitle="Solves the volatility that reproduces a quoted option price (bisection).">
        <Num label="Option price" v={p.mkt} set={s("mkt")} />
        <Async state={iv} label="Solving">{(d) => <p>{d.implied_vol === null ? "No volatility reproduces this price (outside no-arbitrage bounds)." : `IV ${(d.implied_vol * 100).toFixed(2)}%`}</p>}</Async>
      </Card>
      <Card title="Options chain" subtitle="Live chains need a licensed or keyed provider.">
        <Async state={ch} label="Checking">{(d) => <Unavail what="Options chain" why={d.reason} />}</Async>
      </Card>
    </div>
  );
}

/* ---------- Valuation ---------- */
type DCFRes = { result: { enterprise_or_equity_value: number; equity_value: number; per_share: number | null; pv_forecast: number; pv_terminal: number; terminal_share: number;
  forecast: { year: number; cash_flow: number; pv: number }[] }; sensitivity: R[] };
export function ValuationView() {
  const [d, setD] = useState({ method: "FCFF", base: 1000, g: 0.05, years: 5, rate: 0.09, tg: 0.02, debt: 0, shares: 100 });
  const dcf = useAction<DCFRes>("/api/ext/dcf");
  const [tk, setTk] = useState("AAPL");
  const fu = useApi<{ status: string; reason?: string; entity?: string; periods: { period_end: string; income: R; balance: R; cash_flow: R }[]; metrics: R }>(`/api/ext/fundamentals?ticker=${tk}`, 3600000);
  const pe = useApi<{ fundamentals_status: Record<string, string>; portfolio_manager: { weight_matrix: Record<string, Record<string, number>>; target_weights: Record<string, number>;
    cash_weight: number; disagreements: R[] } | null }>(`/api/ext/personas?tickers=AAPL,MSFT,KO`, 3600000);
  const body = { method: d.method, base_cash_flow: d.base, growth: Array(d.years).fill(d.g), discount_rate: d.rate, terminal_growth: d.tg, net_debt: d.debt, shares_outstanding: d.shares };
  const s = (k: keyof typeof d) => (n: number) => setD({ ...d, [k]: n });
  return (
    <div className="ux-layout">
      <Card title="Discounted cash flow" span={2} subtitle="FCFF (discount at WACC, subtract net debt) or FCFE (discount at cost of equity). A model of your inputs, not a price target.">
        <div className="ux-form-grid">
          <Pick label="Method" v={d.method} set={(x) => setD({ ...d, method: x })} opts={["FCFF", "FCFE"]} />
          <Num label="Base cash flow" v={d.base} set={s("base")} /><Num label="Growth / yr" v={d.g} set={s("g")} /><Num label="Years" v={d.years} set={s("years")} step="1" />
          <Num label="Discount rate" v={d.rate} set={s("rate")} /><Num label="Terminal growth" v={d.tg} set={s("tg")} /><Num label="Net debt" v={d.debt} set={s("debt")} /><Num label="Shares" v={d.shares} set={s("shares")} />
        </div>
        <ActionButton action={dcf} body={body} tone="primary">Run DCF</ActionButton>
        <ActionResult action={dcf} />
        {dcf.result ? <>
          <p>Value {big(dcf.result.result.enterprise_or_equity_value)} · equity {big(dcf.result.result.equity_value)} · per share {f(dcf.result.result.per_share)} · terminal share {f(dcf.result.result.terminal_share * 100, 1)}%</p>
          <DataTable rows={dcf.result.sensitivity} columns={Object.keys(dcf.result.sensitivity[0] ?? {}).map((k) => ({ key: k, label: k, align: "right" as const, render: (r: R) => f(r[k], 3) }))} />
        </> : null}
      </Card>
      <Card title="SEC fundamentals" subtitle="EDGAR companyfacts, annual 10-K facts as filed (point-in-time). Needs ATLAS_SEC_USER_AGENT in the local .env.">
        <Pick label="Ticker" v={tk} set={setTk} opts={["AAPL", "MSFT", "KO", "JPM", "XOM"]} />
        <Async state={fu} label="Loading filings">{(x) => x.status !== "ok" ? <Unavail what="Fundamentals" why={x.reason ?? x.status} /> :
          <DataTable rows={Object.entries(x.metrics).map(([k, v]) => ({ k, v })) as R[]} columns={[{ key: "k", label: "Metric" }, { key: "v", label: "Value", align: "right", render: (r) => f(r.v, 3) }]} />}</Async>
      </Card>
      <Card title="Investor personas and weights" span="full" subtitle="Buffett, Graham, Druckenmiller, Wood and Burry checklists scored on filed numbers; the portfolio manager caps any name at 25% and keeps the rest in cash.">
        <Async state={pe} label="Scoring">{(x) => !x.portfolio_manager ? <Unavail what="Persona scores" why={`fundamentals: ${Object.entries(x.fundamentals_status).map(([k, v]) => `${k} ${v}`).join(", ")}`} /> : <>
          <DataTable rows={Object.entries(x.portfolio_manager.weight_matrix).map(([t, m]) => ({ t, ...m, w: x.portfolio_manager!.target_weights[t] })) as R[]}
            columns={[{ key: "t", label: "Ticker" }, ...["buffett", "graham", "druckenmiller", "wood", "burry"].map((p) => ({ key: p, label: p, align: "right" as const, render: (r: R) => f(r[p]) })),
              { key: "w", label: "Target weight", align: "right", render: (r) => `${f(Number(r.w) * 100, 1)}%` }]} />
          <p>Cash {f(x.portfolio_manager.cash_weight * 100, 1)}% · disagreements logged: {x.portfolio_manager.disagreements.length}</p></>}</Async>
      </Card>
    </div>
  );
}

/* ---------- Dossier + agent pipeline ---------- */
type Comp = { rule: string; points: number; why: string };
type Pipe = { conviction?: never; analysts: { analyst: string; stance: number; status?: string; why?: string }[]; debate: { rounds: { round: number; bull: string | null; bear: string | null }[]; net: number; verdict: string };
  trader_proposal: R | null; risk_manager: { status: string; violations?: string[]; reason?: string }; portfolio_manager: { decision: string; why: string }; freshness?: Fresh };
export function AgentsView() {
  const [sym, setSym] = useState("BTCUSDT");
  const ds = useApi<{ conviction: { score: number | null; label: string; components: Comp[] }; trade_levels: R; news: { reason: string }; freshness?: Fresh; technicals: { status: string } }>(`/api/ext/dossier?symbol=${sym}`, 60000);
  const pl = useApi<Pipe>(`/api/ext/pipeline?symbol=${sym}`, 60000);
  const tone = (l: string) => (l === "BUY" ? "good" : l === "SELL" ? "bad" : "neutral") as "good" | "bad" | "neutral";
  return (
    <div className="ux-layout">
      <Card title="Dossier and conviction" span={2} fresh={fr(ds)} subtitle={`Conviction = 50 + named rule points, clamped 1–100. BUY ≥ 65, SELL ≤ 35, else WATCH. ${ADVISORY}`}
        actions={<Pick v={sym} set={setSym} />}>
        <Async state={ds} label="Building dossier">{(d) => d.technicals.status !== "ok" ? <EmptyState title="No daily bars in the feed for this symbol">No conviction is computed without data.</EmptyState> : <>
          <p><Badge tone={tone(d.conviction.label)}>{d.conviction.label}</Badge> {d.conviction.score}/100</p>
          <DataTable rows={d.conviction.components as unknown as R[]} columns={[{ key: "rule", label: "Rule" }, { key: "points", label: "Points", align: "right", render: (r) => f(r.points, 0) }, { key: "why", label: "Why" }]} />
          {d.trade_levels.side ? <p>{String(d.trade_levels.side)}: entry {f(d.trade_levels.entry, 4)} ({String(d.trade_levels.entry_ref)}) · stop {f(d.trade_levels.stop, 4)} · target {f(d.trade_levels.target, 4)} ({String(d.trade_levels.target_ref)}) · R:R {f(d.trade_levels.reward_risk)}</p> : <p>No entry/exit levels (WATCH).</p>}
          <p className="ux-muted">News: {d.news.reason}</p></>}</Async>
      </Card>
      <Card title="Agent pipeline" fresh={fr(pl)} subtitle="Analysts → bull/bear debate → trader → control-plane dry run → portfolio manager. Deterministic, no LLM; never submits.">
        <Async state={pl} label="Running pipeline">{(p) => <>
          <DataTable rows={p.analysts as unknown as R[]} columns={[{ key: "analyst", label: "Analyst" }, { key: "stance", label: "Stance", align: "right", render: (r) => f(r.stance, 1) }, { key: "status", label: "Status", render: (r) => String(r.status ?? "ok") }]} />
          <p>Debate: net {f(p.debate.net, 1)} → {p.debate.verdict} ({p.debate.rounds.length} rounds)</p>
          <p>Trader: {p.trader_proposal ? `${p.trader_proposal.side} ${p.trader_proposal.instrument_id} $${p.trader_proposal.notional_usd}, stop ${p.trader_proposal.stop_distance_bps} bps` : "no proposal"}</p>
          <p>Risk manager: {p.risk_manager.status}{p.risk_manager.violations?.length ? ` (${p.risk_manager.violations.join("; ")})` : ""}</p>
          <p>Portfolio manager: <Badge>{p.portfolio_manager.decision}</Badge></p></>}</Async>
      </Card>
    </div>
  );
}

/* ---------- Watchlist scan + VWAP/POC + Pine ---------- */
export function ScanView() {
  const [sym, setSym] = useState("BTCUSDT");
  const sc = useApi<{ results: { symbol: string; status: string; events?: R[]; freshness?: Fresh }[] }>(`/api/ext/scan?symbols=${SYMS.join(",")}`, 60000);
  const vw = useApi<{ session_vwap: number | null; profile: { poc: number; vah: number; val: number } | null; last_close: number | null; freshness?: Fresh }>(`/api/ext/vwap?symbol=${sym}`, 60000);
  const pl = useApi<{ strategies: string[]; note: string }>("/api/ext/pine", 3600000);
  const [sid, setSid] = useState("sfp");
  const pg = useApi<{ pine: string; atlas_backtest: R; freshness?: Fresh }>(`/api/ext/pine/${sid}?symbol=${sym}`, 3600000);
  const rows = (sc.data?.results ?? []).flatMap((r) => (r.events?.length ? r.events.map((e) => ({ symbol: r.symbol, ...e })) : [{ symbol: r.symbol, kind: r.status === "no_data" ? "no bars in feed" : "no breaches" }])) as R[];
  return (
    <div className="ux-layout">
      <Card title="Watchlist scan" span="full" subtitle="Latest-bar crossings of classic pivots, 60-bar Fibonacci levels and support/resistance zones (3+ touches).">
        <Async state={sc} label="Scanning">{() => <DataTable rows={rows} columns={[{ key: "symbol", label: "Symbol" }, { key: "kind", label: "Event" }, { key: "level", label: "Level" }, { key: "price", label: "Price", align: "right", render: (r) => f(r.price, 4) }, { key: "direction", label: "Direction" }]} />}</Async>
      </Card>
      <Card title="VWAP and volume profile" fresh={fr(vw)} subtitle="Session VWAP and the point of control / 70% value area of the last 500 bars." actions={<Pick v={sym} set={setSym} />}>
        <Async state={vw} label="Computing">{(v) => !v.profile ? <EmptyState title="No bars in the feed for this symbol">Nothing is estimated.</EmptyState> :
          <p>Close {f(v.last_close, 4)} · VWAP {f(v.session_vwap, 4)} · POC {f(v.profile.poc, 4)} · VA {f(v.profile.val, 4)}–{f(v.profile.vah, 4)}</p>}</Async>
      </Card>
      <Card title="Pine v5 export" span={2} fresh={fr(pg)} subtitle={pl.data?.note ?? "Pine text export"} actions={<Pick label="Strategy" v={sid} set={setSid} opts={pl.data?.strategies ?? ["sfp"]} />}>
        <Async state={pg} label="Generating">{(x) => <>
          <p>ATLAS replay ({String(x.atlas_backtest.status)}): trades {f(x.atlas_backtest.n_trades, 0)} · win rate {f(x.atlas_backtest.win_rate)} · profit factor {f(x.atlas_backtest.profit_factor)} · max DD {f(x.atlas_backtest.max_drawdown_r)} R</p>
          <pre className="ux-pre">{x.pine}</pre></>}</Async>
      </Card>
    </div>
  );
}

/* ---------- Broker / alerts / MCP ---------- */
export function BrokerView() {
  const st = useApi<{ status: string; reason: string; base_url: string | null }>("/api/ext/alpaca/status", 30000);
  const ac = useApi<{ status: string; data: R | null; reason?: string }>("/api/ext/alpaca/account", 60000);
  const al = useApi<{ enabled: boolean; channels_configured: Record<string, boolean> }>("/api/ext/alerts/status", 60000);
  const mc = useApi<{ tools: { name: string; description: string }[] }>("/api/ext/mcp/tools", 3600000);
  return (
    <div className="ux-layout">
      <Card title="Alpaca paper broker" span={2} subtitle="Paper endpoint only; the live endpoint is refused. Keys are read from the local .env. Every order passes the control plane first.">
        <Async state={st} label="Checking">{(s) => <p><Badge tone={s.status === "ok" ? "good" : "neutral"}>{s.status.replace(/_/g, " ")}</Badge> {s.reason}</p>}</Async>
        <Async state={ac} label="Account">{(a) => a.status !== "ok" ? null : <DataTable rows={Object.entries(a.data ?? {}).map(([k, v]) => ({ k, v })) as R[]} columns={[{ key: "k", label: "Field" }, { key: "v", label: "Value", align: "right", render: (r) => String(r.v) }]} />}</Async>
      </Card>
      <Card title="Alerts" subtitle="Telegram, Discord and Slack research alerts. Off unless ATLAS_ALERTS_ENABLED=true and a channel is set in the local .env.">
        <Async state={al} label="Checking">{(a) => <p><Badge tone={a.enabled ? "good" : "neutral"}>{a.enabled ? "enabled" : "disabled"}</Badge> {Object.entries(a.channels_configured).map(([k, v]) => `${k}: ${v ? "set" : "not set"}`).join(" · ")}</p>}</Async>
      </Card>
      <Card title="Agent tools (MCP)" span="full" subtitle="Read-only research tools, listed over HTTP at /api/ext/mcp/tools and over stdio by scripts/atlas_mcp_stdio.py. No order tool is exposed.">
        <Async state={mc} label="Listing">{(m) => <DataTable rows={m.tools as unknown as R[]} columns={[{ key: "name", label: "Tool" }, { key: "description", label: "What it does" }]} />}</Async>
      </Card>
    </div>
  );
}
