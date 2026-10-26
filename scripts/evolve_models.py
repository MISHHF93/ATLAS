"""On-demand governed model evolution. Usage:
  PYTHONPATH=src ATLAS_FEED_DB=... python scripts/evolve_models.py [--generations 3] [--seed 11]
Writes leaderboard/lineage/champion under the ML registry (var/ml/registry/evolution; never committed).
Research only: execution_permission none; nothing is promoted to execution."""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--universe", choices=("default", "extended", "evo6", "evo7", "evo7_1h", "evo9_4h", "evo9_1h", "evo9_multi"), default="default")
    ap.add_argument("--variant", default=None)
    a = ap.parse_args()
    from atlas.feeds.feed import get_feed
    from atlas.ml import evolution as E
    uni_map = {
        "evo6": E.UNIVERSE_EVO6,
        "evo7": E.UNIVERSE_EVO7,
        "evo7_1h": E.UNIVERSE_EVO7_1H,
        "evo9_4h": E.UNIVERSE_EVO9_4H,
        "evo9_1h": E.UNIVERSE_EVO9_1H,
        "evo9_multi": E.UNIVERSE_EVO9_MULTI,
    }
    if a.universe in uni_map:
        vid = a.variant or (E.EVO9_VARIANT if a.universe.startswith("evo9") else E.EVO6_VARIANT)
        data, meta = E.build_population_data(get_feed(), uni_map[a.universe], variant=vid, detectors=E.EVO6_DETECTORS)
    else:
        data, meta = E.build_population_data(get_feed(), E.UNIVERSE_EXTENDED if a.universe == "extended" else E.UNIVERSE, variant=a.variant)
    if not len(data):
        print(json.dumps({"status": "no_data", "meta": meta}))
        return 1
    res = E.evolve(data, meta, generations=a.generations, seed=a.seed, log=lambda s: print(s, file=sys.stderr))
    best = res["best_passing_strict_gate"] or res["best_beating_baseline"] or res["best"]
    oos = E.oos_predictions(data, best["genome"]) if best else None
    run = E.record(res, oos=oos)
    print(json.dumps({"run_id": run["run_id"], "decision": run["decision"], "no_model_beats_baseline": run["no_model_beats_baseline"],
                      "no_model_passes_strict_gate": run["no_model_passes_strict_gate"], "variant": meta.get("variant"),
                      "n_rows": meta.get("n_rows"), "universe": a.universe, "macro_coverage": meta.get("macro_coverage"), "by_bar_type": run["by_bar_type"],
                      "top5": [(v["genome_id"], v["metrics"].get("fitness"), v["metrics"].get("ev_r_per_opportunity"),
                                v["metrics"].get("brier_skill"), v["metrics"].get("take_all_ev")) for v in run["leaderboard"][:5]]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
