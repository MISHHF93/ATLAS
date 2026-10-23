"""Data-use admission fails closed without altering display or learned state."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from atlas.marketdata import data_rights, live_view, public_quotes, public_stream
from atlas.models import live_observer


NOW = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_ambient_permission(monkeypatch):
    # Exclude this module from the legacy mock-grant fixture. Even a developer's
    # genuine local policy must not influence these admission checks.
    monkeypatch.delenv(data_rights.POLICY_ENV, raising=False)
    monkeypatch.setattr(public_quotes, "_get_json", lambda *a, **k: pytest.fail("Unexpected HTTP request"))


def write_policy(tmp_path, monkeypatch, *, updates=None, grants=None):
    evidence = tmp_path / "test_permission.txt"
    evidence.write_text("TEST DOUBLE ONLY: explicit written permission for synthetic test inputs.", encoding="utf-8")
    grant = {
        "grant_id": "synthetic-test-permission:v1",
        "provider_id": "coinbase_exchange_public",
        "symbols": ["BTC-USD"],
        "resolutions_seconds": [1, 60],
        "allowed_uses": ["training", "retention"],
        "license_ref": "internal:synthetic-test-only",
        "reviewed_by": "test reviewer",
        "approved_at": "2020-01-01T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "evidence_path": evidence.name,
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "written_permission_confirmed": True,
        **(updates or {}),
    }
    policy = tmp_path / "test_policy.json"
    policy.write_text(json.dumps({"schema_version": 1, "grants": [grant] if grants is None else grants}), encoding="utf-8")
    monkeypatch.setenv(data_rights.POLICY_ENV, str(policy))
    return policy, evidence


def test_missing_permission_is_denied_even_under_pytest():
    denied = data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)
    assert denied["allowed"] is False
    assert denied["state"] == "unverified"
    assert denied["execution_permission"] == "none"
    with pytest.raises(data_rights.DataUseDenied):
        data_rights.require_data_use("coinbase_exchange_public", "BTC-USD", 1, "training")


@pytest.mark.parametrize("raw", ["{", "[]", '{"schema_version": 2, "grants": []}', '{"schema_version": 1, "grants": [], "unexpected": true}'])
def test_invalid_policy_is_denied(tmp_path, monkeypatch, raw):
    policy = tmp_path / "invalid.json"
    policy.write_text(raw, encoding="utf-8")
    monkeypatch.setenv(data_rights.POLICY_ENV, str(policy))
    result = data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)
    assert result["allowed"] is False
    assert result["state"] == "invalid_evidence"


def test_missing_policy_file_and_empty_grants_cannot_authorize(tmp_path, monkeypatch):
    monkeypatch.setenv(data_rights.POLICY_ENV, str(tmp_path / "missing.json"))
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)["allowed"] is False
    write_policy(tmp_path, monkeypatch, grants=[])
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)["allowed"] is False


@pytest.mark.parametrize("updates", [
    {"evidence_sha256": "0" * 64},
    {"evidence_path": "missing-evidence.txt"},
    {"expires_at": NOW.isoformat()},
    {"approved_at": (NOW + timedelta(seconds=1)).isoformat()},
    {"approved_at": "2099-01-01T00:00:00+00:00", "expires_at": "2020-01-01T00:00:00+00:00"},
    {"provider_id": "different_provider"},
    {"symbols": ["ETH-USD"]},
    {"resolutions_seconds": [300]},
    {"allowed_uses": ["retention"]},
    {"allowed_uses": []},
    {"written_permission_confirmed": False},
    {"reviewed_by": ""},
])
def test_bad_evidence_or_scope_cannot_authorize_training(tmp_path, monkeypatch, updates):
    write_policy(tmp_path, monkeypatch, updates=updates)
    result = data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)
    assert result["allowed"] is False


def test_matching_current_explicit_permission_records_scope_and_integrity(tmp_path, monkeypatch):
    policy, _ = write_policy(tmp_path, monkeypatch)
    result = data_rights.check_data_use("coinbase_exchange_live_api", "btc-usd", 60, "training", now=NOW)
    assert result["allowed"] is True
    assert result["state"] == "operator_attested"
    assert result["provider_id"] == "coinbase_exchange_public"
    assert result["symbol"] == "BTC-USD"
    assert result["grant_id"] == "synthetic-test-permission:v1"
    assert result["policy_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert result["execution_permission"] == "none"
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 60, "retention", now=NOW)["allowed"] is True


def test_evidence_tampering_and_use_scope_revoke_admission(tmp_path, monkeypatch):
    _, evidence = write_policy(tmp_path, monkeypatch, updates={"allowed_uses": ["training"]})
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)["allowed"] is True
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "retention", now=NOW)["allowed"] is False
    evidence.write_text("modified evidence", encoding="utf-8")
    assert data_rights.check_data_use("coinbase_exchange_public", "BTC-USD", 1, "training", now=NOW)["allowed"] is False


@pytest.mark.parametrize("symbol", ["BTC-USD", "NVDA"])
def test_unauthorized_training_fetch_cannot_reach_network(monkeypatch, symbol):
    with pytest.raises(data_rights.DataUseDenied):
        public_quotes.fetch_public_candles(symbol, 60, intended_use="training")


def test_training_permission_without_retention_cannot_fetch(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch, updates={"allowed_uses": ["training"]})
    with pytest.raises(data_rights.DataUseDenied) as denied:
        public_quotes.fetch_public_candles("BTC-USD", 60, intended_use="training")
    assert denied.value.decision["intended_use"] == "retention"


def test_matching_training_and_retention_permission_admits_mock_fetch(tmp_path, monkeypatch):
    write_policy(tmp_path, monkeypatch)
    calls = []
    def mock_candles(symbol, granularity, limit):
        calls.append((symbol, granularity, limit))
        return _bars(seconds=60)
    monkeypatch.setattr(public_quotes, "_coinbase_candles", mock_candles)
    result = public_quotes.fetch_public_candles("BTC-USD", 60, limit=12, intended_use="training")
    assert calls == [("BTC-USD", 60, 12)]
    assert result["candles"] == _bars(seconds=60)
    assert result["feed_source"] == "coinbase_exchange_public"


class RecordingStore:
    def __init__(self):
        self.rows = []
        self.commits = []

    def record(self, rows):
        self.rows.extend(rows)

    def restore(self, key):
        return None

    def commit_observation(self, *args):
        self.commits.append(args)


def _bars(now=NOW, seconds=1):
    return [{"timestamp": (now - timedelta(seconds=(8-i)*seconds)).isoformat(),
             "open": 100+i, "high": 102+i, "low": 99+i,
             "close": 101+i, "volume": 1} for i in range(8)]


@pytest.mark.parametrize("symbol,seconds,origin", [
    ("BTC-USD", 1, "coinbase_exchange_public"), ("NVDA", 60, "yahoo_chart_public"),
])
def test_denied_model_use_keeps_display_but_cannot_update_or_capture(monkeypatch, symbol, seconds, origin):
    store = RecordingStore()
    monkeypatch.setattr(live_observer, "_SESSIONS", {})
    monkeypatch.setattr(live_observer, "artifact_store", lambda: store)
    monkeypatch.setattr(live_view, "artifact_store", lambda: store)
    monkeypatch.setattr(live_view, "_CACHE", OrderedDict())
    rows = _bars(seconds=seconds)
    monkeypatch.setattr(live_view, "snapshot", lambda *a, **k: {
        "candles": rows, "chart_source": "public_last_trade", "feed_origin": origin,
        "feed_health": {"connection": "connected"}, "notice": "Synthetic test trades"})
    monkeypatch.setattr(public_quotes, "fetch_public_candles", lambda *a, **k: {
        "as_of": NOW.isoformat(), "candles": rows, "feed_source": origin})
    first = live_view.live_view_snapshot(symbol, sampling=True, now=NOW)
    saved = deepcopy(live_observer._SESSIONS)
    rows.append({**rows[-1], "timestamp": NOW.isoformat(), "close": 120, "high": 121})
    second = live_view.live_view_snapshot(symbol, sampling=True, now=NOW + timedelta(seconds=seconds + 1))
    assert first["candles"]
    assert second["candles"]
    assert second["data_use"]["training"]["allowed"] is False
    assert second["active"]["online_observer"]["status"] == "paused"
    assert second["active"]["online_observer"]["probability_up"] is None
    assert second["active"]["online_observer"]["samples_learned"] == 0
    assert live_observer._SESSIONS == saved
    assert store.rows == store.commits == []


def test_public_stream_without_retention_permission_writes_no_artifact_rows(monkeypatch):
    store = RecordingStore()
    displayed_trades = []
    monkeypatch.setattr(public_stream, "artifact_store", lambda: store)
    monkeypatch.setattr(public_stream, "_IDS", {})
    monkeypatch.setattr(public_stream, "_HEALTH", {})
    monkeypatch.setattr(public_stream, "_INTERRUPTED", set())
    monkeypatch.setattr(public_stream, "snapshot", lambda *a, **k: {"candles": []})
    monkeypatch.setattr(public_stream, "latest_trade_time", lambda *a: None)
    monkeypatch.setattr(public_stream, "fold_trade", lambda row: displayed_trades.append(row))
    received = NOW.isoformat()
    public_stream.process_batch([({"type": "match", "trade_id": 1,
        "product_id": "BTC-USD", "price": "100", "size": "2", "time": received}, received)])
    assert public_stream.feed_health("BTC-USD")["matches_received"] == 1
    assert len(displayed_trades) == 1
    assert store.rows == store.commits == []
