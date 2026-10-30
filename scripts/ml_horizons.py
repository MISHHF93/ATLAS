#!/usr/bin/env python
"""evo-17 multi-horizon research ensemble trainer (paper only, research display, execution_permission none).

  PYTHONPATH=src python scripts/ml_horizons.py --run [--horizons 1m 5m 15m 60m 1d] [--pools crypto equity ...] [--max-bars 20000] [--root var/ml/horizons]

Per (pool, horizon): pools every stored instrument's bars at that horizon's interval (5m is derived from real 1m bars), builds the same layer feature
columns as the directional model (each layer is NaN where its inputs are not available - coverage is written into the manifest), and fits LightGBM and
XGBoost (only if installed) 3-quantile boosters with a split-conformal CQR band, plus the no-change baseline. Prophet is not fitted (not installed here).
Keyed FRED release dates never enter training. Reports hold-out metrics only; the live ledger decides the weights."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

import pandas as pd

from atlas.ai.prediction import horizons as HZ
from atlas.ai.prediction.pools import pool_for_symbol
from atlas.feeds import get_feed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--horizons", nargs="*", default=list(HZ.HORIZONS))
    ap.add_argument("--pools", nargs="*", default=None)
    ap.add_argument("--max-bars", type=int, default=20000, help="newest bars kept per instrument (bounds training time)")
    ap.add_argument("--root", default=None)
    a = ap.parse_args(argv)
    print("models:", json.dumps(HZ.available_models()))
    if not a.run:
        return 0
    from atlas.ai.ml.dataset import load_series
    feed = get_feed()
    events = extra = None
    try:
        from atlas.ext.keyless_context import economic_calendar
        from atlas.ai.ml.directional.context27 import training_events, build_context, stored_daily_symbols, fetch_vix_csv
        events = training_events(economic_calendar(days=60, lookback_days=800, fresh=True))
        extra = build_context({s: load_series(feed, s, "1d").bars for s in stored_daily_symbols(feed)}, fetch_vix_csv())
    except Exception as exc:  # noqa: BLE001
        print(f"context unavailable ({type(exc).__name__}); event / breadth / implied-vol columns stay NaN")

    def refs(sym, iv):
        return load_series(feed, sym, iv).bars

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
        for pool, ins_list in sorted(by_pool.items()):
            if a.pools and pool not in a.pools:
                continue
            t0, frames, used = time.monotonic(), [], []
            for ins in ins_list:
                try:
                    bars = HZ.load_bars(feed, ins, iv)[-a.max_bars:]
                    f = HZ.make_xy(bars, iv, pool, ins, refs, events, extra)
                except Exception as exc:  # noqa: BLE001
                    print(f"  skip {ins} {iv}: {type(exc).__name__}: {str(exc)[:80]}")
                    continue
                if f is not None and len(f):
                    frames.append(f)
                    used.append(ins)
            if not frames:
                print(f"{pool:8s} {h:4s} no usable instruments ({len(ins_list)} candidates)")
                out.append({"pool": pool, "horizon": h, "status": "no_usable_instruments"})
                continue
            res = HZ.train_pool(pd.concat(frames, ignore_index=True), pool, h, root=a.root, instruments=used)
            m = res.get("metrics_oos") or {}
            print(f"{pool:8s} {h:4s} {res.get('status'):18s} rows={res.get('n_rows', res.get('rows'))} inst={len(used)} "
                  + " ".join(f"{k}:pin={v.get('pinball_bps')},cov={v.get('coverage_80')}" for k, v in m.items() if v.get("status") == "ok")
                  + f" layers={res.get('layers_with_any_data')}/{res.get('layers_total')} {time.monotonic() - t0:.0f}s")
            out.append({k: res.get(k) for k in ("pool", "horizon", "status", "n_rows", "n_test", "metrics_oos", "layers_with_any_data", "layers_total")})
    print(json.dumps({"trained": sum(1 for r in out if r.get("status") == "ok"), "cells": len(out), "execution_permission": "none"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
