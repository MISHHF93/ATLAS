"""Prior-day range reversal detector (`prior_day_range_reversal`), single timeframe (designed for 15m bars).

Levels for a session are fixed at the session open from COMPLETED earlier sessions only:
- range_high / range_low = high / low of the prior completed session;
- swing_high = nearest earlier level above range_high, scanning back through older session highs
  (first older session whose high is above range_high); outer_high = next older high above swing_high.
  swing_low / outer_low mirror this below range_low.
- Opening-extreme variant: if the first completed bar of the session has a range > ``opening_extreme_frac`` x the
  prior session range, range_high / range_low are replaced by that bar's high / low (swing levels are re-scanned
  relative to them, prior-session high/low included).

Three-candle framework (shorts only at the upper levels, longs only at the lower levels):
- C1: first completed bar of the session that trades into a level zone (level +/- tolerance, tolerance =
  ``touch_ticks`` x tick + ``touch_atr`` x ATR). A bar touching both an upper and a lower zone is skipped.
- C2: within ``c2_window`` bars after C1, a confirmation bar. Long: closes green and its low holds at/above the C1
  low. Short: closes red and its high holds at/below the C1 high. A close through the level by more than the
  invalidation buffer invalidates the setup.
- C3: a stop-entry at C2 high (long) / C2 low (short). The detector emits the candidate at the close of C2 as a
  *stop order proposal* (``entry_type = "stop"``), because a live stop must rest before price crosses it. It then
  records C3_TRIGGERED when a later bar crosses the trigger, or EXPIRED after ``c3_window`` bars.
- Stop = beyond the more extreme of the level and the C1 extreme, plus ``stop_buffer_atr`` x ATR.
- Target = the opposite range level (``target = "opposite_range"``) or the swing level beyond it (``"swing"``).
Everything is causal: a bar is used only after it has closed, and levels never use the current session.
Candidates carry execution_permission="none"; only the deterministic control plane can act on them.
Default parameters are engineering choices, not optimised values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from atlas.features.price_action.bars import EPS, Bar, candle_geometry
from atlas.features.price_action.detectors import TERMINAL, Candidate, Transition
from atlas.features.price_action.sessions import SessionSpec
from atlas.features.price_action.zones import Zone

PDR_STATES = ("AWAITING_HISTORY", "WATCHING_LEVELS", "C1_AT_LEVEL", "C2_CONFIRMED", "AWAITING_TRIGGER",
              "C3_TRIGGERED", "INVALIDATED", "EXPIRED", "COMPLETED")


@dataclass
class PriorDayRangeConfig:
    tick: float = 0.01
    touch_ticks: float = 0.0
    touch_atr: float = 0.10
    invalidation_atr: float = 0.25        # close beyond the level by more than this x ATR invalidates
    stop_buffer_atr: float = 0.10
    entry_buffer_ticks: float = 1.0        # stop-entry trigger = C2 extreme +/- this many ticks
    c2_window: int = 3                     # bars after C1 in which C2 may appear
    c3_window: int = 3                     # bars after C2 in which the stop-entry may trigger
    use_outer_level: bool = True           # also trade the 2nd swing level
    lookback_sessions: int = 20
    opening_extreme_frac: float | None = 0.5
    target: Literal["opposite_range", "swing"] = "opposite_range"
    max_setups_per_session: int = 2


class PriorDayRangeReversalDetector:
    name = "prior_day_range_reversal"

    def __init__(self, instrument: str, timeframe: int, session: SessionSpec, cfg: PriorDayRangeConfig | None = None):
        self.instrument, self.timeframe, self.session = instrument, timeframe, session
        self.cfg = cfg or PriorDayRangeConfig()
        self.transitions: list[Transition] = []
        self.candidates: list[Candidate] = []
        self.zones: list[Zone] = []
        self.history: list[list[float]] = []      # completed sessions [high, low], oldest first
        self.s: dict[str, Any] = self._fresh(None, 0, 0)

    @staticmethod
    def _fresh(sid: str | None, o: int, c: int) -> dict[str, Any]:
        return {"session_id": sid, "open": o, "close": c, "hi": None, "lo": None, "bars": 0, "levels": None,
                "state": None, "setup_id": None, "seq": 0, "setup_n": 0, "setup": None}

    # ---- persistence ----
    def snapshot(self) -> dict[str, Any]:
        import copy
        return {"s": copy.deepcopy(self.s), "history": [list(h) for h in self.history]}

    def restore(self, snap: dict[str, Any]) -> None:
        import copy
        self.s, self.history = copy.deepcopy(snap["s"]), [list(h) for h in snap["history"]]

    def _go(self, to: str, at: int, reason: str, out: list[Any]) -> None:
        s = self.s
        self.transitions.append(Transition(s["setup_id"], s["seq"], s["state"], to, at, reason))
        s["seq"] += 1
        s["state"] = to
        out.append(self.transitions[-1])

    def _arm(self, at: int, reason: str, out: list[Any]) -> None:
        s = self.s
        s["setup_n"] += 1
        s["setup_id"] = f"{self.instrument}:{s['session_id']}:pdr{s['setup_n']}"
        s["seq"], s["state"], s["setup"] = 0, None, None
        self._go("WATCHING_LEVELS", at, reason, out)

    # ---- levels ----
    def _swings(self, hi: float, lo: float, extra_hi: list[float], extra_lo: list[float]) -> dict[str, float | None]:
        highs = extra_hi + [h for h, _ in reversed(self.history[:-1])][: self.cfg.lookback_sessions]
        lows = extra_lo + [l_ for _, l_ in reversed(self.history[:-1])][: self.cfg.lookback_sessions]
        sh = next((h for h in highs if h > hi), None)
        oh = next((h for h in highs if sh is not None and h > sh), None)
        sl = next((l_ for l_ in lows if l_ < lo), None)
        ol = next((l_ for l_ in lows if sl is not None and l_ < sl), None)
        return {"range_high": hi, "range_low": lo, "swing_high": sh, "swing_low": sl,
                "outer_high": oh if self.cfg.use_outer_level else None, "outer_low": ol if self.cfg.use_outer_level else None}

    def _set_levels(self, first: Bar | None) -> dict[str, Any] | None:
        if not self.history:
            return None
        ph, pl = self.history[-1]
        lv = self._swings(ph, pl, [], [])
        lv["source"], lv["prior_range"] = "prior_session", ph - pl
        if first is not None and self.cfg.opening_extreme_frac is not None and ph - pl > 0 \
                and first.high - first.low > self.cfg.opening_extreme_frac * (ph - pl):
            lv = self._swings(first.high, first.low, [ph], [pl])
            lv["source"], lv["prior_range"] = "opening_candle_extreme", ph - pl
        return lv

    # ---- stepping ----
    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        win = self.session.window_for(bar.start)
        s = self.s
        if win is None or win[0] != s["session_id"]:
            self._close_session(bar, out)
            if win is None:
                self.s = self._fresh(None, 0, 0)
                return out
            self.s = s = self._fresh(*win)
            s["setup_id"] = f"{self.instrument}:{s['session_id']}:levels"
            if not self.history:
                self._go("AWAITING_HISTORY", bar.start, "no_completed_prior_session", out)
            elif self.cfg.opening_extreme_frac is None:
                s["levels"] = self._set_levels(None)
                self._emit_level_zones(bar.start, ctx, out)
                self._arm(bar.start, "levels_from_prior_session", out)
        s["hi"] = bar.high if s["hi"] is None else max(s["hi"], bar.high)
        s["lo"] = bar.low if s["lo"] is None else min(s["lo"], bar.low)
        s["bars"] += 1
        if not self.history:
            return out
        if s["levels"] is None:                    # opening-extreme variant: levels fixed after the first bar closes
            s["levels"] = self._set_levels(bar)
            self._emit_level_zones(bar.end, ctx, out)
            self._arm(bar.end, f"levels_from_{s['levels']['source']}", out)
            if s["levels"]["source"] == "opening_candle_extreme":
                return out                         # the defining bar cannot also be C1
        if s["state"] in TERMINAL or s["state"] is None:
            return out
        self._advance(bar, ctx, out)
        return out

    def _close_session(self, bar: Bar, out: list[Any]) -> None:
        s = self.s
        if s["session_id"] is None:
            return
        if s["state"] is not None and s["state"] not in TERMINAL:
            self._go("EXPIRED", s["close"] or bar.start, "session_end", out)
        if s["hi"] is not None:
            self.history.append([s["hi"], s["lo"]])
            del self.history[: max(0, len(self.history) - self.cfg.lookback_sessions - 1)]

    def _emit_level_zones(self, at: int, ctx: dict[str, Any], out: list[Any]) -> None:
        lv = self.s["levels"]
        tol = self._tol(ctx)
        for k in ("range_high", "swing_high", "outer_high", "range_low", "swing_low", "outer_low"):
            v = lv.get(k)
            if v is None:
                continue
            z = Zone(self.instrument, self.timeframe, f"pdr_{k}", "bearish" if k.endswith("high") else "bullish",
                     v - tol, v + tol, at, confirmed_at=at, max_age_seconds=max(self.s["close"] - at, 1),
                     source_event=self.s["session_id"], feature_snapshot={"level": v, "source": lv["source"]})
            self.zones.append(z)
            out.append(z)

    def _tol(self, ctx: dict[str, Any]) -> float:
        return self.cfg.touch_ticks * self.cfg.tick + self.cfg.touch_atr * (ctx.get("atr") or 0.0)

    def _touched(self, bar: Bar, tol: float, keys: tuple[str, ...]) -> list[tuple[str, float]]:
        lv = self.s["levels"]
        return [(k, lv[k]) for k in keys if lv.get(k) is not None and bar.high >= lv[k] - tol and bar.low <= lv[k] + tol]

    def _advance(self, bar: Bar, ctx: dict[str, Any], out: list[Any]) -> None:
        s, cfg = self.s, self.cfg
        atr = ctx.get("atr") or 0.0
        tol = self._tol(ctx)
        st = s["state"]
        if st == "WATCHING_LEVELS":
            up = self._touched(bar, tol, ("range_high", "swing_high", "outer_high"))
            dn = self._touched(bar, tol, ("range_low", "swing_low", "outer_low"))
            if up and dn:
                return                                         # ambiguous bar spanning both sides: skip
            if up or dn:
                short = bool(up)
                k, lvl = max(up, key=lambda x: x[1]) if short else min(dn, key=lambda x: x[1])
                s["setup"] = {"dir": "short" if short else "long", "level_key": k, "level": lvl,
                              "c1": [bar.start, bar.open, bar.high, bar.low, bar.close], "c1_end": bar.end,
                              "c1_bar_index": s["bars"], "age": 0}
                self._go("C1_AT_LEVEL", bar.end, f"c1_touched_{k}", out)
            return
        su = s["setup"]
        long = su["dir"] == "long"
        if st == "C1_AT_LEVEL":
            su["age"] += 1
            c1o, c1h, c1l = su["c1"][1], su["c1"][2], su["c1"][3]
            if (long and bar.close < su["level"] - cfg.invalidation_atr * atr) or \
                    (not long and bar.close > su["level"] + cfg.invalidation_atr * atr):
                self._go("INVALIDATED", bar.end, "close_through_level", out)
                return self._rearm(bar, out)
            ok = (bar.close > bar.open and bar.low >= c1l) if long else (bar.close < bar.open and bar.high <= c1h)
            if ok:
                self._go("C2_CONFIRMED", bar.end, "confirmation_candle", out)
                c = self._candidate(bar, ctx)
                if c is None:
                    self._go("INVALIDATED", bar.end, "no_room_to_target", out)
                    return self._rearm(bar, out)
                out.append(c)
                su["trigger"], su["age"] = c.entry_reference, 0
                self._go("AWAITING_TRIGGER", bar.end, "stop_entry_proposed_for_control_plane", out)
                return
            if su["age"] >= cfg.c2_window:
                self._go("EXPIRED", bar.end, "c2_window_elapsed", out)
                return self._rearm(bar, out)
            return
        if st == "AWAITING_TRIGGER":
            su["age"] += 1
            if (long and bar.high >= su["trigger"]) or (not long and bar.low <= su["trigger"]):
                self._go("C3_TRIGGERED", bar.end, "price_crossed_c2_extreme", out)
                self._go("COMPLETED", bar.end, "setup_complete", out)
            elif su["age"] >= cfg.c3_window:
                self._go("EXPIRED", bar.end, "c3_window_elapsed", out)
                self._rearm(bar, out)

    def _rearm(self, bar: Bar, out: list[Any]) -> None:
        if self.s["setup_n"] < self.cfg.max_setups_per_session:
            self._arm(bar.end, "rearm", out)

    def _candidate(self, bar: Bar, ctx: dict[str, Any]) -> Candidate | None:
        s, cfg, su = self.s, self.cfg, self.s["setup"]
        lv, long = s["levels"], su["dir"] == "long"
        atr = ctx.get("atr")
        a = atr or 0.0
        c1h, c1l = su["c1"][2], su["c1"][3]
        if long:
            entry = bar.high + cfg.entry_buffer_ticks * cfg.tick
            stop = min(su["level"], c1l) - cfg.stop_buffer_atr * a
            opp, swing = lv["range_high"], lv.get("swing_high")
        else:
            entry = bar.low - cfg.entry_buffer_ticks * cfg.tick
            stop = max(su["level"], c1h) + cfg.stop_buffer_atr * a
            opp, swing = lv["range_low"], lv.get("swing_low")
        target = swing if cfg.target == "swing" and swing is not None else opp
        risk = (entry - stop) if long else (stop - entry)
        room = (target - entry) if long else (entry - target)
        if not (risk > 0 and room > 0):
            return None
        g = candle_geometry(bar)
        prior_rng = max(lv["prior_range"], EPS)
        feats = {
            "level_rank": {"range": 0, "swing": 1, "outer": 2}[su["level_key"].split("_")[0]],
            "level_source_opening_extreme": lv["source"] == "opening_candle_extreme",
            "reward_risk": room / risk,
            "risk_atr": risk / atr if atr else None,
            "prior_range_atr": prior_rng / atr if atr else None,
            "c1_range_atr": (c1h - c1l) / atr if atr else None,
            "c2_body_ratio": g["body_ratio"],
            "bars_c1_to_c2": su["age"],
            "c1_bar_index": su["c1_bar_index"],
            "minutes_since_open": (bar.end - s["open"]) / 60.0,
            "distance_to_target_atr": room / atr if atr else None,
            "second_target": swing if cfg.target == "opposite_range" else None,
            "session_identifier": s["session_id"],
        }
        zone = Zone(self.instrument, self.timeframe, f"pdr_{su['level_key']}", "bullish" if long else "bearish",
                    su["level"] - self._tol(ctx), su["level"] + self._tol(ctx), su["c1"][0], confirmed_at=bar.end,
                    source_event=s["setup_id"]).to_dict()
        c = Candidate(f"{s['setup_id']}:{bar.end}", self.name, self.instrument, "long" if long else "short", bar.end,
                      entry, su["level"], stop, target, zone, feats, entry_type="stop",
                      note="stop-entry proposal (C3 trigger); not a trade; control plane decides")
        self.candidates.append(c)
        return c
