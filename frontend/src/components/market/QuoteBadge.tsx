"use client";
import { FeedQuote, STATUS_LABEL, formatQuotePrice, shortToronto } from "../../lib/feedQuotes";

const COLORS: Record<string, string> = {
  live: "#10b981",
  delayed: "#f59e0b",
  market_closed: "#64748b",
  stale: "#ef4444",
  no_data: "#94a3b8",
};

/** Status pill + source + Toronto timestamp. Every visible price must sit next to one of these. */
export function QuoteMeta({ quote, compact = false }: { quote: FeedQuote | undefined; compact?: boolean }) {
  const q = quote;
  const status = q?.status ?? "no_data";
  const title = q
    ? `${STATUS_LABEL[status]} · source ${q.source ?? "none"} · ${q.observed_at_toronto ?? "no print"} (Toronto)${q.reason ? ` · ${q.reason}` : ""}`
    : "NO DATA · no feed quote";
  return (
    <span
      className="quote-meta"
      data-quote-status={status}
      data-quote-source={q?.source ?? "none"}
      title={title}
      style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: compact ? 9 : 10, whiteSpace: "nowrap" }}
    >
      <span
        style={{
          background: COLORS[status],
          color: "#fff",
          borderRadius: 3,
          padding: "0 4px",
          fontWeight: 700,
          letterSpacing: 0.3,
        }}
      >
        {STATUS_LABEL[status]}
      </span>
      {!compact || q?.source ? (
        <span style={{ color: "var(--text-muted, #94a3b8)" }}>
          {q?.source ?? "no source"}
          {q?.observed_at_toronto ? ` · ${shortToronto(q.observed_at_toronto)}` : ""}
        </span>
      ) : null}
    </span>
  );
}

export function QuotePrice({ quote, prefix = "$" }: { quote: FeedQuote | undefined; prefix?: string }) {
  const p = quote?.price ?? null;
  return (
    <span data-quote-price={p === null ? "none" : String(p)}>{p === null ? "—" : `${prefix}${formatQuotePrice(p)}`}</span>
  );
}

export function QuoteChange({ quote }: { quote: FeedQuote | undefined }) {
  const c = quote?.change_pct;
  if (c === null || c === undefined) return <span style={{ color: "var(--text-muted, #94a3b8)" }}>—</span>;
  return <span style={{ color: c >= 0 ? "#10b981" : "#ef4444" }}>{`${c >= 0 ? "+" : ""}${c.toFixed(2)}%`}</span>;
}
