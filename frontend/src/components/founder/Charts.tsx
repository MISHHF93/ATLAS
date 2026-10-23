"use client";

import type { CSSProperties, ReactNode } from "react";

/**
 * Founder infographics (ported from Lola's console). Okabe-Ito colourblind-safe palette, shapes/labels carry the
 * meaning as well as colour, and every chart ships an equivalent data table (WCAG 1.1.1 / 1.4.1).
 */
export const OKABE_ITO = { blue: "#0072B2", orange: "#E69F00", green: "#009E73", vermillion: "#D55E00", purple: "#CC79A7", sky: "#56B4E9", yellow: "#F0E442" };
const C = OKABE_ITO;
const muted: CSSProperties = { color: "var(--text-muted)", fontSize: 12 };
const n = (v: unknown) => (typeof v === "number" ? v : Number(v ?? 0)) || 0;
export const fmt = (v: unknown, d = 2) => n(v).toLocaleString("en-CA", { maximumFractionDigits: d, minimumFractionDigits: d });

export function Figure({ title, caption, table, children }: { title: string; caption: string; table: ReactNode; children: ReactNode }) {
  return (
    <figure style={{ margin: 0, background: "var(--bg-surface)", border: "1px solid var(--border-light)", borderRadius: 8, padding: 16, color: "var(--text-primary)" }}>
      <figcaption><h2 style={{ fontSize: 15, margin: "0 0 4px" }}>{title}</h2><p style={{ ...muted, margin: "0 0 10px" }}>{caption}</p></figcaption>
      {children}
      <details style={{ marginTop: 8 }}><summary style={{ ...muted, cursor: "pointer" }}>Data table</summary>{table}</details>
    </figure>
  );
}

export function DataTable({ head, rows }: { head: string[]; rows: Array<Array<ReactNode>> }) {
  const cell: CSSProperties = { padding: "4px 8px", borderBottom: "1px solid var(--border-light)", textAlign: "left", fontSize: 12 };
  return (
    <div style={{ maxHeight: 260, overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr>{head.map(h => <th key={h} scope="col" style={{ ...cell, ...muted }}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} style={cell}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** Equity curve with the drawdown underwater area below it. */
export function EquityDrawdown({ points }: { points: Array<[string, number]> }) {
  const W = 640, H = 220, top = 140;
  if (!points.length) return <p style={muted}>No equity history yet.</p>;
  const eq = points.map(p => n(p[1]));
  let peak = -Infinity;
  const dd = eq.map(v => { peak = Math.max(peak, v); return peak ? (v / peak - 1) * 100 : 0; });
  const lo = Math.min(...eq), hi = Math.max(...eq), ddLo = Math.min(-0.5, ...dd);
  const x = (i: number) => 40 + (i / Math.max(1, eq.length - 1)) * (W - 50);
  const y = (v: number) => 10 + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (top - 20);
  const yd = (v: number) => top + 10 + (v / ddLo) * (H - top - 20);
  const line = eq.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `M${x(0)},${yd(0)}` + dd.map((v, i) => `L${x(i).toFixed(1)},${yd(v).toFixed(1)}`).join("") + `L${x(eq.length - 1)},${yd(0)}Z`;
  const maxDd = Math.min(...dd);
  return (
    <Figure title="Equity and drawdown" caption={`Paper equity ${fmt(eq[0])} → ${fmt(eq[eq.length - 1])}; max drawdown ${fmt(maxDd)}%.`}
      table={<DataTable head={["time (UTC)", "equity", "drawdown %"]} rows={points.map((p, i) => [p[0].slice(0, 16), fmt(eq[i]), fmt(dd[i])])} />}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 300 }} role="img" aria-label="Equity line chart with drawdown area">
        <text x={2} y={14} fontSize={10} fill="currentColor">{fmt(hi, 0)}</text>
        <text x={2} y={top - 6} fontSize={10} fill="currentColor">{fmt(lo, 0)}</text>
        <path d={line} fill="none" stroke={C.blue} strokeWidth={2} />
        <line x1={40} x2={W - 10} y1={yd(0)} y2={yd(0)} stroke="currentColor" strokeOpacity={0.3} />
        <path d={area} fill={C.vermillion} fillOpacity={0.35} stroke={C.vermillion} strokeDasharray="3 2" />
        <text x={2} y={H - 6} fontSize={10} fill="currentColor">{fmt(ddLo, 1)}%</text>
        <text x={W - 150} y={14} fontSize={10} fill={C.blue}>━ equity</text>
        <text x={W - 80} y={14} fontSize={10} fill={C.vermillion}>┅ drawdown</text>
      </svg>
    </Figure>
  );
}

/** Bullet charts: how much of each limit is used. The founder daily-loss Safe stop is 2%. */
export function LossBullets({ gauges }: { gauges: Array<{ name: string; used: number; limit: number; unit?: string }> }) {
  const W = 640, row = 30;
  return (
    <Figure title="Loss-limit bullets" caption="Bar = used, tick = limit. Over-limit rows are marked ✕ and drawn in vermillion."
      table={<DataTable head={["limit", "used", "limit", "status"]} rows={gauges.map(g => [g.name, `${fmt(g.used)}${g.unit ?? ""}`, `${fmt(g.limit)}${g.unit ?? ""}`, n(g.used) > n(g.limit) ? "over" : "ok"])} />}>
      <svg viewBox={`0 0 ${W} ${gauges.length * row + 6}`} width="100%" role="img" aria-label="Limit usage bullet charts">
        {gauges.map((g, i) => {
          const max = Math.max(n(g.limit) * 1.5, n(g.used), 1e-9), sx = (v: number) => 170 + (v / max) * (W - 260);
          const over = n(g.used) > n(g.limit);
          return (
            <g key={g.name} transform={`translate(0 ${i * row})`}>
              <text x={0} y={18} fontSize={11} fill="currentColor">{g.name}</text>
              <rect x={170} y={6} width={W - 260} height={16} fill="currentColor" fillOpacity={0.08} />
              <rect x={170} y={10} width={Math.max(1, sx(n(g.used)) - 170)} height={8} fill={over ? C.vermillion : C.green} />
              <line x1={sx(n(g.limit))} x2={sx(n(g.limit))} y1={3} y2={25} stroke={C.orange} strokeWidth={3} />
              <text x={W - 84} y={18} fontSize={11} fill="currentColor">{over ? "✕ " : "✓ "}{fmt(g.used, 1)}/{fmt(g.limit, 1)}{g.unit ?? ""}</text>
            </g>
          );
        })}
      </svg>
    </Figure>
  );
}

export type Flow = { from: string; to: string; value: number };
/** Sankey of money flows (CAD), up to three columns: pure sources, pass-through nodes, pure sinks. */
export function MoneySankey({ flows, title = "Money flow (CAD)" }: { flows: Flow[]; title?: string }) {
  const W = 760, H = 260, nodeW = 10, gap = 10, pal = [C.blue, C.orange, C.green, C.purple, C.sky, C.vermillion];
  const live = flows.filter(f => f.value > 0);
  const names = Array.from(new Set(live.flatMap(f => [f.from, f.to])));
  const isSrc = (nm: string) => live.some(f => f.from === nm), isDst = (nm: string) => live.some(f => f.to === nm);
  const col = (nm: string) => (!isDst(nm) ? 0 : !isSrc(nm) ? 2 : 1);
  const cols = [0, 1, 2].map(c => names.filter(nm => col(nm) === c)).filter(c => c.length);
  const xs = cols.length === 3 ? [170, W / 2 - nodeW / 2, W - 180] : [170, W - 180];
  const size = (nm: string) => Math.max(live.filter(f => f.from === nm).reduce((a, f) => a + f.value, 0), live.filter(f => f.to === nm).reduce((a, f) => a + f.value, 0));
  const maxCol = Math.max(...cols.map(c => c.reduce((a, nm) => a + size(nm), 0)), 1);
  const scale = (H - gap * Math.max(...cols.map(c => c.length), 1)) / maxCol;
  const pos: Record<string, { x: number; y: number; h: number; out: number; inn: number; ci: number }> = {};
  cols.forEach((c, ci) => { let y = 0; for (const nm of c) { const h = size(nm) * scale; pos[nm] = { x: xs[ci], y, h, out: 0, inn: 0, ci }; y += h + gap; } });
  const colour = (nm: string) => pal[names.indexOf(nm) % pal.length];
  return (
    <Figure title={title} caption="Flows recorded in the non-custodial ledgers. Width is proportional to CAD amount; hover a band for its value."
      table={<DataTable head={["from", "to", "CAD"]} rows={live.map(f => [f.from, f.to, fmt(f.value)])} />}>
      {live.length ? (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 320 }} role="img" aria-label="Sankey diagram of money flows">
          {live.map((f, i) => {
            const a = pos[f.from], b = pos[f.to], h = f.value * scale;
            const y0 = a.y + a.out + h / 2, y1 = b.y + b.inn + h / 2, x0 = a.x + nodeW, x1 = b.x, mx = (x0 + x1) / 2;
            a.out += h; b.inn += h;
            return <path key={i} d={`M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1}`} stroke={colour(f.from)} strokeOpacity={0.45} strokeWidth={Math.max(1, h)} fill="none"><title>{`${f.from} → ${f.to}: ${fmt(f.value)} CAD`}</title></path>;
          })}
          {names.map(nm => { const p = pos[nm]; const right = p.ci === cols.length - 1 && cols.length > 1; return (
            <g key={nm}><rect x={p.x} y={p.y} width={nodeW} height={Math.max(2, p.h)} fill={colour(nm)} />
              <text x={right ? p.x + nodeW + 6 : p.x - 6} y={p.y + Math.max(2, p.h) / 2 + 4} fontSize={12} textAnchor={right ? "start" : "end"} fill="currentColor">{nm} {fmt(size(nm), 0)}</text></g>); })}
        </svg>
      ) : <p style={muted}>No flows recorded.</p>}
    </Figure>
  );
}

/** Tax waterfall: proceeds − ACB = gain; denied superficial losses are added back; allowable is what is reported. */
export function TaxWaterfall({ proceeds, acb, denied }: { proceeds: number; acb: number; denied: number }) {
  const gain = proceeds - acb, allowable = gain + denied;
  const steps = [
    { label: "Proceeds", start: 0, end: proceeds, color: C.blue },
    { label: "− ACB", start: proceeds, end: proceeds - acb, color: C.orange },
    { label: "= Gain/loss", start: 0, end: gain, color: gain >= 0 ? C.green : C.vermillion },
    { label: "+ Denied (superficial)", start: gain, end: allowable, color: C.purple },
    { label: "= Allowable", start: 0, end: allowable, color: allowable >= 0 ? C.green : C.vermillion },
  ];
  const W = 640, H = 220, vals = steps.flatMap(s => [s.start, s.end, 0]), hi = Math.max(...vals), lo = Math.min(...vals);
  const y = (v: number) => 10 + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (H - 50), bw = (W - 40) / steps.length;
  return (
    <Figure title="Capital gains waterfall (CAD)" caption="Adjusted cost base method; denied superficial losses are added to the replacement ACB (ITA s.54)."
      table={<DataTable head={["step", "amount CAD"]} rows={steps.map(s => [s.label, fmt(s.end - s.start)])} />}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 300 }} role="img" aria-label="Tax waterfall chart">
        <line x1={20} x2={W - 10} y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity={0.4} />
        {steps.map((s, i) => (
          <g key={s.label}>
            <rect x={24 + i * bw} y={Math.min(y(s.start), y(s.end))} width={bw - 16} height={Math.max(1, Math.abs(y(s.start) - y(s.end)))} fill={s.color} />
            <text x={24 + i * bw} y={H - 24} fontSize={10} fill="currentColor">{s.label}</text>
            <text x={24 + i * bw} y={H - 10} fontSize={10} fill="currentColor">{fmt(s.end - s.start, 0)}</text>
          </g>
        ))}
      </svg>
    </Figure>
  );
}

export type TimelineItem = { date: string; label: string; status: string };
/** FINTRAC timeline: report deadlines and record events. Status uses shape + text, not colour alone. */
export function FintracTimeline({ items }: { items: TimelineItem[] }) {
  const W = 640, H = 120, sorted = [...items].filter(i => i.date).sort((a, b) => a.date.localeCompare(b.date));
  const t = sorted.map(i => Date.parse(i.date)), t0 = Math.min(...t), t1 = Math.max(...t);
  const x = (v: number) => 20 + ((v - t0) / Math.max(1, t1 - t0)) * (W - 40);
  const mark = (s: string) => (/open|due|pending/i.test(s) ? { c: C.vermillion, sh: "▲" } : /filed|done|closed|ok/i.test(s) ? { c: C.green, sh: "●" } : { c: C.orange, sh: "◆" });
  return (
    <Figure title="FINTRAC timeline" caption="▲ open/due · ● filed/closed · ◆ other. Record keeping for review; not legal advice."
      table={<DataTable head={["date", "record", "status"]} rows={sorted.map(i => [i.date, i.label, i.status])} />}>
      {sorted.length ? (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="FINTRAC record timeline">
          <line x1={20} x2={W - 20} y1={60} y2={60} stroke="currentColor" strokeOpacity={0.4} />
          {sorted.map((i, k) => { const m = mark(i.status), xx = x(t[k]); return (
            <g key={k}><text x={xx} y={64} fontSize={14} textAnchor="middle" fill={m.c}>{m.sh}</text>
              <text x={xx} y={k % 2 ? 90 : 40} fontSize={9} textAnchor="middle" fill="currentColor">{i.date.slice(5)} {i.label.slice(0, 18)}</text></g>); })}
        </svg>
      ) : <p style={muted}>No FINTRAC records.</p>}
    </Figure>
  );
}
