"""Run the horizon screen on real stored 15m/1h bars and write var/ml/horizon_tuning/report.json (no training artifacts kept)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, "src")
import pandas as pd
from atlas.feeds.store import FeedStore
from atlas.ai.ml import multires as M, horizon_tune as H
from atlas.ai.ml.costs import VENUE_COSTS

CLASSES = {
    "crypto": {"provider": "coinbase", "symbols": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"), "stock": False, "cost": VENUE_COSTS["crypto_spot"]["cost_bps"], "hs": M.CANDIDATE_HORIZON_BARS},
    "us_equity": {"provider": "polygon", "symbols": ("SPY", "QQQ", "AAPL", "NVDA", "MSFT"), "stock": True, "cost": VENUE_COSTS["us_equity"]["cost_bps"], "hs": (1, 2, 4, 8, 16)},
}


def main() -> int:
    now = int(time.time())
    start = now - 730 * 86400
    fs = FeedStore("var/feeds/atlas_feed.sqlite")
    report = {"schema": M.FEATURE_SCHEMA, "generated_at": now, "note": "feasibility screen on signal and cost; not a P&L backtest", "classes": {}}
    for name, c in CLASSES.items():
        frames = []
        for s in c["symbols"]:
            inp = M.load_inputs(fs, s, provider=c["provider"], start=start, end=now, intervals=("15m", "1h"))
            f = H.class_frame(s, inp, start, now, c["hs"], c["stock"])
            if len(f):
                frames.append(f)
        df = pd.concat(frames) if frames else pd.DataFrame()
        res = H.tune_class(df, c["hs"], c["cost"]) if len(df) else []
        report["classes"][name] = {"symbols": list(c["symbols"]), "rows": int(len(df)), "results": res,
                                   "kept_horizon_bars": [r["h_bars"] for r in res if r["kept"]]}
        print(name, len(df))
        for r in res:
            print(" ", r["horizon_min"], "min  n_test", r["n_test"], " IC", round(r["ic"], 4), [round(x, 4) for x in r["ic_ci95"]], " >cost", round(r.get("move_gt_cost_share", float("nan")), 3), " kept", r["kept"], r["reason"])
    d = Path("var/ml/horizon_tuning"); d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
