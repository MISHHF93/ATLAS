"""Global session boundaries and entry buffers are schedule facts, never trading permission."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from atlas.marketdata.pit import calendars
from atlas.ops.sessions import SessionModel


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def model():
    path = Path(__file__).resolve().parents[2] / "config/founder/schedule.yaml"
    return SessionModel(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(("instant", "expected"), [
    ("2026-10-28T00:00:00Z", True),
    ("2026-10-28T02:29:59.999999Z", True),
    ("2026-10-28T02:30:00Z", False),
    ("2026-10-28T03:29:59Z", False),
    ("2026-10-28T03:30:00Z", True),
    ("2026-10-28T06:29:59Z", True),
    ("2026-10-28T06:30:00Z", False),
])
def test_tokyo_precise_boundaries(instant, expected):
    assert calendars.is_open("XTKS", utc(instant)) is expected


def test_tokyo_plan_splits_lunch_and_preserves_final_close(model):
    plan = model.plan(utc("2026-10-27T23:00:00Z"), horizon_h=8)
    windows = [w for w in plan["windows"] if w["venue"] == "XTKS"]
    assert [(w["open_utc"], w["close_utc"]) for w in windows] == [
        ("2026-10-28T00:00:00+00:00", "2026-10-28T02:30:00+00:00"),
        ("2026-10-28T03:30:00+00:00", "2026-10-28T06:30:00+00:00"),
    ]
    assert all(w["entry_cutoff_utc"] == "2026-10-28T06:20:00+00:00" for w in windows)
    assert model.status("XTKS", utc("2026-10-28T02:25:00Z"))["new_orders_allowed"]
    assert model.next_change("XTKS", utc("2026-10-28T02:29:31Z")) == "2026-10-27T22:30-04:00"
    assert model.next_change("XTKS", utc("2026-10-28T03:00:00Z")) == "2026-10-27T23:30-04:00"


def test_hong_kong_lunch_and_closed_weekend(model):
    assert not model.status("XHKG", utc("2026-10-28T04:15:00Z"))["open"]
    assert model.status("XHKG", utc("2026-10-28T05:00:00Z"))["open"]
    assert not model.status("XHKG", utc("2026-10-31T05:00:00Z"))["open"]


def test_holiday_has_no_windows(model):
    plan = model.plan(utc("2026-11-26T00:00:00Z"))
    assert not [w for w in plan["windows"] if w["venue"] == "XNYS_XNAS"]
    assert not model.status("XNYS_XNAS", utc("2026-11-26T15:00:00Z"))["new_orders_allowed"]


def test_actual_early_close_controls_entry_buffer(model):
    before = model.status("XNYS_XNAS", utc("2026-11-27T17:49:59Z"))
    cutoff = model.status("XNYS_XNAS", utc("2026-11-27T17:50:00Z"))
    assert before["new_orders_allowed"]
    assert cutoff["open"] and not cutoff["new_orders_allowed"]
    assert cutoff["entry_block_reason"] == "close_buffer"
    assert cutoff["entry_cutoff_utc"] == "2026-11-27T17:50:00+00:00"
    assert cutoff["session_close_utc"] == "2026-11-27T18:00:00+00:00"
    assert not model.status("XNYS_XNAS", utc("2026-11-27T18:00:00Z"))["open"]


def test_regional_dst_changes_do_not_use_fixed_utc_offsets():
    def opening(venue, day):
        return calendars.trading_windows(venue, utc(day + "T00:00:00Z"), utc(day + "T23:59:59Z"))[0].open
    # UK summer time has ended on Oct 28, while North America remains on summer time.
    assert opening("XLON", "2026-10-28").hour == 8
    assert (opening("XNYS", "2026-10-28").hour, opening("XNYS", "2026-10-28").minute) == (13, 30)
    assert (opening("XNYS", "2026-11-02").hour, opening("XNYS", "2026-11-02").minute) == (14, 30)
    assert opening("XLON", "2026-11-02").hour == 8


def test_plan_has_provenance_and_no_execution_permission(model):
    plan = model.plan(utc("2026-10-28T15:00:00Z"))
    assert plan["execution_permission"] == "none"
    assert plan["purpose"] == "scheduled_sessions_only"
    assert "model validation" in plan["eligibility_note"]
    nyse = next(row for row in plan["venues"] if row["venue"] == "XNYS_XNAS")
    assert nyse["calendar"]["source"] == "exchange_calendars"
    assert nyse["calendar"]["version"]
    assert "cme_globex" not in [row["venue"] for row in plan["venues"]]
    assert plan == model.plan(utc("2026-10-28T15:00:00Z"))


def test_crypto_does_not_close_at_midnight_or_apply_daily_cutoff(model):
    now = utc("2026-10-28T23:59:59Z")
    assert model.status("crypto", now)["new_orders_allowed"]
    assert model.status("crypto", now)["entry_cutoff_utc"] is None
    assert model.next_change("crypto", now) is None
    assert not [t for t in model.plan(now, horizon_h=1)["transitions"] if t["venue"] == "crypto"]


def test_fx_weekend_close_uses_new_york_dst(model):
    assert model.next_change("fx", utc("2026-10-30T20:59:59Z")) == "2026-10-30T17:00-04:00"
    assert model.next_change("fx", utc("2026-11-06T21:59:59Z")) == "2026-11-06T17:00-05:00"


def test_unknown_and_unavailable_calendars_fail_closed(model, monkeypatch):
    assert not calendars.is_open("NOPE", utc("2026-10-28T15:00:00Z"))
    assert model.can_trade("NOPE", utc("2026-10-28T15:00:00Z")) == (False, 0.0)
    def unavailable(name):
        raise RuntimeError("calendar not installed")
    monkeypatch.setattr(calendars, "_cal", unavailable)
    status = model.status("XNYS_XNAS", utc("2026-10-28T15:00:00Z"))
    assert not status["open"] and not status["new_orders_allowed"]
    assert status["entry_block_reason"] == "calendar_unavailable"
    assert status["schedule_error"]
    plan = model.plan(utc("2026-10-28T15:00:00Z"), horizon_h=1)
    assert not [w for w in plan["windows"] if w["venue"] == "XNYS_XNAS"]


def test_naive_timestamps_and_invalid_horizons_rejected(model):
    with pytest.raises(ValueError, match="tz-aware"):
        model.plan(datetime(2026, 10, 28, 15))
    assert not calendars.is_open("XNYS", datetime(2026, 10, 28, 15))
    for horizon in (0, -1, 169, float("nan")):
        with pytest.raises(ValueError, match="horizon_h"):
            model.plan(datetime(2026, 10, 28, 15, tzinfo=timezone.utc), horizon_h=horizon)
