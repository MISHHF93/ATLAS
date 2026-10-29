"""/api/context/*: keyless official macro + news context (economic calendar, EDGAR filings, GDELT headlines, official RSS).
Read-only, no secrets, execution_permission none. See atlas.ext.keyless_context."""
from __future__ import annotations

from fastapi import APIRouter, Query

from atlas.ext import keyless_context as kc

router = APIRouter()


@router.get("/sources")
def sources() -> dict:
    """What context sources exist and which still need verification. No network calls."""
    return {"sources": kc.sources_status(), "rss": {k: v["title"] for k, v in kc.RSS_SOURCES.items()}, "execution_permission": "none"}


@router.get("/calendar")
def calendar(days: int = Query(14, ge=1, le=60), fresh: bool = False) -> dict:
    return kc.economic_calendar(days=days, fresh=fresh)


@router.get("/filings")
def filings(ticker: str | None = Query(None, max_length=12), forms: str = Query("8-K,10-K,10-Q,4", max_length=40), limit: int = Query(15, ge=1, le=50)) -> dict:
    return kc.edgar_filings(ticker, tuple(f.strip().upper() for f in forms.split(",") if f.strip()), limit)


@router.get("/news")
def news(query: str = Query("federal reserve OR inflation OR earnings", max_length=120), timespan: str = Query("1d", max_length=5), limit: int = Query(15, ge=1, le=50), fresh: bool = False) -> dict:
    return kc.gdelt_headlines(query, timespan, limit, fresh=fresh)


@router.get("/rss")
def rss(source: str = Query("fed_press", max_length=20), limit: int = Query(12, ge=1, le=40), fresh: bool = False) -> dict:
    return kc.rss_headlines(source, limit, fresh=fresh)
