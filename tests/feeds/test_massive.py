"""Massive (Stocks Basic) adapter, shared throttle and backfill planner. No network, no real key."""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from zoneinfo import ZoneInfo

from atlas.feeds import AtlasFeed, FeedStore, ProviderRegistry
from atlas.feeds.core import RateLimiter
from atlas.feeds.massive_backfill import PRIORITY, jobs, materialize_1h, plan_window, run, stock_1m_universe, window_days
from atlas.feeds.providers.polygon import PolygonAdapter, et_midnight, in_rth
from atlas.feeds.stock_providers import intervals_for
from atlas.feeds.throttle import SharedWindowLimiter

NY = ZoneInfo("America/New_York")
KEY = "test-key-not-real"


def ts(y, m, d, hh=0, mm=0):
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=NY).timestamp())


class Http:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        st, body = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        return st, {}, json.dumps(body).encode()


def mk(pages, now, **kw):
    http = Http(pages)
    a = PolygonAdapter(transport=http, env={"MASSIVE_API_KEY": KEY}, clock=lambda: now, sleep=lambda s: None,
                       limiter=RateLimiter(1000, sleep=lambda s: None), **kw)
    return a, http


def row(t_ms, c=1.5):
    return {"t": t_ms, "o": 1, "h": 2, "l": 0.5, "c": c, "v": 9}


NOW = ts(2026, 10, 29, 17, 0)      # Thursday evening, ET


def test_key_goes_in_bearer_header_never_in_the_url():
    a, http = mk([(200, {"results": [row(ts(2026, 10, 28) * 1000)]})], NOW)
    bars = a.history("AAPL", "1d", ts(2026, 10, 1), NOW)
    assert len(bars) == 1 and bars[0].provider == "polygon"
    url, headers = http.calls[0]
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert KEY not in url and "apiKey" not in url
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["adjusted"] == ["true"]


def test_next_url_pages_are_followed_with_the_header_and_no_key_in_the_query():
    p1 = {"results": [row(ts(2026, 10, 26) * 1000)], "next_url": "https://api.massive.com/v2/aggs/next?cursor=abc"}
    p2 = {"results": [row(ts(2026, 10, 27) * 1000)]}
    a, http = mk([(200, p1), (200, p2)], NOW)
    assert len(a.history("AAPL", "1d", ts(2026, 10, 1), NOW)) == 2
    assert len(http.calls) == 2 and http.calls[1][0] == "https://api.massive.com/v2/aggs/next?cursor=abc"
    assert all(h["Authorization"] == f"Bearer {KEY}" for _, h in http.calls)


def test_request_never_reaches_into_the_current_et_day():
    a, http = mk([(200, {"results": []})], NOW)
    a.history("AAPL", "1d", ts(2026, 10, 20), NOW)
    to_ms = int(http.calls[0][0].split("/range/1/day/")[1].split("/")[1].split("?")[0])
    assert to_ms == et_midnight(NOW) * 1000 - 1
    assert a.history("AAPL", "1d", et_midnight(NOW), NOW) == [] and len(http.calls) == 1   # empty window: no call


def test_intraday_keeps_regular_session_only_for_stocks():
    pre, o930, last, post = ts(2026, 10, 28, 8, 0), ts(2026, 10, 28, 9, 30), ts(2026, 10, 28, 15, 45), ts(2026, 10, 28, 16, 0)
    a, _ = mk([(200, {"results": [row(t * 1000) for t in (pre, o930, last, post)]})], NOW)
    got = [b.event_time for b in a.history("SPY", "15m", ts(2026, 10, 28), NOW)]
    assert got == [o930, last]
    assert in_rth(o930) and not in_rth(post) and not in_rth(ts(2026, 10, 31, 10, 0))   # Saturday


def test_crypto_tickers_are_not_cut_to_an_equity_session():
    t = ts(2026, 10, 28, 3, 0)
    a, _ = mk([(200, {"results": [row(t * 1000)]})], NOW)
    a.symbol_map = {"BTCUSDT": "X:BTCUSD"}
    assert len(a.history("BTCUSDT", "15m", ts(2026, 10, 28), NOW)) == 1


def test_past_window_is_cached_so_a_rerun_spends_no_quota(tmp_path):
    a, http = mk([(200, {"results": [row(ts(2026, 10, 27) * 1000)]})], NOW, cache_dir=tmp_path)
    first = a.history("AAPL", "1d", ts(2026, 10, 1), NOW)
    again = a.history("AAPL", "1d", ts(2026, 10, 1), NOW)
    assert len(http.calls) == 1 and [b.close for b in first] == [b.close for b in again]
    assert list(tmp_path.glob("*.json.gz")) and KEY not in "".join(p.name for p in tmp_path.iterdir())


def test_free_plan_serves_1m_15m_and_daily_t_plus_1_but_not_live():
    assert intervals_for("polygon", {}) == ("1m", "15m", "1d")
    assert "1m" in intervals_for("polygon", {"ATLAS_POLYGON_PLAN": "paid"})


def test_shared_limiter_blocks_the_fifth_call_inside_a_minute(tmp_path):
    t = [1000.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s
    lim = SharedWindowLimiter(tmp_path / "thr.json", 4, 60.0, clock=lambda: t[0], sleep=sleep)
    for _ in range(4):
        lim.acquire()
    assert slept == []
    other = SharedWindowLimiter(tmp_path / "thr.json", 4, 60.0, clock=lambda: t[0], sleep=sleep)   # a second process, same file
    other.acquire()
    assert slept and 59 < sum(slept) < 61
    assert not (tmp_path / "thr.json.lock").exists()


def test_plan_window_asks_only_for_the_missing_tail():
    end = et_midnight(NOW)
    assert plan_window(None, NOW, "1d") == (end - 725 * 86400, end)
    last = ts(2026, 10, 28)                     # last stored daily bar = Wed 28 Oct (event), ends Thu 00:00
    assert plan_window(last + 86400, NOW, "1d") is None            # Thursday is today and is never served
    assert plan_window(ts(2026, 10, 27) + 86400, NOW, "1d") == (ts(2026, 10, 28), end)
    mon = ts(2026, 11, 2, 17)                                       # Monday evening: Fri bar already stored, weekend skipped
    assert plan_window(ts(2026, 10, 30) + 86400, mon, "1d") is None


def test_jobs_put_the_priority_tickers_first_and_daily_before_intraday_for_the_rest():
    js = jobs(None, ["ZZZ", "OKLO", "AAPL", "YYY", "SPY"])
    assert js[:4] == [("AAPL", "1d"), ("AAPL", "15m"), ("SPY", "1d"), ("SPY", "15m")]
    assert js[-4:] == [("ZZZ", "1d"), ("YYY", "1d"), ("ZZZ", "15m"), ("YYY", "15m")]
    assert PRIORITY[:3] == ("AAPL", "SPY", "QQQ") and {"ROK", "CEG", "OKLO", "VST", "RKLB", "SOFI", "ENPH"} <= set(PRIORITY)


def test_run_backfills_then_is_idempotent_and_builds_1h(tmp_path):
    d1, d2 = ts(2026, 10, 27), ts(2026, 10, 28)
    daily = {"results": [row(d1 * 1000), row(d2 * 1000, 1.6)]}
    intraday = {"results": [row(ts(2026, 10, 28, h, m) * 1000) for h in (9, 10, 11) for m in (0, 15, 30, 45)]}

    class Routes(Http):
        def __call__(self, url, headers):
            self.calls.append((url, dict(headers)))
            body = daily if "/range/1/day/" in url else intraday
            return 200, {}, json.dumps(body).encode()
    http = Routes([])
    a = PolygonAdapter(transport=http, env={"MASSIVE_API_KEY": KEY}, clock=lambda: NOW, sleep=lambda s: None,
                       limiter=RateLimiter(1000, sleep=lambda s: None))
    feed = AtlasFeed(store=FeedStore(":memory:"), registry=ProviderRegistry([a]), clock=lambda: NOW)
    rows = run(feed, ["AAPL"], "A", now=NOW)
    assert [r["interval"] for r in rows] == ["1d", "15m"] and rows[0]["bars"] == 2 and rows[0]["status"] == "ok"
    assert rows[1]["bars"] == 10 and rows[1]["inserted_1h"] >= 1       # 09:30-11:45 are regular-session bars
    n = len(http.calls)
    rows2 = run(feed, ["AAPL"], "A", now=NOW)
    assert len(http.calls) == n and [r["status"] for r in rows2] == ["up_to_date"] * 2   # a re-run spends no quota
    assert materialize_1h(feed, "AAPL", NOW) == 0                       # deterministic: nothing new to insert
    h1 = feed.store.bars("AAPL", "1h", provider="polygon")
    assert h1 and all(b.event_time % 3600 == 1800 for b in h1)


# ---- 1-minute stock bars (T+1) ----
def _day_1m(y, m, d, c0=100.0):
    """A full regular session of 1m rows plus pre/post-market rows the adapter must drop (390 kept)."""
    rows = [row(ts(y, m, d, 8, 0) * 1000), row(ts(y, m, d, 9, 29) * 1000)]
    rows += [{"t": (ts(y, m, d, 9, 30) + 60 * i) * 1000, "o": c0 + i * 0.01, "h": c0 + i * 0.01 + 0.5, "l": c0 + i * 0.01 - 0.5, "c": c0 + i * 0.01 + 0.1, "v": 10 + i} for i in range(390)]
    rows += [row(ts(y, m, d, 16, 0) * 1000), row(ts(y, m, d, 19, 59) * 1000)]
    return rows


def _feed_1m(http_rows, now=NOW):
    class Routes(Http):
        def __call__(self, url, headers):
            self.calls.append((url, dict(headers)))
            return 200, {}, json.dumps({"results": http_rows if "/range/1/minute/" in url else []}).encode()
    http = Routes([])
    a = PolygonAdapter(transport=http, env={"MASSIVE_API_KEY": KEY}, clock=lambda: now, sleep=lambda s: None, limiter=RateLimiter(1000, sleep=lambda s: None))
    return AtlasFeed(store=FeedStore(":memory:"), registry=ProviderRegistry([a]), clock=lambda: now), http


def test_1m_phase_d_keeps_390_rth_bars_never_today_and_is_idempotent():
    feed, http = _feed_1m(_day_1m(2026, 10, 28))
    rows = run(feed, ["AAPL"], "D", now=NOW)
    assert [(r["interval"], r["status"], r["bars"]) for r in rows] == [("1m", "ok", 390)]
    bars = feed.store.bars("AAPL", "1m", provider="polygon")
    assert bars[0].event_time == ts(2026, 10, 28, 9, 30) and bars[-1].bar_end == ts(2026, 10, 28, 16, 0)
    assert all(b.bar_end - b.event_time == 60 for b in bars)
    to_ms = int(http.calls[0][0].split("/range/1/minute/")[1].split("/")[1].split("?")[0])
    assert to_ms <= et_midnight(NOW) * 1000 - 1                      # T+1: the current ET day is never requested
    n = len(http.calls)
    assert run(feed, ["AAPL"], "D", now=NOW)[0]["status"] == "up_to_date" and len(http.calls) == n


def test_1m_aggregates_to_15m_bars_that_line_up_with_the_session():
    from atlas.feeds.aggregate import aggregate
    feed, _ = _feed_1m(_day_1m(2026, 10, 28))
    run(feed, ["AAPL"], "D", now=NOW)
    one = feed.store.bars("AAPL", "1m", provider="polygon")
    f15 = [b for b in aggregate(one, "15m", NOW) if b.confirmed]
    assert len(f15) == 26 and f15[0].event_time == ts(2026, 10, 28, 9, 30)
    assert f15[0].open == one[0].open and f15[0].close == one[14].close
    assert f15[0].high == max(b.high for b in one[:15]) and f15[0].volume == sum(b.volume for b in one[:15])


def test_1m_universe_window_and_phases(monkeypatch):
    monkeypatch.delenv("ATLAS_STOCK_1M", raising=False)
    monkeypatch.delenv("ATLAS_STOCK_1M_DAYS", raising=False)
    ids = ["ZZZ", "AAPL", "SPY"]
    assert stock_1m_universe(ids) == ["AAPL", "SPY"] and window_days("1m") == 60 and window_days("15m") == 725
    assert jobs(None, ids, "D") == [("AAPL", "1m"), ("SPY", "1m")]
    assert not [j for j in jobs(None, ids, "ABC") if j[1] == "1m"]
    monkeypatch.setenv("ATLAS_STOCK_1M", "all")
    monkeypatch.setenv("ATLAS_STOCK_1M_DAYS", "10")
    assert stock_1m_universe(ids) == ids and window_days("1m") == 10
    end = et_midnight(NOW)
    assert plan_window(None, NOW, "1m") == (end - 10 * 86400, end)
    monkeypatch.setenv("ATLAS_STOCK_1M_DAYS", "bad")
    assert window_days("1m") == 60
