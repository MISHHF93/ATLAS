#!/usr/bin/env python
"""evo-20: keep the 1m / 5m horizon bundles current on new real bars (rolling walk-forward; research only, execution_permission none).

  PYTHONPATH=src python scripts/ml_horizons_roll.py --once [--pools crypto] [--horizons 1m 5m] [--force]
  PYTHONPATH=src python scripts/ml_horizons_roll.py --loop --every 1800

A cycle trains a challenger on the newest real bars and promotes it only if it beats the incumbent on bars neither saw (see atlas.ai.prediction.roll).
Run it as a separate process: it never touches ingest and holds no keys.

``--loop`` writes ``cycle_start`` to ``var/ml/horizons/roll.jsonl`` before training, heartbeats
``roll_status.json`` / ``roll_supervisor.json``, and kills the iteration after ``--timeout`` seconds
(default 4h; 0 waits with no cap). A killed iteration promotes nothing. On Windows the worker is the
base interpreter (``sys._base_executable``), not a second venv redirector. Starting this file itself
via ``Scripts\\python.exe`` still shows the redirector parent; that parent is the venv launcher, and
this process does not spawn another one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

from atlas.ai.prediction import horizons as HZ, roll as RL
from atlas.ai.prediction.pools import pool_for_symbol
from atlas.feeds import get_feed
from atlas.ops.procutil import subprocess_python


def cycle(a, hb: RL.Heartbeat | None = None) -> list[dict]:
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
            if hb is not None:
                hb.update(phase=f"{pool}-{h}", pool=pool, horizon=h)
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


def _once_argv(a) -> list[str]:
    cmd = ["--once", "--horizons", *a.horizons, "--max-bars", str(a.max_bars)]
    if a.pools:
        cmd += ["--pools", *a.pools]
    if a.force:
        cmd.append("--force")
    return cmd


def run_once(a) -> int:
    """In-process cycle with a heartbeat. Used by ``--once`` (including the supervised child)."""
    supervised = os.environ.get("ATLAS_ROLL_SUPERVISED") == "1"
    hb = RL.Heartbeat(interval=RL.HEARTBEAT_S)
    hb.start()
    if not supervised:
        RL.append_event({"event": "cycle_start", "at": time.time(), "pid": os.getpid(), "mode": "once"})
    try:
        cycle(a, hb)
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        print(f"cycle failed: {type(exc).__name__}: {exc}\n{tb[-2000:]}", flush=True)
        RL.append_event({"event": "cycle_error", "at": time.time(), "pid": os.getpid(),
                         "error": f"{type(exc).__name__}: {exc}", "traceback": tb[-2000:]})
        hb.stop(state="error", error=f"{type(exc).__name__}: {exc}")
        return 1
    hb.stop(state="idle", phase="done")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--every", type=int, default=1800)
    ap.add_argument("--timeout", type=float, default=RL.DEFAULT_ITERATION_TIMEOUT_S,
                    help="kill one loop iteration after this many seconds (0 = no cap; heartbeat still updates)")
    ap.add_argument("--horizons", nargs="*", default=["1m", "5m"])
    ap.add_argument("--pools", nargs="*", default=["crypto"])
    ap.add_argument("--max-bars", type=int, default=20000)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if not (a.once or a.loop):
        ap.print_help()
        return 0
    if not a.loop:
        return run_once(a)
    exe, env = subprocess_python()
    env = {**env, "ATLAS_ROLL_SUPERVISED": "1", "PYTHONUNBUFFERED": "1"}
    script = str(Path(__file__).resolve())
    iteration = 0
    while True:
        iteration += 1
        cmd = [exe, "-B", "-u", script, *_once_argv(a)]
        try:
            RL.supervise(cmd, timeout_s=a.timeout, env=env, iteration=iteration)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            print(f"supervisor failed: {type(exc).__name__}: {exc}\n{tb[-2000:]}", flush=True)
            RL.append_event({"event": "cycle_error", "at": time.time(), "iteration": iteration,
                             "error": f"{type(exc).__name__}: {exc}", "traceback": tb[-2000:]})
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
