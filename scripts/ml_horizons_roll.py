#!/usr/bin/env python
"""evo-20: keep the 1m / 5m horizon bundles current on new real bars (rolling walk-forward; research only, execution_permission none).

  PYTHONPATH=src python scripts/ml_horizons_roll.py --once [--pools crypto] [--horizons 1m 5m] [--force]
  PYTHONPATH=src python scripts/ml_horizons_roll.py --loop --every 1800

A cycle trains a challenger on the newest real bars and promotes it only if it beats the incumbent on bars neither saw (see atlas.ai.prediction.roll).
Run it as a separate process: it never touches ingest and holds no keys."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

from atlas.ai.prediction import horizons as HZ, roll as RL
from atlas.ai.prediction.pools import pool_for_symbol
from atlas.feeds import get_feed


def cycle(a) -> list[dict]:
    from atlas.ai.ml.dataset import load_series
    feed = get_feed()
    events = extra = None
    try:
        from atlas.ext.keyless_context import economic_calendar
        from atlas.ai.ml.directional.context27 import training_events, build_context, stored_daily_symbols, fetch_vix_csv
        events = training_events(economic_calendar(days=60, lookback_days=800, fresh=True))
        extra = build_context({s: load_series(feed, s, "1d").bars for s in stored_daily_symbols(feed)}, fetch_vix_csv())
    except Exception as exc:  # noqa: BLE001
        print(f"context unavailable ({type(exc).__name__}); event / breadth / implied-vol columns stay NaN", flush=True)
    from atlas.ai.ml.directional import inventory as INV
    inv = INV.inventory(feed)
    have = defaultdict(set)
    for ins, iv in INV.universe(inv):
        have[iv].add(ins)
    out = []
    for h in a.horizons:
        iv = HZ.HORIZONS[h][0]
        src = have.get("1m", set()) if iv == "5m" else have.get(iv, set())
        by_pool = defaultdict(list)
        for ins in sorted(src):
            by_pool[pool_for_symbol(ins)].append(ins)
        for pool, syms in sorted(by_pool.items()):
            if a.pools and pool not in a.pools:
                continue
            t0 = time.monotonic()
            rows, used = RL.build_rows(feed, pool, h, a.max_bars, lambda s, i: load_series(feed, s, i).bars, events, extra, syms)
            if rows is None:
                out.append({"pool": pool, "horizon": h, "decision": "skip", "reason": "no usable instruments"})
                continue
            r = RL.retrain_cell(pool, h, rows, used, force=a.force)
            r["seconds"] = round(time.monotonic() - t0)
            print(json.dumps({k: r.get(k) for k in ("pool", "horizon", "decision", "reason", "compare", "seconds")}), flush=True)
            out.append(r)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--every", type=int, default=1800)
    ap.add_argument("--horizons", nargs="*", default=["1m", "5m"])
    ap.add_argument("--pools", nargs="*", default=["crypto"])
    ap.add_argument("--max-bars", type=int, default=20000)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if not (a.once or a.loop):
        ap.print_help()
        return 0
    while True:
        try:
            cycle(a)
        except Exception as exc:  # noqa: BLE001
            print(f"cycle failed: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        if not a.loop:
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
