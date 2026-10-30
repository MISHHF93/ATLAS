import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { loadNav, root } from "./nav-registry.mjs";

const nav = loadNav();
const { PAGES, redirectTarget, legacyRedirects } = nav;
const fixture = (n) => JSON.parse(readFileSync(path.join(root, "scripts/fixtures", n), "utf8"));
const allRoutes = PAGES.flatMap((p) => p.tabs.map((t) => `${p.id}.${t.id}`));

test("registry and panels agree: every route id has a panel loader and every loader has a route id", () => {
  const src = readFileSync(path.join(root, "src/nav/panels.tsx"), "utf8");
  const keys = [...src.matchAll(/^\s*"([a-z]+\.[a-z-]+)":/gm)].map((m) => m[1]);
  assert.equal(new Set(keys).size, keys.length, "duplicate panel key");
  assert.deepEqual([...keys].sort(), [...allRoutes].sort());
});

test("workspace views named by the config exist exactly once", () => {
  const views = PAGES.flatMap((p) => p.tabs.filter((t) => t.workspace).map((t) => t.workspace));
  assert.equal(new Set(views).size, views.length, "two tabs claim one desk view");
});

test("every former address (121, frozen from the old registry) redirects to the agreed tab", () => {
  const expected = fixture("legacy-expected.json");
  const old = fixture("legacy-urls.json");
  assert.equal(Object.keys(expected).length, old.length);
  const redirects = legacyRedirects();
  const covered = (url) => {
    const [p, q] = url.split("?");
    const tab = q ? new URLSearchParams(q).get("tab") : null;
    // a request is handled by the first rule matching its path whose tab condition (if any) holds
    const rule = redirects.find((r) => r.source === p && (!r.has || r.has[0].value === tab));
    return rule;
  };
  for (const [url, dest] of Object.entries(expected)) {
    const livePage = PAGES.find((pg) => pg.href === url.split("?")[0]);
    const liveTab = url.includes("?") ? new URLSearchParams(url.split("?")[1]).get("tab") : null;
    const live = livePage && (!liveTab || livePage.tabs.some((t) => t.id === liveTab)) ? livePage : null;
    if (live) { // a live address: it must name a real tab and need no redirect (bare /data is the one deliberate exception, below)
      assert.equal(redirectTarget(url), null, `${url} is live`);
      const tab = url.includes("?") ? new URLSearchParams(url.split("?")[1]).get("tab") : live.tabs[0].id;
      if (url !== "/data") { assert.ok(live.tabs.some((t) => t.id === tab), `${url}: no such tab`); assert.equal(tab === live.tabs[0].id ? live.href : url, dest); }
      continue;
    }
    const rule = covered(url);
    assert.ok(rule, `no redirect rule for ${url}`);
    assert.equal(redirectTarget(url), dest, `${url}`);
    // what the browser ends at: the rule's destination (explicit ?tab= wins over the request query)
    const end = rule.destination;
    const norm = (u) => { const x = new URL(u, "http://x"); return x.pathname + (x.searchParams.get("tab") ? `?tab=${x.searchParams.get("tab")}` : ""); };
    const firstTab = (u) => { const x = new URL(u, "http://x"); const page = PAGES.find((pg) => pg.href === x.pathname); return x.searchParams.get("tab") === page.tabs[0].id ? page.href : u; };
    assert.equal(norm(firstTab(end)), dest, `${url} -> ${end}`);
  }
});

test("exception: /data is the Data page (its old bare alias for Bar query is not redirected)", () => {
  assert.equal(PAGES.find((p) => p.href === "/data").id, "data");
  assert.ok(!legacyRedirects().some((r) => r.source === "/data" && !r.has));
  assert.equal(redirectTarget("/data?tab=bars"), null);
  assert.ok(PAGES.find((p) => p.id === "data").tabs.some((t) => t.id === "bars"));
});

test("old ?tab= values on old paths keep working (old page + tab -> new page + tab)", () => {
  for (const [from, to] of Object.entries({
    "/trade?tab=paper": "/account?tab=paper", "/trade?tab=depth": "/markets?tab=depth", "/control?tab=autopilot": "/account?tab=autopilot",
    "/research?tab=agents": "/news?tab=agents", "/research/lab?tab=ml": "/predictions?tab=models", "/compliance?tab=audit": "/money?tab=audit",
    "/settings?tab=reserve": "/data?tab=reserve", "/settings?tab=bars": "/data?tab=bars", "/inbox": "/?tab=inbox",
  })) assert.equal(redirectTarget(from), to, from);
});

test("no hard-coded internal page links outside the nav config (links come from the registry)", () => {
  const skip = new Set(["src/nav/nav.config.ts"]);
  const patterns = [/href=["']\/(?!api\/)[^"'#]*["']/, /href=\{["']\/(?!api\/)[^"']*["']\}/, /href:\s*["']\/(?!api\/)[^"']*["']/, /\.push\(["']\//, /\.replace\(["']\//, /\.assign\(["']\//, /redirect\(["']\//];
  const bad = [];
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      if (name === "node_modules" || name === ".next") continue;
      const file = path.join(dir, name);
      if (statSync(file).isDirectory()) { walk(file); continue; }
      if (!/\.(tsx?|jsx?)$/.test(name)) continue;
      const rel = path.relative(root, file).split(path.sep).join("/");
      if (skip.has(rel)) continue;
      readFileSync(file, "utf8").split("\n").forEach((line, i) => {
        if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
        if (patterns.some((re) => re.test(line))) bad.push(`${rel}:${i + 1}: ${line.trim().slice(0, 100)}`);
      });
    }
  })(path.join(root, "src")) ;
  (function walk(dir) { for (const name of readdirSync(dir)) { const f = path.join(dir, name); if (statSync(f).isDirectory()) walk(f); else if (/\.tsx?$/.test(name)) readFileSync(f, "utf8").split("\n").forEach((l, i) => { if (patterns.some((re) => re.test(l))) bad.push(`app/${path.relative(path.join(root, "app"), f)}:${i + 1}: ${l.trim().slice(0, 100)}`); }); } })(path.join(root, "app"));
  assert.deepEqual(bad, []);
});

test("brand: logo mark is the Home link labelled 'ATLAS home' and the wordmark is not hidden by CSS", () => {
  const shell = readFileSync(path.join(root, "src/ui/AppShell.tsx"), "utf8");
  assert.match(shell, /<NavLink to="home"[^>]*aria-label="ATLAS home"/);
  assert.match(shell, /<AtlasLogo[^>]*wordmark/);
  const css = readFileSync(path.join(root, "src/ui/tokens.css"), "utf8");
  assert.ok(!/\.ux-brand svg \+ \*/.test(css), "wordmark must stay visible");
});

test("single Safe-stop control: no Engage button or release CLI inside tabs' desk views", () => {
  for (const f of ["src/components/shell/InstitutionalWorkspacesView.tsx", "src/components/workbench/StreamlinedTradingStudio.tsx", "src/components/market/Module02ListingsView.tsx"]) {
    const t = readFileSync(path.join(root, f), "utf8");
    assert.ok(!/Engage Safe stop/.test(t) && !/SafeStopReleaseCli/.test(t), `${f} still has its own Safe stop control`);
  }
});
