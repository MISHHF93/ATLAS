"""Deterministic bar replay that uses the *live* path (``PriceActionEngine.update``), bar by bar.

The paper fill model is deliberately conservative, because OHLC bars cannot show the order of events inside a bar:
- Entry is a limit at ``entry_reference``, active from the bar *after* detection for ``entry_window`` bars.
  It fills at the limit price (no price improvement is assumed when a bar opens through it).
- On the fill bar, a stop touch counts as a stop-out and a target touch is ignored.
- Afterwards, an open beyond the stop exits at the open (the gap is taken in full). An open beyond the target exits
  at the target (no gap gain). A bar that touches both stop and target is counted as a stop (``ambiguous`` += 1).
- Optional realism (``PAPER_REALISM``): order latency in bars, trade-through limit fills, volume-capped partial fills.
- Resolved outcomes are fed back to the engine (``record_outcome``) so the re-entry governor's loss caps apply.
- Exit at the close after ``max_hold_bars``. ``cost_per_unit`` (round trip, price units) is charged on every fill.
Results are research evidence only and carry the caller's ``data_label``. Nothing is submitted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.detectors import Candidate
from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.zones import Zone


@dataclass
class ReplayTrade:
    candidate_id: str
    detector: str
    direction: str
    detected_at: int
    entry: float
    stop: float
    target: float
    filled_at: int | None = None
    exit_at: int | None = None
    exit_price: float | None = None
    outcome: str = "unfilled"          # unfilled | target | stop | timeout | open
    ambiguous: bool = False
    r_multiple: float | None = None
    features: dict[str, Any] = field(default_factory=dict)
    entry_type: str = "limit"          # "stop": fills when price crosses entry, at max(entry, open) (long) / min (short)
    fill_ratio: float = 1.0            # filled qty / order qty (volume-capped partial fill; remainder cancelled)
    order_qty: float | None = None     # per-trade order size (overrides ReplayConfig.order_qty for the participation cap)


@dataclass
class ReplayConfig:
    entry_window: int = 3
    max_hold_bars: int = 8
    cost_per_unit: float = 0.0
    cost_bps: float = 0.0              # round-trip cost as bps of entry, added to cost_per_unit
    zone_rule: str | None = None       # None: ORB candidates only; "zone_entry_v1": also research-map zones
    # execution realism (defaults keep the original behaviour)
    latency_bars: int = 0              # bars after detection before the order is working (decision + routing delay)
    limit_fill: str = "touch"          # "touch" | "trade_through": limit fills only if price trades strictly beyond it
    order_qty: float | None = None     # with max_participation: volume-capped partial fill on the first fill bar
    max_participation: float | None = None   # fraction of the fill bar's volume we may take; volume<=0 -> no fill


# Paper realism used by the research lab, chart markers, the ML dataset and the paper setup autopilot (section 25):
# the order is working one bar after detection, a limit fills only when price trades strictly through it, and a fill
# may take at most 10% of the fill bar's volume (1-unit research orders; bars with zero/unknown volume do not fill).
PAPER_REALISM = {"latency_bars": 1, "limit_fill": "trade_through", "order_qty": 1.0, "max_participation": 0.10}


def paper_replay_config(**kw: Any) -> "ReplayConfig":
    return ReplayConfig(**{**PAPER_REALISM, **kw})


def weighted_r(t: "ReplayTrade") -> float | None:
    return None if t.r_multiple is None else t.r_multiple * t.fill_ratio


def trade_cost(t: "ReplayTrade", cfg: ReplayConfig) -> float:
    return cfg.cost_per_unit + cfg.cost_bps * 1e-4 * abs(t.entry)


ZONE_RULE_RR = 2.0


def zone_trade(z: Zone, bar: Bar) -> "ReplayTrade | None":
    """Research mapping ``zone_entry_v1`` for zone-only detectors (dual_bollinger, wick_reversal).
    Entry limit at the confirmation bar close, stop at the far zone bound, target at 2R. Not a live rule."""
    long = z.direction == "bullish"
    entry = bar.close
    stop = z.lower_bound if long else z.upper_bound
    risk = (entry - stop) if long else (stop - entry)
    if not risk > 0:
        return None
    tgt = entry + ZONE_RULE_RR * risk if long else entry - ZONE_RULE_RR * risk
    fs = z.feature_snapshot or {}
    if z.zone_type == "wick_reversal":
        score = fs.get("lower_wick_ratio") if long else fs.get("upper_wick_ratio")
    else:
        score = fs.get("breakout_strength_atr")
    return ReplayTrade(f"{z.zone_id}:{bar.end}", z.zone_type, "long" if long else "short", bar.end, entry, stop, tgt,
                       features={"score": score, "risk_atr": risk / fs["atr"] if fs.get("atr") else None})


@dataclass
class ReplayResult:
    data_label: str
    trades: list[ReplayTrade]
    candidates: list[Candidate]
    bars: int
    refused: int
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"data_label": self.data_label, "bars": self.bars, "refused": self.refused, "summary": self.summary,
                "trades": [asdict(t) for t in self.trades], "execution_permission": "none"}


def try_fill(t: "ReplayTrade", b: Bar, cfg: "ReplayConfig | None" = None, age: int = 0) -> bool:
    """Entry fill on bar b. Limit: touched -> fill at the limit (no improvement). Stop: crossed -> fill at the trigger,
    or at the open when the bar gaps through it (slippage taken in full). With ``cfg``: no fill while
    ``age < latency_bars``; ``trade_through`` limits need a strict cross; participation caps the filled qty."""
    long = t.direction == "long"
    if cfg is not None and age < cfg.latency_bars:
        return False
    strict = cfg is not None and cfg.limit_fill == "trade_through"
    if t.entry_type == "stop":
        if not ((b.high >= t.entry) if long else (b.low <= t.entry)):
            return False
        t.entry = max(t.entry, b.open) if long else min(t.entry, b.open)
        if (long and t.entry <= t.stop) or (not long and t.entry >= t.stop) or \
                (long and t.entry >= t.target) or (not long and t.entry <= t.target):
            t.outcome = "gap_skipped"          # gapped beyond stop/target: the stop order would be cancelled
            return False
    elif strict and not ((b.low < t.entry) if long else (b.high > t.entry)):
        return False
    elif not ((b.low <= t.entry) if long else (b.high >= t.entry)):
        return False
    qty = (t.order_qty or (cfg.order_qty if cfg is not None else None))
    if cfg is not None and qty and cfg.max_participation:
        cap = max(0.0, b.volume) * cfg.max_participation
        if cap <= 0:
            return False                          # unknown/zero volume: assume no fill (conservative)
        t.fill_ratio = min(1.0, cap / qty)
    t.filled_at, t.outcome = b.start, "open"
    return True


def _step_trade(t: ReplayTrade, b: Bar, cfg: ReplayConfig, held: int) -> None:
    long = t.direction == "long"
    risk = abs(t.entry - t.stop)

    def close(price: float, outcome: str) -> None:
        pnl = (price - t.entry) if long else (t.entry - price)
        t.exit_at, t.exit_price, t.outcome = b.start, price, outcome
        t.r_multiple = (pnl - trade_cost(t, cfg)) / risk if risk > 0 else None

    hit_stop = b.low <= t.stop if long else b.high >= t.stop
    hit_tgt = b.high >= t.target if long else b.low <= t.target
    if t.filled_at == b.start:                       # fill bar: stop only
        if hit_stop:
            t.ambiguous = hit_tgt
            close(t.stop, "stop")
        return
    gap_stop = b.open <= t.stop if long else b.open >= t.stop
    gap_tgt = b.open >= t.target if long else b.open <= t.target
    if gap_stop:
        close(b.open, "stop")
    elif gap_tgt:
        close(t.target, "target")
    elif hit_stop:
        t.ambiguous = hit_tgt
        close(t.stop, "stop")
    elif hit_tgt:
        close(t.target, "target")
    elif held >= cfg.max_hold_bars:
        close(b.close, "timeout")


def replay(instrument: str, timeframe: int, bars: Sequence[Bar], *, engine_cfg: EngineConfig | None = None,
           cfg: ReplayConfig | None = None, data_label: str) -> ReplayResult:
    cfg = cfg or ReplayConfig()
    eng = PriceActionEngine(instrument, timeframe, engine_cfg)
    trades: list[ReplayTrade] = []
    waiting: list[tuple[ReplayTrade, int]] = []
    live: list[tuple[ReplayTrade, int]] = []
    for b in bars:
        # 1) manage existing state using this bar (decided before the bar is shown to detectors)
        nxt_live = []
        for t, held in live:
            _step_trade(t, b, cfg, held + 1)
            if t.exit_at is None:
                nxt_live.append((t, held + 1))
            else:
                eng.record_outcome(t.detector, t.exit_at, weighted_r(t))   # section 13 feedback, before detection
        live = nxt_live
        nxt_wait = []
        for t, age in waiting:
            if try_fill(t, b, cfg, age):
                _step_trade(t, b, cfg, 0)
                if t.exit_at is None:
                    live.append((t, 0))
                else:
                    eng.record_outcome(t.detector, t.exit_at, weighted_r(t))
            elif t.outcome == "gap_skipped":
                pass
            elif age + 1 < cfg.entry_window + cfg.latency_bars:
                nxt_wait.append((t, age + 1))
        waiting = nxt_wait
        # 2) live detection path on the closed bar
        for ev in eng.update(b):
            if isinstance(ev, Candidate):
                t = ReplayTrade(ev.candidate_id, ev.detector, ev.direction, ev.detected_at,
                                ev.entry_reference, ev.proposed_stop, ev.proposed_target,
                                features={"score": ev.features.get("breakout_strength_atr", ev.features.get("reward_risk")),
                                          **{k: v for k, v in ev.features.items() if isinstance(v, (int, float))}},
                                entry_type=ev.entry_type)
                trades.append(t)
                waiting.append((t, 0))
            elif cfg.zone_rule == "zone_entry_v1" and isinstance(ev, Zone) and ev.zone_type != "opening_range" \
                    and not ev.zone_type.startswith("pdr_"):   # PDR level zones are context, not trade rules
                zt = zone_trade(ev, b)
                if zt is not None:
                    trades.append(zt)
                    waiting.append((zt, 0))
    res = ReplayResult(data_label, trades, eng.candidates, len(bars), len(eng.refused))
    done = [t for t in trades if t.r_multiple is not None]
    res.summary = {
        "candidates": len(trades),
        "filled": sum(t.filled_at is not None for t in trades),
        "target": sum(t.outcome == "target" for t in trades),
        "stop": sum(t.outcome == "stop" for t in trades),
        "timeout": sum(t.outcome == "timeout" for t in trades),
        "still_open": sum(t.outcome == "open" for t in trades),
        "ambiguous_bars_counted_as_stop": sum(t.ambiguous for t in trades),
        "mean_r": (sum(t.r_multiple for t in done) / len(done)) if done else None,
        "total_r": sum(t.r_multiple for t in done) if done else None,
        "cost_per_unit": cfg.cost_per_unit, "cost_bps": cfg.cost_bps, "zone_rule": cfg.zone_rule,
        "latency_bars": cfg.latency_bars, "limit_fill": cfg.limit_fill, "max_participation": cfg.max_participation,
        "mean_fill_ratio": (sum(t.fill_ratio for t in trades if t.filled_at is not None) /
                            max(1, sum(t.filled_at is not None for t in trades))),
        "total_weighted_r": sum(weighted_r(t) for t in done) if done else None,
        "fill_model": "conservative_ohlc_v1",
        "reentry_refusals": sum(1 for d in eng.detectors for n in getattr(d, "no_trades", []) if n.get("reason") == "REENTRY_LIMIT"),
    }
    return res


def outcome_labels(res: ReplayResult) -> list[tuple[str, int]]:
    """(candidate_id, 1 if target first else 0) for resolved trades: setup_success labels for calibration."""
    return [(t.candidate_id, int(t.outcome == "target")) for t in res.trades if t.outcome in ("target", "stop")]
