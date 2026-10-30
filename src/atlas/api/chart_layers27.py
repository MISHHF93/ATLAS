"""Chart layers 27-33 (evo-15). Layers 27-32 are computed by the same functions that build the model's training features
(``atlas.ai.ml.directional.layers25``). Layer 33, ``macro_risk``, reads FRED with the user's key and is DISPLAY-ONLY: FRED's terms prohibit
AI training and archival (Decision #29), so none of it is a model feature, none of it is written to disk, and it is cached in memory only.
Each payload carries ``status`` and, when not ok, a plain-language ``reason``. Read-only; no profitability claim."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from atlas.ai.ml.directional import context27 as C27
from atlas.ai.ml.directional import layers25 as L
from atlas.api.chart_layers25 import Ctx, _f, _last, _need, _unavail

IDS = ("breadth", "overnight_intraday", "gap_stats", "seasonality", "implied_vol", "usd_proxy", "macro_risk")


def _ok(reason: str, feat: Mapping, **kw) -> dict[str, Any]:
    return {"status": "ok", "reason": reason, "features": dict(feat), **kw}


def breadth(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    if ctx.group != "equity" or not C27.is_stock_like(ctx.sym):
        return _unavail(f"breadth is computed for stocks and ETFs only; {ctx.sym} is {ctx.group if ctx.group != 'equity' else 'not a stored stock'}")
    if ctx.extra.get("breadth") is None:
        return _unavail(f"needs at least {C27.BREADTH_MIN_NAMES} stored stocks with {C27.BREADTH_MIN_BARS}+ daily bars each (Massive daily bars); the store has fewer")
    feat = _last(ctx.f, L.LAYER_FEATURES["breadth"])
    if feat["br_pct_above_50"] is None:
        return _unavail("no breadth value yet at this bar (the first 50 daily bars of history are still warming up)", features=feat)
    p50 = feat["br_pct_above_50"]
    tone = "broad strength" if p50 >= 0.7 else ("broad weakness" if p50 <= 0.3 else "mixed")
    return _ok("Share of the STORED stock universe (today's list, not the whole market; survivorship-biased) above its 50 and 200-day average, from the last daily close that was final at this bar.",
               feat, tone=tone, meaning="High readings mean most stored stocks are trending up; extreme readings have not reliably predicted direction in recent studies. Context only.")


def _session_unavail(ctx: Ctx, what: str) -> dict[str, Any] | None:
    if ctx.group not in L.SESSION_SHIFT_H or "_" in ctx.sym:
        return _unavail(f"{what} needs a market with a daily close and open; {ctx.sym} trades {'continuously' if ctx.group == 'crypto' else 'around the clock (FX)'}")
    return None


def overnight_intraday(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    u = _session_unavail(ctx, "overnight vs intraday")
    if u:
        return u
    feat = _last(ctx.f, L.LAYER_FEATURES["overnight_intraday"])
    if feat["oi_on_20"] is None:
        return _unavail("needs about 30 completed sessions of history for the 20-day averages", features=feat)
    return _ok("Average close-to-open (overnight) and open-to-close (intraday) log return over the last 20 COMPLETED sessions, in units of that instrument's daily volatility; "
               "'today's gap' uses this session's open versus the previous close. Extended-hours bars, where stored, count as part of the session.", feat,
               meaning="Studies (Lou, Polk and Skouras, 2019) found most of the equity premium accrued overnight. The split is descriptive here; it is not a trade signal.")


def gap_stats(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    u = _session_unavail(ctx, "opening-gap statistics")
    if u:
        return u
    feat = _last(ctx.f, L.LAYER_FEATURES["gap_stats"])
    if feat["gp_size_atr"] is None:
        return _unavail("no opening gap at this bar (flat open) or not enough sessions to size it", features=feat)
    return _ok("Today's opening gap in units of the recent average daily range, whether price has traded back to the previous close yet (1 = filled), "
               "and the share of the last 20 gaps that filled the same day.", feat,
               meaning="Fill rates differ a lot by market and period; treat the 20-day rate as context, not a promise that a gap will fill.")


def seasonality(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    feat = _last(ctx.f, L.LAYER_FEATURES["seasonality"])
    return _ok("Calendar position only: business-day-of-month, the turn-of-month window (last business day and first three), weekday, and quarter-end week. "
               + ("UTC calendar." if ctx.group == "crypto" else "New York calendar."), feat,
               meaning="Turn-of-month and weekday effects are documented but have weakened or become inconsistent in recent data; this is a position marker, not a forecast.")


def implied_vol(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    if ctx.extra.get("vix") is None:
        return _unavail("Cboe VIX history is not available (the free download from cdn.cboe.com failed and there is no cached copy)")
    feat = _last(ctx.f, L.LAYER_FEATURES["implied_vol"])
    if feat["iv_vix_z_252"] is None:
        return _unavail("VIX history does not yet cover this bar", features=feat)
    end = ctx.bars[-1].end
    lvl = _f(C27.asof_join(np.array([end]), ctx.extra["vix"], ["vix"])["vix"].iloc[0], 2)
    return _ok("Cboe VIX (30-day S&P 500 implied volatility) as of the last daily close that was final at this bar; the z-score is against the past 252 sessions. "
               "The variance gap is VIX squared minus 21-day realised S&P 500 variance (needs SPY daily bars).", feat, vix=lvl,
               meaning="Implied volatility prices the market's expected moves and tends to exceed realised (the variance risk premium). It is a risk gauge for US equity risk, not a direction signal. Free CSV; end-of-day only.")


def usd_proxy(ctx: Ctx) -> dict[str, Any]:
    _need(ctx)
    if ctx.sym in L.PROXY_EXCLUDES["USD_PROXY"]:
        return _unavail(f"{ctx.sym} is one of the two currency pairs the dollar proxy is built from")
    if C27.USD_PROXY not in ctx.corr_avail:
        return _unavail(f"needs stored {' and '.join(C27.USD_LEGS)} bars at {ctx.interval} (OANDA practice or ECB/Bank of Canada daily); at least one leg is missing or short")
    feat = _last(ctx.f, L.LAYER_FEATURES["usd_proxy"])
    if feat["usd_ret_64"] is None:
        return _unavail("not enough proxy history yet for the 64-bar change", features=feat)
    return _ok("Synthetic US-dollar strength: exp(0.5 x (ln USD/CAD - ln EUR/USD)), an equal-weight EUR and CAD basket. It is NOT the ICE Dollar Index (DXY, which has no free feed). "
               "Changes are measured over this chart's own bars, using the last proxy bar closed at or before each.", feat,
               meaning="Positive = the dollar has strengthened against euro and Canadian dollar. Context for commodities, gold and global risk; not a forecast.")


# ----------------------------------------------------------------------------------------- 33 macro risk (display only)
FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
MACRO_SERIES = (("T10Y2Y", "10y minus 2y Treasury yield (curve slope)", "pp"), ("T10Y3M", "10y minus 3m Treasury yield", "pp"),
                ("BAMLH0A0HYM2", "ICE BofA US high-yield option-adjusted spread", "pp"), ("BAA10Y", "Moody's Baa corporate yield minus 10y Treasury", "pp"))
_MACRO: dict = {"t": 0.0, "v": None}
_MACRO_LOCK = threading.Lock()
MACRO_TTL_S = 6 * 3600


def _fred_http(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ATLAS-research"}), timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def macro_risk(ctx: Ctx | None = None, env: Mapping[str, str] | None = None, fetch: Callable[[str], tuple[int, str]] | None = None, now: float | None = None) -> dict[str, Any]:
    """Latest yield-curve slope and credit spreads from FRED (keyed). In-memory only, never a model feature, never persisted."""
    note = "DISPLAY ONLY: FRED's terms prohibit using its data to train AI models or to archive it, so this layer is not a model feature and nothing here is stored."
    if env is None:
        from atlas.accounts.credentials import effective_environ
        env = effective_environ()
    key = (env.get("FRED_API_KEY") or "").strip()
    if not key or key.startswith("<"):
        return _unavail("needs FRED_API_KEY (free): add it in Settings > Setup and press Verify", note=note)
    now = time.time() if now is None else now
    with _MACRO_LOCK:
        if _MACRO["v"] is not None and now - _MACRO["t"] < MACRO_TTL_S:
            return _MACRO["v"]
    fetch = fetch or _fred_http
    start = (dt.date.fromtimestamp(now) - dt.timedelta(days=400)).isoformat()
    rows, errs = [], []
    for sid, title, unit in MACRO_SERIES:
        q = urllib.parse.urlencode({"series_id": sid, "api_key": key, "file_type": "json", "observation_start": start, "sort_order": "asc"})
        st, body = fetch(FRED_OBS + "?" + q)
        if st != 200:
            errs.append(f"{sid}: HTTP {st}" if st else f"{sid}: unreachable")
            continue
        try:
            obs = [(o["date"], float(o["value"])) for o in json.loads(body).get("observations", []) if o.get("value") not in (".", "", None)]
        except (ValueError, KeyError):
            errs.append(f"{sid}: unreadable response")
            continue
        if len(obs) < 20:
            errs.append(f"{sid}: only {len(obs)} observations")
            continue
        vals = np.array([v for _, v in obs])
        rows.append({"series": sid, "title": title, "unit": unit, "date": obs[-1][0], "value": _f(vals[-1], 2),
                     "percentile_1y": _f(float(((vals < vals[-1]).sum() + 0.5 * (vals == vals[-1]).sum()) / len(vals)), 2),
                     "inverted": bool(vals[-1] < 0) if sid.startswith("T10Y") else None})
    if not rows:
        return _unavail("FRED did not return usable data (" + "; ".join(errs) + ")", note=note)
    inv = any(r["inverted"] for r in rows if r["inverted"] is not None)
    out = {"status": "ok", "reason": "Latest published values (FRED publishes with a lag of about one business day); "
                                     + (f"partial: {'; '.join(errs)}. " if errs else "") + "A negative curve slope has preceded US recessions historically; wide credit spreads mark stress. " + note,
           "series": rows, "curve_inverted": inv, "model_feature": False, "display_only": True,
           "meaning": "Macro risk backdrop, not a timing tool: inversions have led recessions by many months and also given false alarms."}
    with _MACRO_LOCK:
        _MACRO.update(t=now, v=out)
    return out


def reset_macro_cache() -> None:
    with _MACRO_LOCK:
        _MACRO.update(t=0.0, v=None)
