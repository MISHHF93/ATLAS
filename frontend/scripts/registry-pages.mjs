// Page list from the one page registry, shared by browser checks (no side effects on import).
import fs from "node:fs";
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
