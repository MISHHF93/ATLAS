"""Smoke run of the 15m BUY/SELL/HOLD model on real stored bars (milestone d). Small by design; NOT the heavy retrain.

Per asset class and vertical barrier it trains the existing meta-labeler twice under purged walk-forward folds:
  base      = the existing causal bar features
  base+mr   = base + the multires layers that have real coverage for that group
and prints the gates (train.GATES, unchanged). Writes var/ml/signal15/smoke_<ts>.json and the pre-declared shadow model
(largest barrier, base+mr) to var/ml/signal15/models/. Nothing is registered, promoted or sized.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, "src")
import numpy as np, pandas as pd
from atlas.feeds.store import FeedStore
from atlas.ai.ml import multires as MR, signal15 as S, train as TR

CLASSES = {
    "crypto": {"provider": "coinbase", "symbols": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"), "ac": "crypto"},
    "equity": {"provider": "polygon", "symbols": ("SPY", "QQQ", "AAPL", "NVDA", "MSFT"), "ac": "equity"},
}


def compact(res: dict, key: str) -> dict:
    g = res["groups"].get(key)
    if not g or not g.get("n_oos"):
        return {"n_oos": 0}
    p = g["variants"][TR.PRIMARY]
    return {"n_rows": g["n_rows"], "n_oos": p["n_oos"], "brier_skill": p["brier_skill"], "logloss": p["logloss"], "logloss_baseline": p["logloss_baseline"],
            "ece": p["ece"], "auc": p["auc"], "n_taken": p["n_taken"], "mean_r_taken": p["mean_r_taken"], "mean_r_all": p["mean_r_all"],
            "hit_rate_taken": p["hit_rate_taken"], "dsr": (p.get("dsr") or {}).get("dsr"), "pbo": (g.get("pbo") or {}).get("pbo"),
            "gates": g["gates"], "per_detector": {d: {"n_oos": v["n_oos"], "n_taken": v["n_taken"], "mean_r_taken": v["mean_r_taken"], "brier_skill": v["brier_skill"]} for d, v in g.get("per_detector", {}).items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="var/feeds/atlas_feed.sqlite")
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    now = int(time.time()); start = now - a.days * 86400
    fs = FeedStore(a.db)
    report = {"schema": S.SCHEMA, "generated_at": now, "gates": TR.GATES, "classes": {}, "note": "smoke only; research evidence, not a profitability claim"}
    for name, c in CLASSES.items():
        out = {"provider": c["provider"], "symbols": list(c["symbols"]), "holds": {}}
        for hold in S.HOLD_BARS[c["ac"]]:
            frames, cover = [], {}
            for s in c["symbols"]:
                sd = S.load_sd(fs, s, "15m", c["provider"], c["ac"], start, now)
                inp = MR.load_inputs(fs, s, provider=c["provider"], start=start, end=now, intervals=("15m", "1h"))
                t0 = time.time()
                f = S.setup_frame(sd, inp, hold)
                cover[s] = {"bars_15m": len(sd.bars), "setups": int(len(f)), "secs": round(time.time() - t0, 1)}
                if len(f):
                    frames.append(f)
            if not frames:
                out["holds"][str(hold)] = {"error": "no setups"}
                continue
            data = pd.concat(frames, ignore_index=True).sort_values(["t", "instrument", "candidate_id"]).reset_index(drop=True)
            layers = S.usable_layers(data)
            feats_b, feats_m = S.BASE_FEATURES, S.model_features(layers)
            groups = [(c["ac"], "15m")]
            rb = S.walk_forward(data, feats_b, groups, a.folds)
            rm = S.walk_forward(data, feats_m, groups, a.folds)
            key = f"{c['ac']}-15m"
            rec = {"hold_bars": hold, "hold_hours": hold * 0.25, "rows": int(len(data)), "per_instrument": cover, "layers_used": layers,
                   "layer_coverage_all": MR.availability(data[list(MR.FEATURE_NAMES)]), "n_features_base": len(feats_b), "n_features_mr": len(feats_m),
                   "base_rate": float(data.y.mean()), "mean_r_all_setups": float(data.r.mean()),
                   "cost_bps_inside_label": float((data.cost_r * data.risk_bps).median()),
                   "base": compact(rb, key), "base_plus_multires": compact(rm, key)}
            out["holds"][str(hold)] = rec
            print(name, "hold", hold, "rows", len(data), "layers", list(layers))
            for lab in ("base", "base_plus_multires"):
                r = rec[lab]
                if r.get("n_oos"):
                    print(f"   {lab:19s} n_oos {r['n_oos']:6d} brier_skill {r['brier_skill']:+.4f} auc {r['auc']:.3f} ece {r['ece']:.3f} taken {r['n_taken']:5d} mean_R_taken {r['mean_r_taken']} dsr {r['dsr']} pbo {r['pbo']} failed {[g['gate'] for g in r['gates'] if not g['passed']]}")
                else:
                    print(f"   {lab:19s} no OOS rows")
            if hold == S.HOLD_BARS[c["ac"]][-1] and not a.no_save:
                mm = TR.fit_final(data, c["ac"], "15m", "hgb", feats_m)
                if mm is not None:
                    gates = rec["base_plus_multires"].get("gates", [])
                    S.save_model(Path("var/ml/signal15/models"), f"{name}_h{hold}", mm,
                                 {"asset_class": c["ac"], "provider": c["provider"], "hold_bars": hold, "layers": list(layers), "trained_through": int(data.t.max()),
                                  "n_rows": int(len(data)), "gates": gates, "status": S.status_from_gates(gates) if gates else "not_eligible", "symbols": list(c["symbols"]),
                                  "shadow_weeks": 0})
                    out["holds"][str(hold)]["shadow_model"] = f"{name}_h{hold}"
        report["classes"][name] = out
    d = Path("var/ml/signal15"); d.mkdir(parents=True, exist_ok=True)
    p = d / f"smoke_{time.strftime('%Y%m%d_%H%M%S')}.json"
    p.write_text(json.dumps(report, indent=1, default=str))
    print("report", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

