// Loads the one typed nav config (src/nav/nav.config.ts) for node tests and browser checks. No side effects.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function loadNav() {
  const file = path.join(root, "src/nav/nav.config.ts");
  const out = ts.transpileModule(readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = {};
  new Function("exports", out)(mod);
  return mod;
}

/** { "markets": "/markets", "markets-depth": "/markets?tab=depth", ... } for browser crawls. */
export function pagesFromRegistry() {
  const { PAGES, tabHref } = loadNav();
  const out = {};
  for (const page of PAGES) {
    out[page.id] = page.href;
    page.tabs.slice(1).forEach((t) => { out[`${page.id}-${t.id}`] = tabHref(page, t.id); });
  }
  return out;
}
