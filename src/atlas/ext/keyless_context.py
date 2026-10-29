"""Keyless, official, free macro and news context: an economic calendar (BLS + US Treasury), SEC EDGAR filings, GDELT headlines
and official RSS (Federal Reserve, SEC, Bank of Canada).

Rules this module keeps:
* No API key is required or read here, except FRED which is optional and reported ``needs_key`` until a verified key exists.
* Every item carries its source, its URL and when it was fetched. Nothing is estimated, scored or invented; if a source fails the
  result says so (status + reason) instead of returning an empty list that looks like "no events".
* Read-only, GET only, fixed official hosts, bounded size, in-memory cache, and a per-host rate limit (GDELT asks for one request
  per 5 seconds; SEC allows 10/s and needs a descriptive User-Agent from ATLAS_SEC_USER_AGENT).
* Context only: headlines and calendars never place an order (execution_permission none).
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
NY = ZoneInfo("America/New_York")
MAX_BYTES = 3_000_000
HOST_GAP_S = {"api.gdeltproject.org": 5.0, "www.sec.gov": 0.15, "data.sec.gov": 0.15}
CACHE_TTL_S = {"ics": 3600, "treasury": 3600, "rss": 600, "gdelt": 600, "edgar": 300}

Fetcher = Callable[[str, dict[str, str]], tuple[int, bytes]]

BLS_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_PAGE = "https://www.bls.gov/schedule/news_release/"
TREASURY = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/upcoming_auctions"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
EDGAR_CURRENT = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_SUBS = "https://data.sec.gov/submissions/CIK{cik}.json"
FRED_DATES = "https://api.stlouisfed.org/fred/releases/dates"

RSS_SOURCES: dict[str, dict[str, str]] = {
    "fed_press": {"title": "Federal Reserve: press releases", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "terms": "https://www.federalreserve.gov/feeds/feeds.htm"},
    "fed_monetary": {"title": "Federal Reserve: monetary policy", "url": "https://www.federalreserve.gov/feeds/press_monetary.xml", "terms": "https://www.federalreserve.gov/feeds/feeds.htm"},
    "sec_press": {"title": "SEC: press releases", "url": "https://www.sec.gov/news/pressreleases.rss", "terms": "https://www.sec.gov/about/privacy-information#intellectual-property"},
    "boc_press": {"title": "Bank of Canada: press releases", "url": "https://www.bankofcanada.ca/content_type/press-releases/feed/", "terms": "https://www.bankofcanada.ca/terms/"},
}

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, Any]] = {}
_LAST_HOST: dict[str, float] = {}


def _default_fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    host = urllib.parse.urlparse(url).hostname or ""
    if urllib.parse.urlparse(url).scheme != "https" or not any(host == h or host.endswith("." + h) for h in
                                                                 ("bls.gov", "fiscaldata.treasury.gov", "sec.gov", "gdeltproject.org", "federalreserve.gov", "bankofcanada.ca", "stlouisfed.org")):
        raise ValueError("host not allowed")
    gap = HOST_GAP_S.get(host, 0.0)
    with _LOCK:
        wait = _LAST_HOST.get(host, 0.0) + gap - time.time()
        _LAST_HOST[host] = time.time() + max(wait, 0.0)
    if wait > 0:
        time.sleep(min(wait, 6.0))
    req = urllib.request.Request(url, headers={"User-Agent": "ATLAS-context/1.0", **headers}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - https + allow-listed official hosts only
            return r.status, r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        return e.code, b""


def _cached(kind: str, key: str, fn: Callable[[], Any], now: float, fresh: bool = False):
    ttl = CACHE_TTL_S.get(kind, 300)
    hit = _CACHE.get(key)
    if hit and not fresh and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val.get("status") == "ok":
        _CACHE[key] = (now, val)
    return val


def _src(id: str, title: str, url: str, status: str, reason: str = "", n: int = 0, fetched: float | None = None, **extra) -> dict[str, Any]:
    return {"id": id, "title": title, "url": url, "status": status, "reason": reason, "count": n, "fetched_at": fetched, **extra}


def _toronto(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, TORONTO).strftime("%Y-%m-%d %H:%M %Z")


# ---------------------------------------------------------------- economic calendar
def parse_ics(text: str) -> list[dict[str, Any]]:
    """Minimal VEVENT reader for the BLS release schedule (UTC-normalised; TZID US-Eastern)."""
    text = re.sub(r"\r?\n[ \t]", "", text)
    out = []
    for blk in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        f: dict[str, str] = {}
        for line in blk.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                f.setdefault(k.split(";")[0], v)
        m = re.search(r"DTSTART[^:]*:(\d{8})(?:T(\d{6}))?(Z)?", blk)
        if not m:
            continue
        d, t = m.group(1), m.group(2) or "000000"
        try:
            local = dt.datetime.strptime(d + t, "%Y%m%d%H%M%S")
        except ValueError:
            continue
        when = local.replace(tzinfo=dt.timezone.utc if m.group(3) else NY)   # a trailing Z means UTC; otherwise the schedule's TZID is US-Eastern
        out.append({"ts": when.timestamp(), "title": f.get("SUMMARY", "").replace("\\,", ","), "important": "IMPORTANT" in f.get("CATEGORIES", ""), "all_day": m.group(2) is None})
    return out


def _bls(now: float, fetch: Fetcher, fresh: bool) -> dict[str, Any]:
    def go():
        st, body = fetch(BLS_ICS, {"Accept": "text/calendar"})
        if st != 200:
            return _src("bls", "US Bureau of Labor Statistics: release schedule", BLS_PAGE, "error", f"HTTP {st}")
        ev = parse_ics(body.decode("utf-8", "replace"))
        return {**_src("bls", "US Bureau of Labor Statistics: release schedule", BLS_PAGE, "ok", n=len(ev), fetched=now), "events": ev}
    return _cached("ics", "bls", go, now, fresh)


def _treasury(now: float, fetch: Fetcher, fresh: bool) -> dict[str, Any]:
    def go():
        today = dt.datetime.fromtimestamp(now, NY).date().isoformat()
        q = urllib.parse.urlencode({"filter": f"auction_date:gte:{today}", "sort": "auction_date", "page[size]": "100"})
        st, body = fetch(TREASURY + "?" + q, {"Accept": "application/json"})
        if st != 200:
            return _src("treasury", "US Treasury: upcoming auctions (FiscalData)", "https://fiscaldata.treasury.gov/datasets/upcoming-auctions/", "error", f"HTTP {st}")
        import json
        rows = json.loads(body).get("data", [])
        ev = []
        for r in rows:
            try:
                d = dt.datetime.strptime(r["auction_date"], "%Y-%m-%d").replace(hour=11, minute=30, tzinfo=NY)   # auction time is not in the dataset: date only
            except (KeyError, ValueError):
                continue
            amt = r.get("offering_amt")
            ev.append({"ts": d.timestamp(), "title": f"Treasury auction: {r.get('security_term', '')} {r.get('security_type', '')}".strip(), "important": False, "all_day": True,
                       "detail": {"offering_amt": amt if amt not in (None, "null") else None, "cusip": r.get("cusip")}})
        return {**_src("treasury", "US Treasury: upcoming auctions (FiscalData)", "https://fiscaldata.treasury.gov/datasets/upcoming-auctions/", "ok", n=len(ev), fetched=now), "events": ev}
    return _cached("treasury", "treasury", go, now, fresh)


def _fred(now: float, fetch: Fetcher, env: Mapping[str, str], fresh: bool) -> dict[str, Any]:
    title, url = "FRED: release dates", "https://fred.stlouisfed.org/releases/calendar"
    key = (env.get("FRED_API_KEY") or "").strip()
    if not key or key.startswith("<"):
        return _src("fred", title, url, "needs_key", "Needs verification: add FRED_API_KEY in Settings > Setup (free), then press Verify. Not used until then.",
                    signup="https://fredaccount.stlouisfed.org/apikeys")
    day = dt.datetime.fromtimestamp(now, NY).date()
    q = urllib.parse.urlencode({"api_key": key, "file_type": "json", "realtime_start": day.isoformat(), "realtime_end": (day + dt.timedelta(days=30)).isoformat(),
                                "include_release_dates_with_no_data": "true", "limit": "200", "sort_order": "asc", "order_by": "release_date"})
    st, body = fetch(FRED_DATES + "?" + q, {})
    if st != 200:
        return _src("fred", title, url, "error", f"HTTP {st} (key rejected or rate limited)")
    import json
    ev = []
    for r in json.loads(body).get("release_dates", []):
        try:
            ts = dt.datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=NY).timestamp()
        except (KeyError, ValueError):
            continue
        ev.append({"ts": ts, "title": r.get("release_name", "FRED release"), "important": False, "all_day": True})
    return {**_src("fred", title, url, "ok", n=len(ev), fetched=now), "events": ev}


def economic_calendar(now: float | None = None, days: int = 14, env: Mapping[str, str] | None = None, fetch: Fetcher | None = None, fresh: bool = False) -> dict[str, Any]:
    now = time.time() if now is None else now
    fetch = fetch or _default_fetch
    env = env if env is not None else _env()
    days = max(1, min(int(days), 60))
    start, end = now - 3600, now + days * 86400
    sources, events = [], []
    for fn in (lambda: _bls(now, fetch, fresh), lambda: _treasury(now, fetch, fresh), lambda: _fred(now, fetch, env, fresh)):
        try:
            s = dict(fn())   # a copy: the cached source dict must keep its events for the next call
        except Exception as ex:  # noqa: BLE001 - one source failing never hides the others
            s = _src("?", "source", "", "error", f"{type(ex).__name__}: {str(ex)[:120]}")
        evs = s.pop("events", [])
        win = [e for e in evs if start <= e["ts"] <= end]
        for e in win:
            events.append({**e, "source": s["id"], "source_url": s["url"], "when_toronto": _toronto(e["ts"]), "when_utc": dt.datetime.fromtimestamp(e["ts"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        if s["status"] == "ok" and not win:
            s["reason"] = f"source reachable but lists no events in the next {days} days"
        s["in_window"] = len(win)
        sources.append(s)
    events.sort(key=lambda e: e["ts"])
    return {"as_of": now, "as_of_toronto": _toronto(now), "timezone": "America/Toronto", "window_days": days, "events": events, "sources": sources,
            "note": "Official release schedules only. Importance is shown only where the source flags it (BLS). Auction times are not published in the dataset (date only).",
            "execution_permission": "none"}


# ---------------------------------------------------------------- EDGAR
def _env() -> Mapping[str, str]:
    from atlas.accounts.credentials import effective_environ
    return effective_environ()


def _ua(env: Mapping[str, str]) -> str | None:
    from atlas.marketdata.sec_edgar import validate_sec_user_agent
    try:
        return validate_sec_user_agent(env.get("ATLAS_SEC_USER_AGENT") or "")
    except ValueError:
        return None


def edgar_filings(ticker: str | None = None, forms: tuple[str, ...] = ("8-K", "10-K", "10-Q", "4"), limit: int = 20, now: float | None = None,
                  env: Mapping[str, str] | None = None, fetch: Fetcher | None = None, cik_lookup: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    env = env if env is not None else _env()
    fetch = fetch or _default_fetch
    limit = max(1, min(int(limit), 50))
    base = {"as_of": now, "as_of_toronto": _toronto(now), "ticker": (ticker or "").upper() or None, "execution_permission": "none"}
    ua = _ua(env)
    if not ua:
        return {**base, "status": "needs_config", "items": [], "source": _src("sec_edgar", "SEC EDGAR", "https://www.sec.gov/edgar/search/", "needs_key",
                "Needs verification: set ATLAS_SEC_USER_AGENT to 'AppName you@example.com' (no key; SEC fair-access policy), then press Verify.")}
    import json
    try:
        if ticker:
            sym = re.sub(r"[^A-Za-z.\-]", "", ticker).upper()[:10]
            cik = cik_lookup(sym) if cik_lookup else _cik(sym, fetch, {"User-Agent": ua}, now)
            if not cik:
                return {**base, "status": "unknown_ticker", "items": [], "source": _src("sec_edgar", "SEC EDGAR", "https://www.sec.gov/edgar/search/", "ok", f"{sym} is not in the SEC ticker list (non-US or not an SEC registrant)")}
            st, body = fetch(EDGAR_SUBS.format(cik=str(cik).zfill(10)), {"User-Agent": ua, "Accept": "application/json"})
            if st != 200:
                return {**base, "status": "error", "items": [], "source": _src("sec_edgar", "SEC EDGAR submissions", EDGAR_SUBS.format(cik=str(cik).zfill(10)), "error", f"HTTP {st}")}
            rec = json.loads(body).get("filings", {}).get("recent", {})
            items = []
            for i, form in enumerate(rec.get("form", [])):
                if forms and form not in forms:
                    continue
                acc = rec["accessionNumber"][i]
                doc = rec.get("primaryDocument", [""] * (i + 1))[i]
                items.append({"form": form, "filed": rec["filingDate"][i], "accepted": rec.get("acceptanceDateTime", [""] * (i + 1))[i] or None, "title": rec.get("primaryDocDescription", [""] * (i + 1))[i] or form,
                              "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"})
                if len(items) >= limit:
                    break
            return {**base, "status": "ok", "items": items, "source": _src("sec_edgar", "SEC EDGAR submissions", EDGAR_SUBS.format(cik=str(cik).zfill(10)), "ok", n=len(items), fetched=now)}
        q = urllib.parse.urlencode({"action": "getcurrent", "type": "8-K", "count": str(limit), "output": "atom"})
        st, body = fetch(EDGAR_CURRENT + "?" + q, {"User-Agent": ua})
        if st != 200:
            return {**base, "status": "error", "items": [], "source": _src("sec_edgar", "SEC EDGAR latest filings", EDGAR_CURRENT, "error", f"HTTP {st}")}
        items = _atom(body)[:limit]
        return {**base, "status": "ok", "items": items, "source": _src("sec_edgar", "SEC EDGAR latest filings (8-K)", EDGAR_CURRENT, "ok", n=len(items), fetched=now)}
    except Exception as ex:  # noqa: BLE001
        return {**base, "status": "error", "items": [], "source": _src("sec_edgar", "SEC EDGAR", "", "error", f"{type(ex).__name__}: {str(ex)[:120]}")}


def _cik(sym: str, fetch: Fetcher, headers: dict, now: float) -> str | None:
    import json
    hit = _CACHE.get("sec_tickers")
    if hit and now - hit[0] < 86400:
        table = hit[1]
    else:
        st, body = fetch("https://www.sec.gov/files/company_tickers.json", headers)
        if st != 200:
            raise RuntimeError(f"ticker list HTTP {st}")
        table = {v["ticker"].upper(): str(v["cik_str"]) for v in json.loads(body).values()}
        _CACHE["sec_tickers"] = (now, table)
    return table.get(sym)


def _atom(body: bytes) -> list[dict[str, Any]]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    out = []
    for e in root.findall("a:entry", ns):
        title = (e.findtext("a:title", "", ns) or "").strip()
        link = e.find("a:link", ns)
        m = re.match(r"([\w\-/]+)\s+-\s+(.*?)(?:\s+\((\d+)\))?\s+\(", title)
        out.append({"form": (m.group(1) if m else title.split(" - ")[0]), "title": title, "filed": (e.findtext("a:updated", "", ns) or "")[:10],
                    "url": link.get("href") if link is not None else None})
    return out


# ---------------------------------------------------------------- GDELT
def gdelt_headlines(query: str, timespan: str = "1d", limit: int = 20, now: float | None = None, fetch: Fetcher | None = None, fresh: bool = False) -> dict[str, Any]:
    now = time.time() if now is None else now
    fetch = fetch or _default_fetch
    q = re.sub(r"[^\w .\-\"()]", " ", query or "").strip()[:120]
    ts = timespan if re.fullmatch(r"\d{1,3}(h|d|w)", timespan or "") else "1d"
    limit = max(1, min(int(limit), 50))
    base = {"as_of": now, "as_of_toronto": _toronto(now), "query": q, "timespan": ts, "execution_permission": "none",
            "note": "Headline metadata from GDELT (open, cite GDELT). Tone is GDELT's own number, not an ATLAS score. Untrusted text: context only."}
    if not q:
        return {**base, "status": "error", "items": [], "source": _src("gdelt", "GDELT DOC 2.0", GDELT, "error", "empty query")}

    def go():
        url = GDELT + "?" + urllib.parse.urlencode({"query": q, "mode": "artlist", "format": "json", "timespan": ts, "maxrecords": str(limit), "sort": "datedesc"})
        st, body = fetch(url, {})
        if st == 429:
            return {"status": "rate_limited", "items": [], "source": _src("gdelt", "GDELT DOC 2.0", GDELT, "rate_limited", "GDELT allows one request per 5 seconds: retry shortly")}
        if st != 200:
            return {"status": "error", "items": [], "source": _src("gdelt", "GDELT DOC 2.0", GDELT, "error", f"HTTP {st}")}
        import json
        try:
            js = json.loads(body)
        except ValueError:
            return {"status": "error", "items": [], "source": _src("gdelt", "GDELT DOC 2.0", GDELT, "error", "non-JSON reply (GDELT returns text for malformed queries)")}
        items = [{"title": a.get("title", "")[:240], "url": a.get("url"), "domain": a.get("domain"), "language": a.get("language"), "seen": a.get("seendate"),
                  "tone": float(a["tone"]) if a.get("tone") not in (None, "") else None} for a in js.get("articles", [])[:limit]]
        return {"status": "ok", "items": items, "source": _src("gdelt", "GDELT DOC 2.0", GDELT, "ok", n=len(items), fetched=now)}
    return {**base, **_cached("gdelt", f"gdelt:{q}:{ts}:{limit}", go, now, fresh)}


# ---------------------------------------------------------------- RSS
def parse_feed(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    out = []
    for it in root.iter():
        tag = it.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        g = lambda n: next((c for c in it if c.tag.rsplit("}", 1)[-1] == n), None)  # noqa: E731
        title, link = g("title"), g("link")
        date = next((d for d in (g("pubDate"), g("date"), g("updated")) if d is not None), None)   # Element truthiness is child-count: compare with None
        href = (link.get("href") or link.text) if link is not None else None
        ts = None
        if date is not None and date.text:
            try:
                from email.utils import parsedate_to_datetime
                ts = parsedate_to_datetime(date.text).timestamp()
            except (TypeError, ValueError):
                try:
                    ts = dt.datetime.fromisoformat(date.text.strip().replace("Z", "+00:00")).timestamp()
                except ValueError:
                    ts = None
        out.append({"title": (title.text or "").strip()[:240] if title is not None else "", "url": (href or "").strip() or None, "ts": ts})
    return out


def rss_headlines(source: str = "fed_press", limit: int = 15, now: float | None = None, fetch: Fetcher | None = None, fresh: bool = False) -> dict[str, Any]:
    now = time.time() if now is None else now
    fetch = fetch or _default_fetch
    s = RSS_SOURCES.get(source)
    base = {"as_of": now, "as_of_toronto": _toronto(now), "execution_permission": "none", "available": {k: v["title"] for k, v in RSS_SOURCES.items()}}
    if s is None:
        return {**base, "status": "error", "items": [], "source": _src(source, "unknown feed", "", "error", "choose one of " + ", ".join(RSS_SOURCES))}

    def go():
        st, body = fetch(s["url"], {"Accept": "application/rss+xml, application/xml"})
        if st != 200:
            return {"status": "error", "items": [], "source": _src(source, s["title"], s["url"], "error", f"HTTP {st}")}
        items = parse_feed(body)[:max(1, min(int(limit), 40))]
        for i in items:
            i["when_toronto"] = _toronto(i["ts"]) if i["ts"] else None
        return {"status": "ok", "items": items, "source": _src(source, s["title"], s["url"], "ok", n=len(items), fetched=now, terms=s["terms"])}
    try:
        return {**base, **_cached("rss", f"rss:{source}", go, now, fresh)}
    except Exception as ex:  # noqa: BLE001
        return {**base, "status": "error", "items": [], "source": _src(source, s["title"], s["url"], "error", f"{type(ex).__name__}: {str(ex)[:120]}")}


def sources_status(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """What exists and what each needs. No network."""
    env = env if env is not None else _env()
    fred = bool((env.get("FRED_API_KEY") or "").strip()) and not (env.get("FRED_API_KEY") or "").startswith("<")
    return [
        {"id": "bls", "title": "BLS release schedule", "needs": None, "state": "keyless", "url": BLS_PAGE, "provides": "economic calendar"},
        {"id": "treasury", "title": "US Treasury auctions (FiscalData)", "needs": None, "state": "keyless", "url": "https://fiscaldata.treasury.gov/", "provides": "economic calendar"},
        {"id": "fred", "title": "FRED release dates", "needs": "FRED_API_KEY", "state": "needs_verification" if not fred else "key_present", "url": "https://fred.stlouisfed.org/releases/calendar", "provides": "economic calendar (more releases)"},
        {"id": "sec_edgar", "title": "SEC EDGAR filings", "needs": "ATLAS_SEC_USER_AGENT (a contact string, not a key)" if not _ua(env) else None,
         "state": "keyless" if _ua(env) else "needs_verification", "url": "https://www.sec.gov/edgar/search/", "provides": "filings"},
        {"id": "gdelt", "title": "GDELT headlines", "needs": None, "state": "keyless", "url": "https://www.gdeltproject.org/", "provides": "news headlines (1 request / 5 s)"},
        *[{"id": k, "title": v["title"], "needs": None, "state": "keyless", "url": v["url"], "provides": "official RSS"} for k, v in RSS_SOURCES.items()],
    ]
