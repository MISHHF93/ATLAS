"""15m BUY/SELL/HOLD model (milestone d): no lookahead, barrier bounds, costs in the label, purge, unchanged gates, HOLD default."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from atlas.ai.ml import cv
from atlas.ai.ml import multires as MR
from atlas.ai.ml import signal15 as S
from atlas.ai.ml import train as TR
from atlas.ai.ml.dataset import SeriesData
from atlas.features.price_action.bars import Bar

T0 = 1_790_000_000 // 900 * 900
N = 3000


def synth_bars(seed=7, n=N, asset="crypto"):
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    for i in range(n):
        vol = 0.004 * (1 + 2 * (i % 300 < 60))               # volatility clusters so breakouts and wicks occur
        o, px = px, px * math.exp(rng.normal(0, vol))
        out.append(Bar(T0 + i * 900, 900, o, max(o, px) * (1 + abs(rng.normal(0, vol))), min(o, px) * (1 - abs(rng.normal(0, vol))), px, float(rng.uniform(10, 100))))
    return out


def inputs_for(bars):
    rows = [(b.start, b.open, b.high, b.low, b.close, b.volume) for b in bars]
    return MR.Inputs("SYN", s15=MR.Bars.from_rows("15m", rows))


@pytest.fixture(scope="module")
def frame():
    bars = synth_bars()
    df = S.setup_frame(SeriesData("SYN", "15m", "crypto", bars, ["synthetic"]), inputs_for(bars), 32)
    assert len(df) > 200, "synthetic series must yield setups"
    return df


def test_gates_are_the_trainers_unchanged_object():
    assert S.GATES is TR.GATES
    assert TR.GATES == {"min_oos": 200, "min_dsr": 0.95, "max_pbo": 0.5, "min_shadow_weeks": 4}


def test_labels_and_contract_constants():
    assert S.EXECUTION_PERMISSION == "none" and S.MODE == "paper_shadow_only"
    assert "not advice" in S.LABEL.lower()


def test_hold_below_entry_window_is_refused():
    bars = synth_bars(n=400)
    with pytest.raises(ValueError):
        S.setup_frame(SeriesData("SYN", "15m", "crypto", bars, ["x"]), inputs_for(bars), 2)


def test_rows_sit_on_the_900s_clock_and_barrier_is_bounded(frame):
    assert (frame["t"] % 900 == 0).all()
    assert (frame["exit_at"] >= frame["t"]).all()
    assert (frame["exit_at"] - frame["t"] <= (S.MIN_ENTRY_WINDOW + 32 + 1) * 900).all()   # barrier runs from entry (<= 3 bars after detection)
    assert set(frame["y"].unique()) <= {0, 1}
    assert (frame["hold_bars"] == 32).all()


def test_crypto_round_trip_cost_is_inside_the_label(frame):
    assert np.allclose(frame["cost_r"] * frame["risk_bps"], 124.0, rtol=0.02)


def test_attached_features_do_not_look_ahead(frame):
    bars = synth_bars()
    cut = N // 2
    part = S.setup_frame(SeriesData("SYN", "15m", "crypto", bars[:cut], ["x"]), inputs_for(bars[:cut]), 32)
    horizon = T0 + (cut - 40) * 900
    a = frame[frame.t <= horizon].set_index(["t", "candidate_id"])
    b = part[part.t <= horizon].set_index(["t", "candidate_id"])
    assert len(b) > 20
    common = b.index.intersection(a.index)
    assert len(common) == len(b)
    for col in list(S.BASE_FEATURES) + list(MR.FEATURE_NAMES):
        x, y = a.loc[common, col].to_numpy(float), b.loc[common, col].to_numpy(float)
        assert np.allclose(x, y, equal_nan=True), col


def test_signed_copies_flip_with_direction(frame):
    d = np.where(frame["dir_long"] > 0, 1.0, -1.0)
    assert np.allclose(frame["m15_ret1_x_dir"], frame["m15_ret1"] * d, equal_nan=True)


def test_only_layers_with_real_coverage_are_used(frame):
    layers = S.usable_layers(frame)
    assert "m15" in layers and "s1" not in layers and "m1" not in layers and "flow" not in layers
    feats = S.model_features(layers)
    assert not any(f.startswith(("s1_", "m1_", "f_")) for f in feats)


def test_purged_walk_forward_has_no_overlap(frame):
    f = frame.sort_values(["t", "candidate_id"]).reset_index(drop=True)
    t, e = f["t"].to_numpy(np.int64), f["exit_at"].to_numpy(np.int64)
    folds = list(cv.walk_forward_splits(t, e, n_folds=4, embargo=TR.EMBARGO))
    assert folds
    for _, train, test in folds:
        assert e[train].max() < t[test].min()
        assert (t[test].min() - e[train].max()) >= TR.EMBARGO


class StubConformal:
    def take_mask(self, p):
        return np.asarray(p) > 0.5


class StubModel:
    features = ("a",)
    conformal = StubConformal()

    def decide(self, X):
        p = X["p"].to_numpy(float)
        ev = X["ev"].to_numpy(float)
        return {"p": p, "ev_r": ev, "take": (p > 0.5) & (ev > 0), "size": np.zeros(len(X))}


def test_actions_hold_by_default_and_buy_sell_need_take():
    X = pd.DataFrame({"dir_long": [1, 1, 0, 0, 1], "p": [0.7, 0.7, 0.7, 0.4, 0.4], "ev": [0.2, -0.1, 0.3, 0.3, 0.3]})
    got = S.decide_actions(StubModel(), X)
    assert list(got["action"]) == ["BUY", "HOLD", "SELL", "HOLD", "HOLD"]
    assert "size" not in got.columns
    assert S.decide_actions(StubModel(), X.iloc[0:0]).empty


def test_ranking_puts_actions_first_by_ev():
    f = pd.DataFrame({"action": ["HOLD", "BUY", "SELL"], "ev_r": [0.9, 0.1, 0.4]})
    assert list(S.rank_opportunities(f)["action"]) == ["SELL", "BUY", "HOLD"]


def test_status_never_eligible_without_shadow_weeks():
    ok = [{"gate": "n_oos", "passed": True}, {"gate": "shadow_weeks", "passed": False}]
    assert S.status_from_gates(ok) == "not_eligible"
    assert S.status_from_gates([]) == "not_eligible"
    assert S.status_from_gates([{"gate": "n_oos", "passed": True}]) == "eligible"


def test_save_and_load_roundtrip(tmp_path):
    S.save_model(tmp_path, "k", StubModel(), {"status": "not_eligible"})
    mm, man = S.load_model(tmp_path, "k")
    assert man["execution_permission"] == "none" and man["mode"] == "paper_shadow_only" and man["status"] == "not_eligible"
    assert S.load_model(tmp_path, "missing") is None



