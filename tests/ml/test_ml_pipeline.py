"""ML pipeline guarantees: causality, purging, determinism, gating, calibration/conformal, drift, retrieval, shadow."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from atlas.features.price_action.bars import Bar
from atlas.ml import registry as R
from atlas.ml.calibration import fit_calibrator, fit_conformal
from atlas.ml.cv import inner_split, walk_forward_splits
from atlas.ml.dataset import DETECTORS, FEATURES
from atlas.ml.drift import ADWIN, adwin_report, feature_psi, reference
from atlas.ml.features import bar_features
from atlas.ml.retrieval import BM25Index, build_index, split_passages
from atlas.ml.train import fit_final, run_training


def bars(n=600, seed=0, dur=900):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.002, n)))
    out = []
    for i in range(n):
        o = c[i - 1] if i else c[0]
        out.append(Bar(1_700_000_000 + i * dur, dur, o, max(o, c[i]) * 1.001, min(o, c[i]) * 0.999, c[i], 1000 + 10 * i))
    return out


def synth(n=1500, seed=1, signal=0.0):
    r = np.random.default_rng(seed)
    t = np.sort(1_700_000_000 + r.integers(0, 200 * 86400, n))
    df = pd.DataFrame({f: r.normal(size=n) for f in FEATURES})
    det = r.choice(DETECTORS, n)
    for d in DETECTORS:
        df[f"det_{d}"] = (det == d).astype(float)
    p = 1 / (1 + np.exp(-(signal * df[FEATURES[0]] - 0.4)))
    y = (r.random(n) < p).astype(int)
    df = df.assign(instrument=r.choice(["AAA", "BBB"], n), interval="1h", asset_class="crypto", detector=det,
                   candidate_id=[f"c{i}" for i in range(n)], t=t, exit_at=t + r.integers(3600, 86400, n), y=y,
                   r=np.where(y == 1, 1.5, -1.0) - 0.1, outcome=np.where(y == 1, "target", "stop"))
    return df


# ---------------------------------------------------------------- leakage / causality
def test_bar_features_are_causal():
    b = bars()
    base = bar_features(b)
    k = 400
    future = b[:k] + [Bar(x.start, x.duration, x.open * 3, x.high * 3, x.low * 3, x.close * 3, x.volume * 9) for x in b[k:]]
    pert = bar_features(future)
    idx = base.index[:k]
    pd.testing.assert_frame_equal(base.loc[idx], pert.loc[idx])


def test_features_indexed_by_bar_end():
    b = bars(300)
    assert bar_features(b).index[0] == b[0].start + b[0].duration


# ---------------------------------------------------------------- purging
def test_walk_forward_purge_and_embargo():
    df = synth()
    t, e = df.t.to_numpy(), df.exit_at.to_numpy()
    n = 0
    for _, tr, te in walk_forward_splits(t, e, n_folds=5, embargo=86400):
        n += 1
        t0 = t[te].min()
        assert e[tr].max() < t0 - 86400            # every train label resolved before test start - embargo
        assert not set(tr) & set(te)
        f, c, cf = inner_split(t, e, tr)
        assert e[f].max() < t[c].min() - 86400 and e[c].max() < t[cf].min() - 86400
    assert n >= 3


def test_walk_forward_rejects_unsorted():
    with pytest.raises(ValueError):
        list(walk_forward_splits(np.array([2, 1]), np.array([3, 3])))


# ---------------------------------------------------------------- determinism
def test_training_is_deterministic():
    df = synth()
    a, b = run_training(df), run_training(df)
    sa = a["groups"]["crypto-1h"]["variants"]["hgb_conformal"]
    sb = b["groups"]["crypto-1h"]["variants"]["hgb_conformal"]
    assert json.dumps(sa, sort_keys=True, default=str) == json.dumps(sb, sort_keys=True, default=str)


def test_noise_is_not_eligible_and_signal_learns():
    noise = run_training(synth(signal=0.0))["groups"]["crypto-1h"]
    assert not R.is_eligible(noise["gates"])          # shadow_weeks alone blocks offline eligibility
    sig = run_training(synth(n=3000, signal=2.0))["groups"]["crypto-1h"]["variants"]["hgb_conformal"]
    assert sig["auc"] > 0.7 and sig["brier_skill"] > 0


# ---------------------------------------------------------------- calibration + conformal
def test_calibrator_refuses_in_sample_times():
    r = np.random.default_rng(0)
    s = r.random(500)
    c = fit_calibrator(s, (r.random(500) < s).astype(int), fitted_through=1000)
    assert c.kind == "isotonic"
    with pytest.raises(LookupError):
        c.apply(0.5, observation_time=1000)
    assert 0 < c.apply(0.5, observation_time=1001) < 1


def test_conformal_marginal_coverage():
    r = np.random.default_rng(3)
    p = r.random(4000)
    y = (r.random(4000) < p).astype(int)
    cf = fit_conformal(p[:2000], y[:2000], alpha=0.2)
    sets = cf.sets(p[2000:])
    cover = np.mean([yy in s for yy, s in zip(y[2000:], sets)])
    assert cover >= 0.78
    assert cf.take_mask(np.array([0.999]))[0] and not cf.take_mask(np.array([0.5]))[0]


# ---------------------------------------------------------------- registry gating
def _out(passed: bool):
    g = [{"gate": "x", "passed": passed, "value": 1, "threshold": "1"}]
    return {"gates": g, "variants": {"hgb_conformal": {"n_oos": 10, "dsr": {"dsr": 0.1}}}, "pbo": {"pbo": 0.2}}


def test_registry_gating_and_loading(tmp_path):
    from atlas.models.predict import ModelRegistry
    df = synth()
    model = fit_final(df, "crypto", "1h")
    meta = {"as_of": None, "series": [{"instrument": "AAA", "interval": "1h", "asset_class": "crypto", "providers": ["x"],
                                       "n_bars": 1, "n_rows": 1, "sha256": "ab" * 32}]}
    bad = R.register("crypto-1h", _out(False), meta, model, path=tmp_path)
    assert bad["status"] == "not_eligible"
    reg = ModelRegistry()
    assert R.load_eligible(reg, path=tmp_path) == []
    meta2 = {**meta, "series": [{**meta["series"][0], "sha256": "cd" * 32}]}
    good = R.register("crypto-1h", _out(True), meta2, model, path=tmp_path)
    assert good["status"] == "eligible"
    assert R.load_eligible(reg, path=tmp_path) == [good["version"]]
    assert bad["version"] not in reg.versions()
    again = R.register("crypto-1h", _out(True), meta2, model, path=tmp_path)   # immutable / idempotent
    assert again["created_at"] == good["created_at"]
    assert (tmp_path / good["version"] / "model_card.md").read_text().startswith("# Model card")
    assert R.get("../etc", path=tmp_path) is None


# ---------------------------------------------------------------- drift
def test_psi_and_adwin():
    r = np.random.default_rng(0)
    a = pd.DataFrame({"x": r.normal(size=2000)})
    ref = reference(a, ["x"])
    assert feature_psi(ref, pd.DataFrame({"x": r.normal(size=500)}))["status"] == "stable"
    assert feature_psi(ref, pd.DataFrame({"x": r.normal(2, 1, 500)}))["status"] == "significant"
    rep = adwin_report(np.r_[r.random(400) < 0.2, r.random(400) < 0.7].astype(float))
    assert rep["drift"] and 400 <= rep["detections"][0] <= 500
    assert not adwin_report((r.random(800) < 0.3).astype(float))["drift"]
    w = ADWIN()
    assert w.mean is None


# ---------------------------------------------------------------- retrieval
def test_bm25_ranking_and_citations():
    ps = split_passages("a.md", "# Purging\nembargo purged walk forward cv\n# Kelly\nfractional kelly sizing bet\n")
    ix = BM25Index(ps)
    hit = ix.search("embargo purge", 2)
    assert hit[0]["heading"] == "Purging" and hit[0]["cite"] == "a.md#L1-L2"
    assert ix.search("zzzz") == []


def test_repo_index_finds_ml_docs():
    ix = build_index(".")
    assert any(h["path"].startswith("docs/") for h in ix.search("meta-labeling triple barrier", 5))


# ---------------------------------------------------------------- shadow is forward-only
def test_shadow_only_observes_open_setups(tmp_path):
    from atlas.ml.refresh import shadow_step
    from atlas.models.shadow import ShadowCollector
    df = synth(400)
    model = fit_final(df, "crypto", "1h")
    df["direction"], df["entry"], df["stop"], df["target"] = "long", 100.0, 99.0, 102.0
    sc = ShadowCollector(tmp_path / "s.jsonl")
    man = {"version": "v", "status": "not_eligible", "fitted_through": 0}
    closed = df.head(5).copy()
    assert shadow_step(sc, man, model, closed) == {"observed": 0, "resolved": 0}
    op = closed.assign(y=-1, r=np.nan, exit_at=-1, outcome="open")
    assert shadow_step(sc, man, model, op)["observed"] == 5
    assert shadow_step(sc, man, model, op)["observed"] == 0           # dedup
    assert shadow_step(sc, man, model, closed)["resolved"] == 5
    assert shadow_step(sc, man, model, closed)["resolved"] == 0       # resolutions not duplicated
    assert all("model_not_eligible" in r["reasons"] for r in sc.records())


def test_api_ml_registry_readonly(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path))
    c = TestClient(app)
    r = c.get("/api/ml/registry").json()
    assert r["execution_permission"] == "none" and r["latest"] == []
    assert c.get("/api/ml/models/nope").status_code == 404
    assert c.post("/api/ml/registry").status_code == 405
    assert c.get("/api/ml/search", params={"q": "walk forward"}).status_code == 200
