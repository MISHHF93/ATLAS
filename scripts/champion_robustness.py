"""evo8: block-bootstrap CIs + symbol/time stability for an evolution run's best genome. Writes docs/research JSON/MD.
  PYTHONPATH=src ATLAS_FEED_DB=... ATLAS_ML_REGISTRY=... python scripts/champion_robustness.py --run 432dba69a77e --universe evo7_1h
Runs twice: on the run's exact rows (reproduction) and on all rows now in the feed (same genome, fresh folds)."""
import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--universe", choices=("evo6", "evo7", "evo7_1h"), required=True)
    ap.add_argument("--out", default="docs/research/evo8-champion-robustness.json")
    a = ap.parse_args()
    from atlas.feeds.feed import get_feed
    from atlas.ml import evolution as E
    from atlas.research import champion_robustness as R
    run = json.loads((E.evo_dir() / f"run_{a.run}.json").read_text())
    g = (run.get("best_beating_baseline") or run["best"])
    uni = {"evo6": E.UNIVERSE_EVO6, "evo7": E.UNIVERSE_EVO7, "evo7_1h": E.UNIVERSE_EVO7_1H}[a.universe]
    full, meta = E.build_population_data(get_feed(), uni, variant=E.EVO6_VARIANT, detectors=E.EVO6_DETECTORS)
    t_max = max(f["test_to"] for f in run["folds"])
    same = full[full.t <= t_max].reset_index(drop=True)
    out = {"run_id": a.run, "genome_id": g["genome_id"], "execution_permission": "none", "promoted_to_execution": False,
           "history_note": "feed history: BTC/ETH 1h from 2024-10-23; 28 alts only from 2026-04-27 (15m-derived). No older alt bars are stored.",
           "series": meta["series"]}
    for name, d in (("run_rows", same), ("all_rows_now", full)):
        oos = R.oos_trades(d, g["genome"])
        out[name] = {"n_rows": int(len(d)), "data_hash": E.data_hash(d), **R.report(oos)}
    Path(a.out).write_text(json.dumps(out, indent=1, default=str))
    rr = out["run_rows"]
    print(json.dumps({k: rr[k] for k in ("n_opps", "n_taken", "ci_mean_r_taken", "ci_ev_r_per_opportunity", "ci_mean_r_taken_excl_last_fold")}
                     | {"stab": {k: rr["stability"][k] for k in ("symbols_with_trades", "symbols_positive_mean_r", "months_with_trades",
                                                                 "months_positive_ev", "share_taken_r_from_last_fold", "by_group", "by_half")},
                        "now_rows": out["all_rows_now"]["n_rows"], "now_ci_ev": out["all_rows_now"]["ci_ev_r_per_opportunity"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
