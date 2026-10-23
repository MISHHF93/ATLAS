"""Item 1: CPCV, PBO/CSCV, trial log, DSR gate in promotion + autonomy evaluator."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from atlas.control.policy.schemas import ModelPromotionCfg
from atlas.models.quant.validation import (TrialLog, assemble_paths, cpcv, cpcv_paths, pbo_cscv, purged_kfold_t1,
                                      validation_report)
from atlas.risk.ladder import LadderEvaluator


def _times(n=300, h=5):
    t0 = pd.date_range("2024-01-01", periods=n, freq="D").values
    return t0, t0 + np.timedelta64(h, "D")


def test_purged_kfold_no_label_overlap():
    t0, t1 = _times()
    for tr, te in purged_kfold_t1(t0, t1, 5, 0.01):
        lo, hi = t0[te].min(), t1[te].max()
        assert not np.any((t0[tr] <= hi) & (t1[tr] >= lo))
        assert len(np.intersect1d(tr, te)) == 0


def test_cpcv_split_count_paths_and_purging():
    t0, t1 = _times()
    splits = list(cpcv(t0, t1, n_groups=6, k_test=2))
    assert len(splits) == 15 and cpcv_paths(6, 2) == 5
    for tr, te, _ in splits:
        assert len(np.intersect1d(tr, te)) == 0
    # assemble: each group covered phi times -> phi full paths
    oos = {combo: {g: np.full(3, g, float) for g in combo} for _, _, combo in splits}
    paths = assemble_paths(oos, 6, 2)
    assert len(paths) == 5 and all(len(p) == 18 for p in paths)


def test_pbo_high_for_noise_low_for_real_edge():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (1000, 30))
    assert pbo_cscv(noise, 10)["pbo"] > 0.3
    real = noise.copy(); real[:, 0] += 0.003
    assert pbo_cscv(real, 10)["pbo"] < 0.1


def test_trial_log_append_only_and_dsr_deflates_with_trials(tmp_path):
    log = TrialLog(tmp_path / "t.jsonl")
    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.01, 500)
    few = validation_report(r, [0.02, 0.01])
    for i in range(200):
        log.append("fam", {"i": i}, float(rng.normal(0, 0.05)), 500)
    assert log.count() == 200 and log.count("fam") == 200
    many = validation_report(r, log.srs())
    assert many["n_trials"] == 200 and many["dsr"] < few["dsr"]


def test_promotion_cfg_dsr_floor_cannot_be_lowered():
    with pytest.raises(Exception):
        ModelPromotionCfg(min_dsr=0.5)
    with pytest.raises(Exception):
        ModelPromotionCfg(max_pbo=0.9)


def test_registry_refuses_promotion_without_dsr(tmp_path):
    from atlas.models.quant.registry import ModelRegistry, PromotionDenied
    GOOD = {"n": 50, "lift_bps": 5.0, "brier": 0.24, "champion_brier": 0.245, "drawdown_pct": 2.0}
    t = [datetime(2026, 10, 16, tzinfo=timezone.utc)]
    reg = ModelRegistry(tmp_path / "r", clock=lambda: t[0])
    for val, ok in (({"dsr": 0.80, "n_trials": 40}, False), ({"dsr": 0.99, "pbo": 0.7}, False), ({"dsr": 0.99, "pbo": 0.1}, True)):
        mid = reg.register(_Dummy(), {"feature_importance_stability_spearman": 0.8, "validation": val})
        reg.make_challenger(mid)
        for w in range(4):
            reg.record_shadow_week(mid, f"2027-W{10 + w}", GOOD)
        t[0] += timedelta(days=30)
        if ok:
            reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)
            assert reg.champion == mid
        else:
            with pytest.raises(PromotionDenied, match="deflated_sharpe|pbo"):
                reg.promote(mid, ModelPromotionCfg(), "learning_loop", 1)


class _Dummy:
    def save(self, d):
        d.mkdir(parents=True, exist_ok=True); (d / "m.txt").write_text("x")


def test_autonomy_evaluator_has_dsr_check_deflated_by_trials():
    from types import SimpleNamespace
    pol = SimpleNamespace(autonomy=SimpleNamespace(level=1, model_extra={"gates": {"level_2": {}}}))
    rng = np.random.default_rng(3)
    v = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.005, 120)))
    eq = [[(datetime(2026, 1, 1) + timedelta(days=i)).isoformat(), float(x)] for i, x in enumerate(v)]
    ev = LadderEvaluator(pol)
    a = {c["name"]: c for c in ev.evaluate(eq, [1.0], 0.0, 0, [])["checks"]}
    b = {c["name"]: c for c in ev.evaluate(eq, [1.0], 0.0, 0, list(rng.normal(0, 0.3, 500)))["checks"]}
    assert "deflated_sharpe" in a and a["deflated_sharpe"]["value"] >= b["deflated_sharpe"]["value"]
    assert b["deflated_sharpe"]["passed"] is False
    assert ev.evaluate(eq, [1.0])["can_self_promote"] is False
