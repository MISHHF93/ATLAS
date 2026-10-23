"""Weekly retrain job (weekend / crypto-only window): rebuild dataset, purged walk-forward
evaluation with deflated Sharpe over all trials logged so far, register the new model as
CHALLENGER (it never becomes champion here), write a JSON + Markdown report."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from atlas.models.quant.evaluate import walk_forward_report
from atlas.models.quant.features import bars_frame, dataset
from atlas.models.quant.registry import ModelRegistry


def _trials(root: Path) -> list[float]:
    p = root / "trials.json"
    return json.loads(p.read_text()) if p.exists() else []


def weekly_retrain(bars: dict[str, pd.DataFrame], registry: ModelRegistry, horizon: int = 5, cost_bps: float = 10.0,
                   min_p_hit: float = 0.55, n_splits: int = 4) -> dict:
    ds = dataset(bars, horizon, cost_bps)
    data_hash = hashlib.sha256(pd.util.hash_pandas_object(ds, index=True).values.tobytes()).hexdigest()
    trials = _trials(registry.root)
    rep = walk_forward_report(ds, horizon=horizon, n_splits=n_splits, min_p_hit=min_p_hit, prior_trial_srs=trials)
    model = rep.pop("final_model")
    (registry.root / "trials.json").write_text(json.dumps(trials + rep["trial_srs_added"]))  # every experiment logged
    mid = registry.register(model, rep, data_hash)
    registry.make_challenger(mid)
    rep |= {"model_id": mid, "data_hash": data_hash, "generated": datetime.now(timezone.utc).isoformat(),
            "note": "Registered as CHALLENGER. Needs >= min_shadow_weeks shadow results + gates + sign-off to promote."}
    rdir = registry.root / "reports"
    rdir.mkdir(exist_ok=True)
    (rdir / f"{mid}.json").write_text(json.dumps(rep, indent=1, default=str))
    (rdir / f"{mid}.md").write_text(render_md(rep))
    return rep


def render_md(rep: dict) -> str:
    o, d = rep["oos"], rep["deflated_sharpe"]
    lines = [f"# Weekly retrain report: {rep.get('model_id','')}", "",
             "Paper/shadow only. Models filter rule candidates; they cannot add trades or promote themselves.", "",
             f"- OOS samples: {o['n']}  AUC: {o['auc']:.3f}  Brier: {o['brier']:.4f}",
             f"- Sharpe filtered: {o['sharpe_filtered']:.2f}  rules-only: {o['sharpe_rules_only']:.2f}  lift: {o['lift_bps_per_day']:.2f} bps/day",
             f"- Deflated Sharpe: DSR={d['dsr']:.3f} (trials={d['n_trials']}, SR0/period={d['sr0_expected_max_per_period']:.4f})",
             f"- Feature-importance stability (Spearman): {rep['feature_importance_stability_spearman']:.2f}",
             f"- SHAP backend: {rep['shap_backend']}", "", "| fold | train_end | test_start | AUC | Brier | take | taken bps | rules bps |",
             "|---|---|---|---|---|---|---|---|"]
    for f in rep["folds"]:
        lines.append(f"| {f['fold']} | {f['train_end']} | {f['test_start']} | {f['auc']:.3f} | {f['brier']:.4f} | "
                     f"{f['take_rate']:.2f} | {f['mean_fwd_taken_bps']:.1f} | {f['mean_fwd_rules_bps']:.1f} |")
    lines += ["", "Top SHAP (mean |contribution|):"]
    for k, v in sorted(rep["shap_global_mean_abs"].items(), key=lambda t: -t[1])[:5]:
        lines.append(f"- {k}: {v:.5f}")
    return "\n".join(lines) + "\n"


def synthetic_bars(symbols=("SPY", "QQQ", "XIC"), start=date(2018, 1, 1), end=date(2024, 12, 31), seed=0):
    from atlas.marketdata.pit.synthetic import gbm_bars
    venue = {"XIC": "XTSE"}
    return {s: bars_frame(gbm_bars(s, venue.get(s, "XNYS"), start, end, seed=seed)) for s in symbols}


def main(argv=None) -> int:
    from atlas.risk.safety import assert_paper_only
    assert_paper_only()
    ap = argparse.ArgumentParser(prog="atlas-ml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("retrain"); r.add_argument("--registry", default="var/models")
    r.add_argument("--synthetic", action="store_true", help="use deterministic synthetic bars (offline)")
    r.add_argument("--parquet-dir", help="dir of <SYMBOL>.parquet with close,volume")
    s = sub.add_parser("status"); s.add_argument("--registry", default="var/models")
    rs = sub.add_parser("recipe-search", help="search component x data combinations (CPCV/walk-forward, PBO, DSR)")
    rs.add_argument("--trials", type=int, default=60); rs.add_argument("--seed", type=int, default=7)
    rs.add_argument("--out", default="var/recipes"); rs.add_argument("--models-root", default="var/models")
    rs.add_argument("--report", default="var/recipes/recipe-search.md")
    rs.add_argument("--parquet-dir", help="real daily closes (<SYMBOL>.parquet); default is the SYNTHETIC world")
    rs.add_argument("--tsfm", default="chronos-bolt", help="chronos-bolt | timesfm | moirai | lag-llama | patchtst | patch-linear")
    rs.add_argument("--no-register", action="store_true", help="do not register the winner as a challenger")
    a = ap.parse_args(argv)
    if a.cmd == "recipe-search":
        from atlas.models.quant.recipes import register_winner, render_md, search, world_from_parquet
        w = world_from_parquet(a.parquet_dir) if a.parquet_dir else None
        res = search(w, n_trials=a.trials, seed=a.seed, out_dir=a.out, tsfm_provider=a.tsfm,
                     progress=lambda i, n, r: print(f"  [{i}/{n}] {r.model:<10} {r.data:<12}", flush=True))
        md = render_md(res)
        if not a.no_register:
            mid = register_winner(res, a.models_root)
            md += (f"\nWinner registered as challenger `{mid}` in {a.models_root}/recipe. It must pass the existing "
                   "champion/challenger shadow gates (>= 4 weeks) and owner approval; there is no auto-promotion.\n")
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(md)
        print(md)
        return 0
    reg = ModelRegistry(a.registry)
    if a.cmd == "status":
        print(json.dumps({"champion": reg.champion, "challenger": reg.challenger,
                          "models": {k: v["stage"] for k, v in reg.idx["models"].items()}}, indent=1))
        return 0
    if a.parquet_dir:
        bars = {p.stem: pd.read_parquet(p) for p in Path(a.parquet_dir).glob("*.parquet")}
    elif a.synthetic:
        bars = synthetic_bars()
    else:
        ap.error("need --synthetic or --parquet-dir")
    rep = weekly_retrain(bars, reg)
    print(render_md(rep))
    return 0
