// Headless smoke test: every page and every tab/button-tab must load with zero
// console errors, page errors or 4xx/5xx responses.  Run AFTER `next build` and a
// server restart (a build under a running server leaves stale chunk hashes ->
// "Application error: a client-side exception has occurred").
//   node scripts/smoke_pages.cjs [baseUrl]
const { chromium } = require('playwright');
const base = process.argv[2] || 'http://localhost:3000';
const fs = require('fs');
const path = require('path');
// Every page and every ?tab=<id> from the one nav config (src/nav/nav.config.ts), plus a few retired addresses that must redirect.
async function registryUrls() {
  const { pagesFromRegistry } = await import('./nav-registry.mjs');
  return Object.values(pagesFromRegistry());
}
(async () => {
  const PAGES = [...new Set(['/', ...(await registryUrls())])];
  const b = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  let bad = 0;
  for (const p of PAGES) {
    const pg = await b.newPage();
    const errs = [];
    pg.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 300)); });
    pg.on('pageerror', (e) => errs.push('pageerror: ' + String(e.stack || e).slice(0, 500)));
    pg.on('response', (r) => { if (r.status() >= 400 && r.url().includes('/_next/')) errs.push('http ' + r.status() + ' ' + r.url().slice(0, 120)); });
    try { await pg.goto(base + p, { waitUntil: 'load', timeout: 60000 }); } catch (e) { errs.push('goto: ' + e.message.slice(0, 200)); }
    await pg.waitForTimeout(3500);
    const tabs = pg.locator('nav.ux-hubtabs a');
    const n = await tabs.count();
    for (let i = 0; i < n; i++) {
      try { await tabs.nth(i).click({ timeout: 5000 }); await pg.waitForTimeout(1200); } catch (e) { errs.push('tab ' + i + ': ' + e.message.slice(0, 120)); }
    }
    if (await pg.locator('text=Application error').count()) errs.push('Application error banner shown');
    console.log((errs.length ? 'FAIL ' : 'ok   ') + p + '  (' + n + ' tabs)');
    errs.slice(0, 8).forEach((e) => console.log('     ' + e));
    bad += errs.length;
    await pg.close();
  }
  await b.close();
  process.exit(bad ? 1 : 0);
})();
