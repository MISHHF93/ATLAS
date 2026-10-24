// Vertical-text guard: fails when any visible text is stacked into a narrow column
// (lines of <= 2 characters, or a box far taller than it is wide).
// Usage: node scripts/vertical-text.check.mjs [baseUrl] [--shots dir] [--json out.json]
// Needs `playwright` resolvable (PLAYWRIGHT_MODULE=/path/to/node_modules/playwright) and
// optionally CHROMIUM_PATH.
import fs from "node:fs";
import path from "node:path";
const args = process.argv.slice(2);
const base = (args.find((a) => /^https?:/.test(a)) ?? "http://127.0.0.1:3000").replace(/\/$/, "");
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const shots = opt("--shots"); const jsonOut = opt("--json");
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
// Every page and every non-default tab, read from the one page registry (src/components/shell/pagesMap.ts),
// so new pages are covered automatically. Falls back to nothing silently = never: an empty list fails the run.
export function pagesFromRegistry(file = new URL("../src/components/shell/pagesMap.ts", import.meta.url)) {
  const src = fs.readFileSync(file, "utf8");
  const body = src.slice(src.indexOf("export const PAGES"));
  const out = {};
  for (const blk of body.split(/\n  \{\n    id: /).slice(1)) {
    const id = /^"([^"]+)"/.exec(blk)?.[1]; const href = /href: "([^"]+)"/.exec(blk)?.[1];
    if (!id || !href) continue;
    out[id] = href;
    const tabsAt = blk.indexOf("tabs: [");
    if (tabsAt >= 0) [...blk.slice(tabsAt).matchAll(/\{ id: "([\w-]+)", label/g)].slice(1).forEach((m) => { out[`${id}-${m[1]}`] = `${href}?tab=${m[1]}`; });
  }
  return out;
}
export const PAGES = pagesFromRegistry();
const WIDTHS = [1440, 1024, 768, 390];

function scan() {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent ?? "").replace(/\s+/g, " ").trim();
    if (text.replace(/\s/g, "").length < 4) continue;
    const el = n.parentElement; if (!el || seen.has(el)) continue;
    if (el.closest("svg,script,style,canvas,[aria-hidden=true],[hidden]")) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || cs.writingMode.startsWith("vertical")) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rects = [...r.getClientRects()].filter((q) => q.width > 0 && q.height > 0);
    if (!rects.length) continue;
    // Merge rects into visual lines by top coordinate.
    const lines = [];
    for (const q of rects) { const l = lines.find((x) => Math.abs(x.top - q.top) < q.height / 2); if (l) { l.w += q.width; } else lines.push({ top: q.top, w: q.width }); }
    const box = r.getBoundingClientRect();
    if (box.width === 0) continue;
    const chars = text.replace(/\s/g, "").length;
    const perLine = chars / lines.length;
    const fs = parseFloat(cs.fontSize) || 12;
    const vertical = (lines.length >= 3 && perLine <= 2.5) || (lines.length >= 3 && box.height > box.width * 4 && box.width < fs * 3);
    if (vertical) {
      seen.add(el);
      out.push({ text: text.slice(0, 60), lines: lines.length, perLine: +perLine.toFixed(2), w: Math.round(box.width), h: Math.round(box.height),
        x: Math.round(box.left + scrollX), y: Math.round(box.top + scrollY), tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 60) });
    }
  }
  return out;
}

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const report = []; let total = 0; let loadFails = 0;
if (!Object.keys(PAGES).length) { console.error("vertical-text: no pages parsed from pagesMap.ts"); process.exit(2); }
for (const [name, url] of Object.entries(PAGES)) for (const w of WIDTHS) {
  const page = await browser.newPage({ viewport: { width: w, height: 900 } });
  let loadErr = "";
  try { const resp = await page.goto(base + url, { waitUntil: "load", timeout: 45000 }); if (!resp || resp.status() >= 400) loadErr = `HTTP ${resp?.status() ?? "none"}`; }
  catch (e) { loadErr = String(e?.message ?? e).split("\n")[0]; }
  await page.waitForTimeout(3500);
  const textLen = loadErr ? 0 : await page.evaluate(() => (document.body?.innerText ?? "").trim().length);
  if (!loadErr && textLen < 50) loadErr = `page rendered only ${textLen} chars of text`;
  if (loadErr) { loadFails++; report.push({ page: name, width: w, count: null, error: loadErr }); console.log(`LOAD ${name.padEnd(14)} ${String(w).padStart(4)}  ${loadErr}`); await page.close(); continue; }
  // Open every <details> so collapsed content is checked too.
  await page.evaluate(() => document.querySelectorAll("details").forEach((d) => { d.open = true; }));
  await page.waitForTimeout(400);
  const hits = await page.evaluate(scan);
  total += hits.length;
  report.push({ page: name, width: w, count: hits.length, samples: hits.slice(0, 8) });
  console.log(`${hits.length ? "FAIL" : "ok  "} ${name.padEnd(14)} ${String(w).padStart(4)}  ${hits.length} vertical text${hits.length ? ": " + hits.slice(0, 3).map((h) => JSON.stringify(h.text.slice(0, 24))).join(", ") : ""}`);
  if (shots && hits.length) {
    fs.mkdirSync(shots, { recursive: true });
    for (const [i, h] of hits.slice(0, 3).entries()) {
      try {
        const loc = page.locator(`text=${JSON.stringify(h.text.slice(0, 30))}`).first();
        await loc.scrollIntoViewIfNeeded({ timeout: 2000 });
        const b = await loc.boundingBox();
        if (b) await page.screenshot({ path: path.join(shots, `${name}-${w}-${i}.png`), clip: { x: Math.max(0, b.x - 160), y: Math.max(0, b.y - 60), width: Math.min(w - Math.max(0, b.x - 160), 480), height: Math.min(Math.max(b.height + 120, 200), 700) } });
      } catch {}
    }
  }
  await page.close();
}
await browser.close();
if (jsonOut) fs.writeFileSync(jsonOut, JSON.stringify(report, null, 2));
const checked = report.filter((r) => r.count !== null).length;
console.log(`\nvertical-text: checked ${checked}/${report.length} page/width combos (${Object.keys(PAGES).length} pages x ${WIDTHS.length} widths); ${total} instance(s) in ${report.filter((r) => r.count).length} combos; ${loadFails} failed to load`);
process.exit(loadFails ? 2 : total ? 1 : 0);
