"""Chart prediction: live bars -> features (incl. VWAP) -> registered model -> probability, with honest labelling."""
from __future__ import annotations

import math
import numpy as np

from atlas.ai.ml import chart_prediction as cp
from atlas.ai.ml.features import BAR_FEATURES
from atlas.ai.ml.dataset import FEATURES
from atlas.features.price_action.bars import Bar


def bars(n=300, dur=900, t0=1_772_000_000 - 1_772_000_000 % 900, seed=3):
    rng = np.random.default_rng(seed)
    price, out = 100.0, []
    for i in range(n):
        o = price
        price *= 1 + rng.normal(0, 0.002)
        out.append(Bar(t0 + i * dur, dur, o, max(o, price) * 1.001, min(o, price) * 0.999, price, 100 + (i % 9) * 10))
    return out


class FakeModel:
    """Probability rises with distance above session VWAP for longs and falls for shorts (to prove VWAP features reach the model)."""
    features = tuple(BAR_FEATURES)

    def decide(self, X, use_conformal=True):
        d = X["dir_long"].to_numpy()
        v = np.nan_to_num(X["vwap_dist_atr"].to_numpy(float), nan=0.0)
        p = np.clip(0.5 + 0.08 * np.where(d > 0, v, -v), 0.05, 0.95)
        return {"p": p, "take": p > 0.55, "ev_r": 2 * p - 1}


def manifest(status="eligible", passed=True, group="crypto-15m", inst="BTCUSDT"):
    ac, _, iv = group.rpartition("-")
    return {"version": "v-test", "group": group, "status": status, "created_at": "2026-10-20T00:00:00+00:00",
            "gates": [{"gate": "n_oos", "passed": True}, {"gate": "shadow_weeks", "passed": passed}],
            "series": [{"instrument": inst, "asset_class": ac, "interval": iv}], "calibrator": "isotonic"}


def use(monkeypatch, *manifests):
    monkeypatch.setattr(cp, "list_models", lambda reg=None: list(manifests))
    monkeypatch.setattr(cp, "_model", lambda version, reg: FakeModel())


def test_asset_groups():
    assert cp.asset_group("BTCUSDT") == "crypto" and cp.asset_group("GC") == "gold" and cp.asset_group("AAPL") == "equity"
    assert cp.asset_group("GLD") == "gold" and cp.asset_group("EURUSD") == "equity"


def test_no_model_is_reported_not_fabricated(monkeypatch):
    use(monkeypatch)
    r = cp.model_prediction("BTCUSDT", "15m", bars())
    assert r["status"] == "no_model" and r["gate_status"] == "no_model" and r["label"] == "no model for this scope"
    assert "probability" not in r and "direction" not in r and r["execution_permission"] == "none"


def test_below_gate_model_is_shown_labelled_research(monkeypatch):
    use(monkeypatch, manifest(status="not_eligible", passed=False))
    r = cp.model_prediction("BTCUSDT", "15m", bars())
    assert r["status"] == "ok" and r["gate_status"] == "research_below_gate" and r["label"] == "research / below gate"
    assert r["model"]["gates_failed"] == ["shadow_weeks"] and r["model"]["uses_vwap"] is True
    assert 0 < r["probability"] < 1 and r["direction"] in {"up", "down", "neutral"} and r["execution_permission"] == "none"
    assert r["as_of_toronto"].endswith(("EST", "EDT")) and r["as_of_end"] == bars()[-1].start + 900


def test_gate_passed_model_wins_over_newer_below_gate(monkeypatch):
    newer = {**manifest(status="not_eligible", passed=False), "version": "newer"}
    older = {**manifest(), "version": "older"}
    use(monkeypatch, newer, older)
    r = cp.model_prediction("BTCUSDT", "15m", bars())
    assert r["gate_status"] == "gate_passed" and r["label"] == "model gate passed" and r["model"]["version"] == "older"


def test_scope_is_exact_instrument_asset_and_interval(monkeypatch):
    use(monkeypatch, manifest())
    assert cp.model_prediction("ETHUSDT", "15m", bars())["status"] == "no_model"
    assert cp.model_prediction("BTCUSDT", "1h", bars(dur=3600))["status"] == "no_model"
    assert cp.model_prediction("GC", "15m", bars())["status"] == "no_model"


def test_gold_uses_its_own_group(monkeypatch):
    use(monkeypatch, manifest(group="gold-15m", inst="GC"))
    r = cp.model_prediction("GC", "15m", bars())
    assert r["status"] == "ok" and r["model"]["group"] == "gold-15m"


def test_vwap_features_reach_the_model_and_direction_follows_them(monkeypatch):
    use(monkeypatch, manifest())
    up = bars()
    # push the last closed bar well above its session VWAP -> longs score higher than shorts
    k = up[-1]
    up[-1] = Bar(k.start, k.duration, k.open, k.close * 1.02, k.low, k.close * 1.02, k.volume)
    r = cp.model_prediction("BTCUSDT", "15m", up)
    assert r["p_long"] > r["p_short"] and r["direction"] == "up"
    dn = bars()
    k = dn[-1]
    dn[-1] = Bar(k.start, k.duration, k.open, k.high, k.close * 0.98, k.close * 0.98, k.volume)
    r2 = cp.model_prediction("BTCUSDT", "15m", dn)
    assert r2["p_short"] > r2["p_long"] and r2["direction"] == "down"


def test_refreshes_on_every_new_bar(monkeypatch):
    use(monkeypatch, manifest())
    b = bars(310)
    a, c = cp.model_prediction("BTCUSDT", "15m", b[:-1]), cp.model_prediction("BTCUSDT", "15m", b)
    assert c["as_of_bar"] == a["as_of_bar"] + 900


def test_short_history_and_missing_binary_are_honest(monkeypatch):
    use(monkeypatch, manifest())
    assert cp.model_prediction("BTCUSDT", "15m", bars(30))["status"] == "insufficient_history"
    monkeypatch.setattr(cp, "_model", lambda v, r: None)
    assert cp.model_prediction("BTCUSDT", "15m", bars())["status"] == "model_unavailable"


def test_nan_vwap_is_kept_nan_for_daily_bars(monkeypatch):
    use(monkeypatch, manifest(group="equity-1d", inst="SPY"))
    r = cp.model_prediction("SPY", "1d", bars(300, dur=86400))
    assert r["status"] == "ok" and math.isfinite(r["probability"])


def test_feature_contract_matches_training_columns():
    assert set(BAR_FEATURES) <= set(FEATURES)
