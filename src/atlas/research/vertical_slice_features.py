"""Persistent, point-in-time research slice from bars to paper authorization.

The slice is deliberately narrow and auditable:

* bars must carry both an event time and an ``available_at`` close time;
* features and labels are built only from completed bars;
* walk-forward evaluation purges the training rows whose labels overlap the
  test decisions and adds an embargo;
* forecasts carry calibrated-ish multiclass probabilities, an empirical
  return interval, and an explicit abstain action;
* a proposed action can only become a paper position through
  :class:`ActionableControlPlaneEngine`.

Nothing in this module sends a live order. Forecast accuracy and paper P&L are
kept separate because a correct direction is not a profitable trade.
"""

from __future__ import annotations

import base64
import bisect
import functools
import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

import numpy as np

from atlas.control.advanced_integration import (
    EnhancedControlPlaneEngine,
    create_enhanced_control_plane,
)
from atlas.control.engine import (
    ActionableControlPlaneEngine,
    ActionableOrderDecision,
    ActionableOrderRequest,
    ActionablePositionRecord,
)
from atlas.control.uncertainty_gating import UncertaintyGatingConfig
from atlas.marketdata.data_rights import DataUseDenied, require_data_use
from atlas.strategies.base import StrategySignal

PATH_ID = "vertical-slice-intelligence:v2"
MODEL_FAMILY = "softmax_logistic"
XGBOOST_FAMILY = "xgboost_multiclass"
FEATURE_NAMES: tuple[str, ...] = (
    "return_1",
    "return_3",
    "return_5",
    "return_10",
    "realized_vol_5",
    "range_pct",
    "close_location",
    "volume_z_10",
    "trend_10",
    "drawdown_5",
    "atr_5_pct",
    "volume_change_5",
)
SESSION_FEATURE_NAMES: tuple[str, ...] = (
    "session_sin",
    "session_cos",
    "weekday_sin",
    "weekday_cos",
)
CROSS_ASSET_FEATURE_NAMES: tuple[str, ...] = (
    "ref_return_1",
    "ref_return_5",
    "ref_relative_return_5",
    "ref_correlation_20",
    "ref_vol_ratio_5",
)
RESEARCH_FEATURE_NAMES: tuple[str, ...] = (
    FEATURE_NAMES + SESSION_FEATURE_NAMES + CROSS_ASSET_FEATURE_NAMES
)
FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "momentum": ("return_1", "return_3", "return_5", "return_10"),
    "trend": ("trend_10",),
    "volatility": ("realized_vol_5", "range_pct", "atr_5_pct"),
    "positioning": ("close_location", "drawdown_5"),
    "volume": ("volume_z_10", "volume_change_5"),
    "session": SESSION_FEATURE_NAMES,
    "cross_asset": CROSS_ASSET_FEATURE_NAMES,
}
CLASS_NAMES: tuple[str, ...] = ("down", "neutral", "up")
CLASS_INDEX = {"down": 0, "neutral": 1, "up": 2}
ROUND_TRIP_BPS = {"competition": 16.0, "open_market": 4.0}
MIN_BARS = max(20, len(FEATURE_NAMES) + 8)
DEFAULT_DB_PATH = Path("var") / "vertical_slice.sqlite3"
PAPER_ENGINE_ID = "vertical_slice_paper"
PAPER_STATE_KEY = "vertical_slice_paper:v1"
SCHEDULER_STATE_KEY = "vertical_slice_scheduler:v1"


# ---------------------------------------------------------------------------
# Candle validation, data-use admission, and point-in-time examples
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candle:
    symbol: str
    venue: str
    timestamp: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    license_ref: str


@dataclass(frozen=True)
class FeatureRow:
    features: tuple[float, ...]
    decision_time: datetime
    target_time: datetime
    reference_price: float
    target_price: float | None
    forward_return: float | None
    label: int | None

    @property
    def resolved(self) -> bool:
        return self.label is not None and self.forward_return is not None


@dataclass(frozen=True)
class SliceConfig:
    horizon_steps: int = 1
    bucket_seconds: int = 86_400
    min_train_rows: int = 30
    walk_forward_splits: int = 4
    purge_steps: int | None = None
    embargo_steps: int = 1
    confidence_threshold: float = 0.45
    edge_threshold: float = 0.10
    l2: float = 0.02
    epochs: int = 450
    learning_rate: float = 0.05
    seed: int = 42
    risk_fraction: float = 0.003
    max_notional_usd: Decimal = Decimal("25000")
    starting_equity_usd: Decimal = Decimal("100000")
    data_age_ms: float = 0.0

    def purge(self) -> int:
        return self.horizon_steps if self.purge_steps is None else self.purge_steps

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon_steps": self.horizon_steps,
            "bucket_seconds": self.bucket_seconds,
            "min_train_rows": self.min_train_rows,
            "walk_forward_splits": self.walk_forward_splits,
            "purge_steps": self.purge(),
            "embargo_steps": self.embargo_steps,
            "confidence_threshold": self.confidence_threshold,
            "edge_threshold": self.edge_threshold,
            "l2": self.l2,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "seed": self.seed,
            "risk_fraction": self.risk_fraction,
            "max_notional_usd": str(self.max_notional_usd),
            "starting_equity_usd": str(self.starting_equity_usd),
        }


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def normalize_candles(
    rows: Iterable[dict[str, Any]],
    *,
    symbol: str,
    bucket_seconds: int,
    default_source: str = "user_supplied_unverified",
    default_license: str = "unknown",
    venue: str = "public",
) -> tuple[list[Candle], dict[str, Any]]:
    """Validate OHLCV structure; source labels alone do not establish rights."""
    if bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    usable: list[Candle] = []
    rejected: list[dict[str, Any]] = []
    duplicates = 0
    for index, raw in enumerate(rows):
        try:
            stamp = _utc(raw["timestamp"])
            open_px = _finite(raw["open"], "open")
            high = _finite(raw["high"], "high")
            low = _finite(raw["low"], "low")
            close = _finite(raw["close"], "close")
            volume = _finite(raw.get("volume", 0.0), "volume")
            if min(open_px, high, low, close) <= 0:
                raise ValueError("prices must be positive")
            if high < max(open_px, close) or low > min(open_px, close) or low > high:
                raise ValueError("OHLC bounds are inconsistent")
            if volume < 0:
                raise ValueError("volume must be non-negative")
            available = _utc(raw.get("available_at") or stamp + timedelta(seconds=bucket_seconds))
            conservative_close = stamp + timedelta(seconds=bucket_seconds)
            if available < conservative_close:
                available = conservative_close
            usable.append(
                Candle(
                    symbol=symbol.upper(),
                    venue=str(raw.get("venue") or venue),
                    timestamp=stamp,
                    available_at=available,
                    open=open_px,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    source=str(raw.get("source") or default_source),
                    license_ref=str(raw.get("license_ref") or default_license),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"index": index, "reason": str(exc)})
    usable.sort(key=lambda candle: candle.available_at)
    deduped: list[Candle] = []
    for candle in usable:
        if deduped and candle.available_at == deduped[-1].available_at:
            previous = deduped[-1]
            if (
                previous.timestamp == candle.timestamp
                and math.isclose(previous.close, candle.close, rel_tol=0, abs_tol=1e-12)
                and math.isclose(previous.open, candle.open, rel_tol=0, abs_tol=1e-12)
            ):
                duplicates += 1
                continue
            rejected.append({"index": None, "reason": "conflicting duplicate available_at"})
            continue
        deduped.append(candle)
    gap_count = 0
    for previous, current in zip(deduped, deduped[1:]):
        delta = (current.timestamp - previous.timestamp).total_seconds()
        if delta > bucket_seconds * 1.5:
            gap_count += 1
    quality = {
        "rows_received": index + 1 if "index" in locals() else 0,
        "rows_usable": len(deduped),
        "rows_rejected": len(rejected),
        "duplicates_removed": duplicates,
        "gaps": gap_count,
        "bucket_seconds": bucket_seconds,
        "source": deduped[0].source if deduped else default_source,
        "license_ref": deduped[0].license_ref if deduped else default_license,
        "rejected": rejected[:20],
        "point_in_time": True,
        "timestamp_meaning": "event time is the bar open; available_at is the bar close",
    }
    return deduped, quality


def _public_rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep the provider identity when API envelopes become candle rows."""
    block = payload or {}
    source = str(block.get("feed_source") or "public_market_candles")
    return [{**row, "source": source, "license_ref": "unverified_public_terms"}
            for row in block.get("candles") or []]


def _admit_rows(
    rows: Iterable[dict[str, Any]], *, symbol: str, bucket_seconds: int,
    as_of: datetime,
) -> tuple[list[Candle], dict[str, Any]]:
    """Admit sourced public data and exclude information unavailable as of use.

    Unannotated injected rows remain unverified research inputs, which permits
    deterministic fixture experiments without declaring them deployment ready.
    Public provenance is checked again even when callers set ``fetch=False``.
    """
    materialized = list(rows)
    providers: set[str] = set()
    for row in materialized:
        source = " ".join(str(row.get(key) or "") for key in ("source", "feed_source", "feed_origin", "provider_id")).lower()
        license_ref = str(row.get("license_ref") or "").lower()
        if "coinbase" in source:
            providers.add("coinbase_exchange_public")
        elif "yahoo" in source:
            providers.add("yahoo_chart_public")
        elif "public_market_candles" in source or license_ref in {"venue_public_research_terms", "unverified_public_terms"}:
            providers.add("coinbase_exchange_public" if symbol.endswith("-USD") else "yahoo_chart_public")
    decisions = []
    for provider in sorted(providers):
        _req = getattr(sys.modules.get("atlas.research.vertical_slice"), "require_data_use", require_data_use)
        decisions.append(_req(provider, symbol, bucket_seconds, "training"))
        decisions.append(_req(provider, symbol, bucket_seconds, "retention"))
    normalized, quality = normalize_candles(
        materialized, symbol=symbol, bucket_seconds=bucket_seconds,
        default_source="user_supplied_unverified", default_license="unknown",
    )
    cutoff = _utc(as_of)
    completed = [candle for candle in normalized if candle.available_at <= cutoff]
    return completed, {
        **quality, "rows_usable": len(completed),
        "rows_not_yet_available": len(normalized) - len(completed),
        "as_of": cutoff.isoformat(), "deployment_eligible": False,
        "data_use_admission": {"state": "operator_attested" if decisions else "unverified_user_supplied",
                               "decisions": decisions},
    }


def _blocked_data_use(symbol: str, exc: DataUseDenied) -> dict[str, Any]:
    return {"symbol": symbol, "status": "blocked", "reason": "data_use_denied",
            "data_use": exc.decision, "execution_permission": "none"}


def _returns(closes: Sequence[float], index: int, periods: int) -> float:
    if index - periods < 0:
        return 0.0
    base = closes[index - periods]
    return 0.0 if base == 0 else closes[index] / base - 1.0


def _std(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _feature_values(candles: Sequence[Candle], index: int) -> tuple[float, ...]:
    closes = [candle.close for candle in candles]
    volumes = [candle.volume for candle in candles]
    lookback = max(12, 5)
    window = candles[index - lookback : index + 1]
    recent_returns = [
        closes[position] / closes[position - 1] - 1.0
        for position in range(max(1, index - 4), index + 1)
        if closes[position - 1] != 0
    ]
    bar = candles[index]
    bar_range = bar.high - bar.low
    close_location = 0.5 if bar_range <= 0 else (bar.close - bar.low) / bar_range
    volume_window = volumes[index - 9 : index + 1]
    volume_mean = sum(volume_window) / len(volume_window)
    volume_std = _std(volume_window)
    volume_z = 0.0 if volume_std == 0 else (bar.volume - volume_mean) / volume_std
    recent_volume_mean = sum(volumes[index - 4 : index + 1]) / 5
    volume_change = 0.0 if recent_volume_mean == 0 else bar.volume / recent_volume_mean - 1.0
    true_ranges: list[float] = []
    for position in range(max(1, index - 4), index + 1):
        previous_close = closes[position - 1]
        current = candles[position]
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous_close),
                abs(current.low - previous_close),
            )
        )
    atr = sum(true_ranges) / len(true_ranges) if true_ranges else bar_range
    drawdown = closes[index] / max(closes[index - 4 : index + 1]) - 1.0
    values = (
        _returns(closes, index, 1),
        _returns(closes, index, 3),
        _returns(closes, index, 5),
        _returns(closes, index, 10),
        _std(recent_returns),
        bar_range / bar.close if bar.close else 0.0,
        close_location,
        volume_z,
        _returns(closes, index, 10),
        drawdown,
        atr / bar.close if bar.close else 0.0,
        volume_change,
    )
    return tuple(float(np.clip(value, -1e6, 1e6)) for value in values)


def build_feature_rows(
    candles: Sequence[Candle],
    config: SliceConfig,
    *,
    extra_count: int = 0,
    extra_builder: Any | None = None,
) -> list[FeatureRow]:
    """Build causal feature rows; resolved rows have a future label.

    ``extra_builder`` may append research-only features to the production
    vector. It is called with ``(candles, index)`` and must return the same
    number of values as ``extra_count``.
    """
    if len(candles) < MIN_BARS:
        return []
    rows: list[FeatureRow] = []
    cost_fraction = 0.0  # labels are classified by the caller's track cost
    start = max(len(FEATURE_NAMES) + extra_count, 10)
    for index in range(start, len(candles)):
        target_index = index + config.horizon_steps
        target = candles[target_index] if target_index < len(candles) else None
        forward = None if target is None else target.close / candles[index].close - 1.0
        label = None
        if forward is not None:
            label = _classify(forward, cost_fraction)
        extras = () if extra_builder is None else tuple(extra_builder(candles, index))
        if len(extras) != extra_count:
            raise ValueError("extra_builder returned the wrong number of features")
        rows.append(
            FeatureRow(
                features=_feature_values(candles, index) + extras,
                decision_time=candles[index].available_at,
                target_time=(
                    target.available_at
                    if target is not None
                    else candles[index].available_at
                    + timedelta(seconds=config.bucket_seconds * config.horizon_steps)
                ),
                reference_price=candles[index].close,
                target_price=None if target is None else target.close,
                forward_return=forward,
                label=label,
            )
        )
    return rows


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    size = min(len(left), len(right))
    if size < 2:
        return 0.0
    a = np.asarray(left[-size:], dtype=np.float64)
    b = np.asarray(right[-size:], dtype=np.float64)
    a_std = float(a.std())
    b_std = float(b.std())
    if a_std <= 0.0 or b_std <= 0.0:
        return 0.0
    return float(np.clip(np.corrcoef(a, b)[0, 1], -1.0, 1.0))


def _default_reference_symbol(symbol: str) -> str:
    wanted = symbol.upper()
    if wanted == "BTC-USD":
        return "ETH-USD"
    if wanted.endswith("-USD"):
        return "BTC-USD"
    if wanted == "SPY":
        return "QQQ"
    return "SPY"


def build_research_feature_rows(
    candles: Sequence[Candle],
    config: SliceConfig,
    *,
    reference_candles: Sequence[Candle] | None = None,
    include_session: bool = True,
    include_cross_asset: bool = True,
) -> tuple[list[FeatureRow], tuple[str, ...], bool]:
    """Build production features plus optional session and cross-asset features.

    Cross-asset values are aligned by the reference candle's ``available_at``
    being no later than the primary decision time. Missing reference history
    produces neutral zeros, and the returned flag reports whether the reference
    was usable. These are research candidates, not the production feature set.
    """
    names: list[str] = list(FEATURE_NAMES)
    if include_session:
        names.extend(SESSION_FEATURE_NAMES)
    reference_available = bool(reference_candles) and include_cross_asset
    if reference_available:
        names.extend(CROSS_ASSET_FEATURE_NAMES)
    names_tuple = tuple(names)
    closes = [candle.close for candle in candles]
    reference = list(reference_candles or [])
    reference.sort(key=lambda candle: candle.available_at)
    ref_times = [candle.available_at for candle in reference]
    ref_closes = [candle.close for candle in reference]

    def extras(_candles: Sequence[Candle], index: int) -> tuple[float, ...]:
        values: list[float] = []
        decision_time = candles[index].available_at
        if include_session:
            seconds = (
                decision_time.hour * 3600
                + decision_time.minute * 60
                + decision_time.second
            )
            angle = 2.0 * math.pi * seconds / 86_400.0
            weekday = 2.0 * math.pi * decision_time.weekday() / 7.0
            values.extend((math.sin(angle), math.cos(angle), math.sin(weekday), math.cos(weekday)))
        if reference_available:
            position = bisect.bisect_right(ref_times, decision_time) - 1
            if position < 5:
                values.extend((0.0, 0.0, 0.0, 0.0, 0.0))
            else:
                ref_return_1 = _returns(ref_closes, position, 1)
                ref_return_5 = _returns(ref_closes, position, 5)
                primary_return_5 = _returns(closes, index, 5)
                primary_returns = [
                    closes[item] / closes[item - 1] - 1.0
                    for item in range(max(1, index - 19), index + 1)
                    if closes[item - 1] != 0.0
                ]
                aligned_ref_returns = [
                    ref_closes[item] / ref_closes[item - 1] - 1.0
                    for item in range(max(1, position - 19), position + 1)
                    if ref_closes[item - 1] != 0.0
                ]
                primary_vol = _std(primary_returns[-5:])
                reference_vol = _std(aligned_ref_returns[-5:])
                ratio = 0.0 if reference_vol <= 0.0 else min(primary_vol / reference_vol, 10.0)
                values.extend(
                    (
                        ref_return_1,
                        ref_return_5,
                        primary_return_5 - ref_return_5,
                        _correlation(primary_returns, aligned_ref_returns),
                        ratio,
                    )
                )
        return tuple(float(np.clip(value, -1e6, 1e6)) for value in values)

    rows = build_feature_rows(
        candles,
        config,
        extra_count=len(names_tuple) - len(FEATURE_NAMES),
        extra_builder=extras,
    )
    return rows, names_tuple, reference_available


def _classify(forward_return: float, cost_fraction: float) -> int:
    if forward_return > cost_fraction:
        return CLASS_INDEX["up"]
    if forward_return < -cost_fraction:
        return CLASS_INDEX["down"]
    return CLASS_INDEX["neutral"]


def _relabel(rows: Sequence[FeatureRow], cost_bps: float) -> list[FeatureRow]:
    cost_fraction = cost_bps / 10_000.0
    return [
        FeatureRow(
            features=row.features,
            decision_time=row.decision_time,
            target_time=row.target_time,
            reference_price=row.reference_price,
            target_price=row.target_price,
            forward_return=row.forward_return,
            label=None if row.forward_return is None else _classify(row.forward_return, cost_fraction),
        )
        for row in rows
    ]
