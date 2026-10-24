"use client";

import { AlertTriangle, CloudOff, Inbox, RefreshCw } from "lucide-react";
import { FreshBadge, type Fresh } from "./FreshBadge";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/* ------------------------------------------------------------------ data */

export type ApiState<T> = {
  data: T | null;
  error: string;
  /** HTTP status of the last failure (0 = network / backend unreachable). */
  status: number | null;
  loading: boolean;
  /** True when the last good payload is older than 3 refresh intervals. */
  stale: boolean;
  updatedAt: number | null;
  reload: () => void;
};

/** Polls a same-origin JSON endpoint. Keeps the last good payload on failure and flags it stale. */
export function useApi<T = Record<string, unknown>>(url: string | null, refreshMs = 15000): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!url) return;
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) {
        let detail = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j?.detail) detail = String(j.detail); } catch { /* not JSON */ }
        if (!alive.current) return;
        setStatus(r.status); setError(detail);
      } else {
        const j = (await r.json()) as T;
        if (!alive.current) return;
        setData(j); setError(""); setStatus(null); setUpdatedAt(Date.now());
      }
    } catch {
      if (!alive.current) return;
      setStatus(0); setError("ATLAS backend is unreachable");
    } finally {
      if (alive.current) { setLoading(false); setNow(Date.now()); }
    }
  }, [url]);
  useEffect(() => {
    alive.current = true;
    if (!url) { setLoading(false); return; }
    void load();
    const t = setInterval(load, refreshMs);
    return () => { alive.current = false; clearInterval(t); };
  }, [load, refreshMs, url]);
  const stale = updatedAt !== null && Boolean(error) && now - updatedAt > refreshMs * 3;
  return { data, error, status, loading, stale, updatedAt, reload: () => { setLoading(true); void load(); } };
}

export const num = (v: unknown): number | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
};
export function money(v: unknown, ccy = "USD", digits = 2): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString("en-CA", { style: "currency", currency: ccy, minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function pct(v: unknown, digits = 2, signed = false): string {
  const n = num(v);
  if (n === null) return "—";
  return `${signed && n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}
export function ago(ts: number | null): string {
  if (!ts) return "never";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
}

/* ------------------------------------------------------------ components */

export function PageHeader({ title, summary, actions, eyebrow }: { title: string; summary?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="ux-page-header">
      <div className="ux-page-header__text">
        {eyebrow ? <div className="ux-eyebrow">{eyebrow}</div> : null}
        <h1 className="ux-h1">{title}</h1>
        {summary ? <p className="ux-lede">{summary}</p> : null}
      </div>
      {actions ? <div className="ux-page-header__actions">{actions}</div> : null}
    </header>
  );
}

export function Card({ title, subtitle, actions, children, span, id, footer, fresh }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; span?: 1 | 2 | 3 | "full"; id?: string; footer?: ReactNode;
  /** Freshness of the market data this card shows (shared quant.freshness label). Omit for cards that show no feed data. */
  fresh?: Fresh | null;
}) {
  const labelId = id ? `${id}-title` : undefined;
  return (
    <section className="ux-card" data-span={span} aria-labelledby={title ? labelId : undefined} id={id}>
      {title || actions || fresh !== undefined ? (
        <div className="ux-card__head">
          <div>
            {title ? <h2 className="ux-h2" id={labelId}>{title}</h2> : null}
            {subtitle ? <p className="ux-card__sub">{subtitle}</p> : null}
          </div>
          {actions || fresh !== undefined ? <div className="ux-card__actions">{fresh !== undefined ? <FreshBadge f={fresh} /> : null}{actions}</div> : null}
        </div>
      ) : null}
      <div className="ux-card__body">{children}</div>
      {footer ? <div className="ux-card__foot">{footer}</div> : null}
    </section>
  );
}

export type Tone = "neutral" | "good" | "bad" | "warn" | "info";
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span className="ux-badge" data-tone={tone} title={title}>{children}</span>;
}

export function StatTile({ label, value, delta, deltaTone, hint, meter, loading }: {
  label: string; value: ReactNode; delta?: ReactNode; deltaTone?: Tone; hint?: ReactNode;
  /** 0..1 used fraction, drawn as a bar with a text equivalent. */
  meter?: { used: number; label: string; tone?: Tone };
  loading?: boolean;
}) {
  return (
    <div className="ux-stat">
      <div className="ux-stat__label">{label}</div>
      {loading ? <Skeleton h={28} w="60%" /> : <div className="ux-stat__value">{value}</div>}
      {delta !== undefined && !loading ? <div className="ux-stat__delta" data-tone={deltaTone ?? "neutral"}>{delta}</div> : null}
      {meter && !loading ? (
        <div className="ux-meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(Math.min(1, Math.max(0, meter.used)) * 100)} aria-label={meter.label}>
          <div className="ux-meter__fill" data-tone={meter.tone ?? "info"} style={{ width: `${Math.min(100, Math.max(0, meter.used * 100))}%` }} />
        </div>
      ) : null}
      {hint ? <div className="ux-stat__hint">{hint}</div> : null}
    </div>
  );
}

export type Column<R> = { key: string; label: string; align?: "left" | "right"; render?: (row: R) => ReactNode };
export function DataTable<R extends Record<string, unknown>>({ columns, rows, caption, empty, maxHeight }: {
  columns: Column<R>[]; rows: R[]; caption?: string; empty?: ReactNode; maxHeight?: number;
}) {
  if (!rows.length) return <>{empty ?? <EmptyState title="Nothing to show yet" />}</>;
  return (
    <div className="ux-table-wrap" style={maxHeight ? { maxHeight } : undefined} tabIndex={0} role="region" aria-label={caption ?? "Table"}>
      <table className="ux-table">
        {caption ? <caption className="ux-sr-only">{caption}</caption> : null}
        <thead><tr>{columns.map((c) => <th key={c.key} scope="col" data-align={c.align}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{columns.map((c) => <td key={c.key} data-align={c.align}>{c.render ? c.render(r) : display(r[c.key])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function display(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return <span className="ux-muted">—</span>;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object") return <code className="ux-code">{JSON.stringify(v)}</code>;
  return String(v).replaceAll("_", " ");
}

export function EmptyState({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="ux-state" data-kind="empty">
      <div className="ux-state__icon" aria-hidden>{icon ?? <Inbox size={20} />}</div>
      <div className="ux-state__title">{title}</div>
      {children ? <div className="ux-state__body">{children}</div> : null}
      {action ? <div className="ux-state__action">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ title, detail, onRetry, offline }: { title?: string; detail?: ReactNode; onRetry?: () => void; offline?: boolean }) {
  return (
    <div className="ux-state" data-kind="error" role="alert">
      <div className="ux-state__icon" aria-hidden>{offline ? <CloudOff size={20} /> : <AlertTriangle size={20} />}</div>
      <div className="ux-state__title">{title ?? (offline ? "Backend offline" : "Couldn’t load this")}</div>
      {detail ? <div className="ux-state__body">{detail}</div> : null}
      {onRetry ? <button type="button" className="ux-btn" onClick={onRetry}><RefreshCw size={14} aria-hidden /> Retry</button> : null}
    </div>
  );
}

export function Skeleton({ h = 14, w = "100%" }: { h?: number; w?: number | string }) {
  return <span className="ux-skeleton" style={{ height: h, width: w }} aria-hidden />;
}
export function LoadingSkeleton({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="ux-loading" role="status" aria-live="polite">
      <span className="ux-sr-only">{label}…</span>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} h={14} w={`${90 - i * 12}%`} />)}
    </div>
  );
}

/** Standard loading / error / stale wrapper around one API state. */
export function Async<T>({ state, children, empty, isEmpty, label }: {
  state: ApiState<T>; children: (data: T) => ReactNode; empty?: ReactNode; isEmpty?: (d: T) => boolean; label?: string;
}) {
  if (state.loading && !state.data) return <LoadingSkeleton label={label} />;
  if (!state.data) return <ErrorState offline={state.status === 0} detail={state.error} onRetry={state.reload} />;
  return (
    <>
      {state.stale ? <StaleNote updatedAt={state.updatedAt} onRetry={state.reload} /> : null}
      {isEmpty && isEmpty(state.data) ? empty ?? <EmptyState title="Nothing here yet" /> : children(state.data)}
    </>
  );
}
export function StaleNote({ updatedAt, onRetry }: { updatedAt: number | null; onRetry: () => void }) {
  return (
    <div className="ux-stale" role="status">
      Showing data from {ago(updatedAt)} — refresh failed.{" "}
      <button type="button" className="ux-link-btn" onClick={onRetry}>Retry</button>
    </div>
  );
}

export function Grid({ children, cols = 3 }: { children: ReactNode; cols?: 2 | 3 | 4 }) {
  return <div className="ux-grid" data-cols={cols}>{children}</div>;
}

/* --------------------------------------------------------------- actions */

export type ActionState<T> = { busy: boolean; error: string; status: number | null; result: T | null; run: (body?: unknown) => Promise<T | null>; reset: () => void };

/** One backend write. Console writes carry X-Atlas-Console so the API can refuse cross-site form posts. */
export function useAction<T = Record<string, unknown>>(url: string, method: "POST" | "DELETE" = "POST"): ActionState<T> {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<number | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const run = useCallback(async (body?: unknown) => {
    setBusy(true); setError(""); setStatus(null);
    try {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json", "X-Atlas-Console": "1" }, body: JSON.stringify(body ?? {}) });
      let j: unknown = null;
      try { j = await r.json(); } catch { /* not JSON */ }
      if (!r.ok) {
        const d = (j as { detail?: unknown } | null)?.detail;
        setStatus(r.status); setError(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${r.status}`);
        return null;
      }
      setResult(j as T); return j as T;
    } catch {
      setStatus(0); setError("ATLAS backend is unreachable"); return null;
    } finally { setBusy(false); }
  }, [url, method]);
  return { busy, error, status, result, run, reset: () => { setError(""); setResult(null); setStatus(null); } };
}

export function ActionButton({ action, body, children, tone, confirm, onDone, disabled }: {
  action: ActionState<unknown>; body?: unknown; children: ReactNode; tone?: "primary" | "danger" | "default"; confirm?: string; onDone?: () => void; disabled?: boolean;
}) {
  return (
    <button type="button" className="ux-btn" data-variant={tone ?? "default"} disabled={action.busy || disabled} aria-busy={action.busy}
      onClick={async () => {
        if (confirm && !window.confirm(confirm)) return;
        const r = await action.run(body);
        if (r !== null) onDone?.();
      }}>
      {action.busy ? <RefreshCw size={14} aria-hidden className="ux-spin" /> : null}{children}
    </button>
  );
}

/** Inline result line under a control: success text or the API's own error. */
export function ActionResult({ action, success }: { action: ActionState<unknown>; success?: ReactNode }) {
  if (action.error) return <p className="ux-action-msg" data-tone={action.status === 403 ? "warn" : "bad"} role="alert">{action.status === 403 ? "Not allowed here: " : "Failed: "}{action.error}</p>;
  if (action.result && success) return <p className="ux-action-msg" data-tone="good" role="status">{success}</p>;
  return null;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="ux-btn" data-size="sm" aria-label={`${label}: ${text.slice(0, 60)}`}
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); } catch {
          const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
          try { document.execCommand("copy"); } finally { ta.remove(); }
        }
        setDone(true); setTimeout(() => setDone(false), 1500);
      }}>{done ? "Copied" : label}</button>
  );
}

export function Command({ text }: { text: string }) {
  return <div className="ux-cmd"><code>{text}</code><CopyButton text={text} /></div>;
}
