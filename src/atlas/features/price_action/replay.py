"""Deterministic bar replay that uses the *live* path (``PriceActionEngine.update``), bar by bar.

The paper fill model is deliberately conservative, because OHLC bars cannot show the order of events inside a bar:
- Entry is a limit at ``entry_reference``, active from the bar *after* detection for ``entry_window`` bars.
  It fills at the limit price (no price improvement is assumed when a bar opens through it).
- On the fill bar, a stop touch counts as a stop-out and a target touch is ignored.
- Afterwards, an open beyond the stop exits at the open (the gap is taken in full). An open beyond the target exits
  at the target (no gap gain). A bar that touches both stop and target is counted as a stop (``ambiguous`` += 1).
- Exit at the close after ``max_hold_bars``. ``cost_per_unit`` (round trip, price units) is charged on every fill.
Results are research evidence only and carry the caller's ``data_label``. Nothing is submitted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.detectors import Candidate
from atlas.features.price_action.engine import EngineConfig, PriceActionEngine


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


@dataclass
class ReplayConfig:
    entry_window: int = 3
    max_hold_bars: int = 8
    cost_per_unit: float = 0.0


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


def _step_trade(t: ReplayTrade, b: Bar, cfg: ReplayConfig, held: int) -> None:
    long = t.direction == "long"
    risk = abs(t.entry - t.stop)

    def close(price: float, outcome: str) -> None:
        pnl = (price - t.entry) if long else (t.entry - price)
        t.exit_at, t.exit_price, t.outcome = b.start, price, outcome
        t.r_multiple = (pnl - cfg.cost_per_unit) / risk if risk > 0 else None

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
        live = nxt_live
        nxt_wait = []
        for t, age in waiting:
            touched = b.low <= t.entry if t.direction == "long" else b.high >= t.entry
            if touched:
                t.filled_at, t.outcome = b.start, "open"
                _step_trade(t, b, cfg, 0)
                if t.exit_at is None:
                    live.append((t, 0))
            elif age + 1 < cfg.entry_window:
                nxt_wait.append((t, age + 1))
        waiting = nxt_wait
        # 2) live detection path on the closed bar
        for ev in eng.update(b):
            if isinstance(ev, Candidate):
                t = ReplayTrade(ev.candidate_id, ev.detector, ev.direction, ev.detected_at,
                                ev.entry_reference, ev.proposed_stop, ev.proposed_target)
                trades.append(t)
                waiting.append((t, 0))
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
        "cost_per_unit": cfg.cost_per_unit,
        "fill_model": "conservative_ohlc_v1",
    }
    return res


def outcome_labels(res: ReplayResult) -> list[tuple[str, int]]:
    """(candidate_id, 1 if target first else 0) for resolved trades: setup_success labels for calibration."""
    return [(t.candidate_id, int(t.outcome == "target")) for t in res.trades if t.outcome in ("target", "stop")]
