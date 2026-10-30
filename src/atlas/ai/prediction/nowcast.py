"""Nowcast (evo-16 M3): a predicted price PATH with a conformal interval that widens with time since the last real print.

This is a forecast, never market data. It is not written into the bar store and is never a training label. The path is built
separately from the directional probability (which is a barrier-hit probability, not a price).

State space: log price is a random walk (local level, zero drift: no skill is claimed) observed by real prints. Between prints the
forecast distribution is propagated:  mean = anchor (+ proxy move), std = sigma_per_trading_second * sqrt(trading seconds since the
anchor). The interval is split-conformal: on rolling origins of the asset's own history, |z| = |log-return over k bars| / (sigma_t sqrt(k))
gives an empirical quantile per horizon k; the band is that quantile times the propagated std, so it widens with k and carries the
asset's own fat tails. Live scoring (``nowcast_log``) then grades issued nowcasts against the real bar when it arrives.

Real-time inputs are used only when they exist in the store: the freshest bar across 1m/15m/1h/1d, a fresher ``last_quotes`` print
(OANDA practice once configured), and a correlated proxy that has a fresher print than the target (beta from the asset's own returns,
used only when |corr| >= 0.5). Assets with only end-of-day bars degrade to a forecast from the last close with a widening band."""
from __future__ import annotations

import math
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np

NY = ZoneInfo("America/New_York")
TORONTO = ZoneInfo("America/Toronto")
DUR = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}   # every chart timeframe; only INTERVALS are stored base series
INTERVALS = ("1m", "15m", "1h", "1d")
ALPHA = 0.2                      # 80% interval
KGRID = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)
MIN_BASE_BARS = 120
WINDOW_BARS = 1500
MAX_PATH = 320
LABEL = "Predicted (not market data)"
RTH_OPEN, RTH_CLOSE = (9, 30), (16, 0)
FUT_ID = {"GC", "SI", "MGC", "XAUUSD", "XAGUSD", "XAU_USD", "XAG_USD"}
# real proxies (fresher prints of the same exposure); used only when stored, fresher than the target, and correlated
PROXIES = {"SPY": ("ES", "MES", "SPX"), "QQQ": ("NQ", "MNQ", "NDX"), "DIA": ("YM", "MYM"), "IWM": ("RTY", "M2K"),
           "GLD": ("GC", "MGC", "XAUUSD", "XAU_USD"), "SLV": ("SI", "XAGUSD", "XAG_USD"),
           "ES": ("SPY",), "NQ": ("QQQ",), "GC": ("GLD", "XAUUSD", "XAU_USD"), "SI": ("SLV",), "EUR_USD": ("6E",), "6E": ("EUR_USD",)}
# OANDA practice CFD proxies (labelled as proxy, never the asset): they join the candidates, and only count once their bars are really stored
from atlas.feeds.oanda_proxies import OANDA_PROXY  # noqa: E402
_OANDA_IDS = frozenset(OANDA_PROXY.values())
for _a, _o in OANDA_PROXY.items():
    PROXIES[_a] = tuple(dict.fromkeys((*PROXIES.get(_a, ()), _o)))


# ----------------------------------------------------------------------------- sessions
def session_kind(symbol: str, pool: str) -> str:
    if pool == "crypto":
        return "24x7"
    if pool in ("fx", "index", "other"):
        return "24x5"
    if pool == "metal":
        return "24x5" if symbol.upper() in FUT_ID else "us_rth"
    return "us_rth"


def _ny(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, NY)


def _at(d: date, hm: tuple[int, int]) -> float:
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=NY).timestamp()


def _closed_windows(t0: float, t1: float, kind: str) -> list[tuple[float, float]]:
    """Closed (non-trading) windows overlapping [t0, t1) for the weekly 24x5 calendar (Fri 17:00 -> Sun 17:00 New York)."""
    out = []
    d = _ny(t0).date() - timedelta(days=2)
    end = _ny(t1).date() + timedelta(days=1)
    while d <= end:
        if d.weekday() == 4:
            out.append((_at(d, (17, 0)), _at(d + timedelta(days=2), (17, 0))))
        d += timedelta(days=1)
    return out


def trading_seconds(t0: float, t1: float, kind: str) -> float:
    """Seconds of trading time in [t0, t1): weekends and overnight gaps do not widen the band (holidays are not modelled)."""
    if t1 <= t0:
        return 0.0
    if kind == "24x7":
        return t1 - t0
    if kind == "24x5":
        return (t1 - t0) - sum(max(0.0, min(t1, b) - max(t0, a)) for a, b in _closed_windows(t0, t1, kind))
    tot, d, last = 0.0, _ny(t0).date(), _ny(t1).date()
    while d <= last:
        if d.weekday() < 5:
            tot += max(0.0, min(t1, _at(d, RTH_CLOSE)) - max(t0, _at(d, RTH_OPEN)))
        d += timedelta(days=1)
    return tot


def is_open(ts: float, kind: str) -> bool:
    if kind == "24x7":
        return True
    if kind == "24x5":
        return not any(a <= ts < b for a, b in _closed_windows(ts, ts + 1, kind))
    dt = _ny(ts)
    return dt.weekday() < 5 and _at(dt.date(), RTH_OPEN) <= ts < _at(dt.date(), RTH_CLOSE)


def next_open(ts: float, kind: str) -> float:
    if kind == "24x7" or is_open(ts, kind):
        return ts
    if kind == "24x5":
        for a, b in _closed_windows(ts, ts + 1, kind):
            if a <= ts < b:
                return b
        return ts
    d = _ny(ts).date()
    for _ in range(10):
        if d.weekday() < 5 and _at(d, RTH_OPEN) > ts:
            return _at(d, RTH_OPEN)
        d += timedelta(days=1)
    return ts


def bar_trading_seconds(base_iv: str, kind: str) -> float:
    if base_iv != "1d":
        return float(DUR[base_iv])
    return 23400.0 if kind == "us_rth" else 86400.0


def grid_after(start: float, iv: str, kind: str, n: int) -> list[int]:
    """The next ``n`` target bar starts strictly after bar ``start`` on this interval's grid, skipping closed time."""
    out, s, S = [], float(start), DUR[iv]
    for _ in range(n):
        c = s + S
        if iv == "1d":
            while kind != "24x7" and datetime.fromtimestamp(c + 43200, tz=ZoneInfo("UTC")).weekday() >= 5:
                c += S
        elif not is_open(c, kind):
            c = next_open(c, kind)
        out.append(int(c))
        s = c
    return out


# ----------------------------------------------------------------------------- bars
def _tail(feed, symbol: str, iv: str, now: float, kind: str) -> list:
    span = WINDOW_BARS * DUR[iv] * (1.0 if kind == "24x7" else 1.7 if iv != "1d" else 1.5)
    try:
        return list(feed.bars(symbol, iv, start=int(now - span), as_of=int(now)))
    except KeyError:
        if symbol not in _OANDA_IDS:
            return []
        try:   # an OANDA CFD proxy series is not a catalog asset: read what the practice feed stored, read-only
            return list(feed.store.bars(symbol, iv, int(now - span), None, provider="oanda", as_of=int(now), confirmed_only=True))
        except Exception:
            return []
    except Exception:
        return []


_BARS: dict[tuple[int, str, str], tuple[int, list, float]] = {}
_BARS_TTL = 30.0
_BARS_LOCK = threading.Lock()


def tail_bars(feed, symbol: str, iv: str, now: float, kind: str, last_event: int | None = None) -> list:
    """Closed bars, re-read only when the newest stored bar changed (``last_event``)."""
    key = (id(feed), symbol, iv)
    with _BARS_LOCK:
        hit = _BARS.get(key)
        mono = time.monotonic()
        if hit and ((last_event is not None and hit[0] == last_event) or (last_event is None and mono - hit[2] < _BARS_TTL)):
            return hit[1]
    bars = _tail(feed, symbol, iv, now, kind)
    with _BARS_LOCK:
        if len(_BARS) > 1500:
            _BARS.clear()
        _BARS[key] = (int(bars[-1].event_time) if bars else -1, bars, time.monotonic())
    return bars


def _quote(feed, symbol: str, bar_provider: str | None = None, eod_only: bool = False) -> dict | None:
    """Freshest permitted quote. A quote from a different venue than the bars is a different price (Coinbase BTC-USD sat ~25 bps under the
    Binance/OKX USDT bars, which made every short-horizon band miss), so unless the asset has only end-of-day bars the quote must come from
    the same provider as the last real bar."""
    try:
        qs = feed.store.last_quotes(symbol)
    except Exception:
        return None
    from atlas.feeds.free_sources import allowed as free_allowed
    # unofficial providers (Yahoo) stay out of the trade series, so they never anchor a forecast either
    qs = [q for q in qs if q.get("price") and q.get("event_time") and free_allowed(q.get("provider"))]
    if bar_provider and not eod_only:
        qs = [q for q in qs if q.get("provider") == bar_provider]
    return max(qs, key=lambda q: q["event_time"]) if qs else None


# ----------------------------------------------------------------------------- state-space pieces
def _ewma_sigma(close: np.ndarray, span: int = 100) -> np.ndarray:
    from atlas.ai.ml.directional import labels as L
    return L.ewma_sigma(close, span)


def conformal_scale(close: np.ndarray, alpha: float = ALPHA) -> dict[int, float]:
    """{k: quantile of |z|} on rolling origins: z = log(c[i+k]/c[i]) / (sigma_i sqrt(k)), sigma_i backward-looking at i."""
    c = np.asarray(close, float)[-WINDOW_BARS:]
    lc, sg = np.log(c), _ewma_sigma(c)
    out: dict[int, float] = {}
    for k in KGRID:
        if len(c) < 120 + k + 40:
            break
        i = np.arange(100, len(c) - k)
        s = sg[i]
        ok = np.isfinite(s) & (s > 0)
        if ok.sum() < 40:
            continue
        z = np.abs((lc[i + k] - lc[i])[ok] / (s[ok] * math.sqrt(k)))
        n = len(z)
        q = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
        out[k] = float(np.quantile(z, q))
    return out


def qhat(scale: dict[int, float], k: float) -> float:
    if not scale:
        return 1.2816   # Gaussian 80% when there is not enough history to calibrate
    ks = np.array(sorted(scale), float)
    qs = np.array([scale[int(x)] for x in ks])
    return float(np.interp(math.log(max(k, 1.0)), np.log(ks), qs))


def _proxy_info(feed, symbol: str, base_iv: str, base_bars: list, anchor_t: float, now: float, kind: str) -> dict | None:
    """Beta of this asset's base-interval returns on a correlated proxy whose last real print is fresher than the anchor."""
    from atlas.ai.prediction.pools import pool_for_symbol
    cands = list(PROXIES.get(symbol, ()))
    if pool_for_symbol(symbol) == "crypto" and symbol != "BTCUSDT":
        cands.append("BTCUSDT")
    for p in cands:
        pb = None
        for iv in ("1m", "15m", base_iv):
            b = tail_bars(feed, p, iv, now, kind)
            if b and b[-1].event_time + DUR[iv] > anchor_t + 0.5 * DUR[base_iv]:
                pb = (iv, b)
                break
        if pb is None:
            continue
        piv, b = pb
        pb_base = tail_bars(feed, p, base_iv, now, kind)
        if len(pb_base) < MIN_BASE_BARS:
            continue
        pe = np.array([x.event_time + DUR[base_iv] for x in pb_base], float)
        pc = np.log(np.array([x.close for x in pb_base], float))
        te = np.array([x.event_time + DUR[base_iv] for x in base_bars], float)
        tc = np.log(np.array([x.close for x in base_bars], float))
        idx = np.searchsorted(pe, te, side="right") - 1
        ok = idx >= 0
        if ok.sum() < MIN_BASE_BARS:
            continue
        aligned = pc[idx[ok]]
        r_t, r_p = np.diff(tc[ok])[-250:], np.diff(aligned)[-250:]
        if len(r_t) < 100 or np.std(r_p) == 0:
            continue
        rho = float(np.corrcoef(r_t, r_p)[0, 1])
        if not np.isfinite(rho) or abs(rho) < 0.5:
            continue
        beta = float(np.cov(r_t, r_p)[0, 1] / np.var(r_p, ddof=1))
        at = np.searchsorted(pe, anchor_t, side="right") - 1
        if at < 0:
            continue
        last = b[-1]
        t_p = float(last.event_time + DUR[piv])
        return {"proxy": p, "beta": beta, "rho": rho, "delta": float(math.log(last.close) - pc[at]), "t_proxy": t_p, "interval": piv}
    return None


# ----------------------------------------------------------------------------- the nowcast
def _pick_base(feed, symbol: str, now: float, kind: str, lmap: dict | None) -> tuple[str, list] | None:
    best = None
    for iv in INTERVALS:
        info = (lmap or {}).get((symbol, iv))
        if lmap is not None and (not info or info["n"] < MIN_BASE_BARS):
            continue
        bars = tail_bars(feed, symbol, iv, now, kind, info["last"] if info else None)
        if len(bars) < MIN_BASE_BARS:
            continue
        end = bars[-1].event_time + DUR[iv]
        if best is None or end > best[0]:        # freshest real print; the finest interval wins a tie (loop order)
            best = (end, iv, bars)
    return (best[1], best[2]) if best else None


def nowcast(feed, symbol: str, interval: str = "15m", now: float | None = None, horizon: int | None = None, lmap: dict | None = None,
            live_scale: float = 1.0) -> dict[str, Any]:
    """Predicted path for ``symbol`` on the ``interval`` grid: from the last REAL print through now and ``horizon`` bars ahead."""
    from atlas.ai.prediction.pools import pool_for_symbol
    from atlas.ai.ml.directional import pipeline as P
    now = float(time.time() if now is None else now)
    pool = pool_for_symbol(symbol)
    kind = session_kind(symbol, pool)
    base = {"status": "ok", "kind": "nowcast_v1", "label": LABEL, "symbol": symbol, "interval": interval, "pool": pool, "session": kind,
            "execution_permission": "none", "computed_at": int(now), "alpha": ALPHA, "level": 1 - ALPHA,
            "note": "A forecast, not market data: never written to the bar store and never used as a training label. Zero-drift random walk "
                    "(no directional skill is claimed); the band is split-conformal and widens with time since the last real print."}
    if interval not in DUR:
        return {**base, "status": "unsupported_interval", "reason": f"interval {interval} is not supported"}
    pick = _pick_base(feed, symbol, now, kind, lmap)
    if pick is None:
        return {**base, "status": "no_data", "reason": f"No real bars (at least {MIN_BASE_BARS}) are stored for {symbol}; nothing to anchor a forecast on."}
    base_iv, bars = pick
    last = bars[-1]
    anchor_t, anchor_px, source, provider = float(last.event_time + DUR[base_iv]), float(last.close), "bar", getattr(last, "provider", None)
    q = _quote(feed, symbol, provider, base_iv == "1d")
    if q and float(q["event_time"]) > anchor_t and float(q["event_time"]) <= now + 5 and abs(math.log(float(q["price"]) / anchor_px)) < 0.25:
        anchor_t, anchor_px, source, provider = float(q["event_time"]), float(q["price"]), "quote", q.get("provider")
    close = np.array([b.close for b in bars], float)
    sig_bar = float(_ewma_sigma(close)[-1])
    if not np.isfinite(sig_bar) or sig_bar <= 0:
        return {**base, "status": "insufficient_history", "reason": "volatility cannot be estimated from the stored bars"}
    bts = bar_trading_seconds(base_iv, kind)
    scale = conformal_scale(close)
    prox = _proxy_info(feed, symbol, base_iv, bars, anchor_t, now, kind)
    age = max(0.0, now - anchor_t)
    mode = "end_of_day" if base_iv == "1d" else "live"
    try:
        H = horizon if horizon is not None else max(P.horizon_for(interval, P.group_of(symbol)), 1)
    except Exception:   # the training horizon table has no 5m / 4h equity row; the chart still gets a path
        H = horizon if horizon is not None else {"5m": 36, "4h": 6}.get(interval, 24)
    # target grid: continue from the last real bar of THIS interval when there is one, else from the anchor
    own = tail_bars(feed, symbol, interval, now, kind) if interval != base_iv else bars
    seed = float(own[-1].event_time) if own else float(int(anchor_t // DUR[interval]) * DUR[interval] - DUR[interval])
    S_ = DUR[interval]
    if now - seed > (MAX_PATH // 2) * S_:       # a very stale series: start the grid near now so the path still reaches the present
        seed = (next_open(now - (MAX_PATH // 2) * S_, kind) - S_) if interval != "1d" else float(int((now - (MAX_PATH // 2) * S_) // S_) * S_)
    starts = grid_after(seed, interval, kind, min(MAX_PATH, max(H, 1) + int(max(0.0, now - seed) / DUR[interval]) + 2))
    pts, past_started = [], 0
    for s in starts:
        t_end = s + DUR[interval]
        if t_end <= anchor_t:
            continue
        if s >= now:
            past_started += 1
            if past_started > H:
                break
        ts = trading_seconds(anchor_t, t_end, kind)
        if ts <= 0:
            continue
        var_ts, mu = ts, 0.0
        if prox:
            span = trading_seconds(anchor_t, prox["t_proxy"], kind)
            if span > 0:
                f = min(1.0, trading_seconds(anchor_t, t_end, kind) / span)
                mu = prox["beta"] * prox["delta"] * f
                covered = min(ts, span)
                var_ts = ts - covered * prox["rho"] ** 2
        k = ts / bts
        half = qhat(scale, k) * live_scale * sig_bar * math.sqrt(max(var_ts, 1e-9) / bts)
        mid = anchor_px * math.exp(mu)
        pts.append({"t": int(s), "t_end": int(t_end), "mid": mid, "lo": mid * math.exp(-half), "hi": mid * math.exp(half), "k": round(k, 3),
                    "forming": bool(s < now <= t_end), "future": bool(s >= now)})
    if len(pts) > MAX_PATH:
        pts = pts[-MAX_PATH:]
    forming = [p for p in pts if p["forming"]]
    done = [p for p in pts if p["t_end"] <= now]
    cur = forming[0] if forming else (done[-1] if done else (pts[0] if pts else None))
    inputs = [{"input": "real bars", "interval": base_iv, "provider": provider if source == "bar" else getattr(last, "provider", None), "last_bar_end": int(last.event_time + DUR[base_iv])}]
    if source == "quote":
        inputs.append({"input": "live quote", "provider": provider, "at": int(anchor_t), "note": "a print newer than the last stored bar anchors the path"})
    if prox:
        inputs.append({"input": "proxy", "kind": "proxy", "label": "proxy, not " + symbol, "symbol": prox["proxy"], "beta": round(prox["beta"], 3), "corr": round(prox["rho"], 3),
                       "print_at": int(prox["t_proxy"]), "move_log": round(prox["delta"], 5)})
    reason = None
    if mode == "end_of_day":
        reason = ("Only end-of-day bars are stored for this asset, so this is a forecast path from the last close; the band widens with every "
                  "trading period since that close. Real intraday prints (OANDA practice, once configured) tighten it automatically.")
    from atlas.feeds.oanda_proxies import proxy_candidate
    pc = proxy_candidate(feed, symbol, lambda i: len(tail_bars(feed, i, "1m", now, "24x5")) >= MIN_BASE_BARS or len(tail_bars(feed, i, "15m", now, "24x5")) >= MIN_BASE_BARS)
    return {**base, "mode": mode, "reason": reason, "base_interval": base_iv, "proxy_candidate": pc, "inputs": inputs,
            "anchor": {"t": int(anchor_t), "price": anchor_px, "source": source, "provider": provider, "age_s": int(age),
                       "age_toronto": datetime.fromtimestamp(anchor_t, TORONTO).strftime("%Y-%m-%d %H:%M %Z")},
            "sigma_per_bar": sig_bar, "conformal_k": {str(k): round(v, 3) for k, v in scale.items()}, "live_scale": live_scale,
            "path": pts, "now": cur, "points": len(pts)}
