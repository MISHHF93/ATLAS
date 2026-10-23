"use client";

import { FounderPanel, useFounder } from "./FounderPanel";
import { DataTable, EquityDrawdown, FintracTimeline, Figure, LossBullets, MoneySankey, TaxWaterfall, fmt, type Flow } from "./Charts";

type Row = Record<string, unknown>;
const arr = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : []);
const num = (v: unknown) => Number(v ?? 0) || 0;
const day = (ts: unknown) => (typeof ts === "number" ? new Date(ts * 1000).toISOString().slice(0, 10) : String(ts ?? "").slice(0, 10));
const grid = { display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))" } as const;

function Status({ s }: { s: unknown }) {
  const t = String(s ?? "");
  const icon = /reject|fail|hit|overdue|blocked/i.test(t) ? "✕" : /pending|request|draft|open|received/i.test(t) ? "…" : "✓";
  return <span>{icon} {t.replaceAll("_", " ")}</span>;
}
function Rows({ title, rows, cols, empty = "Nothing here." }: { title: string; rows: Row[]; cols: Array<[string, string]>; empty?: string }) {
  return (
    <Figure title={title} caption={`${rows.length} rows`} table={<span />}>
      {rows.length ? <DataTable head={cols.map(c => c[1])} rows={rows.map(r => cols.map(([k]) => (k === "status" ? <Status s={r[k]} /> : /(_at|ts)$/.test(k) ? day(r[k]) : String(r[k] ?? "-"))))} /> : <p>{empty}</p>}
    </Figure>
  );
}
function Err({ e }: { e: string }) {
  return e ? <p role="alert" style={{ color: "#D55E00" }}>Unavailable: {e}. Seed demo data with <code>atlas-console seed-demo</code>.</p> : null;
}

export function InboxView() {
  const inbox = useFounder("inbox"), ap = useFounder("data/trading/approvals"), pay = useFounder("data/wallet/payouts");
  const items = arr(inbox.data?.items);
  const pend = arr(ap.data?.pending).map(p => ({ ...(p.intent as Row), expires_in_s: Math.round(num(p.expires_in_s)) }));
  const payouts = arr(pay.data?.payouts).filter(p => p.status === "pending_approval");
  return (<>
    <Err e={inbox.error} />
    <Rows title="Action needed" rows={items} cols={[["severity", "severity"], ["area", "area"], ["title", "item"], ["detail", "detail"]]} empty="Nothing waiting on you." />
    <div style={grid}>
      <Rows title="Paper order approvals (decide with atlas-owner + step-up)" rows={pend} cols={[["symbol", "symbol"], ["side", "side"], ["qty", "qty"], ["limit_price", "limit"], ["sleeve", "sleeve"], ["expires_in_s", "expires s"]]} />
      <Rows title="Payouts awaiting two approvals" rows={payouts} cols={[["id", "#"], ["destination", "to"], ["amount", "amount"], ["currency", "ccy"], ["purpose", "purpose"], ["status", "status"]]} />
    </div>
  </>);
}

export function MoneyView() {
  const pnl = useFounder("pnl"), eq = useFounder("data/trading/equity"), risk = useFounder("data/trading/risk"), led = useFounder("data/payments/ledger");
  const tb = (led.data?.trial_balance_cad ?? {}) as Record<string, unknown>;
  return (<>
    <Err e={eq.error} />
    <div style={grid}>
      <EquityDrawdown points={(arr(eq.data?.items) as unknown as Array<[string, number]>)} />
      <LossBullets gauges={arr(risk.data?.gauges) as unknown as Array<{ name: string; used: number; limit: number; unit?: string }>} />
    </div>
    <div style={grid}>
      <FounderPanel path="pnl" title="Founder P&L and 2% Safe stop room" />
      <Figure title="Trial balance (CAD)" caption="Non-custodial ledger: balances are records, the bank/custodian holds the money." table={<span />}>
        <DataTable head={["account", "CAD"]} rows={Object.entries(tb).map(([k, v]) => [k, fmt(v)])} />
      </Figure>
    </div>
    {pnl.error ? <Err e={pnl.error} /> : null}
  </>);
}

export function PaymentsView() {
  const tr = useFounder("data/payments/transfers"), sum = useFounder("data/payments/summary"), payees = useFounder("data/payments/payees");
  const rows = arr(tr.data?.transfers);
  const flows: Flow[] = Object.values(rows.filter(t => t.status !== "rejected").reduce((m: Record<string, Flow>, t) => {
    const k = `${t.source}>${t.payee}`; m[k] = m[k] ?? { from: String(t.source).replace("asset:bank:", "bank "), to: String(t.payee), value: 0 }; m[k].value += num(t.amount_cad); return m;
  }, {}));
  return (<>
    <Err e={tr.error} />
    <p style={{ fontSize: 13 }}>Manual transfer prep only: ATLAS prepares a payment sheet; a human executes it at the bank and records the confirmation with <code>atlas-payments</code> + step-up. Two approvals required: {String(sum.data?.required_approvals ?? 2)}.</p>
    <MoneySankey flows={flows} title="Outgoing transfers by payee (CAD)" />
    <Rows title="Transfers" rows={rows} cols={[["id", "#"], ["created_at", "created"], ["payee", "payee"], ["amount", "amount"], ["currency", "ccy"], ["rail", "rail"], ["purpose", "purpose"], ["status", "status"]]} />
    <Rows title="Payees" rows={arr(payees.data?.payees)} cols={[["id", "#"], ["name", "name"], ["rail", "rail"], ["status", "status"]]} />
  </>);
}

export function PortalView() {
  const w = useFounder("data/wallet/summary"), subs = useFounder("data/wallet/subscriptions"), reds = useFounder("data/wallet/redemptions"), pay = useFounder("data/wallet/payouts");
  const nav = (w.data?.nav ?? {}) as Row;
  const inv = arr(w.data?.investors);
  const flows: Flow[] = [
    ...arr(subs.data?.subscriptions).map(s => ({ from: String(s.investor ?? "investor"), to: "Fund (custodian)", value: num(s.amount) })),
    { from: "Fund (custodian)", to: "Redemptions", value: arr(reds.data?.redemptions).reduce((a, r) => a + num(r.units) * num(nav.nav_per_unit), 0) },
    { from: "Fund (custodian)", to: "Payouts", value: arr(pay.data?.payouts).reduce((a, p) => a + num(p.amount), 0) },
  ];
  return (<>
    <Err e={w.error} />
    <Figure title={`NAV ${String(nav.fund ?? "")}`} caption={`NAV/unit ${String(nav.nav_per_unit ?? "-")} on ${String(nav.nav_date ?? "-")}; net assets ${fmt(nav.net_assets)} CAD. Read from the administrator; the platform never holds investor money.`} table={<span />}>
      <DataTable head={["investor", "type", "units", "value CAD", "pending sub", "pending red units", "bank"]} rows={inv.map(i => [String(i.legal_name), String(i.entity_type), String(i.units), fmt(i.value_cad), fmt(i.pending_sub_cad), String(i.pending_red_units), String(i.bank)])} />
    </Figure>
    <MoneySankey flows={flows} title="Subscriptions, redemptions and payouts (CAD)" />
    <div style={grid}>
      <Rows title="Subscriptions" rows={arr(subs.data?.subscriptions)} cols={[["id", "#"], ["investor", "investor"], ["amount", "amount"], ["reference", "ref"], ["status", "status"]]} />
      <Rows title="Redemptions" rows={arr(reds.data?.redemptions)} cols={[["id", "#"], ["investor", "investor"], ["units", "units"], ["dealing_date", "dealing"], ["status", "status"]]} />
    </div>
    <Rows title="Payouts (two-person approval, CLI/step-up)" rows={arr(pay.data?.payouts)} cols={[["id", "#"], ["destination", "to"], ["amount", "amount"], ["rail", "rail"], ["purpose", "purpose"], ["status", "status"]]} />
  </>);
}

export function TaxView() {
  const t = useFounder("data/trading/tax");
  const d = arr(t.data?.dispositions);
  const sum = (k: string) => d.reduce((a, r) => a + num(r[k]), 0);
  const t1135 = arr(t.data?.t1135);
  return (<>
    <Err e={t.error} />
    <p style={{ fontSize: 13 }}>{String(t.data?.disclaimer ?? "NOT TAX ADVICE.")} Superficial-loss guard: {String(t.data?.superficial_guard ?? "-")}.</p>
    <TaxWaterfall proceeds={sum("proceeds")} acb={sum("acb")} denied={sum("denied_loss")} />
    <Rows title="T5008-style dispositions" rows={d} cols={[["date", "date"], ["property", "property"], ["qty", "qty"], ["proceeds", "proceeds"], ["acb", "ACB"], ["gain", "gain"], ["denied_loss", "denied"], ["allowable", "allowable"], ["fx_source", "FX"]]} />
    <div style={grid}>
      <Rows title="ACB pools" rows={arr(t.data?.pools)} cols={[["property", "property"], ["qty", "qty"], ["acb", "ACB"], ["acb_per_unit", "ACB/unit"]]} />
      <Rows title={`T1135 (threshold ${String(t.data?.t1135_threshold_cad ?? "100000")} CAD)`} rows={t1135} cols={Object.keys(t1135[0] ?? { taxpayer: 1, year: 1 }).map(k => [k, k] as [string, string])} empty="No specified foreign property tracked." />
    </div>
    <Rows title="Superficial loss warnings" rows={arr(t.data?.superficial).map(w => ({ warning: w }))} cols={[["warning", "warning"]]} empty="No superficial losses." />
  </>);
}

export function ComplianceView() {
  const c = useFounder("data/wallet/compliance"), f = useFounder("data/wallet/fintrac"), h = useFounder("data/wallet/hits"), venues = useFounder("venues");
  const recs = arr(f.data?.records).map(r => ({ date: String(r.due_date ?? day(r.first_ts)), label: `${r.kind} #${r.id}`, status: String(r.status) }));
  const sanctions = (c.data?.sanctions ?? {}) as Row;
  return (<>
    <Err e={c.error} />
    <div style={grid}>
      <Rows title="Sanctions hits (second review via CLI/step-up)" rows={arr(h.data?.hits)} cols={[["id", "#"], ["subject", "subject"], ["listed_name", "listed"], ["source", "list"], ["score", "score"], ["status", "status"]]} empty="No hits." />
      <Rows title={`Sanctions lists (threshold ${String(sanctions.threshold ?? "-")})`} rows={arr(sanctions.lists)} cols={[["source", "list"], ["entries", "entries"], ["age_days", "age days"], ["stale", "stale"], ["sample", "sample"]]} />
    </div>
    <FintracTimeline items={recs} />
    <Rows title="FINTRAC records (records only; the reporting entity files)" rows={arr(f.data?.records)} cols={[["id", "#"], ["kind", "kind"], ["amount", "amount"], ["currency", "ccy"], ["due_date", "due"], ["status", "status"]]} />
    <FounderPanel path="compliance" title="Privacy (PIPEDA) and venue registration checks" />
    {venues.error ? null : null}
  </>);
}
