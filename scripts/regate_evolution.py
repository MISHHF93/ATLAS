"""evo8: re-evaluate a stored evolution run under the strict champion gate (ml.evolution.strict_gate).
  PYTHONPATH=src ATLAS_FEED_DB=... ATLAS_ML_REGISTRY=... python scripts/regate_evolution.py --run 432dba69a77e --universe evo7_1h
Rebuilds the run's dataset from the feed (as of the run's last bar), refuses if the data hash differs, and demotes the
stored champion to research-only if it fails. Research only; never promotes."""
import argparse
import json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--universe", choices=("evo6", "evo7", "evo7_1h"), required=True)
    a = ap.parse_args()
    from atlas.feeds.feed import get_feed
    from atlas.ml import evolution as E
    run = json.loads((E.evo_dir() / f"run_{a.run}.json").read_text())
    uni = {"evo6": E.UNIVERSE_EVO6, "evo7": E.UNIVERSE_EVO7, "evo7_1h": E.UNIVERSE_EVO7_1H}[a.universe]
    data, meta = E.build_population_data(get_feed(), uni, variant=E.EVO6_VARIANT, detectors=E.EVO6_DETECTORS)
    t_max = max(f["test_to"] for f in run["folds"])
    if len(data) != run["data"]["n_rows"]:  # feed grew since the run: keep only rows the run could have seen
        data = data[data.t <= t_max].reset_index(drop=True)
        meta["data_hash"] = E.data_hash(data)
        meta["n_rows"] = len(data)
    print(json.dumps({"rebuilt_hash": meta["data_hash"], "stored_hash": run["data"]["data_hash"], "n_rows": meta["n_rows"]}))
    out = E.regate(run, data, data_hash=meta["data_hash"])
    print(json.dumps({k: out[k] for k in ("run_id", "decision", "genome_id", "strict_gate", "reproduced_fitness", "stored_fitness",
                                          "any_genome_passes")} | {"reason": out.get("reason")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
