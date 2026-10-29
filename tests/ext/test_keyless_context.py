"""Keyless official context: calendar / EDGAR / GDELT / RSS parse real-shaped payloads, report failures honestly, never invent items."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from atlas.ext import keyless_context as kc

NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=kc.NY).timestamp()

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261106T083000
SUMMARY:Employment Situation
CATEGORIES:IMPORTANT, BLS
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20260101T083000
SUMMARY:Old release
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20261112T083000
SUMMARY:Consumer Price Index\\, monthly
END:VEVENT
END:VCALENDAR
"""
TREAS = {"data": [{"auction_date": "2026-11-03", "security_type": "Bill", "security_term": "4-Week", "offering_amt": "null", "cusip": "912797AB1"}]}
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><item><title>FOMC statement</title><link>https://example.gov/a</link><pubDate>Wed, 28 Oct 2026 14:00:00 GMT</pubDate></item></channel></rss>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><item><title>BoC holds</title><link>https://b.ca/x</link><dc:date>2026-10-28T09:45:00-04:00</dc:date></item></rdf:RDF>"""


@pytest.fixture(autouse=True)
def clear():
    kc._CACHE.clear()


def fake(routes):
    calls = []

    def f(url, headers):
        calls.append(url)
        for k, v in routes.items():
            if k in url:
                return v if isinstance(v, tuple) else (200, v)
        return 404, b""
    f.calls = calls
    return f


def test_calendar_merges_official_sources_and_marks_fred_needs_key():
    f = fake({"bls.ics": ICS.encode(), "upcoming_auctions": json.dumps(TREAS).encode()})
    out = kc.economic_calendar(NOW, 14, env={}, fetch=f)
    titles = [e["title"] for e in out["events"]]
    assert titles == ["Treasury auction: 4-Week Bill", "Employment Situation", "Consumer Price Index, monthly"]
    assert "Old release" not in titles
    first = out["events"][1]
    assert first["source"] == "bls" and first["important"] is True and first["when_toronto"].startswith("2026-11-06 08:30") and first["when_utc"] == "2026-11-06T13:30:00Z"
    assert out["events"][0]["detail"]["offering_amt"] is None          # "null" is not turned into a number
    fred = next(s for s in out["sources"] if s["id"] == "fred")
    assert fred["status"] == "needs_key" and "Verify" in fred["reason"]
    assert not any("stlouisfed" in c for c in f.calls)                  # no key -> FRED never contacted
    assert out["execution_permission"] == "none"


def test_calendar_source_failure_is_reported_not_hidden():
    f = fake({"bls.ics": (503, b""), "upcoming_auctions": json.dumps({"data": []}).encode()})
    out = kc.economic_calendar(NOW, 14, env={}, fetch=f)
    bls = next(s for s in out["sources"] if s["id"] == "bls")
    tr = next(s for s in out["sources"] if s["id"] == "treasury")
    assert bls["status"] == "error" and "503" in bls["reason"]
    assert tr["status"] == "ok" and "no events" in tr["reason"] and out["events"] == []


def test_fred_used_only_when_key_present():
    f = fake({"bls.ics": ICS.encode(), "upcoming_auctions": b'{"data":[]}', "releases/dates": json.dumps({"release_dates": [{"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-11-12"}]}).encode()})
    out = kc.economic_calendar(NOW, 30, env={"FRED_API_KEY": "abcdef0123456789abcdef0123456789"}, fetch=f)
    assert any(e["source"] == "fred" for e in out["events"])
    assert "abcdef0123456789" not in json.dumps(out)                    # the key never appears in the payload (urls are not echoed with params)


def test_calendar_cache_avoids_refetch():
    f = fake({"bls.ics": ICS.encode(), "upcoming_auctions": b'{"data":[]}'})
    kc.economic_calendar(NOW, 14, env={}, fetch=f)
    n = len(f.calls)
    kc.economic_calendar(NOW + 60, 14, env={}, fetch=f)
    assert len(f.calls) == n


def test_edgar_needs_user_agent_and_never_fetches_without_it():
    f = fake({})
    out = kc.edgar_filings("AAPL", env={}, fetch=f)
    assert out["status"] == "needs_config" and f.calls == [] and "ATLAS_SEC_USER_AGENT" in out["source"]["reason"]


def test_edgar_ticker_filings_parse_and_filter_forms():
    subs = {"filings": {"recent": {"form": ["8-K", "SC 13G", "10-Q"], "filingDate": ["2026-10-20", "2026-10-19", "2026-08-01"], "accessionNumber": ["0000320193-26-000010", "0000320193-26-000009", "0000320193-26-000008"],
                                   "primaryDocument": ["a.htm", "b.htm", "c.htm"], "primaryDocDescription": ["Current report", "", "Quarterly"], "acceptanceDateTime": ["2026-10-20T16:01:00.000Z", "", ""]}}}
    f = fake({"company_tickers": json.dumps({"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}).encode(), "submissions/CIK0000320193": json.dumps(subs).encode()})
    out = kc.edgar_filings("aapl", env={"ATLAS_SEC_USER_AGENT": "ATLASResearch ops@example.com"}, fetch=f, now=NOW)
    assert out["status"] == "ok" and [i["form"] for i in out["items"]] == ["8-K", "10-Q"]
    assert out["items"][0]["url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/a.htm"
    none = kc.edgar_filings("ZZZZ", env={"ATLAS_SEC_USER_AGENT": "ATLASResearch ops@example.com"}, fetch=f, now=NOW)
    assert none["status"] == "unknown_ticker" and none["items"] == []


def test_gdelt_parses_and_rate_limit_is_honest():
    js = {"articles": [{"title": "Fed holds rates", "url": "https://x/y", "domain": "x", "language": "English", "seendate": "20261029T120000Z", "tone": "-1.5"}]}
    out = kc.gdelt_headlines("federal reserve", "1d", 5, now=NOW, fetch=fake({"gdeltproject": json.dumps(js).encode()}))
    assert out["status"] == "ok" and out["items"][0]["tone"] == -1.5 and out["items"][0]["title"] == "Fed holds rates"
    kc._CACHE.clear()
    lim = kc.gdelt_headlines("federal reserve", "1d", 5, now=NOW, fetch=fake({"gdeltproject": (429, b"")}))
    assert lim["status"] == "rate_limited" and lim["items"] == []
    bad = kc.gdelt_headlines("x", "1d", 5, now=NOW, fetch=fake({"gdeltproject": b"Your query was too short"}))
    assert bad["status"] == "error" and bad["items"] == []
    assert kc.gdelt_headlines("", fetch=fake({}))["status"] == "error"


def test_rss_rss2_and_rdf_and_unknown_feed():
    a = kc.rss_headlines("fed_press", now=NOW, fetch=fake({"press_all": RSS}))
    assert a["items"][0]["title"] == "FOMC statement" and a["items"][0]["when_toronto"] == "2026-10-28 10:00 EDT"
    b = kc.rss_headlines("boc_press", now=NOW, fetch=fake({"bankofcanada": RDF}))
    assert b["items"][0]["title"] == "BoC holds" and b["items"][0]["ts"] is not None
    assert kc.rss_headlines("nope")["status"] == "error"
    assert kc.rss_headlines("sec_press", now=NOW, fetch=fake({"pressreleases": (500, b"")}))["status"] == "error"


def test_fetcher_only_talks_https_to_official_hosts():
    for bad in ("http://www.bls.gov/x", "https://evil.example.com/x", "https://bls.gov.evil.com/x", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            kc._default_fetch(bad, {})


def test_endpoints_are_read_only_context(monkeypatch):
    from atlas.api.app import app
    monkeypatch.setattr(kc, "_default_fetch", fake({"press_all": RSS}))
    c = TestClient(app)
    s = c.get("/api/context/sources").json()
    assert {x["id"] for x in s["sources"]} >= {"bls", "treasury", "fred", "sec_edgar", "gdelt", "fed_press"} and s["execution_permission"] == "none"
    assert next(x for x in s["sources"] if x["id"] == "fred")["state"] == "needs_verification"
    assert c.get("/api/context/rss?source=fed_press&fresh=true").json()["items"][0]["title"] == "FOMC statement"
    assert c.post("/api/context/rss").status_code == 405
