// Browser regression against a running ATLAS server. All chart data is an
// intercepted local fixture; no training, evolution, or orders are requested.
// CHROMIUM_PATH can point to an installed Chrome executable.
import assert from "node:assert/strict";
import { chromium } from "playwright";

const base = (process.argv[2] ?? "http://127.0.0.1:3000").replace(/\/$/, "");
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let intercepted = 0;
  await page.route("**/api/ai/chart/overlays?**", async route => {
    intercepted++;
    const query = new URL(route.request().url()).searchParams;
    const bars = Array.from({ length: 12 }, (_, i) => ({
      time: 1792548000 + (i - 8) * 900,
      open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 10 + i,
    }));
    const marker = (id, probability) => ({
      id, source: "evolution_oos", strategy: "browser_fixture", direction: "long",
      time: bars[8].time, detected_at: bars[8].time + 900, price: bars[8].close,
      stop: 105, target: 115, probability, probability_label: "test fixture", uncertainty: null,
      ev_r: null, model_version: "fixture", risk_status: "research", class: "ml_suggested",
      outcome: "target", r: 1,
      resolution_path: [
        { time: bars[10].time, value: 111 }, { time: bars[8].time, value: 109 },
        { time: bars[9].time, value: 110 }, { time: bars[10].time, value: 112, exit: true },
      ],
    });
    const markers = [marker("duplicate-a", 0.6), marker("duplicate-b", 0.7)];
    const points = bars.map(b => ({ time: b.time, value: 0.6, take: false }));
    points.splice(9, 0, { time: bars[8].time, value: 0.7, take: true });
    points.push({ time: bars[0].time, value: 0.5, take: false });
    const payload = {
      status: "ok", symbol: query.get("symbol"), interval: query.get("interval"),
      bar_type: "time", execution_permission: "none", display: { status: "ok", kind: "time" },
      provider: { provider: "local_test_fixture", providers: ["local_test_fixture"], realtime: false, delay_label: "test fixture", built: "test fixture" },
      // Also exercise unsorted/repeated candles, overlapping regimes and VWAP.
      bars: [bars[2], ...bars, bars[8]],
      layers: {
        ml_markers: { status: "ok", items: markers },
        ml_probability: { status: "ok", points },
        vwap: { status: "ok", points: [bars[2], ...bars, bars[8]].map(b => ({ time: b.time, value: b.close })) },
        regimes: { status: "ok", current: "up", spans: [
          { from: bars[0].time, to: bars[8].time, trend: "up", label: "up" },
          { from: bars[8].time, to: bars[11].time, trend: "down", label: "down" },
        ] },
        predictions: { status: "ok", calibration: null, items: markers.map(m => ({
          time: m.time, p: m.probability, take: true, outcome: "target", hit: true, id: m.id, calibrator: "fixture",
        })) },
      },
      ml_panel: { execution_permission: "none", evolution: null, champion: null, current_model: null, why: [] },
    };
    await route.fulfill({ json: payload });
  });
  await page.goto(base + "/trade", { waitUntil: "domcontentloaded", timeout: 60000 });
  const chart = page.locator("[data-atlas-chart]").first();
  await chart.locator(".tv-lightweight-charts canvas").first().waitFor({ state: "visible", timeout: 45000 });
  await chart.getByText("2 out-of-sample predictions in view", { exact: false }).waitFor();
  await chart.getByRole("checkbox", { name: "Regime", exact: true }).check();
  const probability = chart.getByRole("checkbox", { name: "ML probability", exact: true });
  await probability.uncheck();
  await probability.check();
  const markerButton = chart.locator('[data-marker-id="duplicate-b"]');
  await markerButton.waitFor({ state: "visible" });
  await markerButton.click({ force: true });
  await chart.getByRole("dialog", { name: "Marker details" }).waitFor();
  await page.waitForTimeout(500);
  assert.ok(intercepted > 0, "The chart must render the regression fixture");
  assert.equal(await chart.locator(".tv-lightweight-charts").count(), 1);
  assert.equal(await chart.locator("[data-marker-id]").count(), 2, "Both simultaneous candidate markers survive");
  assert.deepEqual(errors, [], "No chart assertion or React runtime error");
  console.log("PASS /trade: repeated/unsorted series, overlapping regimes, layer toggles, both markers, and resolution path");
} finally {
  await browser.close();
}
