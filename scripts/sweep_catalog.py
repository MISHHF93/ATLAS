"""Sweep every catalog asset across every chart timeframe against a running ATLAS server (read-only).

For each (asset, interval) it asks exactly what the chart asks: /api/ai/chart/overlays (bars) and
/api/ai/predictions/nowcast (the labelled predicted line).  It writes one JSON line per cell and a
status table.  Status values:
  bars        real bars are stored and the chart draws candles
  predicted   no bars, the chart draws the labelled predicted line with a banner
  labelled    no bars and no forecast is possible; the API names the cause and the chart shows that plainly (placeholder id, policy-blocked
              source ...).  Honest unavailable: not an error, not a blank
  blank       no bars, no predicted line and no stated cause: this is a defect
  error       HTTP / transport failure: this is a defect
Paper only, read-only.  Usage: python scripts/sweep_catalog.py [--base URL] [--out FILE] [--workers N] [--limit N] [--intervals 1m,5m,...]
"""
from __future__ import annotations

import argparse, json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict

INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]


def chart_symbol(s: str) -> str:
    """Mirror of frontend chartSymbol()."""
    u = s.upper()
    if u.endswith("-USD"):
        return u[:-4] + "USDT"
    if ":" in u and u.split(":", 1)[0].isalpha():
        return u.split(":", 1)[1]
    return u


def get(base: str, path: str, timeout: int = 90):
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"_err": f"{type(e).__name__}: {e}"[:160]}


def catalog(base: str, limit: int | None = None):
    out, off = [], 0
    while True:
        st, j = get(base, f"/api/catalog/search?limit=250&offset={off}")
        if st != 200 or not j or not j.get("results"):
            break
        out.extend(j["results"])
        off += len(j["results"])
        if off >= j.get("total_matching", 0) or (limit and off >= limit):
            break
    return out[:limit] if limit else out


def classify(base: str, symbol: str, interval: str) -> dict:
    sym = chart_symbol(symbol)
    q = urllib.parse.urlencode({"symbol": sym, "interval": interval, "bar_type": "time", "limit": 600})
    so, o = get(base, f"/api/ai/chart/overlays?{q}")
    q2 = urllib.parse.urlencode({"symbol": sym, "interval": interval})
    sn, n = get(base, f"/api/ai/predictions/nowcast?{q2}")
    nbars = len(o.get("bars") or []) if isinstance(o, dict) else 0
    ncst = (n or {}).get("status") if isinstance(n, dict) else None
    npath = len((n or {}).get("path") or []) if isinstance(n, dict) else 0
    row = {"asset": symbol, "chart_symbol": sym, "interval": interval, "overlay_http": so, "bars": nbars,
           "overlay_status": (o or {}).get("status") if isinstance(o, dict) else None,
           "nowcast_http": sn, "nowcast_status": ncst, "nowcast_mode": (n or {}).get("mode") if isinstance(n, dict) else None,
           "nowcast_path": npath, "reason": ((n or {}).get("reason") or "")[:140] if isinstance(n, dict) else ""}
    if so != 200 or sn != 200:
        row["status"] = "error"
        row["reason"] = row["reason"] or f"overlay HTTP {so}, nowcast HTTP {sn}"
    elif nbars > 0:
        row["status"] = "bars"
    elif ncst == "ok" and npath > 0:
        row["status"] = "predicted"
    elif isinstance(o, dict) and o.get("cause") and (o.get("reason") or "").strip():
        row["status"] = "labelled"
        row["cause"] = o["cause"]
        row["reason"] = o["reason"][:160]
    else:
        row["status"] = "blank"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    ap.add_argument("--out", default="sweep.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--every", type=int, default=1, help="take every Nth asset (stratified sample)")
    ap.add_argument("--real-only", action="store_true", help="skip 'Directory Placeholder' rows (EQ####/PERP### ids that name no real listing)")
    ap.add_argument("--intervals", default=",".join(INTERVALS))
    a = ap.parse_args()
    ivs = a.intervals.split(",")
    assets = catalog(a.base, a.limit)
    if a.real_only:
        assets = [x for x in assets if x.get("asset_category") != "placeholder"]
    assets = assets[:: a.every]
    print(f"catalog assets: {len(assets)}", flush=True)
    cls = {x["symbol"]: x.get("asset_class") for x in assets}
    cells = [(x["symbol"], iv) for x in assets for iv in ivs]
    t0 = time.time()
    done = 0
    rows = []
    with open(a.out, "w", encoding="utf-8") as fh, ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(classify, a.base, s, iv) for s, iv in cells]
        for f in as_completed(futs):
            r = f.result()
            r["asset_class"] = cls.get(r["asset"])
            rows.append(r)
            fh.write(json.dumps(r) + "\n")
            done += 1
            if done % 200 == 0:
                print(f"{done}/{len(cells)} {int(time.time() - t0)}s", flush=True)
    tab = defaultdict(Counter)
    for r in rows:
        tab[(r["asset_class"], r["interval"])][r["status"]] += 1
    print("class,interval,bars,predicted,labelled,blank,error")
    for (c, iv), cn in sorted(tab.items(), key=lambda kv: (str(kv[0][0]), INTERVALS.index(kv[0][1]) if kv[0][1] in INTERVALS else 9)):
        print(f"{c},{iv},{cn['bars']},{cn['predicted']},{cn['labelled']},{cn['blank']},{cn['error']}")
    tot = Counter(r["status"] for r in rows)
    print("TOTAL", dict(tot), "cells", len(rows))
    return 0 if not (tot["blank"] or tot["error"]) else 1


if __name__ == "__main__":
    sys.exit(main())
