"""Standalone Massive live poller for US stocks (a separate process; it never touches the crypto ingest service).

    PYTHONPATH=src python scripts/run_massive_live.py --once       # one refresh, then exit
    PYTHONPATH=src python scripts/run_massive_live.py              # loop

Free plan (Stocks Basic): an end-of-day refresh (previous completed ET session; zero API calls while up to date; throttled to 4/min machine-wide).
Paid plan (ATLAS_POLYGON_PLAN=paid): also polls the snapshot every 30 s. See src/atlas/feeds/massive_live.py. Paper only; no orders; no keys are set or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _load_dotenv(path=".env"):
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--db")
    a = ap.parse_args(argv)
    _load_dotenv()
    from atlas.feeds import massive_live as ML
    from atlas.feeds.feed import AtlasFeed
    from atlas.feeds.store import FeedStore
    feed = AtlasFeed(FeedStore(a.db or "var/feeds/atlas_feed.sqlite"))
    while True:
        env = dict(os.environ)
        if not ML.has_key(env):
            print(json.dumps({"status": "no key", "capability": ML.capability(env)["label"]}), flush=True)
            return 2
        ids = ML.stock_instruments(feed)
        if ML.is_paid(env):
            print(json.dumps({"snapshot": ML.poll_snapshot(feed, env, ids)}), flush=True)
        rows = ML.refresh(feed, env, ids)
        print(json.dumps({"capability": ML.capability(env)["label"], "refreshed": sum(1 for r in rows if r["status"] == "ok"),
                          "up_to_date": sum(1 for r in rows if r["status"] == "up_to_date"), "calls": sum(r.get("calls", 0) for r in rows)}), flush=True)
        if a.once:
            return 0
        time.sleep(ML.REFRESH_EVERY_S if not ML.is_paid(env) else ML.SNAPSHOT_EVERY_S)


if __name__ == "__main__":
    sys.exit(main())
