#!/usr/bin/env python
"""ATLAS ML refresh (paper only): incremental backfill, rolling retrain, registry, drift, shadow predictions.

  PYTHONPATH=src python scripts/ml_refresh.py [--backfill] [--no-shadow] [--as-of EPOCH]

Writes var/ml/registry/<version>/, var/ml/last_refresh.json and appends shadow observations to
var/shadow/ml_meta_shadow.jsonl. Never places or proposes orders.
"""
import argparse
import json
import sys

from atlas.feeds import get_feed
from atlas.ml.refresh import refresh
from atlas.models.shadow import ShadowCollector


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="incremental fetch from providers before training")
    ap.add_argument("--no-shadow", action="store_true")
    ap.add_argument("--as-of", type=int, default=None)
    ap.add_argument("--registry", default=None)
    ap.add_argument("--report", default="var/ml/last_refresh.json")
    a = ap.parse_args(argv)
    shadow = None if a.no_shadow else ShadowCollector("var/shadow/ml_meta_shadow.jsonl")
    rep = refresh(get_feed(), registry_root=a.registry, backfill=a.backfill, shadow=shadow, as_of=a.as_of, report_path=a.report)
    for k, g in rep["groups"].items():
        failed = [x["gate"] for x in g.get("gates", []) if not x["passed"]]
        print(f"{k:12s} {g.get('status'):13s} {g.get('version', '')} drift={g.get('drift_status')} failed={failed} shadow={g.get('shadow')}")
    print(json.dumps({"n_rows": rep["n_rows"], "n_open": rep["n_open"], "elapsed_s": rep["elapsed_s"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
