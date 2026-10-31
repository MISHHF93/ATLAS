"""Compare frozen split conformal with ACI on an already-scored, time-ordered stream.

This does not fit a model and does not turn the serve flag on. The calibration prefix
is purged: a prefix row is kept only when its label ended strictly before the stream starts.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from atlas.ai.ml.directional.aci import aci_binary, empirical_qhat


def evaluate_aci_vs_split(t, exit_at, p, y, *, alpha: float = 0.2, gamma: float = 0.01) -> dict[str, Any]:
    t = np.asarray(t, np.int64)
    exit_at = np.asarray(exit_at, np.int64)
    p = np.asarray(p, float)
    y = np.asarray(y, int)
    order = np.argsort(t)
    n = len(order)
    if n < 30:
        return {"status": "insufficient_rows", "n": n, "need": 30, "enable_aci": False,
                "execution_permission": "none",
                "note": "Report only. This function does not set ATLAS_ML_ACI."}
    split_at = order[n // 5]
    t_stream = int(t[split_at])
    cal = [int(i) for i in order if int(t[i]) < t_stream and int(exit_at[i]) < t_stream]
    stream = [int(i) for i in order if int(t[i]) >= t_stream]
    if len(cal) < 20 or len(stream) < 10:
        return {"status": "insufficient_rows", "n_cal": len(cal), "n_stream": len(stream), "enable_aci": False,
                "execution_permission": "none",
                "note": "Report only. This function does not set ATLAS_ML_ACI."}
    cal_p, cal_y = p[cal], y[cal]
    init = np.where(cal_y == 1, 1.0 - cal_p, cal_p)
    q = empirical_qhat(init, alpha)
    sp, sy = p[stream], y[stream]
    s_y = np.where(sy == 1, 1.0 - sp, sp)
    split_err = (s_y > q).astype(float)
    aci = aci_binary(t[stream], exit_at[stream], sp, sy, init_scores=init, alpha=alpha, gamma=gamma)
    split_gap = float(abs(split_err.mean() - alpha))
    return {
        "status": "ok",
        "n_cal": len(cal),
        "n_stream": len(stream),
        "alpha": alpha,
        "split_coverage": float(1.0 - split_err.mean()),
        "split_gap": split_gap,
        "aci_coverage": aci["coverage"],
        "aci_gap": aci["gap"],
        "aci_gap_bound": aci["gap_bound"],
        "aci_within_bound": bool(aci["gap"] <= aci["gap_bound"]) if aci["gap"] == aci["gap"] else False,
        "enable_aci": False,
        "execution_permission": "none",
        "note": "Report only. Set ATLAS_ML_ACI=1 yourself if you accept this coverage. This script does not enable it.",
    }
