"""Live 15m signal service (milestone e): HOLD defaults, real-bar-only decisions, dedup, resolution against real outcomes, payload labels."""
from __future__ import annotations

import functools
import json
import math
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from atlas.ai.ml import contract_v1 as CV
from atlas.ai.ml import nowcast_xgb as N
from atlas.ai.ml import signal15 as S
from atlas.ai.ml import signal15_live as L
from atlas.ai.ml.dataset import SeriesData, build_rows
from atlas.features.price_action.bars import Bar

T0 = 1_790_000_000 // 900 * 900
NB = 3000


def synth(seed=7, n=NB):
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    for i in range(n):
        vol = 0.004 * (1 + 2 * (i % 300 < 60))
        o, px = px, px * math.exp(rng.normal(0, vol))
        out.append(Bar(T0 + i * 900, 900, o, max(o, px) * (1 + abs(rng.normal(0, vol))), min(o, px) * (1 - abs(rng.normal(0, vol))), px, float(rng.uniform(10, 100))))
    return out


BARS = synth()


class FakeStore:
    """Real-bar store stand-in: serves only the first ``k`` synthetic bars, like a feed that has not seen later bars yet."""

    def __init__(self, k):
        self.k = k

    def bars(self, instrument, interval, start=None, end=None, provider=None, confirmed_only=True):
        if interval != "15m" or provider != "coinbase":
            return []
        return [SimpleNamespace(event_time=b.start, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume)
                for b in BARS[: self.k] if (start is None or b.start >= start) and (end is None or b.start <= end)]


class TakeAll:
    features = ("m15_ret1",)
    conformal = SimpleNamespace(take_mask=lambda p: np.asarray(p) > 0.5)

    def decide(self, X):
        n = len(X)
        return {"p": np.full(n, 0.9), "ev_r": np.full(n, 0.5), "take": np.ones(n, bool), "size": np.zeros(n)}


def sd_of(k):
    return SeriesData("X", "15m", "crypto", BARS[:k], ["coinbase"])


def end_of(k):
    return BARS[k - 1].start + 900


@functools.lru_cache(maxsize=None)
def _detected():
    """Detection times of the real-barrier rows of the full series (one pass); candidates for the per-bar checks below."""
    full = build_rows(sd_of(NB), include_open=False, hold_bars=96)
    return full, sorted({int(t) for t in full["t"] if 2000 <= (int(t) - T0) // 900 <= 2700})


def _fresh(k):
    row = L._fresh_open_setup(sd_of(k), "crypto", end_of(k))
    return row


def find_k(want_setup, need_outcome=False):
    full, ts = _detected()
    keys = set(zip(full["t"], full["candidate_id"]))
    tset = set(ts)
    if want_setup:
        cands = [(t - T0) // 900 + j for t in ts for j in range(0, 4)]
    else:
        cands = [k for k in range(2000, 2200) if not any(end_of(k) - j * 900 in tset for j in range(0, 5))]
    for k in cands[:40]:
        row = _fresh(k)
        if (row is not None) != want_setup:
            continue
        if need_outcome and (int(row["t"]), row["candidate_id"]) not in keys:
            continue
        return k
    pytest.skip("synthetic series gave no matching bar")


@pytest.fixture
def rt(tmp_path):
    S.save_model(tmp_path / "models", "crypto_h96", TakeAll(), {"status": "not_eligible", "hold_bars": 96, "provider": "coinbase",
                 "gates": [{"gate": "shadow_weeks", "passed": False}], "shadow_weeks": 0})
    return tmp_path


def lines(p):
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_stale_last_bar_is_hold_and_never_a_signal(rt):
    k = find_k(True)
    out = L.tick_once(FakeStore(k), now=end_of(k) + 5 * 900, rt=rt, classes=("crypto",))
    assert out["n_actionable"] == 0
    for r in out["signals"]:
        assert r["action"] == "HOLD" and r["reasons"][0].startswith("stale_data") and r["setup"] is None
        assert r["execution_permission"] == "none" and r["predicted"] is True and r["advice"] is False


def test_no_real_bars_and_no_model_are_hold(tmp_path):
    out = L.tick_once(FakeStore(0), now=T0, rt=tmp_path, classes=("crypto",))
    assert {r["reasons"][0] for r in out["signals"]} == {"no_model"}
    S.save_model(tmp_path / "models", "crypto_h96", TakeAll(), {"status": "not_eligible"})
    out = L.tick_once(FakeStore(0), now=T0, rt=tmp_path, classes=("crypto",))
    assert {r["reasons"][0] for r in out["signals"]} == {"no_real_bars"}
    assert lines(tmp_path / "signals.jsonl") == []                     # no real decision bar -> nothing logged


def test_no_fresh_setup_is_hold(rt):
    k = find_k(False)
    out = L.tick_once(FakeStore(k), now=end_of(k) + 60, rt=rt, classes=("crypto",))
    assert {r["reasons"][0] for r in out["signals"]} == {"no_fresh_setup"}
    assert all(r["action"] == "HOLD" and r["decision_t"] == end_of(k) for r in out["signals"])


def test_setup_at_T_is_scored_logged_once_and_never_sized(rt):
    k = find_k(True)
    now = end_of(k) + 60
    out = L.tick_once(FakeStore(k), now=now, rt=rt, classes=("crypto",))
    assert out["n_actionable"] == 4 and out["n_logged_new"] == 4
    for r in out["signals"]:
        assert r["action"] in ("BUY", "SELL") and r["decision_t"] == end_of(k) and r["decision_t"] <= now and r["setup"]["detected_t"] <= r["decision_t"]
        assert r["setup"]["age_bars"] <= S.MIN_ENTRY_WINDOW
        assert r["setup"]["stop"] is not None and r["uncertainty"]["kind"] == "split_conformal"
        assert any("model_not_eligible" in x for x in r["reasons"])
        assert "size" not in r and "quantity" not in r and r["mode"] == "paper_shadow_only"
    again = L.tick_once(FakeStore(k), now=now + 30, rt=rt, classes=("crypto",))
    assert again["n_logged_new"] == 0
    assert len(lines(rt / "signals.jsonl")) == 4                        # one row per (instrument, T, model)


def test_resolution_uses_real_outcomes_only_after_the_barrier(rt):
    k = find_k(True, need_outcome=True)
    L.tick_once(FakeStore(k), now=end_of(k) + 60, rt=rt, classes=("crypto",))
    store = FakeStore(NB)
    assert L.resolve_signals(store, now=end_of(k) + 900, rt=rt) == 0   # barrier not reached yet: nothing is resolved early
    n = L.resolve_signals(store, now=BARS[-1].start + 10_000, rt=rt)
    assert n == 4
    assert L.resolve_signals(store, now=BARS[-1].start + 10_000, rt=rt) == 0   # idempotent
    res = lines(rt / "resolved.jsonl")
    assert all(r["y"] in (0, 1) and r["exit_at"] >= r["decision_t"] and r["outcome"] for r in res)
    s = L.shadow_summary(rt)
    assert s["n_resolved"] == 4 and s["live_gate_pass"] is None and s["gates"] == S.GATES
    assert s["gate_shadow_weeks_met"] is False                          # one decision bar is not four shadow weeks


def test_payload_is_labelled_read_only_and_flags_a_stale_tick(rt):
    k = find_k(True)
    L.tick_once(FakeStore(k), now=end_of(k) + 60, rt=rt, classes=("crypto",))
    L._atomic_json(rt / "heartbeat.json", {"state": "running", "pid": 1, "last_tick_at": 1, "ticks": 3})
    p = L.signals_payload(rt, limit=10)
    assert p["execution_permission"] == "none" and p["schema_version"] == CV.SCHEMA_VERSION
    assert "not advice" in p["label"].lower() and p["predicted"] is True and p["advice"] is False
    assert p["gates"] == S.GATES and p["tick"]["state"] == "stale"
    assert {m["model_key"] for m in p["models"]} == {"crypto_h96", "equity_h26"}
    assert next(m for m in p["models"] if m["model_key"] == "equity_h26")["status"] == "no_model"
    assert len(p["recent"]) <= 10 and len(p["latest"]) == 4
    assert "never_run" == L.signals_payload(rt / "empty")["tick"]["state"]


def test_nowcast_payload_reads_a_separate_ledger_and_marks_predictions(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    led = N.Ledger(path)
    pred = {"q10": -0.002, "q50": 0.0005, "q90": 0.003, "lo": -0.003, "hi": 0.004, "base_q": (-0.001, 0.0, 0.001)}
    led.issue("stocks_15m", "SPY", 1_000_900, "m1", 1, 500.0, pred, "gated", 1_000_000)
    led.add_score("stocks_15m", "SPY", 1_000_900, "m1", 1_001_000, 0.001, 0.0005, 0.0005, 0.001, 0.0002, 0.0003, 1, 1)
    led.close()
    p = L.nowcast_payload(path, limit=5)
    assert p["execution_permission"] == "none" and p["predicted"] is True and p["advice"] is False
    row = p["recent"][0]
    assert row["predicted"] is True and row["actual_return"] == 0.001 and row["covered"] is True and row["interval80_return"] == [-0.003, 0.004]
    assert p["groups"][0]["scored"] == 1
    assert L.nowcast_payload(str(tmp_path / "none.sqlite"))["recent"] == []


def test_gapfill_payload_is_labelled_and_read_only(tmp_path):
    p = L.gapfill_payload(str(tmp_path / "none.sqlite"))
    assert p["execution_permission"] == "none" and p["predicted"] is True and p["uses_future"] is True and p["n_predicted_seconds"] == 0
    path = tmp_path / "p.sqlite"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE pred_1s(x); CREATE TABLE calib(venue,bucket,n,q80_abs,mae_bridge,mae_carry,made_at);")
    c.execute("INSERT INTO calib VALUES('coinbase','1-2',10,0.001,0.0004,0.0006,1)")
    c.commit()
    c.close()
    assert L.gapfill_payload(str(path))["calibration"]["coinbase"]["1-2"]["n"] == 10


def test_contract_lists_the_new_endpoints_and_routes_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_SIGNAL15_ROOT", str(tmp_path))
    eps = CV.contract_index()["endpoints"]
    assert {"signals", "nowcast", "gapfill"} <= set(eps)
    from atlas.api.ml import ml_router
    paths = {r.path for r in ml_router.routes}
    assert {"/api/ml/v1/signals", "/api/ml/v1/nowcast", "/api/ml/v1/gapfill"} <= paths
    assert CV.signals_payload(None, 1)["execution_permission"] == "none"


def test_shadow_weeks_count_only_covered_time_not_clock_downtime(tmp_path):
    """Two logged bars four weeks apart (clock stopped in between) must not satisfy the four-shadow-week gate."""
    rows = [{"instrument": "BTCUSDT", "model_key": "crypto_h96", "decision_t": T0, "action": "HOLD", "setup": None},
            {"instrument": "BTCUSDT", "model_key": "crypto_h96", "decision_t": T0 + 29 * 86400, "action": "HOLD", "setup": None}]
    L._append_jsonl(tmp_path / "signals.jsonl", rows)
    s = L.shadow_summary(tmp_path)
    assert s["shadow_span_weeks"] > S.GATES["min_shadow_weeks"]
    assert s["shadow_weeks"] == 0.0 and s["gate_shadow_weeks_met"] is False
    assert s["shadow_longest_gap_h"] == 29 * 24


def test_shadow_weeks_accumulate_over_a_continuously_running_clock():
    ts = [T0 + i * 900 for i in range(4 * 7 * 96 + 1)]                 # four weeks of 15m decision bars, no gaps
    weeks, span, gap = L.covered_weeks(ts)
    assert weeks == pytest.approx(4.0) and span == pytest.approx(4.0) and gap == 900
    weeks2, _, _ = L.covered_weeks(ts[:96] + ts[-96:])                  # one day at each end, three-plus weeks down in between
    assert weeks2 < 1.0
    assert L.covered_weeks([]) == (0.0, 0.0, 0) and L.covered_weeks([T0, T0]) == (0.0, 0.0, 0)
