"""LevelSuiteDetector: one detector that owns the liquidity-level registry + the shared LevelInteractionEngine and feeds
its classified events to the strategy consumers (SFP reversal, gold opening-box Snapback continuation, gold ORB
breakout). Every strategy is individually toggleable (``StrategyToggles``); all are OFF by default and gold rules only
run for gold futures roots (GC, MGC) — they never auto-apply to other assets.

SFP (swing failure pattern) on a level with side s (+1 = level above price):
  sweep = a bar trades beyond the level by >= 1 tick; reclaim = a close back on the original side within
  ``confirm_window`` bars (interaction outcome RECLAIMED, first episode only, i.e. not a retest after acceptance).
  Optional confirmation (``confirm``): none | next_bar (next close continues away) | displacement (a bar body >=
  disp_atr*ATR in trade direction within N bars) | structure (close beyond the reclaim bar's opposite extreme).
  Direction = -s. Stop = sweep extreme + s*(stop_atr*ATR + tick). Target = nearest opposing available level, else
  fixed ``target_r`` R. NO_TRADE(REWARD_BELOW_COST) if (|T-E| - cost)/(|E-S| + cost) < min_rr;
  NO_TRADE(COST_TOO_HIGH) if cost/|E-S| > max_cost_r (default 0.5).
  Several levels reclaimed on one bar in one direction -> one candidate on the highest-priority level, confluence = n.
Snapback (gold box): BOX_FORMING -> BOX_CONFIRMED -> BREAKOUT_OBSERVED -> AWAITING_RETEST (accepted) -> RETEST_OBSERVED
  -> SNAPBACK_CONFIRMED (retest held) -> COMPLETED; or INVALIDATED (retest failed / reclaimed back into box) / EXPIRED.
  The transcript does not fix the stop; alternatives: box_opposite | box_mid | two_box_heights | retest_extreme.
States of SFP map to the generic engine: REFERENCE_LEVEL_CONFIRMED=LEVEL_IDENTIFIED, LEVEL_APPROACHED=PRICE_APPROACHING,
LEVEL_SWEPT=BREAKOUT_OR_REJECTION_OBSERVED, AWAITING_RECLAIM=AWAITING_CONFIRMATION, RECLAIM_CONFIRMED=RECLAIMED,
BREAKOUT_ACCEPTED=ACCEPTED, RECLAIM_FAILED=UNRESOLVED, then AWAITING_OPTIONAL_DISPLACEMENT -> STRATEGY_CANDIDATE_GENERATED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.calendar import TradingCalendar
from atlas.features.price_action.detectors import Candidate, Transition
from atlas.features.price_action.htf import DailyBias, FourHour
from atlas.features.price_action.levels import (PRIORITY, priority_of, InteractionConfig, LevelEvent, LevelInteractionEngine,
                                                LiquidityLevelRegistry, PriceLevel, RegistryConfig)
from atlas.features.price_action.reentry import ReentryConfig, ReentryGovernor, load_reentry_config
from atlas.features.price_action.zones import Zone

NY = ZoneInfo("America/New_York")
GOLD_ROOTS = ("GC", "MGC")
SFP_STATE_MAP = {"LEVEL_IDENTIFIED": "REFERENCE_LEVEL_CONFIRMED", "PRICE_APPROACHING": "LEVEL_APPROACHED",
                 "BREAKOUT_OR_REJECTION_OBSERVED": "LEVEL_SWEPT", "AWAITING_CONFIRMATION": "AWAITING_RECLAIM",
                 "RECLAIMED": "RECLAIM_CONFIRMED", "ACCEPTED": "BREAKOUT_ACCEPTED", "UNRESOLVED": "RECLAIM_FAILED",
                 "EXPIRED": "EXPIRED", "REJECTED": "NO_TRADE", "LEVEL_TESTED": "LEVEL_APPROACHED"}
ORDERFLOW_FIELDS = ("delta_at_sweep", "absorption", "resting_liquidity", "book_imbalance")


def is_gold(instrument: str) -> bool:
    root = instrument.split("=")[0].split(":")[0].upper()
    return root in GOLD_ROOTS


@dataclass
class StrategyToggles:
    sfp: bool = False
    gold_snapback: bool = False
    gold_orb_breakout: bool = False


@dataclass
class SFPConfig:
    confirm: str = "none"              # none | next_bar | displacement | structure
    confirm_bars: int = 3
    disp_atr: float = 1.0
    stop_atr: float = 0.1
    target: str = "opposing"           # opposing | fixed_r
    target_r: float = 2.0
    min_rr: float = 1.0
    max_cost_r: float = 0.5            # NO_TRADE(COST_TOO_HIGH) if cost / |E-S| exceeds this
    sources: tuple[str, ...] = ("prev_day", "prev_week", "prev_month", "asia_session", "london_session", "ny_session",
                                "swing", "equal", "box")


@dataclass
class GoldBox:
    name: str                          # setup type, e.g. GOLD_OPENING_ORB
    start: time
    end: time
    trade_until: time = time(12, 0)    # NY time; box levels expire after this


@dataclass
class GoldConfig:
    boxes: tuple[GoldBox, ...] = (GoldBox("GOLD_OPENING_ORB", time(8, 20), time(8, 50)),)
    stop: str = "box_opposite"         # box_opposite | box_mid | two_box_heights | retest_extreme
    target_r: float = 2.0
    min_rr: float = 1.0
    max_cost_r: float = 0.5            # NO_TRADE(COST_TOO_HIGH) if cost / |E-S| exceeds this


@dataclass
class SuiteConfig:
    toggles: StrategyToggles = field(default_factory=StrategyToggles)
    tick: float = 0.01
    venue: str = ""
    calendar: str = "crypto"
    registry: RegistryConfig = field(default_factory=RegistryConfig)
    interaction: InteractionConfig = field(default_factory=InteractionConfig)
    sfp: SFPConfig = field(default_factory=SFPConfig)
    gold: GoldConfig = field(default_factory=GoldConfig)
    reentry: ReentryConfig = field(default_factory=load_reentry_config)   # code defaults + tighten-only overlay
    htf_filter: bool = False           # True -> candidates against a bullish/bearish daily bias become NO_TRADE(HTF_CONFLICT)
    cost_price: float = 0.0            # round-trip cost estimate in price units used for the net-RR gate
    daily: tuple = ()                  # (open_ts, high, low, close) completed provider daily bars for HTF bias


class LevelSuiteDetector:
    name = "level_suite"

    def __init__(self, instrument: str, timeframe: int, cfg: SuiteConfig):
        self.instrument, self.tf, self.cfg = instrument, timeframe, cfg
        cfg.interaction.tick = cfg.tick
        self.cal = TradingCalendar(cfg.calendar)
        self.registry = LiquidityLevelRegistry(instrument, cfg.venue, timeframe, self.cal, cfg.registry, cfg.tick)
        self.engine = LevelInteractionEngine(cfg.interaction)
        self.gov = ReentryGovernor(cfg.reentry)
        self.daily = DailyBias(cfg.daily) if cfg.daily else None
        self.h4 = FourHour()
        self.gold_on = is_gold(instrument) and (cfg.toggles.gold_snapback or cfg.toggles.gold_orb_breakout)
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []
        self.no_trades: list[dict[str, Any]] = []
        self.transitions: list[Transition] = []
        self.level_events: list[LevelEvent] = []
        self._pending: list[dict[str, Any]] = []          # SFP awaiting optional confirmation
        self._boxes: dict[str, dict[str, Any]] = {}        # box_key -> state
        self._snap: dict[str, dict[str, Any]] = {}         # box level id -> snapback state
        self._last_close: float | None = None
        self._seq = 0

    # ---------- helpers ----------
    def _tr(self, sid: str, frm: str | None, to: str, at: int, why: str) -> None:
        self._seq += 1
        self.transitions.append(Transition(sid, self._seq, frm, to, at, why))

    def htf(self, t: int) -> dict[str, Any]:
        if self.daily is None:
            return {"bias": "insufficient", "daily_bars": 0}
        return self.daily.at(t, self.h4.trend())

    def _day(self, ts: int) -> str:
        s = self.cal.session_of(ts)
        return s[0].isoformat() if s else datetime.fromtimestamp(ts, timezone.utc).date().isoformat()

    FAMILY_OF = {"sfp_reversal": "sfp", "gold_orb_breakout": "orb", "gold_snapback": "snapback"}

    def record_outcome(self, detector: str, ts: int, r: float | None) -> bool:
        """Paper outcome feedback (section 13): the governor's cumulative-loss caps count realized R per trading day."""
        fam = self.FAMILY_OF.get(detector)
        if fam is None:
            return False
        self.gov.record_outcome(fam, self._day(ts), r)
        return True

    def _no_trade(self, family: str, reason: str, at: int, **kw: Any) -> None:
        self.no_trades.append({"family": family, "reason": reason, "at": at, **kw})

    def _emit(self, family: str, detector: str, setup: str, direction: str, at: int, entry: float, stop: float,
              target: float, level: PriceLevel, event_id: str, feats: dict[str, Any], expl: dict[str, list[str]]) -> Candidate | None:
        risk, reward = abs(entry - stop), abs(target - entry)
        if risk <= 0:
            self._no_trade(family, "INSUFFICIENT_DATA", at, detail="zero risk")
            return None
        c = self.cfg.cost_price
        net_rr = (reward - c) / (risk + c)
        max_cost_r = self.cfg.sfp.max_cost_r if family == "sfp" else self.cfg.gold.max_cost_r
        if c / risk > max_cost_r:
            self._no_trade(family, "COST_TOO_HIGH", at, cost_r=c / risk, level=level.id)
            return None
        if net_rr < (self.cfg.sfp.min_rr if family == "sfp" else self.cfg.gold.min_rr):
            self._no_trade(family, "REWARD_BELOW_COST", at, net_rr=net_rr, level=level.id)
            return None
        h = self.htf(at)
        if self.cfg.htf_filter and ((direction == "long" and h["bias"] == "bearish") or (direction == "short" and h["bias"] == "bullish")):
            self._no_trade(family, "HTF_CONFLICT", at, bias=h["bias"], level=level.id)
            return None
        day = self._day(at - 1)
        ok, why = self.gov.allow(family, level.id, day, at)
        if not ok:
            self._no_trade(family, "REENTRY_LIMIT", at, detail=why, level=level.id)
            return None
        self.gov.record(family, level.id, day, at)
        hb = {"bullish": 1, "bearish": -1}.get(h["bias"], 0)
        f = {"setup_type": setup, "event_id": event_id, "reward_risk": reward / risk, "net_reward_risk": net_rr,
             "risk_price": risk, "cost_price": c, "cost_r": c / risk, "htf_bias": h["bias"],
             "htf_aligned": float(hb == (1 if direction == "long" else -1)), "htf_against": float(hb == (-1 if direction == "long" else 1)),
             "level_source": level.source_type, "level_priority": priority_of(level.source_type),
             "level_age_h": level.age(at) / 3600.0, "level_touches": level.touch_count,
             "reference_levels": [level.to_dict()], "explanation": expl,
             "invalidation_rule": "stop touch (gap-through exits at open); stop-first on ambiguous bars",
             "required_data": ["confirmed OHLCV bars", f"calendar {self.cfg.calendar}"] + (["provider daily bars"] if self.daily else []),
             **{k: "missing" for k in ORDERFLOW_FIELDS}, **feats}
        cand = Candidate(f"{detector}:{self.instrument}:{level.id}:{at}", detector, self.instrument, direction, at,
                         entry, stop, stop, target, {"level_id": level.id, "price": level.price, "source": level.source_type}, f)
        self.candidates.append(cand)
        return cand

    # ---------- gold boxes ----------
    def _gold_boxes(self, bar: Bar, atr: float) -> None:
        loc = datetime.fromtimestamp(bar.start, timezone.utc).astimezone(NY)
        d = loc.date()
        for gb in self.cfg.gold.boxes:
            key = f"{gb.name}:{d.isoformat()}"
            b0 = int(datetime.combine(d, gb.start, NY).timestamp())
            b1 = int(datetime.combine(d, gb.end, NY).timestamp())
            st = self._boxes.get(key)
            if st is None and b0 <= bar.start < b1 and self.cal.session_of(bar.start) is not None:
                aligned = (b0 % self.tf == 0) and (b1 % self.tf == 0) and bar.duration <= b1 - b0
                st = self._boxes[key] = {"h": bar.high, "l": bar.low, "n": 0, "b0": b0, "b1": b1, "ok": aligned, "done": False}
                self._tr(key, None, "BOX_FORMING", bar.end, "first bar in box window")
                if not aligned:
                    st["done"] = True
                    self._no_trade("gold", "INSUFFICIENT_DATA", bar.end, detail=f"{gb.name} {gb.start}-{gb.end} NY not buildable from {self.tf}s bars")
                    self._tr(key, "BOX_FORMING", "INSUFFICIENT_DATA", bar.end, "timeframe does not align with box")
                    continue
            if st is None or st["done"]:
                continue
            if bar.start < b1:
                st["h"], st["l"] = max(st["h"], bar.high), min(st["l"], bar.low)
                st["n"] += 1
            if bar.end >= b1:
                st["done"] = True
                need = (b1 - b0) // self.tf
                if st["n"] != need:
                    self._no_trade("gold", "INSUFFICIENT_DATA", bar.end, detail=f"{key}: {st['n']}/{need} bars")
                    self._tr(key, "BOX_FORMING", "INSUFFICIENT_DATA", bar.end, "missing bars in box")
                    continue
                exp = int(datetime.combine(d, gb.trade_until, NY).timestamp())
                z = Zone(self.instrument, self.tf, f"gold_box:{gb.name}", "neutral", st["l"], st["h"], b0, confirmed_at=b1,
                         max_age_seconds=exp - b0, feature_snapshot={"box": gb.name, "start_ny": str(gb.start), "end_ny": str(gb.end)})
                self.zones.append(z)
                self._tr(key, "BOX_FORMING", "BOX_CONFIRMED", bar.end, f"{need} bars complete")
                for kind, px in (("high", st["h"]), ("low", st["l"])):
                    lv = self.registry.add_level("box", kind, px, b0, b1, key, {"box": gb.name, "height": st["h"] - st["l"]}, expires=exp)
                    self.engine.watch(lv, bar.close)
                    self._snap[lv.id] = {"state": "BOX_CONFIRMED", "box": st, "name": gb.name, "key": key, "level": lv}

    def _gold_event(self, ev: LevelEvent, bar: Bar, atr: float) -> None:
        sn = self._snap.get(ev.level_id)
        if sn is None or sn["state"] in ("COMPLETED", "INVALIDATED", "EXPIRED"):
            return
        lv, box = sn["level"], sn["box"]
        hgt = box["h"] - box["l"]
        key = f"{sn['key']}:{lv.kind}"

        def go(to: str, why: str) -> None:
            self._tr(key, sn["state"], to, bar.end, why)
            sn["state"] = to
        if ev.kind == "expiration":
            go("EXPIRED", "trade window over")
            return
        if not ev.post_accept:
            if ev.kind == "breakout_attempt" and sn["state"] == "BOX_CONFIRMED":
                go("BREAKOUT_OBSERVED", "traded beyond box")
            elif ev.kind == "reclaim" and sn["state"] == "BREAKOUT_OBSERVED":
                go("BOX_CONFIRMED", "closed back inside box (SFP domain)")
            elif ev.kind == "breakout_acceptance":
                go("AWAITING_RETEST", "accepted outside box")
                sn["event_id"] = ev.event_id
                sn["dir"] = "long" if lv.kind == "high" else "short"
                if self.cfg.toggles.gold_orb_breakout:
                    long = sn["dir"] == "long"
                    stop = box["l"] if long else box["h"]
                    e = bar.close
                    tgt = e + (1 if long else -1) * self.cfg.gold.target_r * abs(e - stop)
                    self._emit("orb", "gold_orb_breakout", "OPENING_BOX_BREAKOUT", sn["dir"], bar.end, e, stop, tgt, lv,
                               ev.event_id, {"box_height": hgt, "box_height_atr": hgt / atr if atr else 0.0, "variant": sn["name"]},
                               {"OBSERVED": [f"{sn['name']} box {box['l']:.2f}-{box['h']:.2f}", f"{self.cfg.interaction.accept_bars} closes beyond {lv.price:.2f}"],
                                "INFERRED": ["acceptance outside the opening box"], "UNVERIFIED": ["order flow behind the breakout (no data)"]})
            return
        # post-accept: retest of the broken boundary
        if ev.kind == "touch" and sn["state"] == "AWAITING_RETEST":
            go("RETEST_OBSERVED", "retest touch")
        elif ev.kind == "retest_success" and sn["state"] in ("AWAITING_RETEST", "RETEST_OBSERVED"):
            go("SNAPBACK_CONFIRMED", "retest held")
            if self.cfg.toggles.gold_snapback:
                long = sn["dir"] == "long"
                e = bar.close
                m = self.cfg.gold.stop
                sgn = 1 if long else -1
                stop = {"box_opposite": box["l"] if long else box["h"], "box_mid": (box["h"] + box["l"]) / 2,
                        "two_box_heights": e - sgn * 2 * hgt,
                        "retest_extreme": (bar.low if long else bar.high) - sgn * self.cfg.tick}[m]
                tgt = e + sgn * self.cfg.gold.target_r * abs(e - stop)
                setup = "SNAPBACK_CONTINUATION_LONG" if long else "SNAPBACK_CONTINUATION_SHORT"
                self._emit("snapback", "gold_snapback", setup, sn["dir"], bar.end, e, stop, tgt, lv, sn.get("event_id", ev.event_id),
                           {"box_height": hgt, "box_height_atr": hgt / atr if atr else 0.0, "stop_mode": m, "variant": sn["name"]},
                           {"OBSERVED": [f"{sn['name']} box {box['l']:.2f}-{box['h']:.2f}", "accepted outside, retested, held"],
                            "INFERRED": ["broken boundary acting as support/resistance"],
                            "UNVERIFIED": ["stop rule (transcript ambiguous; mode=" + m + ")", "order flow (no data)"]})
            go("COMPLETED", "candidate evaluated")
        elif ev.kind in ("retest_failure", "breakout_failure"):
            go("INVALIDATED", "retest failed")

    # ---------- SFP ----------
    def _sfp_reclaims(self, evs: list[LevelEvent], bar: Bar, atr: float) -> None:
        by_dir: dict[int, list[LevelEvent]] = {}
        for ev in evs:
            if ev.kind != "reclaim" or ev.post_accept:
                continue
            lv = self._level(ev.level_id)
            if lv is None or lv.source_type not in self.cfg.sfp.sources:
                continue
            by_dir.setdefault(ev.side, []).append(ev)
        for s, group in by_dir.items():
            group.sort(key=lambda e: (-priority_of(self._level(e.level_id).source_type), e.level_id))
            ev = group[0]
            p = {"ev": ev, "level": self._level(ev.level_id), "s": s, "bars": 0, "confluence": len(group),
                 "reclaim_bar": bar, "others": [g.level_id for g in group[1:]]}
            self._tr(ev.event_id, "LEVEL_SWEPT", "RECLAIM_CONFIRMED", bar.end, f"closed back; confluence={len(group)}")
            if self.cfg.sfp.confirm == "none":
                self._sfp_emit(p, bar, atr)
            else:
                self._tr(ev.event_id, "RECLAIM_CONFIRMED", "AWAITING_OPTIONAL_DISPLACEMENT", bar.end, self.cfg.sfp.confirm)
                self._pending.append(p)

    def _sfp_pending(self, bar: Bar, atr: float) -> None:
        keep = []
        for p in self._pending:
            p["bars"] += 1
            s, ev, rb = p["s"], p["ev"], p["reclaim_bar"]
            if s * bar.high > s * ev.extreme:                           # traded beyond sweep extreme -> failed
                self._tr(ev.event_id, "AWAITING_OPTIONAL_DISPLACEMENT", "RECLAIM_FAILED", bar.end, "new extreme beyond sweep")
                self._no_trade("sfp", "UNRESOLVED_INTERACTION", bar.end, event_id=ev.event_id)
                continue
            m = self.cfg.sfp.confirm
            ok = ((m == "next_bar" and -s * bar.close > -s * rb.close)
                  or (m == "displacement" and -s * (bar.close - bar.open) >= self.cfg.sfp.disp_atr * atr > 0)
                  or (m == "structure" and -s * bar.close > -s * (rb.low if s > 0 else rb.high)))
            if ok:
                self._sfp_emit(p, bar, atr)
            elif p["bars"] >= self.cfg.sfp.confirm_bars:
                self._tr(ev.event_id, "AWAITING_OPTIONAL_DISPLACEMENT", "EXPIRED", bar.end, "no confirmation")
                self._no_trade("sfp", "UNRESOLVED_INTERACTION", bar.end, event_id=ev.event_id, detail="confirmation expired")
            else:
                keep.append(p)
        self._pending = keep

    def _level(self, lid: str) -> PriceLevel | None:
        tr = self.engine.trackers.get(lid)
        return tr.lvl if tr else self._lv_cache.get(lid)

    def _sfp_emit(self, p: dict[str, Any], bar: Bar, atr: float) -> None:
        ev, lv, s = p["ev"], p["level"], p["s"]
        direction = "short" if s > 0 else "long"
        e = bar.close
        stop = ev.extreme + s * (self.cfg.sfp.stop_atr * atr + self.cfg.tick)
        tgt = None
        if self.cfg.sfp.target == "opposing":
            opp = [t.lvl.price for t in self.engine.trackers.values()
                   if t.lvl.available_ts <= bar.end and (-s) * (t.lvl.price - e) > 0 and t.lvl.kind != lv.kind]
            if opp:
                tgt = min(opp, key=lambda x: abs(x - e))
        if tgt is None:
            tgt = e - s * self.cfg.sfp.target_r * abs(e - stop)
        sweep_depth = abs(ev.extreme - lv.price)
        rb = p["reclaim_bar"]
        rng = max(rb.high - rb.low, 1e-12)
        wick = (rb.high - max(rb.open, rb.close)) if s > 0 else (min(rb.open, rb.close) - rb.low)
        feats = {"sweep_depth_atr": sweep_depth / atr if atr else 0.0, "sweep_bars": ev.bars, "wick_frac": wick / rng,
                 "reclaim_close_dist_atr": abs(rb.close - lv.price) / atr if atr else 0.0, "confluence": p["confluence"],
                 "confirm_mode": self.cfg.sfp.confirm, "confirm_bars": p["bars"], "target_mode": self.cfg.sfp.target}
        setup = "SFP_REVERSAL_SHORT" if direction == "short" else "SFP_REVERSAL_LONG"
        expl = {"OBSERVED": [f"{lv.source_type} {lv.kind} {lv.price:.4f} swept to {ev.extreme:.4f}",
                             f"close {rb.close:.4f} back on the original side after {ev.bars} bar(s)"] + [f"also swept: {o}" for o in p["others"]],
                "INFERRED": ["failed auction beyond a potential liquidity reference level"],
                "UNVERIFIED": ["resting liquidity / stop orders at the level (no order-book data)", "order-flow absorption (missing)"]}
        c = self._emit("sfp", "sfp_reversal", setup, direction, bar.end, e, stop, tgt, lv, ev.event_id, feats, expl)
        if c is not None:
            self._tr(ev.event_id, "AWAITING_OPTIONAL_DISPLACEMENT" if p["bars"] else "RECLAIM_CONFIRMED",
                     "STRATEGY_CANDIDATE_GENERATED", bar.end, c.candidate_id)

    # ---------- main ----------
    _lv_cache: dict[str, PriceLevel]

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        if not hasattr(self, "_lv_cache"):
            self._lv_cache = {}
        atr = float(ctx.get("atr") or 0.0)
        n0 = len(self.candidates)
        self.h4.update(bar.start, bar.close)
        if self.cfg.toggles.sfp and self._pending:
            self._sfp_pending(bar, atr)
        if self.gold_on:
            self._gold_boxes(bar, atr)
        evs = self.engine.step(bar, atr)
        self.level_events += evs
        for lid in {e.level_id for e in evs}:
            if lid not in self.engine.trackers:
                pass
        if self.gold_on:
            for ev in evs:
                self._gold_event(ev, bar, atr)
        if self.cfg.toggles.sfp:
            self._sfp_reclaims(evs, bar, atr)
        for lv in self.registry.step(bar, atr):
            if self.cfg.toggles.sfp and lv.source_type in self.cfg.sfp.sources:
                self.engine.watch(lv, bar.close)
            self._lv_cache[lv.id] = lv
        # keep a bounded cache of levels referenced by events after their tracker is gone
        for t in self.engine.trackers.values():
            self._lv_cache.setdefault(t.lvl.id, t.lvl)
        self._last_close = bar.close
        return self.candidates[n0:]
