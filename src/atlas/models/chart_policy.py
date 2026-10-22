"""Chart-bar policy. Triple-barrier labels, a purged walk-forward, and a paper signal.

LightGBM and XGBoost are not installed. The fit is a causal decision stump on the
training fold. The signal cannot submit an order.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from atlas.features.pine_features import average_true_range, momentum_divergence, volatility_squeeze, volume_delta, vwap_bands
from atlas.models.self_training import TripleBarrierSample, build_purged_embargoed_splits
from atlas.strategies.base import StrategySignal

PATH_ID = "chart-policy:v1"


def _label_bar(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    index: int,
    atr: float,
    horizon: int,
) -> tuple[int, int, str, float]:
    entry = float(closes[index])
    upper = entry + 1.5 * atr
    lower = entry - 1.0 * atr
    last = min(len(closes) - 1, index + horizon)
    for cursor in range(index + 1, last + 1):
        if float(highs[cursor]) >= upper and float(lows[cursor]) <= lower:
            return 0, cursor, "lower_stop", lower
        if float(highs[cursor]) >= upper:
            return 1, cursor, "upper_profit", upper
        if float(lows[cursor]) <= lower:
            return -1, cursor, "lower_stop", lower
    return 0, last, "vertical_expiry", float(closes[last])


def _stump(features: list[list[float]], labels: list[int]) -> tuple[int, float, float, float]:
    """One feature threshold. Returns feature index, threshold, left rate, right rate."""
    best: tuple[float, int, float, float, float] | None = None
    positives = sum(1 for label in labels if label == 1)
    for feature_index in range(len(features[0])):
        column = [row[feature_index] for row in features]
        threshold = sorted(column)[len(column) // 2]
        left = [labels[i] for i, value in enumerate(column) if value <= threshold]
        right = [labels[i] for i, value in enumerate(column) if value > threshold]
        if not left or not right:
            continue
        left_rate = sum(1 for label in left if label == 1) / len(left)
        right_rate = sum(1 for label in right if label == 1) / len(right)
        error = abs(left_rate - (sum(1 for label in left if label == 1) / len(left)))
        del error
        impurity = abs(left_rate - 0.5) + abs(right_rate - 0.5)
        if best is None or impurity > best[0]:
            best = (impurity, feature_index, threshold, left_rate, right_rate)
    if best is None:
        rate = positives / len(labels) if labels else 0.5
        return 0, 0.0, rate, rate
    return best[1], best[2], best[3], best[4]


def _probability(row: list[float], stump: tuple[int, float, float, float]) -> float:
    feature_index, threshold, left_rate, right_rate = stump
    return left_rate if row[feature_index] <= threshold else right_rate


def _cross_entropy(probability: float, label: int) -> float:
    clipped = min(1.0 - 1e-6, max(1e-6, probability))
    target = 1.0 if label == 1 else 0.0
    return -(target * math.log(clipped) + (1.0 - target) * math.log(1.0 - clipped))


def train_chart_policy(
    candles: list[dict[str, Any]],
    *,
    symbol: str = "BTC-USD",
    horizon_bars: int = 30,
    embargo_bars: int = 5,
    drawdown_penalty: float = 0.25,
) -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in candles]
    highs = [float(bar["high"]) for bar in candles]
    lows = [float(bar["low"]) for bar in candles]
    opens = [float(bar["open"]) for bar in candles]
    volumes = [float(bar.get("volume") or 0.0) for bar in candles]
    hold = StrategySignal(
        strategy_id=PATH_ID,
        symbol=symbol,
        direction="HOLD",
        target_conviction=0.5,
        suggested_stop_loss=max(0.0, closes[-1] * 0.99) if closes else 1.0,
        suggested_take_profit=closes[-1] * 1.01 if closes else 1.0,
        reference_price=closes[-1] if closes else 1.0,
        target_entry_price=closes[-1] if closes else 1.0,
        rationale="Not enough closed bars for a purged triple-barrier fit.",
        execution_permission="none",
    )
    if len(closes) < horizon_bars + 40:
        return {
            "path_id": PATH_ID,
            "status": "insufficient_bars",
            "signal": hold.model_dump(mode="json"),
            "orders_submitted": 0,
            "execution_permission": "none",
        }

    atr = average_true_range(highs, lows, closes)
    bands = vwap_bands(highs, lows, closes, volumes)
    squeeze = volatility_squeeze(highs, lows, closes)
    momentum = momentum_divergence(closes)
    delta = volume_delta(opens, closes, volumes)
    samples: list[TripleBarrierSample] = []
    feature_rows: list[list[float]] = []
    anchor = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(30, len(closes) - horizon_bars):
        width = atr[index]
        if width is None or width <= 0 or bands["vwap"][index] is None:
            continue
        label, touch, hit, exit_price = _label_bar(highs, lows, closes, index, float(width), horizon_bars)
        entry = closes[index]
        samples.append(
            TripleBarrierSample(
                sample_index=index,
                barrier_touch_index=touch,
                entry_time=anchor + timedelta(minutes=index),
                barrier_touch_time=anchor + timedelta(minutes=touch),
                entry_price=entry,
                exit_price=max(exit_price, 1e-8),
                atr_fraction=max(float(width) / entry, 1e-6),
                upper_barrier_price=entry + 1.5 * float(width),
                lower_barrier_price=max(1e-8, entry - 1.0 * float(width)),
                label=label,  # type: ignore[arg-type]
                barrier_hit=hit,  # type: ignore[arg-type]
                realized_return=(exit_price - entry) / entry,
                execution_permission="none",
            )
        )
        feature_rows.append(
            [
                float(bands["vwap"][index]) / entry - 1.0,
                float(squeeze["atr_ratio"][index] or 0.0),
                float(squeeze["squeeze"][index] or 0),
                float(momentum["rsi"][index] or 50.0) / 100.0,
                float(momentum["rsi_divergence"][index] or 0),
                float(delta["rolling_delta"][index] or 0.0) / max(entry, 1.0),
            ]
        )
    if len(samples) < 12:
        return {
            "path_id": PATH_ID,
            "status": "insufficient_bars",
            "signal": hold.model_dump(mode="json"),
            "orders_submitted": 0,
            "execution_permission": "none",
        }

    position_of = {sample.sample_index: position for position, sample in enumerate(samples)}
    binary = [1 if sample.label == 1 else 0 for sample in samples]
    splits = build_purged_embargoed_splits(samples, num_folds=3, purge_bars=horizon_bars, embargo_bars=embargo_bars)
    losses: list[float] = []
    last_stump: tuple[int, float, float, float] | None = None
    embargoed_indexes: set[int] = set()
    for fold in splits:
        train_index = [
            position_of[index]
            for index in fold.train_sample_indices
            if index in position_of and index not in embargoed_indexes
        ]
        test_index = [position_of[index] for index in fold.test_sample_indices if index in position_of]
        if fold.test_sample_indices:
            last_test = max(fold.test_sample_indices)
            for sample in samples:
                if last_test < sample.sample_index <= last_test + embargo_bars:
                    embargoed_indexes.add(sample.sample_index)
        if len(train_index) < 4 or not test_index:
            continue
        stump = _stump([feature_rows[i] for i in train_index], [binary[i] for i in train_index])
        last_stump = stump
        equity = 1.0
        peak = 1.0
        worst = 0.0
        entropy = 0.0
        for position in test_index:
            probability = _probability(feature_rows[position], stump)
            entropy += _cross_entropy(probability, binary[position])
            side = 1.0 if probability >= 0.5 else -1.0
            equity *= 1.0 + side * samples[position].realized_return
            peak = max(peak, equity)
            worst = max(worst, (peak - equity) / peak if peak else 0.0)
        losses.append(entropy / len(test_index) + drawdown_penalty * worst)

    if last_stump is None:
        return {
            "path_id": PATH_ID,
            "status": "insufficient_bars",
            "signal": hold.model_dump(mode="json"),
            "orders_submitted": 0,
            "execution_permission": "none",
            "model_library": "causal_stump",
        }
    stump = last_stump
    probability = _probability(feature_rows[-1], stump)
    last_close = closes[-1]
    last_atr = float(atr[-1] or last_close * 0.01)
    direction = "BUY" if probability >= 0.55 else "SELL" if probability <= 0.45 else "HOLD"
    if direction == "SELL":
        stop = last_close + last_atr
        target = max(0.0, last_close - 1.5 * last_atr)
    else:
        stop = max(0.0, last_close - last_atr)
        target = last_close + 1.5 * last_atr
    signal = StrategySignal(
        strategy_id=PATH_ID,
        symbol=symbol,
        direction=direction,
        target_conviction=min(0.99, max(0.01, probability if direction != "SELL" else 1.0 - probability)),
        suggested_stop_loss=stop,
        suggested_take_profit=target,
        reference_price=last_close,
        target_entry_price=last_close,
        rationale="Purged stump on VWAP, ATR squeeze, RSI divergence, and bar-sign delta. No order authority.",
        telemetry={
            "model_library": "causal_stump",
            "upper_barrier": "1.5 ATR",
            "lower_barrier": "1.0 ATR",
            "horizon_bars": horizon_bars,
            "embargo_bars": embargo_bars,
            "folds": len(splits),
            "mean_penalized_loss": sum(losses) / len(losses) if losses else None,
        },
        execution_permission="none",
    )
    return {
        "path_id": PATH_ID,
        "status": "trained",
        "signal": signal.model_dump(mode="json"),
        "orders_submitted": 0,
        "execution_permission": "none",
    }
