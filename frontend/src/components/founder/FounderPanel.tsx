"use client";

import type { ReactNode } from "react";
import { Database } from "lucide-react";
import { EmptyState, ErrorState, LoadingSkeleton, useApi, type ApiState } from "../../ui/primitives";

/** Founder pages: read-only views of /api/founder/*. Paper only, execution_permission none. */
export type FounderPayload = Record<string, unknown> & { execution_permission?: string; trading?: string };
type Status = { available?: boolean; demo?: boolean; hint?: string };

/** title/summary/eyebrow are kept for the existing call sites; the page frame (Hub) already shows the page and tab, so nothing repeats them here. */
export function FounderShell({ children }: { title?: string; summary?: string; eyebrow?: string; children: ReactNode }) {
  return (
    <div className="ux-page">
      <p className="ux-muted">Read-only: nothing on this page can send an order or move money.</p>
      {children}
    </div>
  );
}

/** Probe /status once so pages never call data/* views that 404 before demo data is seeded. */
export function useFounderStatus() {
  return useApi<Status>("/api/founder/data/status", 60000);
}

/** Wraps a founder page body: loading, backend offline, or "no data seeded yet" empty state with the seed hint. */
export function FounderGate({ status, children }: { status: ApiState<Status>; children: ReactNode }) {
  if (status.loading && !status.data) return <LoadingSkeleton rows={4} />;
  if (!status.data) return <ErrorState offline={status.status === 0} detail={status.error} onRetry={status.reload} />;
  if (!status.data.available)
    return (
      <EmptyState title="No founder data yet" icon={<Database size={20} />}
        action={<button type="button" className="ux-btn" onClick={status.reload}>Check again</button>}>
        Nothing has been recorded in the founder ledgers, so there is nothing to show. To load the labelled demo set, run{" "}
        <code className="ux-code">{status.data.hint ?? "atlas-console seed-demo"}</code>.
      </EmptyState>
    );
  return <>{children}</>;
}

/** Fetch a founder data view only once status says data exists. */
export function useFounderData<T = Record<string, unknown>>(available: boolean | undefined, path: string, refreshMs = 30000) {
  return useApi<T>(available ? `/api/founder/data/${path}` : null, refreshMs);
}
