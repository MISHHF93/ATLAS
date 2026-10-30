import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { loadNav, root } from "./nav-registry.mjs";

const nav = loadNav();
const { PAGES, NAV_SECTIONS, pageForPath, hrefForWorkspace, redirectTarget, tabHref, legacyRedirects, href } = nav;

test("navigation stays compact: 9 pages, at most 8 header items, at most 8 tabs per page, plain summaries", () => {
  assert.equal(PAGES.length, 9, "pages");
  const header = PAGES.filter((p) => p.placement === "header");
  assert.ok(header.length <= 8, `header items: ${header.length}`);
  assert.equal(PAGES.filter((p) => p.placement === "logo").length, 1, "exactly one page is the logo/Home link");
  assert.equal(PAGES.find((p) => p.placement === "logo").href, "/");
  assert.ok(PAGES.some((p) => p.id === "health"), "Health stays its own page");
  const sections = new Set(NAV_SECTIONS.map((s) => s.id));
  for (const p of PAGES) {
    assert.ok(sections.has(p.section), `unknown section: ${p.id}`);
    assert.ok(p.tabs.length >= 1 && p.tabs.length <= 8, `tabs on ${p.id}: ${p.tabs.length}`);
    assert.ok(p.summary.length > 20 && p.summary.length < 160, `summary length: ${p.id}`);
    for (const t of p.tabs) assert.ok(t.summary.length > 20 && t.summary.length < 160, `tab summary: ${p.id}/${t.id}`);
  }
});

test("canonical addresses are the agreed ones and each is unique", () => {
  assert.deepEqual(PAGES.map((p) => p.href), ["/", "/markets", "/predictions", "/news", "/account", "/money", "/data", "/health", "/settings"]);
  const ids = PAGES.flatMap((p) => p.tabs.map((t) => `${p.id}.${t.id}`));
  assert.equal(new Set(ids).size, ids.length, "duplicate route id");
  assert.equal(new Set(PAGES.map((p) => p.id)).size, PAGES.length);
  for (const p of PAGES) {
    assert.equal(tabHref(p, p.tabs[0].id), p.href, "first tab is the bare address");
    for (const t of p.tabs.slice(1)) assert.equal(tabHref(p, t.id), `${p.href}?tab=${t.id}`);
    assert.equal(href(p.id), p.href);
  }
});

test("app/ holds only the Home page and the [hub] page; no stub redirect pages", () => {
  const app = path.join(root, "app");
  const found = [];
  (function visit(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) visit(file);
      else if (entry.name === "page.tsx") {
        found.push(path.relative(app, file).split(path.sep).join("/"));
        assert.equal(readFileSync(file, "utf8").match(/redirect\("/), null, `stub redirect page: ${file}`);
      }
    }
  })(app);
  assert.deepEqual(found.sort(), ["[hub]/page.tsx", "page.tsx"]);
});

test("redirects: permanent, unique sources, tab rules explicit, never to a retired address, no loops", () => {
  const redirects = legacyRedirects();
  const keys = redirects.map((r) => r.source + (r.has ? `?tab=${r.has[0].value}` : ""));
  assert.equal(new Set(keys).size, keys.length, "duplicate redirect source");
  const canonical = new Set(PAGES.map((p) => p.href));
  const liveTab = (page, tab) => page.tabs.some((t) => t.id === tab);
  redirects.forEach((r, i) => {
    assert.equal(r.permanent, true);
    const dest = new URL(r.destination, "http://x");
    assert.ok(canonical.has(dest.pathname), `redirect to a non-canonical page: ${r.source} -> ${r.destination}`);
    const page = PAGES.find((p) => p.href === dest.pathname);
    const tab = dest.searchParams.get("tab");
    if (tab) assert.ok(liveTab(page, tab), `redirect to a tab that does not exist: ${r.source} -> ${r.destination}`);
    // a redirect source must never be a canonical page without a retired-tab condition (that would loop)
    if (!r.has) assert.ok(!canonical.has(r.source), `redirect source is a live page: ${r.source}`);
    if (r.has) {
      assert.match(r.destination, /\?tab=/, `retired-tab redirect must name its tab explicitly: ${r.source}`);
      if (dest.pathname === r.source) assert.ok(!liveTab(page, r.has[0].value) || tab !== r.has[0].value, `redirect loop: ${r.source}`);
      // tab rules must come before bare-path rules so the query condition is evaluated first
      assert.ok(!redirects.slice(0, i).some((x) => !x.has && x.source === r.source), `bare rule shadows tab rule: ${r.source}`);
    }
  });
});

test("retired desk workspace destinations resolve to their tab", () => {
  for (const [route, to] of Object.entries({
    "/trade/cockpit": "/markets", "/trade/journal": "/money?tab=audit", "/control/dealing-desk": "/account",
    "/trade/blotter": "/account", "/research/microstructure": "/markets?tab=read",
  })) assert.equal(hrefForWorkspace(route), to, route);
  assert.equal(pageForPath("/trade").id, "markets");
});
