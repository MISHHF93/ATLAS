from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import math
import sqlite3

import pytest

from atlas.marketdata import live_view
from atlas.models import live_observer

NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)


def bars(period=1):
    return [{"timestamp": (NOW - timedelta(seconds=(8-i)*period)).isoformat(),
             "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1}
            for i in range(8)]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(live_observer, "_SESSIONS", {})
    monkeypatch.setattr(live_view, "_CACHE", OrderedDict())
    monkeypatch.setattr(live_view, "artifact_store", lambda: None)
    monkeypatch.setattr(live_observer, "artifact_store", lambda: None)


def test_cached_forming_minute_does_not_become_training_target_without_new_observation(monkeypatch):
    rows = bars(60) + [{**bars(60)[-1], "timestamp": NOW.isoformat(), "close": 120, "high": 121}]
    received = NOW + timedelta(seconds=59)
    clock = [0.0]
    monkeypatch.setattr(live_view.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(live_view.public_quotes, "fetch_public_candles", lambda *a, **k: {
        "as_of": received.isoformat(), "candles": rows, "feed_source": "yahoo_chart_public"})
    first = live_view.live_view_snapshot("NVDA", sampling=True, now=received)
    assert first["active"]["online_observer"]["samples_learned"] == 0
    clock[0] = 2
    cached = live_view.live_view_snapshot("NVDA", sampling=True, now=NOW + timedelta(seconds=61))
    assert cached["active"]["candles"] == first["active"]["candles"]
    assert cached["active"]["online_observer"]["samples_learned"] == 0
    received = NOW + timedelta(seconds=62)
    clock[0] = 11
    observed_closed = live_view.live_view_snapshot("NVDA", sampling=True, now=received)
    assert observed_closed["active"]["online_observer"]["samples_learned"] == 1


def test_transport_pause_retains_weights_and_does_not_resolve_a_pending_prediction():
    rows = bars()
    first = live_observer.observe_public_bars("T", rows, now=NOW)
    later = {**rows[-1], "timestamp": NOW.isoformat(), "close": 120, "high": 121}
    paused = live_observer.observe_public_bars("T", rows + [later], now=NOW + timedelta(seconds=2), learning_allowed=False)
    assert paused["status"] == "paused"
    assert paused["samples_learned"] == first["samples_learned"] == 0
    resumed = live_observer.observe_public_bars("T", rows + [later], now=NOW + timedelta(seconds=2))
    assert resumed["samples_learned"] == 1
    for options in ({"bars": [], "now": NOW + timedelta(seconds=3)},
                    {"bars": rows + [later], "now": NOW + timedelta(seconds=40)},
                    {"bars": rows + [later], "now": NOW + timedelta(seconds=3), "learning_allowed": False}):
        result = live_observer.observe_public_bars("T", **options)
        assert result["samples_learned"] == 1
        assert result["weights"] == resumed["weights"]
        assert result["probability_up"] is None


def test_online_metrics_score_the_saved_forecast_before_update_and_do_not_recount():
    rows = bars()
    live_observer.observe_public_bars("M", rows, now=NOW)
    later = {**rows[-1], "timestamp": NOW.isoformat(), "close": 120, "high": 121}
    result = live_observer.observe_public_bars("M", rows + [later], now=NOW + timedelta(seconds=2))
    metrics = result["metrics"]
    assert metrics["samples_evaluated"] == 1
    assert metrics["brier_score"] == .25
    assert metrics["log_loss"] == pytest.approx(math.log(2))
    assert metrics["validated"] is False
    assert metrics["scope"] == "prequential_before_update"
    again = live_observer.observe_public_bars("M", rows + [later], now=NOW + timedelta(seconds=3))
    assert again["metrics"] == metrics


@pytest.mark.parametrize("change", [
    {"close": float("nan")}, {"high": 1}, {"volume": -1}, {"incomplete": True},
    {"timestamp": "bad"}, {"timestamp": "2026-10-22T14:59:58"},
])
def test_observer_validates_its_inputs_even_without_the_native_view(change):
    rows = bars()
    invalid = {**rows[-1], **change}
    result = live_observer.observe_public_bars("BAD", rows[:-1] + [invalid], now=NOW)
    assert result["rejected_bars"] == 1
    assert invalid not in result["candles"]
    assert all(math.isfinite(value) for value in result["weights"])


def test_older_snapshot_cannot_overwrite_the_newer_prediction():
    rows = bars()
    live_observer.observe_public_bars("OLD", rows, now=NOW)
    older = live_observer.observe_public_bars("OLD", rows[:-1], now=NOW)
    assert older["status"] == "out_of_order"
    assert older["prediction_at"] == rows[-1]["timestamp"]
    assert older["samples_learned"] == 0


def test_failed_atomic_commit_changes_neither_saved_fit_nor_artifacts(tmp_path, monkeypatch):
    from atlas.marketdata.live_artifacts import LiveArtifactStore
    store = LiveArtifactStore(tmp_path / "atomic.sqlite")
    monkeypatch.setattr(live_observer, "artifact_store", lambda: store)
    rows = bars()
    initial = live_observer.observe_public_bars("ATOMIC", rows, now=NOW)
    before = store.manifest()["counts"]
    checkpoint = store.restore("ATOMIC")
    with store.connect() as conn:
        conn.execute("CREATE TRIGGER fail_state BEFORE INSERT ON checkpoints BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    later = {**rows[-1], "timestamp": NOW.isoformat(), "close": 120, "high": 121}
    with pytest.raises(sqlite3.IntegrityError):
        live_observer.observe_public_bars("ATOMIC", rows + [later], now=NOW + timedelta(seconds=2))
    assert store.restore("ATOMIC") == checkpoint
    assert store.manifest()["counts"] == before
    assert live_observer._SESSIONS["ATOMIC"]["weights"] == initial["weights"]
    with store.connect() as conn:
        conn.execute("DROP TRIGGER fail_state")
    learned = live_observer.observe_public_bars("ATOMIC", rows + [later], now=NOW + timedelta(seconds=2))
    assert learned["samples_learned"] == 1
    live_observer._SESSIONS.clear()
    restored = live_observer.observe_public_bars("ATOMIC", [], now=NOW + timedelta(seconds=4))
    assert restored["samples_learned"] == 1
    assert restored["metrics"] == learned["metrics"]


def test_prediction_from_later_contaminated_inputs_is_skipped_after_recovery():
    rows = bars()
    live_observer.observe_public_bars("GAP", rows, now=NOW)
    rows[-1]["incomplete"] = True
    later = [{**rows[-2], "timestamp": (NOW + timedelta(seconds=i)).isoformat(),
              "close": 120+i, "high": 122+i} for i in range(5)]
    result = live_observer.observe_public_bars("GAP", rows + later, now=NOW + timedelta(seconds=6))
    assert result["samples_learned"] == 0
    assert result["skipped_outcomes"] == 1
    assert result["prediction_at"] == later[-1]["timestamp"]
    assert result["rejected_bars"] == 1
