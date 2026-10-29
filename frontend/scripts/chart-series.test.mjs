import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/market/chartSeries.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017 },
}).outputText;
const exports = {};
new Function("exports", compiled)(exports);
const { orderedChartPoints } = exports;

test("repeated prediction timestamps keep the final value and color at the real candle time", () => {
  const points = Array.from({ length: 10 }, (_, i) => ({
    time: 1792548000 + i * 900, value: 0.4, color: "skip",
  }));
  points.splice(9, 0, { ...points[8], value: 0.71, color: "take" });
  const result = orderedChartPoints(points);
  assert.equal(result.length, 10);
  assert.deepEqual(result[8], { time: 1792555200, value: 0.71, color: "take" });
  assert.ok(result.every((p, i) => i === 0 || p.time > result[i - 1].time));
  // The prediction records remain intact; only the chart's display series collapses.
  assert.equal(points.length, 11);
});

test("out-of-order candles and overlapping regimes retain one complete point per time", () => {
  const first = Object.freeze({ time: 20, open: 10, high: 12, low: 9, close: 11 });
  const revision = Object.freeze({ time: 20, open: 10, high: 13, low: 9, close: 12 });
  const input = Object.freeze([first, Object.freeze({ ...first, time: 10 }), revision]);
  const result = orderedChartPoints(input);
  assert.deepEqual(result.map(p => p.time), [10, 20]);
  assert.equal(result[1], revision);
  assert.deepEqual(input.map(p => p.time), [20, 10, 20]);
  assert.deepEqual(orderedChartPoints([
    { time: 20, value: 1, color: "up" }, { time: 10, value: 1, color: "up" },
    { time: 20, value: 1, color: "down" },
  ]), [{ time: 10, value: 1, color: "up" }, { time: 20, value: 1, color: "down" }]);
});

test("invalid times are discarded without coercing or shifting valid timestamps", () => {
  const points = [{ time: NaN, value: 1 }, { time: Infinity, value: 2 },
    { time: -Infinity, value: 3 }, { time: 0, value: 4 }, { time: 1.25, value: 5 }];
  assert.deepEqual(orderedChartPoints(points), points.slice(3));
  assert.deepEqual(orderedChartPoints([]), []);
});

test("resolution paths sort all observations instead of dropping an out-of-order run", () => {
  const path = [
    { time: 30, value: 103 }, { time: 10, value: 101 }, { time: 20, value: 102 },
    { time: 30, value: 104, exit: true },
  ];
  assert.deepEqual(orderedChartPoints(path), [path[1], path[2], path[3]]);
});
