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
const { PAGES, pageForPath, hrefForWorkspace, redirectTarget, tabHref } = registry;
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

test("every app page is canonical or redirects directly to its owner", () => {
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
        const owner = PAGES.find(page => page.href === route || allAliases(page).includes(route));
        assert.ok(owner, `Unregistered page: ${route}`);
        const source = readFileSync(file, "utf8");
        const redirect = source.match(/redirect\("([^"]+)"\)/)?.[1];
        if (owner.href === route) assert.equal(redirect, undefined, `Canonical page redirects: ${route}`);
        else assert.equal(redirect, redirectTarget(route), `Alias must redirect directly to its hub tab: ${route}`);
      }
    }
  }
  visit(app);
  for (const page of PAGES) {
    for (const route of [page.href, ...allAliases(page)]) assert.ok(known.has(route), `Missing route: ${route}`);
  }
});

test("retired workspace destinations resolve to their consolidated pages", () => {
  for (const [route, href] of Object.entries({
    "/trade/cockpit": "/trade", "/trade/journal": "/compliance?tab=audit",
    "/control/dealing-desk": "/control?tab=positions", "/research/microstructure": "/research",
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
