"""Known stream discontinuities contaminate only their received candle window."""

from datetime import datetime, timedelta, timezone

import pytest

from atlas.marketdata import public_stream, second_tape
from atlas.marketdata.live_artifacts import artifact_store


NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)
SYMBOL = "GAP-USD"


@pytest.fixture(autouse=True)
def isolated_stream(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_LIVE_ARTIFACT_DB", str(tmp_path / "gaps.sqlite"))
    for name in ("_BARS", "_SEEN", "_LAST_IDS", "_GAPS", "_WATCHED", "_MISSES"):
        monkeypatch.setattr(second_tape, name, {})
    monkeypatch.setattr(public_stream, "_IDS", {})
    monkeypatch.setattr(public_stream, "_HEALTH", {})
    monkeypatch.setattr(public_stream, "_INTERRUPTED", set())
    monkeypatch.setattr(public_stream, "_AVAILABLE", {SYMBOL})


def match(trade_id, offset):
    stamp = (NOW + timedelta(seconds=offset)).isoformat()
    return ({"type": "match", "trade_id": trade_id, "product_id": SYMBOL,
             "time": stamp, "price": str(100 + offset), "size": "2"}, stamp)


def candles():
    return second_tape.snapshot(SYMBOL, sampling=True, register_interest=False)["candles"]


def test_trade_id_gap_flags_existing_and_next_received_bars_but_not_later_bars():
    public_stream.process_batch([match(100, 0), match(103, 2), match(104, 3)])
    rows = candles()
    assert len(rows) == 3  # No invented candle in the missing second.
    assert [row.get("incomplete", False) for row in rows] == [True, True, False]
    assert all(row["prints"] == 1 and row["volume"] == 2 for row in rows)
    retained = artifact_store().recent_bars(SYMBOL)
    assert [row.get("incomplete", False) for row in retained] == [True, True, False]


def test_heartbeat_gap_flags_later_received_bars_inside_its_window():
    public_stream.process_batch([match(100, 0)])
    stamp = (NOW + timedelta(seconds=3)).isoformat()
    public_stream.process_batch([({"type": "heartbeat", "product_id": SYMBOL,
                                  "last_trade_id": 102, "time": stamp}, stamp)])
    # This contiguous ID does not independently prove a gap. The prior
    # heartbeat still established incomplete coverage through second three.
    public_stream.process_batch([match(101, 2), match(102, 3), match(103, 4)])
    assert [row.get("incomplete", False) for row in candles()] == [True, True, True, False]


def test_reconnect_marks_window_even_when_next_trade_id_is_contiguous():
    public_stream.process_batch([match(100, 0)])
    public_stream.note_stream_interruption()
    public_stream.process_batch([match(101, 2), match(102, 3)])
    assert [row.get("incomplete", False) for row in candles()] == [True, True, False]
    assert not public_stream._INTERRUPTED


def test_restart_restores_bars_and_marks_unobserved_interval_in_persistent_capture():
    public_stream.process_batch([match(100, 0)])
    public_stream._IDS.clear()
    public_stream._HEALTH.clear()
    second_tape._BARS.clear()
    second_tape._SEEN.clear()
    second_tape._LAST_IDS.clear()
    public_stream.process_batch([match(101, 2), match(102, 3)])
    assert [row.get("incomplete", False) for row in candles()] == [True, True, False]
    assert [row.get("incomplete", False) for row in artifact_store().recent_bars(SYMBOL)] == [True, True, False]


def test_heartbeat_window_remains_incomplete_across_restart():
    public_stream.process_batch([match(100, 0)])
    stamp = (NOW + timedelta(seconds=3)).isoformat()
    public_stream.process_batch([({"type": "heartbeat", "product_id": SYMBOL,
                                  "last_trade_id": 102, "time": stamp}, stamp)])
    public_stream._IDS.clear()
    public_stream._HEALTH.clear()
    second_tape._BARS.clear()
    second_tape._SEEN.clear()
    second_tape._LAST_IDS.clear()
    second_tape._GAPS.clear()
    public_stream.process_batch([match(101, 2), match(102, 3), match(103, 4)])
    assert [row.get("incomplete", False) for row in candles()] == [True, True, True, False]


def test_gap_window_is_bounded_and_expires_without_holding_later_bars():
    second_tape.mark_gap(SYMBOL, NOW - timedelta(days=1), NOW)
    assert len(second_tape._GAPS[SYMBOL]) <= second_tape.KEEP_SECONDS + 1
    second_tape.fold_trade({"symbol": SYMBOL, "observed_at": (NOW + timedelta(seconds=91)).isoformat(),
                           "price": 101, "size": 1, "trade_id": 1})
    assert SYMBOL not in second_tape._GAPS
    assert candles()[0].get("incomplete") is not True


def test_continuous_healthy_stream_does_not_mark_received_bars_incomplete():
    public_stream.process_batch([match(100, 0), match(101, 1), match(102, 2)])
    assert len(candles()) == 3
    assert not any(row.get("incomplete") for row in candles())
