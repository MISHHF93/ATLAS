"use client";

import React from "react";
import { GuideIcon, markColor, markForSymbol } from "../shell/guideIcons";
import type { FeedQuote } from "../../lib/feedQuotes";
import { QuoteChange, QuoteMeta, QuotePrice } from "./QuoteBadge";

/** Secondary microstructure figures. Shown only when the card is expanded. */
export type AssetCardDetail = { label: string; value: string; tone?: "up" | "down" | "warn" | "info" };

export type AssetCardProps = {
  symbol: string;
  name: string;
  /** Short market label, e.g. "Stock" or "Crypto perp". */
  kind: string;
  venue?: string;
  quote: FeedQuote | undefined;
  selected?: boolean;
  onSelect?: () => void;
  details?: AssetCardDetail[];
  footnote?: string;
};

/**
 * One scannable asset card: symbol + name, the feed price (never a fixture), change %, and the
 * quote-status pill with source and Toronto time. Everything else is behind "Details".
 */
export function AssetCard({ symbol, name, kind, venue, quote, selected, onSelect, details, footnote }: AssetCardProps) {
  const mark = markForSymbol(symbol);
  return (
    <article
      className={`asset-card${selected ? " is-selected" : ""}`}
      data-asset-card={symbol}
      data-quote-status={quote?.status ?? "no_data"}
    >
      <button type="button" className="asset-card-main" aria-pressed={!!selected} onClick={onSelect} title={`Show ${symbol} on the chart`}>
        <span className="asset-card-head">
          <GuideIcon name={mark} color={markColor(mark)} />
          <span className="asset-card-symbol">{symbol}</span>
          <span className="asset-card-kind">{kind}</span>
        </span>
        <span className="asset-card-name" title={venue ? `${name} · ${venue}` : name}>{name}</span>
        <span className="asset-card-price-row">
          <span className="asset-card-price"><QuotePrice quote={quote} /></span>
          <span className="asset-card-change"><QuoteChange quote={quote} /></span>
        </span>
        <span className="asset-card-status"><QuoteMeta quote={quote} /></span>
      </button>
      {details && details.length ? (
        <details className="asset-card-details">
          <summary>Details</summary>
          {venue ? <div className="asset-card-venue">{venue}</div> : null}
          <dl>
            {details.map((d) => (
              <div key={d.label}>
                <dt>{d.label}</dt>
                <dd data-tone={d.tone ?? "info"}>{d.value}</dd>
              </div>
            ))}
          </dl>
          {footnote ? <p className="asset-card-foot">{footnote}</p> : null}
        </details>
      ) : null}
    </article>
  );
}

/** Compact one-row-per-asset alternative for fast scanning. */
export function AssetTable({ rows, quotes, selected, onSelect }: {
  rows: Array<{ symbol: string; name: string; kind: string }>;
  quotes: Record<string, FeedQuote>;
  selected?: string;
  onSelect: (symbol: string) => void;
}) {
  return (
    <div className="asset-table-wrap">
      <table className="asset-table">
        <thead><tr><th>Symbol</th><th className="hide-sm">Name</th><th className="num">Price</th><th className="num">Change</th><th>Quote</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className={r.symbol === selected ? "is-selected" : undefined} data-asset-row={r.symbol}>
              <td><button type="button" className="asset-table-symbol" onClick={() => onSelect(r.symbol)} aria-pressed={r.symbol === selected}>{r.symbol}</button><span className="asset-card-kind">{r.kind}</span></td>
              <td className="hide-sm">{r.name}</td>
              <td className="num"><QuotePrice quote={quotes[r.symbol]} /></td>
              <td className="num"><QuoteChange quote={quotes[r.symbol]} /></td>
              <td><QuoteMeta quote={quotes[r.symbol]} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
