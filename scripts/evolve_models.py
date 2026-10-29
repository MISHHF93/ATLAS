"""On-demand governed model evolution. Usage:
  PYTHONPATH=src ATLAS_FEED_DB=... python scripts/evolve_models.py [--generations 3] [--seed 11]
Writes leaderboard/lineage/champion under the ML registry (var/ml/registry/evolution; never committed).
Research only: execution_permission none; nothing is promoted to execution."""
import argparse
import json
from datetime import datetime, timezone


def _run_niches(data, meta, args) -> int:
    """Evolve each venue on its own rows, then keep one elite per session and volatility cell."""
    from atlas.ai.ml import niche_archive as N
    from atlas.ai.ml.market_islands import evolve_islands, open_islands
    from atlas.ai.ml.registry import _clean
    from atlas.ml import evolution as E

    log = lambda s: print(s, flush=True)
    log(f"island evolution rows={len(data)}")
    genes = {**E.GENES, "bar_type": ("time",)} if getattr(args, "bar_types", "all") == "time" else None
    islands = evolve_islands(
        data, meta, generations=args.generations, seed=args.seed, seeds=E.LIVE_SEEDS,
        top_k=2, children_per_parent=1, log=log, genes=genes,
    )
    crowned = E.publish_research_champion(islands.get("strict_passes") or [])
    log(f"strict-gate champions published: {len(crowned)}")
    log("niche illumination")
    archive = N.fill_from_genomes(data, E.LIVE_SEEDS, log=log)
    now = datetime.now(timezone.utc)
    latest = data.sort_values("t").iloc[-1]
    rv = float(latest["rv_pctile_480"]) if "rv_pctile_480" in data.columns else None
    selection = N.select_elite(archive, now, rv)
    out = {
        "created_at": int(now.timestamp()),
        "execution_permission": "none",
        "promoted_to_execution": False,
        "n_rows": int(len(data)),
        "data_hash": meta.get("data_hash"),
        "universe": args.universe,
        "generations": args.generations,
        "seed": args.seed,
        "islands": islands["islands"],
        "archive_summary": N.summary(archive),
        "cells": archive["cells"],
        "skipped": archive["skipped"],
        "n_evaluated": archive["n_evaluated"],
        "open_islands": sorted(open_islands(now)),
        "selection": selection,
        "champion_runs": crowned,
        "variant": getattr(args, "variant", None),
        "note": (
            "Official 4h bars, prior-day-range reversal, 2 ATR stop, cost/R capped at 0.15. "
            "The daily trend is a gene. The evo8 gate is unchanged. Yahoo is not a source. "
            "Nothing is eligible for execution."
            if getattr(args, "universe", None) == "official"
            else "Research run. The evo8 gate is unchanged. Nothing is eligible for execution."
        ),
    }
    d = E.evo_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"niches_{out['created_at']}.json"
    path.write_text(json.dumps(_clean(out), default=str))
    brief = {
        "status": "ok",
        "path": str(path),
        "n_rows": out["n_rows"],
        "archive": out["archive_summary"],
        "open_islands": out["open_islands"],
        "selection": {k: selection.get(k) for k in ("decision", "cell", "island", "genome_id", "fitness", "reason")},
        "islands": [
            (r["island"], r["n_rows"], r.get("genome_id"), (r.get("metrics") or {}).get("fitness"), r.get("no_model_beats_baseline"))
            for r in islands["islands"]
        ],
        "champion_runs": crowned,
        "execution_permission": "none",
        "promoted_to_execution": False,
    }
    print(json.dumps(_clean(brief), indent=1, default=str), flush=True)
    print("EVOLVE_DONE", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--universe", choices=("default", "extended", "official", "evo6", "evo7", "evo7_1h", "evo9_4h", "evo9_1h", "evo9_multi"), default="default")
    ap.add_argument("--variant", default=None)
    ap.add_argument("--mode", choices=("pooled", "niches"), default="pooled")
    ap.add_argument("--bar-types", choices=("all", "time"), default="all")
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
    bar_types = None if a.bar_types == "all" else ("time",)
    if a.universe in uni_map:
        vid = a.variant or (E.EVO9_VARIANT if a.universe.startswith("evo9") else E.EVO6_VARIANT)
        data, meta = E.build_population_data(get_feed(), uni_map[a.universe], variant=vid, detectors=E.EVO6_DETECTORS, bar_types=bar_types, log=lambda s: print(s, flush=True))
    else:
        chosen = {"extended": E.UNIVERSE_EXTENDED, "official": E.UNIVERSE_OFFICIAL}.get(a.universe, E.UNIVERSE)
        detectors = None
        if a.universe == "official":
            a.variant = a.variant or E.OFFICIAL_VARIANT
            detectors = E.EVO6_DETECTORS
        data, meta = E.build_population_data(
            get_feed(), chosen, variant=a.variant, detectors=detectors, bar_types=bar_types,
            log=lambda s: print(s, flush=True),
        )
    if not len(data):
        print(json.dumps({"status": "no_data", "meta": meta}))
        print("EVOLVE_FAILED no_data", flush=True)
        return 1
    if a.mode == "niches":
        return _run_niches(data, meta, a)
    genes = {**E.GENES, "bar_type": ("time",)} if a.bar_types == "time" else None
    res = E.evolve(data, meta, generations=a.generations, seed=a.seed, genes=genes, log=lambda s: print(s, flush=True))
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
