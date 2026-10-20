"""Subsystem H: Hardware Acceleration & High-Throughput Vectorized Backtesting (`src/atlas/hardware/`).

Implements contiguous array vectorized return, drawdown, and Sharpe evaluation
for low-latency SIMD-friendly backtesting sweeps (`execution_permission = "none"`).
"""
from __future__ import annotations

import math
from array import array
from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Record


class VectorizedBacktestResult(Record):
    """High-throughput vectorized backtest report over contiguous double-precision arrays."""

    bar_count: int = Field(ge=1)
    cumulative_return: FiniteFloat
    max_drawdown_fraction: FiniteFloat = Field(ge=0)
    annualized_sharpe: FiniteFloat
    execution_permission: Literal["none"] = "none"


def run_vectorized_backtest(
    asset_returns: tuple[float, ...] | list[float],
    signal_weights: tuple[float, ...] | list[float],
    *,
    cost_bps: float = 2.0,
) -> VectorizedBacktestResult:
    """Execute a contiguous `array('d')` vectorized backtest with transaction costs."""
    if not asset_returns or len(asset_returns) != len(signal_weights):
        raise ValueError("asset_returns and signal_weights must be non-empty and of equal length")

    ret_arr = array("d", asset_returns)
    sig_arr = array("d", signal_weights)
    n = len(ret_arr)
    cost_frac = cost_bps / 10_000.0

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    net_rets = array("d")
    prev_w = 0.0

    for i in range(n):
        w = sig_arr[i]
        r_net = w * ret_arr[i] - abs(w - prev_w) * cost_frac
        net_rets.append(r_net)
        equity *= 1.0 + r_net
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        prev_w = w

    mean_r = sum(net_rets) / n
    var_r = sum((r - mean_r) ** 2 for r in net_rets) / max(1, n)
    sharpe = (mean_r / math.sqrt(var_r)) * math.sqrt(252.0) if var_r > 1e-15 else 0.0

    return VectorizedBacktestResult(
        bar_count=n,
        cumulative_return=round(equity - 1.0, 6),
        max_drawdown_fraction=round(max_dd, 6),
        annualized_sharpe=round(sharpe, 4),
    )


__all__ = ["VectorizedBacktestResult", "run_vectorized_backtest"]

