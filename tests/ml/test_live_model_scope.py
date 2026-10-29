"""Live models must pass validation within their exact asset/timeframe/symbol scope."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from atlas.ai.ml import live_intelligence as live


def manifest(**changes):
    result = {
        "version": "test-v1", "group": "crypto-15m", "status": "eligible",
        "created_at": "2026-10-20T00:00:00+00:00",
        "gates": [{"gate": "validation", "passed": True}],
        "series": [{"instrument": "BTCUSDT", "asset_class": "crypto", "interval": "15m"}],
    }
    result.update(changes)
    return result


@pytest.fixture
def store(tmp_path, monkeypatch):
    loads = []

    def load_model(version, path):
        loads.append(version)
        return object()

    def write(value):
        directory = tmp_path / value["version"]
        directory.mkdir(exist_ok=True)
        (directory / "manifest.json").write_text(json.dumps(value), encoding="utf-8")

    monkeypatch.setattr(live, "load_model", load_model)
    monkeypatch.setattr(live, "_MODEL_CACHE", {})
    return tmp_path, write, loads


def test_exact_eligible_scoped_model_loads_and_caches_binary(store):
    path, write, loads = store
    write(manifest())
    first = live.load_cached_registered_model("crypto-15m", path, instrument="BTC-USD")
    second = live.load_cached_registered_model("crypto-15m", path, instrument="BTCUSDT")
    assert first[0]["version"] == "test-v1" and first[2] is None
    assert first[1] is second[1]
    assert loads == ["test-v1"]


@pytest.mark.parametrize("changes", [
    {"status": "not_eligible"},
    {"gates": []},
    {"gates": [{"gate": "validation", "passed": False}]},
    {"gates": [{"gate": "validation", "passed": "true"}]},
    {"gates": [None]},
    {"gates": None},
    {"series": []},
    {"series": None},
    {"series": [{"instrument": "ETHUSDT", "asset_class": "crypto", "interval": "15m"}]},
    {"series": [{"instrument": "BTCUSDT", "asset_class": "equity", "interval": "15m"}]},
    {"series": [{"instrument": "BTCUSDT", "asset_class": "crypto", "interval": "1h"}]},
])
def test_live_loader_rejects_unvalidated_or_out_of_scope_manifests(store, changes):
    path, write, loads = store
    write(manifest(**changes))
    man, model, error = live.load_cached_registered_model("crypto-15m", path, instrument="BTCUSDT")
    assert man is None and model is None and "No eligible model" in error
    assert loads == []


@pytest.mark.parametrize("group,instrument", [
    ("crypto-1h", "BTCUSDT"),
    ("equity-15m", "SPY"),
    ("crypto-15m", "ETHUSDT"),
    ("crypto-15m", None),
])
def test_live_loader_does_not_fall_back_to_other_markets_or_missing_scope(store, group, instrument):
    path, write, loads = store
    write(manifest())
    man, model, error = live.load_cached_registered_model(group, path, instrument=instrument)
    assert man is None and model is None and error
    assert loads == []


@pytest.mark.parametrize("change", ["gates", "status", "series", "withdrawn"])
def test_cached_model_cannot_bypass_revised_eligibility_or_scope(store, change):
    path, write, loads = store
    current = manifest()
    write(current)
    assert live.load_cached_registered_model("crypto-15m", path, instrument="BTCUSDT")[1] is not None
    if change == "withdrawn":
        (path / "test-v1" / "manifest.json").unlink()
    else:
        revised = deepcopy(current)
        if change == "gates":
            revised["gates"][0]["passed"] = False
        elif change == "status":
            revised["status"] = "not_eligible"
        else:
            revised["series"][0]["instrument"] = "ETHUSDT"
        write(revised)
    man, model, error = live.load_cached_registered_model("crypto-15m", path, instrument="BTCUSDT")
    assert man is None and model is None and error
    assert loads == ["test-v1"]


def test_newer_rejected_model_does_not_replace_eligible_scoped_model(store):
    path, write, loads = store
    write(manifest())
    write(manifest(version="test-v2", created_at="2026-10-21T00:00:00+00:00", status="not_eligible"))
    man, model, error = live.load_cached_registered_model("crypto-15m", path, instrument="BTCUSDT")
    assert man["version"] == "test-v1" and model is not None and error is None
    assert loads == ["test-v1"]


def test_prediction_health_reports_registered_but_rejected_models_as_unavailable(store):
    path, write, _ = store
    write(manifest(status="not_eligible"))
    result = live.get_prediction_health(reg_path=path)
    assert result["registered_models_count"] == 1
    assert result["eligible_models_count"] == 0
    assert result["health_classification"] == "UNAVAILABLE"
    assert result["active_model_version"] is None
    assert result["execution_permission"] == "none"
