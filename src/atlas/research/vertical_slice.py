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
        decisions.append(require_data_use(provider, symbol, bucket_seconds, "training"))
        decisions.append(require_data_use(provider, symbol, bucket_seconds, "retention"))
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


# ---------------------------------------------------------------------------
# Model and evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoftmaxModel:
    model_id: str
    feature_names: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    weights: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]
    training_rows: int
    training_loss: float
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        x = (np.asarray(features, dtype=np.float64) - np.asarray(self.mean)) / np.asarray(self.scale)
        z = x @ np.asarray(self.weights) + np.asarray(self.bias)
        z -= z.max()
        exp = np.exp(z)
        return exp / exp.sum()

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        x = (np.asarray(matrix, dtype=np.float64) - np.asarray(self.mean)) / np.asarray(self.scale)
        z = x @ np.asarray(self.weights) + np.asarray(self.bias)
        z -= z.max(axis=1, keepdims=True)
        exp = np.exp(z)
        return exp / exp.sum(axis=1, keepdims=True)

    def importance(self) -> list[dict[str, Any]]:
        weights = np.asarray(self.weights)
        magnitude = np.abs(weights).sum(axis=1)
        total = float(magnitude.sum()) or 1.0
        order = np.argsort(-magnitude)
        return [
            {
                "feature": self.feature_names[int(index)],
                "importance": round(float(magnitude[int(index)] / total), 6),
                "coef_down": round(float(weights[int(index), 0]), 6),
                "coef_neutral": round(float(weights[int(index), 1]), 6),
                "coef_up": round(float(weights[int(index), 2]), 6),
            }
            for index in order
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": MODEL_FAMILY,
            "feature_names": list(self.feature_names),
            "mean": list(self.mean),
            "scale": list(self.scale),
            "weights": [list(row) for row in self.weights],
            "bias": list(self.bias),
            "training_rows": self.training_rows,
            "training_loss": self.training_loss,
            "dataset_hash": self.dataset_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SoftmaxModel":
        return cls(
            model_id=str(payload["model_id"]),
            feature_names=tuple(payload["feature_names"]),
            mean=tuple(float(value) for value in payload["mean"]),
            scale=tuple(float(value) for value in payload["scale"]),
            weights=tuple(tuple(float(value) for value in row) for row in payload["weights"]),
            bias=tuple(float(value) for value in payload["bias"]),
            training_rows=int(payload["training_rows"]),
            training_loss=float(payload["training_loss"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def _xgboost_module() -> Any | None:
    try:
        import xgboost  # type: ignore[import-not-found]
    except ImportError:
        return None
    return xgboost


@dataclass
class XGBoostModel:
    """Small adapter around the optional XGBoost multiclass classifier."""

    model: Any
    feature_names: tuple[str, ...]
    model_id: str
    version: str
    training_rows: int
    training_log_loss: float
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        return self.predict_many(np.asarray([features], dtype=np.float64))[0]

    def _booster(self) -> Any:
        return self.model.get_booster() if hasattr(self.model, "get_booster") else self.model

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        values = np.asarray(matrix, dtype=np.float64)
        if hasattr(self.model, "get_booster"):
            raw = np.asarray(self.model.predict(values), dtype=np.float64)
        else:
            xgboost = _xgboost_module()
            if xgboost is None:
                raise RuntimeError("xgboost is unavailable")
            raw = np.asarray(
                self._booster().predict(
                    xgboost.DMatrix(values, feature_names=list(self.feature_names))
                ),
                dtype=np.float64,
            )
        if raw.ndim == 1:
            raw = np.column_stack([1.0 - raw, raw, np.zeros_like(raw)])
        raw = np.clip(raw, 1e-12, 1.0)
        return raw / raw.sum(axis=1, keepdims=True)

    def importance(self) -> list[dict[str, Any]]:
        booster = self._booster()
        raw = booster.get_score(importance_type="gain")
        values = np.asarray(
            [
                float(raw.get(f"f{index}", raw.get(name, 0.0)))
                for index, name in enumerate(self.feature_names)
            ],
            dtype=np.float64,
        )
        total = float(values.sum()) or 1.0
        order = np.argsort(-values)
        return [
            {
                "feature": self.feature_names[int(index)],
                "importance": round(float(values[int(index)] / total), 6),
                "method": "gain",
            }
            for index in order
        ]

    def explain(
        self,
        features: Sequence[float],
        class_index: int,
        feature_map: dict[str, float],
    ) -> list[dict[str, Any]]:
        xgboost = _xgboost_module()
        if xgboost is None:
            raise RuntimeError("xgboost is unavailable")
        matrix = xgboost.DMatrix(
            np.asarray([features], dtype=np.float64),
            feature_names=list(self.feature_names),
        )
        values = np.asarray(
            self._booster().predict(matrix, pred_contribs=True),
            dtype=np.float64,
        )
        if values.ndim == 3:
            contributions = values[0, :-1, class_index]
        else:
            contributions = values[0, :-1]
        order = np.argsort(-np.abs(contributions))
        return [
            {
                "feature": self.feature_names[int(index)],
                "value": round(float(feature_map[self.feature_names[int(index)]]), 8),
                "contribution": round(float(contributions[int(index)]), 8),
                "method": "tree_shap",
            }
            for index in order[:6]
        ]

    def to_dict(self) -> dict[str, Any]:
        raw = self._booster().save_raw()
        return {
            "model_id": self.model_id,
            "model_family": XGBOOST_FAMILY,
            "feature_names": list(self.feature_names),
            "training_rows": self.training_rows,
            "training_log_loss": round(self.training_log_loss, 8),
            "dataset_hash": self.dataset_hash,
            "version": self.version,
            "raw_model_b64": base64.b64encode(bytes(raw)).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "XGBoostModel":
        xgboost = _xgboost_module()
        if xgboost is None:
            raise RuntimeError("xgboost is required to load this model")
        booster = xgboost.Booster()
        booster.load_model(bytearray(base64.b64decode(payload["raw_model_b64"])))
        return cls(
            model=booster,
            feature_names=tuple(payload["feature_names"]),
            model_id=str(payload["model_id"]),
            version=str(payload.get("version") or "unknown"),
            training_rows=int(payload["training_rows"]),
            training_log_loss=float(payload["training_log_loss"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def fit_xgboost(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
    seed: int = 42,
    dataset_hash: str = "",
) -> XGBoostModel | None:
    xgboost = _xgboost_module()
    if xgboost is None:
        return None
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if x.ndim != 2 or x.shape[1] != len(feature_names) or len(y) != len(x):
        raise ValueError("feature matrix and labels are not aligned")
    if len(np.unique(y)) < 2:
        return None
    dtrain = xgboost.DMatrix(
        x,
        label=y,
        feature_names=list(feature_names),
    )
    parameters = {
        "objective": "multi:softprob",
        "num_class": 3,
        "max_depth": 3,
        "eta": 0.05,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "min_child_weight": 2.0,
        "lambda": 1.0,
        "tree_method": "hist",
        "nthread": 1,
        "seed": seed,
        "verbosity": 0,
        "eval_metric": "mlogloss",
    }
    model = xgboost.train(parameters, dtrain, num_boost_round=120)
    probabilities = np.asarray(model.predict(dtrain), dtype=np.float64)
    probabilities = np.clip(probabilities, 1e-12, 1.0)
    training_log_loss = float(
        -np.log(probabilities[np.arange(len(y)), y]).mean()
    )
    fingerprint = dataset_hash or hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    return XGBoostModel(
        model=model,
        feature_names=tuple(feature_names),
        model_id=f"{XGBOOST_FAMILY}:{fingerprint[:12]}:{len(feature_names)}f",
        version=str(getattr(xgboost, "__version__", "unknown")),
        training_rows=len(y),
        training_log_loss=training_log_loss,
        dataset_hash=fingerprint,
    )


@dataclass(frozen=True)
class ConstantProbabilityModel:
    """Baseline champion used when a learned model loses out of sample."""

    model_id: str
    model_family: str
    probabilities: tuple[float, float, float]
    feature_names: tuple[str, ...]
    training_rows: int
    dataset_hash: str

    def predict_proba(self, features: Sequence[float]) -> np.ndarray:
        return np.asarray(self.probabilities, dtype=np.float64)

    def predict_many(self, matrix: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray(self.probabilities, dtype=np.float64), (len(matrix), 1))

    def importance(self) -> list[dict[str, Any]]:
        return []

    def explain(
        self,
        features: Sequence[float],
        class_index: int,
        feature_map: dict[str, float],
    ) -> list[dict[str, Any]]:
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "probabilities": list(self.probabilities),
            "feature_names": list(self.feature_names),
            "training_rows": self.training_rows,
            "dataset_hash": self.dataset_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConstantProbabilityModel":
        values = tuple(float(value) for value in payload["probabilities"])
        if len(values) != 3:
            raise ValueError("baseline probabilities must have three classes")
        return cls(
            model_id=str(payload["model_id"]),
            model_family=str(payload["model_family"]),
            probabilities=(values[0], values[1], values[2]),
            feature_names=tuple(payload["feature_names"]),
            training_rows=int(payload["training_rows"]),
            dataset_hash=str(payload["dataset_hash"]),
        )


def _one_hot(labels: np.ndarray) -> np.ndarray:
    out = np.zeros((len(labels), 3), dtype=np.float64)
    out[np.arange(len(labels)), labels] = 1.0
    return out


def fit_softmax(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    feature_names: Sequence[str] = FEATURE_NAMES,
    l2: float = 0.02,
    epochs: int = 450,
    learning_rate: float = 0.05,
    seed: int = 42,
    dataset_hash: str = "",
) -> SoftmaxModel:
    if len(features) != len(labels) or not features:
        raise ValueError("features and labels must be non-empty and aligned")
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if x.ndim != 2 or x.shape[1] != len(feature_names):
        raise ValueError("feature matrix width does not match feature_names")
    if y.min() < 0 or y.max() > 2:
        raise ValueError("labels must be 0, 1, or 2")
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    normalized = (x - mean) / scale
    rng = np.random.default_rng(seed)
    weights = rng.normal(0.0, 0.01, size=(x.shape[1], 3))
    bias = np.zeros(3, dtype=np.float64)
    target = _one_hot(y)
    m_w = np.zeros_like(weights)
    v_w = np.zeros_like(weights)
    m_b = np.zeros_like(bias)
    v_b = np.zeros_like(bias)
    beta1, beta2, epsilon = 0.9, 0.999, 1e-8
    loss = float("inf")
    for epoch in range(1, epochs + 1):
        logits = normalized @ weights + bias
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probabilities = exp / exp.sum(axis=1, keepdims=True)
        loss = float(-np.log(np.clip(probabilities[np.arange(len(y)), y], 1e-12, 1.0)).mean())
        loss += float(l2 * np.sum(weights * weights))
        gradient = (probabilities - target) / len(y)
        grad_w = normalized.T @ gradient + 2.0 * l2 * weights
        grad_b = gradient.sum(axis=0)
        m_w = beta1 * m_w + (1 - beta1) * grad_w
        v_w = beta2 * v_w + (1 - beta2) * (grad_w * grad_w)
        m_b = beta1 * m_b + (1 - beta1) * grad_b
        v_b = beta2 * v_b + (1 - beta2) * (grad_b * grad_b)
        m_w_hat = m_w / (1 - beta1**epoch)
        v_w_hat = v_w / (1 - beta2**epoch)
        m_b_hat = m_b / (1 - beta1**epoch)
        v_b_hat = v_b / (1 - beta2**epoch)
        weights -= learning_rate * m_w_hat / (np.sqrt(v_w_hat) + epsilon)
        bias -= learning_rate * m_b_hat / (np.sqrt(v_b_hat) + epsilon)
    fingerprint = dataset_hash or hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
    model_id = f"{MODEL_FAMILY}:{fingerprint[:12]}:{len(feature_names)}f"
    return SoftmaxModel(
        model_id=model_id,
        feature_names=tuple(feature_names),
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        weights=tuple(tuple(float(value) for value in row) for row in weights),
        bias=tuple(float(value) for value in bias),
        training_rows=len(y),
        training_loss=round(loss, 8),
        dataset_hash=fingerprint,
    )


def _frequency_baseline(labels: Sequence[int]) -> np.ndarray:
    counts = np.bincount(np.asarray(labels, dtype=np.int64), minlength=3).astype(np.float64)
    counts += 0.5
    return counts / counts.sum()


def _action(probabilities: Sequence[float], config: SliceConfig) -> tuple[str, str | None, float]:
    p_down, p_neutral, p_up = (float(value) for value in probabilities)
    confidence = max(p_down, p_up)
    edge = p_up - p_down
    if (
        p_up >= config.confidence_threshold
        and p_up >= p_neutral
        and edge >= config.edge_threshold
    ):
        return "long", "up_probability_and_positive_edge", edge
    if (
        p_down >= config.confidence_threshold
        and p_down >= p_neutral
        and edge <= -config.edge_threshold
    ):
        return "short", "down_probability_and_negative_edge", edge
    if p_neutral == max(probabilities):
        return "abstain", "neutral_class", edge
    return "abstain", "confidence_or_edge_below_threshold", edge


def _bucket(value: float, bins: int = 5) -> int:
    return min(bins - 1, max(0, int(value * bins)))


def evaluate_predictions(
    probabilities: np.ndarray,
    labels: Sequence[int],
    forward_returns: Sequence[float],
    *,
    cost_bps: float,
    config: SliceConfig,
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64)
    p = np.asarray(probabilities, dtype=np.float64)
    returns = np.asarray(forward_returns, dtype=np.float64)
    target = _one_hot(y)
    brier = float(np.sum((p - target) ** 2, axis=1).mean())
    log_loss = float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1.0)).mean())
    accuracy = float((p.argmax(axis=1) == y).mean())
    actions = [_action(row, config) for row in p]
    taken = [index for index, (action, _, _) in enumerate(actions) if action != "abstain"]
    cost = cost_bps / 10_000.0
    net_returns: list[float] = []
    direction_hits = 0
    for index in taken:
        signed = returns[index] if actions[index][0] == "long" else -returns[index]
        net_returns.append(float(signed - cost))
        if signed > 0:
            direction_hits += 1
    bins: list[dict[str, Any]] = []
    predicted_class = p.argmax(axis=1)
    confidence = p[np.arange(len(y)), predicted_class]
    correct = (predicted_class == y).astype(np.float64)
    ece = 0.0
    for bucket in range(5):
        mask = np.array([_bucket(value) == bucket for value in confidence])
        count = int(mask.sum())
        mean_conf = float(confidence[mask].mean()) if count else 0.0
        observed = float(correct[mask].mean()) if count else 0.0
        if count:
            ece += count / len(y) * abs(mean_conf - observed)
        bins.append(
            {
                "lower": round(bucket / 5, 2),
                "upper": round((bucket + 1) / 5, 2),
                "count": count,
                "mean_confidence": round(mean_conf, 6) if count else None,
                "observed_accuracy": round(observed, 6) if count else None,
            }
        )
    return {
        "rows": int(len(y)),
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "accuracy": round(accuracy, 6),
        "coverage": round(len(taken) / len(y), 6) if len(y) else 0.0,
        "taken": len(taken),
        "direction_hits": direction_hits,
        "direction_accuracy": round(direction_hits / len(taken), 6) if taken else None,
        "mean_net_return": round(float(np.mean(net_returns)), 8) if net_returns else None,
        "cumulative_net_return": round(float(np.sum(net_returns)), 8) if net_returns else None,
        "cost_bps": cost_bps,
        "expected_calibration_error": round(ece, 6),
        "calibration_bins": bins,
        "execution": "not_attempted",
        "execution_permission": "none",
    }


def _dataset_fingerprint(rows: Sequence[FeatureRow], symbol: str, config: SliceConfig) -> str:
    digest = hashlib.sha256()
    digest.update(symbol.encode("utf-8"))
    digest.update(json.dumps(config.as_dict(), sort_keys=True).encode("utf-8"))
    for row in rows:
        digest.update(row.decision_time.isoformat().encode("ascii"))
        digest.update(np.asarray(row.features, dtype=np.float64).tobytes())
        if row.label is not None:
            digest.update(bytes([row.label]))
    return digest.hexdigest()


def purged_walk_forward(
    rows: Sequence[FeatureRow],
    symbol: str,
    *,
    cost_bps: float,
    config: SliceConfig,
    feature_names: Sequence[str] = FEATURE_NAMES,
    collect_rows: bool = False,
) -> dict[str, Any]:
    """Compare candidates on purged expanding-window model-selection folds.

    Every candidate, including the frequency baseline, is fitted on that fold's
    training labels only. Pooled OOS comparison selects a candidate; it is not an
    independent evaluation of the selected model or deployment approval.
    """
    resolved = [row for row in rows if row.resolved]
    total = len(resolved)
    if total < config.min_train_rows + 5:
        return {
            "status": "insufficient_history",
            "required_rows": config.min_train_rows + 5,
            "available_rows": total,
            "notice": "The slice will not report walk-forward metrics without enough resolved labels.",
        }
    predictions: list[np.ndarray] = []
    frequency_predictions: list[np.ndarray] = []
    xgb_predictions: list[np.ndarray] = []
    labels: list[int] = []
    returns: list[float] = []
    prediction_rows: list[dict[str, Any]] = []
    folds: list[dict[str, Any]] = []
    xgb_errors: list[str] = []
    xgb = _xgboost_module()
    xgb_version = None if xgb is None else str(getattr(xgb, "__version__", "unknown"))
    train_floor = config.min_train_rows
    remaining = total - train_floor
    block = max(5, remaining // max(1, config.walk_forward_splits))
    dataset_hash = _dataset_fingerprint(resolved, symbol, config)
    for fold in range(config.walk_forward_splits):
        test_start = train_floor + fold * block
        if test_start >= total:
            break
        test_end = min(total, test_start + block)
        # A row at index i resolves at i + horizon. Anything at or after
        # test_start - horizon can share bars with the test decision.
        train_end = test_start - config.purge() - config.embargo_steps
        if train_end < train_floor:
            continue
        train_rows = resolved[:train_end]
        test_rows = resolved[test_start:test_end]
        if not train_rows or not test_rows:
            continue
        # Freeze the class prior before any test outcomes are scored. Fitting a
        # single prior to the pooled test labels would give the baseline future
        # information unavailable to the other candidates.
        frequency = _frequency_baseline([int(row.label) for row in train_rows])
        fold_frequency_predictions = np.tile(frequency, (len(test_rows), 1))
        frequency_predictions.extend(fold_frequency_predictions)
        model = fit_softmax(
            [row.features for row in train_rows],
            [int(row.label) for row in train_rows],
            feature_names=feature_names,
            l2=config.l2,
            epochs=config.epochs,
            learning_rate=config.learning_rate,
            seed=config.seed + fold,
            dataset_hash=dataset_hash,
        )
        probabilities = model.predict_many(np.asarray([row.features for row in test_rows]))
        predictions.extend(probabilities)
        labels.extend(int(row.label) for row in test_rows)
        returns.extend(float(row.forward_return) for row in test_rows)
        if collect_rows:
            prediction_rows.extend(
                {
                    "decision_time": row.decision_time.isoformat(),
                    "label": int(row.label),
                    "forward_return": float(row.forward_return),
                    "probabilities": [float(value) for value in probability],
                    "frequency_baseline_probabilities": [float(value) for value in frequency],
                }
                for row, probability in zip(test_rows, probabilities)
            )
        if xgb is not None and not xgb_errors:
            try:
                challenger = fit_xgboost(
                    [row.features for row in train_rows],
                    [int(row.label) for row in train_rows],
                    feature_names=feature_names,
                    seed=config.seed + fold,
                    dataset_hash=dataset_hash,
                )
                if challenger is None:
                    xgb_errors.append("insufficient_class_diversity")
                    xgb_predictions.clear()
                else:
                    xgb_predictions.extend(
                        challenger.predict_many(np.asarray([row.features for row in test_rows]))
                    )
            except Exception as exc:
                xgb_errors.append(f"{type(exc).__name__}: {exc}")
                xgb_predictions.clear()
        folds.append(
            {
                "fold": fold,
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
                "train_last_decision": train_rows[-1].decision_time.isoformat(),
                "train_last_target": train_rows[-1].target_time.isoformat(),
                "test_first_decision": test_rows[0].decision_time.isoformat(),
                "frequency_baseline_probabilities": [float(value) for value in frequency],
                "purged_steps": config.purge(),
                "embargo_steps": config.embargo_steps,
                "no_label_overlap": train_rows[-1].target_time < test_rows[0].decision_time,
            }
        )
    if not predictions:
        return {
            "status": "insufficient_history",
            "available_rows": total,
            "notice": "No fold had enough training rows after purging.",
        }
    matrix = np.asarray(predictions)
    softmax_metrics = evaluate_predictions(
        matrix, labels, returns, cost_bps=cost_bps, config=config
    )
    frequency_metrics = evaluate_predictions(
        np.asarray(frequency_predictions), labels, returns, cost_bps=cost_bps, config=config
    )
    uniform_metrics = evaluate_predictions(
        np.full((len(labels), 3), 1.0 / 3.0),
        labels,
        returns,
        cost_bps=cost_bps,
        config=config,
    )
    if xgb is None:
        challenger: dict[str, Any] = {
            "name": "xgboost",
            "status": "unavailable",
            "version": None,
            "reason": "Package is not installed; no challenger metrics are reported.",
        }
    elif xgb_errors:
        challenger = {
            "name": "xgboost",
            "status": "failed",
            "version": xgb_version,
            "reason": xgb_errors[-1],
        }
    elif len(xgb_predictions) == len(labels):
        challenger = {
            "name": "xgboost",
            "status": "scored",
            "version": xgb_version,
            "model_family": XGBOOST_FAMILY,
            "model": evaluate_predictions(
                np.asarray(xgb_predictions),
                labels,
                returns,
                cost_bps=cost_bps,
                config=config,
            ),
        }
    else:
        challenger = {
            "name": "xgboost",
            "status": "failed",
            "version": xgb_version,
            "reason": "Challenger predictions did not align with test rows.",
        }
    candidates: list[tuple[str, dict[str, Any]]] = [
        (MODEL_FAMILY, softmax_metrics),
        ("frequency_baseline", frequency_metrics),
        ("uniform_baseline", uniform_metrics),
    ]
    if challenger["status"] == "scored":
        candidates.append((XGBOOST_FAMILY, challenger["model"]))
    primary_family, primary_metrics = min(
        candidates,
        key=lambda item: (
            float(item[1]["brier_score"]),
            float(item[1]["log_loss"]),
        ),
    )
    return {
        "status": "scored",
        "model": softmax_metrics,
        "primary_model_family": primary_family,
        "primary_metrics": primary_metrics,
        "selection": {
            "primary_model_family": primary_family,
            "reason": "lowest_walk_forward_brier_then_log_loss",
            "comparison_metric": "brier_score_then_log_loss",
            "evaluation_scope": "pooled_walk_forward_model_selection",
            "independent_validation": False,
        },
        "xgboost_challenger": challenger,
        "frequency_baseline": frequency_metrics,
        "uniform_baseline": uniform_metrics,
        "folds": folds,
        "dataset_hash": dataset_hash,
        **({"prediction_rows": prediction_rows} if collect_rows else {}),
        "notice": (
            "Walk-forward rows are predictions made before their outcomes. "
            "Brier/log loss measure probabilities; net return includes the "
            "track round-trip cost and is not an executed P&L. Model selection "
            "uses pooled purged walk-forward folds with train-only class priors. "
            "These folds are model-selection evidence, not independent validation "
            "of the winner or deployment approval."
        ),
    }


def _drop_feature_columns(
    rows: Sequence[FeatureRow],
    drop_indices: set[int],
    feature_count: int,
) -> list[FeatureRow]:
    keep = [index for index in range(feature_count) if index not in drop_indices]
    return [
        FeatureRow(
            features=tuple(row.features[index] for index in keep),
            decision_time=row.decision_time,
            target_time=row.target_time,
            reference_price=row.reference_price,
            target_price=row.target_price,
            forward_return=row.forward_return,
            label=row.label,
        )
        for row in rows
    ]


def _regime_labels(
    rows: Sequence[FeatureRow],
    feature_names: Sequence[str],
) -> dict[str, str]:
    """Label each decision with a causal volatility/trend regime.

    The volatility threshold is the median of the trailing (up to 60) decisions,
    so the label never uses a later bar. This is descriptive research metadata,
    not a validated regime classifier or a trading signal.
    """
    names = tuple(feature_names)
    if "realized_vol_5" not in names or "return_10" not in names:
        return {}
    vol_index = names.index("realized_vol_5")
    return_index = names.index("return_10")
    history: list[float] = []
    labels: dict[str, str] = {}
    for row in sorted((item for item in rows if item.resolved), key=lambda item: item.decision_time):
        volatility = float(row.features[vol_index])
        prior = history[-60:]
        median = float(np.median(prior)) if len(prior) >= 5 else None
        high_vol = median is not None and volatility >= median
        direction = "up" if float(row.features[return_index]) >= 0 else "down"
        labels[row.decision_time.isoformat()] = (
            f"{direction}_{'high' if high_vol else 'low'}_vol"
        )
        history.append(volatility)
    return labels


def _regime_metrics(
    prediction_rows: Sequence[dict[str, Any]],
    regime_labels: dict[str, str],
    *,
    cost_bps: float,
    config: SliceConfig,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in prediction_rows:
        regime = regime_labels.get(str(row.get("decision_time")))
        if regime:
            groups.setdefault(regime, []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for regime, group in sorted(groups.items()):
        if len(group) < 5:
            result[regime] = {
                "status": "insufficient",
                "rows": len(group),
                "notice": "Fewer than five out-of-sample rows in this regime.",
                "execution_permission": "none",
            }
            continue
        result[regime] = {
            "status": "scored",
            "rows": len(group),
            "metrics": evaluate_predictions(
                np.asarray([row["probabilities"] for row in group], dtype=np.float64),
                [int(row["label"]) for row in group],
                [float(row["forward_return"]) for row in group],
                cost_bps=cost_bps,
                config=config,
            ),
            "execution_permission": "none",
        }
    return result


def ablate_feature_families(
    rows: Sequence[FeatureRow],
    symbol: str,
    *,
    cost_bps: float,
    config: SliceConfig,
    feature_names: Sequence[str] = FEATURE_NAMES,
    families: Sequence[str] | None = None,
    include_regimes: bool = False,
) -> dict[str, Any]:
    """Measure each feature family by retraining with that family removed.

    Every ablation uses the same purged expanding walk-forward and the same
    labels as the baseline. A family is only evidence-supported when removing
    it makes out-of-sample Brier/log loss worse; otherwise the result is
    inconclusive or negative. This is not a profitability claim.
    """
    names = tuple(feature_names)
    wanted = tuple(families or FEATURE_FAMILIES.keys())
    baseline = purged_walk_forward(
        rows,
        symbol,
        cost_bps=cost_bps,
        config=config,
        feature_names=names,
        collect_rows=include_regimes,
    )
    baseline_softmax = baseline.get("model") or {}
    regime_labels = _regime_labels(rows, names) if include_regimes else {}
    payload: dict[str, Any] = {
        "status": baseline.get("status", "unavailable"),
        "symbol": symbol.upper(),
        "config": config.as_dict(),
        "feature_names": list(names),
        "families": {
            family: list(members)
            for family, members in FEATURE_FAMILIES.items()
        },
        "baseline": {
            "primary_model_family": baseline.get("primary_model_family"),
            "primary_metrics": baseline.get("primary_metrics"),
            "softmax_metrics": baseline_softmax or None,
            **(
                {
                    "regime_metrics": _regime_metrics(
                        baseline.get("prediction_rows") or [],
                        regime_labels,
                        cost_bps=cost_bps,
                        config=config,
                    )
                }
                if include_regimes
                else {}
            ),
        },
        **({"regimes": sorted(set(regime_labels.values()))} if include_regimes else {}),
        "ablations": [],
        "notice": (
            "Each row retrains the softmax model without one feature family on "
            "the same purged walk-forward folds. Positive delta_brier_removed "
            "means removing the family made Brier worse, so the family carried "
            "out-of-sample information. Small deltas are inconclusive. Regime "
            "breakdowns, when present, are descriptive trailing thresholds, not "
            "a validated regime classifier. This is research evidence, not a "
            "profitability or live-trading claim."
        ),
        "execution_permission": "none",
    }
    if baseline.get("status") != "scored":
        return payload
    baseline_brier = float(baseline_softmax.get("brier_score") or 0.0)
    baseline_log_loss = float(baseline_softmax.get("log_loss") or 0.0)
    baseline_accuracy = float(baseline_softmax.get("accuracy") or 0.0)
    for family in wanted:
        members = tuple(
            name for name in FEATURE_FAMILIES.get(family, ()) if name in names
        )
        if not members:
            payload["ablations"].append(
                {
                    "family": family,
                    "status": "unknown_or_absent",
                    "removed_features": [],
                    "execution_permission": "none",
                }
            )
            continue
        drop_indices = {names.index(name) for name in members}
        remaining_names = tuple(name for name in names if name not in members)
        ablated = purged_walk_forward(
            _drop_feature_columns(rows, drop_indices, len(names)),
            symbol,
            cost_bps=cost_bps,
            config=config,
            feature_names=remaining_names,
            collect_rows=include_regimes,
        )
        metrics = ablated.get("model") or {}
        if ablated.get("status") != "scored" or not metrics:
            payload["ablations"].append(
                {
                    "family": family,
                    "status": ablated.get("status", "unavailable"),
                    "removed_features": list(members),
                    "remaining_features": list(remaining_names),
                    "execution_permission": "none",
                }
            )
            continue
        brier = float(metrics.get("brier_score") or 0.0)
        log_loss = float(metrics.get("log_loss") or 0.0)
        accuracy = float(metrics.get("accuracy") or 0.0)
        delta_brier = brier - baseline_brier
        delta_log_loss = log_loss - baseline_log_loss
        delta_accuracy = accuracy - baseline_accuracy
        if delta_brier > 0.005:
            evidence = "removal_worsened"
        elif delta_brier < -0.005:
            evidence = "removal_improved"
        else:
            evidence = "inconclusive"
        payload["ablations"].append(
            {
                "family": family,
                "status": "scored",
                "removed_features": list(members),
                "remaining_features": list(remaining_names),
                "metrics": metrics,
                "delta_brier_removed": round(delta_brier, 8),
                "delta_log_loss_removed": round(delta_log_loss, 8),
                "delta_accuracy_removed": round(delta_accuracy, 8),
                "evidence": evidence,
                **(
                    {
                        "regime_metrics": _regime_metrics(
                            ablated.get("prediction_rows") or [],
                            regime_labels,
                            cost_bps=cost_bps,
                            config=config,
                        )
                    }
                    if include_regimes
                    else {}
                ),
                "execution_permission": "none",
            }
        )
    payload["status"] = "measured"
    return payload


def optional_gbdt_status() -> list[dict[str, Any]]:
    """Report optional challengers honestly; never fabricate a run."""
    status: list[dict[str, Any]] = []
    for name in ("xgboost", "lightgbm"):
        try:
            module = __import__(name)
            status.append(
                {
                    "name": name,
                    "status": "available",
                    "version": getattr(module, "__version__", "unknown"),
                    "reason": "Trained as a challenger on the same purged walk-forward folds when enough history exists.",
                }
            )
        except ImportError:
            status.append(
                {
                    "name": name,
                    "status": "unavailable",
                    "version": None,
                    "reason": "Package is not installed; no challenger metrics are reported.",
                }
            )
    return status


# ---------------------------------------------------------------------------
# Persistent ledger
# ---------------------------------------------------------------------------


class ForecastLedger:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    path_id TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    model_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forecasts (
                    forecast_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    track TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL,
                    decision_time TEXT NOT NULL,
                    target_time TEXT NOT NULL,
                    bucket_seconds INTEGER,
                    horizon_steps INTEGER,
                    reference_price REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    probabilities_json TEXT NOT NULL,
                    predicted_class TEXT NOT NULL,
                    action TEXT NOT NULL,
                    action_reason TEXT,
                    confidence REAL NOT NULL,
                    edge REAL NOT NULL,
                    interval_low REAL,
                    interval_high REAL,
                    cost_bps REAL NOT NULL,
                    status TEXT NOT NULL,
                    realized_return REAL,
                    realized_class TEXT,
                    brier_score REAL,
                    resolved_at TEXT,
                    execution_permission TEXT NOT NULL DEFAULT 'none'
                );
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id TEXT PRIMARY KEY,
                    forecast_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    track TEXT NOT NULL,
                    side TEXT NOT NULL,
                    requested_notional_usd REAL NOT NULL,
                    authorized_notional_usd REAL,
                    control_plane_decision TEXT NOT NULL,
                    position_id TEXT,
                    order_id TEXT,
                    gate_scale REAL,
                    gate_reason TEXT,
                    violations_json TEXT NOT NULL,
                    stop_distance_bps REAL,
                    entry_price REAL,
                    status TEXT NOT NULL,
                    realized_return_net REAL,
                    realized_pnl_usd REAL,
                    resolved_at TEXT,
                    created_at TEXT NOT NULL,
                    execution_permission TEXT NOT NULL DEFAULT 'none'
                );
                CREATE TABLE IF NOT EXISTS paper_state (
                    engine_id TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_forecasts_status ON forecasts(status, target_time);
                CREATE INDEX IF NOT EXISTS idx_forecasts_symbol ON forecasts(symbol, decision_time);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON paper_trades(status, forecast_id);
                """
            )
            existing = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(forecasts)").fetchall()
            }
            for column in ("bucket_seconds", "horizon_steps"):
                if column not in existing:
                    self._connection.execute(
                        f"ALTER TABLE forecasts ADD COLUMN {column} INTEGER"
                    )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record_run(self, run_id: str, created_at: datetime, config: SliceConfig, report: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO runs(run_id, created_at, path_id, config_json, report_json) VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    created_at.isoformat(),
                    PATH_ID,
                    json.dumps(config.as_dict(), sort_keys=True),
                    json.dumps(report, sort_keys=True, default=str),
                ),
            )

    def save_model(
        self,
        model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel,
        symbol: str,
        created_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO models(model_id, created_at, symbol, dataset_hash, model_json) VALUES (?, ?, ?, ?, ?)",
                (
                    model.model_id,
                    created_at.isoformat(),
                    symbol,
                    model.dataset_hash,
                    json.dumps(model.to_dict(), sort_keys=True),
                ),
            )

    def load_model(
        self, model_id: str
    ) -> SoftmaxModel | XGBoostModel | ConstantProbabilityModel | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT model_json FROM models WHERE model_id = ?", (model_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["model_json"])
        if payload.get("model_family") == XGBOOST_FAMILY:
            return XGBoostModel.from_dict(payload)
        return SoftmaxModel.from_dict(payload)

    def insert_forecast(self, payload: dict[str, Any]) -> bool:
        columns = (
            "forecast_id",
            "run_id",
            "symbol",
            "track",
            "model_id",
            "model_revision",
            "dataset_hash",
            "decision_time",
            "target_time",
            "bucket_seconds",
            "horizon_steps",
            "reference_price",
            "features_json",
            "probabilities_json",
            "predicted_class",
            "action",
            "action_reason",
            "confidence",
            "edge",
            "interval_low",
            "interval_high",
            "cost_bps",
            "status",
            "execution_permission",
        )
        values = tuple(payload.get(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"INSERT OR IGNORE INTO forecasts({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return cursor.rowcount > 0

    def insert_trade(self, payload: dict[str, Any]) -> bool:
        columns = (
            "trade_id",
            "forecast_id",
            "symbol",
            "track",
            "side",
            "requested_notional_usd",
            "authorized_notional_usd",
            "control_plane_decision",
            "position_id",
            "order_id",
            "gate_scale",
            "gate_reason",
            "violations_json",
            "stop_distance_bps",
            "entry_price",
            "status",
            "created_at",
            "execution_permission",
        )
        values = tuple(payload.get(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                f"INSERT OR IGNORE INTO paper_trades({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            return cursor.rowcount > 0

    def open_forecasts(self, as_of: datetime) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM forecasts WHERE status = 'open' AND target_time <= ? ORDER BY target_time",
                (as_of.isoformat(),),
            ).fetchall()
        return [_decode_forecast(dict(row)) for row in rows]

    def resolve_forecast(
        self,
        forecast_id: str,
        *,
        realized_return: float,
        realized_class: str,
        brier_score: float,
        resolved_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE forecasts SET status = 'resolved', realized_return = ?,
                    realized_class = ?, brier_score = ?, resolved_at = ?
                WHERE forecast_id = ? AND status = 'open'
                """,
                (
                    realized_return,
                    realized_class,
                    brier_score,
                    resolved_at.isoformat(),
                    forecast_id,
                ),
            )

    def trade_for_forecast(self, forecast_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM paper_trades WHERE forecast_id = ?", (forecast_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def resolve_trade(
        self,
        trade_id: str,
        *,
        realized_return_net: float,
        realized_pnl_usd: float,
        resolved_at: datetime,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE paper_trades SET status = 'resolved', realized_return_net = ?,
                    realized_pnl_usd = ?, resolved_at = ?
                WHERE trade_id = ?
                """,
                (realized_return_net, realized_pnl_usd, resolved_at.isoformat(), trade_id),
            )

    def recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_forecasts(self, limit: int = 50, *, status: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM forecasts"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY decision_time DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, tuple(params)).fetchall()
        return [_decode_forecast(dict(row)) for row in rows]

    def latest_forecast_decision(
        self,
        symbol: str,
        horizon_steps: int | None = None,
    ) -> str | None:
        query = "SELECT decision_time FROM forecasts WHERE symbol = ?"
        params: list[Any] = [symbol.upper()]
        if horizon_steps is not None:
            query += " AND COALESCE(horizon_steps, 1) = ?"
            params.append(int(horizon_steps))
        query += " ORDER BY decision_time DESC LIMIT 1"
        with self._lock:
            row = self._connection.execute(query, tuple(params)).fetchone()
        return None if row is None else str(row["decision_time"])

    def state_keys(self, prefix: str) -> list[str]:
        escaped = (
            prefix.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        with self._lock:
            rows = self._connection.execute(
                "SELECT engine_id FROM paper_state "
                "WHERE engine_id = ? OR engine_id LIKE ? ESCAPE '\\' "
                "ORDER BY engine_id",
                (prefix, f"{escaped}%"),
            ).fetchall()
        return [str(row["engine_id"]) for row in rows]

    def save_state(self, key: str, state: dict[str, Any], updated_at: datetime) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO paper_state(engine_id, updated_at, state_json) VALUES (?, ?, ?)",
                (key, updated_at.isoformat(), json.dumps(state, sort_keys=True, default=str)),
            )

    def load_state(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM paper_state WHERE engine_id = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row["state_json"])

    def latest_run_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._connection.execute(
                "SELECT report_json FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["report_json"]) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            total = self._connection.execute("SELECT COUNT(*) AS n FROM forecasts").fetchone()["n"]
            resolved = self._connection.execute(
                "SELECT COUNT(*) AS n FROM forecasts WHERE status = 'resolved'"
            ).fetchone()["n"]
            open_rows = self._connection.execute(
                "SELECT COUNT(*) AS n FROM forecasts WHERE status = 'open'"
            ).fetchone()["n"]
            trades = [dict(row) for row in self._connection.execute(
                "SELECT * FROM paper_trades"
            ).fetchall()]
            runs = self._connection.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
            latest_run = self._connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        resolved_rows = self.recent_forecasts(500, status="resolved")
        brier_values = [row["brier_score"] for row in resolved_rows if row.get("brier_score") is not None]
        brier = float(np.mean(brier_values)) if brier_values else None
        taken = [row for row in resolved_rows if row.get("action") in ("long", "short")]
        hits = 0
        for row in taken:
            sign = 1.0 if row["action"] == "long" else -1.0
            if sign * float(row.get("realized_return") or 0.0) > 0:
                hits += 1
        authorized = [trade for trade in trades if trade["control_plane_decision"] == "authorized_paper"]
        rejected = [trade for trade in trades if trade["control_plane_decision"] != "authorized_paper"]
        resolved_trades = [trade for trade in trades if trade["status"] == "resolved"]
        pnl_values = [
            float(trade["realized_pnl_usd"])
            for trade in resolved_trades
            if trade.get("realized_pnl_usd") is not None
        ]
        report = None if latest_run is None else json.loads(latest_run["report_json"])
        return {
            "path_id": PATH_ID,
            "database": str(self.path),
            "runs": runs,
            "forecasts": {"total": total, "open": open_rows, "resolved": resolved},
            "resolved_direction_accuracy": round(hits / len(taken), 6) if taken else None,
            "resolved_taken": len(taken),
            "mean_brier_score": None if brier is None else round(brier, 8),
            "paper_trades": {
                "proposed": len([trade for trade in trades if trade["status"] != "not_proposed"]),
                "authorized": len(authorized),
                "rejected_or_not_proposed": len(rejected),
                "resolved": len(resolved_trades),
                "net_pnl_usd": round(sum(pnl_values), 2) if pnl_values else None,
                "wins": len([value for value in pnl_values if value > 0]),
                "losses": len([value for value in pnl_values if value < 0]),
            },
            "latest_run": report,
            "execution_permission": "none",
        }


def _decode_forecast(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key in ("features_json", "probabilities_json"):
        if key in decoded and isinstance(decoded[key], str):
            decoded[key.removesuffix("_json")] = json.loads(decoded[key])
            del decoded[key]
    return decoded


# ---------------------------------------------------------------------------
# Paper authorization
# ---------------------------------------------------------------------------


def build_paper_engine(
    engine_id: str = PAPER_ENGINE_ID,
    config: SliceConfig | None = None,
) -> EnhancedControlPlaneEngine:
    cfg = config or SliceConfig()
    base = ActionableControlPlaneEngine()
    base.current_equity_usd = cfg.starting_equity_usd
    base.high_water_mark_usd = cfg.starting_equity_usd
    base.start_of_day_equity_usd = cfg.starting_equity_usd
    base.gross_notional_usd = Decimal("0")
    base.correlated_exposure_usd = Decimal("0")
    base.sector_exposure_usd = Decimal("0")
    base.open_positions = []
    base.order_history = []
    base.audit_log = []
    base.completed_trading_days = max(5, base.completed_trading_days)
    base.best_day_profit_usd = Decimal("0")
    base.total_cumulative_profit_usd = Decimal("0")
    return create_enhanced_control_plane(
        engine_id,
        base,
        UncertaintyGatingConfig(
            confidence_threshold=cfg.confidence_threshold,
            interval_width_threshold=0.25,
            max_position_scale=1.0,
            min_position_scale=0.1,
        ),
    )


def _decimal_text(value: Decimal) -> str:
    return str(value)


def _max_sequence(values: Sequence[str | None], prefix: str, default: int = 1) -> int:
    highest = default
    for value in values:
        if not value or not value.startswith(prefix):
            continue
        try:
            highest = max(highest, int(value.removeprefix(prefix)))
        except ValueError:
            continue
    return highest


def serialize_paper_state(
    engine: EnhancedControlPlaneEngine,
    *,
    updated_at: datetime,
    engine_id: str = PAPER_ENGINE_ID,
) -> dict[str, Any]:
    """Serialize only the state needed to resume paper authorization.

    Closed positions are not restored; their outcomes live in the ledger. Open
    positions retain the matching order history entry because the engine reads
    entry price from ``order_history`` when it books an exit.
    """
    base = engine.base_engine
    open_positions = [position for position in base.open_positions if position.status == "open"]
    open_ids = {position.position_id for position in open_positions}
    orders = [
        order
        for order in base.order_history
        if order.position_id in open_ids and order.entry_price is not None
    ]
    return {
        "engine_id": engine_id,
        "updated_at": updated_at.isoformat(),
        "account": {
            "current_equity_usd": _decimal_text(base.current_equity_usd),
            "high_water_mark_usd": _decimal_text(base.high_water_mark_usd),
            "start_of_day_equity_usd": _decimal_text(base.start_of_day_equity_usd),
            "gross_notional_usd": _decimal_text(base.gross_notional_usd),
            "correlated_exposure_usd": _decimal_text(base.correlated_exposure_usd),
            "sector_exposure_usd": _decimal_text(base.sector_exposure_usd),
            "best_day_profit_usd": _decimal_text(base.best_day_profit_usd),
            "total_cumulative_profit_usd": _decimal_text(base.total_cumulative_profit_usd),
            "completed_trading_days": base.completed_trading_days,
        },
        "active_track": base.active_track,
        "kill_switch_engaged": base.kill_switch_engaged,
        "active_champion_model": base.active_champion_model,
        "active_challenger_model": base.active_challenger_model,
        "challenger_approved": base.challenger_approved,
        "training_runs_completed": base.training_runs_completed,
        "sequence": {"order": base._order_seq, "position": base._pos_seq},
        "open_positions": [position.model_dump(mode="json") for position in open_positions],
        "order_history": [order.model_dump(mode="json") for order in orders],
        "audit_tail": list(base.audit_log[-20:]),
        "execution_permission": "none",
    }


def restore_paper_state(engine: EnhancedControlPlaneEngine, state: dict[str, Any]) -> dict[str, Any]:
    """Restore a previously serialized paper state in place.

    Unknown or malformed sections are ignored rather than fabricated. Returns a
    small report so callers can surface what was restored.
    """
    base = engine.base_engine
    account = state.get("account") or {}
    decimal_fields = (
        "current_equity_usd",
        "high_water_mark_usd",
        "start_of_day_equity_usd",
        "gross_notional_usd",
        "correlated_exposure_usd",
        "sector_exposure_usd",
        "best_day_profit_usd",
        "total_cumulative_profit_usd",
    )
    restored_fields: list[str] = []
    for name in decimal_fields:
        raw = account.get(name)
        if raw is None:
            continue
        try:
            setattr(base, name, Decimal(str(raw)))
            restored_fields.append(name)
        except (ArithmeticError, ValueError):
            continue
    if isinstance(account.get("completed_trading_days"), int):
        base.completed_trading_days = account["completed_trading_days"]
        restored_fields.append("completed_trading_days")
    if state.get("active_track") in ("competition", "open_market"):
        base.active_track = state["active_track"]
    if isinstance(state.get("kill_switch_engaged"), bool):
        base.kill_switch_engaged = state["kill_switch_engaged"]
    for name in ("active_champion_model", "active_challenger_model"):
        if isinstance(state.get(name), str) and state[name]:
            setattr(base, name, state[name])
    if isinstance(state.get("challenger_approved"), bool):
        base.challenger_approved = state["challenger_approved"]
    if isinstance(state.get("training_runs_completed"), int):
        base.training_runs_completed = state["training_runs_completed"]

    positions: list[ActionablePositionRecord] = []
    orders: list[ActionableOrderDecision] = []
    try:
        for row in state.get("open_positions") or []:
            position = ActionablePositionRecord.model_validate(row)
            if position.status == "open":
                positions.append(position)
    except (ValueError, TypeError):
        positions = []
    open_ids = {position.position_id for position in positions}
    try:
        for row in state.get("order_history") or []:
            order = ActionableOrderDecision.model_validate(row)
            if order.position_id in open_ids:
                orders.append(order)
    except (ValueError, TypeError):
        orders = []
    base.open_positions = positions
    base.order_history = orders
    base.audit_log = [str(line) for line in (state.get("audit_tail") or [])][-20:]
    sequence = state.get("sequence") or {}
    base._order_seq = _max_sequence(
        [order.order_id for order in orders],
        "ord-",
        default=max(1, int(sequence.get("order") or 1)),
    )
    base._pos_seq = _max_sequence(
        [position.position_id for position in positions],
        "pos-",
        default=max(1, int(sequence.get("position") or 1)),
    )
    return {
        "restored": True,
        "fields": restored_fields,
        "open_positions": len(positions),
        "orders": len(orders),
        "updated_at": state.get("updated_at"),
        "execution_permission": "none",
    }


def _forecast_id(symbol: str, model_id: str, decision_time: datetime, target_time: datetime, track: str) -> str:
    raw = f"{symbol}|{track}|{model_id}|{decision_time.isoformat()}|{target_time.isoformat()}"
    return "fc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _instrument_id(track: str, symbol: str) -> str:
    if track == "competition":
        return f"comp:{symbol.lower().replace('-usd', '')}-perp:v1"
    return f"open:{symbol.lower()}-eq:v1"


def execute_forecast_paper_trade(
    forecast: dict[str, Any],
    engine: EnhancedControlPlaneEngine,
    config: SliceConfig,
) -> dict[str, Any]:
    """Convert a research action into a gated paper order.

    The engine is the sole authorization boundary. An abstain never reaches it.
    """
    action = forecast.get("action")
    trade_id = "tr_" + hashlib.sha256(str(forecast["forecast_id"]).encode("utf-8")).hexdigest()[:24]
    request_id = forecast["forecast_id"]
    base_payload: dict[str, Any] = {
        "trade_id": trade_id,
        "forecast_id": request_id,
        "symbol": forecast["symbol"],
        "track": forecast["track"],
        "side": "none",
        "requested_notional_usd": 0.0,
        "authorized_notional_usd": None,
        "control_plane_decision": "abstained",
        "position_id": None,
        "order_id": None,
        "gate_scale": None,
        "gate_reason": None,
        "violations_json": "[]",
        "stop_distance_bps": None,
        "entry_price": None,
        "status": "not_proposed",
        "created_at": forecast["decision_time"],
        "execution_permission": "none",
    }
    if action not in ("long", "short"):
        base_payload["gate_reason"] = forecast.get("action_reason") or "abstain"
        return base_payload
    price = float(forecast["reference_price"])
    stop_bps = _stop_distance(forecast)
    risk_budget = float(engine.base_engine.current_equity_usd) * config.risk_fraction
    requested = min(
        float(config.max_notional_usd),
        risk_budget / max(stop_bps / 10_000.0, 1e-6),
    )
    stop = price * (1.0 - stop_bps / 10_000.0) if action == "long" else price * (1.0 + stop_bps / 10_000.0)
    take = price * (1.0 + 2.0 * stop_bps / 10_000.0) if action == "long" else price * (1.0 - 2.0 * stop_bps / 10_000.0)
    signal = StrategySignal(
        strategy_id="VERTICAL_SLICE_SOFTMAX",
        symbol=forecast["symbol"],
        direction="BUY" if action == "long" else "SELL",
        target_conviction=float(forecast["confidence"]),
        conviction=float(forecast["confidence"]),
        suggested_stop_loss=stop,
        suggested_take_profit=take,
        reference_price=price,
        target_entry_price=price,
        rationale=str(forecast.get("action_reason") or ""),
        telemetry={"model_id": forecast["model_id"], "edge": forecast["edge"]},
    )
    instrument_id = _instrument_id(forecast["track"], forecast["symbol"])
    expected = float(forecast.get("expected_return") or 0.0)
    prediction = price * (1.0 + expected)
    lower = price * (1.0 + float(forecast.get("interval_low") or expected))
    upper = price * (1.0 + float(forecast.get("interval_high") or expected))
    gate = engine.uncertainty_gating.evaluate_trade(
        model_id=forecast["model_id"],
        instrument_id=instrument_id,
        prediction=prediction,
        lower=lower,
        upper=upper,
        confidence=float(forecast["confidence"]),
        current_price=price,
        proposed_position=requested,
    )
    now = _utc(forecast["decision_time"])
    if not gate.trade_allowed:
        request = ActionableOrderRequest(
            track=forecast["track"],
            instrument_id=instrument_id,
            side="buy" if action == "long" else "sell",
            notional_usd=Decimal(str(round(requested, 2))),
            stop_kind="atr",
            stop_distance_bps=Decimal(str(round(stop_bps, 2))),
            holding_horizon_seconds=config.bucket_seconds * config.horizon_steps,
            vpin_toxicity=0.0,
            data_age_ms=config.data_age_ms,
        )
        decision = engine.base_engine.submit_order(
            request,
            now=now,
            intake_violations=(
                "uncertainty_gating: " + (gate.rejection_reason or "trade not allowed"),
            ),
        )
        base_payload.update(
            {
                "side": action,
                "requested_notional_usd": round(requested, 2),
                "control_plane_decision": "rejected_by_uncertainty_gate",
                "position_id": None,
                "order_id": decision.order_id,
                "violations_json": json.dumps(list(decision.violations)),
                "stop_distance_bps": round(stop_bps, 2),
                "entry_price": price,
                "gate_scale": round(gate.position_scale, 6),
                "gate_reason": gate.rejection_reason,
            }
        )
        return base_payload
    authorized = Decimal(str(round(requested, 2))) * Decimal(str(gate.position_scale))
    authorized = authorized.quantize(Decimal("0.01"))
    intake = engine.base_engine.ingest_whale_policy_signal(
        signal,
        track=forecast["track"],
        desired_notional_usd=authorized,
        data_age_ms=config.data_age_ms,
        require_connector=False,
        now=now,
    )
    decision = intake.decision
    violations = list(decision.violations)
    if decision.position_id is None:
        base_payload.update(
            {
                "side": action,
                "requested_notional_usd": round(requested, 2),
                "authorized_notional_usd": float(authorized),
                "control_plane_decision": decision.control_plane_decision,
                "order_id": decision.order_id,
                "violations_json": json.dumps(violations),
                "stop_distance_bps": round(stop_bps, 2),
                "entry_price": price,
                "gate_scale": round(gate.position_scale, 6),
                "gate_reason": "control_plane_rejected",
            }
        )
        return base_payload
    base_payload.update(
        {
            "side": action,
            "requested_notional_usd": round(requested, 2),
            "authorized_notional_usd": float(decision.notional_usd),
            "control_plane_decision": "authorized_paper",
            "position_id": decision.position_id,
            "order_id": decision.order_id,
            "violations_json": json.dumps(violations),
            "stop_distance_bps": round(stop_bps, 2),
            "entry_price": price,
            "gate_scale": round(gate.position_scale, 6),
            "gate_reason": gate.rejection_reason,
            "status": "open",
        }
    )
    return base_payload


def _stop_distance(forecast: dict[str, Any]) -> float:
    features = forecast.get("features") or {}
    atr = float(features.get("atr_5_pct") or 0.0)
    return float(min(300.0, max(30.0, atr * 10_000.0 * 1.5)))


def resolve_forecast(
    ledger: ForecastLedger,
    forecast: dict[str, Any],
    *,
    exit_price: float,
    resolved_at: datetime,
    engine: EnhancedControlPlaneEngine | None = None,
) -> dict[str, Any]:
    reference = float(forecast["reference_price"])
    realized = exit_price / reference - 1.0
    cost_fraction = float(forecast["cost_bps"]) / 10_000.0
    realized_class = CLASS_NAMES[_classify(realized, cost_fraction)]
    raw_probabilities = forecast["probabilities"]
    if isinstance(raw_probabilities, dict):
        probabilities = np.asarray(
            [float(raw_probabilities[name]) for name in CLASS_NAMES], dtype=np.float64
        )
    else:
        probabilities = np.asarray(raw_probabilities, dtype=np.float64)
    target = np.zeros(3)
    target[CLASS_INDEX[realized_class]] = 1.0
    brier = float(np.sum((probabilities - target) ** 2))
    ledger.resolve_forecast(
        forecast["forecast_id"],
        realized_return=realized,
        realized_class=realized_class,
        brier_score=brier,
        resolved_at=resolved_at,
    )
    trade = ledger.trade_for_forecast(forecast["forecast_id"])
    trade_result = None
    if trade and trade["status"] == "open" and trade["control_plane_decision"] == "authorized_paper":
        sign = 1.0 if trade["side"] == "long" else -1.0
        net = sign * realized - cost_fraction
        notional = float(trade["authorized_notional_usd"] or trade["requested_notional_usd"])
        pnl = net * notional
        if engine is not None and trade.get("position_id"):
            closed = engine.base_engine.close_position(
                str(trade["position_id"]),
                exit_price=exit_price,
                fee_usd=Decimal(str(round(notional * cost_fraction, 2))),
                reason="vertical_slice_resolution",
                now=resolved_at,
            )
            if closed.get("status") == "closed":
                pnl = float(closed["paper_pnl_usd"])
        ledger.resolve_trade(
            trade["trade_id"],
            realized_return_net=net,
            realized_pnl_usd=pnl,
            resolved_at=resolved_at,
        )
        trade_result = {
            "trade_id": trade["trade_id"],
            "side": trade["side"],
            "net_return": round(net, 8),
            "pnl_usd": round(pnl, 2),
        }
    return {
        "forecast_id": forecast["forecast_id"],
        "symbol": forecast["symbol"],
        "action": forecast["action"],
        "realized_return": round(realized, 8),
        "realized_class": realized_class,
        "brier_score": round(brier, 8),
        "trade": trade_result,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _service_locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class VerticalSliceService:
    ledger: ForecastLedger = field(default_factory=ForecastLedger)
    config: SliceConfig = field(default_factory=SliceConfig)
    engine: EnhancedControlPlaneEngine | None = None
    engine_id: str = PAPER_ENGINE_ID
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    _state_restored: bool = field(default=False, init=False, repr=False, compare=False)
    _restore_report: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)
    _engines: dict[int, EnhancedControlPlaneEngine] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.engine is None:
            self.engine = build_paper_engine(self.engine_id, config=self.config)
        self._engines = {1: self.engine}
        self._restore_paper_state()

    def _state_key(self, horizon_steps: int) -> str:
        horizon = max(1, int(horizon_steps))
        return PAPER_STATE_KEY if horizon == 1 else f"{PAPER_STATE_KEY}:h{horizon}"

    def _engine_id_for(self, horizon_steps: int) -> str:
        horizon = max(1, int(horizon_steps))
        return self.engine_id if horizon == 1 else f"{self.engine_id}:h{horizon}"

    def _engine_for(self, horizon_steps: int) -> EnhancedControlPlaneEngine:
        horizon = max(1, int(horizon_steps))
        if horizon in self._engines:
            return self._engines[horizon]
        engine = build_paper_engine(self._engine_id_for(horizon), config=self.config)
        saved = self.ledger.load_state(self._state_key(horizon))
        if saved:
            try:
                restore_paper_state(engine, saved)
            except Exception:  # noqa: BLE001 - corrupt state must not fabricate a book
                pass
        self._engines[horizon] = engine
        return engine

    def _restore_paper_state(self) -> None:
        if self.engine is None:
            self._state_restored = True
            self._restore_report = {"restored": False, "reason": "no_saved_state", "execution_permission": "none"}
            return
        engines: dict[int, EnhancedControlPlaneEngine] = {1: self.engine}
        reports: dict[str, Any] = {}
        for key in self.ledger.state_keys(PAPER_STATE_KEY):
            suffix = key.removeprefix(PAPER_STATE_KEY)
            if not suffix:
                horizon = 1
            elif suffix.startswith(":h"):
                try:
                    horizon = int(suffix[2:])
                except ValueError:
                    continue
            else:
                continue
            if horizon < 1:
                continue
            if horizon == 1:
                engine = self.engine
            else:
                engine = build_paper_engine(self._engine_id_for(horizon), config=self.config)
                engines[horizon] = engine
            state = self.ledger.load_state(key)
            if not state:
                continue
            try:
                reports[str(horizon)] = restore_paper_state(engine, state)
            except Exception as exc:  # noqa: BLE001 - corrupt state must not stop the API
                reports[str(horizon)] = {
                    "restored": False,
                    "reason": "corrupt_saved_state",
                    "error": type(exc).__name__,
                }
        self._engines = engines
        if not reports:
            self._restore_report = {
                "restored": False,
                "reason": "no_saved_state",
                "horizons": [],
                "execution_permission": "none",
            }
        else:
            self._restore_report = {
                "restored": any(report.get("restored") for report in reports.values()),
                "horizons": reports,
                "execution_permission": "none",
            }
        self._state_restored = True

    def _save_paper_state(self, now: datetime) -> None:
        for horizon, engine in self._engines.items():
            self.ledger.save_state(
                self._state_key(horizon),
                serialize_paper_state(
                    engine,
                    updated_at=now,
                    engine_id=self._engine_id_for(horizon),
                ),
                now,
            )

    def configure(
        self,
        *,
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
    ) -> SliceConfig:
        with self._lock:
            updates: dict[str, Any] = {}
            if bucket_seconds is not None:
                updates["bucket_seconds"] = int(bucket_seconds)
            if horizon_steps is not None:
                updates["horizon_steps"] = int(horizon_steps)
            if updates:
                self.config = SliceConfig(**{**self.config.__dict__, **updates})
            return self.config

    @_service_locked
    def run(
        self,
        *,
        symbols: Sequence[str] = ("BTC-USD",),
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        fetch: bool = True,
        now: datetime | None = None,
        paper: bool = True,
    ) -> dict[str, Any]:
        config = SliceConfig(
            **{
                **self.config.__dict__,
                **(
                    {"bucket_seconds": bucket_seconds}
                    if bucket_seconds is not None
                    else {}
                ),
                **(
                    {"horizon_steps": horizon_steps}
                    if horizon_steps is not None
                    else {}
                ),
            }
        )
        self.config = config
        if self.engine is None:
            self.engine = build_paper_engine(config=config)
        created_at = now or datetime.now(timezone.utc)
        run_id = "vs_" + hashlib.sha256(
            json.dumps(
                {
                    "symbols": [symbol.upper() for symbol in symbols],
                    "config": config.as_dict(),
                    "created_at": created_at.date().isoformat(),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:24]
        reports: list[dict[str, Any]] = []
        for symbol in symbols:
            reports.append(
                self._run_symbol(
                    symbol.upper(),
                    config,
                    candles=candles_by_symbol.get(symbol.upper()) if candles_by_symbol else None,
                    fetch=fetch,
                    created_at=created_at,
                    run_id=run_id,
                    paper=paper,
                )
            )
        combined = _combine_reports(reports)
        report = {
            "run_id": run_id,
            "path_id": PATH_ID,
            "created_at": created_at.isoformat(),
            "config": config.as_dict(),
            "symbols": reports,
            "metrics": combined,
            "optional_challengers": optional_gbdt_status(),
            "limitations": [
                "This is research, not investment advice or a live trading record.",
                "Brier/log loss score probabilities; paper P&L includes modeled round-trip cost but no borrow, funding, slippage, or market impact.",
                "Empirical intervals are conditional return quantiles, not guaranteed coverage.",
                "Paper positions, equity, and open authorizations are restored from the local ledger after restart. They remain a local simulation, not a venue record.",
                "Public venue candles can be delayed, revised, or unavailable; unavailable data is reported as such.",
                "Model selection includes frequency and uniform baselines. When a learned model loses out of sample, the baseline is selected and the forecast may abstain.",
            ],
            "execution_permission": "none",
        }
        self.ledger.record_run(run_id, created_at, config, report)
        if paper:
            self._save_paper_state(created_at)
        return report

    def ablate_features(
        self,
        *,
        symbol: str = "BTC-USD",
        bucket_seconds: int | None = None,
        horizon_steps: int | None = None,
        families: Sequence[str] | None = None,
        candles: list[dict[str, Any]] | None = None,
        fetch: bool = True,
        include_regimes: bool = False,
        include_session: bool = False,
        include_cross_asset: bool = False,
        reference_symbol: str | None = None,
        reference_candles: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run a read-only feature-family ablation on one symbol."""
        config = SliceConfig(
            **{
                **self.config.__dict__,
                **(
                    {"bucket_seconds": bucket_seconds}
                    if bucket_seconds is not None
                    else {}
                ),
                **(
                    {"horizon_steps": horizon_steps}
                    if horizon_steps is not None
                    else {}
                ),
            }
        )
        wanted = symbol.upper()
        source_rows = candles
        if source_rows is None and fetch:
            try:
                from atlas.marketdata.public_quotes import fetch_public_candles

                payload = fetch_public_candles(
                    wanted, config.bucket_seconds, limit=400, intended_use="training"
                )
                source_rows = _public_rows(payload)
            except DataUseDenied as exc:
                return _blocked_data_use(wanted, exc)
            except Exception as exc:  # noqa: BLE001 - report, never fill
                return {
                    "status": "unavailable",
                    "symbol": wanted,
                    "reason": type(exc).__name__,
                    "execution_permission": "none",
                }
        if not source_rows:
            return {
                "status": "unavailable",
                "symbol": wanted,
                "reason": "public_candles_unavailable",
                "execution_permission": "none",
            }
        moment = now or datetime.now(timezone.utc)
        try:
            normalized, quality = _admit_rows(source_rows, symbol=wanted, bucket_seconds=config.bucket_seconds, as_of=moment)
        except DataUseDenied as exc:
            return _blocked_data_use(wanted, exc)
        reference_wanted = (
            (reference_symbol or _default_reference_symbol(wanted)).upper()
        )
        if reference_wanted == wanted:
            reference_wanted = _default_reference_symbol(reference_wanted)
        reference_available = False
        reference_reason: str | None = None
        normalized_reference: list[Candle] = []
        reference_quality: dict[str, Any] | None = None
        if include_cross_asset:
            source_reference = reference_candles
            if source_reference is None and fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(
                        reference_wanted, config.bucket_seconds, limit=400, intended_use="training"
                    )
                    source_reference = _public_rows(payload)
                except DataUseDenied as exc:
                    return _blocked_data_use(reference_wanted, exc)
                except Exception as exc:  # noqa: BLE001 - report, never fill
                    reference_reason = type(exc).__name__
            elif source_reference is None:
                reference_reason = "reference_candles_not_supplied"
            if source_reference:
                try:
                    normalized_reference, reference_quality = _admit_rows(source_reference, symbol=reference_wanted, bucket_seconds=config.bucket_seconds, as_of=moment)
                except DataUseDenied as exc:
                    return _blocked_data_use(reference_wanted, exc)
            elif reference_reason is None:
                reference_reason = "reference_candles_unavailable"
        rows, feature_names, reference_available = build_research_feature_rows(
            normalized,
            config,
            reference_candles=normalized_reference,
            include_session=include_session,
            include_cross_asset=include_cross_asset,
        )
        rows = _relabel(
            rows,
            ROUND_TRIP_BPS["competition" if wanted.endswith("-USD") else "open_market"],
        )
        if not rows:
            return {
                "status": "insufficient_history",
                "symbol": wanted,
                "bars": len(normalized),
                "required_bars": MIN_BARS,
                "quality": quality,
                "execution_permission": "none",
            }
        selected_families = families or [
            family
            for family, members in FEATURE_FAMILIES.items()
            if any(name in feature_names for name in members)
        ]
        report = ablate_feature_families(
            rows,
            wanted,
            cost_bps=ROUND_TRIP_BPS[
                "competition" if wanted.endswith("-USD") else "open_market"
            ],
            config=config,
            feature_names=feature_names,
            families=selected_families,
            include_regimes=include_regimes,
        )
        return {
            **report,
            "as_of": (now or datetime.now(timezone.utc)).isoformat(),
            "bars": len(normalized),
            "quality": quality,
            "research_features": {
                "session_requested": include_session,
                "cross_asset_requested": include_cross_asset,
                "reference_symbol": reference_wanted if include_cross_asset else None,
                "reference_available": reference_available,
                "reference_reason": reference_reason,
                "reference_quality": reference_quality,
            },
            "read_only": True,
            "execution_permission": "none",
        }

    def ablate_multi(
        self,
        *,
        symbols: Sequence[str],
        bucket_seconds: int = 86_400,
        horizon_steps: Sequence[int] = (1,),
        families: Sequence[str] | None = None,
        include_regimes: bool = True,
        include_session: bool = False,
        include_cross_asset: bool = False,
        reference_symbol: str | None = None,
        reference_candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Measure feature families across symbols and horizons without writing.

        The matrix is bounded so one request cannot trigger an unbounded number
        of walk-forward retrainings. Each cell is still a separate purged
        walk-forward ablation against the same baseline as the single-symbol
        endpoint.
        """
        wanted = tuple(
            dict.fromkeys(
                symbol.strip().upper() for symbol in symbols if symbol.strip()
            )
        ) or ("BTC-USD",)
        horizons = tuple(
            sorted({int(step) for step in horizon_steps if 1 <= int(step) <= 24})
        ) or (1,)
        wanted = wanted[:6]
        horizons = horizons[:3]
        moment = now or datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        reference_cache: dict[str, list[dict[str, Any]] | None] = {}
        for symbol in wanted:
            candles: list[dict[str, Any]] | None = (candles_by_symbol or {}).get(symbol)
            fetch_error: str | None = None
            if candles is not None:
                candles = list(candles)
            elif fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(symbol, bucket_seconds, limit=400, intended_use="training")
                    candles = _public_rows(payload)
                except DataUseDenied as exc:
                    rows.extend({**_blocked_data_use(symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                    continue
                except Exception as exc:  # noqa: BLE001 - report, never fill
                    fetch_error = type(exc).__name__
            else:
                fetch_error = "candles_not_supplied"
            if not candles:
                for horizon in horizons:
                    rows.append(
                        {
                            "symbol": symbol,
                            "horizon_steps": horizon,
                            "status": "unavailable",
                            "reason": fetch_error or "public_candles_unavailable",
                            "execution_permission": "none",
                        }
                    )
                continue
            ref_symbol = (
                (reference_symbol or _default_reference_symbol(symbol)).upper()
            )
            if ref_symbol == symbol:
                ref_symbol = _default_reference_symbol(ref_symbol)
            ref_candles: list[dict[str, Any]] | None = None
            if include_cross_asset:
                if ref_symbol not in reference_cache:
                    source = (reference_candles_by_symbol or {}).get(ref_symbol)
                    if source is None and fetch and ref_symbol != symbol:
                        try:
                            from atlas.marketdata.public_quotes import fetch_public_candles

                            payload = fetch_public_candles(
                                ref_symbol, bucket_seconds, limit=400, intended_use="training"
                            )
                            source = _public_rows(payload)
                        except DataUseDenied as exc:
                            rows.extend({**_blocked_data_use(ref_symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                            continue
                        except Exception:  # noqa: BLE001 - report, never fill
                            source = None
                    reference_cache[ref_symbol] = source
                ref_candles = reference_cache.get(ref_symbol)
            for horizon in horizons:
                try:
                    cell = self.ablate_features(
                        symbol=symbol,
                        bucket_seconds=bucket_seconds,
                        horizon_steps=horizon,
                        families=families,
                        candles=candles,
                        fetch=False,
                        include_regimes=include_regimes,
                        include_session=include_session,
                        include_cross_asset=include_cross_asset,
                        reference_symbol=ref_symbol,
                        reference_candles=ref_candles,
                        now=moment,
                    )
                except Exception as exc:  # noqa: BLE001 - one cell must not fail the matrix
                    rows.append(
                        {
                            "symbol": symbol,
                            "horizon_steps": horizon,
                            "status": "error",
                            "error": type(exc).__name__,
                            "execution_permission": "none",
                        }
                    )
                    continue
                ablations = list(cell.get("ablations") or [])
                supported = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "removal_worsened"
                ]
                negative = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "removal_improved"
                ]
                inconclusive = [
                    item.get("family")
                    for item in ablations
                    if item.get("evidence") == "inconclusive"
                ]
                cell_status = cell.get("status")
                rows.append(
                    {
                        "symbol": symbol,
                        "horizon_steps": horizon,
                        "status": "scored" if cell_status == "measured" else cell_status,
                        "reason": cell.get("reason"),
                        "data_use": cell.get("data_use"),
                        "bars": cell.get("bars"),
                        "baseline": cell.get("baseline"),
                        "ablations": ablations,
                        "supported_families": supported,
                        "negative_families": negative,
                        "inconclusive_families": inconclusive,
                        "research_features": cell.get("research_features"),
                        "execution_permission": "none",
                    }
                )
        scored = [row for row in rows if row.get("status") == "scored"]
        return {
            "status": "blocked" if rows and all(row.get("status") == "blocked" for row in rows) else "evaluated",
            "bucket_seconds": bucket_seconds,
            "symbols": list(wanted),
            "horizons": list(horizons),
            "families": list(families or FEATURE_FAMILIES.keys()),
            "include_regimes": include_regimes,
            "include_session": include_session,
            "include_cross_asset": include_cross_asset,
            "as_of": moment.isoformat(),
            "rows": rows,
            "scored_cells": len(scored),
            "cells": len(rows),
            "notice": (
                "Cross-symbol and cross-horizon ablation matrix. Each cell retrains "
                "on purged walk-forward folds and is read-only; no forecasts, paper "
                "trades, or order permission were created. Session and cross-asset "
                "features are research candidates built only from completed "
                "timestamps and admitted reference candles; they are not in the "
                "production feature set. Regime rows use trailing volatility/trend "
                "thresholds and are descriptive, not a validated regime classifier. "
                "Small deltas are inconclusive and do not justify changing the "
                "production feature set."
            ),
            "read_only": True,
            "execution_permission": "none",
        }

    def evaluate_multi(
        self,
        *,
        symbols: Sequence[str],
        bucket_seconds: int = 86_400,
        horizon_steps: Sequence[int] = (1,),
        now: datetime | None = None,
        fetch: bool = True,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Evaluate the same slice across symbols and horizons without paper trades.

        The evaluation uses an in-memory ledger so it cannot pollute the audited
        production ledger or create paper positions. Metrics are still
        walk-forward, purged, and baseline-compared per symbol/horizon.
        """
        wanted = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
        ) or ("BTC-USD",)
        horizons = tuple(
            sorted({int(step) for step in horizon_steps if 1 <= int(step) <= 24})
        ) or (1,)
        moment = now or datetime.now(timezone.utc)
        temporary = VerticalSliceService(
            ledger=ForecastLedger(":memory:"),
            config=self.config,
        )
        rows: list[dict[str, Any]] = []
        try:
            for symbol in wanted:
                candles: list[dict[str, Any]] | None = (candles_by_symbol or {}).get(symbol)
                fetch_error: str | None = None
                if candles is not None:
                    candles = list(candles)
                elif fetch:
                    try:
                        from atlas.marketdata.public_quotes import fetch_public_candles

                        payload = fetch_public_candles(symbol, bucket_seconds, limit=400, intended_use="training")
                        candles = _public_rows(payload)
                    except DataUseDenied as exc:
                        rows.extend({**_blocked_data_use(symbol, exc), "horizon_steps": horizon} for horizon in horizons)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        fetch_error = type(exc).__name__
                else:
                    fetch_error = "candles_not_supplied"
                if not candles:
                    for horizon in horizons:
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": "unavailable",
                                "reason": fetch_error or "public_candles_unavailable",
                                "execution_permission": "none",
                            }
                        )
                    continue
                for horizon in horizons:
                    try:
                        report = temporary.run(
                            symbols=[symbol],
                            bucket_seconds=bucket_seconds,
                            horizon_steps=horizon,
                            candles_by_symbol={symbol: candles},
                            fetch=False,
                            now=moment,
                            paper=False,
                        )
                        symbol_report = (report.get("symbols") or [{}])[0]
                        walk = symbol_report.get("walk_forward") or {}
                        primary = walk.get("primary_metrics") or {}
                        baseline = walk.get("frequency_baseline") or {}
                        challenger = walk.get("xgboost_challenger") or {}
                        challenger_metrics = challenger.get("model") or {}
                        selected = walk.get("primary_model_family") or (
                            symbol_report.get("model") or {}
                        ).get("model_family")
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": symbol_report.get("status"),
                                "reason": symbol_report.get("reason"),
                                "data_use": symbol_report.get("data_use"),
                                "bars": symbol_report.get("bars"),
                                "selected_model_family": selected,
                                "walk_forward_status": walk.get("status"),
                                "brier_score": primary.get("brier_score"),
                                "log_loss": primary.get("log_loss"),
                                "accuracy": primary.get("accuracy"),
                                "coverage": primary.get("coverage"),
                                "rows": primary.get("rows"),
                                "taken": primary.get("taken"),
                                "direction_accuracy": primary.get("direction_accuracy"),
                                "frequency_brier_score": baseline.get("brier_score"),
                                "challenger_status": challenger.get("status"),
                                "challenger_brier_score": challenger_metrics.get("brier_score"),
                                "baseline_selected": selected in {"frequency_baseline", "uniform_baseline"},
                                "execution_permission": "none",
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 - one cell must not fail the matrix
                        rows.append(
                            {
                                "symbol": symbol,
                                "horizon_steps": horizon,
                                "status": "error",
                                "error": type(exc).__name__,
                                "execution_permission": "none",
                            }
                        )
        finally:
            temporary.ledger.close()
        scored = [row for row in rows if row.get("walk_forward_status") == "scored"]
        return {
            "status": "blocked" if rows and all(row.get("status") == "blocked" for row in rows) else "evaluated",
            "bucket_seconds": bucket_seconds,
            "symbols": list(wanted),
            "horizons": list(horizons),
            "as_of": moment.isoformat(),
            "rows": rows,
            "scored_cells": len(scored),
            "cells": len(rows),
            "notice": (
                "Evaluation-only matrix. Each cell uses purged walk-forward evidence against "
                "frequency and uniform baselines. No paper trades were created and no order permission exists."
            ),
            "execution_permission": "none",
        }

    def _run_symbol(
        self,
        symbol: str,
        config: SliceConfig,
        *,
        candles: list[dict[str, Any]] | None,
        fetch: bool,
        created_at: datetime,
        run_id: str,
        paper: bool,
    ) -> dict[str, Any]:
        track = "competition" if symbol.endswith("-USD") else "open_market"
        cost_bps = ROUND_TRIP_BPS[track]
        source_rows = candles
        fetch_error = None
        if source_rows is None:
            if not fetch:
                return _unavailable(symbol, track, "candles_not_supplied")
            try:
                from atlas.marketdata.public_quotes import fetch_public_candles

                payload = fetch_public_candles(symbol, config.bucket_seconds, limit=400, intended_use="training")
                if payload:
                    source_rows = _public_rows(payload)
            except DataUseDenied as exc:
                return {**_blocked_data_use(symbol, exc), "track": track}
            except Exception as exc:  # network/library failure is reported, never filled
                fetch_error = type(exc).__name__
        if not source_rows:
            return _unavailable(symbol, track, fetch_error or "public_candles_unavailable")
        try:
            normalized, quality = _admit_rows(source_rows, symbol=symbol, bucket_seconds=config.bucket_seconds, as_of=created_at)
        except DataUseDenied as exc:
            return {**_blocked_data_use(symbol, exc), "track": track}
        if len(normalized) < MIN_BARS:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "bars": len(normalized),
                "required_bars": MIN_BARS,
                "execution_permission": "none",
            }
        rows = _relabel(build_feature_rows(normalized, config), cost_bps)
        resolved_rows = [row for row in rows if row.resolved]
        if not resolved_rows:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "bars": len(normalized),
                "execution_permission": "none",
            }
        dataset_hash = _dataset_fingerprint(resolved_rows, symbol, config)
        walk = purged_walk_forward(resolved_rows, symbol, cost_bps=cost_bps, config=config)
        softmax = fit_softmax(
            [row.features for row in resolved_rows],
            [int(row.label) for row in resolved_rows],
            l2=config.l2,
            epochs=config.epochs,
            learning_rate=config.learning_rate,
            seed=config.seed,
            dataset_hash=dataset_hash,
        )
        model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel = softmax
        primary_family = str(walk.get("primary_model_family") or MODEL_FAMILY)
        fallback_reason = None
        if primary_family in {"frequency_baseline", "uniform_baseline"}:
            probabilities_for_baseline = (
                _frequency_baseline([int(row.label) for row in resolved_rows])
                if primary_family == "frequency_baseline"
                else np.full(3, 1.0 / 3.0, dtype=np.float64)
            )
            model = ConstantProbabilityModel(
                model_id=f"{primary_family}:{dataset_hash[:12]}:baseline",
                model_family=primary_family,
                probabilities=tuple(float(value) for value in probabilities_for_baseline),  # type: ignore[arg-type]
                feature_names=FEATURE_NAMES,
                training_rows=len(resolved_rows),
                dataset_hash=dataset_hash,
            )
        elif primary_family == XGBOOST_FAMILY:
            xgb_model = fit_xgboost(
                [row.features for row in resolved_rows],
                [int(row.label) for row in resolved_rows],
                seed=config.seed,
                dataset_hash=dataset_hash,
            )
            if xgb_model is not None:
                model = xgb_model
            else:
                primary_family = MODEL_FAMILY
                fallback_reason = "xgboost_final_fit_failed"
        walk["selected_model_id"] = model.model_id
        walk["selected_model_family"] = primary_family
        walk["selection"] = {
            **dict(walk.get("selection") or {}),
            "primary_model_family": primary_family,
            "selected_model_id": model.model_id,
            "fallback_reason": fallback_reason,
        }
        self.ledger.save_model(model, symbol, created_at)
        latest = rows[-1] if rows else None
        if latest is None:
            return {
                "symbol": symbol,
                "track": track,
                "status": "insufficient_history",
                "quality": quality,
                "execution_permission": "none",
            }
        probabilities = model.predict_proba(latest.features)
        action, reason, edge = _action(probabilities, config)
        expected = _expected_return(resolved_rows, int(probabilities.argmax()))
        interval_low, interval_high = _return_interval(resolved_rows, int(probabilities.argmax()))
        feature_map = {name: value for name, value in zip(FEATURE_NAMES, latest.features)}
        contributions = _contributions(model, latest.features, int(probabilities.argmax()), feature_map)
        forecast_id = _forecast_id(symbol, model.model_id, latest.decision_time, latest.target_time, track)
        forecast = {
            "forecast_id": forecast_id,
            "run_id": run_id,
            "symbol": symbol,
            "track": track,
            "model_id": model.model_id,
            "model_revision": dataset_hash[:16],
            "dataset_hash": dataset_hash,
            "decision_time": latest.decision_time.isoformat(),
            "target_time": latest.target_time.isoformat(),
            "bucket_seconds": config.bucket_seconds,
            "horizon_steps": config.horizon_steps,
            "reference_price": latest.reference_price,
            "features_json": json.dumps(feature_map, sort_keys=True),
            "probabilities_json": json.dumps(
                {name: round(float(prob), 8) for name, prob in zip(CLASS_NAMES, probabilities)},
                sort_keys=True,
            ),
            "predicted_class": CLASS_NAMES[int(probabilities.argmax())],
            "action": action,
            "action_reason": reason,
            "confidence": round(float(probabilities.max()), 8),
            "edge": round(float(edge), 8),
            "interval_low": interval_low,
            "interval_high": interval_high,
            "cost_bps": cost_bps,
            "status": "open",
            "execution_permission": "none",
        }
        inserted = self.ledger.insert_forecast(forecast)
        trade = None
        if inserted and paper:
            forecast_for_trade = {
                **forecast,
                "features": feature_map,
                "probabilities": [float(value) for value in probabilities],
                "expected_return": expected,
            }
            trade_payload = execute_forecast_paper_trade(
                forecast_for_trade,
                self._engine_for(config.horizon_steps),
                config,
            )
            self.ledger.insert_trade(trade_payload)
            trade = trade_payload
        return {
            "symbol": symbol,
            "track": track,
            "status": "forecast_recorded" if inserted else "duplicate_forecast_skipped",
            "quality": quality,
            "bars": len(normalized),
            "dataset_hash": dataset_hash,
            "model": {
                "model_id": model.model_id,
                "model_family": primary_family,
                "training_rows": model.training_rows,
                "training_loss": getattr(
                    model, "training_loss", getattr(model, "training_log_loss", None)
                ),
                "importance": model.importance()[:6],
            },
            "chart": _chart_payload(
                normalized,
                latest,
                probabilities,
                action,
                forecast_id,
                interval=(interval_low, interval_high),
                limit=160,
            ),
            "walk_forward": walk,
            "forecast": {
                **forecast,
                "features": feature_map,
                "probabilities": {
                    name: round(float(prob), 8) for name, prob in zip(CLASS_NAMES, probabilities)
                },
                "expected_return": expected,
                "feature_contributions": contributions,
            },
            "paper_trade": trade,
            "execution_permission": "none",
        }

    def _forecast_horizon(self, forecast: dict[str, Any]) -> int:
        raw = forecast.get("horizon_steps")
        if raw is not None:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        bucket = self.config.bucket_seconds
        try:
            bucket = max(1, int(forecast.get("bucket_seconds") or bucket))
            delta = _utc(forecast["target_time"]) - _utc(forecast["decision_time"])
            return max(1, int(round(delta.total_seconds() / bucket)))
        except (KeyError, TypeError, ValueError):
            return 1

    @_service_locked
    def resolve(
        self,
        *,
        symbols: Sequence[str] = ("BTC-USD",),
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        fetch: bool = True,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        now = as_of or datetime.now(timezone.utc)
        resolutions: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        for symbol in symbols:
            symbol = symbol.upper()
            source_rows = candles_by_symbol.get(symbol) if candles_by_symbol else None
            if source_rows is None and fetch:
                try:
                    from atlas.marketdata.public_quotes import fetch_public_candles

                    payload = fetch_public_candles(symbol, self.config.bucket_seconds, limit=400, intended_use="training")
                    if payload:
                        source_rows = _public_rows(payload)
                except DataUseDenied as exc:
                    blocked.append(_blocked_data_use(symbol, exc))
                    continue
                except Exception:
                    source_rows = None
            if not source_rows:
                continue
            try:
                normalized, _ = _admit_rows(source_rows, symbol=symbol, bucket_seconds=self.config.bucket_seconds, as_of=now)
            except DataUseDenied as exc:
                blocked.append(_blocked_data_use(symbol, exc))
                continue
            by_time = {candle.available_at: candle.close for candle in normalized}
            for forecast in self.ledger.open_forecasts(now):
                if forecast["symbol"] != symbol:
                    continue
                target_time = _utc(forecast["target_time"])
                exact = by_time.get(target_time)
                if exact is None:
                    later = [stamp for stamp in by_time if stamp >= target_time]
                    if not later:
                        continue
                    exact = by_time[min(later)]
                horizon = self._forecast_horizon(forecast)
                resolutions.append(
                    resolve_forecast(
                        self.ledger,
                        forecast,
                        exit_price=exact,
                        resolved_at=now,
                        engine=self._engine_for(horizon),
                    )
                )
        if resolutions:
            self._save_paper_state(now)
        return {
            "resolved": resolutions,
            "blocked": blocked,
            "count": len(resolutions),
            "as_of": now.isoformat(),
            "execution_permission": "none",
        }

    def status(self) -> dict[str, Any]:
        summary = self.ledger.summary()
        summary["research_inputs"] = {
            "feature_names": list(FEATURE_NAMES),
            "classes": list(CLASS_NAMES),
            "optional_challengers": optional_gbdt_status(),
            "execution_permission": "none",
        }
        summary["paper_state"] = {
            "engine_id": self.engine_id,
            **self._restore_report,
        }
        summary["paper_account"] = self._paper_account_snapshot()
        return summary

    def _paper_account_snapshot(self) -> dict[str, Any]:
        if not self._engines:
            return {
                "status": "unavailable",
                "execution_permission": "none",
            }
        books: dict[str, Any] = {}
        for horizon, engine in sorted(self._engines.items()):
            base = engine.base_engine
            books[str(horizon)] = {
                "current_equity_usd": float(base.current_equity_usd),
                "high_water_mark_usd": float(base.high_water_mark_usd),
                "open_positions": sum(
                    1 for position in base.open_positions if position.status == "open"
                ),
                "gross_notional_usd": float(base.gross_notional_usd),
                "correlated_exposure_usd": float(base.correlated_exposure_usd),
                "sector_exposure_usd": float(base.sector_exposure_usd),
                "kill_switch_engaged": base.kill_switch_engaged,
            }
        return {
            "status": "available",
            "current_equity_usd": round(
                sum(book["current_equity_usd"] for book in books.values()), 6
            ),
            "high_water_mark_usd": round(
                sum(book["high_water_mark_usd"] for book in books.values()), 6
            ),
            "starting_equity_usd": float(self.config.starting_equity_usd) * len(books),
            "open_positions": sum(book["open_positions"] for book in books.values()),
            "gross_notional_usd": round(
                sum(book["gross_notional_usd"] for book in books.values()), 6
            ),
            "correlated_exposure_usd": round(
                sum(book["correlated_exposure_usd"] for book in books.values()), 6
            ),
            "sector_exposure_usd": round(
                sum(book["sector_exposure_usd"] for book in books.values()), 6
            ),
            "kill_switch_engaged": any(
                book["kill_switch_engaged"] for book in books.values()
            ),
            "books": books,
            "restored_from_disk": bool(self._restore_report.get("restored")),
            "execution_permission": "none",
        }

    def forecasts(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.ledger.recent_forecasts(limit)

    def paper_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.ledger.recent_trades(limit)

    def chart(self, symbol: str, limit: int = 160) -> dict[str, Any]:
        wanted = symbol.upper()
        for report in self.ledger.latest_run_reports():
            for row in report.get("symbols") or []:
                if str(row.get("symbol", "")).upper() != wanted:
                    continue
                chart = row.get("chart")
                if not isinstance(chart, dict):
                    break
                bars = list(chart.get("bars") or [])[-max(20, min(int(limit), 500)) :]
                return {
                    **chart,
                    "bars": bars,
                    "run_id": report.get("run_id"),
                    "created_at": report.get("created_at"),
                    "execution_permission": "none",
                }
        return {
            "symbol": wanted,
            "status": "unavailable",
            "bars": [],
            "markers": [],
                "reason": "No recorded run contains admitted research bars for this symbol.",
            "execution_permission": "none",
        }

    def lucky_moments(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.ledger.recent_forecasts(500, status="resolved")
        lucky: list[dict[str, Any]] = []
        for row in rows:
            if row.get("action") not in ("long", "short") or row.get("realized_return") is None:
                continue
            sign = 1.0 if row["action"] == "long" else -1.0
            net_gross = sign * float(row["realized_return"])
            if net_gross <= 0:
                continue
            interval_low = float(row.get("interval_low") or 0.0)
            interval_high = float(row.get("interval_high") or 0.0)
            reason = None
            if float(row.get("confidence") or 0.0) < 0.55:
                reason = "low_confidence_win"
            elif net_gross > abs(interval_high) * 1.5 and interval_high > 0:
                reason = "outside_expected_interval"
            if reason:
                lucky.append(
                    {
                        "forecast_id": row["forecast_id"],
                        "symbol": row["symbol"],
                        "decision_time": row["decision_time"],
                        "action": row["action"],
                        "confidence": row["confidence"],
                        "edge": row["edge"],
                        "realized_return": row["realized_return"],
                        "signed_gross_return": round(net_gross, 8),
                        "interval": [interval_low, interval_high],
                        "reason": reason,
                        "caution": "A favorable outcome with weak confidence may be luck, not repeatable skill.",
                    }
                )
        return lucky[: max(1, min(int(limit), 100))]


def _expected_return(rows: Sequence[FeatureRow], class_index: int) -> float:
    values = [float(row.forward_return) for row in rows if row.label == class_index and row.forward_return is not None]
    if not values:
        values = [float(row.forward_return) for row in rows if row.forward_return is not None]
    return round(sum(values) / len(values), 8) if values else 0.0


def _return_interval(rows: Sequence[FeatureRow], class_index: int) -> tuple[float | None, float | None]:
    values = sorted(float(row.forward_return) for row in rows if row.label == class_index and row.forward_return is not None)
    if len(values) < 5:
        values = sorted(float(row.forward_return) for row in rows if row.forward_return is not None)
    if len(values) < 5:
        return None, None
    low = values[int(0.05 * (len(values) - 1))]
    high = values[int(0.95 * (len(values) - 1))]
    return round(low, 8), round(high, 8)


def _contributions(
    model: SoftmaxModel | XGBoostModel | ConstantProbabilityModel,
    features: Sequence[float],
    class_index: int,
    feature_map: dict[str, float],
) -> list[dict[str, Any]]:
    if isinstance(model, XGBoostModel):
        return model.explain(features, class_index, feature_map)
    if isinstance(model, ConstantProbabilityModel):
        return []
    mean = np.asarray(model.mean)
    scale = np.asarray(model.scale)
    weights = np.asarray(model.weights)[:, class_index]
    normalized = (np.asarray(features) - mean) / scale
    contributions = normalized * weights
    order = np.argsort(-np.abs(contributions))
    return [
        {
            "feature": FEATURE_NAMES[int(index)],
            "value": round(float(feature_map[FEATURE_NAMES[int(index)]]), 8),
            "standardized": round(float(normalized[int(index)]), 6),
            "coefficient": round(float(weights[int(index)]), 6),
            "contribution": round(float(contributions[int(index)]), 8),
            "method": "linear_logit",
        }
        for index in order[:6]
    ]


def _chart_payload(
    candles: Sequence[Candle],
    latest: FeatureRow,
    probabilities: np.ndarray,
    action: str,
    forecast_id: str,
    *,
    interval: tuple[float | None, float | None],
    limit: int,
) -> dict[str, Any]:
    window = list(candles)[-max(20, min(int(limit), 500)) :]
    return {
        "symbol": latest and window[-1].symbol if window else None,
        "bucket_seconds": (
            (window[-1].timestamp - window[-2].timestamp).total_seconds()
            if len(window) > 1
            else None
        ),
        "bars": [
            {
                "time": candle.available_at.isoformat(),
                "open": round(candle.open, 8),
                "high": round(candle.high, 8),
                "low": round(candle.low, 8),
                "close": round(candle.close, 8),
                "volume": round(candle.volume, 8),
            }
            for candle in window
        ],
        "markers": [
            {
                "forecast_id": forecast_id,
                "time": latest.decision_time.isoformat(),
                "target_time": latest.target_time.isoformat(),
                "price": round(latest.reference_price, 8),
                "action": action,
                "predicted_class": CLASS_NAMES[int(probabilities.argmax())],
                "confidence": round(float(probabilities.max()), 8),
                "probabilities": {
                    name: round(float(prob), 8)
                    for name, prob in zip(CLASS_NAMES, probabilities)
                },
                "interval_low": interval[0],
                "interval_high": interval[1],
            }
        ],
        "notice": (
            "Bars are the research observations used by the model. Data-use admission is reported separately. The marker "
            "is the recorded decision time, not an exchange-native TradingView marker."
        ),
        "execution_permission": "none",
    }


def _unavailable(symbol: str, track: str, reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "track": track,
        "status": "unavailable",
        "reason": reason,
        "notice": "No forecast was fabricated from missing or unauthorized data.",
        "execution_permission": "none",
    }


def _combine_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        report["walk_forward"]
        for report in reports
        if report.get("walk_forward", {}).get("status") == "scored"
    ]
    if not scored:
        return {
            "status": "insufficient_history",
            "symbols_scored": 0,
            "notice": "No symbol had enough purged walk-forward rows to score.",
        }
    selected = [
        (item.get("primary_model_family") or "softmax_logistic", item.get("primary_metrics") or item["model"])
        for item in scored
    ]
    rows = sum(int(metrics["rows"]) for _, metrics in selected)
    brier = sum(float(metrics["brier_score"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    log_loss = sum(float(metrics["log_loss"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    accuracy = sum(float(metrics["accuracy"]) * int(metrics["rows"]) for _, metrics in selected) / rows
    taken = sum(int(metrics["taken"]) for _, metrics in selected)
    hits = sum(int(metrics["direction_hits"]) for _, metrics in selected)
    families: dict[str, int] = {}
    for family, _ in selected:
        families[family] = families.get(family, 0) + 1
    return {
        "status": "scored",
        "symbols_scored": len(selected),
        "selected_model_families": families,
        "rows": rows,
        "brier_score": round(brier, 8),
        "log_loss": round(log_loss, 8),
        "accuracy": round(accuracy, 6),
        "coverage": round(taken / rows, 6) if rows else 0.0,
        "taken": taken,
        "direction_accuracy": round(hits / taken, 6) if taken else None,
        "notice": (
            "Aggregated selected-model metrics across symbols with unequal row counts. "
            "Baselines can win; a learned model that loses out of sample is not selected. "
            "Inspect each symbol before drawing conclusions."
        ),
    }


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _scheduler_horizons() -> tuple[int, ...]:
    raw = os.environ.get("ATLAS_VERTICAL_SLICE_HORIZONS", "1")
    horizons: set[int] = set()
    for item in raw.split(","):
        try:
            horizon = int(item.strip())
        except (TypeError, ValueError):
            continue
        if 1 <= horizon <= 24:
            horizons.add(horizon)
    return tuple(sorted(horizons)) or (1,)


def _scheduler_settings() -> tuple[tuple[str, ...], int, int, int]:
    raw = os.environ.get(
        "ATLAS_VERTICAL_SLICE_SYMBOLS",
        "BTC-USD,ETH-USD,SOL-USD,SPY,QQQ,NVDA,AAPL,MSFT,TSLA",
    )
    symbols = tuple(
        symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()
    ) or ("BTC-USD",)
    return (
        symbols,
        _env_int("ATLAS_VERTICAL_SLICE_BUCKET_SECONDS", 86_400),
        _env_int("ATLAS_VERTICAL_SLICE_POLL_SECONDS", 300),
        _env_int("ATLAS_VERTICAL_SLICE_INITIAL_DELAY_SECONDS", 60),
    )


class VerticalSliceScheduler:
    """Check completed public bars and run/resolve the slice at most once per bar."""

    def __init__(
        self,
        service: VerticalSliceService | None = None,
        *,
        symbols: Sequence[str] | None = None,
        bucket_seconds: int | None = None,
        horizons: Sequence[int] | None = None,
        poll_seconds: int | None = None,
        initial_delay_seconds: int | None = None,
    ) -> None:
        defaults = _scheduler_settings()
        self.service = service or get_vertical_slice_service()
        self.symbols = tuple(symbols or defaults[0])
        self.horizons = tuple(
            sorted({max(1, min(int(step), 24)) for step in (horizons or _scheduler_horizons())})
        ) or (1,)
        self.bucket_seconds = int(bucket_seconds or defaults[1])
        self.poll_seconds = int(poll_seconds or defaults[2])
        self.initial_delay_seconds = int(initial_delay_seconds if initial_delay_seconds is not None else defaults[3])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._process_lock_handle: Any | None = None
        saved = self.service.ledger.load_state(SCHEDULER_STATE_KEY) or {}
        self._state: dict[str, Any] = {
            "symbols": list(self.symbols),
            "bucket_seconds": self.bucket_seconds,
            "horizons": list(self.horizons),
            "poll_seconds": self.poll_seconds,
            "last_check_at": saved.get("last_check_at"),
            "last_bar_at": saved.get("last_bar_at"),
            "last_run_at": saved.get("last_run_at"),
            "runs": int(saved.get("runs") or 0),
            "resolutions": int(saved.get("resolutions") or 0),
            "skips": int(saved.get("skips") or 0),
            "errors": int(saved.get("errors") or 0),
            "last_error": saved.get("last_error"),
            "execution_permission": "none",
        }

    def _scheduler_lock_path(self) -> Path | None:
        path = self.service.ledger.path
        if str(path) == ":memory:":
            return None
        return path.with_name(f"{path.name}.scheduler.lock")

    def _acquire_process_lock(self) -> bool:
        if self._process_lock_handle is not None:
            return True
        lock_path = self._scheduler_lock_path()
        if lock_path is None:
            return True
        handle = None
        try:
            handle = open(lock_path, "a+b")
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if handle is not None:
                handle.close()
            return False
        self._process_lock_handle = handle
        return True

    def _release_process_lock(self) -> None:
        handle = self._process_lock_handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
            self._process_lock_handle = None

    def tick(
        self,
        *,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
    ) -> dict[str, Any]:
        leased = self._process_lock_handle is None
        if not self._acquire_process_lock():
            return {
                **self.status(),
                "status": "skipped",
                "reason": "scheduler_lock_held_elsewhere",
                "details": [],
            }
        try:
            return self._tick_unlocked(
                candles_by_symbol=candles_by_symbol,
                now=now,
                fetch=fetch,
            )
        finally:
            if leased and not self.is_running():
                self._release_process_lock()

    def _tick_unlocked(
        self,
        *,
        candles_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        now: datetime | None = None,
        fetch: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            moment = now or datetime.now(timezone.utc)
            self.service.configure(bucket_seconds=self.bucket_seconds)
            runs = resolutions = skips = errors = 0
            last_bar: datetime | None = None
            last_error: str | None = None
            details: list[dict[str, Any]] = []
            for symbol in self.symbols:
                symbol = symbol.upper()
                rows = (candles_by_symbol or {}).get(symbol)
                if rows is None and fetch:
                    try:
                        from atlas.marketdata.public_quotes import fetch_public_candles

                        payload = fetch_public_candles(symbol, self.bucket_seconds, limit=400, intended_use="training")
                        rows = _public_rows(payload)
                    except DataUseDenied as exc:
                        skips += 1
                        details.append(_blocked_data_use(symbol, exc))
                        continue
                    except Exception as exc:  # noqa: BLE001 - one symbol must not stop the loop
                        errors += 1
                        last_error = f"{symbol}:{type(exc).__name__}"
                        details.append({"symbol": symbol, "status": "fetch_error", "error": type(exc).__name__})
                        continue
                if not rows:
                    skips += 1
                    details.append({"symbol": symbol, "status": "no_candles"})
                    continue
                try:
                    normalized, quality = _admit_rows(rows, symbol=symbol, bucket_seconds=self.bucket_seconds, as_of=moment)
                except DataUseDenied as exc:
                    skips += 1
                    details.append(_blocked_data_use(symbol, exc))
                    continue
                if not normalized:
                    skips += 1
                    details.append({"symbol": symbol, "status": "no_usable_candles", "quality": quality})
                    continue
                available_at = normalized[-1].available_at
                if last_bar is None or available_at > last_bar:
                    last_bar = available_at
                for horizon in self.horizons:
                    latest = self.service.ledger.latest_forecast_decision(symbol, horizon)
                    already_done = latest is not None and _utc(latest) >= available_at
                    if not already_done:
                        try:
                            report = self.service.run(
                                symbols=[symbol],
                                bucket_seconds=self.bucket_seconds,
                                horizon_steps=horizon,
                                candles_by_symbol={symbol: rows},
                                fetch=False,
                                now=moment,
                            )
                            runs += 1
                            symbol_report = (report.get("symbols") or [{}])[0]
                            details.append(
                                {
                                    "symbol": symbol,
                                    "horizon": horizon,
                                    "status": "ran",
                                    "result": symbol_report.get("status"),
                                    "bar_at": available_at.isoformat(),
                                }
                            )
                        except Exception as exc:  # noqa: BLE001
                            errors += 1
                            last_error = f"{symbol}:h{horizon}:{type(exc).__name__}"
                            details.append(
                                {
                                    "symbol": symbol,
                                    "horizon": horizon,
                                    "status": "run_error",
                                    "error": type(exc).__name__,
                                }
                            )
                    else:
                        skips += 1
                        details.append(
                            {
                                "symbol": symbol,
                                "horizon": horizon,
                                "status": "already_processed",
                                "bar_at": available_at.isoformat(),
                            }
                        )
                try:
                    resolution = self.service.resolve(
                        symbols=[symbol],
                        candles_by_symbol={symbol: rows},
                        fetch=False,
                        as_of=moment,
                    )
                    resolutions += int(resolution.get("count") or 0)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    last_error = f"{symbol}:{type(exc).__name__}"
                    details.append({"symbol": symbol, "status": "resolve_error", "error": type(exc).__name__})
            self._state.update(
                {
                    "symbols": list(self.symbols),
                    "bucket_seconds": self.bucket_seconds,
                    "horizons": list(self.horizons),
                    "poll_seconds": self.poll_seconds,
                    "last_check_at": moment.isoformat(),
                    "last_bar_at": last_bar.isoformat() if last_bar else self._state.get("last_bar_at"),
                    "last_run_at": moment.isoformat() if runs else self._state.get("last_run_at"),
                    "runs": int(self._state.get("runs") or 0) + runs,
                    "resolutions": int(self._state.get("resolutions") or 0) + resolutions,
                    "skips": int(self._state.get("skips") or 0) + skips,
                    "errors": int(self._state.get("errors") or 0) + errors,
                    "last_error": last_error or self._state.get("last_error"),
                    "execution_permission": "none",
                }
            )
            self.service.ledger.save_state(SCHEDULER_STATE_KEY, self._state, moment)
            return {**self._state, "details": details, "running": self.is_running()}

    def __tick_safely(self) -> None:
        try:
            self.tick()
        except Exception as exc:  # noqa: BLE001 - the background loop must survive
            with self._lock:
                self._state["errors"] = int(self._state.get("errors") or 0) + 1
                self._state["last_error"] = type(exc).__name__
                self._state["last_check_at"] = datetime.now(timezone.utc).isoformat()
                self.service.ledger.save_state(
                    SCHEDULER_STATE_KEY, self._state, datetime.now(timezone.utc)
                )

    def _loop(self) -> None:
        if self.initial_delay_seconds and self._stop.wait(self.initial_delay_seconds):
            return
        while not self._stop.is_set():
            self.__tick_safely()
            if self._stop.wait(self.poll_seconds):
                break

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                if not self._acquire_process_lock():
                    self._state["errors"] = int(self._state.get("errors") or 0) + 1
                    self._state["last_error"] = "scheduler_lock_held_elsewhere"
                    return self.status()
                if self._state.get("last_error") == "scheduler_lock_held_elsewhere":
                    self._state["last_error"] = None
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._loop,
                    name="vertical-slice-scheduler",
                    daemon=True,
                )
                try:
                    self._thread.start()
                except Exception:
                    self._thread = None
                    self._release_process_lock()
                    raise
        return self.status()

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._release_process_lock()
        return self.status()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            **self._state,
            "running": self.is_running(),
            "initial_delay_seconds": self.initial_delay_seconds,
            "execution_permission": "none",
        }


_SERVICE: VerticalSliceService | None = None
_SERVICE_LOCK = threading.Lock()
_SCHEDULER: VerticalSliceScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def get_vertical_slice_service() -> VerticalSliceService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = VerticalSliceService()
        return _SERVICE


def get_vertical_slice_scheduler() -> VerticalSliceScheduler:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = VerticalSliceScheduler(get_vertical_slice_service())
        return _SCHEDULER
