#!/usr/bin/env python
"""evo-14 directional research pipeline (paper only, research display, execution_permission none).

  PYTHONPATH=src python scripts/ml_directional.py --inventory
  PYTHONPATH=src python scripts/ml_directional.py --run [--intervals 15m 1h 1d] [--no-persist]

Trains on every (instrument, interval) that has stored bars, pooled by asset group and interval, under the strict gate set.
Writes var/ml/directional/report.json and, per group, model.pkl + manifest.json. Reports out-of-sample metrics only.
"""
import argparse
import json
import sys
from pathlib import Path

from atlas.ai.ml.directional import inventory as INV
from atlas.ai.ml.directional import pipeline as P
from atlas.feeds import get_feed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--intervals", nargs="*", default=None)
    ap.add_argument("--root", default="var/ml/directional")
    ap.add_argument("--no-persist", action="store_true")
    a = ap.parse_args(argv)
    feed = get_feed()
    inv = INV.inventory(feed)
    Path(a.root).mkdir(parents=True, exist_ok=True)
    Path(a.root, "inventory.json").write_text(json.dumps(inv, indent=2, default=str))
    print(f"inventory: {inv['n_series_rows']} series rows, {inv['n_instruments']} instruments, {inv['n_usable']} usable (>= {P.CONFIG['min_bars']} bars); by interval {inv['by_interval']}")
    for g, ins in inv["by_group"].items():
        print(f"  {g}: {len(ins)} instruments")
    if inv["too_short"]:
        print(f"  skipped (too short): {len(inv['too_short'])} series")
    if not a.run:
        return 0
    uni = [u for u in INV.universe(inv) if not a.intervals or u[1] in a.intervals]
    events, note = None, "events: not fetched"
    try:   # official release schedules (BLS / Treasury; FRED only if its key is set): scheduled in advance, so point-in-time safe
        from atlas.ext.keyless_context import economic_calendar
        cal = economic_calendar(days=60, lookback_days=800, fresh=True)
        events = [e["ts"] for e in cal["events"]]
        note = f"{len(events)} scheduled releases from {', '.join(s['id'] for s in cal['sources'] if s.get('status') == 'ok') or 'no source'}"
    except Exception as exc:  # noqa: BLE001
        note = f"event calendar unavailable ({type(exc).__name__}); ev_* features are NaN"
    print(note)
    news_in: dict = {}
    try:   # point-in-time news features from the local store (only for SEC-registered equities; everything else stays NaN)
        from atlas.news.features import news_input, ticker_of
        news_in = {i: ni for i, _ in uni if (ni := news_input(ticker_of(i))) is not None}
    except Exception as exc:  # noqa: BLE001
        print(f"news store unavailable ({type(exc).__name__}); nw_* features are NaN")
    print(f"news features: {len(news_in)} instruments have collected sources; the rest are NaN (honest coverage)")
    res = P.run(feed, uni, registry_root=None if a.no_persist else a.root, events=events, events_note=note, news=news_in)
    Path(a.root, "report.json").write_text(json.dumps(res, indent=2, default=float))
    for k, g in sorted(res["groups"].items()):
        pr = (g.get("prob") or {}).get("hgb") or {}
        fails = [x["gate"] for x in g.get("gates", []) if not x["passed"]]
        print(f"{k:14s} {g.get('label'):26s} n_oos={g.get('n_oos')} auc={pr.get('auc')} brier_skill={pr.get('brier_skill')} failed={fails}")
    print(json.dumps({"groups": len(res["groups"]), "skipped": len(res["skipped"]), "n_trials": res.get("n_trials"), "elapsed_s": res["elapsed_s"], "execution_permission": "none"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
