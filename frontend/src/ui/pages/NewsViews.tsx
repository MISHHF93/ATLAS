"use client";
/** News & AI review (Research). Per-user watchlist, a feed of official filings/releases (tier 1) and unverified headlines (tier 3), each linked to its
 *  source, with deterministic hype/pump-scam flags and, only when a verified paid-tier Gemini key exists, grounded LLM scores. The LLM Reviewer can only
 *  restrict an ML proposal (veto or reduce confidence); it never adds or enlarges a trade and never executes. Everything here is advisory:
 *  execution_permission none. If the LLM is unavailable the reviewer says "no opinion" and the existing pipeline is unchanged. Times are Toronto time. */
import { useState } from "react";
import { Async, Badge, Card, DataTable, EmptyState, StatTile, useApi, type Tone } from "../primitives";
import { api } from "./acct";

type R = Record<string, unknown>;
type Llm = { enabled: boolean; reason: string; model?: string | null; gemini_state?: string; gemini_tier?: string | null };
type Elig = { eligible: boolean; reasons: string[]; min_n: number; effect?: { groups?: Record<string, { n: number; mean_r?: number | null }>; restricted_minus_allowed?: { mean: number; ci95: [number, number] } | null } };
type Status = { scope: string; llm: Llm; reviewer: { mode: string; eligibility: Elig }; sources: { id: string; title: string; state: string; needs?: string | null; provides?: string; url?: string }[];
  counts: Record<string, number>; watchlist: string[]; execution_permission: string };
type Flag = { type: string; why?: string; quote?: string };
type Item = { id: string; ticker: string; source: string; tier: number; tier_label: string; kind: string; published_at: number; url: string; title: string; form?: string | null;
  annotation: { event_type?: string | null; sentiment?: number | null; materiality?: number | null; grounded: boolean; evidence_quote?: string | null; hype_flags: Flag[]; analyzer?: string | null };
  reviewer: { review_id: string; verdict: string; side: string; symbol: string; applied: boolean }[] };
type Review = { review_id: string; ts: number; symbol: string; side: string; verdict: string; status: string; mode: string; applied: number | boolean; reason?: string; recommendation?: string;
  confidence_multiplier?: number; model?: string | null; outcome?: string | null; outcome_r?: number | null; sources?: { id: string; title?: string; url: string | null; tier?: number }[]; citations?: string[] };
type Feed = { status: string; reason?: string; watchlist: string[]; items: Item[]; recent_reviews: Review[]; llm: Llm };

const toronto = (s: number) => new Date(s * 1000).toLocaleString("en-CA", { timeZone: "America/Toronto", dateStyle: "medium", timeStyle: "short" });
const VT: Record<string, Tone> = { veto: "bad", reduce_confidence: "warn", approve_to_forward: "good", allow: "good", no_opinion: "neutral" };
const VL: Record<string, string> = { veto: "veto", reduce_confidence: "reduce confidence", approve_to_forward: "forward (no objection)", allow: "forward (no objection)", no_opinion: "no opinion" };
const SRC_TONE: Record<string, Tone> = { keyless: "good", verified: "good", needs_verification: "warn", needs_key: "warn", needs_config: "warn", rate_limited: "warn", error: "bad" };

function LlmCard({ st }: { st: Status }) {
  const e = st.reviewer.eligibility, g = e.effect?.groups ?? {};
  return (
    <Card title="AI analyst and reviewer" span="full" subtitle="Advisory only (execution_permission none). Pipeline: ML proposal → LLM review → deterministic control plane. The reviewer can only make a trade more conservative.">
      <div className="ux-layout">
        <StatTile label="LLM" value={st.llm.enabled ? "on" : "off"} hint={st.llm.enabled ? `${st.llm.model} · verified key, paid tier` : st.llm.reason} />
        <StatTile label="Reviewer mode" value={st.reviewer.mode} hint={st.reviewer.mode === "shadow" ? "logs verdicts; changes nothing" : st.reviewer.mode === "gate" ? "may veto / reduce confidence" : "disabled"} />
        <StatTile label="Shadow outcomes (restricted / allowed)" value={`${g.restricted?.n ?? 0} / ${g.allow?.n ?? 0}`} hint={`gate needs ≥ ${e.min_n} each and a 95% CI showing restricted trades did worse`} />
        <StatTile label="Eligible to gate?" value={e.eligible ? "yes (a human still sets the mode)" : "no"} hint={e.reasons.slice(0, 2).join(" · ")} />
      </div>
      <p className="ux-small">Sources: {st.sources.map((s) => <span key={s.id}><Badge tone={SRC_TONE[s.state] ?? "neutral"} title={s.needs ? `Needs ${s.needs}` : s.provides}>{s.title}: {(s.state ?? "unknown").replace(/_/g, " ")}</Badge>{" "}</span>)}</p>
    </Card>
  );
}

function Watch({ st, onSaved }: { st: Status; onSaved: () => void }) {
  const avail = useApi<{ tickers: string[]; available: Record<string, string> }>("/api/news/watchlist", 600000);
  const [pick, setPick] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (t: string[]) => { setBusy(true); const r = await api<{ rejected?: string[] }>("/api/news/watchlist", { tickers: t }); setBusy(false); setMsg(r.ok ? (r.data.rejected?.length ? `Not tracked (not in the equity catalog): ${r.data.rejected.join(", ")}` : "Saved.") : r.message); onSaved(); avail.reload(); };
  const refresh = async () => { setBusy(true); setMsg("Collecting from SEC EDGAR, GDELT and official RSS…"); const r = await api<{ status: string; reason?: string; llm?: Llm; collect?: { new?: number } }>("/api/news/refresh", {}); setBusy(false);
    setMsg(r.ok ? (r.data.status === "ok" ? `Done: ${r.data.collect?.new ?? 0} new items.${r.data.llm?.enabled ? "" : " AI scoring is off, so items carry rule-based event labels and hype flags only."}` : String(r.data.reason ?? r.data.status)) : r.message); onSaved(); };
  const names = avail.data?.available ?? {};
  const wl = st.watchlist;
  return (
    <Card title="My watchlist" span="full" subtitle="Per-user. Equities in the ATLAS catalog only (filings need a US ticker). EDGAR filings need ATLAS_SEC_USER_AGENT with a real contact in Settings → Setup.">
      <div className="ux-form-row">
        {wl.length ? wl.map((t) => <Badge key={t} tone="info" title={names[t]}>{t} <button type="button" aria-label={`Remove ${t}`} className="ux-btn" onClick={() => save(wl.filter((x) => x !== t))} disabled={busy}>×</button></Badge>) : <span className="ux-small">Nothing tracked yet.</span>}
      </div>
      <div className="ux-form-row">
        <select aria-label="Add ticker" value={pick} onChange={(e) => setPick(e.target.value)}>
          <option value="">Add a ticker…</option>
          {Object.entries(names).filter(([t]) => !wl.includes(t)).sort().map(([t, n]) => <option key={t} value={t}>{t} · {n}</option>)}
        </select>
        <button type="button" className="ux-btn" disabled={busy || !pick} onClick={() => { void save([...wl, pick]); setPick(""); }}>Add</button>
        <button type="button" className="ux-btn" disabled={busy || !wl.length} onClick={refresh}>Refresh news</button>
      </div>
      {msg ? <p className="ux-small" role="status">{msg}</p> : null}
    </Card>
  );
}

function Ask({ wl, onDone }: { wl: string[]; onDone: () => void }) {
  const [sym, setSym] = useState("");
  const [side, setSide] = useState<"long" | "short">("long");
  const [text, setText] = useState("");
  const [out, setOut] = useState<Review | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const symbol = (sym || wl[0] || "").toUpperCase();
  const go = async () => { setBusy(true); setErr(""); const r = await api<Review>("/api/news/review", { symbol, side, situation: text }); setBusy(false); if (r.ok) { setOut(r.data); onDone(); } else setErr(r.message || "Review failed"); };
  return (
    <Card title="Ask the reviewer" span="full" subtitle="Paste a situation (a post, headline or filing excerpt). It is treated as untrusted text: it can never give the reviewer instructions. The reply is a logged opinion, never an order.">
      <div className="ux-form-row">
        <input aria-label="Ticker" placeholder="Ticker" value={sym} onChange={(e) => setSym(e.target.value)} style={{ width: 100 }} />
        <select aria-label="Proposed side" value={side} onChange={(e) => setSide(e.target.value as "long" | "short")}><option value="long">ML proposes long</option><option value="short">ML proposes short</option></select>
        <button type="button" className="ux-btn" disabled={busy || !symbol} onClick={go}>{busy ? "Reviewing…" : `Review ${symbol || "…"}`}</button>
      </div>
      <textarea aria-label="Situation" rows={3} maxLength={2000} placeholder="Optional: paste the post or headline to assess (e.g. a social-media tip)" value={text} onChange={(e) => setText(e.target.value)} style={{ width: "100%" }} />
      {err ? <p className="ux-small">{err}</p> : null}
      {out ? <div data-review-result>
        <p><Badge tone={VT[out.verdict] ?? "neutral"}>{VL[out.verdict] ?? out.verdict}</Badge>{" "}<span className="ux-small">mode {out.mode} · {out.applied ? "applied" : "not applied (shadow or no opinion)"}</span></p>
        <p className="ux-small">{out.reason}</p>
        {out.sources?.filter((s) => s.url && out.citations?.includes(s.id)).map((s) => <p key={s.id} className="ux-small"><a className="ux-link" href={s.url ?? undefined} target="_blank" rel="noopener noreferrer">{s.title || s.id}</a></p>)}
      </div> : null}
    </Card>
  );
}

export function NewsFeedView() {
  const st = useApi<Status>("/api/news/status", 30000);
  const feed = useApi<Feed>("/api/news/feed", 60000);
  const both = () => { st.reload(); feed.reload(); };
  return (
    <div className="ux-layout">
      <Async state={st} label="Reading news status">{(s) => <><LlmCard st={s} /><Watch st={s} onSaved={both} /><Ask wl={s.watchlist} onDone={both} /></>}</Async>
      <Card title="News & filings feed" span="full" subtitle="Official filings and releases (tier 1) are shown apart from unverified headlines (tier 3). Every row links to its source; nothing is summarised without one.">
        <Async state={feed} label="Reading the feed">{(d) => d.items.length === 0 ? (
          <EmptyState title="No items yet">{d.reason ?? "Add tickers and press Refresh news."}</EmptyState>
        ) : (
          <DataTable rows={d.items as unknown as R[]} columns={[
            { key: "when", label: "Published (Toronto)", render: (r) => toronto(Number(r.published_at)) },
            { key: "ticker", label: "Ticker", render: (r) => String(r.ticker) === "*" ? "macro" : String(r.ticker) },
            { key: "tier", label: "Source", render: (r) => <Badge tone={Number(r.tier) === 1 ? "good" : "warn"}>{String(r.tier_label)}</Badge> },
            { key: "title", label: "Item", render: (r) => <a className="ux-link" href={String(r.url)} target="_blank" rel="noopener noreferrer">{String(r.title)}</a> },
            { key: "ev", label: "Event · AI score", render: (r) => { const a = (r as unknown as Item).annotation; return `${(a.event_type ?? "—").replace(/_/g, " ")} · ${a.grounded && a.sentiment != null ? `sentiment ${a.sentiment.toFixed(2)}, materiality ${a.materiality?.toFixed(2)}` : "not AI-scored"}`; } },
            { key: "flags", label: "Hype / scam flags", render: (r) => { const f = (r as unknown as Item).annotation.hype_flags; return f.length ? f.map((x) => <Badge key={x.type} tone="bad" title={x.why}>{x.type.replace(/_/g, " ")}</Badge>) : "none"; } },
            { key: "rev", label: "Reviewer", render: (r) => { const v = (r as unknown as Item).reviewer; return v.length ? v.slice(0, 2).map((x) => <Badge key={x.review_id} tone={VT[x.verdict] ?? "neutral"}>{x.symbol} {x.side}: {VL[x.verdict] ?? x.verdict}</Badge>) : "—"; } },
          ]} />
        )}</Async>
      </Card>
      <Card title="Recent reviews (audit log)" span="full" subtitle="Every review is logged with its prompt hash, model, cited sources and output. Outcomes fill in from paper trades.">
        <Async state={feed} label="Reading reviews" isEmpty={(d) => !d.recent_reviews.length} empty={<EmptyState title="No reviews yet">Ask the reviewer above, or open a marker on the chart with the News layer on.</EmptyState>}>{(d) => (
          <DataTable rows={d.recent_reviews as unknown as R[]} columns={[
            { key: "ts", label: "When", render: (r) => toronto(Number(r.ts)) },
            { key: "symbol", label: "Proposal", render: (r) => `${r.symbol} ${r.side}` },
            { key: "verdict", label: "Verdict", render: (r) => <Badge tone={VT[String(r.verdict)] ?? "neutral"}>{VL[String(r.verdict)] ?? String(r.verdict)}</Badge> },
            { key: "mode", label: "Mode", render: (r) => `${r.mode}${r.applied ? " · applied" : ""}` },
            { key: "reason", label: "Reason", render: (r) => String(r.reason ?? "") },
            { key: "outcome", label: "Paper outcome", render: (r) => r.outcome ? `${r.outcome}${r.outcome_r != null ? ` ${Number(r.outcome_r) >= 0 ? "+" : ""}${Number(r.outcome_r).toFixed(2)}R` : ""}` : "pending" },
          ]} />
        )}</Async>
      </Card>
    </div>
  );
}
