"""Smoke-train the t227u nowcast workers on REAL stored bars (no retrain --run, tiny models). Writes only var/ml/nowcast_xgb/."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from atlas.feeds.store import FeedStore
from atlas.ai.ml import nowcast_xgb as N
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/feeds/atlas_feed.sqlite")
    ap.add_argument("--groups", default="stocks_15m,stocks_1m,fx_1d")
    ap.add_argument("--targets", default=",".join(N.PRIORITY_STOCKS))
    ap.add_argument("--days", type=int, default=720)
    a = ap.parse_args()
    now = int(time.time())
    start = now - a.days * 86400
    feed = FeedStore(a.db)
    out = {}
    for g in a.groups.split(","):
        t0 = time.time()
        if N.GROUPS[g]["kind"] == "stock":
            frames = [N.stock_samples(feed, t, g, start, now) for t in a.targets.split(",")]
            df = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
        else:
            df = N.fx_samples(feed, g, start, now)
        rep = N.train_group(g, df)
        rep.pop("_model", None), rep.pop("_base", None)
        rep["seconds"] = round(time.time() - t0, 1)
        out[g] = rep
        print(json.dumps({k: v for k, v in rep.items() if k != "features"}, indent=1, default=str))
    rd = N.ROOT / "reports"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / f"smoke_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
