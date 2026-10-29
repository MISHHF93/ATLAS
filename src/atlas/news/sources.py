"""Collect per-ticker news items from FREE, OFFICIAL / open sources only, through the existing allow-listed fetcher in
``atlas.ext.keyless_context`` (https only, fixed hosts, per-host rate limit, size cap). No key is read or set here.

* SEC EDGAR submissions (needs ``ATLAS_SEC_USER_AGENT``, a contact string under the SEC fair-access policy; without it nothing is requested)
* GDELT DOC 2.0 article list (open, 1 request / 5 s; third-party news, so tier 2 = unverified)
* Official RSS (Federal Reserve, SEC, Bank of Canada) as market-wide ``*`` items
Every item keeps the source's own URL and publication time (point-in-time). Nothing is summarised or invented here."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Callable, Mapping

from atlas.ext import keyless_context as K
from atlas.news import store as S

TIER_OFFICIAL, TIER_NEWS = 1, 2
EDGAR_FORMS = ("8-K", "10-K", "10-Q", "6-K", "20-F", "S-1", "S-3", "424B5", "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A", "144", "DEF 14A")
GDELT_SPAN, GDELT_LIMIT, EDGAR_LIMIT = "3d", 40, 50
MACRO_FEEDS = ("fed_press", "fed_monetary", "sec_press", "boc_press")
_SUFFIX = re.compile(r"\b(inc|incorporated|corporation|corp|company|co|holdings?|limited|ltd|plc|n\.v|s\.a|se|group|technologies|class [a-c])\b\.?", re.I)


def short_name(name: str) -> str:
    return re.sub(r"\s+", " ", _SUFFIX.sub(" ", re.sub(r"[,.]", " ", name or ""))).strip()


def _seen(s: str | None) -> float | None:
    try:
        return dt.datetime.strptime(s or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def _iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def edgar_rows(ticker: str, now: float, env: Mapping[str, str] | None = None, fetch: Callable | None = None, cik_lookup: Callable | None = None) -> tuple[list[dict], dict]:
    r = K.edgar_filings(ticker, forms=EDGAR_FORMS, limit=EDGAR_LIMIT, now=now, env=env, fetch=fetch, cik_lookup=cik_lookup)
    src = {"id": "sec_edgar", "ticker": ticker, "status": r["status"], "reason": (r.get("source") or {}).get("reason", ""), "n": 0}
    rows: list[dict] = []
    for it in r.get("items", []):
        ts = _iso(it.get("accepted")) or _iso(it.get("filed"))
        if ts is None or not it.get("url"):
            continue   # no publication time -> cannot be point-in-time -> not stored
        codes = it.get("codes")
        title = f"{it['form']}: {it['title']}" + (f" (items {codes})" if codes else "")
        rows.append({"id": S.item_id("edgar", it["url"]), "ticker": ticker, "source": "sec_edgar", "tier": TIER_OFFICIAL, "kind": "filing", "published_at": ts,
                     "url": it["url"], "title": title[:300], "form": it["form"], "codes": codes, "tone": None, "domain": "sec.gov", "content_hash": S.content_hash(title, it["url"])})
    src["n"] = len(rows)
    if r["status"] == "ok":
        full = len(r.get("items", [])) >= EDGAR_LIMIT
        S.set_coverage(ticker, "sec_edgar", min(x["published_at"] for x in rows) if (full and rows) else now - 365 * 86400, now)
    return rows, src


def gdelt_rows(ticker: str, name: str, now: float, fetch: Callable | None = None) -> tuple[list[dict], dict]:
    q = f'"{short_name(name) or ticker}" (stock OR shares OR earnings OR SEC)'
    r = K.gdelt_headlines(q, timespan=GDELT_SPAN, limit=GDELT_LIMIT, now=now, fetch=fetch)
    src = {"id": "gdelt", "ticker": ticker, "status": r["status"], "reason": (r.get("source") or {}).get("reason", ""), "n": 0, "query": q}
    rows = []
    for a in r.get("items", []):
        ts, url = _seen(a.get("seen")), a.get("url")
        if ts is None or not url or not a.get("title"):
            continue
        rows.append({"id": S.item_id("gdelt", url), "ticker": ticker, "source": "gdelt", "tier": TIER_NEWS, "kind": "news", "published_at": ts, "url": url, "title": a["title"],
                     "form": None, "codes": None, "tone": a.get("tone"), "domain": a.get("domain"), "content_hash": S.content_hash(a["title"], url)})
    src["n"] = len(rows)
    if r["status"] == "ok":
        full = len(r.get("items", [])) >= GDELT_LIMIT
        S.set_coverage(ticker, "gdelt", min(x["published_at"] for x in rows) if (full and rows) else now - 3 * 86400, now)
    return rows, src


def macro_rows(now: float, fetch: Callable | None = None) -> tuple[list[dict], list[dict]]:
    rows, srcs = [], []
    for fid in MACRO_FEEDS:
        r = K.rss_headlines(fid, limit=25, now=now, fetch=fetch)
        srcs.append({"id": fid, "ticker": "*", "status": r["status"], "reason": (r.get("source") or {}).get("reason", ""), "n": 0})
        for it in r.get("items", []):
            if it.get("ts") is None or not it.get("url") or not it.get("title"):
                continue
            rows.append({"id": S.item_id(fid, it["url"]), "ticker": "*", "source": fid, "tier": TIER_OFFICIAL, "kind": "macro", "published_at": it["ts"], "url": it["url"],
                         "title": it["title"], "form": None, "codes": None, "tone": None, "domain": fid, "content_hash": S.content_hash(it["title"], it["url"])})
            srcs[-1]["n"] += 1
    return rows, srcs


def collect(tickers: list[str], now: float | None = None, env: Mapping[str, str] | None = None, fetch: Callable | None = None, cik_lookup: Callable | None = None,
            names: Mapping[str, str] | None = None, macro: bool = True) -> dict[str, Any]:
    """Fetch, store (idempotent) and report per-source status. A failing source says so; it is never silently an empty list."""
    now = time.time() if now is None else now
    names = names or {}
    rows: list[dict] = []
    sources: list[dict] = []
    for t in tickers:
        er, es = edgar_rows(t, now, env, fetch, cik_lookup)
        gr, gs = gdelt_rows(t, names.get(t, t), now, fetch)
        rows += er + gr
        sources += [es, gs]
    if macro:
        mr, ms = macro_rows(now, fetch)
        rows += mr
        sources += ms
    new = S.upsert_items(rows, now)
    return {"fetched": len(rows), "new": new, "sources": sources, "execution_permission": "none"}
