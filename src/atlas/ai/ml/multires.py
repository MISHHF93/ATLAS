"""Multi-resolution features on a 15-minute decision clock (milestone c).

Layers: 1s trade bars, 1m, 5m (built from 1m), 15m and 1h bars. A decision at time ``T`` (a multiple of 900 s,
UTC) may use only bars whose END is <= T. Every feature is computed by ``features_at(inputs, T)`` from slices of
already-closed data, so truncating all inputs after T cannot change the result (tests prove it).

Honesty rules:
  * a feature is NaN when the underlying real data does not exist or the window is not contiguous. Nothing is
    forward-filled, interpolated or predicted here;
  * order flow / trade intensity / 1s volatility exist only for crypto, only since the 1s aggregator started
    (``atlas_1s.sqlite``), and trade intensity is only computed for minutes in which the collector was provably
    alive (some instrument on the venue had a row) so a collector outage never reads as "no trades";
  * spread: no bid/ask is persisted anywhere, so there is NO spread feature (reported unavailable, not faked);
  * vwap deviation is bar-approximated (typical price x volume) for 15m/1m and trade-exact for crypto flow.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

FEATURE_SCHEMA = "atlas-multires-v1"
DECISION_S = 900
BAR_S = {"1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600}
NAN = float("nan")

# candidate decision horizons in 15-minute bars (15m, 30m, 1h, 2h, 4h, 8h, 24h); milestone (c) tunes the set
CANDIDATE_HORIZON_BARS = (1, 2, 4, 8, 16, 32, 96)

GROUP_FEATURES: dict[str, tuple[str, ...]] = {
    "m15": ("m15_ret1", "m15_ret4", "m15_ret16", "m15_rv16", "m15_vwapdev16", "m15_volz", "m15_range"),
    "h1": ("h1_ret1", "h1_ret6", "h1_rv24"),
    "m5": ("m5_ret1", "m5_rv"),
    "m1": ("m1_ret15", "m1_rv15", "m1_rv60", "m1_vwapdev15", "m1_vwapdev60", "m1_vol_ratio", "m1_cover15"),
    "flow": ("f_ofi1", "f_ofi5", "f_ofi15", "f_ti15", "f_ti_ratio", "f_vwapdev15", "f_active15"),
    "s1": ("s1_rv15", "s1_n15", "s1_ret60", "s1_ofi60"),
}
FEATURE_NAMES: tuple[str, ...] = tuple(n for g in GROUP_FEATURES.values() for n in g)
SPREAD_AVAILABLE = False     # no bid/ask is stored; see module docstring


@dataclass(frozen=True)
class Bars:
    """Closed OHLCV bars of one interval, sorted by start, unique."""
    interval: str
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    @property
    def dur(self) -> int:
        return BAR_S[self.interval]

    @property
    def end(self) -> np.ndarray:
        return self.ts + self.dur

    def __len__(self) -> int:
        return int(self.ts.shape[0])

    @classmethod
    def from_rows(cls, interval: str, rows: Iterable[tuple]) -> "Bars":
        """rows: (start_ts, open, high, low, close, volume)."""
        d: dict[int, tuple] = {}
        for r in rows:
            d[int(r[0])] = r
        ks = sorted(d)
        a = np.array([d[k][1:6] for k in ks], dtype=float).reshape(-1, 5)
        return cls(interval, np.array(ks, dtype=np.int64), a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4])

    @classmethod
    def from_feed(cls, interval: str, bars: Sequence) -> "Bars":
        return cls.from_rows(interval, ((b.event_time, b.open, b.high, b.low, b.close, b.volume) for b in bars))

    def n_closed(self, T: int) -> int:
        """number of bars with end <= T (bars are sorted so these are a prefix)."""
        return int(np.searchsorted(self.end, T, side="right"))

    def window(self, lo: int, hi: int) -> tuple[int, int]:
        """index range of bars with start >= lo and end <= hi."""
        return int(np.searchsorted(self.ts, lo, side="left")), self.n_closed(hi)


@dataclass(frozen=True)
class Flow:
    """Crypto trade flow per minute (from flow_1m) plus the venue-alive minute set."""
    ts: np.ndarray
    vol: np.ndarray
    buy: np.ndarray
    sell: np.ndarray
    ntr: np.ndarray
    vnum: np.ndarray
    active_s: np.ndarray
    close: np.ndarray
    alive_ts: np.ndarray           # minute starts in which the collector provably ran (any instrument on the venue)

    @classmethod
    def from_rows(cls, rows: Sequence[tuple], alive: Iterable[int]) -> "Flow":
        """rows: (ts, volume, buy_vol, sell_vol, n_trades, vwap_num, active_s, open, high, low, close)."""
        a = np.array(rows, dtype=float).reshape(-1, 11)
        order = np.argsort(a[:, 0], kind="stable")
        a = a[order]
        return cls(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 6], a[:, 10],
                   np.array(sorted(set(int(x) for x in alive)), dtype=np.int64))


@dataclass(frozen=True)
class Secs:
    """1s trade bars: (ts, close, volume, buy, sell, n_trades)."""
    ts: np.ndarray
    c: np.ndarray
    vol: np.ndarray
    buy: np.ndarray
    sell: np.ndarray
    ntr: np.ndarray

    @classmethod
    def from_rows(cls, rows: Sequence[tuple]) -> "Secs":
        """rows: (ts, open, high, low, close, volume, buy_vol, sell_vol, n_trades, vwap_num)."""
        a = np.array(rows, dtype=float).reshape(-1, 10)
        a = a[np.argsort(a[:, 0], kind="stable")]
        return cls(a[:, 0].astype(np.int64), a[:, 4], a[:, 5], a[:, 6], a[:, 7], a[:, 8])


@dataclass
class Inputs:
    instrument: str
    s1m: Bars | None = None
    s15: Bars | None = None
    s1h: Bars | None = None
    flow: Flow | None = None
    secs: Secs | None = None


# ---------------------------------------------------------------- helpers
def _lr(a: float, b: float) -> float:
    return math.log(a / b) if a > 0 and b > 0 else NAN


def _contig(ts: np.ndarray, dur: int) -> bool:
    return bool(ts.shape[0] >= 1 and np.all(np.diff(ts) == dur))


def _rv(c: np.ndarray, ts: np.ndarray, dur: int) -> float:
    """sqrt(sum of squared close-to-close log returns) over CONSECUTIVE bar pairs only."""
    if c.shape[0] < 2:
        return NAN
    ok = np.diff(ts) == dur
    if not ok.any():
        return NAN
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(c[1:] / c[:-1])
    r = r[ok]
    r = r[np.isfinite(r)]
    return float(math.sqrt(float(np.sum(r * r)))) if r.size else NAN


def _vwapdev(h, l, c, v) -> float:
    sv = float(np.sum(v))
    if c.shape[0] < 1 or not sv > 0:
        return NAN
    vw = float(np.sum((h + l + c) / 3.0 * v)) / sv
    return (float(c[-1]) / vw - 1.0) * 1e4 if vw > 0 else NAN


def _bar_group(prefix: str, b: Bars | None, T: int, rets: Sequence[int], rv_k: int, vwap_k: int | None, with_volz=False) -> dict:
    out: dict[str, float] = {}
    if b is None:
        return out
    n = b.n_closed(T)
    if n < 1 or T - int(b.end[n - 1]) > 4 * b.dur:      # nothing closed, or the series is stale (collector gap)
        return out
    ts, c = b.ts, b.c
    for k in rets:
        if n - 1 - k >= 0 and _contig(ts[n - 1 - k:n], b.dur):
            out[f"{prefix}_ret{k}"] = _lr(c[n - 1], c[n - 1 - k])
    lo = max(0, n - 1 - rv_k)
    if n - lo >= 2:
        out[f"{prefix}_rv{rv_k}"] = _rv(c[lo:n], ts[lo:n], b.dur)
    if vwap_k:
        lo = max(0, n - vwap_k)
        if _contig(ts[lo:n], b.dur):
            out[f"{prefix}_vwapdev{vwap_k}"] = _vwapdev(b.h[lo:n], b.l[lo:n], c[lo:n], b.v[lo:n])
    if with_volz and n >= 4:
        lo = max(0, n - 16)
        if _contig(ts[lo:n], b.dur):
            m = float(np.mean(b.v[lo:n - 1])) if n - 1 > lo else 0.0
            if m > 0 and b.v[n - 1] > 0:
                out[f"{prefix}_volz"] = math.log(float(b.v[n - 1]) / m)
    if with_volz:
        if b.l[n - 1] > 0:
            out[f"{prefix}_range"] = _lr(b.h[n - 1], b.l[n - 1])
    return out


def _m5_group(b: Bars | None, T: int) -> dict:
    """5m bars built ONLY from complete (5 x 1m) buckets inside the last 15 minutes."""
    out: dict[str, float] = {}
    if b is None:
        return out
    a, z = b.window(T - DECISION_S, T)
    if z - a < 5:
        return out
    ts, c = b.ts[a:z], b.c[a:z]
    bucket = ts // 300
    closes: dict[int, float] = {}
    for u in np.unique(bucket):
        m = bucket == u
        if int(m.sum()) == 5 and _contig(ts[m], 60):
            closes[int(u)] = float(c[m][-1])
    ks = sorted(closes)
    if len(ks) >= 2 and all(ks[i + 1] - ks[i] == 1 for i in range(len(ks) - 1)):
        r = [_lr(closes[ks[i + 1]], closes[ks[i]]) for i in range(len(ks) - 1)]
        out["m5_ret1"] = r[-1]
        out["m5_rv"] = float(math.sqrt(sum(x * x for x in r)))
    return out


def _m1_group(b: Bars | None, T: int) -> dict:
    out: dict[str, float] = {}
    if b is None:
        return out
    a, z = b.window(T - DECISION_S, T)
    n15 = z - a
    out["m1_cover15"] = n15 / 15.0 if n15 else NAN
    if n15 >= 2:
        if n15 == 15 and _contig(b.ts[a:z], 60):          # a window with a hole is NaN, never a shorter span passed off as 15m
            out["m1_ret15"] = _lr(b.c[z - 1], b.o[a])
        out["m1_rv15"] = _rv(b.c[a:z], b.ts[a:z], 60)
        out["m1_vwapdev15"] = _vwapdev(b.h[a:z], b.l[a:z], b.c[a:z], b.v[a:z])
    a60, z60 = b.window(T - 3600, T)
    if z60 - a60 >= 20:
        out["m1_rv60"] = _rv(b.c[a60:z60], b.ts[a60:z60], 60)
        out["m1_vwapdev60"] = _vwapdev(b.h[a60:z60], b.l[a60:z60], b.c[a60:z60], b.v[a60:z60])
    a4, z4 = b.window(T - 14400, T)
    if n15 >= 5 and z4 - a4 >= 60:
        m15 = float(np.mean(b.v[a:z]))
        m4 = float(np.mean(b.v[a4:z4]))
        if m15 > 0 and m4 > 0:
            out["m1_vol_ratio"] = m15 / m4
    return out


def _ofi(buy: float, sell: float) -> float:
    s = buy + sell
    return (buy - sell) / s if s > 0 else NAN


def _flow_group(fl: Flow | None, T: int) -> dict:
    out: dict[str, float] = {}
    if fl is None or fl.ts.shape[0] == 0:
        return out

    def rng(lo: int, hi: int) -> tuple[int, int]:
        return int(np.searchsorted(fl.ts, lo, side="left")), int(np.searchsorted(fl.ts, hi, side="left"))

    def alive(lo: int, hi: int) -> int:
        return int(np.searchsorted(fl.alive_ts, hi, side="left") - np.searchsorted(fl.alive_ts, lo, side="left"))

    for name, w in (("f_ofi1", 60), ("f_ofi5", 300), ("f_ofi15", 900)):
        a, z = rng(T - w, T)
        if z > a:
            out[name] = _ofi(float(fl.buy[a:z].sum()), float(fl.sell[a:z].sum()))
    a, z = rng(T - 900, T)
    al15 = alive(T - 900, T)
    if al15 >= 10:
        out["f_ti15"] = float(fl.ntr[a:z].sum()) / al15            # trades per alive minute (zero-trade minutes count)
        out["f_active15"] = float(fl.active_s[a:z].sum()) / (al15 * 60.0)
        a4, z4 = rng(T - 14400, T)
        al4 = alive(T - 14400, T)
        if al4 >= 120:
            ti4 = float(fl.ntr[a4:z4].sum()) / al4
            if ti4 > 0:
                out["f_ti_ratio"] = out["f_ti15"] / ti4
    if z > a:
        sv = float(fl.vol[a:z].sum())
        if sv > 0:
            vw = float(fl.vnum[a:z].sum()) / sv
            if vw > 0:
                out["f_vwapdev15"] = (float(fl.close[z - 1]) / vw - 1.0) * 1e4
    return out


def _secs_group(s: Secs | None, T: int) -> dict:
    out: dict[str, float] = {}
    if s is None or s.ts.shape[0] == 0:
        return out
    a, z = int(np.searchsorted(s.ts, T - DECISION_S, side="left")), int(np.searchsorted(s.ts, T, side="left"))
    n = z - a
    out["s1_n15"] = float(n)
    if n >= 10:
        c = s.c[a:z]
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.log(c[1:] / c[:-1])
        r = r[np.isfinite(r)]
        out["s1_rv15"] = float(math.sqrt(float(np.sum(r * r)))) if r.size else NAN
    a6 = int(np.searchsorted(s.ts, T - 60, side="left"))
    if z - a6 >= 2:
        out["s1_ret60"] = _lr(s.c[z - 1], s.c[a6])
    if z > a6:
        out["s1_ofi60"] = _ofi(float(s.buy[a6:z].sum()), float(s.sell[a6:z].sum()))
    return out


# ---------------------------------------------------------------- public API
def features_at(inp: Inputs, T: int) -> dict[str, float]:
    """All features for the decision at ``T`` using only data whose end is <= T. Missing -> NaN."""
    T = int(T)
    f: dict[str, float] = {}
    f.update(_bar_group("m15", inp.s15, T, (1, 4, 16), 16, 16, with_volz=True))
    f.update(_bar_group("h1", inp.s1h, T, (1, 6), 24, None))
    f.update(_m5_group(inp.s1m, T))
    f.update(_m1_group(inp.s1m, T))
    f.update(_flow_group(inp.flow, T))
    f.update(_secs_group(inp.secs, T))
    return {k: f.get(k, NAN) for k in FEATURE_NAMES}


def decision_grid(start: int, end: int) -> list[int]:
    """15m decision times t with start <= t < end, multiples of 900 s (UTC; also the ET quarter-hours)."""
    first = -(-int(start) // DECISION_S) * DECISION_S
    return list(range(first, int(end), DECISION_S))


def build_frame(inp: Inputs, grid: Iterable[int]) -> pd.DataFrame:
    rows = [features_at(inp, t) for t in grid]
    idx = pd.Index([int(t) for t in grid], name="decision_ts")
    return pd.DataFrame(rows, index=idx, columns=list(FEATURE_NAMES))


def availability(df: pd.DataFrame) -> dict[str, float]:
    """share of decision rows with at least one real value, per feature group (honest coverage)."""
    return {g: float(df[list(cols)].notna().any(axis=1).mean()) if len(df) else 0.0 for g, cols in GROUP_FEATURES.items()}


def load_inputs(feed, instrument: str, *, provider: str, start: int, end: int, trade_store=None, venue: str | None = None,
                intervals: Sequence[str] = ("1m", "15m", "1h")) -> Inputs:
    """Read real stored bars (confirmed only) and, for crypto, the 1s aggregator tables (read-only)."""
    inp = Inputs(instrument)
    for iv in intervals:
        rows = getattr(feed, "store", feed).bars(instrument, iv, start - 4 * 86400, end, provider=provider, confirmed_only=True)
        if rows:
            setattr(inp, {"1m": "s1m", "15m": "s15", "1h": "s1h"}[iv], Bars.from_feed(iv, rows))
    if trade_store is not None and venue:
        lo = start - 4 * 86400
        fr = trade_store.flow_1m(venue, instrument, lo, end)
        if fr:
            alive = _alive_minutes(trade_store, venue, lo, end)
            inp.flow = Flow.from_rows(fr, alive)
        sr = trade_store.bars_1s(venue, instrument, lo, end)
        if sr:
            inp.secs = Secs.from_rows(sr)
    return inp


def _alive_minutes(trade_store, venue: str, lo: int, hi: int) -> list[int]:
    with trade_store._ro() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT ts FROM flow_1m WHERE venue=? AND ts>=? AND ts<?", (venue, int(lo), int(hi)))]
