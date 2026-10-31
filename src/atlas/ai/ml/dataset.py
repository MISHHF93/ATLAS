"""Meta-label dataset built ONLY from the ATLAS feed store (point-in-time ``as_of`` reads).

Primary model = the price-action setup library (orb_retest, dual_band_breakout zones via zone_entry_v1,
wick_reversal, prior_day_range_reversal). Every detected setup becomes one row. Labels come from the
conservative_ohlc_v1 replay = a triple barrier: upper/lower = proposed target/stop, vertical = 1 trading day
(crypto 24h; US equities one RTH session). Meta label y = 1 iff the realized after-cost R multiple > 0
(Lopez de Prado 2018, ch. 3.6). Unfilled setups are dropped (no position was ever opened).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

import numpy as np
import pandas as pd

from atlas.features.price_action.bars import Bar
from atlas.features.price_action.engine import EngineConfig
from atlas.features.price_action.prior_day import PriorDayRangeConfig
from atlas.features.price_action.replay import ReplayConfig, paper_replay_config, replay, trade_cost
from atlas.features.price_action.sessions import US_EQUITY_RTH, SessionSpec
from atlas.ai.ml.costs import VENUE_COSTS, venue_for
from atlas.ai.ml.features import BAR_FEATURES, bar_features
from atlas.ai.ml.vwap_features import GOLD_INSTRUMENTS

UTC_DAY = SessionSpec("utc_day", "UTC", datetime.min.time(), datetime.min.time(), weekdays=(0, 1, 2, 3, 4, 5, 6))
DETECTORS = ("dual_band_breakout", "orb_retest", "prior_day_range_reversal", "wick_reversal")
SETUP_FEATURES = ("dir_long", "reward_risk", "cost_r", "risk_atr", "entry_is_stop") + tuple(f"det_{d}" for d in DETECTORS)
SIGNED = ("ret_4", "ret_16", "ema20_dist_atr", "ema20_slope_atr", "body_frac")
FEATURES = BAR_FEATURES + SETUP_FEATURES + tuple(f"{s}_x_dir" for s in SIGNED)
# Single id for the column list above. Live scoring must refuse a manifest trained on a different list.
FEATURE_SCHEMA_VERSION = "atlas-pit-features-v2.4"
DUR = {"1m": 60, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}   # 4h = complete UTC buckets of closed feed 1h bars (crypto only)


def max_hold_bars(interval: str, asset_class: str) -> int:
    """Vertical barrier: one day for 15m/1h/4h; 1m holds 60 bars (one hour); 1d holds 10 sessions."""
    if interval == "1m":
        return 60
    if interval == "1d":
        return 10
    if asset_class == "crypto":
        return 86400 // DUR[interval]
    if interval == "4h":
        raise ValueError("4h is crypto only (equity RTH 1h bars do not tile UTC 4h buckets)")
    return {"15m": 26, "1h": 7}[interval]    # one 6.5h RTH session


@dataclass
class SeriesData:
    instrument: str
    interval: str
    asset_class: str
    bars: list[Bar]
    providers: list[str] = field(default_factory=list)

    def digest(self) -> str:
        h = hashlib.sha256(f"{self.instrument}|{self.interval}".encode())
        for b in self.bars:
            h.update(f"{b.start},{b.open!r},{b.high!r},{b.low!r},{b.close!r},{b.volume!r};".encode())
        return h.hexdigest()


def resample_buckets(sd: SeriesData, secs: int, label: str) -> SeriesData:
    """UTC ``secs`` buckets from closed bars; a bucket is emitted only when every sub-bar is present."""
    k = secs // sd.bars[0].duration if sd.bars else 1
    out, cur = [], []

    def flush() -> None:
        if len(cur) == k:
            out.append(Bar(cur[0].start // secs * secs, secs, cur[0].open, max(x.high for x in cur),
                           min(x.low for x in cur), cur[-1].close, sum(x.volume for x in cur)))

    for b in sd.bars:
        if cur and b.start // secs != cur[0].start // secs:
            flush()
            cur = []
        cur.append(b)
    flush()
    return SeriesData(sd.instrument, label, sd.asset_class, out, sd.providers + [f"derived:{sd.interval}->{label}"])


def resample_4h(sd: SeriesData) -> SeriesData:
    """UTC 4h buckets from closed 1h bars; a bucket is emitted only when all four 1h bars are present."""
    return resample_buckets(sd, 14400, "4h")


def load_series(feed, instrument: str, interval: str, as_of: int | None = None, start: int | None = None) -> SeriesData:
    if interval == "4h":
        sd = resample_4h(load_series(feed, instrument, "1h", as_of=as_of, start=start))
        if sd.asset_class != "crypto":
            raise ValueError("4h is crypto only")
        return sd
    fb = feed.bars(instrument, interval, start, None, as_of=as_of, confirmed_only=True) if start is not None \
        else feed.bars(instrument, interval, as_of=as_of)
    if interval == "1h" and not fb:
        inst0 = feed.instruments.get(instrument)
        if inst0 is not None and inst0.asset_class == "crypto":   # evo7: crypto alts carry only 15m; derive complete UTC hours
            sd15 = load_series(feed, instrument, "15m", as_of=as_of, start=start)
            return resample_buckets(sd15, 3600, "1h") if sd15.bars else sd15
    dur = DUR[interval]
    bars, last = [], None
    for b in fb:
        if last is not None and b.event_time <= last:
            continue
        if as_of is not None and b.event_time + dur > as_of:      # bar not closed at as_of
            continue
        try:
            bars.append(Bar(int(b.event_time), dur, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = b.event_time
    inst = feed.instruments.get(instrument)
    ac = "crypto" if inst.asset_class == "crypto" else "gold" if instrument.upper() in GOLD_INSTRUMENTS else "equity"
    return SeriesData(instrument, interval, ac, bars,
                      sorted({b.provider for b in fb if getattr(b, "provider", None)}))


def build_rows(sd: SeriesData, include_open: bool = False, variant: Any = None, detectors: Sequence[str] | None = None,
               hold_bars: int | None = None) -> pd.DataFrame:
    """One row per filled + resolved setup with causal features at detection time.

    ``include_open`` also emits filled-but-unresolved setups (outcome ``open``, r NaN, y -1, exit_at -1) for
    shadow scoring only; they are never used for training. ``variant`` (research.setup_variants.SetupVariant)
    re-labels with its ATR-scaled stop/target, cost filter and hold multiple; ``detectors`` restricts the rows;
    ``hold_bars`` overrides the vertical barrier (bars) and is None for every existing caller."""
    if len(sd.bars) < 200:
        return pd.DataFrame()
    vc = VENUE_COSTS[venue_for(sd.asset_class)]
    session = UTC_DAY if sd.asset_class == "crypto" else US_EQUITY_RTH
    vk = {} if variant is None else {"stop_atr_mult": variant.stop_atr_mult, "target_rr": variant.target_rr, "max_cost_r": variant.max_cost_r}
    hold = int(hold_bars) if hold_bars is not None else max_hold_bars(sd.interval, sd.asset_class) * (variant.hold_mult if variant is not None else 1)
    cfg = paper_replay_config(entry_window=3, max_hold_bars=hold,   # section 25 realism
                       cost_per_unit=vc["cost_per_unit"], cost_bps=vc["cost_bps"], zone_rule="zone_entry_v1", **vk)
    res = replay(sd.instrument, sd.bars[0].duration, sd.bars, engine_cfg=EngineConfig(session=session, pdr=PriorDayRangeConfig()),
                 cfg=cfg, data_label="atlas-feed")
    bf = bar_features(sd.bars, sd.asset_class, sd.instrument)
    out = []
    for t in res.trades:
        is_open = include_open and t.outcome == "open"
        if t.detector not in DETECTORS or (detectors is not None and t.detector not in detectors) or not (is_open or (t.outcome in ("target", "stop", "timeout") and t.r_multiple is not None)):
            continue
        risk = abs(t.entry - t.stop)
        if risk <= 0 or t.detected_at not in bf.index:
            continue
        x = bf.loc[t.detected_at]
        d = 1.0 if t.direction == "long" else -1.0
        atr = x["atr_bps"] * t.entry / 1e4 if np.isfinite(x["atr_bps"]) else np.nan
        row = {"instrument": sd.instrument, "interval": sd.interval, "asset_class": sd.asset_class, "detector": t.detector,
               "candidate_id": t.candidate_id, "t": int(t.detected_at), "exit_at": -1 if is_open else int(t.exit_at),
               "outcome": t.outcome, "direction": t.direction,
               "r": float("nan") if is_open else float(t.r_multiple), "y": -1 if is_open else int(t.r_multiple > 0), "entry": t.entry, "stop": t.stop, "target": t.target,
               "risk_bps": risk / t.entry * 1e4}
        row |= {k: float(x[k]) for k in BAR_FEATURES}
        row |= {"dir_long": float(d > 0), "reward_risk": abs(t.target - t.entry) / risk, "cost_r": trade_cost(t, cfg) / risk,
                "risk_atr": risk / atr if atr and np.isfinite(atr) and atr > 0 else np.nan,
                "entry_is_stop": float(t.entry_type == "stop")}
        row |= {f"det_{k}": float(t.detector == k) for k in DETECTORS}
        row |= {f"{s}_x_dir": float(x[s]) * d for s in SIGNED}
        out.append(row)
    df = pd.DataFrame(out)
    return df.sort_values(["t", "candidate_id"]).reset_index(drop=True) if len(df) else df


def latest_open_setup(bars, instrument: str, interval: str, asset_class: str) -> dict[str, Any] | None:
    """Newest filled, still-open setup as one training row, or None.

    The row comes only from ``build_rows(..., include_open=True)``. Unfilled
    candidates are dropped, the same rule as training. A resolved setup is not a
    live meta-label: the forward object is an open one. The feature columns are
    the detection-time columns, including NaN where the bar feature was NaN.
    """
    if len(bars) < 200:
        return None
    df = build_rows(SeriesData(instrument, interval, asset_class, list(bars)), include_open=True)
    if df is None or len(df) == 0 or "y" not in df.columns:
        return None
    open_rows = df.loc[df["y"] < 0]
    if len(open_rows) == 0:
        return None
    return open_rows.sort_values(["t", "candidate_id"]).iloc[-1].to_dict()


def build_dataset(feed, universe: Sequence[tuple[str, str]], as_of: int | None = None, include_open: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames, meta = [], {"series": [], "as_of": as_of}
    h = hashlib.sha256()
    for inst, iv in universe:
        sd = load_series(feed, inst, iv, as_of=as_of)
        dg = sd.digest()
        h.update(dg.encode())
        df = build_rows(sd, include_open=include_open)
        meta["series"].append({"instrument": inst, "interval": iv, "asset_class": sd.asset_class, "providers": sd.providers,
                               "n_bars": len(sd.bars), "first_bar": sd.bars[0].start if sd.bars else None,
                               "last_bar_end": sd.bars[-1].end if sd.bars else None, "sha256": dg, "n_rows": int((df.y >= 0).sum()) if len(df) else 0,
                               "max_hold_bars": max_hold_bars(iv, sd.asset_class)})
        if len(df):
            frames.append(df)
    meta["data_hash"] = h.hexdigest()
    data = pd.concat(frames, ignore_index=True).sort_values(["t", "instrument", "candidate_id"]).reset_index(drop=True) \
        if frames else pd.DataFrame()
    return data, meta


def canonical_json(o: Any) -> str:
    return json.dumps(o, sort_keys=True, default=str)
