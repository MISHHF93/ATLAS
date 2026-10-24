"""Interaction crawl: click every visible button/control on every canonical route.

Fails (exit 1) on console errors, unexpected 4xx/5xx (intended 403s from step-up-guarded
console actions are allowed) and dead controls (a click that changes nothing: no DOM
mutation, no request, no navigation, no dialog, no focus/aria change).
Mutating console actions (request start, create/revoke key, reject, engage Safe stop,
paper orders, sign out) are skipped or their confirm() dialogs dismissed, so the crawl
never changes system state.
usage: python interact.py BASE OUTDIR [paths]"""
import json, os, pathlib, re, sys
from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1], sys.argv[2]
app = pathlib.Path(__file__).resolve().parent.parent / "app"
routes = sorted({"/" + str(p.parent.relative_to(app)).strip(".").strip("/") for p in app.rglob("page.tsx")})
if len(sys.argv) > 3: routes = sys.argv[3].split(",")
IGNORE = re.compile(r"tradingview|widget", re.I)
ALLOWED_403 = re.compile(r"/api/console/(approvals/[^/]+/approve|keys)$|/api/founder/safe-stop/reset$")
SKIP = re.compile(r"request start|create key|switch off|^reject|revoke|sign out|log out|place|submit order|buy|sell|send|delete|engage|close all|flatten|release", re.I)
MAX = 80
os.makedirs(OUT, exist_ok=True)

PROBE = """() => { window.__mut = 0; if (!window.__mo) { window.__mo = new MutationObserver(m => { window.__mut += m.length; });
  window.__mo.observe(document.body, {subtree: true, childList: true, attributes: true, characterData: true}); } }"""
SNAP = """() => [document.activeElement && document.activeElement.outerHTML.slice(0, 80), location.href]"""
CONTROLS = "button:visible, [role=button]:visible, [role=tab]:visible, summary:visible, input[type=checkbox]:visible"

report, failures = {}, []
with sync_playwright() as p:
    b = p.chromium.launch()
    for vname, vp in [("desktop", {"width": 1440, "height": 900}), ("mobile", {"width": 390, "height": 844})]:
        ctx = b.new_context(viewport=vp)
        for r in routes:
            last = ["(load)"]; pg = ctx.new_page(); errs, bad, dead, skipped, clicked, reqs, dialogs = [], [], [], [], 0, [0], [0]
            pg.on("console", lambda m: m.type == "error" and not IGNORE.search(m.text + str(m.location)) and errs.append(m.text[:200]))
            pg.on("pageerror", lambda e: errs.append(f"pageerror after '{last[0]}': " + str(e)[:160] + " @ " + (e.stack or "").split("\n")[1:2].__str__()[:160]))
            pg.on("request", lambda q: reqs.__setitem__(0, reqs[0] + 1))
            def on_resp(resp):
                if resp.status < 400 or IGNORE.search(resp.url): return
                if resp.status == 403 and ALLOWED_403.search(resp.url.split("?")[0]): return
                if resp.status == 404 and "this-does-not-exist" in resp.url: return
                bad.append(f"{resp.status} {resp.request.method} {resp.url.replace(BASE, '')}")
            pg.on("response", on_resp)
            def on_dialog(d):
                dialogs[0] += 1; d.dismiss()
            pg.on("dialog", on_dialog)
            pg.goto(BASE + r, wait_until="load", timeout=45000); pg.wait_for_timeout(2000)
            if pg.url.replace(BASE, "").rstrip("/").replace("/?", "?") != r.rstrip("/").replace("/?", "?"):
                pg.close(); continue  # alias redirect; its target is crawled itself
            n = min(pg.locator(CONTROLS).count(), MAX)
            for i in range(n):
                loc = pg.locator(CONTROLS).nth(i)
                try:
                    if not loc.is_visible() or not loc.is_enabled(): continue
                    label = (loc.get_attribute("aria-label") or loc.inner_text(timeout=500) or loc.get_attribute("title") or "").strip().replace("\n", " ")[:60]
                except Exception: continue
                if SKIP.search(label): skipped.append(label); continue
                last[0] = label
                pg.evaluate(PROBE); before = pg.evaluate(SNAP); r0, d0 = reqs[0], dialogs[0]
                aria0 = loc.evaluate("e => [e.getAttribute('aria-expanded'), e.getAttribute('aria-pressed'), e.checked, e.parentElement && e.parentElement.open]")
                e0 = None
                try: loc.click(timeout=3000)
                except Exception as e0_:
                    e0 = e0_
                    # nth() locators go stale when a list re-renders; retry once by label before calling it dead
                    try:
                        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                        alt = pg.get_by_role("button", name=label, exact=True) if label else loc
                        vis = [alt.nth(k) for k in range(min(alt.count(), 20)) if alt.nth(k).is_visible()]
                        (vis[0] if vis else loc).click(timeout=3000); e0 = None
                    except Exception as e1: e0 = e1
                if e0 is not None:
                    e = e0; dead.append(f"{label or '(unlabelled)'}: not clickable ({' | '.join(l.strip() for l in str(e).splitlines() if 'intercept' in l or 'not stable' in l or 'outside' in l)[:200]})"); continue
                clicked += 1; pg.wait_for_timeout(450)
                try:
                    after = pg.evaluate(SNAP); mut = pg.evaluate("() => window.__mut || 0")
                except Exception: after, mut = [None, None], 1  # navigated
                try: aria1 = loc.evaluate("e => [e.getAttribute('aria-expanded'), e.getAttribute('aria-pressed'), e.checked, e.parentElement && e.parentElement.open]", timeout=500)
                except Exception: aria1 = None
                if not mut and reqs[0] == r0 and dialogs[0] == d0 and after == before and aria1 == aria0:
                    dead.append(label or "(unlabelled)")
                if after[1] and after[1] != before[1]:
                    pg.goto(BASE + r, wait_until="load"); pg.wait_for_timeout(1200)
                else:
                    pg.keyboard.press("Escape")
                for overlay in (".ux-palette-scrim",):
                    if pg.locator(overlay).count(): pg.keyboard.press("Escape")
            report.setdefault(r, {})[vname] = {"clicked": clicked, "console": errs, "bad": bad, "dead": dead, "skipped": skipped}
            if errs or bad or dead: failures.append(f"{r} [{vname}]")
            print(r, vname, "clicked", clicked, "errs", len(errs), "bad", len(bad), "dead", len(dead), flush=True)
            pg.close()
        ctx.close()
    b.close()
json.dump(report, open(f"{OUT}/interact.json", "w"), indent=1)
print("INTERACT_FAILURES", len(failures), failures)
sys.exit(1 if failures else 0)
