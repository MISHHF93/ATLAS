"""Pass 5 intel layer: lab reproducibility, causal regimes, portfolio VaR, track separation, grounded assistant,
memory no-look-ahead + attribution, microstructure gating, Four-Box boxes, API wiring."""
import math

import numpy as np
import pytest

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.replay import ReplayTrade


def _bars(n=900, seed=3, dur=900, t0=1_760_000_000):
    rng = np.random.default_rng(seed)
    px, out = 2000.0, []
    for i in range(n):
        o = px; c = o * math.exp(rng.normal(0, 0.003)); h = max(o, c) * (1 + abs(rng.normal(0, 0.0015))); l_ = min(o, c) * (1 - abs(rng.normal(0, 0.0015)))
        out.append(Bar(t0 + i * dur, dur, o, h, l_, c, float(rng.integers(100, 1000)))); px = c
    return out


def test_bootstrap_seeded_and_lab_report_id_reproducible(tmp_path, monkeypatch):
    from atlas.intel.lab import bootstrap_mean_ci, list_runs, run_experiment
    x = np.random.default_rng(0).normal(0.1, 1, 200)
    assert bootstrap_mean_ci(x, seed=1) == bootstrap_mean_ci(x, seed=1)
    assert bootstrap_mean_ci(x[:3]) is None
    monkeypatch.setenv("ATLAS_LAB_DIR", str(tmp_path))
    b = _bars()
    v = {"sfp_only": {"sfp": True}, "all": {"sfp": True, "gold_snapback": True}}
    r1 = run_experiment("GC", b, variants=v, n_boot=200, data_label="synthetic_fixture")
    r2 = run_experiment("GC", b, variants=v, n_boot=200, data_label="synthetic_fixture")
    assert r1["report_id"] == r2["report_id"] and r1["variants"] == r2["variants"]
    assert len(list_runs()) == 2 and (tmp_path / f"report_{r1['report_id']}.md").exists()
    for s in r1["variants"].values():
        means = [c["mean_r"] for c in s["cost_sensitivity"] if c["mean_r"] is not None]
        assert means == sorted(means, reverse=True)          # more cost never helps
    assert r1["execution_permission"] == "none"
    assert run_experiment("GC", [], record=False)["status"] == "no_data"


def test_regime_classifier_is_causal():
    from atlas.intel.regime import classify
    b = _bars(400)
    full = classify(b)
    part = classify(b[:250])
    assert full[:250] == part                                  # appending future bars never changes past labels
    assert full[0]["label"] == "warmup" and full[-1]["label"] != "warmup"


def test_strategy_by_regime_groups():
    from atlas.intel.regime import strategy_by_regime
    labels = [{"t": 0, "label": "range/low"}, {"t": 100, "label": "trend_up/high"}]
    tr = [ReplayTrade("a", "sfp", "long", 50, 1, 0, 2, outcome="target", r_multiple=1.0),
          ReplayTrade("b", "sfp", "long", 150, 1, 0, 2, outcome="stop", r_multiple=-1.0),
          ReplayTrade("c", "sfp", "long", 160, 1, 0, 2, outcome="unfilled")]
    rows = {r["regime"]: r for r in strategy_by_regime(tr, labels)}
    assert rows["range/low"]["n"] == 1 and rows["trend_up/high"]["mean_r"] == -1.0


class _Feed:
    def __init__(self, series): self.s = series

    def bars(self, sym, iv):
        if sym not in self.s:
            raise KeyError(sym)
        return self.s[sym]


class _B:
    def __init__(self, t, c): self.event_time, self.close = t, c


def test_portfolio_var_and_stress():
    from atlas.intel.portfolio import report
    rng = np.random.default_rng(1)
    mk = lambda: [_B(86400 * i, 100 * math.exp(np.cumsum(rng.normal(0, 0.01, 1))[0] + 0.001 * i)) for i in range(120)]  # noqa: E731
    f = _Feed({"GC": mk(), "SPY": mk()})
    pos = [{"instrument_id": "GC", "side": "buy", "notional_usd": "10000", "status": "open"},
           {"instrument_id": "ZZZ", "side": "sell", "notional_usd": "5000", "status": "open"}]
    r = report(f, pos, ["GC", "SPY"])
    assert r["exposure"]["gross_usd"] == 15000 and r["exposure"]["net_usd"] == 5000
    assert r["book"]["status"] == "partial" and r["book"]["unpriced_positions"] == ["ZZZ"]
    assert r["book"]["var95_usd"] is not None and r["book"]["cvar95_usd"] >= r["book"]["var95_usd"]
    assert any(s["kind"] == "hypothetical" for s in r["book"]["stress"])
    assert report(f, [], ["GC"])["book"]["status"] == "no_open_positions"


def test_tracks_enforced_separately():
    from atlas.control.engine import ActionableControlPlaneEngine
    from atlas.control.tracks import probe, rulebooks
    rb = {r["field"]: r for r in rulebooks(ActionableControlPlaneEngine())["rows"]}
    assert rb["min_stop_distance_bps"]["competition"] == 25.0 and rb["min_stop_distance_bps"]["open_market"] == 30.0
    p = {x["id"]: x for x in probe()}
    tight = p["stop_28bps"]
    assert tight["competition"]["decision"] != "rejected_by_control_plane"
    assert tight["open_market"]["decision"] == "rejected_by_control_plane"
    assert any("min_stop_distance" in v for v in tight["open_market"]["violations"])
    assert p["stop_100bps"]["competition"]["notional_usd"] <= 50000 and p["stop_100bps"]["open_market"]["notional_usd"] <= 40000


def test_assistant_grounded_and_llm_disabled(monkeypatch, tmp_path):
    from atlas.intel import assistant as A
    for k in ("XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    r1 = A.ask("deflated sharpe ratio", lab_dir=str(tmp_path))
    r2 = A.ask("deflated sharpe ratio", lab_dir=str(tmp_path))
    assert r1["evidence"] and [e["id"] for e in r1["evidence"]] == [e["id"] for e in r2["evidence"]]
    ids = {e["id"] for e in r1["evidence"]}
    assert all(set(a["evidence"]) <= ids for a in r1["answer"])
    assert r1["llm"]["state"] == "disabled_no_key" and r1["llm"]["used"] is False
    none = A.ask("zzqqxxnotaword", lab_dir=str(tmp_path))
    assert none["status"] == "no_evidence" and none["answer"] == []


def test_memory_no_lookahead_and_attribution_sums():
    from atlas.intel.memory import analogues, attribution, build_memory
    tr = [ReplayTrade(f"c{i}", "sfp" if i % 2 else "orb", "long", 1000 * i, 1, 0, 2, exit_at=1000 * i + 500,
                      outcome="target" if i % 3 else "stop", r_multiple=1.0 if i % 3 else -1.0, features={"x": float(i)}) for i in range(30)]
    mem = build_memory(tr, [{"t": 0, "label": "range/low"}])
    a = analogues(mem, {"x": 10.0}, as_of=10_600, k=5)
    assert a["status"] == "ok" and a["n_eligible"] == 11       # only trades resolved by as_of
    assert all(int(r["candidate_id"][1:]) <= 10 for r in a["analogues"])
    at = attribution(mem)
    for key in ("by_detector", "by_regime", "by_direction", "by_hour_utc", "by_outcome"):
        assert abs(sum(b["total_r"] for b in at[key]) - at["total_r"]) < 1e-6
    assert analogues(mem, {"x": 1.0}, as_of=0)["status"] == "insufficient_history"


def test_microstructure_gating():
    from atlas.intel.microstructure import report
    r = report("GC", _bars(300))
    st = {m["metric"]: m for m in r["metrics"]}
    assert r["highest_tier"] == "bars"
    assert st["corwin_schultz_spread_bps"]["status"] == "ok"
    for m in ("vpin", "kyles_lambda", "order_flow_imbalance", "quoted_spread_bps"):
        assert st[m]["status"] == "gated" and "value" not in st[m]


def test_fourbox_boxes():
    from atlas.intel.fourbox import scan
    r = scan("BTCUSDT", _bars(500))
    boxes = {b["box"]: b for b in r["boxes"]}
    assert boxes["Event"]["status"] == "disabled" and boxes["Opening"]["status"] == "disabled"
    assert boxes["Breakout"]["detector"] == "dual_bollinger" and boxes["Anchor"]["detector"] == "wick_reversal"
    assert scan("SPY", _bars(500))["boxes"][0]["status"] == "enabled"


@pytest.mark.parametrize("url", ["/api/intel/regimes", "/api/intel/memory", "/api/intel/microstructure", "/api/intel/fourbox",
                                 "/api/intel/portfolio", "/api/intel/tracks", "/api/intel/holidays?symbol=GC",
                                 "/api/intel/assistant?q=risk+policy", "/api/intel/lab/runs"])
def test_intel_api_wired(url, monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_LAB_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    r = TestClient(app).get(url)
    assert r.status_code == 200, r.text
    assert r.json()["execution_permission"] == "none" if "holidays" not in url else r.json()["holiday_source"].startswith("exchange_calendars")
