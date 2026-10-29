"""Catalog coverage: for every asset the desk lists, which provider serves it, which env var it needs, and why a chart is empty.

This is the answer to "why does AAPL / gold / FX show no data?". It reads only metadata (the instrument master, the provider
manifests, the free-data policy gate and the store's latest bar), so it never calls a vendor and never needs a key.

Status per asset (strongest first):
  ok               an allowed, keyed provider is in the chain and the store holds a bar from one
  daily_only       only daily reference sources (ECB / Bank of Canada) can serve it: bars are 1d, labelled as such
  awaiting_data    a provider is usable but the store has no bar from it yet (run scripts/backfill_feeds.py or just open the chart)
  needs_key        every provider that could serve it needs a free key / account that is not configured
  policy_blocked   the only providers in the chain are paid or unofficial and the free-data gate refuses them
  no_provider      the instrument has no provider at all (a catalog bug, caught by tests/feeds/test_coverage.py)

Proxies (gold spot, indices) are shown as labelled stand-ins, never silently substituted.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

from .free_sources import SOURCES, allowed, delay_s, latency

# Spot / index names the desk accepts that have no direct free series: shown with the ETF or futures that stands in for them.
PROXIES: dict[str, dict[str, str]] = {
    "XAUUSD": {"instrument": "GC", "proxy": "GLD", "label": "Gold spot: GC futures need a paid feed; GLD (SPDR Gold Shares ETF) is the free stand-in"},
    "XAGUSD": {"instrument": "SI", "proxy": "SLV", "label": "Silver spot: SI futures need a paid feed; SLV (iShares Silver Trust) is the free stand-in"},
    "SPX": {"instrument": "ES", "proxy": "SPY", "label": "S&P 500 index: no free official intraday index feed; SPY is the stand-in"},
    "NDX": {"instrument": "NQ", "proxy": "QQQ", "label": "Nasdaq-100 index: QQQ is the stand-in"},
    "DJI": {"instrument": "YM", "proxy": "DIA", "label": "Dow Jones index: DIA is the stand-in"},
    "RUT": {"instrument": "RTY", "proxy": "IWM", "label": "Russell 2000 index: IWM is the stand-in"},
}

CLASS_LABEL = {"equity": "Stocks", "etf": "ETFs (incl. GLD, SLV)", "crypto": "Crypto", "future": "Futures (gold, indices, energy, rates)",
               "fx": "FX", "index": "Indices", "metal": "Metals"}


def _provider_row(feed, name: str, inst=None) -> dict[str, Any]:
    a = feed.registry.get(name)
    terms = SOURCES.get(name)
    policy_ok = allowed(name)
    keys_missing: list[str] = []
    if a is not None:
        a.refresh_env()
        keys_missing = [k for k in a.caps.auth_env if not a.env.get(k)]
    enabled = bool(a and a.enabled)
    if a is None:
        why = "not_registered"
    elif not policy_ok:
        why = ("paid_provider_off (ATLAS_ALLOW_PAID_DATA)" if terms and terms.cost == "paid" else "unofficial_endpoint_off (ATLAS_ALLOW_UNOFFICIAL_DATA)")
    elif keys_missing:
        why = "missing_env:" + ",".join(keys_missing)
    elif not enabled:
        why = (a.health().reason or "disabled") if a else "disabled"
    else:
        why = "ok"
    ivs = list(a.caps.intervals) if a else []
    plan = feed.plan_intervals(name, inst) if inst is not None else None
    if plan is not None:
        ivs = [i for i in ivs if i in plan]
    return {"provider": name, "cost": terms.cost if terms else "unknown", "latency": latency(name), "delay_s": delay_s(name),
            "intervals": ivs, "env": list(a.caps.auth_env) if a else [], "register": terms.register if terms else "",
            "policy_allowed": policy_ok, "keys_missing": keys_missing, "usable": policy_ok and enabled, "why": why}


def _fix(rows: list[dict], status: str) -> str:
    if status in ("ok", "awaiting_data", "daily_only"):
        return ""
    keyed = [r for r in rows if r["policy_allowed"] and r["keys_missing"]]
    if keyed:
        r = keyed[0]
        extra = f" (or {keyed[1]['provider']})" if len(keyed) > 1 else ""
        return (f"Needs verification: add a free {r['provider']} key{extra}: set {', '.join(r['keys_missing'])} in Settings > Setup, then press Verify"
                + (f" (sign up: {r['register']})" if r["register"] else ""))
    blocked = [r for r in rows if not r["policy_allowed"]]
    if blocked:
        return "Only paid or unofficial sources exist for this series; the free-data policy refuses them. Use the labelled free proxy."
    return "No provider is configured for this instrument."


def asset_coverage(feed, instrument_id: str, now: float | None = None) -> dict[str, Any]:
    from .status import toronto
    now = now or time.time()
    inst = feed.instruments.get(instrument_id)
    names = list(feed.chain(inst))
    rows = [_provider_row(feed, n, inst) for n in names]
    usable = [r for r in rows if r["usable"]]
    intervals = sorted({iv for r in usable for iv in r["intervals"]}, key=lambda x: ["1m", "5m", "15m", "1h", "4h", "1d"].index(x) if x in ["1m", "5m", "15m", "1h", "4h", "1d"] else 9)
    last = None
    try:
        for b in reversed(feed.bars(instrument_id, "1d", int(now - 400 * 86400), int(now) + 1)[-1:]):
            last = b
        for iv in ("1m", "15m", "1h"):
            bs = feed.bars(instrument_id, iv, int(now - 10 * 86400), int(now) + 1)[-1:]
            if bs and (last is None or bs[-1].event_time > last.event_time):
                last = bs[-1]
    except Exception:
        last = None
    daily_only = bool(usable) and intervals == ["1d"]
    if not rows:
        status = "no_provider"
    elif not usable:
        status = "policy_blocked" if all(not r["policy_allowed"] for r in rows) else "needs_key"
    elif last is not None:
        status = "daily_only" if daily_only else "ok"
    else:
        status = "awaiting_data"
    served = usable[0] if usable else None
    return {"instrument": instrument_id, "asset_class": inst.asset_class, "status": status,
            "served_by": served["provider"] if served else None, "intervals": intervals, "daily_only": daily_only,
            "delayed": bool(served and (served["delay_s"] or 0) > 0), "latency": served["latency"] if served else None,
            "chain": rows, "last_bar_interval": last.interval if last else None, "last_bar_provider": last.provider if last else None,
            "last_bar_toronto": toronto(last.bar_end if last.interval != "1d" else last.event_time) if last else None,
            "fix": _fix(rows, status),
            "label": (("Daily reference rate only (no intraday): bars are 1D and labelled so on the chart." if inst.asset_class == "fx" else
                       "End-of-day bars only on the free plan (previous close). Intraday needs a free-account source (Questrade, Alpaca) or a paid plan.") if daily_only else
                      "Delayed data" if served and (served["delay_s"] or 0) > 0 else "")}


def _stock_summary(feed) -> dict[str, Any]:
    from . import stock_providers as sp
    env = feed.env() if hasattr(feed, "env") else {}
    return sp.summary(env)


def catalog_coverage(feed, ids: Iterable[str] | None = None, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    ids = list(ids) if ids is not None else [i.id for i in feed.instruments.all()]
    rows = []
    for iid in ids:
        try:
            rows.append(asset_coverage(feed, iid, now))
        except KeyError:
            rows.append({"instrument": iid, "asset_class": "unknown", "status": "no_provider", "chain": [], "fix": "Not in the instrument master"})
    proxies = []
    by_id = {r["instrument"]: r for r in rows}
    for alias, p in PROXIES.items():
        pr = by_id.get(p["proxy"])
        proxies.append({"symbol": alias, **p, "proxy_status": pr["status"] if pr else "no_provider", "proxy_served_by": pr["served_by"] if pr else None})
    classes: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = classes.setdefault(r["asset_class"], {"asset_class": r["asset_class"], "label": CLASS_LABEL.get(r["asset_class"], r["asset_class"]), "count": 0, "by_status": {},
                                                  "served_by": {}, "needs": set()})
        c["count"] += 1
        c["by_status"][r["status"]] = c["by_status"].get(r["status"], 0) + 1
        if r.get("served_by"):
            c["served_by"][r["served_by"]] = c["served_by"].get(r["served_by"], 0) + 1
        if r["status"] in ("needs_key", "policy_blocked"):
            for p in r["chain"]:
                if p["policy_allowed"] and p["keys_missing"]:
                    c["needs"].add(",".join(p["keys_missing"]))
    for c in classes.values():
        c["needs"] = sorted(c["needs"])
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    from .status import toronto
    return {"as_of": now, "as_of_toronto": toronto(now), "timezone": "America/Toronto", "status_counts": counts,
            "classes": sorted(classes.values(), key=lambda c: c["asset_class"]), "assets": rows, "proxies": proxies,
            "stock_provider": _stock_summary(feed)}
