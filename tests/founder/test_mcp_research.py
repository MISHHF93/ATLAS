"""US-06: read-only research tools over the local point-in-time bar store (offline)."""
from datetime import datetime, timedelta, timezone

import pytest

from atlas.marketdata.pit.models import Bar
from atlas.marketdata.pit.store import SqliteBarStore
from atlas.mcp.trading.research import _ema, _rsi, _sma
from atlas.mcp.trading.service import build_service

CONFIG_DIR = "config/founder"
T0 = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)


@pytest.fixture
def svc():
    s = build_service(CONFIG_DIR)
    st = SqliteBarStore()
    st.write([Bar(symbol="XIC.TO", ts=T0 + timedelta(days=i), open=30 + i, high=31 + i, low=29 + i, close=30.5 + i, volume=1000)
              for i in range(40)])
    s.bar_store = st
    return s


def test_bars_quote_and_limit(svc):
    b = svc.get_bars("XIC.TO", 10)
    assert len(b["bars"]) == 10 and b["bars"][-1]["c"] == 69.5 and b["source"] == "local_store"
    assert svc.get_quote("XIC.TO") == {"symbol": "XIC.TO", "last": 69.5, "source": "last_stored_bar", "ts": b["bars"][-1]["ts"]}
    assert svc.get_quote("NOPE")["last"] is None and svc.get_bars("NOPE")["bars"] == []


def test_point_in_time(svc):
    from atlas.mcp.trading.research import get_bars
    assert len(get_bars(svc.bar_store, "XIC.TO", 100, as_of=T0 + timedelta(days=4))["bars"]) == 5


def test_indicators(svc):
    out = svc.compute_indicators("XIC.TO", [{"name": "sma", "params": {"period": 5}}, {"name": "RSI"}, {"name": "ATR"}, {"name": "BBANDS"}, {"name": "EMA"}])
    assert out["series"]["SMA_5"][-1]["value"] == pytest.approx(sum(30.5 + i for i in range(35, 40)) / 5)
    assert out["series"]["RSI_14"][-1]["value"] == 100.0                       # only up-moves
    assert out["series"]["ATR_14"][-1]["value"] == pytest.approx(2.0)          # gap-up of 1 + range 2 => true range 2
    assert {"BB_MID_20", "BB_UP_20", "BB_LO_20", "EMA_20"} <= set(out["series"])
    with pytest.raises(ValueError):
        svc.compute_indicators("XIC.TO", [{"name": "MAGIC"}])


def test_math_helpers():
    assert _sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert _ema([1, 2, 3], 2)[1] == 1.5 and _ema([1, 2, 3], 2)[2] == pytest.approx(3 * 2 / 3 + 1.5 / 3)
    assert _rsi([1, 2, 1, 2, 1], 2)[2] == pytest.approx(50.0)


def test_no_store_is_explicit():
    s = build_service(CONFIG_DIR)
    s.bar_store = None
    assert s.get_bars("X")["source"] == "none" and s.compute_indicators("X", [{"name": "SMA"}])["series"] == {}


def test_research_module_has_no_network_imports():
    import atlas.mcp.trading.research as r
    src = open(r.__file__).read()
    assert not any(m in src for m in ("import requests", "urllib", "http.client", "socket", "httpx"))
