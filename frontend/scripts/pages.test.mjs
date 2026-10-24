import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const compiled = ts.transpileModule(readFileSync(path.join(root, "src/components/shell/pagesMap.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
const registry = {};
new Function("exports", compiled)(registry);
const { PAGES, pageForPath, hrefForWorkspace, redirectTarget, tabHref, legacyRedirects } = registry;
const allAliases = page => [...(page.aliases ?? []), ...(page.tabs ?? []).flatMap(t => t.aliases ?? [])];

test("each page and legacy address has exactly one owner", () => {
  const addresses = PAGES.flatMap(page => [page.href, ...allAliases(page)]);
  assert.equal(new Set(addresses).size, addresses.length);
  assert.equal(new Set(PAGES.map(page => page.id)).size, PAGES.length);
  for (const page of PAGES) {
    assert.equal(pageForPath(page.href), page);
    for (const alias of allAliases(page)) assert.equal(pageForPath(alias), page);
    for (const tab of page.tabs ?? []) {
      if (tab.workspaceRoute) assert.equal(hrefForWorkspace(tab.workspaceRoute), tabHref(page, tab.id));
      for (const alias of tab.aliases ?? []) assert.equal(redirectTarget(alias), tabHref(page, tab.id));
    }
  }
});

test("app/ holds only canonical pages; every former address is a permanent next.config redirect", () => {
  const app = path.join(root, "app");
  const known = new Set();
  function visit(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.name === "page.tsx") {
        const suffix = path.relative(app, dir).split(path.sep).join("/");
        const route = suffix ? `/${suffix}` : "/";
        known.add(route);
        assert.ok(PAGES.some(page => page.href === route), `Page file that is not a canonical hub: ${route}`);
        assert.equal(readFileSync(file, "utf8").match(/redirect\("/), null, `Stub redirect page left behind: ${route}`);
      }
    }
  }
  visit(app);
  for (const page of PAGES) assert.ok(known.has(page.href), `Missing canonical page: ${page.href}`);
  const redirects = legacyRedirects();
  const sources = redirects.map(r => r.source + (r.has ? `?tab=${r.has[0].value}` : ""));
  assert.equal(new Set(sources).size, sources.length, "duplicate redirect source");
  for (const r of redirects) {
    assert.equal(r.permanent, true);
    const target = r.destination.split("?")[0];
    assert.ok(PAGES.some(page => page.href === target), `Redirect to a non-canonical page: ${r.source} -> ${r.destination}`);
    if (!r.has) assert.ok(!known.has(r.source), `Redirect source still has a page file: ${r.source}`);
  }
  for (const r of redirects.filter(r => r.has)) {
    assert.match(r.destination, /\?tab=/, `retired-tab redirect must name its tab explicitly: ${r.source}`);
    assert.notEqual(new URL(r.destination, "http://x").searchParams.get("tab"), r.has[0].value, `redirect loop: ${r.source}`);
  }
  for (const page of PAGES) for (const alias of allAliases(page)) assert.ok(redirects.some(r => r.source === alias && !r.has), `No redirect for ${alias}`);
});

test("retired tabs open the tab that absorbed them", () => {
  for (const [from, to] of Object.entries({
    "/control?tab=positions": "/control", "/research/lab?tab=microstructure": "/research", "/research/lab?tab=fourbox": "/research?tab=zones",
  })) assert.equal(redirectTarget(from), to);
  const lab = PAGES.find(p => p.id === "lab");
  assert.ok(!lab.tabs.some(t => t.id === "microstructure" || t.id === "fourbox"));
  assert.ok(!PAGES.find(p => p.id === "risk").tabs.some(t => t.id === "positions"));
});

test("retired workspace destinations resolve to their consolidated pages", () => {
  for (const [route, href] of Object.entries({
    "/trade/cockpit": "/trade", "/trade/journal": "/compliance?tab=audit",
    "/control/dealing-desk": "/control", "/trade/blotter": "/control", "/research/microstructure": "/research",
    "/data/pipelines": "/settings?tab=connectors", "/research/registry": "/research/evidence?tab=training",
  })) assert.equal(hrefForWorkspace(route), href);
});

test("navigation stays compact: 10-14 main destinations, every hub tab has a plain summary", () => {
  const main = PAGES.filter(p => !p.advanced);
  assert.ok(main.length >= 10 && main.length <= 14, `main destinations: ${main.length}`);
  for (const p of PAGES) {
    assert.ok(p.summary.length > 20 && p.summary.length < 160, `summary length: ${p.id}`);
    for (const t of p.tabs ?? []) assert.ok(t.summary.length > 20 && t.summary.length < 160, `tab summary: ${p.id}/${t.id}`);
  }
});
