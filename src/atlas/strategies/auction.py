"""NYSE/Nasdaq Opening Auction Drive Strategy (`STRAT_AUCTION_DRIVE`) (`src/atlas/strategies/auction.py`).

Ingests NYSE/Nasdaq opening auction order imbalance telemetry between `09:25–09:30 ET`
for liquid benchmark equities (`SPY`, `QQQ`, `NVDA`). Generates opening momentum drive
signals with a strict mandatory time-decay exit at `10:15 ET` (`time_decay_exit_et="10:15 ET"`).

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


ALLOWED_AUCTION_TICKERS: frozenset[str] = frozenset({"SPY", "QQQ", "NVDA"})


def _parse_hhmm_minutes(et_time_str: str) -> int:
    """Convert an 'HH:MM' or 'HH:MM ET' timestamp string into minutes from midnight."""
    cleaned = et_time_str.strip().upper().replace("ET", "").strip()
    parts = cleaned.split(":")
    if len(parts) < 2:
        return 9 * 60 + 28
    try:
        hours = int(parts[0])
        minutes = int(parts[1][:2])
        return hours * 60 + minutes
    except ValueError:
        return 9 * 60 + 28


class OpeningAuctionDriveStrategy(BaseStrategy):
    """NYSE/Nasdaq 09:25–09:30 ET Opening Auction Imbalance Momentum Drive (`STRAT_AUCTION_DRIVE`)."""

    def __init__(
        self,
        *,
        imbalance_zscore_threshold: float = 1.8,
        min_imbalance_shares: float = 25_000.0,
    ) -> None:
        super().__init__(
            strategy_id="STRAT_AUCTION_DRIVE",
            name="NYSE/Nasdaq Opening Auction Imbalance Drive",
            track="open_market",
        )
        self.imbalance_zscore_threshold = imbalance_zscore_threshold
        self.min_imbalance_shares = min_imbalance_shares

    def generate_signal(
        self,
        candle_batch: Sequence[CandleBar | dict[str, Any]],
        orderbook_depth: OrderBookDepthSnapshot | dict[str, Any],
        microstructure_metrics: MicrostructureMetrics | dict[str, Any],
    ) -> StrategySignal:
        candles = self._coerce_candles(candle_batch)
        last_close = candles[-1].close if candles else 584.20
        symbol = (candles[-1].symbol if candles else "SPY").upper()

        depth = self._coerce_depth(orderbook_depth, default_symbol=symbol, default_price=last_close)
        metrics = self._coerce_metrics(microstructure_metrics)

        ref_px = float(depth.poc_price)
        atr_frac = max(0.0035, float(metrics.atr_bps) / 10_000.0)
        default_stop = round(ref_px * (1.0 - atr_frac), 4)
        default_tp = round(ref_px * (1.0 + 1.8 * atr_frac), 4)

        ticker = depth.symbol.upper()
        if ticker not in ALLOWED_AUCTION_TICKERS:
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=ticker,
                direction="HOLD",
                target_conviction=0.0,
                suggested_stop_loss=default_stop,
                suggested_take_profit=default_tp,
                execution_tactic="TWAP",
                reference_price=ref_px,
                time_decay_exit_et="10:15 ET",
                rationale=f"HOLD: {ticker} is outside allowed auction universe {sorted(ALLOWED_AUCTION_TICKERS)}.",
                execution_permission="none",
            )

        minutes_et = _parse_hhmm_minutes(metrics.auction_timestamp_et)
        auction_window_start = 9 * 60 + 25  # 09:25 ET
        auction_window_end = 9 * 60 + 30    # 09:30 ET
        time_decay_cutoff = 10 * 60 + 15    # 10:15 ET

        if minutes_et >= time_decay_cutoff or not (auction_window_start <= minutes_et <= auction_window_end):
            return StrategySignal(
                strategy_id=self.strategy_id,
                symbol=ticker,
                direction="HOLD",
                target_conviction=0.0,
                suggested_stop_loss=default_stop,
                suggested_take_profit=default_tp,
                execution_tactic="TWAP",
                reference_price=ref_px,
                time_decay_exit_et="10:15 ET",
                rationale=(
                    f"HOLD / Time-Decay Exit Active: auction_timestamp_et={metrics.auction_timestamp_et} "
                    f"outside 09:25–09:30 ET entry window (mandatory exit at 10:15 ET)."
                ),
                execution_permission="none",
            )

        imb_shares = float(metrics.auction_imbalance_shares)
        imb_z = float(metrics.auction_imbalance_zscore)

        if abs(imb_shares) >= self.min_imbalance_shares and abs(imb_z) >= self.imbalance_zscore_threshold:
            conviction = round(
                min(0.94, 0.58 + 0.12 * (abs(imb_z) - self.imbalance_zscore_threshold)),
                4,
            )
            if imb_shares > 0 and imb_z > 0:
                stop_px = round(ref_px * (1.0 - atr_frac), 4)
                tp_px = round(ref_px * (1.0 + 2.0 * atr_frac), 4)
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=ticker,
                    direction="BUY",
                    target_conviction=conviction,
                    suggested_stop_loss=stop_px,
                    suggested_take_profit=tp_px,
                    execution_tactic="TWAP",
                    reference_price=ref_px,
                    time_decay_exit_et="10:15 ET",
                    rationale=(
                        f"Opening Auction Drive BUY {ticker} at {metrics.auction_timestamp_et} ET: "
                        f"imbalance=+{imb_shares:,.0f} sh ({imb_z:+.2f}sigma). Mandatory time-decay exit at 10:15 ET."
                    ),
                    execution_permission="none",
                )
            if imb_shares < 0 and imb_z < 0:
                stop_px = round(ref_px * (1.0 + atr_frac), 4)
                tp_px = round(ref_px * (1.0 - 2.0 * atr_frac), 4)
                return StrategySignal(
                    strategy_id=self.strategy_id,
                    symbol=ticker,
                    direction="SELL",
                    target_conviction=conviction,
                    suggested_stop_loss=stop_px,
                    suggested_take_profit=tp_px,
                    execution_tactic="TWAP",
                    reference_price=ref_px,
                    time_decay_exit_et="10:15 ET",
                    rationale=(
                        f"Opening Auction Drive SELL {ticker} at {metrics.auction_timestamp_et} ET: "
                        f"imbalance={imb_shares:,.0f} sh ({imb_z:+.2f}sigma). Mandatory time-decay exit at 10:15 ET."
                    ),
                    execution_permission="none",
                )

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=ticker,
            direction="HOLD",
            target_conviction=0.0,
            suggested_stop_loss=default_stop,
            suggested_take_profit=default_tp,
            execution_tactic="TWAP",
            reference_price=ref_px,
            time_decay_exit_et="10:15 ET",
            rationale=f"HOLD: {ticker} auction imbalance ({imb_shares:,.0f} sh, {imb_z:+.2f}sigma) below threshold.",
            execution_permission="none",
        )

