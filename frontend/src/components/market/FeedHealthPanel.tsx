"use client";

import React, { useEffect, useState } from "react";

interface HealthRow {
  symbol: string;
  provider: string | null;
  status: string;
  last_price: number | null;
  last_quote_at: string | null;
  lag_seconds: number | null;
  last_bar_interval: string | null;
  last_bar_end: string | null;
  flags: string[];
}
interface HealthBody {
  as_of_toronto: string;
  store_present: boolean;
  live_ingest: { running?: boolean; pid?: number | null } & Record<string, unknown>;
  status_counts: Record<string, number>;
  symbols: HealthRow[];
}

function lag(s: number | null): string {
  if (s === null || s === undefined) return "—";
  if (s < 120) return `${Math.round(s)}s`;
  if (s < 7200) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

/** Settings > Connectors: per-symbol ATLAS feed health from /api/feeds/health. */
export function FeedHealthPanel() {
  const [body, setBody] = useState<HealthBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let active = true;
    const pull = async () => {
      try {
        const r = await fetch("/api/feeds/health", { cache: "no-store" });
        if (!r.ok) throw new Error(`Feed health returned HTTP ${r.status}`);
        const b = (await r.json()) as HealthBody;
        if (active) { setBody(b); setError(null); }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "Feed health failed");
      }
    };
    void pull();
    const t = window.setInterval(pull, 15000);
    return () => { active = false; window.clearInterval(t); };
  }, []);

  const rows = (body?.symbols ?? []).filter((r) => !filter || r.symbol.toLowerCase().includes(filter.toLowerCase()) || r.status.includes(filter.toLowerCase()));
  return (
    <div className="clean-card" data-testid="feed-health">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Feed health</h2>
          <p className="clean-card-subtitle">
            {error
              ? error
              : body
              ? `As of ${body.as_of_toronto} · live ingest ${body.live_ingest?.running ? `running (pid ${body.live_ingest.pid})` : "not running"} · ` +
                Object.entries(body.status_counts).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")
              : "Loading /api/feeds/health"}
          </p>
        </div>
        <input className="input input-sm" placeholder="Filter symbol or status" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="atlas-feed-scroll">
        <table className="clean-table">
          <thead>
            <tr><th>Symbol</th><th>Status</th><th>Provider</th><th>Last</th><th>Quote time (Toronto)</th><th>Lag</th><th>Last bar</th><th>Flags</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol} data-feed-health-status={r.status}>
                <td>{r.symbol}</td>
                <td>{r.status.replace("_", " ")}</td>
                <td>{r.provider ?? "—"}</td>
                <td>{r.last_price === null ? "—" : r.last_price.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td>
                <td>{r.last_quote_at ?? "—"}</td>
                <td>{lag(r.lag_seconds)}</td>
                <td>{r.last_bar_end ? `${r.last_bar_interval} · ${r.last_bar_end}` : "—"}</td>
                <td style={{ fontSize: 11 }}>{r.flags.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
