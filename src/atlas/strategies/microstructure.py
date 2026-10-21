"""VPIN & OFI Passive Absorption Strategy (`STRAT_VPIN_ABSORB`) (`src/atlas/strategies/microstructure.py`).

Evaluates real-time Volume-Synchronized Probability of Informed Trading (VPIN) and
Order Flow Imbalance (OFI). When `VPIN > 0.35` and `OFI > 2.0` standard deviations
with consolidating price action, generates a passive `BUY` signal anchored at the
Point of Control (`poc_price`), with an ATR/structure stop-loss below Value Area Low (`val_price`)
and take-profit at Value Area High (`vah_price`).

Strictly enforces `execution_permission = "none"`.
"""
from __future__ import annotations

from typing import Any, Sequence

from atlas.strategies.base import (
    BaseStrategy,
    CandleBar,
    MicrostructureMetrics,
    OrderBookDepthSnapshot,
    StrategySignal,
)


class VpinAbsorptionStrategy(BaseStrategy):
    """Microstructure passive absorption strategy (`STRAT_VPIN_ABSORB`)."""

    def __init__(
        self,
        *,
        vpin_threshold: float = 0.35,
        ofi_zscore_threshold: float = 2.0,
        max_bar_range_pct: float = 0.012,
    ) -> None:
        super().__init__(
            strategy_id="STRAT_VPIN_ABSORB",
            name="VPIN & OFI Passive POC Absorption",
            track="both",
        )
        self.vpin_threshold = vpin_threshold
        self.ofi_zscore_threshold = ofi_zscore_threshold
        self.max_bar_range_pct = max_bar_range_pct

    def generate_signal(
        self,
        candle_batch: Sequence[CandleBar | dict[str, Any]],
        orderbook_depth: OrderBookDepthSnapshot | dict[str, Any],
        microstructure_metrics: MicrostructureMetrics | dict[str, Any],
    ) -> StrategySignal:
        candles = self._coerce_candles(candle_batch)
        last_close = candles[-1].close if candles else 100.0
        symbol = candles[-1].symbol if candles else "BTC-USD"

        depth = self._coerce_depth(orderbook_depth, default_symbol=symbol, default_price=last_close)
        metrics = self._coerce_metrics(microstructure_metrics)

        # Evaluate price consolidation across recent bars (tight range around POC)
        if candles:
            recent = candles[-5:]
            highs = max(c.high for c in recent)
            lows = min(c.low for c in recent)
            mean_px = sum(c.close for c in recent) / len(recent)
            realized_range_pct = (highs - lows) / max(1e-9, mean_px)
            is_consolidating = (
                realized_range_pct <= self.max_bar_range_pct
                or metrics.price_consolidation_score >= 0.50
            )
        else:
            is_consolidating = metrics.price_consolidation_score >= 0.50

        poc_px = float(depth.poc_price)
        atr_frac = max(0.0040, float(metrics.atr_bps) / 10_000.0)
        stop_px = round(min(float(depth.val_price), poc_px * (1.0 - atr_frac)), 4)
        tp_px = round(max(float(depth.vah_price), poc_px * (1.0 + 1.8 * atr_frac)), 4)

        if (
            metrics.vpin > self.vpin_threshold
            and metrics.ofi_zscore > self.ofi_zscore_threshold
            and is_consolidating
        ):
            raw_conv = 0.55 + 0.25 * min(1.0, (metrics.ofi_zscore - self.ofi_zscore_threshold) / 2.0) + 0.15 * min(
                1.0, (metrics.vpin - self.vpin_threshold) / 0.30
            )
            conviction = round(min(0.95, max(0.50, raw_conv)), 4)
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=depth.symbol,
                direction="BUY",
                target_conviction=conviction,
                suggested_stop_loss=stop_px,
                suggested_take_profit=tp_px,
                execution_tactic="LIMIT",
                reference_price=poc_px,
                rationale=(
                    f"Passive BUY at POC ({poc_px:.2f}): VPIN={metrics.vpin:.3f}>{self.vpin_threshold:.2f}, "
                    f"OFI_z={metrics.ofi_zscore:.2f}sigma>{self.ofi_zscore_threshold:.1f}sigma with consolidating price."
                ),
                execution_permission="none",
            )

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=depth.symbol,
            direction="HOLD",
            target_conviction=0.0,
            suggested_stop_loss=stop_px,
            suggested_take_profit=tp_px,
            execution_tactic="LIMIT",
            reference_price=poc_px,
            rationale=(
                f"HOLD: VPIN={metrics.vpin:.3f}, OFI_z={metrics.ofi_zscore:.2f}sigma, "
                f"consolidating={is_consolidating} below absorption trigger."
            ),
            execution_permission="none",
        )

