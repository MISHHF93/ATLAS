"use client";

import { AppNav } from "../shell/AppNav";
import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

/** Founder workbench panels (Lola port). Read-only views of /api/founder/*; paper only, execution_permission none. */
export type FounderPayload = Record<string, unknown> & { execution_permission?: string; trading?: string };

const card: CSSProperties = {
  background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderRadius: 8, padding: 16,
  color: "var(--text-primary)",
};
const muted: CSSProperties = { color: "var(--text-muted)", fontSize: 12 };

export function useFounder(path: string, refreshMs = 15000) {
  const [data, setData] = useState<FounderPayload | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/founder/${path}`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unavailable");
    }
  }, [path]);
  useEffect(() => {
    load();
    const t = setInterval(load, refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs]);
  return { data, error, reload: load };
}

export function FounderShell({ title, summary, children }: { title: string; summary: string; children: ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-canvas)" }}>
    <AppNav />
    <main style={{ padding: 24, display: "grid", gap: 16, alignContent: "start" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
        <div>
          <a href="/" style={{ ...muted, textDecoration: "none" }}>ATLAS / Founder</a>
          <h1 style={{ color: "var(--text-primary)", margin: "4px 0", fontSize: 22 }}>{title}</h1>
          <p style={muted}>{summary} Paper only. Nothing on this page can send an order or move money.</p>
        </div>
        <SafeStopButton />
      </header>
      {children}
    </main>
    </div>
  );
}

function Value({ v }: { v: unknown }): ReactNode {
  if (v === null || v === undefined) return <span style={muted}>-</span>;
  if (Array.isArray(v)) {
    if (v.length && typeof v[0] === "object") return <Table rows={v as Record<string, unknown>[]} />;
    return <span>{v.map(String).join(", ") || "-"}</span>;
  }
  if (typeof v === "object") return <KeyValues data={v as Record<string, unknown>} />;
  return <span>{String(v)}</span>;
}

export function KeyValues({ data, hide = [] }: { data: Record<string, unknown>; hide?: string[] }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "minmax(140px, 220px) 1fr", gap: "6px 12px", margin: 0 }}>
      {Object.entries(data).filter(([k]) => !hide.includes(k)).map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt style={muted}>{k.replaceAll("_", " ")}</dt>
          <dd style={{ margin: 0, fontSize: 13 }}><Value v={v} /></dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = Array.from(new Set(rows.flatMap(r => Object.keys(r))));
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead><tr>{cols.map(c => <th key={c} style={{ ...muted, textAlign: "left", padding: 6, borderBottom: "1px solid var(--border-strong)" }}>{c.replaceAll("_", " ")}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map(c => <td key={c} style={{ padding: 6, borderBottom: "1px solid var(--border-light)" }}><Value v={r[c]} /></td>)}</tr>)}</tbody>
    </table>
  );
}

export function FounderPanel({ path, title, hide = [] }: { path: string; title: string; hide?: string[] }) {
  const { data, error } = useFounder(path);
  return (
    <section style={card}>
      <h2 style={{ fontSize: 15, margin: "0 0 12px" }}>{title}</h2>
      {error && <p style={{ color: "var(--accent-danger, #ff5c7a)" }}>Unavailable: {error}</p>}
      {!data && !error && <p style={muted}>Loading...</p>}
      {data && <KeyValues data={data} hide={["execution_permission", "trading", "track", ...hide]} />}
      {data && <p style={{ ...muted, marginTop: 12 }}>execution_permission: {data.execution_permission} · {data.trading}</p>}
    </section>
  );
}

/** Safe stop: halts all paper trading at once. Reset is owner CLI + step-up only, never from the browser. */
export function SafeStopButton() {
  const { data, reload } = useFounder("safe-stop", 5000);
  const [busy, setBusy] = useState(false);
  const engaged = Boolean(data?.engaged);
  const engage = async () => {
    if (!window.confirm("Engage Safe stop? All new paper orders will be rejected until you reset with step-up (atlas-owner).")) return;
    setBusy(true);
    try {
      await fetch("/api/founder/safe-stop", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "owner_safe_stop_button" }) });
    } finally {
      setBusy(false);
      reload();
    }
  };
  return (
    <button type="button" onClick={engage} disabled={busy || engaged} title={engaged ? `Halted: ${String(data?.reason ?? "")}` : "Halt all paper trading now"}
      style={{ background: engaged ? "var(--bg-subtle)" : "#c81e3a", color: "var(--text-on-dark)", border: "1px solid var(--border-strong)",
        borderRadius: 6, padding: "10px 16px", fontWeight: 700, cursor: engaged ? "default" : "pointer" }}>
      {engaged ? "Safe stop ON (reset via atlas-owner)" : "Safe stop"}
    </button>
  );
}
