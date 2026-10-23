"""Autonomy ladder evaluator (read-only, cannot promote), models overview + dashboard panel, weekly retrain-all job."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from founder_conftest import CONFIG_DIR
from mm_helpers import planted_bars
from atlas.control.policy import load_all
from atlas.mcp.trading import build_service
from atlas.models.quant.multi import KINDS, models_overview, registry_for, weekly_retrain_all
from atlas.risk.ladder import LadderEvaluator, evaluate_service


def series(days, mu, sd, seed=0):
    rng = np.random.default_rng(seed)
    v = 20_000 * np.exp(np.cumsum(rng.normal(mu, sd, days)))
    t0 = datetime(2026, 1, 1, 21, tzinfo=timezone.utc)
    return [[(t0 + timedelta(days=i)).isoformat(), float(x)] for i, x in enumerate(v)]


@pytest.fixture(scope="module")
def policy():
    return load_all(CONFIG_DIR).risk


def test_ladder_ready_with_strong_evidence(policy):
    eq = series(90, 0.002, 0.005)
    r = LadderEvaluator(policy).evaluate(eq, [100, 80, -30, 60], backtest_return_pct=(eq[-1][1] / eq[0][1] - 1) * 100 * 1.1)
    assert r["target_level"] == 2 and r["evidence_ready"], r["checks"]
    assert r["can_self_promote"] is False and r["live_locked"]


@pytest.mark.parametrize("kw,failing", [
    (dict(eq=series(30, 0.002, 0.005)), "paper_trading_days"),
    (dict(eq=series(90, 0.0, 0.02, seed=3)), "sharpe"),
    (dict(pnls=[10, -50]), "profit_factor"),
    (dict(bt=None), "backtest_divergence_pct"),
    (dict(breaches=1), "unhandled_breaches"),
])
def test_ladder_gates_fail(policy, kw, failing):
    eq = kw.get("eq", series(90, 0.002, 0.005))
    bt = kw["bt"] if "bt" in kw else (eq[-1][1] / eq[0][1] - 1) * 100
    r = LadderEvaluator(policy).evaluate(eq, kw.get("pnls", [100, -20]), bt, kw.get("breaches", 0))
    assert not r["evidence_ready"] and failing in [c["name"] for c in r["checks"] if not c["passed"]]
    if kw.get("breaches"):
        assert r["demotion_recommended"]


def test_evaluator_cannot_change_autonomy(tmp_path):
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    before = hashlib.sha256((CONFIG_DIR / "risk_policy.yaml").read_bytes()).hexdigest()
    r = evaluate_service(svc)
    assert hashlib.sha256((CONFIG_DIR / "risk_policy.yaml").read_bytes()).hexdigest() == before
    assert svc.cfg.risk.autonomy.level == 1 and r["current_level"] == 1
    assert not any(hasattr(LadderEvaluator, n) for n in ("promote", "set_level", "write_policy"))
    assert svc.store.get("autonomy_readiness")["target_level"] == 2
    assert svc.audit.entries("autonomy.evaluated")[0]["actor"] == "autonomy_evaluator"


@pytest.fixture(scope="module")
def trained_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("models")
    bars = {"core_etf": {"SPY": planted_bars(900, seed=1)}, "crypto": {"BTC": planted_bars(900, seed=2, freq="D", vol=0.03)}}
    rng = np.random.default_rng(0)
    import pandas as pd
    fills = pd.DataFrame({"half_spread_bps": rng.uniform(1, 10, 300), "daily_vol_bps": rng.uniform(50, 300, 300), "participation": rng.uniform(0, 0.05, 300)})
    fills["realised_bps"] = 1 + fills.half_spread_bps + 0.5 * fills.daily_vol_bps * np.sqrt(fills.participation)
    out = weekly_retrain_all(root, bars, bars["core_etf"]["SPY"]["close"], fills=fills)
    return root, out


def test_weekly_retrain_all_creates_challengers_for_each_kind(trained_root):
    root, out = trained_root
    assert {"scorers", "regime", "vol", "cost", "execution", "portfolio"} <= set(out)
    ov = {m["kind"]: m for m in models_overview(root)}
    assert set(ov) == set(KINDS)
    for k in ("scorer_core_etf", "scorer_crypto", "regime", "vol", "cost"):
        assert ov[k]["status"] == "shadow" and ov[k]["challenger"] and ov[k]["champion"] is None and ov[k]["last_retrain"]
        assert (root / ov[k]["card"]).exists()
    assert ov["anomaly"]["status"] == "not trained" and ov["scorer_active_equity"]["status"] == "not trained"


def test_dashboard_models_panel(trained_root):
    from test_dashboard import free_port, req
    from atlas.ops.dashboard.server import serve_in_thread
    root, _ = trained_root
    svc = build_service(CONFIG_DIR); svc.heartbeat(); svc.models_root = str(root)
    evaluate_service(svc)
    port = free_port(); srv = serve_in_thread(svc, port, None)
    try:
        c, b, _ = req(port, "/api/models")
        d = json.loads(b)
        assert c == 200 and len(d["models"]) == len(KINDS) and d["autonomy"]["can_self_promote"] is False
        assert b"ladderchecks" in req(port, "/")[1]
    finally:
        srv.shutdown(); srv.server_close()


def test_runner_learning_loop_and_drift_jobs(tmp_path):
    from atlas.ops.runner import build_jobs
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    js = build_jobs(svc, str(CONFIG_DIR), str(tmp_path / "rep"), str(tmp_path / "models"))
    assert {"learning_loop", "model_drift_report", "daily_summary", "kill_switch_drill"} <= set(js.jobs)
    js.jobs["learning_loop"][1](datetime.now(timezone.utc))
    ov = {m["kind"]: m for m in models_overview(tmp_path / "models")}
    assert ov["scorer_core_etf"]["status"] == "shadow" and ov["regime"]["status"] == "shadow"
    assert svc.store.get("autonomy_readiness")
    js.jobs["model_drift_report"][1](datetime.now(timezone.utc))
