// evo-16 hotfix: a timeframe without stored bars shows the labelled forecast + info banner, never the old "No 1m feed bars" dead end,
// and the forecast component draws lines only (no candlestick series, no setData of OHLC).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const chart = readFileSync(new URL("../src/components/market/AtlasChart.tsx", import.meta.url), "utf8");
const only = readFileSync(new URL("../src/components/market/NowcastOnly.tsx", import.meta.url), "utf8");

test("the chart no longer dead-ends on 'feed bars ... yet'", () => {
  assert.ok(!/feed bars for/.test(chart));
  assert.ok(/NowcastOnly/.test(chart) && /nowcast-info-banner/.test(chart));
});
test("forecast-only chart never draws candles", () => {
  assert.ok(!/addCandlestickSeries|addBarSeries/.test(only));
  assert.ok(/LineStyle\.Dashed/.test(only) && /LineStyle\.Dotted/.test(only) && /Predicted/.test(only));
  assert.ok(/not market data/.test(only) && /last real/.test(only));
});

// evo-17: the research ensemble's live record sits next to the dashed line and on the health page; it is labelled research / gated.
const chips = readFileSync(new URL("../src/components/market/HorizonChips.tsx", import.meta.url), "utf8");
const health = readFileSync(new URL("../src/ui/pages/PredictionHealth.tsx", import.meta.url), "utf8");
test("horizon chips show live hit rate, coverage and n, and say research / gated", () => {
  assert.ok(/HorizonChips/.test(chart) && /hit \$\{pct/.test(chips) && /cover \$\{pct/.test(chips) && /n=/.test(chips));
  assert.ok(/gated/.test(chips) && /exec none/.test(chips) && /execution_permission: none/.test(chips));
});
test("health page lists ensemble weights, per-model live scores and the transfer tag", () => {
  assert.ok(/horizons\/status/.test(health) && /weights_basis/.test(health) && /Moves dashed line/.test(health));
  assert.ok(/prophet/.test(health) && /transfer/.test(health) && /execution_permission none/.test(health));
});
