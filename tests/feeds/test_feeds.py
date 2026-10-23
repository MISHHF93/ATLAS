"""ATLAS feed layer tests. NO NETWORK: every HTTP call goes through a fake transport.
All payloads below are SYNTHETIC fixtures shaped after each provider's official docs (cited in
docs/data-providers/<name>.md); prices are made up and are not market data."""
from __future__ import annotations

import json
import urllib.parse

import pytest

from atlas.feeds import AtlasFeed, FeedBar, FeedStore, InstrumentMaster, ProviderRegistry, assess, find_gaps
from atlas.feeds.aggregate import aggregate
from atlas.feeds.core import ProviderError, RateLimiter, backoff_delays
from atlas.feeds.providers import (ALL_ADAPTERS, AlpacaAdapter, AlphaVantageAdapter, BinanceAdapter, BybitAdapter,
                                   CoinbaseAdapter, DatabentoAdapter, FinnhubAdapter, FREDAdapter, IBKRAdapter,
                                   KrakenAdapter, OandaAdapter, OKXAdapter, PolygonAdapter, QuestradeAdapter,
                                   TiingoAdapter, TradierAdapter, TwelveDataAdapter, YahooAdapter)
from atlas.feeds.providers.binance import parse_kline_ws
from atlas.feeds.providers.kraken import parse_ohlc_ws
from atlas.feeds.providers.stubs import parse_databento_json

T0 = 1_790_000_100 // 900 * 900          # synthetic bar start, aligned to 15m
NOW = T0 + 900 * 10


class FakeHTTP:
    """Routes by URL substring -> list of (status, headers, body) responses (last one repeats)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        for key, resp in self.routes.items():
            if key in url:
                r = resp.pop(0) if len(resp) > 1 else resp[0]
                st, hd, body = r
                return st, hd, body if isinstance(body, bytes) else json.dumps(body).encode()
        raise OSError("no route (test must not hit network): " + url)


def mk(cls, routes, env=None):
    http = FakeHTTP(routes)
    return cls(transport=http, env=env or {}, clock=lambda: NOW, sleep=lambda s: None,
               limiter=RateLimiter(1000, sleep=lambda s: None)), http


def q(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# ---------------- manifests / registry ----------------

def test_every_adapter_has_complete_manifest():
    names = set()
    for cls in ALL_ADAPTERS:
        c = cls.caps
        assert c.name not in names; names.add(c.name)
        assert c.status in ("working", "interface_fixture_tested", "documented_stub")
        assert c.asset_classes and c.schemas and c.official_docs and c.terms_url and c.rate_limits
        assert all(d.startswith("https://") for d in c.official_docs)
        assert all(e.isupper() for e in c.auth_env)
    assert {"binance", "coinbase", "kraken", "okx", "bybit", "yahoo", "fred", "alpaca", "tiingo", "polygon", "finnhub",
            "twelvedata", "alphavantage", "databento", "ibkr", "oanda", "questrade", "tradier", "cme", "tmx"} <= names


def test_keyed_adapters_activate_only_with_env():
    for cls in ALL_ADAPTERS:
        a = cls(env={})
        if cls.caps.status == "documented_stub":
            assert not a.enabled and a.health().reason == "documented_stub"
        elif cls.caps.auth_env:
            assert not a.enabled and a.health().reason.startswith("missing_env:")
            b = cls(env={k: "x" for k in cls.caps.auth_env})
            assert b.enabled
        else:
            assert a.enabled
    with pytest.raises(ProviderError):
        AlpacaAdapter(env={}).history("SPY", "15m", T0, NOW)
    snap = ProviderRegistry(env={}).snapshot()
    assert {s["name"]: s["enabled"] for s in snap}["alpaca"] is False
    assert all("manifest" in s and "health" in s for s in snap)


# ---------------- keyless adapters ----------------

def test_binance_geo_block_fails_over_to_next_host_and_paginates():
    rows = [[(T0 + i * 900) * 1000, "100", "101", "99", "100.5", "3", (T0 + i * 900 + 899) * 1000] for i in range(10)]
    a, http = mk(BinanceAdapter, {"api.binance.com": [(451, {}, {"code": 0, "msg": "restricted location"})],
                                  "data-api.binance.vision": [(200, {}, rows[:6]), (200, {}, rows[6:]), (200, {}, [])]},
                 env={"ATLAS_BINANCE_REST_HOSTS": "https://api.binance.com,https://data-api.binance.vision"})
    bars = a.history("BTCUSDT", "15m", T0, NOW)
    assert len(bars) == 10 and bars[0].event_time == T0 and bars[-1].confirmed
    assert "api.binance.com" in http.calls[0][0] and all("vision" in u for u, _ in http.calls[1:])


def test_binance_rate_limit_retry_after_then_success():
    rows = [[T0 * 1000, "1", "2", "0.5", "1.5", "1", 0]]
    slept = []
    http = FakeHTTP({"vision": [(429, {"Retry-After": "3"}, b"slow down"), (200, {}, rows), (200, {}, [])]})
    a = BinanceAdapter(transport=http, env={}, clock=lambda: NOW, sleep=slept.append, limiter=RateLimiter(1000, sleep=lambda s: None))
    assert len(a.history("BTCUSDT", "15m", T0, T0 + 900)) == 1
    assert slept[0] == 3.0 and a.health().rate_limited == 1


def test_binance_ws_kline_only_final_is_confirmed():
    a = BinanceAdapter(env={}, clock=lambda: NOW)
    k = {"t": T0 * 1000, "s": "BTCUSDT", "i": "15m", "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "9", "x": False}
    (b,) = parse_kline_ws({"data": {"e": "kline", "k": k}}, T0 + 100, {}, a)
    assert not b.confirmed
    (b,) = parse_kline_ws({"data": {"e": "kline", "k": {**k, "x": True}}}, T0 + 901, {}, a)
    assert b.confirmed


def test_coinbase_kraken_okx_bybit_yahoo_parse():
    cb, _ = mk(CoinbaseAdapter, {"coinbase": [(200, {}, [[T0 + 900, 9, 11, 10, 10.5, 2], [T0, 9, 11, 10, 10.2, 1]])]})
    assert [b.event_time for b in cb.history("BTCUSDT", "15m", T0, T0 + 1800)] == [T0, T0 + 900]
    assert cb.history("BTCUSDT", "15m", T0, T0 + 1800)[0].open == 10
    kr, _ = mk(KrakenAdapter, {"kraken": [(200, {}, {"error": [], "result": {"XBTUSDT": [[T0, "10", "11", "9", "10.5", "10.2", "3", 7]], "last": T0}})]})
    (b,) = kr.history("BTCUSDT", "15m", T0, T0 + 900)
    assert b.volume == 3 and b.provider_symbol == "XBTUSDT"
    ok, _ = mk(OKXAdapter, {"okx": [(200, {}, {"code": "0", "data": [[str((T0 + 900) * 1000), "1", "2", "0.5", "1", "5", "", "", "1"],
                                                                        [str(T0 * 1000), "1", "2", "0.5", "1", "5", "", "", "1"]]}),
                                    (200, {}, {"code": "0", "data": []})]})
    assert len(ok.history("BTCUSDT", "15m", T0, T0 + 1800)) == 2
    by, _ = mk(BybitAdapter, {"bybit": [(200, {}, {"retCode": 0, "result": {"list": [[str(T0 * 1000), "1", "2", "0.5", "1", "5", "5"]]}})]})
    assert len(by.history("BTCUSDT", "15m", T0, T0 + 900)) == 1
    by2, _ = mk(BybitAdapter, {"bybit": [(403, {}, b"configured to block access from your country")]})
    with pytest.raises(ProviderError) as e:
        by2.history("BTCUSDT", "15m", T0, T0 + 900)
    assert e.value.geo_blocked
    yh, _ = mk(YahooAdapter, {"yahoo": [(200, {}, {"chart": {"result": [{"timestamp": [T0, T0 + 900, T0 + 9000],
               "indicators": {"quote": [{"open": [1, None, 1], "high": [2, 2, 2], "low": [0.5, 0.5, 0.5], "close": [1.5, 1, 1.5], "volume": [10, 1, 5]}]}}]}})]})
    bars = yh.history("SPY", "15m", T0, NOW + 900)
    assert [b.event_time for b in bars] == [T0, T0 + 9000] and bars[0].confirmed and not bars[1].confirmed
    assert YahooAdapter.caps.unofficial


def test_kraken_ws_v2_ohlc():
    a = KrakenAdapter(env={}, clock=lambda: NOW)
    m = {"channel": "ohlc", "type": "update", "data": [{"symbol": "BTC/USDT", "open": 1, "high": 2, "low": 0.5, "close": 1.5,
         "volume": 3, "interval_begin": "2026-09-21T12:00:00.000000000Z".replace(".000000000", ""), "interval": 15}]}
    (b,) = parse_ohlc_ws(m, NOW, {"BTC/USDT": "BTCUSDT"}, "15m", a)
    assert b.instrument == "BTCUSDT" and b.close == 1.5


def test_fred_observations_vintages():
    f, http = mk(FREDAdapter, {"stlouisfed": [(200, {}, {"observations": [
        {"realtime_start": "2026-01-05", "realtime_end": "9999-12-31", "date": "2026-01-01", "value": "4.1"},
        {"realtime_start": "2026-01-05", "realtime_end": "9999-12-31", "date": "2026-01-02", "value": "."}]})]}, env={"FRED_API_KEY": "k"})
    obs = f.observations("DGS10")
    assert obs[0].value == 4.1 and obs[1].value is None and q(http.calls[0][0])["api_key"] == "k"
    s = FeedStore(":memory:")
    assert s.ingest_observations(obs) == 2 and s.ingest_observations(obs) == 0
    assert s.observations("DGS10", as_of_date="2026-01-04") == []


# ---------------- keyed adapters (fixture-tested) ----------------

def test_alpaca_rest_pagination_headers_and_stream_parse():
    p1 = {"bars": {"SPY": [{"t": "2026-09-21T13:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "n": 5, "vw": 1.2}]}, "next_page_token": "abc"}
    p2 = {"bars": {"SPY": [{"t": "2026-09-21T13:45:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.6, "v": 50, "n": 5, "vw": 1.2}]}, "next_page_token": None}
    env = {"ALPACA_API_KEY_ID": "id", "ALPACA_API_SECRET_KEY": "sec"}
    a, http = mk(AlpacaAdapter, {"data.alpaca.markets/v2/stocks/bars": [(200, {}, p1), (200, {}, p2)]}, env)
    import datetime as dt
    s = int(dt.datetime(2026, 9, 21, 13, 30, tzinfo=dt.timezone.utc).timestamp())
    a.clock = lambda: s + 86400
    bars = a.history("SPY", "15m", s, s + 3600)
    assert len(bars) == 2 and bars[1].close == 1.6
    u, h = http.calls[0]
    assert h["APCA-API-KEY-ID"] == "id" and h["APCA-API-SECRET-KEY"] == "sec"
    assert q(u)["timeframe"] == "15Min" and q(u)["feed"] == "iex" and q(http.calls[1][0])["page_token"] == "abc"
    msgs = [{"T": "b", "S": "SPY", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": "2026-09-21T13:30:00Z"},
            {"T": "u", "S": "SPY", "o": 1, "h": 2.5, "l": 0.5, "c": 1.7, "v": 12, "t": "2026-09-21T13:30:00Z"},
            {"T": "t", "S": "SPY", "p": 1.6, "s": 3, "t": "2026-09-21T13:30:05Z"},
            {"T": "error", "code": 406, "msg": "connection limit exceeded"}]
    items = list(a.parse_stream(msgs, s + 120))
    assert [type(i).__name__ for i in items] == ["FeedBar", "FeedBar", "FeedTrade"] and items[1].close == 1.7
    assert "406" in a.health().last_error


@pytest.mark.parametrize("cls,env,route,payload,interval", [
    (TiingoAdapter, {"TIINGO_API_KEY": "k"}, "tiingo", [{"date": "2026-09-21T13:30:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}], "15m"),
    (PolygonAdapter, {"POLYGON_API_KEY": "k"}, "massive", {"results": [{"t": 1790000000000 // 900000 * 900000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}]}, "15m"),
    (FinnhubAdapter, {"FINNHUB_API_KEY": "k"}, "finnhub", {"s": "ok", "t": [T0], "o": [1], "h": [2], "l": [0.5], "c": [1.5], "v": [9]}, "15m"),
    (TwelveDataAdapter, {"TWELVEDATA_API_KEY": "k"}, "twelvedata", {"values": [{"datetime": "2026-09-21 13:30:00", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "9"}], "status": "ok"}, "15m"),
    (AlphaVantageAdapter, {"ALPHAVANTAGE_API_KEY": "k"}, "alphavantage", {"Meta Data": {"6. Time Zone": "US/Eastern"}, "Time Series (15min)": {"2026-09-21 09:45:00": {"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": "1.5", "5. volume": "9"}}}, "15m"),
    (OandaAdapter, {"OANDA_API_TOKEN": "k"}, "oanda", {"candles": [{"time": "1790000000.000000000", "complete": True, "volume": 9, "mid": {"o": "1", "h": "2", "l": "0.5", "c": "1.5"}}]}, "15m"),
    (TradierAdapter, {"TRADIER_ACCESS_TOKEN": "k"}, "tradier", {"series": {"data": {"timestamp": T0, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}}}, "15m"),
    (IBKRAdapter, {"IBKR_CP_GATEWAY_URL": "https://localhost:5000"}, "localhost", {"data": [{"t": T0 * 1000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}]}, "15m"),
])
def test_keyed_adapter_parses_fixture(cls, env, route, payload, interval):
    a, http = mk(cls, {route: [(200, {}, payload)]}, env)
    a.clock = lambda: 1_800_000_000
    bars = a.history("SPY", interval, 1_780_000_000, 1_800_000_000)
    assert len(bars) == 1 and bars[0].close == 1.5 and bars[0].high == 2 and bars[0].confirmed
    assert bars[0].provider == cls.caps.name
    flat = json.dumps(http.calls)
    assert "k" in flat or "localhost" in flat


def test_alphavantage_intraday_timestamps_are_bar_end_converted_to_start():
    a, _ = mk(AlphaVantageAdapter, {"alphavantage": [(200, {}, {"Meta Data": {"6. Time Zone": "US/Eastern"},
              "Time Series (15min)": {"2026-09-21 09:45:00": {"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": "1.5", "5. volume": "9"}}})]},
              {"ALPHAVANTAGE_API_KEY": "k"})
    a.clock = lambda: 1_800_000_000
    import datetime as dt
    (b,) = a.history("SPY", "15m", 1_780_000_000, 1_800_000_000)
    assert dt.datetime.fromtimestamp(b.event_time, dt.timezone.utc).strftime("%H:%M") == "13:30"


def test_questrade_refresh_flow_and_databento_parse():
    env = {"QUESTRADE_REFRESH_TOKEN": "r"}
    a, http = mk(QuestradeAdapter, {"oauth2/token": [(200, {}, {"access_token": "acc", "api_server": "https://api01.iq.questrade.com/"})],
                                    "symbols/search": [(200, {}, {"symbols": [{"symbolId": 8049}]})],
                                    "candles/8049": [(200, {}, {"candles": [{"start": "2026-09-21T09:30:00-04:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}]})]}, env)
    a.clock = lambda: 1_800_000_000
    assert len(a.history("SPY", "15m", 1_780_000_000, 1_800_000_000)) == 1
    assert http.calls[1][1]["Authorization"] == "Bearer acc"
    d = DatabentoAdapter(env={"DATABENTO_API_KEY": "k"}, clock=lambda: NOW)
    with pytest.raises(ProviderError):  # billed: requires explicit dataset opt-in
        d.history("ES", "1h", T0, NOW)
    line = json.dumps({"hd": {"ts_event": str(T0 * 10**9)}, "open": "5000250000000", "high": "5001000000000", "low": "4999000000000", "close": "5000500000000", "volume": "12"})
    (b,) = parse_databento_json(d, "ES", "1h", line.encode(), NOW + 3600 * 3)
    assert b.open == 5000.25 and b.volume == 12


# ---------------- store / PIT / quality ----------------

def bar(t, c=100.0, prov="binance", rt=None, conf=True, inst="BTCUSDT", iv="15m"):
    return FeedBar(inst, iv, t, c, c + 1, c - 1, c, 1.0, prov, rt if rt is not None else t + 900, conf)


def test_store_idempotent_revisions_and_point_in_time():
    s = FeedStore(":memory:")
    r = s.ingest([bar(T0, 100, conf=False, rt=T0 + 300)])
    assert r["inserted"] == 1
    assert s.ingest([bar(T0, 100, conf=False, rt=T0 + 301)])["inserted"] == 0   # dedup: same content
    assert s.ingest([bar(T0, 101, rt=T0 + 900)])["revised"] == 1                # confirmed final
    assert s.ingest([bar(T0, 102, rt=T0 + 2000)])["revised"] == 1               # provider revision
    assert s.ingest([bar(T0, 99, conf=False, rt=T0 + 3000)])["revised"] == 0    # never downgrade to provisional
    assert [b.close for b in s.bars("BTCUSDT", "15m")] == [102]
    assert [b.close for b in s.bars("BTCUSDT", "15m", as_of=T0 + 1000)] == [101]   # what was known then
    assert s.bars("BTCUSDT", "15m", as_of=T0 + 500) == []                          # only provisional known
    assert len(s.bars("BTCUSDT", "15m", as_of=T0 + 500, confirmed_only=False)) == 1
    assert len(s.revisions("BTCUSDT", "15m", T0)) == 3


def test_gap_detection_quality_flags_and_predict_abstains():
    bars = [bar(T0 + i * 900) for i in range(20) if i not in (5, 6)]
    assert find_gaps(bars, "24x7", "15m", T0, T0 + 20 * 900) == [(T0 + 5 * 900, T0 + 7 * 900)]
    q = assess(bars, "24x7", "15m", T0 + 20 * 900 + 10, lookback_bars=50)
    assert "gap" in q.flags and "stale" not in q.flags
    q = assess(bars, "24x7", "15m", T0 + 40 * 900, lookback_bars=50)
    assert "stale" in q.flags
    full = [bar(T0 + i * 900) for i in range(20)]
    assert assess(full, "24x7", "15m", T0 + 20 * 900 + 10).ok()
    cross = [bar(T0 + i * 900, 110, prov="okx") for i in range(20)]
    assert "provider_disagreement" in assess(full, "24x7", "15m", T0 + 20 * 900 + 10, cross=cross).flags
    assert "no_data" in assess([], "24x7", "15m", NOW).flags

    from atlas.models import predict as P
    m = P.RegisteredModel if hasattr(P, "RegisteredModel") else None
    snap = P.FeatureSnapshot({"x": 1.0}, {"x": NOW}, data_quality_flags=("stale",))
    reg = P.ModelRegistry()
    out = P.predict("BTCUSDT", NOW, "1h", snap, None, reg)
    assert out.abstained
    assert P.FeatureSnapshot({"x": 1.0}, {"x": NOW}).data_quality_flags == ()
    assert P.DATA_QUALITY == "data_quality"


def test_us_equity_calendar_gaps_ignore_nights_weekends_and_holidays():
    import datetime as dt
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    # Fri 2026-07-02 full day, Fri 07-03 holiday (observed Independence Day), Mon 07-06
    d = lambda *a: int(dt.datetime(*a, tzinfo=ny).timestamp())
    bars = [bar(t, inst="SPY") for day in ((2026, 7, 2), (2026, 7, 6)) for t in range(d(*day, 9, 30), d(*day, 16, 0), 900)]
    assert find_gaps(bars, "us_equity_rth", "15m", bars[0].event_time, bars[-1].bar_end) == []
    holes = [b for b in bars if b.event_time != d(2026, 7, 6, 10, 0)]
    assert find_gaps(holes, "us_equity_rth", "15m", bars[0].event_time, bars[-1].bar_end) == [(d(2026, 7, 6, 10, 0), d(2026, 7, 6, 10, 15))]


def test_aggregate_1m_to_15m_confirmation():
    mins = [FeedBar("SPY", "1m", T0 + i * 60, 1 + i, 2 + i, 0.5, 1.5 + i, 1, "alpaca", T0 + i * 60 + 60, True) for i in range(15)]
    (b,) = aggregate(mins, "15m", T0 + 900)
    assert b.open == 1 and b.close == 15.5 and b.high == 16 and b.volume == 15 and b.confirmed
    (b,) = aggregate(mins[:10], "15m", T0 + 600)
    assert not b.confirmed


# ---------------- the ATLAS feed facade ----------------

def test_feed_failover_priority_backfill_gap_fill_and_health():
    store = FeedStore(":memory:")
    rows = [[(T0 + i * 900) * 1000, "100", "101", "99", "100", "1", 0] for i in range(10) if i != 4]
    binance, bh = mk(BinanceAdapter, {"vision": [(500, {}, b"down")]})
    okx, oh = mk(OKXAdapter, {"okx": [(200, {}, {"code": "0", "data": [[str((T0 + i * 900) * 1000), "100", "101", "99", "100", "1", "", "", "1"] for i in reversed(range(10)) if i != 4]}),
                                      (200, {}, {"code": "0", "data": []})]})
    kraken, _ = mk(KrakenAdapter, {"kraken": [(200, {}, {"error": [], "result": {"XBTUSDT": [[T0 + 4 * 900, "100", "101", "99", "100", "100", "1", 1]]}})]})
    coinbase, _ = mk(CoinbaseAdapter, {"coinbase": [(200, {}, [[T0 + i * 900, 99, 101, 100.1, 100.1, 1] for i in range(10)])]})
    feed = AtlasFeed(store, ProviderRegistry([binance, okx, kraken, coinbase]), InstrumentMaster(), clock=lambda: NOW)
    r = feed.backfill("BTCUSDT", "15m", T0, NOW)
    assert r["provider"] == "okx" and "binance" in r["errors"]           # failover
    assert r["gap_fills"] and r["gap_fills"][0]["gap"][0] == T0 + 4 * 900 # automatic backfill filled the hole
    ser = feed.bars("BTCUSDT", "15m", T0, NOW)
    assert len(ser) == 10 and {b.provider for b in ser} == {"okx", "kraken"}
    cc = feed.cross_check("BTCUSDT", "15m", T0, NOW)
    assert cc["coinbase"]["ok"] and cc["coinbase"]["median_bps"] == 10.0
    assert "coinbase" not in {b.provider for b in feed.bars("BTCUSDT", "15m", T0, NOW)}  # sanity-only never merged
    assert feed.quality_flags("BTCUSDT", "15m", NOW) == ()
    assert "stale" in feed.quality_flags("BTCUSDT", "15m", NOW + 86400)
    h = feed.health()
    assert any(e["event"] == "failover" for e in h["events"]) and h["series"] and h["providers"]
    from atlas.feeds import udf
    u = udf.history("BTCUSDT", "15", T0, NOW, feed=feed)
    assert u["s"] == "ok" and len(u["t"]) == 10
    assert udf.symbol_info("SPY", feed)["session"] == "0930-1600"


def test_backoff_and_rate_limiter():
    d = list(backoff_delays(base=1, cap=8, attempts=6, jitter=lambda: 1.0))
    assert d == [1, 2, 4, 8, 8, 8]
    t = [0.0]; slept = []
    rl = RateLimiter(2, 1.0, clock=lambda: t[0], sleep=lambda s: slept.append(s))
    rl.acquire(); rl.acquire(); rl.acquire()
    assert slept and slept[0] == pytest.approx(0.5)


def test_research_loader_reads_from_feed_store(tmp_path):
    from atlas.research.setup_evidence import load_datasets
    p = tmp_path / "f.sqlite"
    s = FeedStore(p)
    s.ingest([bar(T0 + i * 900) for i in range(100)])
    (bars, meta), = list(load_datasets(p, ("15m",)))
    assert len(bars) == 100 and meta["asset_class"] == "crypto" and meta["source"].startswith("binance")


def test_tradier_quota_violation_400_is_retried_as_rate_limit():
    # SYNTHETIC fixture: Tradier documents over-quota as HTTP 400 "Quota Violation" (not 429).
    from atlas.feeds.providers import TradierAdapter
    http = FakeHTTP({"tradier": [(400, {}, b"Quota Violation"), (500, {}, b"x"), (400, {}, b"Quota Violation")]})
    a = TradierAdapter(transport=http, env={"TRADIER_ACCESS_TOKEN": "x"}, clock=lambda: NOW, sleep=lambda s: None,
                       limiter=RateLimiter(1000, sleep=lambda s: None))
    with pytest.raises(ProviderError) as ei:
        a.get_json("https://sandbox.tradier.com/v1/markets/timesales", {})
    assert ei.value.retryable and a.health().rate_limited >= 2 and len(http.calls) > 1
