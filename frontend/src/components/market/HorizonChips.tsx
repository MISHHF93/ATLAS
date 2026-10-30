"use client";
/** evo-17: the research ensemble's per-horizon live record, shown next to the dashed forecast. A chip says what the model has actually done
 *  against real bars (hit rate, 80% coverage, n), never what it is expected to do. Research only; execution_permission none. */
import type { HzLive, HzRow, Nowcast } from "./nowcast";

const pct = (v: number | null | undefined) => (v == null ? "n/a" : `${Math.round(v * 100)}%`);
export function horizonChipText(r: HzRow): string {
  if (r.status !== "ok") return `${r.h}: no model forecast`;
  const a: HzLive | undefined = r.live?.asset;
  const n = a?.n ?? 0;
  if (n < 1) return `${r.h}: 0 live scores yet`;
  return `${r.h}: hit ${pct(a?.hit_rate)} (n=${a?.hit_n ?? 0}) · cover ${pct(a?.coverage_80)} (n=${n})`;
}

export function HorizonChips({ nc }: { nc: Nowcast | null }) {
  const rows = nc?.horizons?.horizons;
  if (!rows?.length) return null;
  const sorted = [...rows];
  return (
    <span className="atlas-hz-chips" data-testid="horizon-chips" aria-label="Research ensemble live record per horizon">
      {sorted.map((r) => {
        const tip = r.status === "ok"
          ? `${r.label ?? "research / below gate"}. ${r.applied ? "Live gate passed: this horizon shifts the dashed line." : `Gated: ${r.gate ? `${r.gate.n} of ${r.gate.needs_n} live scores, ${r.gate.rule}` : "not enough live evidence"}; the dashed line is not moved by it.`} `
            + `Pool live (n=${r.live?.pool.n ?? 0}): pinball ${r.live?.pool.pinball_bps ?? "n/a"} bps, coverage ${pct(r.live?.pool.coverage_80)}. Weights (${r.weights?.basis ?? "n/a"}): ${Object.entries(r.weights?.weights ?? {}).map(([m, w]) => `${m} ${Math.round(w * 100)}%`).join(", ")}. `
            + `${r.transfer ? r.transfer.note + " " : ""}execution_permission: none.`
          : r.reason ?? "no forecast";
        return (
          <span key={r.h} className="atlas-chart-badge" title={tip} data-testid={`hz-chip-${r.h}`}
            style={{ borderStyle: "dashed", borderColor: "#B8A1FF", opacity: r.status === "ok" ? 1 : 0.6 }}>
            {horizonChipText(r)}{r.status === "ok" ? (r.applied ? " · applied" : " · gated") : ""}{r.transfer ? " · transfer" : ""}
          </span>
        );
      })}
      <span className="atlas-chart-badge" title="Quantile boosters (LightGBM / XGBoost where installed) + no-change baseline, conformal 80% bands, weighted by live pinball. Research only.">research · exec none</span>
    </span>
  );
}
