"use client";
import { useApi } from "./primitives";

/** Shared data-freshness label (live / delayed / historical / simulated / unavailable). Never upgraded client-side. */
export type Fresh = { label: "live" | "delayed" | "historical" | "simulated" | "unavailable"; last_bar_end: number | null; age_s: number | null; source: string; symbol?: string };

export function ageText(age?: number | null): string {
  if (age == null) return "";
  if (age < 3600) return `${Math.round(age / 60)} min old`;
  if (age < 172800) return `${Math.round(age / 3600)} h old`;
  return `${Math.round(age / 86400)} d old`;
}

export function FreshBadge({ f }: { f?: Fresh | null }) {
  const label = f?.label ?? "unavailable";
  const age = ageText(f?.age_s);
  return <span className="ux-chip" data-fresh={label} title={f?.source ?? ""}>{label}{age ? ` · ${age}` : ""}</span>;
}

type FeedFreshness = { counts?: Record<string, number>; newest?: Fresh; store_present?: boolean };

/** Platform-wide freshness chip (header + curtain): counts per label over the UI universe, from /api/feeds/freshness. */
export function DataFreshnessChip({ compact = false }: { compact?: boolean }) {
  const r = useApi<FeedFreshness>("/api/feeds/freshness", 60000);
  const d = r.data;
  const counts = d?.counts ?? {};
  const order = ["live", "delayed", "historical", "simulated", "unavailable"];
  const summary = order.filter((k) => counts[k]).map((k) => `${k} ${counts[k]}`).join(" · ") || "unavailable";
  const worst = [...order].reverse().find((k) => counts[k]) ?? "unavailable";
  const title = `Data freshness across ${Object.values(counts).reduce((a, b) => a + b, 0)} symbols: ${summary}. Newest bar: ${d?.newest?.symbol ?? "none"} (${d?.newest?.label ?? "unavailable"}${d?.newest?.age_s != null ? `, ${ageText(d.newest.age_s)}` : ""}).`;
  return (
    <span className="ux-chip" data-fresh={d ? worst : "unavailable"} title={title} aria-label={title}>
      Data: {d ? (compact ? `${counts.live ?? 0} live / ${Object.values(counts).reduce((a, b) => a + b, 0)}` : summary) : "unavailable"}
    </span>
  );
}
