"""Orchestration for the News feature: watchlist, refresh (collect + annotate), feed assembly, status. No order path; advisory only."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from atlas.news import annotate as A
from atlas.news import llm as L
from atlas.news import reviewer as RV
from atlas.news import sources as SRC
from atlas.news import store as S

MAX_WATCH, MIN_GAP_S, FEED_DAYS = 40, 60.0, 14
_LAST: dict[str, float] = {}
_LOCK = threading.Lock()


def stock_names() -> dict[str, str]:
    from atlas.feeds.universe import STOCKS
    from atlas.marketdata.catalog import FLAGSHIP_EQUITIES, NAMED_EQUITY_DIRECTORY
    names = {r[0]: r[1] for r in FLAGSHIP_EQUITIES}
    names.update({r[0]: r[1] for r in NAMED_EQUITY_DIRECTORY})
    keep = set(STOCKS)
    return {k: v for k, v in names.items() if k in keep}


def valid_tickers(ts: list[str]) -> tuple[list[str], list[str]]:
    names = stock_names()
    good, bad = [], []
    for t in ts:
        u = str(t).strip().upper()
        (good if u in names else bad).append(u)
    return list(dict.fromkeys(good))[:MAX_WATCH], bad


def status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from atlas.ext import keyless_context as K
    from atlas.accounts.credentials import effective_environ
    e = dict(env) if env is not None else dict(effective_environ())
    scope = S.current_scope()
    srcs = [s for s in K.sources_status(e) if s["id"] in ("sec_edgar", "gdelt", *SRC.MACRO_FEEDS)]
    return {"scope": scope, "llm": L.llm_status(), "reviewer": {"mode": RV.mode(e), "eligibility": RV.gate_eligibility(scope)},
            "sources": srcs, "counts": S.counts(), "watchlist": S.get_watchlist(scope), "execution_permission": "none"}


def refresh(tickers: list[str] | None = None, annotate_llm: bool = True, env: Mapping[str, str] | None = None, fetch: Callable | None = None,
            cik_lookup: Callable | None = None, llm: L.LLM | None = None, llm_info: Mapping[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    scope = S.current_scope()
    ts, bad = valid_tickers(tickers if tickers is not None else S.get_watchlist(scope))
    if not ts:
        return {"status": "empty_watchlist", "reason": "Add tickers to your watchlist first (PUT /api/news/watchlist).", "invalid": bad, "execution_permission": "none"}
    with _LOCK:
        if fetch is None and now - _LAST.get(scope, 0.0) < MIN_GAP_S:
            return {"status": "throttled", "reason": f"refreshed {int(now - _LAST[scope])}s ago; sources are rate-limited (GDELT: 1 request / 5 s)", "execution_permission": "none"}
        _LAST[scope] = now
    names = stock_names()
    rep = SRC.collect(ts, now, env, fetch, cik_lookup, {t: names.get(t, t) for t in ts})
    items = S.items_for([*ts, "*"], since=now - 7 * 86400, until=now, limit=300)
    info = llm_info
    if annotate_llm and llm is None:
        llm, info = L.get_llm(env)
    ann = A.annotate(items, scope, llm if annotate_llm else None, (info or {}).get("model"), now)
    return {"status": "ok", "tickers": ts, "invalid": bad, "collect": rep, "annotate": ann, "llm": info or {"enabled": False}, "execution_permission": "none"}


def _pick(anns: list[dict[str, Any]]) -> dict[str, Any]:
    rules = next((a for a in anns if a["analyzer"] == "rules"), None)
    llm = next((a for a in anns if a["analyzer"] == "llm"), None)
    flags = {f["type"]: f for a in anns for f in a["hype_flags"]}
    base = llm or rules or {}
    return {"event_type": base.get("event_type") or (rules or {}).get("event_type"), "sentiment": (llm or {}).get("sentiment"), "materiality": (llm or {}).get("materiality"),
            "grounded": bool(llm and llm["grounded"]), "evidence_quote": (llm or {}).get("evidence_quote"), "rationale": (llm or {}).get("rationale"),
            "hype_flags": list(flags.values()), "analyzer": "llm" if llm else ("rules" if rules else None), "model": (llm or {}).get("model")}


def feed(tickers: list[str] | None = None, limit: int = 80, days: int = FEED_DAYS, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    scope = S.current_scope()
    wl = S.get_watchlist(scope)
    ts = [t for t in (tickers or wl) if t]
    items = S.items_for([*ts, "*"], since=now - days * 86400, until=now, limit=limit)
    ann = S.annotations_for([(i["id"], i["ticker"]) for i in items], scope)
    revs = RV.reviews_for(scope, limit=100)
    by_url: dict[str, list[dict[str, Any]]] = {}
    for r in revs:
        cited = {s["url"] for s in r["sources"] if s.get("id") in r["citations"] and s.get("url")}
        for u in cited:
            by_url.setdefault(u, []).append({"review_id": r["review_id"], "verdict": r["verdict"], "side": r["side"], "symbol": r["symbol"], "ts": r["ts"], "applied": r["applied"]})
    out = []
    for i in items:
        out.append({"id": i["id"], "ticker": i["ticker"], "source": i["source"], "tier": i["tier"], "tier_label": "official" if i["tier"] == 1 else "unverified news",
                    "kind": i["kind"], "published_at": i["published_at"], "url": i["url"], "title": i["title"], "form": i["form"], "gdelt_tone": i["tone"],
                    "annotation": _pick(ann.get((i["id"], i["ticker"]), [])), "reviewer": by_url.get(i["url"], [])})
    reason = None
    if not out:
        reason = ("Your watchlist is empty." if not wl and not tickers else "Nothing collected yet: press Refresh. EDGAR needs ATLAS_SEC_USER_AGENT; GDELT and official RSS need no key.")
    return {"status": "ok" if out else "empty", "reason": reason, "scope": scope, "watchlist": wl, "items": out, "recent_reviews": revs[:10], "llm": L.llm_status(), "execution_permission": "none"}
