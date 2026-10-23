from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import sqlite3
import zipfile

from atlas.marketdata.live_artifacts import artifact_store
from atlas.marketdata.public_stream import process_batch, feed_health
from atlas.marketdata.second_tape import snapshot
from atlas.models.live_observer import observe_public_bars, _SESSIONS


def test_capture_preserves_distinct_trades_at_same_timestamp_and_records_gaps(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_LIVE_ARTIFACT_DB", str(tmp_path / "capture.sqlite"))
    monkeypatch.setattr("atlas.marketdata.public_stream._AVAILABLE", {"CAPTURE-USD"})
    now = datetime.now(timezone.utc).isoformat()
    def match(trade_id):
        return {"type": "match", "trade_id": trade_id, "product_id": "CAPTURE-USD", "price": "100", "size": "2", "time": now}
    process_batch([(match(100), now), (match(101), now), (match(104), now), (match(104), now)])
    tape = snapshot("CAPTURE-USD", sampling=True)
    assert tape["candles"][-1]["prints"] == 3
    assert tape["candles"][-1]["volume"] == 6
    manifest = artifact_store().manifest()
    assert manifest["counts"]["raw_match"] == 3
    assert manifest["counts"]["gap"] == 1
    assert manifest["counts"]["bar"] == 1
    assert feed_health("CAPTURE-USD")["coverage"] == "gap_detected"


def test_observer_checkpoint_restores_without_relearning_and_export_is_verifiable(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_LIVE_ARTIFACT_DB", str(tmp_path / "capture.sqlite"))
    now = datetime.now(timezone.utc)
    symbol = "CAPTURE-OBSERVER-USD"
    rows = [{"timestamp": (now - timedelta(seconds=8-i)).isoformat(), "open": 100+i,
             "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1} for i in range(8)]
    observe_public_bars(symbol, rows, now=now)
    later = {**rows[-1], "timestamp": now.isoformat(), "high": 121, "close": 120}
    learned = observe_public_bars(symbol, rows + [later], now=now+timedelta(seconds=2))
    assert learned["samples_learned"] == 1
    assert learned["persistence"] == "sqlite_checkpoint"
    _SESSIONS.pop(symbol)
    restored = observe_public_bars(symbol, rows + [later], now=now+timedelta(seconds=2))
    assert restored["samples_learned"] == 1
    assert restored["weights"] == learned["weights"]
    store = artifact_store()
    assert store.manifest()["counts"]["prediction"] == 2
    assert store.manifest()["counts"]["outcome"] == 1
    with zipfile.ZipFile(io.BytesIO(store.export())) as archive:
        database = archive.read("live_capture.sqlite")
        manifest = json.loads(archive.read("manifest.json"))
        assert hashlib.sha256(database).hexdigest() == manifest["database_sha256"]
        conn = sqlite3.connect(":memory:")
        conn.deserialize(database)
        payload = json.loads(conn.execute("SELECT payload FROM artifacts WHERE kind='prediction' LIMIT 1").fetchone()[0])
        assert len(payload["input_bars"]) == 4
        assert len(payload["features"]) == 3
        assert payload["model_version"] == "online_logistic_observer:v1"
        conn.close()


def test_unsupported_product_is_withheld_without_changing_valid_subscriptions(monkeypatch):
    from atlas.marketdata.public_stream import eligible_symbols
    monkeypatch.setattr("atlas.marketdata.public_stream._AVAILABLE", {"BTC-USD", "ETH-USD"})
    assert eligible_symbols({"BTC-USD", "UNKNOWN-USD"}) == {"BTC-USD"}
    tape = snapshot("UNKNOWN-USD", sampling=True)
    assert tape["chart_source"] == "withheld"
    assert tape["candles"] == []
    assert tape["feed_health"]["supported"] is False
