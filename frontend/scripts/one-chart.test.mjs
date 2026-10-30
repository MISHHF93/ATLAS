// chart-2: exactly ONE full price chart per asset. Static guard (runs with test:routes):
//  - only AtlasChart creates a Lightweight Charts instance;
//  - the retired duplicate chart components stay deleted and unimported;
//  - the real-time view is a timeframe inside AtlasChart, not a separate viewer.
// Runtime guard: scripts/one-chart.check.mjs loads every page and fails if >1 chart mounts for a symbol.
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = [];
(function walk(d) {
  for (const e of readdirSync(d, { withFileTypes: true })) {
    if (["node_modules", ".next"].includes(e.name)) continue;
    const f = path.join(d, e.name);
    if (e.isDirectory()) walk(f); else if (/\.(tsx?|mjs)$/.test(e.name)) files.push(f);
  }
})(path.join(root, "src")), (function walk(d) {
  for (const e of readdirSync(d, { withFileTypes: true })) { const f = path.join(d, e.name); if (e.isDirectory()) walk(f); else if (/\.tsx?$/.test(e.name)) files.push(f); }
})(path.join(root, "app"));
const rel = (f) => path.relative(root, f).split(path.sep).join("/");
// AlpacaChartCard (paper tab) is the integrations worker's area; it plots the Alpaca paper account's own bars.
export const CREATE_CHART_ALLOW = new Set([
  "src/components/market/AtlasChart.tsx",
  "src/components/market/NowcastOnly.tsx", // sub-renderer of AtlasChart (its only importer); never mounted on its own
]);
export const RETIRED = ["LiveMarketViewer", "SecondBars", "LiveChartEngine", "AtlasUdfTape", "TvFrame"];

test("only AtlasChart creates a price chart", () => {
  const offenders = files.filter((f) => /\bcreateChart\s*\(/.test(readFileSync(f, "utf8")) && !CREATE_CHART_ALLOW.has(rel(f)));
  assert.deepEqual(offenders.map(rel), []);
});

test("retired duplicate chart components are gone and unimported", () => {
  for (const name of RETIRED) {
    assert.equal(existsSync(path.join(root, `src/components/market/${name}.tsx`)), false, `${name}.tsx should be deleted`);
    const users = files.filter((f) => new RegExp(`from ["'][^"']*/${name}["']`).test(readFileSync(f, "utf8")));
    assert.deepEqual(users.map(rel), [], `${name} still imported`);
  }
});

test("real time is a timeframe of AtlasChart, and DeskChart renders only AtlasChart", () => {
  const chart = readFileSync(path.join(root, "src/components/market/AtlasChart.tsx"), "utf8");
  assert.match(chart, /CHART_INTERVALS = \["live",/);
  const desk = readFileSync(path.join(root, "src/components/market/DeskChart.tsx"), "utf8");
  assert.equal((desk.match(/<AtlasChart\b/g) ?? []).length, 1);
  assert.doesNotMatch(desk, /SecondBars|LiveMarketViewer|createChart/);
});

test("no page mounts two AtlasCharts unconditionally side by side", () => {
  // A JSX fragment with two <AtlasChart> siblings with the same symbol expression is a duplicate.
  for (const f of files) {
    const src = readFileSync(f, "utf8").replace(/\r\n/g, "\n");
    const syms = [...src.matchAll(/<AtlasChart\s+symbol=\{([^}]+)\}/g)].map((m) => m[1].trim());
    const blocks = src.split(/\n\s*\)\}\n|\n\s*\) : |\n\s*: \(/);
    for (const b of blocks) {
      const inBlock = [...b.matchAll(/<AtlasChart\s+symbol=\{([^}]+)\}/g)].map((m) => m[1].trim());
      assert.equal(new Set(inBlock).size, inBlock.length, `${rel(f)} mounts the same symbol twice in one branch (${syms.join(", ")})`);
    }
  }
});
