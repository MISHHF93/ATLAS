"""Causal price-action detectors: opening range + breakout-retest-continuation state machine,
dual Bollinger breakout zones, wick reversal zones.

Every detector consumes one *confirmed* bar at a time via `step(bar, ctx)` where ctx is the
indicator context for that bar (atr, bands) computed only from bars <= this bar. A detector never
revisits earlier bars, so no signal can be created retroactively. Candidates carry
execution_permission="none"; they are proposals for the deterministic control plane only.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from atlas.features.price_action.bars import EPS, Bar, candle_geometry
from atlas.features.price_action.sessions import SessionSpec
from atlas.features.price_action.zones import Zone

STATES = ("RANGE_FORMING", "RANGE_CONFIRMED", "AWAITING_BREAKOUT", "BREAKOUT_CONFIRMED", "AWAITING_RETEST",
          "RETEST_OBSERVED", "CONTINUATION_CONFIRMED", "CANDIDATE_EVALUATED", "INVALIDATED", "EXPIRED", "COMPLETED")
TERMINAL = {"INVALIDATED", "EXPIRED", "COMPLETED"}


@dataclass(frozen=True)
class Transition:
    setup_id: str
    seq: int
    from_state: str | None
    to_state: str
    at: int
    reason: str


@dataclass
class Candidate:
    candidate_id: str
    detector: str
    instrument: str
    direction: Literal["long", "short"]
    detected_at: int
    entry_reference: float
    invalidation_level: float
    proposed_stop: float
    proposed_target: float
    zone: dict[str, Any]
    features: dict[str, Any]
    execution_permission: str = "none"
    entry_type: str = "limit"        # "limit" (rest at entry_reference) or "stop" (trigger when price crosses it)
    probability: None = None  # no calibrated model is attached in this slice
    note: str = "deterministic setup candidate; not a trade; control plane decides"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ORBRetestConfig:
    range_seconds: int = 3600
    breakout_buffer: float = 0.0          # absolute price units
    breakout_buffer_atr: float = 0.0      # extra buffer as multiple of ATR
    touch_tolerance: float = 0.0
    confirmation_buffer: float = 0.0
    require_touch_on_confirmation_bar: bool = True   # literal spec rule
    max_bars_after_breakout: int | None = None
    max_setups_per_session: int = 2
    reward_risk: float = 2.0              # engineering assumption for proposed target


class ORBRetestDetector:
    """Session opening range (first completed range_seconds window, wicks included) and
    breakout -> retest -> continuation setup state machine."""
    name = "orb_retest"

    def __init__(self, instrument: str, timeframe: int, session: SessionSpec, cfg: ORBRetestConfig | None = None):
        self.instrument, self.timeframe, self.session = instrument, timeframe, session
        self.cfg = cfg or ORBRetestConfig()
        self.transitions: list[Transition] = []
        self.candidates: list[Candidate] = []
        self.zones: list[Zone] = []
        self._reset(None, 0, 0)

    # ---- persisted state ----
    def _reset(self, sid: str | None, o: int, c: int) -> None:
        self.s: dict[str, Any] = {"session_id": sid, "open": o, "close": c, "state": None, "setup_n": 0,
                                  "setup_id": None, "seq": 0, "oh": None, "ol": None, "covered": 0,
                                  "range_vol": 0.0, "range_bars": 0, "dir": None, "bo": None, "bars_since_bo": 0,
                                  "retest": None, "extreme": None, "failed": 0}

    def snapshot(self) -> dict[str, Any]:
        return {"s": dict(self.s), "n_transitions": len(self.transitions)}

    def restore(self, snap: dict[str, Any]) -> None:
        self.s = dict(snap["s"])

    def _go(self, to: str, at: int, reason: str) -> None:
        s = self.s
        tr = Transition(s["setup_id"], s["seq"], s["state"], to, at, reason)
        s["seq"] += 1
        s["state"] = to
        self.transitions.append(tr)

    def _new_setup(self, at: int, reason: str) -> None:
        s = self.s
        s["setup_n"] += 1
        s["setup_id"] = f"{self.instrument}:{s['session_id']}:{s['setup_n']}"
        s["seq"], s["state"], s["dir"], s["bo"], s["retest"], s["extreme"], s["bars_since_bo"] = 0, None, None, None, None, None, 0
        self._go("AWAITING_BREAKOUT", at, reason)

    def _buf(self, ctx: dict[str, Any]) -> float:
        return self.cfg.breakout_buffer + self.cfg.breakout_buffer_atr * (ctx.get("atr") or 0.0)

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        win = self.session.window_for(bar.start)
        s = self.s
        if win is None or win[0] != s["session_id"]:
            if s["state"] is not None and s["state"] not in TERMINAL:
                self._go("EXPIRED", s["close"] or bar.start, "session_end")
                out.append(self.transitions[-1])
            if win is None:
                self._reset(None, 0, 0)
                return out
            self._reset(*win)
            s = self.s
            s["setup_id"] = f"{self.instrument}:{s['session_id']}:range"
            self._go("RANGE_FORMING", bar.start, "session_open")
            out.append(self.transitions[-1])
        if s["state"] in TERMINAL and s["setup_id"].endswith(":range"):
            return out
        range_end = s["open"] + self.cfg.range_seconds
        if s["state"] == "RANGE_FORMING":
            if bar.start < s["open"] or bar.end > range_end:
                self._go("INVALIDATED", bar.end, "bar_misaligned_with_range_window")
                return out + [self.transitions[-1]]
            s["oh"] = bar.high if s["oh"] is None else max(s["oh"], bar.high)
            s["ol"] = bar.low if s["ol"] is None else min(s["ol"], bar.low)
            s["covered"] += bar.duration
            s["range_vol"] += bar.volume
            s["range_bars"] += 1
            if bar.end == range_end:
                if s["covered"] != self.cfg.range_seconds:
                    self._go("INVALIDATED", bar.end, "missing_bars_in_range_window")
                    return out + [self.transitions[-1]]
                self._go("RANGE_CONFIRMED", bar.end, "first_completed_range_window")
                out.append(self.transitions[-1])
                z = Zone(self.instrument, self.timeframe, "opening_range", "neutral", s["ol"], s["oh"], s["open"],
                         confirmed_at=bar.end, max_age_seconds=s["close"] - bar.end, source_event=s["session_id"],
                         feature_snapshot={"opening_range_height": s["oh"] - s["ol"], "atr": ctx.get("atr")})
                self.zones.append(z)
                out.append(z)
                self._new_setup(bar.end, "range_confirmed")
                out.append(self.transitions[-1])
            return out
        oh, ol, rng = s["oh"], s["ol"], max(s["oh"] - s["ol"], EPS)
        atr = ctx.get("atr")
        buf = self._buf(ctx)
        st = s["state"]
        if st == "AWAITING_BREAKOUT":
            d = "long" if bar.close > oh + buf else "short" if bar.close < ol - buf else None
            if d:
                g = candle_geometry(bar)
                s["dir"] = d
                strength = (bar.close - oh) / rng if d == "long" else (ol - bar.close) / rng
                s["bo"] = {"at": bar.end, "close": bar.close, "vol": bar.volume, "strength": strength,
                           "strength_atr": (bar.close - oh if d == "long" else ol - bar.close) / max(atr, EPS) if atr else None,
                           "body_ratio": g["body_ratio"]}
                s["extreme"] = bar.low if d == "long" else bar.high
                self._go("BREAKOUT_CONFIRMED", bar.end, f"close_beyond_range_{d}")
                self._go("AWAITING_RETEST", bar.end, "await_retest")
                out += self.transitions[-2:]
            return out
        if st in ("AWAITING_RETEST", "RETEST_OBSERVED"):
            long = s["dir"] == "long"
            s["bars_since_bo"] += 1
            s["extreme"] = min(s["extreme"], bar.low) if long else max(s["extreme"], bar.high)
            if (long and bar.close < ol - buf) or (not long and bar.close > oh + buf):
                s["failed"] += 1
                self._go("INVALIDATED", bar.end, "close_through_opposite_range_bound")
                out.append(self.transitions[-1])
                if s["setup_n"] < self.cfg.max_setups_per_session:
                    self._new_setup(bar.end, "rearm_after_failure")
                    out.append(self.transitions[-1])
                return out
            touched = (bar.low <= oh + self.cfg.touch_tolerance) if long else (bar.high >= ol - self.cfg.touch_tolerance)
            if touched and st == "AWAITING_RETEST":
                s["retest"] = {"at": bar.end, "bar_start": bar.start, "vol": bar.volume}
                self._go("RETEST_OBSERVED", bar.end, "price_returned_to_range")
                out.append(self.transitions[-1])
                st = "RETEST_OBSERVED"
            if st == "RETEST_OBSERVED":
                confirm = (bar.close > oh + self.cfg.confirmation_buffer) if long else (bar.close < ol - self.cfg.confirmation_buffer)
                if self.cfg.require_touch_on_confirmation_bar:
                    confirm = confirm and touched
                if confirm:
                    self._go("CONTINUATION_CONFIRMED", bar.end, "confirmation_close_beyond_range")
                    out.append(self.transitions[-1])
                    out.append(self._candidate(bar, ctx))
                    self._go("CANDIDATE_EVALUATED", bar.end, "candidate_emitted_for_control_plane")
                    self._go("COMPLETED", bar.end, "setup_complete")
                    out += self.transitions[-2:]
                    return out
            mb = self.cfg.max_bars_after_breakout
            if mb is not None and s["bars_since_bo"] >= mb:
                self._go("EXPIRED", bar.end, "max_bars_after_breakout")
                out.append(self.transitions[-1])
        return out

    def _candidate(self, bar: Bar, ctx: dict[str, Any]) -> Candidate:
        s, long = self.s, self.s["dir"] == "long"
        oh, ol = s["oh"], s["ol"]
        rng = max(oh - ol, EPS)
        atr = ctx.get("atr")
        entry = bar.close
        stop = s["extreme"] - self.cfg.touch_tolerance if long else s["extreme"] + self.cfg.touch_tolerance
        risk = abs(entry - stop)
        target = entry + self.cfg.reward_risk * risk if long else entry - self.cfg.reward_risk * risk
        bo, rt = s["bo"], s["retest"]
        opposing = ol if long else oh
        feats = {
            "opening_range_height": oh - ol,
            "opening_range_atr_ratio": (oh - ol) / max(atr, EPS) if atr else None,
            "breakout_strength": bo["strength"], "breakout_strength_atr": bo["strength_atr"],
            "breakout_candle_body_ratio": bo["body_ratio"],
            "retest_depth": ((oh - s["extreme"]) if long else (s["extreme"] - ol)) / rng,
            "time_to_retest": rt["at"] - bo["at"],
            "confirmation_strength": ((bar.close - oh) if long else (ol - bar.close)) / rng,
            "retest_volume_ratio": rt["vol"] / bo["vol"] if bo["vol"] > 0 else None,
            "first_retest_flag": True,
            "prior_failed_breakouts": s["failed"],
            "session_identifier": s["session_id"],
            "market_regime": None,  # not wired in this slice
            "distance_to_opposing_zone_atr": abs(entry - opposing) / max(atr, EPS) if atr else None,
        }
        zone = Zone(self.instrument, self.timeframe, "opening_range", "bullish" if long else "bearish", ol, oh,
                    s["open"], confirmed_at=s["open"] + self.cfg.range_seconds, source_event=s["setup_id"]).to_dict()
        c = Candidate(f"{s['setup_id']}:{bar.end}", self.name, self.instrument, "long" if long else "short", bar.end,
                      entry, opposing, stop, target, zone, feats)
        self.candidates.append(c)
        return c


@dataclass
class DualBandConfig:
    variant: Literal["close_beyond", "range_pierce", "close_beyond_and_pierce"] = "close_beyond"
    threshold: Literal["current", "prior"] = "current"
    zone_max_age_seconds: int | None = None


class DualBollingerDetector:
    """Band A (close, 20, 2) and Band B (open, 4, 4); population std. Emits a breakout Zone
    from the qualifying candle's high-low range."""
    name = "dual_bollinger"

    def __init__(self, instrument: str, timeframe: int, cfg: DualBandConfig | None = None):
        self.instrument, self.timeframe, self.cfg = instrument, timeframe, cfg or DualBandConfig()
        self.zones: list[Zone] = []

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        for z in self.zones:
            for e in z.update(bar):
                out.append(("zone_event", z.zone_id, e, bar.end))
        key = "prev_" if self.cfg.threshold == "prior" else ""
        a, b = ctx.get(key + "band_a"), ctx.get(key + "band_b")
        if a is None or b is None:
            return out
        up_a, up_b, lo_a, lo_b = a[2], b[2], a[0], b[0]
        v = self.cfg.variant
        close_up = bar.close > up_a and bar.close > up_b
        close_dn = bar.close < lo_a and bar.close < lo_b
        pierce_up = all(bar.low < u < bar.high for u in (up_a, up_b))
        pierce_dn = all(bar.low < l_ < bar.high for l_ in (lo_a, lo_b))
        bull = close_up if v == "close_beyond" else pierce_up if v == "range_pierce" else (close_up and pierce_up)
        bear = close_dn if v == "close_beyond" else pierce_dn if v == "range_pierce" else (close_dn and pierce_dn)
        if bull or bear:
            atr = ctx.get("atr")
            ref = max(up_a, up_b) if bull else min(lo_a, lo_b)
            z = Zone(self.instrument, self.timeframe, "dual_band_breakout", "bullish" if bull else "bearish",
                     bar.low, bar.high, bar.start, confirmed_at=bar.end, max_age_seconds=self.cfg.zone_max_age_seconds,
                     source_event=f"{v}/{self.cfg.threshold}",
                     feature_snapshot={"band_a": a, "band_b": b, "atr": atr,
                                       "breakout_strength_atr": abs(bar.close - ref) / max(atr, EPS) if atr else None,
                                       "band_a_width": a[2] - a[0], "band_b_width": b[2] - b[0]})
            self.zones.append(z)
            out.append(z)
        return out


@dataclass
class WickConfig:
    lookback: int = 10
    min_wick_ratio: float = 0.5          # wick / range
    min_wick_body: float = 1.5           # wick / max(body, EPS)
    confirm_bars: int = 1
    confirmation: Literal["close_beyond_candidate_close", "close_beyond_candidate_extreme_body"] = "close_beyond_candidate_close"
    zone_max_age_seconds: int | None = None


class WickReversalDetector:
    """Swing extreme (Low[t] < min prior `lookback` lows) with a long rejection wick, confirmed by a
    later completed candle. Zone = [candidate low, candidate body low] (bullish) / mirror (bearish)."""
    name = "wick_reversal"

    def __init__(self, instrument: str, timeframe: int, cfg: WickConfig | None = None):
        self.instrument, self.timeframe, self.cfg = instrument, timeframe, cfg or WickConfig()
        self.hist: deque[Bar] = deque(maxlen=self.cfg.lookback)
        self.pending: list[dict[str, Any]] = []
        self.zones: list[Zone] = []

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        for z in self.zones:
            for e in z.update(bar):
                out.append(("zone_event", z.zone_id, e, bar.end))
        keep = []
        for p in self.pending:
            c: Bar = p["bar"]
            p["age"] += 1
            if p["dir"] == "bullish":
                ok = bar.close > (c.close if self.cfg.confirmation == "close_beyond_candidate_close" else max(c.open, c.close))
                lo, hi = c.low, min(c.open, c.close)
            else:
                ok = bar.close < (c.close if self.cfg.confirmation == "close_beyond_candidate_close" else min(c.open, c.close))
                lo, hi = max(c.open, c.close), c.high
            if ok:
                z = Zone(self.instrument, self.timeframe, "wick_reversal", p["dir"], lo, hi, c.start,
                         confirmed_at=bar.end, max_age_seconds=self.cfg.zone_max_age_seconds,
                         source_event=f"swing@{c.start}", feature_snapshot={**p["geom"], "atr": ctx.get("atr"),
                                                                            "bars_to_confirm": p["age"]})
                self.zones.append(z)
                out.append(z)
            elif p["age"] < self.cfg.confirm_bars:
                keep.append(p)
        self.pending = keep
        if len(self.hist) == self.cfg.lookback:
            g = candle_geometry(bar)
            body = max(g["body"], EPS)
            if bar.low < min(b.low for b in self.hist) and g["lower_wick_ratio"] >= self.cfg.min_wick_ratio \
                    and g["lower_wick"] / body >= self.cfg.min_wick_body:
                self.pending.append({"bar": bar, "dir": "bullish", "age": 0, "geom": g})
            elif bar.high > max(b.high for b in self.hist) and g["upper_wick_ratio"] >= self.cfg.min_wick_ratio \
                    and g["upper_wick"] / body >= self.cfg.min_wick_body:
                self.pending.append({"bar": bar, "dir": "bearish", "age": 0, "geom": g})
        self.hist.append(bar)
        return out
