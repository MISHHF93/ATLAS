"""Causal price-action and order-flow strategy detectors extending the ATLAS strategy suite:

1. ``FailedBreakoutReversalDetector`` (``failed_breakout_reversal``):
   Detects multi-bar range breakouts that fail to hold and close back inside the prior range
   within ``reclaim_window_bars``, targeting mean-reversion across the range.
2. ``NasdaqOpeningSessionDetector`` (``nasdaq_opening_drive``):
   Scoped strictly to Nasdaq instruments (``NQ``, ``MNQ``, ``QQQ``, ``TQQQ``, ``NDX``). Models the
   09:30–10:00 America/New_York Cash Open initial balance (IB-30) drive or failed-open reversal.
3. ``FairPriceSessionAnchorDetector`` (``fair_price_session_anchor``):
   Tracks causal session VWAP, cumulative volume-weighted variance, and session opening anchor.
   Detects stretched value rejection back to fair price or trend reclaim of session VWAP.
4. ``ScheduledNewsPostReleaseDetector`` (``scheduled_news_post_release``):
   Consumes ``EconomicEvent`` objects strictly through ``event.as_of(bar.end)`` (zero look-ahead).
   Constructs the post-release volatility box once the release bar closes and detects post-release
   accepted breakout or snapback reversal.
5. ``WhaleOrderFlowDetector`` (``whale_orderflow_research``):
   Computes causal rolling volume z-score, Close Location Value (CLV), and Effort-vs-Result
   absorption metrics to identify institutional/whale accumulation and distribution footprints.
6. ``PropFirmCompetitionAdvisor`` (``prop_firm_competition_intel``):
   Deterministic risk-reducing overlay for prop-firm / competition rules (trailing drawdown buffer,
   daily loss pacing, consistency rule cap). Outputs ``size_scalar <= 1.0`` and never loosens
   ``config/founder/risk_policy.yaml``.

All detectors enforce ``execution_permission="none"``.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

from atlas.features.price_action.bars import EPS, Bar, bar_confirmed, candle_geometry
from atlas.features.price_action.detectors import Candidate
from atlas.features.price_action.events import EconomicEvent
from atlas.features.price_action.features import batch_features
from atlas.features.price_action.zones import Zone

EXECUTION_PERMISSION = "none"
NY_TZ = ZoneInfo("America/New_York")
NASDAQ_INSTRUMENTS = frozenset({"NQ", "MNQ", "QQQ", "TQQQ", "NDX", "NQ=F", "MNQ=F"})


def is_nasdaq_instrument(instrument: str) -> bool:
    norm = (instrument or "").strip().upper()
    return norm in NASDAQ_INSTRUMENTS


# ---------------------------------------------------------------------------
# 1. Failed Breakout Reversal Detector
# ---------------------------------------------------------------------------

@dataclass
class FailedBreakoutConfig:
    lookback_bars: int = 12
    reclaim_window_bars: int = 3
    min_pierce_atr: float = 0.05
    reward_risk: float = 2.0


class FailedBreakoutReversalDetector:
    """Detects a breakout beyond the prior ``lookback_bars`` range high/low that fails and closes
    back inside the range within ``reclaim_window_bars`` completed bars."""

    name = "failed_breakout_reversal"

    def __init__(self, instrument: str, timeframe: int, cfg: FailedBreakoutConfig | None = None):
        self.instrument = instrument
        self.timeframe = timeframe
        self.cfg = cfg or FailedBreakoutConfig()
        self.hist: deque[Bar] = deque(maxlen=self.cfg.lookback_bars)
        self.pending_breakout: dict[str, Any] | None = None
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        atr = float(ctx.get("atr") or max(bar.high - bar.low, EPS))

        # Check if a pending breakout fails and reclaims back inside the range
        if self.pending_breakout is not None:
            p = self.pending_breakout
            p["age"] += 1
            p["extreme_high"] = max(p["extreme_high"], bar.high)
            p["extreme_low"] = min(p["extreme_low"], bar.low)

            if p["breakout_dir"] == "up" and bar.close < p["range_high"] and bar.close < bar.open:
                # Failed upside breakout -> Short reversal candidate
                lo, hi = p["range_high"], p["extreme_high"]
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "failed_breakout_reversal",
                    "bearish",
                    lo,
                    max(hi, lo + EPS),
                    p["started_at"],
                    confirmed_at=bar.end,
                    source_event=f"failed_up_bo@{p['started_at']}",
                    feature_snapshot={
                        "range_high": p["range_high"],
                        "range_low": p["range_low"],
                        "failed_extreme": p["extreme_high"],
                        "reclaim_bars": p["age"],
                        "atr": atr,
                    },
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = p["extreme_high"] + 0.15 * atr
                risk = max(abs(stop - entry), EPS)
                target = entry - self.cfg.reward_risk * risk
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:short",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="short",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=p["extreme_high"],
                    proposed_stop=stop,
                    proposed_target=target,
                    zone=z.to_dict(),
                    features={
                        "trap_magnitude_atr": (p["extreme_high"] - p["range_high"]) / max(atr, EPS),
                        "reclaim_bars": p["age"],
                        "range_width_atr": (p["range_high"] - p["range_low"]) / max(atr, EPS),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)
                self.pending_breakout = None
            elif p["breakout_dir"] == "down" and bar.close > p["range_low"] and bar.close > bar.open:
                # Failed downside breakdown -> Long reversal candidate
                lo, hi = p["extreme_low"], p["range_low"]
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "failed_breakout_reversal",
                    "bullish",
                    lo,
                    max(hi, lo + EPS),
                    p["started_at"],
                    confirmed_at=bar.end,
                    source_event=f"failed_dn_bo@{p['started_at']}",
                    feature_snapshot={
                        "range_high": p["range_high"],
                        "range_low": p["range_low"],
                        "failed_extreme": p["extreme_low"],
                        "reclaim_bars": p["age"],
                        "atr": atr,
                    },
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = p["extreme_low"] - 0.15 * atr
                risk = max(abs(entry - stop), EPS)
                target = entry + self.cfg.reward_risk * risk
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:long",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="long",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=p["extreme_low"],
                    proposed_stop=stop,
                    proposed_target=target,
                    zone=z.to_dict(),
                    features={
                        "trap_magnitude_atr": (p["range_low"] - p["extreme_low"]) / max(atr, EPS),
                        "reclaim_bars": p["age"],
                        "range_width_atr": (p["range_high"] - p["range_low"]) / max(atr, EPS),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)
                self.pending_breakout = None
            elif p["age"] >= self.cfg.reclaim_window_bars:
                self.pending_breakout = None

        if len(self.hist) >= max(4, self.cfg.lookback_bars // 2) and self.pending_breakout is None:
            r_high = max(b.high for b in self.hist)
            r_low = min(b.low for b in self.hist)
            min_pierce = self.cfg.min_pierce_atr * atr
            if bar.close > r_high + min_pierce:
                self.pending_breakout = {
                    "breakout_dir": "up",
                    "range_high": r_high,
                    "range_low": r_low,
                    "extreme_high": bar.high,
                    "extreme_low": bar.low,
                    "started_at": bar.start,
                    "age": 0,
                }
            elif bar.close < r_low - min_pierce:
                self.pending_breakout = {
                    "breakout_dir": "down",
                    "range_high": r_high,
                    "range_low": r_low,
                    "extreme_high": bar.high,
                    "extreme_low": bar.low,
                    "started_at": bar.start,
                    "age": 0,
                }

        self.hist.append(bar)
        return out


# ---------------------------------------------------------------------------
# 2. Nasdaq (NQ / QQQ) Opening Session Detector
# ---------------------------------------------------------------------------

@dataclass
class NasdaqOpeningConfig:
    opening_window_seconds: int = 1800  # 09:30 - 10:00 ET (30-min Initial Balance)
    min_drive_body_ratio: float = 0.45
    reward_risk: float = 2.0


class NasdaqOpeningSessionDetector:
    """Scoped strictly to Nasdaq instruments (NQ, MNQ, QQQ, TQQQ, NDX).
    Tracks the 09:30–10:00 America/New_York Cash Open Initial Balance (IB-30) and detects either:
    - Opening Drive continuation on an accepted close outside IB-30 with displacement, or
    - Opening Judas Swing / failed IB extension that reclaims the opening anchor.
    """

    name = "nasdaq_opening_drive"

    def __init__(self, instrument: str, timeframe: int, cfg: NasdaqOpeningConfig | None = None):
        self.instrument = instrument
        self.timeframe = timeframe
        self.cfg = cfg or NasdaqOpeningConfig()
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []
        self._session_date: str | None = None
        self._open_ts: int = 0
        self._ib_end_ts: int = 0
        self._open_price: float | None = None
        self._ib_high: float | None = None
        self._ib_low: float | None = None
        self._ib_confirmed: bool = False
        self._emitted_for_session: bool = False

    def _ny_session_bounds(self, ts: int) -> tuple[str, int, int]:
        dt_ny = dt.datetime.fromtimestamp(ts, tz=NY_TZ)
        session_date = dt_ny.strftime("%Y-%m-%d")
        open_dt = dt_ny.replace(hour=9, minute=30, second=0, microsecond=0)
        close_dt = dt_ny.replace(hour=16, minute=0, second=0, microsecond=0)
        return session_date, int(open_dt.timestamp()), int(close_dt.timestamp())

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        if not is_nasdaq_instrument(self.instrument):
            return []
        out: list[Any] = []
        s_date, open_ts, close_ts = self._ny_session_bounds(bar.start)
        if bar.start < open_ts or bar.end > close_ts:
            return out

        if s_date != self._session_date:
            self._session_date = s_date
            self._open_ts = open_ts
            self._ib_end_ts = open_ts + self.cfg.opening_window_seconds
            self._open_price = bar.open
            self._ib_high = bar.high
            self._ib_low = bar.low
            self._ib_confirmed = False
            self._emitted_for_session = False

        atr = float(ctx.get("atr") or max(bar.high - bar.low, EPS))
        if bar.end <= self._ib_end_ts:
            self._ib_high = bar.high if self._ib_high is None else max(self._ib_high, bar.high)
            self._ib_low = bar.low if self._ib_low is None else min(self._ib_low, bar.low)
            if bar.end == self._ib_end_ts and self._ib_high is not None and self._ib_low is not None:
                self._ib_confirmed = True
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "nasdaq_ib30",
                    "neutral",
                    self._ib_low,
                    max(self._ib_high, self._ib_low + EPS),
                    self._open_ts,
                    confirmed_at=bar.end,
                    source_event=f"nq_ib30:{s_date}",
                    feature_snapshot={
                        "ib_range": self._ib_high - self._ib_low,
                        "open_price": self._open_price,
                        "atr": atr,
                    },
                )
                self.zones.append(z)
                out.append(z)
            return out

        if not self._ib_confirmed or self._emitted_for_session or self._ib_high is None or self._ib_low is None:
            return out

        geom = candle_geometry(bar)
        ib_rng = max(self._ib_high - self._ib_low, EPS)
        if bar.close > self._ib_high and geom["body_ratio"] >= self.cfg.min_drive_body_ratio:
            entry = bar.close
            stop = max(self._ib_low, entry - max(ib_rng * 0.6, atr))
            risk = max(abs(entry - stop), EPS)
            target = entry + self.cfg.reward_risk * risk
            z_dict = self.zones[-1].to_dict() if self.zones else {}
            cand = Candidate(
                candidate_id=f"{self.instrument}:{self.name}:{bar.end}:long",
                detector=self.name,
                instrument=self.instrument,
                direction="long",
                detected_at=bar.end,
                entry_reference=entry,
                invalidation_level=self._ib_low,
                proposed_stop=stop,
                proposed_target=target,
                zone=z_dict,
                features={
                    "ib_range": ib_rng,
                    "drive_extension_atr": (bar.close - self._ib_high) / max(atr, EPS),
                    "body_ratio": geom["body_ratio"],
                    "session_date": s_date,
                },
            )
            self.candidates.append(cand)
            self._emitted_for_session = True
            out.append(cand)
        elif bar.close < self._ib_low and geom["body_ratio"] >= self.cfg.min_drive_body_ratio:
            entry = bar.close
            stop = min(self._ib_high, entry + max(ib_rng * 0.6, atr))
            risk = max(abs(stop - entry), EPS)
            target = entry - self.cfg.reward_risk * risk
            z_dict = self.zones[-1].to_dict() if self.zones else {}
            cand = Candidate(
                candidate_id=f"{self.instrument}:{self.name}:{bar.end}:short",
                detector=self.name,
                instrument=self.instrument,
                direction="short",
                detected_at=bar.end,
                entry_reference=entry,
                invalidation_level=self._ib_high,
                proposed_stop=stop,
                proposed_target=target,
                zone=z_dict,
                features={
                    "ib_range": ib_rng,
                    "drive_extension_atr": (self._ib_low - bar.close) / max(atr, EPS),
                    "body_ratio": geom["body_ratio"],
                    "session_date": s_date,
                },
            )
            self.candidates.append(cand)
            self._emitted_for_session = True
            out.append(cand)
        return out


# ---------------------------------------------------------------------------
# 3. Fair-Price / Session-Anchor Detector (Causal Session VWAP + Opening Anchor)
# ---------------------------------------------------------------------------

@dataclass
class FairPriceAnchorConfig:
    band_sigma: float = 1.75
    min_bars_in_session: int = 4
    reward_risk: float = 2.0


class FairPriceSessionAnchorDetector:
    """Computes causal session VWAP and volume-weighted dispersion bands around the daily/session
    anchor. Emits a candidate when price stretches beyond ``band_sigma`` standard deviations from
    session fair price and prints a confirmed rejection bar back toward session VWAP."""

    name = "fair_price_session_anchor"

    def __init__(self, instrument: str, timeframe: int, cfg: FairPriceAnchorConfig | None = None):
        self.instrument = instrument
        self.timeframe = timeframe
        self.cfg = cfg or FairPriceAnchorConfig()
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []
        self._day_key: str | None = None
        self._cum_pv: float = 0.0
        self._cum_p2v: float = 0.0
        self._cum_v: float = 0.0
        self._session_open: float | None = None
        self._bars_in_session: int = 0
        self._stretched_dir: Literal["above", "below"] | None = None
        self._stretch_extreme: float | None = None

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        day_key = dt.datetime.fromtimestamp(bar.start, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        if day_key != self._day_key:
            self._day_key = day_key
            self._cum_pv = 0.0
            self._cum_p2v = 0.0
            self._cum_v = 0.0
            self._session_open = bar.open
            self._bars_in_session = 0
            self._stretched_dir = None
            self._stretch_extreme = None

        tp = (bar.high + bar.low + bar.close) / 3.0
        vol = max(float(bar.volume), 1.0)
        self._cum_pv += tp * vol
        self._cum_p2v += (tp * tp) * vol
        self._cum_v += vol
        self._bars_in_session += 1

        vwap = self._cum_pv / max(self._cum_v, EPS)
        variance = max(0.0, (self._cum_p2v / max(self._cum_v, EPS)) - (vwap * vwap))
        atr = float(ctx.get("atr") or max(bar.high - bar.low, EPS))
        sigma = max(math.sqrt(variance), 0.35 * atr)
        upper_band = vwap + self.cfg.band_sigma * sigma
        lower_band = vwap - self.cfg.band_sigma * sigma

        if self._bars_in_session < self.cfg.min_bars_in_session:
            return out

        if self._stretched_dir == "above":
            self._stretch_extreme = max(float(self._stretch_extreme or bar.high), bar.high)
            if bar.close < upper_band and bar.close < bar.open:
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "fair_price_anchor",
                    "bearish",
                    vwap,
                    max(upper_band, vwap + EPS),
                    bar.start,
                    confirmed_at=bar.end,
                    source_event=f"vwap_reversion_short@{bar.end}",
                    feature_snapshot={"vwap": vwap, "sigma": sigma, "session_open": self._session_open},
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = float(self._stretch_extreme) + 0.15 * atr
                risk = max(abs(stop - entry), EPS)
                target = max(vwap, entry - self.cfg.reward_risk * risk) if entry - self.cfg.reward_risk * risk < vwap else vwap
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:short",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="short",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=float(self._stretch_extreme),
                    proposed_stop=stop,
                    proposed_target=entry - self.cfg.reward_risk * risk,
                    zone=z.to_dict(),
                    features={
                        "session_vwap": round(vwap, 6),
                        "session_open_anchor": self._session_open,
                        "vwap_zscore": round((bar.close - vwap) / max(sigma, EPS), 4),
                        "fair_value_target": round(vwap, 6),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)
                self._stretched_dir = None
                self._stretch_extreme = None
        elif self._stretched_dir == "below":
            self._stretch_extreme = min(float(self._stretch_extreme or bar.low), bar.low)
            if bar.close > lower_band and bar.close > bar.open:
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "fair_price_anchor",
                    "bullish",
                    min(lower_band, vwap - EPS),
                    vwap,
                    bar.start,
                    confirmed_at=bar.end,
                    source_event=f"vwap_reversion_long@{bar.end}",
                    feature_snapshot={"vwap": vwap, "sigma": sigma, "session_open": self._session_open},
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = float(self._stretch_extreme) - 0.15 * atr
                risk = max(abs(entry - stop), EPS)
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:long",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="long",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=float(self._stretch_extreme),
                    proposed_stop=stop,
                    proposed_target=entry + self.cfg.reward_risk * risk,
                    zone=z.to_dict(),
                    features={
                        "session_vwap": round(vwap, 6),
                        "session_open_anchor": self._session_open,
                        "vwap_zscore": round((bar.close - vwap) / max(sigma, EPS), 4),
                        "fair_value_target": round(vwap, 6),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)
                self._stretched_dir = None
                self._stretch_extreme = None

        if bar.high > upper_band:
            self._stretched_dir = "above"
            self._stretch_extreme = max(float(self._stretch_extreme or bar.high), bar.high)
        elif bar.low < lower_band:
            self._stretched_dir = "below"
            self._stretch_extreme = min(float(self._stretch_extreme or bar.low), bar.low)

        return out


# ---------------------------------------------------------------------------
# 4. Scheduled News Post-Release Detector (Strictly Causal via event.as_of)
# ---------------------------------------------------------------------------

@dataclass
class ScheduledNewsConfig:
    max_bars_after_release: int = 8
    reward_risk: float = 2.0


class ScheduledNewsPostReleaseDetector:
    """Strictly causal post-release scheduled-news detector.
    - Never predicts pre-release direction.
    - Queries ``event.as_of(bar.end)`` at every completed bar so unreleased actuals/consensus never leak.
    - When the release bar completes, locks the post-release volatility box ``[release_low, release_high]``.
    - Emits a post-release candidate when a subsequent bar within ``max_bars_after_release`` confirms
      acceptance outside the release box.
    """

    name = "scheduled_news_post_release"

    def __init__(
        self,
        instrument: str,
        timeframe: int,
        events: Sequence[EconomicEvent] = (),
        cfg: ScheduledNewsConfig | None = None,
    ):
        self.instrument = instrument
        self.timeframe = timeframe
        self.events = tuple(events)
        self.cfg = cfg or ScheduledNewsConfig()
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []
        self._active_boxes: dict[str, dict[str, Any]] = {}
        self._completed_events: set[str] = set()

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        atr = float(ctx.get("atr") or max(bar.high - bar.low, EPS))

        for raw_ev in self.events:
            if raw_ev.instrument_relevance and self.instrument not in raw_ev.instrument_relevance:
                continue
            if raw_ev.event_id in self._completed_events:
                continue
            ev = raw_ev.as_of(bar.end)
            release_t = ev.actual_release_time or ev.scheduled_release_time
            # Only form the release box on the completed candle containing the release timestamp
            if ev.event_id not in self._active_boxes and bar.start <= release_t < bar.end:
                surprise = ev.raw_surprise(bar.end)
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "economic_event",
                    "neutral",
                    bar.low,
                    max(bar.high, bar.low + EPS),
                    bar.start,
                    confirmed_at=bar.end,
                    source_event=ev.event_id,
                    feature_snapshot={
                        "event_type": ev.event_type,
                        "raw_surprise": surprise,
                        "reported_value": ev.reported_value,
                        "consensus_value": ev.consensus_value,
                    },
                )
                self.zones.append(z)
                out.append(z)
                self._active_boxes[ev.event_id] = {
                    "event": ev,
                    "zone": z,
                    "low": bar.low,
                    "high": bar.high,
                    "bars_since": 0,
                    "surprise": surprise,
                }
                continue

            if ev.event_id in self._active_boxes and bar.start >= release_t:
                box = self._active_boxes[ev.event_id]
                box["bars_since"] += 1
                hi, lo = box["high"], box["low"]
                rng = max(hi - lo, EPS)
                if bar.close > hi:
                    entry = bar.close
                    stop = max(lo, entry - max(rng, atr))
                    risk = max(abs(entry - stop), EPS)
                    cand = Candidate(
                        candidate_id=f"{self.instrument}:{self.name}:{ev.event_id}:{bar.end}:long",
                        detector=self.name,
                        instrument=self.instrument,
                        direction="long",
                        detected_at=bar.end,
                        entry_reference=entry,
                        invalidation_level=lo,
                        proposed_stop=stop,
                        proposed_target=entry + self.cfg.reward_risk * risk,
                        zone=box["zone"].to_dict(),
                        features={
                            "event_id": ev.event_id,
                            "event_type": ev.event_type,
                            "raw_surprise": box["surprise"],
                            "bars_since_release": box["bars_since"],
                            "release_box_width_atr": rng / max(atr, EPS),
                        },
                    )
                    self.candidates.append(cand)
                    out.append(cand)
                    self._completed_events.add(ev.event_id)
                    del self._active_boxes[ev.event_id]
                elif bar.close < lo:
                    entry = bar.close
                    stop = min(hi, entry + max(rng, atr))
                    risk = max(abs(stop - entry), EPS)
                    cand = Candidate(
                        candidate_id=f"{self.instrument}:{self.name}:{ev.event_id}:{bar.end}:short",
                        detector=self.name,
                        instrument=self.instrument,
                        direction="short",
                        detected_at=bar.end,
                        entry_reference=entry,
                        invalidation_level=hi,
                        proposed_stop=stop,
                        proposed_target=entry - self.cfg.reward_risk * risk,
                        zone=box["zone"].to_dict(),
                        features={
                            "event_id": ev.event_id,
                            "event_type": ev.event_type,
                            "raw_surprise": box["surprise"],
                            "bars_since_release": box["bars_since"],
                            "release_box_width_atr": rng / max(atr, EPS),
                        },
                    )
                    self.candidates.append(cand)
                    out.append(cand)
                    self._completed_events.add(ev.event_id)
                    del self._active_boxes[ev.event_id]
                elif box["bars_since"] >= self.cfg.max_bars_after_release:
                    self._completed_events.add(ev.event_id)
                    del self._active_boxes[ev.event_id]

        return out


# ---------------------------------------------------------------------------
# 5. Whale & Institutional Order-Flow Detector
# ---------------------------------------------------------------------------

@dataclass
class WhaleOrderFlowConfig:
    vol_lookback: int = 12
    min_vol_zscore: float = 1.8
    min_abs_clv: float = 0.45
    reward_risk: float = 2.0


class WhaleOrderFlowDetector:
    """Detects institutional/whale volume anomalies combined with Close Location Value (CLV)
    accumulation/distribution or high-volume absorption wicks."""

    name = "whale_orderflow_research"

    def __init__(self, instrument: str, timeframe: int, cfg: WhaleOrderFlowConfig | None = None):
        self.instrument = instrument
        self.timeframe = timeframe
        self.cfg = cfg or WhaleOrderFlowConfig()
        self.vol_hist: deque[float] = deque(maxlen=self.cfg.vol_lookback)
        self.zones: list[Zone] = []
        self.candidates: list[Candidate] = []

    def step(self, bar: Bar, ctx: dict[str, Any]) -> list[Any]:
        out: list[Any] = []
        atr = float(ctx.get("atr") or max(bar.high - bar.low, EPS))
        rng = max(bar.high - bar.low, EPS)
        clv = ((bar.close - bar.low) - (bar.high - bar.close)) / rng

        if len(self.vol_hist) >= max(5, self.cfg.vol_lookback // 2):
            mean_v = sum(self.vol_hist) / len(self.vol_hist)
            var_v = sum((v - mean_v) ** 2 for v in self.vol_hist) / len(self.vol_hist)
            std_v = max(math.sqrt(var_v), mean_v * 0.1, EPS)
            vol_z = (bar.volume - mean_v) / std_v
            whale_net_flow = float(ctx.get("whale_net_flow") or 0.0)

            if vol_z >= self.cfg.min_vol_zscore and (clv >= self.cfg.min_abs_clv or whale_net_flow > 0):
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "whale_accumulation",
                    "bullish",
                    bar.low,
                    max(bar.high, bar.low + EPS),
                    bar.start,
                    confirmed_at=bar.end,
                    source_event=f"whale_buy@{bar.end}",
                    feature_snapshot={"vol_zscore": round(vol_z, 4), "clv": round(clv, 4), "whale_net_flow": whale_net_flow},
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = bar.low - 0.2 * atr
                risk = max(abs(entry - stop), EPS)
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:long",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="long",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=bar.low,
                    proposed_stop=stop,
                    proposed_target=entry + self.cfg.reward_risk * risk,
                    zone=z.to_dict(),
                    features={
                        "vol_zscore": round(vol_z, 4),
                        "clv": round(clv, 4),
                        "whale_net_flow": whale_net_flow,
                        "effort_vs_result": round(vol_z / max(rng / max(atr, EPS), 0.1), 4),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)
            elif vol_z >= self.cfg.min_vol_zscore and (clv <= -self.cfg.min_abs_clv or whale_net_flow < 0):
                z = Zone(
                    self.instrument,
                    self.timeframe,
                    "whale_distribution",
                    "bearish",
                    bar.low,
                    max(bar.high, bar.low + EPS),
                    bar.start,
                    confirmed_at=bar.end,
                    source_event=f"whale_sell@{bar.end}",
                    feature_snapshot={"vol_zscore": round(vol_z, 4), "clv": round(clv, 4), "whale_net_flow": whale_net_flow},
                )
                self.zones.append(z)
                out.append(z)
                entry = bar.close
                stop = bar.high + 0.2 * atr
                risk = max(abs(stop - entry), EPS)
                cand = Candidate(
                    candidate_id=f"{self.instrument}:{self.name}:{bar.end}:short",
                    detector=self.name,
                    instrument=self.instrument,
                    direction="short",
                    detected_at=bar.end,
                    entry_reference=entry,
                    invalidation_level=bar.high,
                    proposed_stop=stop,
                    proposed_target=entry - self.cfg.reward_risk * risk,
                    zone=z.to_dict(),
                    features={
                        "vol_zscore": round(vol_z, 4),
                        "clv": round(clv, 4),
                        "whale_net_flow": whale_net_flow,
                        "effort_vs_result": round(vol_z / max(rng / max(atr, EPS), 0.1), 4),
                    },
                )
                self.candidates.append(cand)
                out.append(cand)

        self.vol_hist.append(float(bar.volume))
        return out


# ---------------------------------------------------------------------------
# 6. Prop-Firm & Trading Competition Risk-Pacing Advisor (Strict Risk Reduction Only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PropFirmCompetitionState:
    account_equity_usd: float = 100_000.0
    high_water_mark_usd: float = 100_000.0
    max_trailing_drawdown_usd: float = 3_000.0
    daily_realized_pnl_usd: float = 0.0
    max_daily_loss_usd: float = 1_500.0
    total_cumulative_profit_usd: float = 0.0
    consistency_cap_fraction: float = 0.30  # single day profit target cap <= 30% of total profit target
    profit_target_usd: float = 6_000.0


class PropFirmCompetitionAdvisor:
    """Evaluates prop-firm and trading competition survival rules and computes a strictly
    risk-reducing position size scalar ``size_scalar in [0.0, 1.0]``.
    HARD INVARIANT: ``size_scalar`` NEVER exceeds ``1.0`` and NEVER overrides deterministic risk limits.
    """

    name = "prop_firm_competition_intel"

    def evaluate(self, state: PropFirmCompetitionState | None = None) -> dict[str, Any]:
        st = state or PropFirmCompetitionState()
        trailing_dd_used = max(0.0, st.high_water_mark_usd - st.account_equity_usd)
        trailing_dd_rem = max(0.0, st.max_trailing_drawdown_usd - trailing_dd_used)
        trailing_dd_frac_rem = trailing_dd_rem / max(st.max_trailing_drawdown_usd, EPS)

        daily_loss_used = max(0.0, -st.daily_realized_pnl_usd)
        daily_loss_rem = max(0.0, st.max_daily_loss_usd - daily_loss_used)
        daily_loss_frac_rem = daily_loss_rem / max(st.max_daily_loss_usd, EPS)

        # Consistency rule check: if today's positive PnL is approaching consistency_cap_fraction * profit_target
        max_single_day_profit = st.consistency_cap_fraction * st.profit_target_usd
        consistency_scalar = 1.0
        reasons: list[str] = []
        if st.daily_realized_pnl_usd > 0 and max_single_day_profit > 0:
            if st.daily_realized_pnl_usd >= max_single_day_profit:
                consistency_scalar = 0.0
                reasons.append("consistency_cap_reached_halt_for_session")
            elif st.daily_realized_pnl_usd >= 0.8 * max_single_day_profit:
                consistency_scalar = 0.25
                reasons.append("near_consistency_cap_scale_down")

        dd_scalar = min(1.0, trailing_dd_frac_rem if trailing_dd_frac_rem >= 0.5 else trailing_dd_frac_rem * 0.75)
        daily_scalar = min(1.0, daily_loss_frac_rem if daily_loss_frac_rem >= 0.5 else daily_loss_frac_rem * 0.75)
        if trailing_dd_frac_rem <= 0.15:
            dd_scalar = 0.0
            reasons.append("trailing_drawdown_buffer_critical")
        if daily_loss_frac_rem <= 0.15:
            daily_scalar = 0.0
            reasons.append("daily_loss_buffer_critical")

        size_scalar = round(max(0.0, min(1.0, dd_scalar, daily_scalar, consistency_scalar)), 4)
        return {
            "advisor": self.name,
            "size_scalar": size_scalar,
            "halt_new_entries": size_scalar == 0.0,
            "trailing_drawdown_remaining_usd": round(trailing_dd_rem, 2),
            "trailing_drawdown_remaining_pct": round(trailing_dd_frac_rem * 100.0, 2),
            "daily_loss_remaining_usd": round(daily_loss_rem, 2),
            "daily_loss_remaining_pct": round(daily_loss_frac_rem * 100.0, 2),
            "consistency_cap_usd": round(max_single_day_profit, 2),
            "reasons": reasons or ["within_competition_buffers"],
            "loosens_risk_limits": False,
            "execution_permission": EXECUTION_PERMISSION,
        }


# ---------------------------------------------------------------------------
# Unified Extended Strategy Runner
# ---------------------------------------------------------------------------

class ExtendedStrategyEngine:
    """Runs causal extended detectors over confirmed bars for a given instrument."""

    def __init__(
        self,
        instrument: str,
        timeframe: int,
        events: Sequence[EconomicEvent] = (),
        atr_n: int = 14,
    ):
        self.instrument = instrument
        self.timeframe = timeframe
        self.atr_n = atr_n
        self.detectors: list[Any] = [
            FailedBreakoutReversalDetector(instrument, timeframe),
            FairPriceSessionAnchorDetector(instrument, timeframe),
            ScheduledNewsPostReleaseDetector(instrument, timeframe, events=events),
            WhaleOrderFlowDetector(instrument, timeframe),
        ]
        if is_nasdaq_instrument(instrument):
            self.detectors.append(NasdaqOpeningSessionDetector(instrument, timeframe))

    def run_batch(self, bars: Sequence[Bar], now: int | None = None, extra_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        admitted: list[Bar] = []
        last: int | None = None
        for b in bars:
            n = b.end if now is None else now
            if b.duration != self.timeframe or not bar_confirmed(b, n) or (last is not None and b.start <= last):
                continue
            admitted.append(b)
            last = b.start
        ctxs = batch_features(admitted, self.atr_n)
        for b, c in zip(admitted, ctxs):
            merged = {**c, **(extra_ctx or {})}
            for d in self.detectors:
                d.step(b, merged)
        zones = [z.to_dict() for d in self.detectors for z in d.zones]
        candidates = [c.to_dict() for d in self.detectors for c in d.candidates]
        return {
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "admitted_bars": len(admitted),
            "detectors_run": [d.name for d in self.detectors],
            "zones": zones,
            "candidates": candidates,
            "execution_permission": EXECUTION_PERMISSION,
        }

