"""Spot vs. Perpetual Basis & Funding Arbitrage Strategy (`STRAT_BASIS_ARB`) (`src/atlas/strategies/arbitrage.py`).

Ingests spot vs. perpetual prices and 8-hour funding rates. Generates dual-leg
delta-neutral arbitrage signals when funding divergence exceeds `3.0` standard deviations:
- When `funding_zscore > +3.0` (perp rich / positive funding spike):
  Primary leg `SELL` perpetual, secondary leg `BUY` spot (`execution_tactic="ALMGREN_CHRISS"`).
- When `funding_zscore < -3.0` (perp discount / negative funding spike):
  Primary leg `BUY` perpetual, secondary leg `SELL` spot (`execution_tactic="ALMGREN_CHRISS"`).

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


class BasisArbitrageStrategy(BaseStrategy):
    """Dual-leg spot-perp delta-neutral funding arbitrage strategy (`STRAT_BASIS_ARB`)."""

    def __init__(self, *, funding_zscore_threshold: float = 3.0) -> None:
        super().__init__(
            strategy_id="STRAT_BASIS_ARB",
            name="Spot-Perpetual Basis & 8h Funding Arbitrage",
            track="competition",
        )
        self.funding_zscore_threshold = funding_zscore_threshold

    def generate_signal(
        self,
        candle_batch: Sequence[CandleBar | dict[str, Any]],
        orderbook_depth: OrderBookDepthSnapshot | dict[str, Any],
        microstructure_metrics: MicrostructureMetrics | dict[str, Any],
    ) -> StrategySignal:
        candles = self._coerce_candles(candle_batch)
        last_close = candles[-1].close if candles else 68410.0
        symbol = candles[-1].symbol if candles else "BTC-USD"

        depth = self._coerce_depth(orderbook_depth, default_symbol=symbol, default_price=last_close)
        metrics = self._coerce_metrics(microstructure_metrics)

        spot_px = float(metrics.spot_price if metrics.spot_price is not None else depth.poc_price)
        perp_px = float(metrics.perp_price if metrics.perp_price is not None else depth.poc_price * 1.0015)
        basis_bps = ((perp_px - spot_px) / max(1e-9, spot_px)) * 10_000.0
        z_funding = float(metrics.funding_zscore)

        atr_frac = max(0.0045, float(metrics.atr_bps) / 10_000.0)
        spot_leg_symbol = f"{depth.symbol}-SPOT"

        if z_funding > self.funding_zscore_threshold:
            # Short Perp / Long Spot delta-neutral carry harvest
            conviction = round(min(0.95, 0.60 + 0.10 * (z_funding - self.funding_zscore_threshold)), 4)
            stop_px = round(perp_px * (1.0 + atr_frac), 4)
            tp_px = round(perp_px * (1.0 - 1.5 * atr_frac), 4)
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=depth.symbol,
                direction="SELL",
                target_conviction=conviction,
                suggested_stop_loss=stop_px,
                suggested_take_profit=tp_px,
                execution_tactic="ALMGREN_CHRISS",
                reference_price=perp_px,
                secondary_leg_symbol=spot_leg_symbol,
                secondary_leg_direction="BUY",
                rationale=(
                    f"Delta-neutral SELL {depth.symbol} perp ({perp_px:.2f}) / BUY {spot_leg_symbol} ({spot_px:.2f}): "
                    f"8h funding={metrics.funding_rate_8h:.5f}, z={z_funding:.2f}sigma > {self.funding_zscore_threshold:.1f}sigma "
                    f"(basis={basis_bps:.1f} bps)."
                ),
                execution_permission="none",
            )

        if z_funding < -self.funding_zscore_threshold:
            # Long Perp / Short Spot reverse basis arbitrage
            conviction = round(min(0.95, 0.60 + 0.10 * (abs(z_funding) - self.funding_zscore_threshold)), 4)
            stop_px = round(perp_px * (1.0 - atr_frac), 4)
            tp_px = round(perp_px * (1.0 + 1.5 * atr_frac), 4)
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=depth.symbol,
                direction="BUY",
                target_conviction=conviction,
                suggested_stop_loss=stop_px,
                suggested_take_profit=tp_px,
                execution_tactic="ALMGREN_CHRISS",
                reference_price=perp_px,
                secondary_leg_symbol=spot_leg_symbol,
                secondary_leg_direction="SELL",
                rationale=(
                    f"Delta-neutral BUY {depth.symbol} perp ({perp_px:.2f}) / SELL {spot_leg_symbol} ({spot_px:.2f}): "
                    f"8h funding={metrics.funding_rate_8h:.5f}, z={z_funding:.2f}sigma < -{self.funding_zscore_threshold:.1f}sigma "
                    f"(basis={basis_bps:.1f} bps)."
                ),
                execution_permission="none",
            )

        stop_px = round(perp_px * (1.0 - atr_frac), 4)
        tp_px = round(perp_px * (1.0 + atr_frac), 4)
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=depth.symbol,
            direction="HOLD",
            target_conviction=0.0,
            suggested_stop_loss=stop_px,
            suggested_take_profit=tp_px,
            execution_tactic="LIMIT",
            reference_price=perp_px,
            secondary_leg_symbol=spot_leg_symbol,
            secondary_leg_direction="HOLD",
            rationale=(
                f"HOLD: funding_zscore={z_funding:.2f}sigma within [-{self.funding_zscore_threshold:.1f}, "
                f"+{self.funding_zscore_threshold:.1f}] threshold."
            ),
            execution_permission="none",
        )

