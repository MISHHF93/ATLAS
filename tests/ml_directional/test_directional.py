"""evo-14 directional pipeline: causality, label arithmetic, ACI guarantee, gates on pure noise. Synthetic bars only."""
import numpy as np
import pandas as pd
import pytest

from atlas.ai.ml.directional import labels as L
from atlas.ai.ml.directional import pipeline as P
from atlas.ai.ml.directional.aci import aci_binary
from atlas.ai.ml.directional.features import build_features, cross_features, feature_names
from atlas.features.price_action.bars import Bar

DUR = 900


def make_bars(n=3000, seed=1, drift=0.0, start=1_700_000_000, vol=0.004):
    rng = np.random.default_rng(seed)
    sig = vol * np.exp(0.3 * np.sin(np.arange(n) / 200.0))
    r = rng.normal(drift, sig)
    c = 100 * np.exp(np.cumsum(r))
    out, prev = [], 100.0
    for i in range(n):
        o = prev
        cl = c[i]
        hi = max(o, cl) * (1 + abs(rng.normal(0, sig[i] / 2)))
        lo = min(o, cl) * (1 - abs(rng.normal(0, sig[i] / 2)))
        out.append(Bar(start + i * DUR, DUR, o, hi, lo, cl, 1000.0 + rng.integers(0, 500)))
        prev = cl
    return out


def frame(bars):
    return pd.DataFrame({"end": [b.end for b in bars], "high": [b.high for b in bars], "low": [b.low for b in bars], "close": [b.close for b in bars]})


def test_triple_barrier_hand_example():
    # entry 100, sigma 0.01, horizon 4, k 1 -> w = 0.02; upper = 100*e^0.02 = 102.02
    cl = [100, 100.5, 101.0, 102.5, 101.0, 100.0]
    bars = [Bar(i * 60, 60, c, c * 1.0001, c * 0.9999, c) for i, c in enumerate(cl)]
    df = frame(bars)
    bars2 = list(bars)
    # make bar 3 spike through the upper barrier
    bars2[3] = Bar(180, 60, 101.0, 102.6, 100.9, 102.5)
    df = frame(bars2)
    lab = L.triple_barrier(df, np.array([0]), np.full(len(df), 0.01), horizon=4, k=1.0)
    assert lab.loc[0, "label"] == 1 and lab.loc[0, "y_up"] == 1
    assert lab.loc[0, "ret"] == pytest.approx(0.02)
    assert lab.loc[0, "t_barrier_exit"] == bars2[3].end and lab.loc[0, "exit_at"] == bars2[4].end
    # both barriers in one bar -> ambiguous label 0
    bars3 = list(bars)
    bars3[2] = Bar(120, 60, 100.5, 103.0, 97.0, 100.5)
    lab = L.triple_barrier(frame(bars3), np.array([0]), np.full(6, 0.01), horizon=4, k=1.0)
    assert lab.loc[0, "label"] == 0 and bool(lab.loc[0, "ambiguous"])


def test_unresolved_events_are_dropped():
    bars = make_bars(300)
    df = frame(bars)
    lab = L.triple_barrier(df, np.array([295]), L.ewma_sigma(df["close"].to_numpy()), horizon=10)
    assert len(lab) == 0


def test_events_labels_and_features_do_not_use_the_future():
    bars = make_bars(1500, seed=3)
    cut = 1000
    a = bars
    b = bars[: cut + 1] + [Bar(x.start, x.duration, x.close * 3, x.close * 3.1, x.close * 2.9, x.close * 3, 9.0) for x in bars[cut + 1:]]
    da, db = frame(a), frame(b)
    sa, sb = L.ewma_sigma(da["close"].to_numpy()), L.ewma_sigma(db["close"].to_numpy())
    assert np.allclose(sa[: cut + 1], sb[: cut + 1], equal_nan=True)
    ea, eb = L.cusum_events(da["close"].to_numpy(), sa), L.cusum_events(db["close"].to_numpy(), sb)
    # b has a huge jump at cut+1 so only events <= cut are comparable
    assert np.array_equal(ea[ea <= cut], eb[eb <= cut])
    h = 20
    la = L.triple_barrier(da, ea[ea <= cut - h], sa, h)
    lb = L.triple_barrier(db, eb[eb <= cut - h], sb, h)
    pd.testing.assert_frame_equal(la, lb)
    fa = build_features(a, "15m", "crypto", "BTCUSDT", True)
    fb = build_features(b, "15m", "crypto", "BTCUSDT", True)
    pd.testing.assert_frame_equal(fa.iloc[: cut + 1], fb.iloc[: cut + 1])


def test_cross_features_use_only_reference_bars_that_ended_by_own_end():
    own_end = np.array([100, 200, 300, 400])
    own_close = np.array([1.0, 1.1, 1.2, 1.3])
    ref_end = np.array([100, 250, 400])        # the 250 bar must not be visible at own end 200
    ref_close = np.array([10.0, 20.0, 30.0])
    x = cross_features(own_end, own_close, {"R": (ref_end, ref_close)})
    # at own_end=200 the last ref bar ending <= 200 is the 100 bar (10.0); at 300 it is 250 (20.0)
    assert x["x_R_ret_1"].iloc[1] == pytest.approx(0.0)
    assert x["x_R_ret_1"].iloc[2] == pytest.approx(np.log(20 / 10))
    assert x["x_R_ret_1"].iloc[3] == pytest.approx(np.log(30 / 20))


def test_aci_coverage_guarantee_on_iid_stream():
    rng = np.random.default_rng(0)
    n = 4000
    p = np.clip(rng.beta(2, 2, n), 0.01, 0.99)
    y = (rng.random(n) < p).astype(int)           # perfectly calibrated
    t = np.arange(n) * 10
    res = aci_binary(t, t + 5, p, y, alpha=0.2, gamma=0.01, window=500)
    assert abs(res["coverage"] - 0.8) <= res["gap_bound"]
    assert res["gap"] < 0.03


def test_aci_stays_valid_under_a_shifted_calibration():
    rng = np.random.default_rng(1)
    n = 6000
    p = np.clip(rng.beta(2, 2, n), 0.01, 0.99)
    y = (rng.random(n) < np.where(np.arange(n) < n // 2, p, 1 - p)).astype(int)   # labels flip halfway: p becomes anti-calibrated
    t = np.arange(n) * 10
    res = aci_binary(t, t + 5, p, y, alpha=0.2, gamma=0.02, window=300)
    assert res["gap"] <= res["gap_bound"]


def test_aci_only_uses_resolved_scores():
    n = 50
    t = np.arange(n) * 10
    p = np.full(n, 0.9)
    y = np.zeros(n, int)                            # always wrong at p=0.9 for label 1
    never_resolved = np.full(n, 10**9)
    res = aci_binary(t, never_resolved, p, y, alpha=0.2, gamma=0.01)
    assert all(s == frozenset({0, 1}) for s in res["sets"])    # no resolved history -> full set, never a singleton


def test_noise_series_is_labelled_research_below_gate_and_never_eligible():
    bars = make_bars(2600, seed=11, drift=0.0)
    res = P.run(None, [("BTCUSDT", "15m")], load=lambda i, iv: bars if i == "BTCUSDT" else (_ for _ in ()).throw(KeyError(i)))
    g = res["groups"]["crypto-15m"]
    assert res["execution_permission"] == "none"
    assert g["label"] == P.LABEL_BELOW or g["label"] == P.LABEL_SHADOW
    names = [x["gate"] for x in g["gates"]]
    assert {"n_oos", "brier_beats_base_rate", "deflated_sharpe", "pbo", "aci_coverage", "quantile_beats_unconditional", "shadow_weeks"} <= set(names)
    assert not next(x for x in g["gates"] if x["gate"] == "shadow_weeks")["passed"]
    # inherited strictness
    assert P.GATE_SET["min_dsr"] >= P.META_GATES["min_dsr"] and P.GATE_SET["max_pbo"] <= P.META_GATES["max_pbo"] and P.GATE_SET["min_oos"] >= P.META_GATES["min_oos"]
    # pure noise must not pass the full offline set (DSR/PBO/Brier together)
    assert g["label"] == P.LABEL_BELOW


def test_short_or_missing_series_are_skipped_with_reason():
    res = P.run(None, [("BTCUSDT", "15m"), ("ETHUSDT", "15m")], load=lambda i, iv: make_bars(50) if i == "BTCUSDT" else (_ for _ in ()).throw(RuntimeError("no data")))
    reasons = " ".join(s["reason"] for s in res["skipped"])
    assert "only 50 bars" in reasons and "load_error" in reasons and res["groups"] == {}


def test_run_is_deterministic():
    bars = make_bars(2200, seed=5)
    a = P.run(None, [("BTCUSDT", "15m")], load=lambda i, iv: bars if i == "BTCUSDT" else (_ for _ in ()).throw(KeyError(i)))
    b = P.run(None, [("BTCUSDT", "15m")], load=lambda i, iv: bars if i == "BTCUSDT" else (_ for _ in ()).throw(KeyError(i)))
    ga, gb = a["groups"]["crypto-15m"], b["groups"]["crypto-15m"]
    assert ga["prob"]["hgb"]["brier"] == gb["prob"]["hgb"]["brier"]
    assert a["data_digest"] == b["data_digest"]


def test_feature_name_contract():
    bars = make_bars(800, seed=2)
    f = build_features(bars, "15m", "crypto", "BTCUSDT", True)
    assert set(feature_names()) <= set(f.columns)


def _momentum_bars(n=6000, seed=2, s=0.004):
    rng = np.random.default_rng(seed)
    r = [0.0]
    for _ in range(1, n):
        r.append(0.48 * s * np.tanh(sum(r[-16:]) / (4 * s)) + rng.normal(0, s))
    c = 100 * np.exp(np.cumsum(r))
    return [Bar(1_700_000_000 + i * DUR, DUR, c[i - 1] if i else 100.0, max(c[i], c[i - 1] if i else 100.0) * 1.0005,
                min(c[i], c[i - 1] if i else 100.0) * 0.9995, c[i], 1000.0) for i in range(n)]


def test_pipeline_detects_planted_structure_but_probabilities_stay_bounded():
    bars = _momentum_bars()
    res = P.run(None, [("BTCUSDT", "15m")], load=lambda i, iv: bars if i == "BTCUSDT" else (_ for _ in ()).throw(KeyError(i)))
    g = res["groups"]["crypto-15m"]
    assert max(g["prob"]["hgb"]["auc"], g["prob"]["logit"]["auc"]) > 0.55          # the planted dependence is found out of sample
    assert g["prob"]["hgb"]["logloss"] < 3.0                                         # clipping: no 0/1 probabilities
    assert "shadow_weeks" in [x["gate"] for x in g["gates"]]


def test_persist_and_live_score_roundtrip(tmp_path):
    from atlas.ai.ml.directional.live import directional_prediction
    bars = _momentum_bars(3500, seed=4)
    res = P.run(None, [("BTCUSDT", "15m")], load=lambda i, iv: bars, registry_root=tmp_path)
    g = res["groups"]["crypto-15m"]
    out = directional_prediction("BTCUSDT", "15m", bars, root=tmp_path)
    assert out["status"] == "ok" and out["execution_permission"] == "none" and out["label"] == g["label"]
    assert 0.0 < out["probability"] < 1.0 and out["conformal_set"] and out["band"]["p10"] < out["band"]["p90"]
    assert out["orders"].startswith("none")
    # unknown instrument / scope are reported, never guessed
    assert directional_prediction("SOLUSDT", "15m", bars, root=tmp_path)["status"] == "no_model"
    assert directional_prediction("BTCUSDT", "1h", bars, root=tmp_path)["status"] == "no_model"
    assert directional_prediction("BTCUSDT", "15m", bars[:100], root=tmp_path)["status"] == "insufficient_history"


def test_live_score_ignores_the_unfinished_future_of_reference_series():
    from atlas.ai.ml.directional.features import cross_features as cf
    # a reference bar that ends after own_end can never leak in
    x = cf(np.array([100]), np.array([1.0]), {"R": (np.array([50, 101]), np.array([5.0, 99.0]))})
    assert np.isnan(x["x_R_ret_1"].iloc[0]) or x["x_R_ret_1"].iloc[0] == 0.0
