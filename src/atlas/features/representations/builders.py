"""Causal bar builders (all inputs are completed time bars in time order; outputs carry ``completed_at``).

Rule for every builder: an output bar exists only once completed, and ``completed_at`` is the ``end`` of the source
bar whose data completed it. No output depends on any source bar after ``completed_at``. Because the feed holds bars,
not trades, intrabar price paths are unknown; builders that need a path use the source **close** sequence (documented
per builder). Real prices only for fills: none of these outputs is used for execution or replay P&L.

Formulas
- heikin_ashi: HA_close = (O+H+L+C)/4; HA_open_0 = (O_0+C_0)/2, HA_open_t = (HA_open_{t-1}+HA_close_{t-1})/2;
  HA_high = max(H, HA_open, HA_close); HA_low = min(L, HA_open, HA_close). Synthetic prices; features/display only.
- renko(brick="atr"|float): brick size b = fixed float, or the causal ATR(14) of the source bars at the moment the
  brick forms (Wilder). Using source closes: while close >= last_brick_top + b, emit an up brick; while
  close <= last_brick_bottom - b, emit a down brick. A reversal needs 2b (the classic rule). Several bricks may complete
  on one source bar; they share that bar's completed_at. Time between bricks is irregular by design.
- range_bars(r="atr"|float): accumulate source closes; a bar completes when max(close)-min(close) over the current bar
  >= r (r = causal ATR(14) at bar open, or fixed). OHLC are the first/max/min/last source closes in the bar.
- threshold_bars(kind="volume"|"dollar", per_day=k): accumulate source volume (or volume*close); complete when the
  running sum >= threshold, threshold = (mean daily volume or dollar volume over the prior 20 completed UTC days)/k.
  Until 20 days of history exist no bar is produced (warmup). OHLC from the source bars' O/H/L/C. Gated unavailable
  if the source has no volume.
- kagi(rev="atr"|float): reversal amount r = causal ATR(14) at the source bar (or fixed). Using source closes, a
  line extends while price makes new extremes in its direction; when the close retraces >= r from the line's extreme,
  the line is complete and emitted (open = line start, close = extreme, high/low = line range), and a new line starts
  at the extreme in the opposite direction. The live (unfinished) line is never emitted. completed_at = end of the
  source bar whose close confirmed the reversal.
- point_figure(box="atr"|float, reversal=3): box size b = causal ATR(14) frozen when a column starts (or fixed).
  Using source closes, an X column extends by whole boxes while close >= top + b; it completes when close <= top - 3b
  (O columns mirror this). Only completed columns are emitted (open = column start level, close = last filled box,
  direction +1 for X, -1 for O); the live column is never emitted. completed_at = end of the reversing source bar.
- tick_bars: need trade-level prints. The feed stores bars only, so this returns [] with availability "unavailable".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from atlas.features.price_action.bars import Bar

BAR_TYPES = ("time", "heikin_ashi", "renko_atr", "range_atr", "volume", "dollar", "kagi_atr", "pnf_atr", "tick")


@dataclass(frozen=True)
class AltBar:
    kind: str
    start: int            # first source bar start included
    completed_at: int     # end of the source bar that completed this bar (availability time)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    direction: int = 0    # +1 / -1 for bricks; sign(close-open) otherwise
    n_src: int = 1


def _atr_series(bars: Sequence[Bar], n: int = 14) -> list[float | None]:
    out: list[float | None] = []
    atr = None
    prev = None
    for i, b in enumerate(bars):
        tr = b.high - b.low if prev is None else max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
        atr = tr if atr is None else (atr * (n - 1) + tr) / n
        out.append(atr if i + 1 >= n else None)
        prev = b.close
    return out


def _sgn(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def heikin_ashi(bars: Sequence[Bar]) -> list[AltBar]:
    out: list[AltBar] = []
    ho = hc = None
    for b in bars:
        c = (b.open + b.high + b.low + b.close) / 4
        o = (b.open + b.close) / 2 if ho is None else (ho + hc) / 2
        out.append(AltBar("heikin_ashi", b.start, b.end, o, max(b.high, o, c), min(b.low, o, c), c, b.volume, _sgn(c - o)))
        ho, hc = o, c
    return out


def renko(bars: Sequence[Bar], brick: float | Literal["atr"] = "atr") -> list[AltBar]:
    atr = _atr_series(bars) if brick == "atr" else None
    out: list[AltBar] = []
    top = bot = None
    last_dir = 0
    for i, b in enumerate(bars):
        size = (atr[i] if atr else float(brick))  # type: ignore[index,arg-type]
        if not size or size <= 0:
            continue
        if top is None:
            top = bot = b.close
            continue
        c = b.close
        while True:
            if last_dir >= 0 and c >= top + size:
                o, cl = top, top + size
                out.append(AltBar("renko_atr" if brick == "atr" else "renko", b.start, b.end, o, cl, o, cl, 0.0, 1))
                bot, top, last_dir = o, cl, 1
            elif last_dir <= 0 and c <= bot - size:
                o, cl = bot, bot - size
                out.append(AltBar("renko_atr" if brick == "atr" else "renko", b.start, b.end, o, o, cl, cl, 0.0, -1))
                top, bot, last_dir = o, cl, -1
            elif last_dir > 0 and c <= bot - size:           # reversal: 2 bricks from top
                o, cl = bot, bot - size
                out.append(AltBar("renko_atr" if brick == "atr" else "renko", b.start, b.end, o, o, cl, cl, 0.0, -1))
                top, bot, last_dir = o, cl, -1
            elif last_dir < 0 and c >= top + size:
                o, cl = top, top + size
                out.append(AltBar("renko_atr" if brick == "atr" else "renko", b.start, b.end, o, cl, o, cl, 0.0, 1))
                bot, top, last_dir = o, cl, 1
            else:
                break
    return out


def range_bars(bars: Sequence[Bar], r: float | Literal["atr"] = "atr") -> list[AltBar]:
    atr = _atr_series(bars) if r == "atr" else None
    out: list[AltBar] = []
    cur: dict | None = None
    for i, b in enumerate(bars):
        size = atr[i] if atr else float(r)  # type: ignore[index,arg-type]
        if cur is None:
            if not size:
                continue
            cur = {"start": b.start, "o": b.close, "h": b.close, "l": b.close, "v": 0.0, "n": 0, "r": size}
            continue
        cur["h"], cur["l"] = max(cur["h"], b.close), min(cur["l"], b.close)
        cur["v"] += b.volume
        cur["n"] += 1
        if cur["h"] - cur["l"] >= cur["r"]:
            out.append(AltBar("range_atr", cur["start"], b.end, cur["o"], cur["h"], cur["l"], b.close, cur["v"], _sgn(b.close - cur["o"]), cur["n"]))
            nxt = atr[i] if atr else float(r)  # type: ignore[index,arg-type]
            cur = {"start": b.end, "o": b.close, "h": b.close, "l": b.close, "v": 0.0, "n": 0, "r": nxt}
    return out


def threshold_bars(bars: Sequence[Bar], kind: Literal["volume", "dollar"] = "volume", per_day: int = 24, lookback_days: int = 20) -> list[AltBar]:
    if not any(b.volume for b in bars):
        return []
    daily: dict[int, float] = {}
    out: list[AltBar] = []
    cur: dict | None = None
    for b in bars:
        day = b.start // 86400
        amt = b.volume * (b.close if kind == "dollar" else 1.0)
        prior = [v for d, v in daily.items() if d < day][-lookback_days:]
        daily[day] = daily.get(day, 0.0) + amt
        if len(prior) < lookback_days:
            continue
        thr = sum(prior) / len(prior) / per_day
        if thr <= 0:
            continue
        if cur is None:
            cur = {"start": b.start, "o": b.open, "h": b.high, "l": b.low, "s": 0.0, "v": 0.0, "n": 0}
        cur["h"], cur["l"] = max(cur["h"], b.high), min(cur["l"], b.low)
        cur["s"] += amt
        cur["v"] += b.volume
        cur["n"] += 1
        if cur["s"] >= thr:
            out.append(AltBar(kind, cur["start"], b.end, cur["o"], cur["h"], cur["l"], b.close, cur["v"], _sgn(b.close - cur["o"]), cur["n"]))
            cur = None
    return out


def kagi(bars: Sequence[Bar], rev: float | Literal["atr"] = "atr") -> list[AltBar]:
    atr = _atr_series(bars) if rev == "atr" else None
    out: list[AltBar] = []
    anchor = None
    d = 0
    seg_start = ext = lo = hi = 0.0
    seg_t = 0
    n = 0
    for i, b in enumerate(bars):
        r = atr[i] if atr else float(rev)  # type: ignore[index,arg-type]
        c = b.close
        if anchor is None:
            anchor, seg_t = c, b.start
            continue
        if not r or r <= 0:
            continue
        if d == 0:
            if abs(c - anchor) >= r:
                d = 1 if c > anchor else -1
                seg_start, ext, lo, hi, n = anchor, c, min(anchor, c), max(anchor, c), 1
            continue
        n += 1
        lo, hi = min(lo, c), max(hi, c)
        if (d > 0 and c > ext) or (d < 0 and c < ext):
            ext = c
        elif (d > 0 and c <= ext - r) or (d < 0 and c >= ext + r):
            out.append(AltBar("kagi_atr" if rev == "atr" else "kagi", seg_t, b.end, seg_start, max(seg_start, ext), min(seg_start, ext), ext, 0.0, d, n))
            seg_start, seg_t, d = ext, b.start, -d
            ext, lo, hi, n = c, min(seg_start, c), max(seg_start, c), 1
    return out


def point_figure(bars: Sequence[Bar], box: float | Literal["atr"] = "atr", reversal: int = 3) -> list[AltBar]:
    atr = _atr_series(bars) if box == "atr" else None
    kind = "pnf_atr" if box == "atr" else "pnf"
    out: list[AltBar] = []
    anchor = None
    d = 0
    bs = start_lvl = last = 0.0
    col_t = 0
    n = 0
    for i, b in enumerate(bars):
        size = atr[i] if atr else float(box)  # type: ignore[index,arg-type]
        c = b.close
        if anchor is None:
            anchor, col_t = c, b.start
            continue
        if d == 0:
            if not size or size <= 0:
                continue
            k = int(abs(c - anchor) // size)
            if k >= 1:
                d, bs, start_lvl, n = (1 if c > anchor else -1), size, anchor, 1
                last = anchor + d * k * size
            continue
        n += 1
        if d > 0:
            k = int((c - last) // bs) if c > last else 0
            if k >= 1:
                last += k * bs
            elif c <= last - reversal * bs:
                out.append(AltBar(kind, col_t, b.end, start_lvl, last, start_lvl, last, 0.0, 1, n))
                nb = size if size and size > 0 else bs
                start_lvl, col_t, d, n = last - bs, b.start, -1, 1
                bs = nb
                last = start_lvl - int((start_lvl - c) // bs) * bs
        else:
            k = int((last - c) // bs) if c < last else 0
            if k >= 1:
                last -= k * bs
            elif c >= last + reversal * bs:
                out.append(AltBar(kind, col_t, b.end, start_lvl, start_lvl, last, last, 0.0, -1, n))
                nb = size if size and size > 0 else bs
                start_lvl, col_t, d, n = last + bs, b.start, 1, 1
                bs = nb
                last = start_lvl + int((c - start_lvl) // bs) * bs
    return out


def tick_bars(bars: Sequence[Bar], trades: Sequence | None = None, n: int = 500) -> list[AltBar]:
    """Gated: requires trade prints, which the ATLAS feed does not store. Never approximated from bars."""
    return []


def availability(bars: Sequence[Bar], has_trades: bool = False) -> dict[str, dict]:
    vol = any(b.volume for b in bars)
    a = {t: {"available": True} for t in BAR_TYPES}
    for t in ("volume", "dollar"):
        if not vol:
            a[t] = {"available": False, "reason": "source bars carry no volume"}
    if not has_trades:
        a["tick"] = {"available": False, "reason": "tick bars need trade-level prints; the feed stores bars only"}
    a["heikin_ashi"]["note"] = "synthetic prices: features/display only, never fills or P&L"
    return a


def build(kind: str, bars: Sequence[Bar]) -> list[AltBar]:
    if kind == "heikin_ashi":
        return heikin_ashi(bars)
    if kind == "renko_atr":
        return renko(bars, "atr")
    if kind == "range_atr":
        return range_bars(bars, "atr")
    if kind in ("volume", "dollar"):
        return threshold_bars(bars, kind)  # type: ignore[arg-type]
    if kind == "kagi_atr":
        return kagi(bars, "atr")
    if kind == "pnf_atr":
        return point_figure(bars, "atr")
    if kind == "tick":
        return tick_bars(bars)
    if kind == "time":
        return [AltBar("time", b.start, b.end, b.open, b.high, b.low, b.close, b.volume, _sgn(b.close - b.open)) for b in bars]
    raise ValueError(kind)
