"""Native ML contract, ACI flag, and shadow-week count. No training."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from atlas.ai.ml.aci_eval import evaluate_aci_vs_split
from atlas.ai.ml.aci_serve import live_take, note_resolved
from atlas.ai.ml.contract_v1 import SCHEMA_VERSION, contract_index, monitor_payload
from atlas.ai.ml.serve_config import aci_enabled
from atlas.ai.ml.shadow_track import observe_open_setup, shadow_weeks_count
from atlas.ai.ml.train import GATES, gates
from atlas.ai.models.shadow import ShadowCollector


def test_aci_flag_defaults_off_and_empty_buffer_abstains(monkeypatch, tmp_path):
    assert aci_enabled() is False
    assert contract_index()["aci_default_off"] is True
    monkeypatch.setenv("ATLAS_ML_ACI", "1")
    monkeypatch.setenv("ATLAS_ML_ACI_STATE", str(tmp_path / "aci.json"))
    take, info = live_take(0.8)
    assert take is False and info["enabled"] is True and info["n_scores"] == 0
    assert note_resolved(0.8, 1)["n_resolved"] == 1
    take2, info2 = live_take(0.8)
    assert info2["n_scores"] == 1
    assert take2 in (True, False)


def test_aci_eval_does_not_enable_the_flag():
    import numpy as np
    rng = np.random.default_rng(1)
    n = 200
    t = np.arange(n) * 900
    p = np.clip(rng.normal(0.4, 0.05, n), 0.05, 0.95)
    y = (rng.random(n) < p).astype(int)
    rep = evaluate_aci_vs_split(t, t + 3600, p, y)
    assert rep["status"] == "ok" and rep["enable_aci"] is False
    assert rep["execution_permission"] == "none"
    assert 0.0 <= rep["aci_coverage"] <= 1.0
    assert aci_enabled() is False


def test_shadow_weeks_need_a_resolved_outcome_and_do_not_skip_other_gates(tmp_path):
    path = tmp_path / "shadow.jsonl"
    sc = ShadowCollector(path)
    for week_ts, outcome in ((1_704_067_200, "target"), (1_704_672_000, None)):
        cand = SimpleNamespace(candidate_id=f"c{week_ts}", instrument="BTCUSDT", detector="wick_reversal",
                               direction="long", detected_at=week_ts, entry_reference=100.0, proposed_stop=99.0,
                               proposed_target=102.0)
        sc.observe(candidate=cand, decision="proposal_rejected", reasons=["shadow_only_not_an_order"], probability=0.6)
        if outcome:
            sc.resolve(f"c{week_ts}", outcome=outcome, r_multiple=0.4, exit_at=week_ts + 3600)
    assert shadow_weeks_count(path) == 1
    out = {"variants": {"hgb_conformal": {"n_oos": 10, "brier_skill": -0.2, "logloss": 0.9, "logloss_baseline": 0.5,
                                          "dsr": {"dsr": 0.2}}}, "pbo": {"pbo": 0.8}}
    rows = gates(out, shadow_weeks=shadow_weeks_count(path))
    by = {g["gate"]: g["passed"] for g in rows}
    assert by["shadow_weeks"] is False
    rows4 = gates(out, shadow_weeks=4)
    by4 = {g["gate"]: g["passed"] for g in rows4}
    assert by4["shadow_weeks"] is True and by4["brier_beats_base_rate"] is False
    assert GATES == {"min_oos": 200, "min_dsr": 0.95, "max_pbo": 0.5, "min_shadow_weeks": 4}


def test_observe_open_setup_dedups(tmp_path):
    row = {"candidate_id": "s1", "instrument": "BTCUSDT", "detector": "wick_reversal", "direction": "long",
           "t": 1_700_000_000, "entry": 100.0, "stop": 99.0, "target": 102.0}
    assert observe_open_setup(row, model_version="v", probability=0.6, expected_value_r=0.1, take=True, path=tmp_path / "s.jsonl")
    assert not observe_open_setup(row, model_version="v", probability=0.6, expected_value_r=0.1, take=True, path=tmp_path / "s.jsonl")
    assert shadow_weeks_count(tmp_path / "s.jsonl") == 0


def test_plan_does_not_train():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ml_public_ohlcv_retrain", Path("scripts/ml_public_ohlcv_retrain.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    body = mod.plan()
    assert body["will_train"] is False and body["execution_permission"] == "none"
    assert body["gates"]["min_oos"] == 200
    assert body["providers"] == ["coinbase", "kraken"]
    assert len(body["universe"]) == 9


def test_v1_contract_route_and_empty_monitor():
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    client = TestClient(app)
    body = client.get("/api/ml/v1/contract").json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["execution_permission"] == "none"
    assert body["gates"]["max_pbo"] == 0.5
    roll = client.get("/api/ml/v1/roll").json()
    assert roll["execution_permission"] == "none" and "state" in roll
    mon = monitor_payload(path="/tmp/atlas-ml-empty-registry-does-not-exist")
    assert mon["oos_brier"] == [] and mon["execution_permission"] == "none"
    missing = client.get("/api/ml/v1/models/no-such-version")
    assert missing.status_code == 404


def test_live_aci_flag_abstains_without_history(monkeypatch, tmp_path):
    from atlas.ai.ml import live_intelligence as live
    from atlas.ai.ml.dataset import FEATURES
    live._MODEL_CACHE.clear()
    monkeypatch.setenv("ATLAS_ML_ACI", "1")
    monkeypatch.setenv("ATLAS_ML_ACI_STATE", str(tmp_path / "empty.json"))
    monkeypatch.setenv("ATLAS_ML_REGISTRY", str(tmp_path / "registry"))
    reg = tmp_path / "registry" / "crypto-15m"
    reg.mkdir(parents=True)
    (reg / "manifest.json").write_text(json.dumps({
        "version": "crypto-15m", "group": "crypto-15m", "status": "eligible",
        "created_at": "2026-10-20T00:00:00+00:00", "calibrator": "platt",
        "gates": [{"gate": "test", "passed": True}],
        "series": [{"instrument": "BTCUSDT", "asset_class": "crypto", "interval": "15m"}],
    }))

    def decide(frame, use_conformal=True):
        return {"p": [0.7], "take": [True], "ev_r": [0.2]}

    monkeypatch.setattr(live, "load_model", lambda version, path: SimpleNamespace(
        calibrator=SimpleNamespace(kind="platt", fitted_through=0), conformal=SimpleNamespace(qhat=0.2),
        win_r={}, loss_r={}, decide=decide))
    now = datetime(2026, 10, 21, 14, 30, tzinfo=ZoneInfo("UTC"))
    cutoff = now.timestamp()

    def bars(symbol, interval):
        return [SimpleNamespace(
            event_time=int(cutoff - (300 - i) * 900),
            open=100 + (i % 9), high=103 + (i % 9), low=98 + (i % 9), close=101 + (i % 9), volume=1000 + i,
        ) for i in range(300)]

    row = {name: 0.0 for name in FEATURES}
    row.update(detector="wick_reversal", direction="long", t=int(cutoff) - 900, candidate_id="aci-1",
               reward_risk=1.5, cost_r=0.02)
    monkeypatch.setattr(live, "latest_open_setup", lambda *a, **k: row)
    pred = live.generate_live_prediction(
        "BTC-USD", "15m", feed=SimpleNamespace(bars=bars), now=now, persist=False,
        stale_threshold_seconds=86400,
    )
    assert pred["prediction_status"] == "VALID"
    assert pred["aci"]["enabled"] is True
    assert pred["conformal_take"] is False
    assert pred["execution_permission"] == "none"
