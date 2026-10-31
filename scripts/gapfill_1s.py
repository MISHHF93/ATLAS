"""Calibrate and run the predicted 1s gap fill on the real 1s store (read-only on atlas_1s.sqlite; writes pred_1s only)."""
from __future__ import annotations
import json, sys, time
sys.path.insert(0, "src")
from atlas.feeds.trades1s import TradeBarStore
from atlas.ai.ml import gapfill1s as G


def main() -> int:
    now = int(time.time())
    ts = TradeBarStore("var/feeds/atlas_1s.sqlite")
    ps = G.PredStore("var/ml/nowcast_xgb/pred_1s.sqlite")
    rep = {}
    for cov in ts.coverage():
        v = cov["venue"]
        cal = G.calibrate_venue(ts, v, cov["first"], cov["last"] + 1)
        ps.save_calib(v, cal, now)
        n_pred = 0
        for ins in sorted(r[0] for r in G._ids(ts, v, cov["first"], cov["last"] + 1)):
            n_pred += len(G.fill(ts, ps, v, ins, cov["first"], cov["last"] + 1, now))
        rep[v] = {"calib": cal, "predicted_rows": n_pred, "real_rows": cov["rows"]}
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
