// Crawl ATLAS pages: every visible [data-quote-price] must sit with a [data-quote-status] (and a source when a price is
// shown). Saves a full-page screenshot per page. Usage: BASE=http://localhost:3310 OUT=/workspace/shots/data2 node scripts/quote_crawl.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const BASE = process.env.BASE ?? "http://localhost:3000";
const OUT = process.env.OUT ?? "shots";
const PAGES = (process.env.PAGES ?? "/,/trade,/research,/data/pipelines,/settings").split(",");
const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, timezoneId: "America/Toronto" });
let failures = 0;
const summary = [];
for (const route of PAGES) {
  await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(Number(process.env.SETTLE_MS ?? 12000));
  const res = await page.evaluate(() => {
    const out = { prices: 0, shown: 0, bad: [], statuses: {} };
    for (const el of document.querySelectorAll("[data-quote-price]")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      out.prices++;
      const price = el.getAttribute("data-quote-price");
      let node = el, meta = null;
      for (let i = 0; i < 7 && node && !meta; i++) { node = node.parentElement; meta = node?.querySelector("[data-quote-status]") ?? null; }
      const status = meta?.getAttribute("data-quote-status");
      const source = meta?.getAttribute("data-quote-source");
      if (status) out.statuses[status] = (out.statuses[status] ?? 0) + 1;
      if (price !== "none") out.shown++;
      if (!status || (price !== "none" && !source)) out.bad.push({ price, status, source, text: el.textContent?.slice(0, 40) });
    }
    return out;
  });
  const file = `${OUT}/${route === "/" ? "home" : route.slice(1).replace(/\//g, "_")}.png`;
  await page.screenshot({ path: file, fullPage: false });
  summary.push({ route, ...res, bad: res.bad.slice(0, 5), badCount: res.bad.length, file });
  failures += res.bad.length;
}
console.log(JSON.stringify(summary, null, 1));
await browser.close();
process.exit(failures ? 1 : 0);
