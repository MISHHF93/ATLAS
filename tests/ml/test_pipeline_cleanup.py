"""Focused checks for the ML pipeline cleanup. No training, no gate changes."""
from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

from atlas.ai.ml import registry as R
from atlas.ai.ml.refresh import group_providers
from atlas.ai.ml.train import GATES
from atlas.ai.prediction import roll as RL


def test_latest_open_setup_is_a_training_row_or_absent():
    from atlas.features.price_action.bars import Bar
    from atlas.ai.ml.dataset import FEATURES, SeriesData, build_rows, latest_open_setup

    bars = []
    px = 100.0
    for i in range(240):
        o, px = px, px * (1.001 if i % 17 < 8 else 0.999)
        bars.append(Bar(1_700_000_000 + i * 900, 900, o, max(o, px) * 1.002, min(o, px) * 0.998, px, 50.0 + i))
    got = latest_open_setup(bars, "BTCUSDT", "15m", "crypto")
    df = build_rows(SeriesData("BTCUSDT", "15m", "crypto", bars), include_open=True)
    open_rows = df.loc[df["y"] < 0] if len(df) and "y" in df.columns else df
    if got is None:
        assert len(open_rows) == 0
        return
    last = open_rows.sort_values(["t", "candidate_id"]).iloc[-1]
    assert int(got["t"]) == int(last["t"]) and got["candidate_id"] == last["candidate_id"]
    assert got["detector"] == last["detector"]
    assert set(FEATURES) <= set(got)


def test_promotion_gates_are_unchanged():
    assert GATES == {"min_oos": 200, "min_dsr": 0.95, "max_pbo": 0.5, "min_shadow_weeks": 4}


def test_code_sha_runs_git_at_the_repo_root(monkeypatch):
    calls = []

    class Done:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake(argv, **kw):
        calls.append((argv, kw.get("cwd")))
        if argv[1] == "rev-parse":
            return Done("abcdef1234567890\n")
        return Done(" M src/atlas/ai/ml/registry.py\n")

    monkeypatch.setattr(R.subprocess, "run", fake)
    assert R.code_sha() == "abcdef1234567890-dirty"
    cwd = calls[0][1]
    assert cwd == R.repo_root()
    assert (cwd / "pyproject.toml").is_file()
    assert (cwd / "src" / "atlas" / "ai" / "ml").is_dir()


def test_dirty_tree_does_not_reuse_the_clean_version(tmp_path, monkeypatch):
    meta = {"as_of": 1, "series": [{
        "instrument": "AAA", "interval": "1h", "asset_class": "crypto", "providers": [None],
        "n_bars": 1, "n_rows": 1, "sha256": "ab" * 32,
    }]}
    out = {"gates": [{"gate": "n_oos", "passed": False, "value": 1, "threshold": ">= 200"}],
           "variants": {"hgb_conformal": {"n_oos": 1}}, "pbo": {"pbo": 0.2}}
    model = SimpleNamespace(calibrator=SimpleNamespace(kind="platt", fitted_through=0), conformal=SimpleNamespace(qhat=0.2))
    monkeypatch.setattr(R, "code_sha", lambda: "abcdef1234567890")
    clean = R.register("crypto-1h", out, meta, model, path=tmp_path)
    monkeypatch.setattr(R, "code_sha", lambda: "abcdef1234567890-dirty")
    dirty = R.register("crypto-1h", out, meta, model, path=tmp_path)
    assert clean["version"] != dirty["version"]
    assert dirty["version"].endswith("abcdef1-dirty")
    assert clean["status"] == "not_eligible" and dirty["status"] == "not_eligible"
    card = (tmp_path / clean["version"] / "model_card.md").read_text()
    assert "| none |" in card
    stored = json.loads((tmp_path / clean["version"] / "manifest.json").read_text())
    assert stored["series"][0]["providers"] == []


def test_reconcile_marks_missing_versions_and_does_not_promote(tmp_path):
    report = {"groups": {
        "crypto-15m": {"version": "atlas-meta-crypto-15m-deadbeef01-d63417b", "status": "not_eligible",
                       "providers": [], "gates": [{"gate": "brier_beats_base_rate", "passed": False}]},
        "equity-1h": {"version": "atlas-meta-equity-1h-aaaaaaaaaa-d63417b", "status": "eligible", "providers": [None]},
    }}
    out = R.reconcile_refresh(report, path=tmp_path)
    crypto = out["groups"]["crypto-15m"]
    equity = out["groups"]["equity-1h"]
    assert crypto["artifact"] == "missing" and crypto["status"] == "not_eligible"
    assert equity["artifact"] == "missing" and equity["status"] == "not_eligible"
    assert equity["status"] != "eligible"
    assert crypto["provider_status"] == "none" and equity["provider_status"] == "none"
    assert out["execution_permission"] == "none"
    assert GATES["min_shadow_weeks"] == 4


def test_group_providers_ignores_nulls():
    meta = {"series": [
        {"asset_class": "equity", "interval": "1h", "providers": [None]},
        {"asset_class": "crypto", "interval": "15m", "providers": ["coinbase", None, "kraken"]},
        {"asset_class": "gold", "interval": "1d", "providers": []},
    ]}
    assert group_providers(meta, "equity-1h") == []
    assert group_providers(meta, "crypto-15m") == ["coinbase", "kraken"]
    assert group_providers(meta, "gold-1d") == []


def test_roll_supervise_times_out_and_logs(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    rc = RL.supervise(cmd, timeout_s=0.4, root=tmp_path, iteration=3, heartbeat_s=0.05)
    assert rc == RL.TIMED_OUT
    lines = [json.loads(ln) for ln in (tmp_path / "roll.jsonl").read_text().splitlines()]
    events = [ln["event"] for ln in lines]
    assert events[0] == "cycle_start"
    assert "cycle_timeout" in events
    assert all(ln["execution_permission"] == "none" for ln in lines)
    status = json.loads((tmp_path / "roll_status.json").read_text())
    assert status["state"] == "timeout"
    sup = json.loads((tmp_path / "roll_supervisor.json").read_text())
    assert sup["state"] == "timeout" and sup["iteration"] == 3


def test_roll_supervise_records_a_clean_exit(tmp_path):
    cmd = [sys.executable, "-c", "print('ok')"]
    assert RL.supervise(cmd, timeout_s=5, root=tmp_path, iteration=1, heartbeat_s=0.05) == 0
    events = [json.loads(ln)["event"] for ln in (tmp_path / "roll.jsonl").read_text().splitlines()]
    assert events == ["cycle_start", "cycle_done"]


def test_roll_heartbeat_updates_while_running(tmp_path):
    hb = RL.Heartbeat(root=tmp_path, interval=0.05)
    hb.start()
    time.sleep(0.15)
    hb.update(phase="crypto-1m")
    first = json.loads((tmp_path / "roll_status.json").read_text())
    time.sleep(0.15)
    second = json.loads((tmp_path / "roll_status.json").read_text())
    hb.stop(state="idle")
    assert first["phase"] == "crypto-1m"
    assert second["heartbeat_at"] >= first["heartbeat_at"]
    done = json.loads((tmp_path / "roll_status.json").read_text())
    assert done["state"] == "idle" and done["execution_permission"] == "none"
