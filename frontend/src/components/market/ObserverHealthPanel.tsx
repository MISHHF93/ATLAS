"use client";

import { useEffect, useState } from "react";

type ObserverModel = {
  symbol: string;
  last_checked_at?: string;
  feed_origin?: string;
  bucket_seconds?: number;
  feed_status?: string;
  model_status?: string;
  samples_learned?: number;
  last_bar_close?: string;
  feed_age_seconds?: number | null;
  status?: string;
  notice?: string;
  error?: string | null;
};

type ObserverHealth = {
  state?: string;
  coverage_status?: string;
  sampling_enabled?: boolean;
  started_at?: string;
  last_cycle_at?: string;
  intervals_seconds?: { crypto?: number; minute?: number };
  symbols?: ObserverModel[];
  summary?: { watched?: number; observing?: number; unavailable?: number };
  viewer_interests?: { ttl_seconds?: number; capacity?: number; active?: Array<{ symbol: string }> };
  default_symbols?: string[];
  configured_symbols?: string[];
  omitted_symbols?: string[];
  transport_extra_crypto_capacity?: number;
  last_error?: string | null;
};

const numeric = (value?: number | null, digits = 1) => typeof value === "number" && Number.isFinite(value)
  ? value.toLocaleString("en-US", { maximumFractionDigits: digits }) : "Unavailable";
const timestamp = (value?: string) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString() : "Unavailable";
const label = (value?: string) => value ? value.replaceAll("_", " ") : "Unavailable";

export function ObserverHealthPanel() {
  const [health, setHealth] = useState<ObserverHealth | null>(null);
  const [receivedAt, setReceivedAt] = useState<string>();
  const [error, setError] = useState("");

  useEffect(() => {
    let controller: AbortController | null = null;
    let closed = false;
    let pending = false;
    const pull = async () => {
      if (pending) return;
      pending = true;
      const request = new AbortController();
      controller = request;
      const timeout = window.setTimeout(() => request.abort(), 10000);
      try {
        const response = await fetch("/api/ml/live-observer/status", { cache: "no-store", signal: request.signal });
        if (!response.ok) throw new Error(`Observer monitoring returned HTTP ${response.status}.`);
        const body = await response.json() as ObserverHealth;
        if (!body || typeof body !== "object" || !Array.isArray(body.symbols) || typeof body.state !== "string") {
          throw new Error("Observer monitoring returned an incomplete status.");
        }
        if (!closed && !request.signal.aborted) {
          setHealth(body);
          setReceivedAt(new Date().toISOString());
          setError("");
        }
      } catch (cause) {
        if (!closed) setError(request.signal.aborted ? "Observer monitoring timed out." : cause instanceof Error ? cause.message : "Observer monitoring is unavailable.");
      } finally {
        window.clearTimeout(timeout);
        pending = false;
      }
    };
    void pull();
    const timer = window.setInterval(pull, 5000);
    return () => { closed = true; controller?.abort(); window.clearInterval(timer); };
  }, []);

  return <section className="clean-card" aria-label="Live market observer monitoring">
    <div className="clean-card-header">
      <div>
        <h2 className="clean-card-title">Live market observer</h2>
        <p className="clean-card-subtitle">The background learner watches received market API data and updates only after a later completed candle resolves a prediction.</p>
      </div>
      <span className="badge">{error ? "Status unavailable" : health ? `Process: ${label(health.state)}` : "Loading status"}</span>
    </div>
    {error ? <p role="status" className="model-flow-warning">{error} {health ? "The table shows the last successful snapshot; its statuses may be stale." : "No observer status has been verified."} Retrying every 5 seconds.</p> : null}
    {health?.last_error ? <p role="status" className="model-flow-warning">Observer error: {health.last_error}</p> : null}
    <p className="clean-card-subtitle" style={{ margin: "8px 0" }}>
      Last snapshot received {timestamp(receivedAt)} / started {timestamp(health?.started_at)} / last background cycle {timestamp(health?.last_cycle_at)} / sampling {health?.sampling_enabled == null ? "unavailable" : health.sampling_enabled ? "enabled" : "disabled"} / coverage {label(health?.coverage_status)}.
    </p>
    {health ? <>
      <p className="clean-card-subtitle" style={{ margin: "8px 0" }}>
        Crypto checks every {numeric(health.intervals_seconds?.crypto, 2)}s / minute-candle checks every {numeric(health.intervals_seconds?.minute)}s.
        {health.summary ? ` ${numeric(health.summary.observing, 0)} observing / ${numeric(health.summary.watched, 0)} watched / ${numeric(health.summary.unavailable, 0)} unavailable.` : ""}
        {health.viewer_interests?.capacity != null ? ` Additional viewer watch capacity: ${numeric(health.viewer_interests.capacity, 0)}.` : ""}
        {health.viewer_interests?.ttl_seconds != null ? ` Selected symbols stay watched for ${numeric(health.viewer_interests.ttl_seconds, 0)}s after their last viewer request.` : ""}
        {health.transport_extra_crypto_capacity != null ? ` The trade stream supports ${numeric(health.transport_extra_crypto_capacity, 0)} additional crypto watches.` : ""}
      </p>
      {health.default_symbols?.length ? <p className="clean-card-subtitle" style={{ margin: "8px 0" }}>Always watched: {health.default_symbols.join(", ")}.{health.configured_symbols?.length ? ` Configured additions: ${health.configured_symbols.join(", ")}.` : ""}</p> : null}
      {health.omitted_symbols?.length ? <p className="model-flow-warning">Outside current watch capacity: {health.omitted_symbols.join(", ")}. These symbols are not being observed in the background.</p> : null}
      <div style={{ maxWidth: "100%", overflowX: "auto" }} tabIndex={0} role="region" aria-label="Observed symbols and market data health">
        <table className="clean-table" style={{ minWidth: 960 }}>
          <thead><tr><th>Symbol / source</th><th>Input resolution</th><th>Feed / model</th><th>Feed age</th><th>Learned outcomes</th><th>Input / check times</th></tr></thead>
          <tbody>{health.symbols?.length ? health.symbols.map(model => <tr key={model.symbol}>
            <td><strong>{model.symbol}</strong><div className="clean-card-subtitle">{model.feed_origin || "Source unavailable"}</div>{model.error ? <p className="model-flow-warning" style={{ margin: "4px 0", maxWidth: 300, whiteSpace: "normal" }}>{model.error}</p> : null}</td>
            <td>{model.bucket_seconds != null ? `${numeric(model.bucket_seconds, 0)}s candles` : "Unavailable"}</td>
            <td>{label(model.status)}<br/>Feed: {label(model.feed_status)}<br/>Model: {label(model.model_status)}{model.notice ? <p className="clean-card-subtitle" style={{ margin: "4px 0", maxWidth: 280, whiteSpace: "normal" }}>{model.notice}</p> : null}</td>
            <td>{model.feed_age_seconds == null ? "Unavailable" : `${numeric(model.feed_age_seconds)}s`}</td>
            <td>{numeric(model.samples_learned, 0)}</td>
            <td>Input: {timestamp(model.last_bar_close)}<br/>Checked: {timestamp(model.last_checked_at)}</td>
          </tr>) : <tr><td colSpan={6}>No watched symbol snapshots have been reported yet.</td></tr>}</tbody>
        </table>
      </div>
    </> : null}
    <p className="clean-card-subtitle" style={{ margin: "12px 0 0" }}>A running process or a growing sample count does not establish predictive accuracy. Real time trade coverage depends on the connected provider; minute-candle sources can be delayed or closed. The observer remains experimental and cannot place orders. Open Real time on Desk or Markets to inspect a symbol's actual inputs and predictions.</p>
  </section>;
}
