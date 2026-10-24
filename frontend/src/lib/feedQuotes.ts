"use client";
// ATLAS feed quotes: one source of truth for every on-screen price.
// GET /api/feeds/quotes for the first paint, then /api/feeds/stream (SSE, ends itself every ~50 s; EventSource
// reconnects) for pushes written by the live-ingest service. Every quote carries source, Toronto time and status.
import { useEffect, useMemo, useState } from "react";

export type QuoteStatus = "live" | "delayed" | "market_closed" | "stale" | "no_data";

export type FeedQuote = {
  symbol: string;
  instrument?: string | null;
  price: number | null;
  change_pct: number | null;
  source: string | null;
  observed_at: number | null;
  observed_at_toronto: string | null;
  age_seconds?: number | null;
  status: QuoteStatus;
  reason?: string;
};

export const NO_QUOTE = (symbol: string): FeedQuote => ({
  symbol,
  price: null,
  change_pct: null,
  source: null,
  observed_at: null,
  observed_at_toronto: null,
  status: "no_data",
});

export function useFeedQuotes(symbols: string[]): Record<string, FeedQuote> {
  const key = useMemo(() => Array.from(new Set(symbols.filter(Boolean))).sort().join(","), [symbols]);
  const [quotes, setQuotes] = useState<Record<string, FeedQuote>>({});
  useEffect(() => {
    if (!key) return;
    let closed = false;
    fetch(`/api/feeds/quotes?symbols=${encodeURIComponent(key)}`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!closed && body?.quotes) setQuotes((prev) => ({ ...prev, ...body.quotes }));
      })
      .catch(() => undefined);
    if (typeof EventSource === "undefined") return () => { closed = true; };
    const es = new EventSource(`/api/feeds/stream?symbols=${encodeURIComponent(key)}`);
    es.addEventListener("quotes", (ev) => {
      try {
        const body = JSON.parse((ev as MessageEvent).data);
        if (body?.quotes) setQuotes((prev) => ({ ...prev, ...body.quotes }));
      } catch {
        /* ignore malformed frame */
      }
    });
    return () => {
      closed = true;
      es.close();
    };
  }, [key]);
  return quotes;
}

export const STATUS_LABEL: Record<QuoteStatus, string> = {
  live: "LIVE",
  delayed: "DELAYED",
  market_closed: "MARKET CLOSED",
  stale: "STALE",
  no_data: "NO DATA",
};

export function formatQuotePrice(price: number | null | undefined): string {
  if (price === null || price === undefined || !Number.isFinite(price)) return "—";
  const digits = price >= 1000 ? 2 : price >= 1 ? 2 : price >= 0.01 ? 4 : 8;
  return price.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function shortToronto(ts: string | null | undefined): string {
  // "2026-10-23 16:00:00 EDT" -> "Oct 23 16:00:00 ET (Toronto)"
  if (!ts) return "—";
  const m = ts.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2}) (\w+)$/);
  if (!m) return ts;
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1];
  return `${mon} ${Number(m[3])} ${m[4]} ${m[5]}`;
}
