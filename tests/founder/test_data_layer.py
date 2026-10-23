from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from atlas.marketdata.pit.calendars import is_open, is_open_cross_checked, sessions
from atlas.marketdata.pit.models import Bar
from atlas.marketdata.pit.providers import FinnhubAdapter, MassivePolygonAdapter, ProviderDisabled
from atlas.marketdata.pit.providers.base import FixtureTransport
from atlas.marketdata.pit.store import ParquetBarStore, SqliteBarStore
from atlas.marketdata.pit.synthetic import gbm_bars

FX = Path(__file__).parent / "fixtures"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
KEY = "fixture-key-not-real-000000"


def test_providers_disabled_by_default():
    with pytest.raises(ProviderDisabled):
        MassivePolygonAdapter().get_daily_bars("SPY", "2023-10-02", "2023-10-04")
    with pytest.raises(ProviderDisabled):
        FinnhubAdapter().earnings_calendar("2026-10-19", "2026-10-23")


def test_enabled_but_offline_transport_still_blocked():
    with pytest.raises(ProviderDisabled):
        MassivePolygonAdapter(api_key=KEY, enabled=True).get_daily_bars("SPY", "a", "b")


@pytest.mark.parametrize("k", [None, "<your-polygon-massive-api-key>", "placeholder"])
def test_placeholder_key_rejected(k):
    t = FixtureTransport({"/2023-10-04": (FX / "polygon_aggs_SPY.json").read_text()})
    with pytest.raises(ProviderDisabled):
        MassivePolygonAdapter(api_key=k, enabled=True, transport=t).get_daily_bars("SPY", "2023-10-02", "2023-10-04")


def test_polygon_parse_fixture():
    t = FixtureTransport({"/2023-10-04": (FX / "polygon_aggs_SPY.json").read_text()})
    bars = MassivePolygonAdapter(api_key=KEY, enabled=True, transport=t).get_daily_bars("SPY", "2023-10-02", "2023-10-04")
    assert len(bars) == 3 and bars[0].open == 429.0 and bars[-1].close == 429.9
    assert all(b.available_at >= b.ts for b in bars)
    assert "/v2/aggs/ticker/SPY/range/1/day/" in t.calls[0][0]


def test_finnhub_parse_fixture():
    t = FixtureTransport({"/calendar/earnings": (FX / "finnhub_earnings.json").read_text(),
                          "/news-sentiment": (FX / "finnhub_sentiment.json").read_text()})
    f = FinnhubAdapter(api_key=KEY, enabled=True, transport=t)
    ev = f.earnings_calendar("2026-10-19", "2026-10-23")
    assert [e.symbol for e in ev] == ["AAA", "BBB", "CCC"]
    assert ev[0].available_at == datetime(2026, 10, 20, 21, 30, tzinfo=UTC)  # after close
    assert ev[2].available_at > datetime(2026, 10, 22, 23, 59, tzinfo=UTC)  # unknown hour => after day end
    assert f.news_sentiment("AAA")["bullish"] == 0.8


def test_bar_validation():
    ts = datetime(2026, 1, 2, 21, tzinfo=UTC)
    with pytest.raises(ValueError):
        Bar(symbol="X", ts=ts.replace(tzinfo=None), open=1, high=1, low=1, close=1, volume=0)
    with pytest.raises(ValueError):
        Bar(symbol="X", ts=ts, open=1, high=1, low=1, close=1, volume=0, available_at=ts - timedelta(minutes=1))
    with pytest.raises(ValueError):
        Bar(symbol="X", ts=ts, open=2, high=1.5, low=1, close=1, volume=0)


def _bars():
    b = gbm_bars("XIC", "XTSE", date(2026, 1, 1), date(2026, 2, 28), seed=1)
    late = b[-1].model_copy(update={"available_at": b[-1].ts + timedelta(days=3)})
    return b[:-1] + [late]


@pytest.mark.parametrize("kind", ["sqlite", "parquet"])
def test_store_roundtrip_and_pit(kind, tmp_path):
    s = SqliteBarStore() if kind == "sqlite" else ParquetBarStore(tmp_path / "pq")
    bars = _bars()
    s.write(bars)
    s.write(bars[:5])  # idempotent upsert
    got = s.read("XIC")
    assert len(got) == len(bars) and got[0].close == pytest.approx(bars[0].close)
    asof = bars[-1].ts + timedelta(hours=1)
    pit = s.read("XIC", as_of=asof)
    assert len(pit) == len(bars) - 1 and all(b.available_at <= asof for b in pit)


@pytest.mark.parametrize("venue,ts,expected", [
    ("XTSE", datetime(2026, 10, 15, 11, 0, tzinfo=NY), True),
    ("XTSE", datetime(2026, 7, 1, 11, 0, tzinfo=NY), False),         # Canada Day
    ("XNYS", datetime(2026, 7, 3, 11, 0, tzinfo=NY), False),         # Independence Day observed
    ("XNAS", datetime(2026, 10, 15, 15, 59, tzinfo=NY), True),
    ("XNYS_XNAS", datetime(2026, 10, 15, 16, 1, tzinfo=NY), False),  # after close
    ("XLON", datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Europe/London")), True),
    ("XLON", datetime(2026, 12, 25, 10, 0, tzinfo=ZoneInfo("Europe/London")), False),
    ("XETR", datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Europe/Berlin")), True),
    ("XTKS", datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")), True),
    ("XTKS", datetime(2026, 10, 17, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo")), False),  # Saturday
    ("XHKG", datetime(2026, 10, 15, 10, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")), True),
    ("crypto", datetime(2026, 10, 17, 3, 0, tzinfo=UTC), True),
    ("fx", datetime(2026, 10, 17, 12, 0, tzinfo=NY), False),          # Saturday
    ("fx", datetime(2026, 10, 18, 16, 59, tzinfo=NY), False),         # Sun before open
    ("fx", datetime(2026, 10, 18, 17, 0, tzinfo=NY), True),
    ("fx", datetime(2026, 10, 16, 17, 0, tzinfo=NY), False),          # Fri close
    ("fx", datetime(2026, 10, 14, 3, 0, tzinfo=NY), True),
    ("NOPE", datetime(2026, 10, 15, 12, 0, tzinfo=UTC), False),
])
def test_calendars(venue, ts, expected):
    assert is_open(venue, ts) is expected


def test_naive_timestamp_fails_closed():
    assert is_open("crypto", datetime(2026, 1, 1)) is False


def test_cross_check_disagreement_closed():
    ts = datetime(2026, 10, 15, 11, 0, tzinfo=NY)
    assert is_open_cross_checked("XTSE", ts, lambda v, t: True)
    assert not is_open_cross_checked("XTSE", ts, lambda v, t: False)
    assert not is_open_cross_checked("XTSE", ts, lambda v, t: 1 / 0)


def test_sessions():
    s = sessions("XTSE", date(2026, 6, 29), date(2026, 7, 3))
    assert date(2026, 7, 1) not in s and len(s) == 4
    assert len(sessions("crypto", date(2026, 1, 1), date(2026, 1, 7))) == 7
    assert sessions("NOPE", date(2026, 1, 1), date(2026, 1, 7)) == []
