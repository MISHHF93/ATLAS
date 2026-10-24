"use client";

import { ApprovalsCard } from "../../ui/pages/Console";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { FounderGate, useFounderData, useFounderStatus } from "./FounderPanel";
import { EquityDrawdown, FintracTimeline, LossBullets, MoneySankey, TaxWaterfall, fmt, type Flow } from "./Charts";
import { Async, Badge, Card, DataTable, EmptyState, Grid, StatTile, money, num as toNum, pct, useApi, type Column, type Tone } from "../../ui/primitives";
import { PnlTiles } from "../../ui/PnlTiles";

type Row = Record<string, unknown>;
const arr = (v: unknown): Row[] => (Array.isArray(v) ? (v as Row[]) : []);
const num = (v: unknown) => toNum(v) ?? 0;
const day = (ts: unknown) => (typeof ts === "number" ? new Date(ts * 1000).toISOString().slice(0, 10) : String(ts ?? "").slice(0, 10));

function statusTone(s: unknown): Tone {
  const t = String(s ?? "");
  if (/reject|fail|hit|overdue|blocked|stale/i.test(t)) return "bad";
  if (/pending|request|draft|open|received|review/i.test(t)) return "warn";
  return "good";
}
const StatusBadge = ({ s }: { s: unknown }) => <Badge tone={statusTone(s)}>{String(s ?? "—").replaceAll("_", " ")}</Badge>;

/** Column helper: [key, label, kind]. kind: "status" | "date" | "money" | "num" */
function cols(spec: Array<[string, string, ("status" | "date" | "money" | "num")?]>): Column<Row>[] {
  return spec.map(([key, label, kind]) => ({
    key, label, align: kind === "money" || kind === "num" ? "right" : "left",
    render: kind === "status" ? (r) => <StatusBadge s={r[key]} /> : kind === "date" ? (r) => day(r[key]) : kind === "money" ? (r) => fmt(r[key]) : undefined,
  }));
}

function TableCard({ title, subtitle, rows, columns, empty, span }: { title: string; subtitle?: string; rows: Row[]; columns: Column<Row>[]; empty: string; span?: 1 | 2 | "full" }) {
  return (
    <Card title={title} subtitle={subtitle ?? `${rows.length} ${rows.length === 1 ? "row" : "rows"}`} span={span}>
      <DataTable caption={title} rows={rows} columns={columns} maxHeight={320} empty={<EmptyState title={empty} />} />
    </Card>
  );
}

/* ----------------------------------------------------------------- Inbox */
export function InboxView() {
  const inbox = useApi<{ items?: Row[] }>("/api/founder/inbox", 30000);
  const status = useFounderStatus();
  const ok = status.data?.available;
  const ap = useFounderData(ok, "trading/approvals");
  const pay = useFounderData(ok, "wallet/payouts");
  const pend = arr(ap.data?.pending).map((p) => ({ ...(p.intent as Row), expires_in_s: Math.round(num(p.expires_in_s)) }));
  const payouts = arr(pay.data?.payouts).filter((p) => p.status === "pending_approval");
  return (
    <>
      <Card title="Action needed" subtitle="Items from compliance, venues and the ledgers that need a decision.">
        <Async state={inbox} label="Loading inbox" isEmpty={(d) => !arr(d.items).length}
          empty={<EmptyState title="All clear" icon={<ShieldCheck size={20} />}>Nothing is waiting on you.</EmptyState>}>
          {(d) => (
            <DataTable<Row> caption="Action needed" rows={arr(d.items)} columns={[
              { key: "severity", label: "Severity", render: (r) => <Badge tone={/high|urgent/.test(String(r.severity)) ? "bad" : "warn"}>{String(r.severity ?? "normal")}</Badge> },
              { key: "area", label: "Area" },
              { key: "title", label: "Item", render: (r) => (r.href ? <Link className="ux-link" href={String(r.href)}>{String(r.title)}</Link> : String(r.title ?? "")) },
              { key: "detail", label: "Detail" },
            ]} />
          )}
        </Async>
      </Card>
      <ApprovalsCard />
      <FounderGate status={status}>
        <div className="ux-grid" data-cols={2}>
          <TableCard title="Paper order approvals (demo ledger)" subtitle="Decide with atlas-owner and step-up auth" rows={pend}
            columns={cols([["symbol", "Symbol"], ["side", "Side"], ["qty", "Qty", "num"], ["limit_price", "Limit", "money"], ["sleeve", "Sleeve"], ["expires_in_s", "Expires (s)", "num"]])}
            empty="No paper orders waiting for approval" />
          <TableCard title="Payouts awaiting two approvals" rows={payouts}
            columns={cols([["id", "#"], ["destination", "To"], ["amount", "Amount", "money"], ["currency", "Ccy"], ["purpose", "Purpose"], ["status", "Status", "status"]])}
            empty="No payouts waiting" />
        </div>
      </FounderGate>
    </>
  );
}

/* ----------------------------------------------------------------- Money */
export function MoneyView() {
  const status = useFounderStatus();
  const ok = status.data?.available;
  const eq = useFounderData(ok, "trading/equity"), risk = useFounderData(ok, "trading/risk"), led = useFounderData(ok, "payments/ledger");
  const accounts = arr(led.data?.accounts);
  return (
    <>
      <PnlTiles />
      <FounderGate status={status}>
        <div className="ux-grid" data-cols={2}>
          <EquityDrawdown points={arr(eq.data?.items) as unknown as Array<[string, number]>} />
          <LossBullets gauges={arr(risk.data?.gauges) as unknown as Array<{ name: string; used: number; limit: number; unit?: string }>} />
        </div>
        <TableCard title="Ledger accounts" subtitle={`Trial balance ${fmt(led.data?.trial_balance_cad)} CAD. Balances are records; the bank or custodian holds the money.`}
          rows={accounts} columns={cols([["code", "Account"], ["kind", "Kind"], ["currency", "Ccy"], ["balance_cad", "Balance (CAD)", "money"]])} empty="No ledger accounts yet" />
      </FounderGate>
    </>
  );
}

/* -------------------------------------------------------------- Payments */
export function PaymentsView() {
  const status = useFounderStatus();
  const ok = status.data?.available;
  const tr = useFounderData(ok, "payments/transfers"), sum = useFounderData(ok, "payments/summary"), payees = useFounderData(ok, "payments/payees");
  const rows = arr(tr.data?.transfers);
  const flows: Flow[] = Object.values(rows.filter((t) => t.status !== "rejected").reduce((m: Record<string, Flow>, t) => {
    const k = `${t.source}>${t.payee}`; m[k] = m[k] ?? { from: String(t.source).replace("asset:bank:", "bank "), to: String(t.payee), value: 0 }; m[k].value += num(t.amount_cad); return m;
  }, {}));
  return (
    <>
      <div className="ux-callout">ATLAS only prepares payment sheets. A person makes the transfer at the bank and records the confirmation with <code className="ux-code">atlas-payments</code> and step-up auth. Each transfer needs {String(sum.data?.required_approvals ?? 2)} approvals.</div>
      <FounderGate status={status}>
        <MoneySankey flows={flows} title="Outgoing transfers by payee (CAD)" />
        <TableCard title="Transfers" rows={rows} empty="No transfers recorded"
          columns={cols([["id", "#"], ["created_at", "Created", "date"], ["payee", "Payee"], ["amount", "Amount", "money"], ["currency", "Ccy"], ["rail", "Rail"], ["purpose", "Purpose"], ["status", "Status", "status"]])} />
        <TableCard title="Payees" rows={arr(payees.data?.payees)} empty="No payees yet" columns={cols([["id", "#"], ["name", "Name"], ["rail", "Rail"], ["status", "Status", "status"]])} />
      </FounderGate>
    </>
  );
}

/* --------------------------------------------------------- Partner wallet */
export function PortalView() {
  const status = useFounderStatus();
  const ok = status.data?.available;
  const w = useFounderData(ok, "wallet/summary"), subs = useFounderData(ok, "wallet/subscriptions"), reds = useFounderData(ok, "wallet/redemptions"), pay = useFounderData(ok, "wallet/payouts");
  const nav = (w.data?.nav ?? {}) as Row;
  const inv = arr(w.data?.investors);
  const flows: Flow[] = [
    ...arr(subs.data?.subscriptions).map((s) => ({ from: String(s.investor ?? "investor"), to: "Fund (custodian)", value: num(s.amount) })),
    { from: "Fund (custodian)", to: "Redemptions", value: arr(reds.data?.redemptions).reduce((a, r) => a + num(r.units) * num(nav.nav_per_unit), 0) },
    { from: "Fund (custodian)", to: "Payouts", value: arr(pay.data?.payouts).reduce((a, p) => a + num(p.amount), 0) },
  ];
  return (
    <>
      <div className="ux-callout">Read-only view of money held by the partner custodian and fund administrator. ATLAS never holds or moves partner money.</div>
      <FounderGate status={status}>
        <Grid cols={3}>
          <StatTile label="Net assets (CAD)" value={nav.net_assets === undefined ? "—" : fmt(nav.net_assets)} hint={String(nav.fund ?? "")} />
          <StatTile label="NAV per unit" value={String(nav.nav_per_unit ?? "—")} hint={nav.nav_date ? `as of ${String(nav.nav_date)}` : undefined} />
          <StatTile label="Partners" value={String(inv.length)} />
        </Grid>
        <TableCard title="Partner holdings" subtitle="From the administrator’s register" rows={inv} empty="No partners on the register"
          columns={cols([["legal_name", "Partner"], ["entity_type", "Type"], ["units", "Units", "num"], ["value_cad", "Value (CAD)", "money"], ["pending_sub_cad", "Pending sub.", "money"], ["pending_red_units", "Pending red. units", "num"], ["bank", "Bank"]])} />
        <MoneySankey flows={flows} title="Subscriptions, redemptions and payouts (CAD)" />
        <div className="ux-grid" data-cols={2}>
          <TableCard title="Subscriptions" rows={arr(subs.data?.subscriptions)} empty="No subscriptions" columns={cols([["id", "#"], ["investor", "Partner"], ["amount", "Amount", "money"], ["reference", "Ref"], ["status", "Status", "status"]])} />
          <TableCard title="Redemptions" rows={arr(reds.data?.redemptions)} empty="No redemptions" columns={cols([["id", "#"], ["investor", "Partner"], ["units", "Units", "num"], ["dealing_date", "Dealing"], ["status", "Status", "status"]])} />
        </div>
        <TableCard title="Payouts" subtitle="Two-person approval through the CLI with step-up" rows={arr(pay.data?.payouts)} empty="No payouts"
          columns={cols([["id", "#"], ["destination", "To"], ["amount", "Amount", "money"], ["rail", "Rail"], ["purpose", "Purpose"], ["status", "Status", "status"]])} />
      </FounderGate>
    </>
  );
}

/* ------------------------------------------------------------------- Tax */
export function TaxView() {
  const status = useFounderStatus();
  const t = useFounderData(status.data?.available, "trading/tax");
  const d = arr(t.data?.dispositions);
  const sum = (k: string) => d.reduce((a, r) => a + num(r[k]), 0);
  const t1135 = arr(t.data?.t1135);
  return (
    <>
      <div className="ux-callout">Not tax advice. Figures are estimates for your accountant.</div>
      <FounderGate status={status}>
        {t.data ? <p className="ux-muted ux-small">{String(t.data.disclaimer ?? "")} Superficial-loss guard: {String(t.data.superficial_guard ?? "—")}.</p> : null}
        <TaxWaterfall proceeds={sum("proceeds")} acb={sum("acb")} denied={sum("denied_loss")} />
        <TableCard title="Dispositions (T5008 style)" rows={d} empty="No dispositions this year"
          columns={cols([["date", "Date"], ["property", "Property"], ["qty", "Qty", "num"], ["proceeds", "Proceeds", "money"], ["acb", "ACB", "money"], ["gain", "Gain", "money"], ["denied_loss", "Denied", "money"], ["allowable", "Allowable", "money"], ["fx_source", "FX"]])} />
        <div className="ux-grid" data-cols={2}>
          <TableCard title="ACB pools" rows={arr(t.data?.pools)} empty="No pools" columns={cols([["property", "Property"], ["qty", "Qty", "num"], ["acb", "ACB", "money"], ["acb_per_unit", "ACB/unit", "money"]])} />
          <TableCard title={`T1135 (threshold ${String(t.data?.t1135_threshold_cad ?? "100000")} CAD)`} rows={t1135} empty="No specified foreign property tracked"
            columns={cols(Object.keys(t1135[0] ?? { taxpayer: 1, year: 1 }).map((k) => [k, k.replaceAll("_", " ")] as [string, string]))} />
        </div>
        <TableCard title="Superficial loss warnings" rows={arr(t.data?.superficial).map((w) => ({ warning: w }))} empty="No superficial losses" columns={cols([["warning", "Warning"]])} />
      </FounderGate>
    </>
  );
}

/* ------------------------------------------------------------ Compliance */
type Venue = Row & { venue?: string; legal_entity?: string; regulator?: string; registration?: string; last_verified?: string; paper_only?: boolean };
export function ComplianceView() {
  const comp = useApi<Row>("/api/founder/compliance", 60000);
  const venues = useApi<{ venues?: Venue[] }>("/api/founder/venues", 60000);
  const status = useFounderStatus();
  const ok = status.data?.available;
  const c = useFounderData(ok, "wallet/compliance"), f = useFounderData(ok, "wallet/fintrac"), h = useFounderData(ok, "wallet/hits");
  const recs = arr(f.data?.records).map((r) => ({ date: String(r.due_date ?? day(r.first_ts)), label: `${r.kind} #${r.id}`, status: String(r.status) }));
  const sanctions = (c.data?.sanctions ?? {}) as Row;
  const problems = (comp.data?.venue_problems ?? {}) as Record<string, string>;
  return (
    <>
      <Card title="Venue registration" subtitle="Each venue must be registered to serve Ontario clients. Re-verify anything flagged.">
        <Async state={venues} label="Loading venues" isEmpty={(d) => !arr(d.venues).length} empty={<EmptyState title="No venues configured" />}>
          {(d) => (
            <DataTable<Venue> caption="Venues" rows={(d.venues ?? []) as Venue[]} columns={[
              { key: "venue", label: "Venue" }, { key: "legal_entity", label: "Legal entity" }, { key: "regulator", label: "Regulator" },
              { key: "registration", label: "Registration", render: (r) => <Badge tone={problems[String(r.venue)] ? "bad" : "good"}>{String(r.registration ?? "").replaceAll("_", " ")}</Badge> },
              { key: "last_verified", label: "Last verified" },
              { key: "paper_only", label: "Paper only" },
            ]} />
          )}
        </Async>
      </Card>
      <FounderGate status={status}>
        <div className="ux-grid" data-cols={2}>
          <TableCard title="Sanctions hits" subtitle="Second review through the CLI with step-up" rows={arr(h.data?.hits)} empty="No sanctions hits"
            columns={cols([["id", "#"], ["subject", "Subject"], ["listed_name", "Listed"], ["source", "List"], ["score", "Score", "num"], ["status", "Status", "status"]])} />
          <TableCard title={`Sanctions lists (match threshold ${String(sanctions.threshold ?? "—")})`} rows={arr(sanctions.lists)} empty="No lists loaded"
            columns={cols([["source", "List"], ["entries", "Entries", "num"], ["age_days", "Age (days)", "num"], ["stale", "Stale"]])} />
        </div>
        <FintracTimeline items={recs} />
        <TableCard title="FINTRAC records" subtitle="Records only; the reporting entity files them" rows={arr(f.data?.records)} empty="No FINTRAC records"
          columns={cols([["id", "#"], ["kind", "Kind"], ["amount", "Amount", "money"], ["currency", "Ccy"], ["due_date", "Due"], ["status", "Status", "status"]])} />
      </FounderGate>
      <Async state={comp} label="Loading policy">
        {(d) => (
          <Card title="Policy" subtitle="How ATLAS handles privacy and FINTRAC record-keeping">
            <dl className="ux-dl">
              <dt>Privacy</dt><dd>{String(d.privacy ?? "—")}</dd>
              <dt>FINTRAC mode</dt><dd>{String(((d.fintrac ?? {}) as Row).mode ?? "—").replaceAll("_", " ")}</dd>
              <dt>Large-transaction threshold</dt><dd>{fmt(((d.fintrac ?? {}) as Row).threshold_cad, 0)} CAD</dd>
              <dt>Retention</dt><dd>{String(((d.fintrac ?? {}) as Row).retention_years ?? "—")} years</dd>
              <dt>Sanctions lists</dt><dd>{arr(((d.sanctions ?? {}) as Row).lists).map(String).join(", ") || "—"}</dd>
            </dl>
          </Card>
        )}
      </Async>
    </>
  );
}
