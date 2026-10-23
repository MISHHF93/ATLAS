"""Multi-model foundation: PIT feature store, generic registry (digest-checked), model cards, PSI drift auto-demote."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from atlas.marketdata.pit.featurestore import FeatureStore
from atlas.models.quant.drift import DriftMonitor, psi
from atlas.models.quant.modelcard import ModelCard
from atlas.models.quant.registry import ModelRegistry, PromotionDenied

T = lambda d, h=21: datetime(2026, 1, d, h, tzinfo=timezone.utc)  # noqa: E731


def test_feature_store_point_in_time_and_revisions():
    fs = FeatureStore()
    fs.put("XIC", "fund", T(5), T(9), {"eps": 1.0})           # Q released on the 9th
    fs.put("XIC", "fund", T(5), T(20), {"eps": 1.2})          # revision published on the 20th
    assert fs.get("XIC", "fund", T(8)) is None                 # not yet knowable
    assert fs.get("XIC", "fund", T(10))["eps"] == 1.0
    assert fs.get("XIC", "fund", T(21))["eps"] == 1.2
    f = fs.frame("XIC", "fund", [T(8), T(10), T(21)])
    assert np.isnan(f["eps"].iloc[0]) and list(f["eps"].iloc[1:]) == [1.0, 1.2]
    with pytest.raises(ValueError):
        fs.put("XIC", "fund", T(9), T(5), {"eps": 0})


def test_feature_store_frame_with_lag():
    fs = FeatureStore()
    idx = pd.DatetimeIndex([T(d) for d in (5, 6, 7)])
    fs.put_frame("SPY", "tech", pd.DataFrame({"r": [1.0, 2.0, 3.0]}, index=idx), lag=timedelta(hours=1))
    f = fs.frame("SPY", "tech", [T(6, 21) , T(6, 22)])
    assert list(f["r"]) == [1.0, 2.0]   # the 6th's value only after its 1h publication lag


class Toy:
    def __init__(self, w=1.0):
        self.w = w

    def save(self, d):
        d.mkdir(parents=True, exist_ok=True); (d / "w.txt").write_text(str(self.w))

    @classmethod
    def load(cls, d):
        return cls(float((d / "w.txt").read_text()))


CARD = ModelCard("toy", "toy", "test", "tests", "anything real", "synthetic", ["x"], ["toy"], ["none"])


def test_registry_generic_card_digest(tmp_path):
    reg = ModelRegistry(tmp_path, model_cls=Toy, kind="toy")
    mid = reg.register(Toy(2.0), {"auc": 0.6}, "h", card=CARD, reference=pd.DataFrame({"x": np.arange(100.0)}))
    assert reg.load(mid).w == 2.0
    assert (tmp_path / mid / "model_card.md").read_text().startswith("# Model card: toy")
    (tmp_path / mid / "w.txt").write_text("9")
    with pytest.raises(PermissionError, match="changed"):
        reg.load(mid)
    with pytest.raises(ValueError, match="incomplete"):
        ModelCard("x", "x", "", "u", "o", "d", ["f"], ["l"], ["r"]).validate()


def test_psi_values():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 1, 5000)
    assert psi(a, rng.normal(0, 1, 5000)) < 0.02
    assert psi(a, rng.normal(1.0, 1, 5000)) > 0.25


def _champ(reg, w, ref):
    mid = reg.register(Toy(w), {}, reference=ref)
    reg.idx["models"][mid]["stage"] = "champion"
    return mid


def test_drift_auto_demotes_to_previous_champion(tmp_path):
    rng = np.random.default_rng(1)
    ref = pd.DataFrame({"x": rng.normal(0, 1, 2000)})
    reg = ModelRegistry(tmp_path, model_cls=Toy, kind="toy")
    m1 = _champ(reg, 1, ref)
    reg.idx["models"][m1]["stage"] = "archived"
    m2 = _champ(reg, 2, ref); reg.idx["previous_champion"] = m1
    mon = DriftMonitor(reg)
    assert mon.check(pd.DataFrame({"x": rng.normal(0, 1, 500)}))["status"] == "stable"
    r = mon.check(pd.DataFrame({"x": rng.normal(2, 1, 500)}))
    assert r["status"] == "drift" and r["restored"] == m1 and reg.champion == m1 and reg.stage(m2) == "archived"
    assert reg.summary()["last_drift"]["event"] in ("demote", "drift_check")


def test_demote_without_previous_leaves_no_champion_and_ai_cannot_demote(tmp_path):
    reg = ModelRegistry(tmp_path, model_cls=Toy, kind="toy")
    _champ(reg, 1, None)
    with pytest.raises(PromotionDenied):
        reg.demote("ai", "x")
    assert reg.demote("drift_monitor", "x") is None and reg.champion is None
