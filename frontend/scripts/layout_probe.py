"""Screenshot pages at several widths and flag horizontal overflow / clipped text.
usage: layout_probe.py BASE OUTDIR [widths] [paths]"""
import json, sys
from playwright.sync_api import sync_playwright

PROBE = """() => {
  const out = {hscroll: document.documentElement.scrollWidth > window.innerWidth + 1, clipped: [], overflow: []};
  const vw = window.innerWidth;
  for (const el of document.querySelectorAll('main *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (el.closest('.tv-lightweight-charts, canvas, svg, .ux-table-wrap, [data-scroll], pre, code, table')) continue;
    if (r.right > vw + 2 && !el.closest('[data-fullbleed-scroll]')) out.overflow.push(`${el.tagName.toLowerCase()}.${(el.className||'').toString().split(' ')[0]} right=${Math.round(r.right)}`);
    const text = el.childNodes.length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (text && (cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.textOverflow === 'ellipsis') && el.scrollWidth > el.clientWidth + 2 && !el.title)
      out.clipped.push(`${el.tagName.toLowerCase()}.${(el.className||'').toString().split(' ')[0]}: ${el.textContent.trim().slice(0,40)}`);
  }
  out.overflow = [...new Set(out.overflow)].slice(0, 15); out.clipped = [...new Set(out.clipped)].slice(0, 15);
  return out;
}"""

def main():
    base, outdir = sys.argv[1], sys.argv[2]
    widths = [int(w) for w in (sys.argv[3] if len(sys.argv) > 3 else "1920,768").split(",")]
    paths = (sys.argv[4] if len(sys.argv) > 4 else "/,/trade,/money,/research,/research/price-action,/control").split(",")
    report = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in widths:
            pg = b.new_page(viewport={"width": w, "height": 1000 if w > 500 else 844})
            for path in paths:
                pg.goto(base + path, wait_until="load", timeout=45000); pg.wait_for_timeout(2500)
                name = (path.strip("/").replace("/", "_") or "home") + f"--{w}"
                pg.screenshot(path=f"{outdir}/{name}.png", full_page=False)
                report[name] = pg.evaluate(PROBE)
                print(name, "hscroll" if report[name]["hscroll"] else "ok", len(report[name]["overflow"]), len(report[name]["clipped"]))
        b.close()
    json.dump(report, open(f"{outdir}/layout.json", "w"), indent=1)
    bad = [k for k, v in report.items() if v["hscroll"] or v["overflow"] or v["clipped"]]
    print("LAYOUT_ISSUES", len(bad), bad)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
