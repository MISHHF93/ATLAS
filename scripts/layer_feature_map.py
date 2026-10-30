"""Layer -> model-feature mapping with non-NaN coverage per asset group, from a directional training run's report.json.
Usage: PYTHONPATH=src python scripts/layer_feature_map.py [--report var/ml/directional/report.json] [--out docs/layer-feature-map.md]

Nothing is invented: feature names come from the code, coverage from the training matrices the run actually fitted
(`feature_coverage[group-interval].finite_frac`, written by atlas.ai.ml.directional.pipeline). 'n/a' means the layer is a model
OUTPUT or a realised outcome, which is excluded from the inputs by design (it would be circular)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from atlas.ai.ml.directional import features as DF, layers25 as L
from atlas.ai.ml.dataset import SETUP_FEATURES
from atlas.ai.ml.vwap_features import VWAP_FEATURES

OUTPUT_LAYERS = {"ml_markers": "model output", "ml_probability": "model output", "predictions": "model output (scored markers)", "prediction_zone": "model output (forward band)",
                 "outcomes": "realised outcome (label)", "trade_lines": "derived from model markers", "marker_details": "explanation of model markers", "conviction": "rule score summarising setups + model output"}
# Base layers feed the model through the pre-existing feature groups (evo-14 "v2") and the setup meta-labeller.
BASE = {"setups": SETUP_FEATURES, "zones": ("dist_hi64_atr", "dist_lo64_atr", "range_pos_64", "ex_pd_range_pos"), "vwap": VWAP_FEATURES, "anchored_vwap": ("ex_avwap_dist_atr",),
        "sessions": ("hod_sin", "hod_cos", "vwap_sess_frac"), "volume_profile": ("ex_vp_poc_dist_atr", "ex_vp_va_pos"), "regimes": DF.REGIME_FEATURES}
DISPLAY_ONLY = {"macro_risk": "FRED (keyed): terms prohibit AI training/archival (Decision #29), so display only"}
ORDER = ["setups", "zones", "vwap", "anchored_vwap", "sessions", "volume_profile", "regimes", "conformal_bands", "mtf_confluence", "events", "market_clock", "cross_corr", "vol_cone",
         "liquidity", "model_disagreement", "account_size", "drift_alert", "news", "breadth", "overnight_intraday", "gap_stats", "seasonality", "implied_vol", "usd_proxy"]


def table(report: dict) -> str:
    cov = report.get("feature_coverage") or {}
    groups = ("crypto", "equity", "gold")
    keys = {g: sorted(k for k in cov if k.split("-")[0] == g) for g in groups}

    def frac(feat: str, g: str) -> tuple[float | None, int]:
        """Mean finite fraction across the group's intervals, weighted by rows."""
        n = tot = 0
        for k in keys[g]:
            f = cov[k]["finite_frac"].get(feat)
            if f is None:
                continue
            n += cov[k]["n_rows"]
            tot += f * cov[k]["n_rows"]
        return (tot / n if n else None), n

    def cell(feats, g):
        vals = [frac(f, g)[0] for f in feats]
        vals = [v for v in vals if v is not None]
        if not vals:
            return "not in this run's training set"
        dead = sum(1 for v in vals if v < 0.005)
        return f"{100 * sum(vals) / len(vals):.0f}%" + (f" ({dead}/{len(vals)} all-NaN)" if dead else "")

    out = ["| # | Layer | Model features (names) | " + " | ".join(f"{g} non-NaN" for g in groups) + " |", "|---|---|---|" + "---|" * len(groups)]
    i = 0
    for lid in ORDER:
        i += 1
        feats = BASE.get(lid) or L.LAYER_FEATURES.get(lid, ())
        out.append(f"| {i} | {lid} | {', '.join(feats)} | " + " | ".join(cell(feats, g) for g in groups) + " |")
    for lid, why in {**OUTPUT_LAYERS, **DISPLAY_ONLY}.items():
        i += 1
        out.append(f"| {i} | {lid} | n/a: {why} | n/a | n/a | n/a |")
    out += ["", "Per-feature, per group-interval detail (finite fraction of training rows):", "", "| group-interval | rows | features all-NaN (0%) | features under 50% |", "|---|---|---|---|"]
    for k in sorted(cov):
        fr = cov[k]["finite_frac"]
        out.append(f"| {k} | {cov[k]['n_rows']} | {', '.join(c for c, v in fr.items() if v < 0.005) or 'none'} | {', '.join(f'{c} {v:.0%}' for c, v in fr.items() if 0.005 <= v < 0.5) or 'none'} |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="var/ml/directional/report.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rep = json.loads(Path(a.report).read_text(encoding="utf-8"))
    md = table(rep)
    if a.out:
        Path(a.out).write_text(md + "\n", encoding="utf-8")
    print(md)
