"""Shared price-level contract, POTENTIAL LIQUIDITY REFERENCE LEVELS registry and the generic causal
price-level interaction engine that SFP, Snapback and ORB-breakout all consume (no duplicated interaction logic).

Definitions (all on COMPLETED bars; a level is usable only by bars with ``bar.start >= available_ts``):
- Period levels: high / low of the previous COMPLETED trading day / ISO week / calendar month, where the trading day
  is the venue calendar session (``calendar.TradingCalendar``: UTC day for crypto, exchange_calendars for XNYS/COMEX/...).
  available_ts = end of the last bar of that period (the period is complete only when a bar of a later period arrives).
- Session levels (24h assets only): Asia = 09:00-15:00 Asia/Tokyo, London = 08:00-16:30 Europe/London,
  New York = 09:30-16:00 America/New_York. available_ts = session close.
- Swing points (fractal k): bar i is a swing high if high_i > max(high_{i-k..i-1}) and high_i >= max(high_{i+1..i+k});
  available at the end of bar i+k (never earlier).
- Equal highs/lows: two confirmed swing highs (lows) within ``eq_tol = max(eq_ticks*tick, eq_atr*ATR)`` and at most
  ``eq_max_gap`` bars apart -> a level at the more extreme price, available when the later swing is confirmed.
- Box boundaries (opening range, gold boxes) are added by their owners via ``add_level``.
These are labelled POTENTIAL LIQUIDITY REFERENCE LEVELS: whether resting liquidity exists there is UNVERIFIED
(no order-book data is stored).

Interaction engine (per level, side s=+1 if the level is above the last close, else -1; prices are sign-transformed so
the bull and bear cases share one code path): states
LEVEL_IDENTIFIED -> PRICE_APPROACHING -> LEVEL_TESTED -> BREAKOUT_OR_REJECTION_OBSERVED -> AWAITING_CONFIRMATION ->
{ACCEPTED | RECLAIMED | REJECTED | UNRESOLVED} (+ EXPIRED). Classified events: approach, touch, rejection,
breakout_attempt, sweep, reclaim, breakout_acceptance, breakout_failure, retest_success, retest_failure,
consolidation (unresolved), expiration. After ACCEPTED the side flips and the next episode is a retest.
Downstream pipeline states STRATEGY_CANDIDATE -> ML_EVALUATION -> RISK_EVALUATION -> PAPER_EXECUTION_OR_ABSTENTION are
owned by consumers / proposals.evaluate / the control plane.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import time
from typing import Any

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.calendar import TradingCalendar
from atlas.features.price_action.detectors import Transition
from atlas.features.price_action.sessions import SessionSpec

LABEL = "POTENTIAL LIQUIDITY REFERENCE LEVELS"
INTERACTION_STATES = ("LEVEL_IDENTIFIED", "PRICE_APPROACHING", "LEVEL_TESTED", "BREAKOUT_OR_REJECTION_OBSERVED",
                      "AWAITING_CONFIRMATION", "ACCEPTED", "RECLAIMED", "REJECTED", "UNRESOLVED", "EXPIRED")
PIPELINE_STATES = ("STRATEGY_CANDIDATE", "ML_EVALUATION", "RISK_EVALUATION", "PAPER_EXECUTION_OR_ABSTENTION")
EVENT_KINDS = ("approach", "touch", "rejection", "breakout_attempt", "sweep", "reclaim", "breakout_acceptance",
               "breakout_failure", "retest_success", "retest_failure", "consolidation", "expiration")
# priority for dedupe when one bar sweeps several levels (higher = more significant)
PRIORITY = {"prev_month": 9, "prev_week": 8, "prev_day": 7, "ny_session": 6, "london_session": 6, "asia_session": 5,
            "equal": 4, "box": 4, "round": 3, "swing": 3}

ASIA = SessionSpec("asia", "Asia/Tokyo", time(9, 0), time(15, 0), weekdays=(0, 1, 2, 3, 4, 5, 6))
LONDON = SessionSpec("london", "Europe/London", time(8, 0), time(16, 30), weekdays=(0, 1, 2, 3, 4, 5, 6))
NEWYORK = SessionSpec("ny", "America/New_York", time(9, 30), time(16, 0), weekdays=(0, 1, 2, 3, 4, 5, 6))


@dataclass
class PriceLevel:
    id: str
    instrument: str
    venue: str
    source_type: str          # prev_day | prev_week | prev_month | asia_session | london_session | ny_session | swing | equal | box
    kind: str                 # high | low
    price: float
    created_ts: int           # start of the first bar that defines it
    available_ts: int         # first instant it may be used
    session_id: str
    timeframe: int
    confirmation: str = "confirmed"
    touch_count: int = 0
    state: str = "LEVEL_IDENTIFIED"
    invalidation: str = "accepted through (N consecutive closes beyond) or expired"
    expires_ts: int | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    label: str = LABEL
    # zone-registry evidence fields (counts are observed interactions, not predictions)
    confluence_ids: list[str] = field(default_factory=list)   # other levels within tolerance at availability
    rejection_count: int = 0
    breakout_attempt_count: int = 0
    sweep_count: int = 0
    acceptance_count: int = 0
    last_event_ts: int | None = None

    def age(self, now: int) -> int:
        return max(0, now - self.available_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LevelEvent:
    level_id: str
    event_id: str             # level_id#episode: the shared-evidence key
    kind: str
    at: int                   # bar end
    side: int                 # +1 level was above price, -1 below (orientation of THIS episode)
    post_accept: bool         # True when this episode is a retest after the level was accepted through
    extreme: float            # most extreme price beyond the level in this episode (real price), else level
    bars: int                 # bars since the episode's first crossing
    detail: str = ""


@dataclass
class InteractionConfig:
    tick: float = 0.01
    approach_atr: float = 0.5
    touch_atr: float = 0.05
    min_cross_ticks: float = 1.0
    accept_bars: int = 2          # consecutive closes beyond level (+ accept_buffer) -> ACCEPTED
    accept_buffer_atr: float = 0.0
    reject_atr: float = 0.25      # touch bar closing this far away -> REJECTED
    confirm_window: int = 4       # bars after crossing before UNRESOLVED


class _Tracker:
    def __init__(self, lvl: PriceLevel, side: int):
        self.lvl, self.s, self.state, self.ep, self.post = lvl, side, "LEVEL_IDENTIFIED", 0, False
        self.ext = self.bars = self.beyond = 0
        self.approached = False


class LevelInteractionEngine:
    def __init__(self, cfg: InteractionConfig | None = None):
        self.cfg = cfg or InteractionConfig()
        self.trackers: dict[str, _Tracker] = {}
        self.transitions: list[Transition] = []
        self._seq = 0

    def watch(self, lvl: PriceLevel, last_close: float) -> None:
        self.trackers[lvl.id] = _Tracker(lvl, 1 if lvl.price > last_close else -1)

    def _go(self, tr: _Tracker, to: str, at: int, why: str) -> None:
        self._seq += 1
        self.transitions.append(Transition(tr.lvl.id, self._seq, tr.state, to, at, why))
        tr.state = to
        tr.lvl.state = to

    def step(self, bar: Bar, atr: float | None) -> list[LevelEvent]:
        out: list[LevelEvent] = []
        c = self.cfg
        a = atr or 0.0
        for lid in list(self.trackers):
            tr = self.trackers[lid]
            lvl = tr.lvl
            if bar.start < lvl.available_ts:
                continue
            s = tr.s
            hi, cl, L = (bar.high if s > 0 else -bar.low), s * bar.close, s * lvl.price
            evid = f"{lid}#{tr.ep}"

            def ev(kind: str, extreme: float | None = None, detail: str = "") -> None:
                x = L if extreme is None else extreme
                lvl.last_event_ts = bar.end
                if kind == "rejection":
                    lvl.rejection_count += 1
                elif kind == "breakout_attempt":
                    lvl.breakout_attempt_count += 1
                elif kind == "sweep":
                    lvl.sweep_count += 1
                elif kind == "breakout_acceptance":
                    lvl.acceptance_count += 1
                out.append(LevelEvent(lid, evid, kind, bar.end, s, tr.post, s * x, tr.bars, detail))

            if lvl.expires_ts is not None and bar.start >= lvl.expires_ts and tr.state != "AWAITING_CONFIRMATION":
                self._go(tr, "EXPIRED", bar.end, "max age")
                ev("expiration")
                del self.trackers[lid]
                continue
            cross = c.min_cross_ticks * c.tick
            if tr.state in ("LEVEL_IDENTIFIED", "PRICE_APPROACHING", "LEVEL_TESTED"):
                if hi > L + cross:
                    self._go(tr, "BREAKOUT_OR_REJECTION_OBSERVED", bar.end, "traded beyond level")
                    tr.ext, tr.bars, tr.beyond = hi, 0, 0
                    ev("breakout_attempt", hi)
                    self._confirm(tr, bar, cl, L, a, ev)
                elif hi >= L - max(c.touch_atr * a, c.tick):
                    lvl.touch_count += 1
                    if tr.state != "LEVEL_TESTED":
                        self._go(tr, "LEVEL_TESTED", bar.end, "touched within tolerance")
                    ev("touch")
                    if cl < L - c.reject_atr * a:
                        self._go(tr, "REJECTED", bar.end, "closed away after touch")
                        ev("retest_success" if tr.post else "rejection")
                        self._rearm(tr)
                elif hi >= L - c.approach_atr * a and tr.state == "LEVEL_IDENTIFIED":
                    self._go(tr, "PRICE_APPROACHING", bar.end, "within approach distance")
                    ev("approach")
            elif tr.state == "AWAITING_CONFIRMATION":
                tr.bars += 1
                tr.ext = max(tr.ext, hi)
                self._confirm(tr, bar, cl, L, a, ev)
        return out

    def _confirm(self, tr: _Tracker, bar: Bar, cl: float, L: float, a: float, ev) -> None:
        c = self.cfg
        if cl < L:
            self._go(tr, "RECLAIMED", bar.end, "closed back on the original side")
            ev("sweep", tr.ext)
            ev("retest_success" if tr.post else "reclaim", tr.ext)
            self._rearm(tr)
            return
        if cl > L + c.accept_buffer_atr * a:
            tr.beyond += 1
        else:
            tr.beyond = 0
        if tr.beyond >= c.accept_bars:
            self._go(tr, "ACCEPTED", bar.end, f"{tr.beyond} closes beyond")
            ev("retest_failure" if tr.post else "breakout_acceptance", tr.ext)
            if tr.post:
                ev("breakout_failure", tr.ext)
            post = not tr.post
            tr.s = -tr.s
            self._rearm(tr)
            tr.post = post
            return
        if tr.state != "AWAITING_CONFIRMATION":
            self._go(tr, "AWAITING_CONFIRMATION", bar.end, "beyond level, unresolved")
        elif tr.bars >= c.confirm_window:
            self._go(tr, "UNRESOLVED", bar.end, "confirmation window elapsed")
            ev("consolidation", tr.ext)
            self._rearm(tr)

    def _rearm(self, tr: _Tracker) -> None:
        tr.ep += 1
        tr.ext = tr.bars = tr.beyond = 0
        tr.state = tr.lvl.state = "LEVEL_IDENTIFIED"


@dataclass
class RegistryConfig:
    swing_k: int = 3
    swing_max_age: int = 3 * 86400
    eq_ticks: float = 2.0
    eq_atr: float = 0.10
    eq_max_gap: int = 96
    sessions: bool = True          # Asia/London/NY levels (24h instruments only)
    periods: tuple[str, ...] = ("day", "week", "month")
    round_step: float | None = None   # psychological round-number levels (e.g. 50.0 for GC); None = off
    round_max_age: int = 7 * 86400
    confluence_atr: float = 0.15      # levels within this many ATR are linked in confluence_ids


class LiquidityLevelRegistry:
    """Causal registry. ``step(bar, atr)`` returns the levels that became available at this bar's end."""

    def __init__(self, instrument: str, venue: str, timeframe: int, calendar: TradingCalendar,
                 cfg: RegistryConfig | None = None, tick: float = 0.01):
        self.instrument, self.venue, self.tf, self.cal, self.cfg, self.tick = instrument, venue, timeframe, calendar, cfg or RegistryConfig(), tick
        self.levels: list[PriceLevel] = []
        self.current: dict[str, PriceLevel] = {}       # source_type:kind -> latest period/session level
        self._agg: dict[str, dict[str, Any]] = {}
        self._win: deque[Bar] = deque(maxlen=2 * self.cfg.swing_k + 1)
        self._swings: list[tuple[int, PriceLevel]] = []
        self._n = 0
        self.daily_closes: list[tuple[int, float]] = []   # (available_ts, close) of completed trading days

    def _mk(self, st: str, kind: str, price: float, created: int, avail: int, sid: str, prov: dict, expires=None) -> PriceLevel:
        lv = PriceLevel(f"{self.instrument}:{st}:{kind}:{created}", self.instrument, self.venue, st, kind, price, created, avail,
                        sid, self.tf, expires_ts=expires, provenance={"source": "atlas_feed_confirmed_bars", **prov})
        self.levels.append(lv)
        return lv

    def add_level(self, st: str, kind: str, price: float, created: int, avail: int, sid: str, prov: dict,
                  expires: int | None = None) -> PriceLevel:
        return self._mk(st, kind, price, created, avail, sid, prov, expires)

    def _period_keys(self, bar: Bar) -> dict[str, tuple[str, str]]:
        s = self.cal.session_of(bar.start)
        if s is None:
            return {}
        d = s[0]
        iso = d.isocalendar()
        keys = {"day": (d.isoformat(), d.isoformat()), "week": (f"{iso[0]}-W{iso[1]:02d}", d.isoformat()),
                "month": (f"{d.year}-{d.month:02d}", d.isoformat())}
        if self.cfg.sessions and self.cal.code != "XNYS":
            for sp in (ASIA, LONDON, NEWYORK):
                w = sp.window_for(bar.start)
                if w is not None and bar.end <= w[2]:
                    keys[f"{sp.name}_session"] = (w[0], str(w[2]))
        return {k: v for k, v in keys.items() if k in self.cfg.periods or k.endswith("_session")}

    def _finalize(self, name: str, ag: dict[str, Any]) -> list[PriceLevel]:
        st = name if name.endswith("_session") else f"prev_{name}"
        avail = int(ag["close"]) if name.endswith("_session") else ag["last_end"]
        new = []
        for kind, px, at in (("high", ag["h"], ag["h_at"]), ("low", ag["l"], ag["l_at"])):
            old = self.current.get(f"{st}:{kind}")
            if old is not None:
                old.expires_ts = avail          # superseded by the newer completed period
            lv = self._mk(st, kind, px, ag["first"], avail, ag["key"],
                          {"period": ag["key"], "extreme_bar_start": at, "bars": ag["n"]})
            self.current[f"{st}:{kind}"] = lv
            new.append(lv)
        if name == "day":
            self.daily_closes.append((avail, ag["c"]))
        return new

    def step(self, bar: Bar, atr: float | None) -> list[PriceLevel]:
        new: list[PriceLevel] = []
        self._n += 1
        keys = self._period_keys(bar)
        # finalize aggregates whose key changed (or whose session closed)
        for name in list(self._agg):
            ag = self._agg[name]
            k = keys.get(name)
            closed = name.endswith("_session") and bar.start >= int(ag["close"])
            if (k is not None and k[0] != ag["key"]) or closed or (k is None and not name.endswith("_session") and False):
                new += self._finalize(name, ag)
                del self._agg[name]
        for name, (key, extra) in keys.items():
            ag = self._agg.get(name)
            if ag is None:
                ag = self._agg[name] = {"key": key, "first": bar.start, "h": bar.high, "l": bar.low, "h_at": bar.start,
                                        "l_at": bar.start, "n": 0, "close": extra if name.endswith("_session") else None}
            if bar.high > ag["h"]:
                ag["h"], ag["h_at"] = bar.high, bar.start
            if bar.low < ag["l"]:
                ag["l"], ag["l_at"] = bar.low, bar.start
            ag["n"] += 1
            ag["last_end"], ag["c"] = bar.end, bar.close
        # confirmed fractal swings
        self._win.append(bar)
        k = self.cfg.swing_k
        if len(self._win) == 2 * k + 1:
            w = list(self._win)
            m = w[k]
            for kind, val, left, right in (("high", m.high, [b.high for b in w[:k]], [b.high for b in w[k + 1:]]),
                                           ("low", -m.low, [-b.low for b in w[:k]], [-b.low for b in w[k + 1:]])):
                if val > max(left) and val >= max(right):
                    px = m.high if kind == "high" else m.low
                    lv = self._mk("swing", kind, px, m.start, bar.end, f"swing:{m.start}", {"bar_start": m.start, "k": k},
                                  expires=bar.end + self.cfg.swing_max_age)
                    new.append(lv)
                    tol = max(self.cfg.eq_ticks * self.tick, self.cfg.eq_atr * (atr or 0.0))
                    for n0, prev in reversed(self._swings):
                        if self._n - n0 > self.cfg.eq_max_gap:
                            break
                        if prev.kind == kind and abs(prev.price - px) <= tol and (prev.expires_ts or 0) > bar.end:
                            ex = max(prev.price, px) if kind == "high" else min(prev.price, px)
                            new.append(self._mk("equal", kind, ex, prev.created_ts, bar.end, f"equal:{prev.created_ts}:{m.start}",
                                                {"swings": [prev.id, lv.id], "tolerance": tol}, expires=bar.end + self.cfg.swing_max_age))
                            break
                    self._swings.append((self._n, lv))
            self._swings = self._swings[-200:]
        new += self._round_levels(bar)
        self._link_confluence(new, bar.end, atr)
        return new

    def _round_levels(self, bar: Bar) -> list[PriceLevel]:
        """Round-number levels at completed-bar close: the nearest step above and below (causal, deduped)."""
        st = self.cfg.round_step
        if not st:
            return []
        import math
        out = []
        for kind, px in (("high", math.ceil(bar.close / st) * st), ("low", math.floor(bar.close / st) * st)):
            key = f"round:{kind}"
            cur = self.current.get(key)
            if cur is not None and abs(cur.price - px) < 1e-9 and (cur.expires_ts or 0) > bar.end:
                continue
            if cur is not None:
                cur.expires_ts = bar.end
            lv = self._mk("round", kind, float(px), bar.start, bar.end, f"round:{px}", {"step": st},
                          expires=bar.end + self.cfg.round_max_age)
            self.current[key] = lv
            out.append(lv)
        return out

    def _link_confluence(self, new: list[PriceLevel], now: int, atr: float | None) -> None:
        if not new or not atr:
            return
        tol = self.cfg.confluence_atr * atr
        live = [l for l in self.levels if l.available_ts <= now and (l.expires_ts is None or l.expires_ts > now)]
        for lv in new:
            for o in live:
                if o.id != lv.id and abs(o.price - lv.price) <= tol:
                    if o.id not in lv.confluence_ids:
                        lv.confluence_ids.append(o.id)
                    if lv.id not in o.confluence_ids:
                        o.confluence_ids.append(lv.id)
