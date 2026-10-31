#!/usr/bin/env python
"""Coinbase and Kraken public OHLCV backfill, then the existing meta-label refresh.

Run this on a machine with network and the feed store. It is not part of CI and this
repository run does not execute ``--run``.

  PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py
  PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --backfill
  PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --run

``--run`` calls ``atlas.ai.ml.refresh.refresh`` on BTCUSDT, ETHUSDT, and SOLUSDT at
15m, 1h, and 1d. Bars come from the public Coinbase and Kraken adapters already in
the feed (no key). Gates are ``train.GATES``, unchanged. ``shadow_weeks`` is the count
of resolved weeks in ``var/shadow/ml_meta_shadow.jsonl``. A passing shadow gate does
not skip the others, and nothing here sets execution permission or places an order.
"""
from __future__ import annotations

import argparse
import json
import sys

from atlas.ai.ml.train import GATES

CRYPTO_UNIVERSE = [(i, iv) for i in ("BTCUSDT", "ETHUSDT", "SOLUSDT") for iv in ("15m", "1h", "1d")]
SHADOW_PATH = "var/shadow/ml_meta_shadow.jsonl"


def plan() -> dict:
    return {
        "universe": [{"instrument": i, "interval": iv} for i, iv in CRYPTO_UNIVERSE],
        "providers": ["coinbase", "kraken"],
        "keys": "none (public OHLCV)",
        "gates": dict(GATES),
        "shadow_path": SHADOW_PATH,
        "commands": {
            "plan": "PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py",
            "backfill_only": "PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --backfill",
            "backfill_and_retrain": "PYTHONPATH=src python scripts/ml_public_ohlcv_retrain.py --run",
        },
        "will_train": False,
        "execution_permission": "none",
        "note": "Eligible still cannot place an order. Do not run --run in CI.",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="fetch public bars only; do not train")
    ap.add_argument("--run", action="store_true", help="backfill and retrain; heavy; not for CI")
    ap.add_argument("--report", default="var/ml/last_refresh.json")
    a = ap.parse_args(argv)
    if not a.backfill and not a.run:
        print(json.dumps(plan(), indent=1))
        return 0
    from atlas.ai.ml.refresh import incremental_backfill, refresh
    from atlas.ai.models.shadow import ShadowCollector
    from atlas.feeds import get_feed
    feed = get_feed()
    if not a.run:
        fetched = incremental_backfill(feed, CRYPTO_UNIVERSE)
        print(json.dumps({"backfill": fetched, "trained": False, "execution_permission": "none"}, default=str))
        return 0
    shadow = ShadowCollector(SHADOW_PATH)
    rep = refresh(feed, universe=CRYPTO_UNIVERSE, backfill=True, shadow=shadow, report_path=a.report)
    brief = {k: {"status": g.get("status"), "version": g.get("version"), "failed": [x["gate"] for x in g.get("gates", []) if not x.get("passed")]}
             for k, g in rep.get("groups", {}).items()}
    print(json.dumps({"shadow_weeks": rep.get("shadow_weeks"), "groups": brief, "elapsed_s": rep.get("elapsed_s"),
                      "execution_permission": "none"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
