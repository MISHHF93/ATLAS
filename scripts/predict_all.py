"""evo-16: score every catalog asset that has a model and bars, log it, and print the coverage table (read-only; no orders).
    python scripts/predict_all.py [--sweep] [--intervals 1d,1h,15m] [--json out.json]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="compute predictions first")
    ap.add_argument("--intervals", default="1m,15m,1h,1d")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    from atlas.ai.prediction import service as S
    from atlas.feeds.feed import get_feed
    feed = get_feed()
    if a.sweep:
        print("sweep:", S.sweep(feed, intervals=tuple(a.intervals.split(","))))
    rep = S.coverage(feed, fresh=True)
    print(f"{rep['n_assets']} assets; status: {rep['status_counts']}")
    print(f"{'asset':10} {'pool':7} {'status':20} {'last real':18} {'last pred':18} {'model':26} reason")
    for r in rep["assets"]:
        print(f"{r['instrument']:10} {r['pool']:7} {r['status']:20} {(r['last_real_toronto'] or '-'):18} {(r['last_prediction_toronto'] or '-'):18} "
              f"{(r['model_version'] or '-'):26} {r['reason'][:90]}")
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
