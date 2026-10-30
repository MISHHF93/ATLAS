// Runtime one-chart guard: loads every page/tab from the page registry and fails if any symbol has more than
// one full price chart mounted ([data-atlas-chart]) or if a Lightweight Charts canvas renders outside AtlasChart.
// Usage: node scripts/one-chart.check.mjs [baseUrl]   (needs playwright; CHROMIUM_PATH optional)
import { pagesFromRegistry } from "./registry-pages.mjs";
const base = (process.argv.slice(2).find((a) => /^https?:/.test(a)) ?? "http://127.0.0.1:3000").replace(/\/$/, "");
const OUTSIDE_ALLOW = new Set();
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pages = pagesFromRegistry(); let fail = 0;
if (!Object.keys(pages).length) { console.error("one-chart: no pages loaded from nav.config.ts"); process.exit(2); }
for (const [id, href] of Object.entries(pages)) {
  try { await page.goto(base + href, { waitUntil: "networkidle", timeout: 30000 }); } catch { /* count what rendered */ }
  await page.waitForTimeout(800);
  const r = await page.evaluate(() => {
    const per = {};
    document.querySelectorAll("[data-atlas-chart]").forEach((n) => { const s = n.getAttribute("data-atlas-chart"); per[s] = (per[s] ?? 0) + 1; });
    const outside = [...document.querySelectorAll(".tv-lightweight-charts")].filter((n) => !n.closest("[data-atlas-chart]")).length;
    return { per, outside };
  });
  const dup = Object.entries(r.per).filter(([, n]) => n > 1);
  const bad = dup.length || (r.outside && !OUTSIDE_ALLOW.has(id));
  if (bad) fail++;
  console.log(`${bad ? "FAIL" : "ok  "} ${id.padEnd(22)} charts=${JSON.stringify(r.per)} outside=${r.outside}`);
}
await browser.close();
if (fail) { console.error(`${fail} page(s) mount more than one chart per asset`); process.exit(1); }
