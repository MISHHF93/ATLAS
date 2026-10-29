"use client";
/** Macro and news context from official, keyless sources: economic calendar (BLS, US Treasury; FRED only once its key is verified),
 *  SEC EDGAR filings, official RSS (Federal Reserve, SEC, Bank of Canada) and GDELT headlines. Read-only context: nothing here can place an order.
 *  A source that fails says so; nothing is estimated. Times are Toronto time. Short lists, no nested scroll areas. */
import { useState } from "react";
import { Async, Badge, Card, DataTable, EmptyState, useApi, type Tone } from "../primitives";

type R = Record<string, unknown>;
type Src = { id: string; title: string; url: string; status: string; reason: string; count: number; in_window?: number };
type Cal = { as_of_toronto: string; events: { when_toronto: string; title: string; source: string; source_url: string; important: boolean; all_day: boolean }[]; sources: Src[]; note: string };
type Feed = { status: string; items: { title: string; url: string | null; when_toronto?: string | null }[]; source: Src };
type Fil = { status: string; items: { form: string; filed: string; title: string; url: string | null }[]; source: Src };
type News = { status: string; items: { title: string; url: string | null; domain: string | null; seen: string | null; tone: number | null }[]; source: Src; note: string };

const ST: Record<string, Tone> = { ok: "good", needs_key: "warn", needs_config: "warn", rate_limited: "warn", error: "bad", unknown_ticker: "neutral" };
const ST_TEXT: Record<string, string> = { ok: "live", needs_key: "needs verification", needs_config: "needs verification", rate_limited: "rate limited, retry soon", error: "unavailable", unknown_ticker: "not an SEC filer" };
const SRC_LABEL: Record<string, string> = { bls: "BLS", treasury: "Treasury", fred: "FRED" };

function SourceNote({ s, status }: { s?: Src; status?: string }) {
  if (!s) return null;
  const st = status ?? s.status;
  return <p className="ux-small"><Badge tone={ST[st] ?? "neutral"}>{ST_TEXT[st] ?? st}</Badge>{" "}{s.reason ? `${s.reason} ` : ""}<a className="ux-link" href={s.url} target="_blank" rel="noopener noreferrer">{s.title} ↗</a></p>;
}
const link = (t: string, u: string | null) => (u ? <a className="ux-link" href={u} target="_blank" rel="noopener noreferrer">{t}</a> : t);

export function CalendarCard() {
  const cal = useApi<Cal>("/api/context/calendar?days=14", 600000);
  return (
    <Card title="Economic calendar" span={2} subtitle="Next 14 days, Toronto time. Official release schedules only; importance shown only where the source flags it.">
      <Async state={cal} label="Reading release schedules">{(c) => (
        <>
          <DataTable rows={c.events.slice(0, 12) as unknown as R[]} empty={<EmptyState title="No scheduled releases listed" />} columns={[
            { key: "when_toronto", label: "When" },
            { key: "title", label: "Release", render: (r) => <>{String(r.title)}{r.important ? <> <Badge tone="info">flagged</Badge></> : null}</> },
            { key: "source", label: "Source", render: (r) => link(SRC_LABEL[String(r.source)] ?? String(r.source), String(r.source_url)) },
          ]} />
          {c.sources.map((s) => (s.status === "ok" && s.in_window ? null : <SourceNote key={s.id} s={s} />))}
          <p className="ux-small">{c.note}</p>
        </>
      )}</Async>
    </Card>
  );
}

export function RssCard({ source, title }: { source: string; title: string }) {
  const f = useApi<Feed>(`/api/context/rss?source=${source}&limit=6`, 600000);
  return (
    <Card title={title} span={1}>
      <Async state={f} label="Reading feed">{(d) => (
        <>
          {d.items.length ? <ul className="ux-list">{d.items.slice(0, 6).map((i, k) => <li key={k}><span>{link(i.title, i.url)}{i.when_toronto ? <span className="ux-small"> · {i.when_toronto}</span> : null}</span></li>)}</ul> : <EmptyState title="Nothing to show" />}
          <SourceNote s={d.source} status={d.status} />
        </>
      )}</Async>
    </Card>
  );
}

export function FilingsCard() {
  const [t, setT] = useState("");
  const [q, setQ] = useState("");
  const f = useApi<Fil>(`/api/context/filings?limit=8${q ? `&ticker=${encodeURIComponent(q)}` : ""}`, 600000);
  return (
    <Card title="SEC filings" span={2} subtitle="Latest 8-K filings across the market, or one US company's recent 8-K, 10-K, 10-Q and Form 4."
      actions={<form className="ux-form-row" data-tight onSubmit={(e) => { e.preventDefault(); setQ(t.trim().toUpperCase()); }}>
        <input aria-label="US ticker" value={t} maxLength={10} placeholder="Ticker, e.g. AAPL" onChange={(e) => setT(e.target.value)} />
        <button type="submit" className="ux-btn">Show</button>
      </form>}>
      <Async state={f} label="Reading EDGAR">{(d) => (
        <>
          {d.items.length ? <DataTable rows={d.items as unknown as R[]} columns={[
            { key: "filed", label: "Filed" }, { key: "form", label: "Form" },
            { key: "title", label: "Filing", render: (r) => link(String(r.title), r.url ? String(r.url) : null) },
          ]} /> : <EmptyState title={d.status === "ok" ? "No matching filings" : "Filings unavailable"}>{d.source.reason}</EmptyState>}
          <SourceNote s={d.source} status={d.status} />
        </>
      )}</Async>
    </Card>
  );
}

export function NewsCard() {
  const n = useApi<News>("/api/context/news?limit=8&timespan=1d", 600000);
  return (
    <Card title="Market headlines (GDELT)" span={1} subtitle="Headline metadata only. Tone is GDELT's own number, not an ATLAS score.">
      <Async state={n} label="Reading headlines">{(d) => (
        <>
          {d.items.length ? <ul className="ux-list">{d.items.slice(0, 8).map((i, k) => <li key={k}><span>{link(i.title, i.url)}<span className="ux-small"> · {i.domain}{i.tone !== null ? ` · tone ${i.tone.toFixed(1)}` : ""}</span></span></li>)}</ul> : <EmptyState title="No headlines right now" />}
          <SourceNote s={d.source} status={d.status} />
        </>
      )}</Async>
    </Card>
  );
}

export function ContextView() {
  return (
    <div className="ux-layout">
      <CalendarCard />
      <RssCard source="fed_press" title="Federal Reserve releases" />
      <FilingsCard />
      <RssCard source="boc_press" title="Bank of Canada releases" />
      <NewsCard />
      <RssCard source="sec_press" title="SEC press releases" />
    </div>
  );
}
