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
