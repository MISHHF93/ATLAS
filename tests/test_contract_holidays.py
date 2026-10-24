from datetime import date

import pytest

from atlas.feeds.contracts import _bdays_back, _sessions, contract_for, holiday_source, last_trade_date

xc = pytest.importorskip("exchange_calendars")


def test_holiday_calendar_is_used():
    g = contract_for("GC")
    assert holiday_source(g, 2026) == "exchange_calendars:COMEX"
    ses = _sessions("COMEX", 2025, 2027)
    assert date(2026, 12, 25) not in ses and date(2026, 12, 24) in ses


def test_third_last_bday_skips_holiday():
    g = contract_for("GC")
    assert last_trade_date(g, 2026, 12) == date(2026, 12, 29)
    # GCF? not listed; check roll arithmetic over Christmas: 2 bdays back from 2026-12-28 skips 12-25
    assert _bdays_back(date(2026, 12, 28), 2, _sessions("COMEX", 2025, 2027)) == date(2026, 12, 23)
    assert _bdays_back(date(2026, 12, 28), 2) == date(2026, 12, 24)  # weekday-only fallback differs


def test_es_third_friday_holiday_moves_back():
    es = contract_for("ES")
    ses = _sessions("CMES", 2025, 2027)
    for y, m in ((2026, 3), (2026, 6), (2026, 9), (2026, 12)):
        d = last_trade_date(es, y, m)
        assert d in ses and d.month == m
