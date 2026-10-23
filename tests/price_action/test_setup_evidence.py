"""Evaluation-harness tests on SYNTHETIC fixtures only (labelled); no real-data numbers live here."""
import json
import math

import numpy as np

from atlas.research.setup_evidence import Resolved, load_bars, registry_gates, reliability, walk_forward


def _resolved(n=600, informative=True, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        s = rng.normal()
        p = 1 / (1 + math.exp(-(1.5 * s - 1))) if informative else 0.27
        y = int(rng.random() < p)
        out.append(Resolved(i * 7200, i * 7200 + 3600, s, y, 2.0 - 0.05 if y else -1.05, 2.0, 0.05))
    return out


def test_walk_forward_is_purged_and_calibrated_only_on_past():
    wf = walk_forward(_resolved())
    assert wf["n_oos"] > 0 and len([f for f in wf["folds"] if "n_train" in f and "n_test" in f]) == 5
    assert wf["brier_skill"] > 0 and wf["logloss_model"] < wf["logloss_baseline"]   # informative synthetic score


def test_uninformative_score_has_no_skill_and_fails_gates():
    wf = walk_forward(_resolved(informative=False))
    c = {"interval": "1h", **wf, "dsr": {"r_gate": {"dsr": 0.1}}}
    g = {x["gate"]: x["passed"] for x in registry_gates(c, {"1h": {"pbo": 0.6}})}
    assert not g["deflated_sharpe"] and not g["pbo"] and not g["shadow_weeks"]


def test_reliability_bins_cover_all():
    p = np.linspace(0, 1, 101); y = (p > 0.5).astype(int)
    assert sum(b["n"] for b in reliability(p, y)) == 101


def test_load_bars_drops_in_progress_bar(tmp_path):
    f = tmp_path / "X_1h.json"
    f.write_text(json.dumps({"source": "synthetic_fixture", "url": "-", "symbol": "X", "interval": "1h",
                             "fetched_at": "1970-01-01T03:30:00+00:00",
                             "bars": [[0, 1, 2, 0.5, 1.5, 0], [3600, 1, 2, 0.5, 1.5, 0], [7200, 1, 2, 0.5, 1.5, 0], [10800, 1, 2, 0.5, 1, 0]]}))
    bars, meta = load_bars(f)
    assert [b.start for b in bars] == [0, 3600, 7200] and meta["n_bars"] == 3
