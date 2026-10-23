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
const { PAGES, pageForPath, hrefForWorkspace } = registry;

test("each page and legacy address has exactly one owner", () => {
  const addresses = PAGES.flatMap(page => [page.href, ...(page.aliases ?? [])]);
  assert.equal(new Set(addresses).size, addresses.length);
  assert.equal(new Set(PAGES.map(page => page.id)).size, PAGES.length);
  for (const page of PAGES) {
    assert.equal(pageForPath(page.href), page);
    for (const alias of page.aliases ?? []) assert.equal(pageForPath(alias), page);
    if (page.workspaceRoute) assert.equal(hrefForWorkspace(page.workspaceRoute), page.href);
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
        const owner = PAGES.find(page => page.href === route || page.aliases?.includes(route));
        assert.ok(owner, `Unregistered page: ${route}`);
        const source = readFileSync(file, "utf8");
        const redirect = source.match(/redirect\("([^"]+)"\)/)?.[1];
        if (owner.href === route) assert.equal(redirect, undefined, `Canonical page redirects: ${route}`);
        else assert.equal(redirect, owner.href, `Alias must redirect directly: ${route}`);
      }
    }
  }
  visit(app);
  for (const page of PAGES) {
    for (const route of [page.href, ...(page.aliases ?? [])]) assert.ok(known.has(route), `Missing route: ${route}`);
  }
});

test("retired workspace destinations resolve to their consolidated pages", () => {
  for (const [route, href] of Object.entries({
    "/trade/cockpit": "/", "/trade/journal": "/control/surveillance",
    "/control/dealing-desk": "/trade/blotter", "/research/microstructure": "/research",
  })) assert.equal(hrefForWorkspace(route), href);
});
