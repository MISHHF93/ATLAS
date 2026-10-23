"""Backfill the ATLAS feed store (var/feeds/atlas_feed.sqlite, never committed) from the provider chain, fill gaps,
cross-check against sanity providers, and print counts + freshness + quality flags.

    python scripts/backfill_feeds.py                      # default universe
    python scripts/backfill_feeds.py --instruments BTCUSDT --intervals 15m --days 30
    python scripts/backfill_feeds.py --health             # print health payload only
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from atlas.feeds import get_feed

DAYS = {"15m": {"crypto": 180, "etf": 59}, "1h": {"crypto": 730, "etf": 720}}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M") if t else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="BTCUSDT,ETHUSDT,SPY,QQQ,IWM")
    ap.add_argument("--intervals", default="15m,1h")
    ap.add_argument("--days", type=int)
    ap.add_argument("--db")
    ap.add_argument("--no-cross-check", action="store_true")
    ap.add_argument("--health", action="store_true")
    a = ap.parse_args()
    feed = get_feed(a.db)
    if a.health:
        print(json.dumps(feed.health(), indent=1, default=str)); return
    now = int(time.time())
    report = []
    for inst_id in a.instruments.split(","):
        inst = feed.instruments.get(inst_id)
        for iv in a.intervals.split(","):
            days = a.days or DAYS.get(iv, {}).get(inst.asset_class if inst.asset_class == "crypto" else "etf", 30)
            start = now - days * 86400
            r = feed.backfill(inst_id, iv, start, now)
            cc = {} if a.no_cross_check else feed.cross_check(inst_id, iv, max(start, now - 7 * 86400), now)
            bars = feed.bars(inst_id, iv, start, now + 1)
            q = feed.quality(inst_id, iv, int(time.time()))
            report.append({"instrument": inst_id, "interval": iv, "provider": r["provider"], "inserted": r.get("inserted"),
                           "revised": r.get("revised"), "failover_errors": r.get("errors"), "gap_fills": len(r["gap_fills"]),
                           "bars": len(bars), "first": iso(bars[0].event_time) if bars else None,
                           "last_closed_bar_end": iso(bars[-1].bar_end) if bars else None, "age_seconds": q.age_seconds,
                           "gaps_in_window": len(q.gaps), "flags": list(q.flags), "cross_check": cc})
            print(json.dumps(report[-1], default=str), flush=True)
    print("\n| instrument | tf | provider | bars | first (UTC) | last closed bar end (UTC) | age s | flags |")
    print("|---|---|---|---|---|---|---|---|")
    for x in report:
        print(f"| {x['instrument']} | {x['interval']} | {x['provider']} | {x['bars']} | {x['first']} | {x['last_closed_bar_end']} | {x['age_seconds']} | {','.join(x['flags']) or 'ok'} |")


if __name__ == "__main__":
    main()
