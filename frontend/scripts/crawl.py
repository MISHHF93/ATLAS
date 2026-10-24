"""Visual crawl: screenshot every route (desktop+mobile), record console errors and non-2xx.
usage: python crawl.py BASE OUTDIR"""
import json, sys, re
from playwright.sync_api import sync_playwright
BASE, OUT = sys.argv[1], sys.argv[2]
import pathlib, os
app = pathlib.Path(__file__).resolve().parent.parent / "app"
routes = sorted({"/" + str(p.parent.relative_to(app)).replace(".", "") .strip("/") for p in app.rglob("page.tsx")})
routes = [r if r != "/" else "/" for r in routes] + ["/this-does-not-exist"]
if len(sys.argv) > 3: routes += [x for x in sys.argv[3].split(",") if x]  # extra routes, e.g. hub tab URLs
IGNORE = re.compile(r"tradingview|s3\.tradingview|widget", re.I)
os.makedirs(OUT, exist_ok=True)
report = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, vp in [("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})]:
        ctx = b.new_context(viewport=vp, device_scale_factor=1)
        for r in routes:
            pg = ctx.new_page(); errs = []; bad = []
            pg.on("console", lambda m: m.type == "error" and not IGNORE.search(m.text + str(m.location)) and errs.append(m.text[:200]))
            pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
            pg.on("response", lambda resp: (resp.status >= 400) and not IGNORE.search(resp.url) and not (resp.status == 404 and resp.url.rstrip("/").endswith("/this-does-not-exist")) and bad.append(f"{resp.status} {resp.url}"))
            try:
                resp = pg.goto(BASE + r, wait_until="load", timeout=45000)
            except Exception as e:
                try: resp = None; pg.wait_for_timeout(2000)
                except Exception: pass
                errs.append("nav: " + str(e)[:120])
            pg.wait_for_timeout(2500)
            slug = (r.strip("/").replace("/", "_").replace("?tab=", "__") or "home")
            pg.screenshot(path=f"{OUT}/{slug}--{name}.png", full_page=False)
            report.setdefault(r, {})[name] = {"final": pg.url.replace(BASE, ""), "status": resp.status if resp else None, "console": errs, "bad": bad,
                "title": pg.title()}
            pg.close()
        ctx.close()
    b.close()
json.dump(report, open(f"{OUT}/report.json", "w"), indent=1)
for r, v in report.items():
    d = v["desktop"]; m = v["mobile"]
    print(r, "->", d["final"], d["status"], "errs", len(d["console"]) + len(m["console"]), "bad", len(d["bad"]) + len(m["bad"]))
