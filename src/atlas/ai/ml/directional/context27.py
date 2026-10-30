"""Market-wide context for the layer-27+ features (evo-15): stored-universe breadth, Cboe VIX, and a synthetic US-dollar proxy.

Everything here is point-in-time: each value carries an ``avail`` epoch (the moment its inputs were all final) and is joined to a bar
with ``merge_asof(direction='backward')`` on that bar's END, so a bar never sees a value that did not yet exist.

Honest limits (also printed by the chart layers):
* ``breadth`` is the breadth of the equities ATLAS has STORED (today's list), not of the whole market, and the list was chosen today, so it
  carries survivorship/selection bias. It is a context feature, not an index.
* ``vix`` is the Cboe VIX daily close (free CSV from cdn.cboe.com, keyless). One value per day, available after that day's close.
* ``USD_PROXY`` is synthetic: exp(0.5*(ln USDCAD - ln EURUSD)), an equal-weight EUR/CAD dollar index, NOT the ICE DXY.
Keyed FRED data is never read here (Decision #29, FRED terms prohibit AI training/archival).
"""
from __future__ import annotations

import io
import math
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
VIX_TTL_S = 12 * 3600
BREADTH_MIN_BARS = 400          # same floor as the training universe (a 1d series needs >= 400 bars to be pooled)
BREADTH_MIN_NAMES = 30
USD_LEGS = ("EUR_USD", "USD_CAD")
USD_PROXY = "USD_PROXY"
NY = "America/New_York"


def is_stock_like(symbol: str) -> bool:
    from atlas.ai.ml.chart_prediction import GOLD_INSTRUMENTS
    s = symbol.upper()
    return s.isalpha() and 1 <= len(s) <= 5 and not s.endswith("USDT") and s not in GOLD_INSTRUMENTS


def _day_key(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    """New-York calendar date (yyyymmdd) of the MIDPOINT of each bar: right for daily bars whatever their start convention."""
    mid = (np.asarray(start, float) + np.asarray(end, float)) / 2.0
    ny = pd.to_datetime(mid, unit="s", utc=True).tz_convert(NY)
    return (ny.year * 10000 + ny.month * 100 + ny.day).to_numpy(np.int64)


def breadth_context(day_bars: Mapping[str, Sequence]) -> pd.DataFrame | None:
    """Per trading day: share of names above their 50/200-day mean, 10-day mean advance share, and the 5-day change of the 50-day share.
    ``avail`` = the latest bar end among the names that traded that day. None when fewer than BREADTH_MIN_NAMES usable names."""
    closes, ends = {}, {}
    for sym, bars in day_bars.items():
        if len(bars) < BREADTH_MIN_BARS:
            continue
        st = np.array([b.start for b in bars], float)
        en = np.array([b.end for b in bars], float)
        key = _day_key(st, en)
        cl = pd.Series(np.array([b.close for b in bars], float), index=key)
        cl = cl[~cl.index.duplicated(keep="last")]
        closes[sym] = cl
        ends[sym] = pd.Series(en, index=key)[~pd.Series(en, index=key).index.duplicated(keep="last")]
    if len(closes) < BREADTH_MIN_NAMES:
        return None
    C = pd.DataFrame(closes).sort_index()
    E = pd.DataFrame(ends).sort_index().reindex(C.index)
    ma50, ma200 = C.rolling(50, min_periods=50).mean(), C.rolling(200, min_periods=200).mean()
    v50, v200 = ma50.notna(), ma200.notna()

    def share(above, valid):
        n = valid.sum(axis=1)
        return (above & valid).sum(axis=1).where(n >= BREADTH_MIN_NAMES) / n.where(n >= BREADTH_MIN_NAMES)

    d = C.diff()
    adv, dec = (d > 0).sum(axis=1), (d < 0).sum(axis=1)
    adv_share = (adv / (adv + dec).replace(0, np.nan)).where((adv + dec) >= BREADTH_MIN_NAMES)
    p50 = share(C > ma50, v50)
    out = pd.DataFrame({"br_pct_above_50": p50, "br_pct_above_200": share(C > ma200, v200),
                        "br_adv_share_10": adv_share.rolling(10, min_periods=5).mean(), "br_pct50_chg_5": p50 - p50.shift(5)})
    out["avail"] = E.max(axis=1).to_numpy()
    out = out.dropna(subset=["avail"]).astype({"avail": np.int64}).reset_index(drop=True)
    return out if len(out) else None


def parse_vix_csv(text: str) -> pd.DataFrame | None:
    """Cboe VIX_History.csv (DATE,OPEN,HIGH,LOW,CLOSE) -> frame with ``date`` (UTC midnight epoch of the session date) and ``close``."""
    try:
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().upper() for c in df.columns]
        d = pd.to_datetime(df["DATE"], format="%m/%d/%Y", errors="coerce")
        out = pd.DataFrame({"day": d, "close": pd.to_numeric(df["CLOSE"], errors="coerce")}).dropna()
        out = out[out["close"] > 0].sort_values("day").drop_duplicates("day", keep="last").reset_index(drop=True)
    except Exception:
        return None
    return out if len(out) >= 300 else None


_VIX_LOCK = threading.Lock()


def fetch_vix_csv(cache: str | os.PathLike | None = None, ttl: float = VIX_TTL_S, now: float | None = None, timeout: float = 20.0) -> str | None:
    """Cached Cboe download. A failed download falls back to a stale cache file, else None (the VIX features then stay NaN, never invented)."""
    now = time.time() if now is None else now
    p = Path(cache or os.environ.get("ATLAS_VIX_CACHE") or "var/cache/cboe_vix.csv")
    with _VIX_LOCK:
        try:
            if p.exists() and now - p.stat().st_mtime < ttl:
                return p.read_text(encoding="utf-8")
        except OSError:
            pass
        try:
            req = urllib.request.Request(VIX_URL, headers={"User-Agent": "Mozilla/5.0 (ATLAS research; paper only)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode("utf-8", "replace")
            if parse_vix_csv(txt) is None:
                raise ValueError("unparseable")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
            return txt
        except Exception:
            try:
                return p.read_text(encoding="utf-8") if p.exists() else None
            except OSError:
                return None


def vix_context(vix: pd.DataFrame | None, spy_daily: Sequence | None = None) -> pd.DataFrame | None:
    """Per VIX session: level z-score vs 252 days, 5-day log change, and implied-minus-realised variance (VIX^2 - 21d SPY realised vol^2, annualised pts).
    Available at the next UTC midnight (the VIX settles ~16:15 ET, hours before)."""
    if vix is None or len(vix) < 300:
        return None
    lv = np.log(vix["close"].astype(float))
    z = (lv - lv.rolling(252, min_periods=120).mean()) / lv.rolling(252, min_periods=120).std()
    out = pd.DataFrame({"iv_vix_z_252": z, "iv_vix_chg_5": lv - lv.shift(5), "iv_vrp": np.nan, "vix": vix["close"].astype(float)})
    day = pd.to_datetime(vix["day"])
    if spy_daily is not None and len(spy_daily) >= 60:
        st = np.array([b.start for b in spy_daily], float)
        en = np.array([b.end for b in spy_daily], float)
        key = pd.Series(np.log(np.array([b.close for b in spy_daily], float)), index=_day_key(st, en))
        key = key[~key.index.duplicated(keep="last")].sort_index()
        rv = np.sqrt(key.diff().pow(2).rolling(21, min_periods=15).mean() * 252.0) * 100.0
        vkey = pd.Series((day.dt.year * 10000 + day.dt.month * 100 + day.dt.day).to_numpy(np.int64))
        m = rv.reindex(vkey.to_numpy()).to_numpy()
        out["iv_vrp"] = ((vix["close"].to_numpy(float) ** 2) - m ** 2) / 100.0       # variance points / 100
    out["avail"] = (((day - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)) + 86400).to_numpy(np.int64)
    out = out.reset_index(drop=True)
    out["iv_vix_z_252"] = out["iv_vix_z_252"].replace([np.inf, -np.inf], np.nan)
    return out


def usd_proxy_series(load: Callable[[str], Sequence]) -> tuple[np.ndarray, np.ndarray] | None:
    """(end, level) of the synthetic dollar index on EUR_USD's bar ends; ``load(sym)`` returns stored bars. None when either leg is short."""
    try:
        e, c = list(load("EUR_USD")), list(load("USD_CAD"))
    except Exception:
        return None
    if len(e) < 300 or len(c) < 300:
        return None
    left = pd.DataFrame({"end": np.array([b.end for b in e], np.int64), "eur": [b.close for b in e]}).sort_values("end")
    right = pd.DataFrame({"end": np.array([b.end for b in c], np.int64), "cad": [b.close for b in c]}).sort_values("end")
    m = pd.merge_asof(left, right, on="end", direction="backward").dropna()
    if len(m) < 300:
        return None
    lvl = np.exp(0.5 * (np.log(m["cad"].to_numpy(float)) - np.log(m["eur"].to_numpy(float))))
    return m["end"].to_numpy(np.int64), lvl


def asof_join(end: np.ndarray, ctx: pd.DataFrame | None, cols: Sequence[str]) -> pd.DataFrame:
    """Value of each ctx column as known at each bar end (last row with avail <= end). NaN before the context starts or when ctx is None."""
    n = len(end)
    if ctx is None or not len(ctx):
        return pd.DataFrame({c: np.full(n, np.nan) for c in cols})
    left = pd.DataFrame({"end": np.asarray(end, np.int64)})
    right = ctx[["avail", *cols]].sort_values("avail")
    m = pd.merge_asof(left, right, left_on="end", right_on="avail", direction="backward")
    return m[list(cols)].reset_index(drop=True)


def build_context(day_bars: Mapping[str, Sequence], vix_text: str | None = None) -> dict[str, pd.DataFrame | None]:
    """{"breadth": frame|None, "vix": frame|None} from stored 1d bars (stock-like names only) and the Cboe CSV text."""
    stocks = {s: b for s, b in day_bars.items() if is_stock_like(s)}
    vix = parse_vix_csv(vix_text) if vix_text else None
    return {"breadth": breadth_context(stocks), "vix": vix_context(vix, day_bars.get("SPY"))}


_SHARED: dict = {"t": 0.0, "ctx": None}
_SHARED_LOCK = threading.Lock()
SHARED_TTL_S = 3600.0


def shared_context(load_daily: Callable[[str], Sequence], symbols: "Sequence[str] | Callable[[], Sequence[str]]", now: float | None = None, fetch_vix: Callable[[], str | None] = fetch_vix_csv,
                   ttl: float = SHARED_TTL_S) -> dict[str, pd.DataFrame | None]:
    """Process-wide memo (``ttl`` s) of build_context over the stored stock-like symbols: chart and live model share one build."""
    now = time.time() if now is None else now
    with _SHARED_LOCK:
        if _SHARED["ctx"] is not None and now - _SHARED["t"] < ttl:
            return _SHARED["ctx"]
        day = {}
        for s in (symbols() if callable(symbols) else symbols):      # lazy: the symbol scan only runs on a cache miss
            if is_stock_like(s):
                try:
                    day[s] = list(load_daily(s))
                except Exception:
                    pass
        ctx = build_context(day, fetch_vix())
        _SHARED.update(t=now, ctx=ctx)
        return ctx


def training_events(cal: Mapping) -> list[float]:
    """Release timestamps allowed into training: official BLS/Treasury schedules only. Keyed FRED release dates are display-only (Decision #29)."""
    return [e["ts"] for e in cal.get("events", []) if e.get("source") != "fred"]


def stored_daily_symbols(feed) -> list[str]:
    """Stock-like instruments with at least BREADTH_MIN_BARS stored daily bars (the breadth universe).
    One narrow GROUP BY on the 1d rows; store.summary() scans every interval and took ~35 s on the 1M-row store."""
    rows = feed.store._fetchall("SELECT instrument, COUNT(DISTINCT event_time) FROM bar_revisions WHERE interval='1d' GROUP BY instrument")
    return sorted({str(i) for i, n in rows if (n or 0) >= BREADTH_MIN_BARS and is_stock_like(str(i))})


def reset_shared() -> None:
    with _SHARED_LOCK:
        _SHARED.update(t=0.0, ctx=None)
