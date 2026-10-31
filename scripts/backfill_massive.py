"""Backfill stock/ETF bars from Massive (Stocks Basic) into var/feeds/atlas_feed.sqlite (never committed).

    PYTHONPATH=src python scripts/backfill_massive.py                       # priority tickers, then the whole stock/ETF catalog
    PYTHONPATH=src python scripts/backfill_massive.py --instruments AAPL,SPY --phases A
    PYTHONPATH=src python scripts/backfill_massive.py --plan                # list the jobs, make no call

Phases: A = priority tickers (1d + 15m), B = the rest, daily, C = the rest, 15m, D = 1m regular-session bars
(last ATLAS_STOCK_1M_DAYS completed days, default 60; priority tickers unless ATLAS_STOCK_1M=all). Re-runnable: only the missing tail is fetched.
Needs MASSIVE_API_KEY or POLYGON_API_KEY in the environment / .env. Throttled to 4 calls/min for the whole machine.
Personal, non-commercial use only on the Basic plan.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="", help="comma list; default = every stock/ETF in the UI universe")
    ap.add_argument("--phases", default="ABCD")
    ap.add_argument("--days", type=int)
    ap.add_argument("--db")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--no-1h", action="store_true")
    a = ap.parse_args(argv)
    _load_dotenv()
    from atlas.feeds import get_feed
    from atlas.feeds import massive_backfill as MB
    from atlas.feeds.universe import ETFS, STOCKS
    feed = get_feed(a.db)
    ids = [s.strip().upper() for s in a.instruments.split(",") if s.strip()] or (sorted(ETFS) + list(STOCKS))
    if a.plan:
        js = MB.jobs(feed, ids, a.phases)
        print(json.dumps({"jobs": len(js), "approx_minutes": round(len(js) / 4, 1), "first": js[:6]}))
        return 0
    prov = feed.registry.get(MB.PROVIDER)
    if not (prov and prov.enabled):
        print("polygon/massive is not enabled: set MASSIVE_API_KEY (or POLYGON_API_KEY) in .env", file=sys.stderr)
        return 2
    MB.run(feed, ids, a.phases, days=a.days, emit=lambda r: print(json.dumps(r, default=str), flush=True), make_1h=not a.no_1h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
