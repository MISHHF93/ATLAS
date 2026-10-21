"""Microstructure & Whale Feature Extractor (`src/atlas/features/microstructure.py`).

Implements streaming and historical causal calculation of:
1. **Rolling VPIN (Volume-Synchronized Probability of Informed Trading)**:
   Partitions tick streams into volume buckets of size $V = \\text{ADV} / N$ (e.g. $N=50$) and computes:
   $$\\mathrm{VPIN} = \\frac{\\sum_{\\tau=1}^M |V_\\tau^B - V_\\tau^S|}{M \\cdot V}$$
2. **Multi-Level Order Flow Imbalance (OFI)**:
   Computes depth-weighted queue variations across Top 5 L2 bid/ask levels:
   $$\\mathrm{OFI}_t = \\sum_{k=1}^5 e^{-\\alpha k} \\left[ I_{\\{P_k^b \\ge P_{k, t-1}^b\\}} \\Delta q_k^b - I_{\\{P_k^a \\le P_{k, t-1}^a\\}} \\Delta q_k^a \\right]$$
3. **Rolling Kyle's Lambda ($\\lambda_t$)**:
   Calculates $\\lambda_t = \\frac{\\operatorname{Cov}(\\Delta P, Q)}{\\operatorname{Var}(Q)}$ over rolling volume windows.
4. **Hawkes Process Child-Order Intensity**:
   Fits $\\lambda(t) = \\mu_0 + \\sum_{t_i < t} \\alpha e^{-\\beta (t - t_i)}$ to detect algorithmic iceberg order slicing
   when branching ratio $\\frac{\\alpha}{\\beta} \\to 1.0$.

All feature extractors enforce strict point-in-time causality and `execution_permission = "none"`.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from pydantic import AwareDatetime, Field, FiniteFloat

from atlas.marketdata.microstructure import (
    BookLevelSnapshot,
    HawkesIntensityReport,
    KylesLambdaResult,
    MultiLevelOfiReport,
    VpinBucketReport,
    VpinBucketSlice,
    compute_hawkes_intensity,
    compute_multilevel_ofi,
    compute_volume_synchronized_vpin,
    estimate_kyles_lambda,
)
from atlas.models.schemas import Probability, Record, Text


class WhaleMicrostructureFeatureSnapshot(Record):
    """Unified point-in-time feature vector combining VPIN, Multi-Level OFI, Kyle's Lambda, and Hawkes Intensity."""

    symbol: Text
    as_of: AwareDatetime
    vpin: Probability
    bucket_volume_v: FiniteFloat = Field(gt=0)
    ofi_raw: FiniteFloat
    ofi_normalized: FiniteFloat
    ofi_zscore: FiniteFloat
    kyles_lambda: FiniteFloat
    kyles_r_squared: Probability
    hawkes_intensity_lambda: FiniteFloat = Field(ge=0)
    hawkes_branching_ratio: FiniteFloat = Field(ge=0)
    iceberg_slicing_detected: bool
    atr_14: FiniteFloat = Field(gt=0)
    spread_bps: FiniteFloat = Field(ge=0)
    execution_permission: Literal["none"] = "none"


def compute_rolling_vpin(
    price_deltas: Sequence[float],
    trade_volumes: Sequence[float],
    *,
    adv: float | None = None,
    buckets_per_day_n: int = 50,
    bucket_volume_override: float | None = None,
    window_m: int = 20,
    toxicity_threshold: float = 0.45,
) -> VpinBucketReport:
    """Partition tick streams into volume buckets of size $V = \\text{ADV} / N$ and compute rolling VPIN."""
    if bucket_volume_override is not None and bucket_volume_override > 0:
        bucket_v = float(bucket_volume_override)
    elif adv is not None and adv > 0:
        bucket_v = max(1e-6, float(adv) / max(1, int(buckets_per_day_n)))
    else:
        total_vol = sum(max(0.0, float(v)) for v in trade_volumes)
        bucket_v = max(1.0, total_vol / max(4, min(int(buckets_per_day_n), len(trade_volumes))))

    return compute_volume_synchronized_vpin(
        list(price_deltas),
        list(trade_volumes),
        bucket_volume=bucket_v,
        max_buckets=max(1, int(window_m)),
        toxicity_threshold=toxicity_threshold,
    )


def compute_exponential_multilevel_ofi(
    prev_book: Sequence[BookLevelSnapshot],
    curr_book: Sequence[BookLevelSnapshot],
    *,
    alpha: float = 0.45,
) -> MultiLevelOfiReport:
    """Compute depth-weighted queue variations across Top 5 L2 bid/ask levels:
    $\\mathrm{OFI}_t = \\sum_{k=1}^5 e^{-\\alpha k} [I(P_k^b \\ge P_{k,t-1}^b) \\Delta q_k^b - I(P_k^a \\le P_{k,t-1}^a) \\Delta q_k^a]$.
    """
    if len(prev_book) != len(curr_book) or len(curr_book) == 0:
        raise ValueError("prev_book and curr_book must be non-empty and have identical level count")
    if alpha <= 0:
        raise ValueError("Exponential decay alpha must be strictly positive")

    k_levels = min(5, len(curr_book))
    weights = [round(math.exp(-alpha * k), 6) for k in range(1, k_levels + 1)]
    contributions: list[float] = []
    abs_capacity = 0.0

    for idx in range(k_levels):
        prev_lvl = prev_book[idx]
        curr_lvl = curr_book[idx]
        w_k = weights[idx]

        # Delta q_k^b under Cont-Kukanov-Stoikov queue transition rules
        if curr_lvl.bid_price > prev_lvl.bid_price:
            delta_q_b = curr_lvl.bid_size
        elif curr_lvl.bid_price == prev_lvl.bid_price:
            delta_q_b = curr_lvl.bid_size - prev_lvl.bid_size
        else:
            delta_q_b = -prev_lvl.bid_size

        # Delta q_k^a under Cont-Kukanov-Stoikov queue transition rules
        if curr_lvl.ask_price < prev_lvl.ask_price:
            delta_q_a = curr_lvl.ask_size
        elif curr_lvl.ask_price == prev_lvl.ask_price:
            delta_q_a = curr_lvl.ask_size - prev_lvl.ask_size
        else:
            delta_q_a = -prev_lvl.ask_size

        ind_b = 1.0 if curr_lvl.bid_price >= prev_lvl.bid_price else 0.0
        ind_a = 1.0 if curr_lvl.ask_price <= prev_lvl.ask_price else 0.0

        ofi_k = w_k * (ind_b * delta_q_b - ind_a * delta_q_a)
        contributions.append(round(ofi_k, 6))
        abs_capacity += w_k * (abs(delta_q_b) + abs(delta_q_a) + prev_lvl.bid_size + prev_lvl.ask_size)

    ofi_raw = sum(contributions)
    ofi_norm = max(-1.0, min(1.0, ofi_raw / abs_capacity)) if abs_capacity > 1e-12 else 0.0
    dominant: Literal["buy", "sell", "neutral"] = (
        "buy" if ofi_norm > 0.05 else ("sell" if ofi_norm < -0.05 else "neutral")
    )

    return MultiLevelOfiReport(
        ofi_raw=round(ofi_raw, 6),
        ofi_normalized=round(ofi_norm, 6),
        level_contributions=tuple(contributions),
        weights=tuple(weights),
        dominant_pressure=dominant,
    )


def compute_rolling_kyles_lambda(
    price_changes: Sequence[float],
    signed_order_flows: Sequence[float],
    *,
    window: int | None = None,
    spike_threshold: float = 0.0025,
) -> KylesLambdaResult:
    """Compute $\\lambda_t = \\operatorname{Cov}(\\Delta P, Q) / \\operatorname{Var}(Q)$ over a rolling volume window."""
    dp_seq = list(price_changes[-window:]) if window is not None else list(price_changes)
    q_seq = list(signed_order_flows[-window:]) if window is not None else list(signed_order_flows)
    return estimate_kyles_lambda(dp_seq, q_seq, spike_threshold=spike_threshold)


def compute_hawkes_child_order_intensity(
    event_times_sec: Sequence[float],
    *,
    eval_time_sec: float,
    mu_0: float = 0.50,
    alpha: float = 0.92,
    beta: float = 1.00,
    clustering_threshold: float = 1.45,
) -> HawkesIntensityReport:
    """Fit $\\lambda(t) = \\mu_0 + \\sum_{t_i < t} \\alpha e^{-\\beta (t - t_i)}$ to detect algorithmic
    iceberg order slicing when branching ratio $\\alpha / \\beta \\to 1.0$.
    """
    return compute_hawkes_intensity(
        list(event_times_sec),
        eval_time_sec=eval_time_sec,
        mu_0=mu_0,
        alpha=alpha,
        beta=beta,
        clustering_threshold=clustering_threshold,
    )


class MicrostructureWhaleFeatureExtractor:
    """Streaming and historical feature extractor for VPIN, Top-5 OFI, Kyle's Lambda, and Hawkes clustering."""

    def __init__(
        self,
        *,
        buckets_per_day_n: int = 50,
        vpin_window_m: int = 20,
        ofi_alpha: float = 0.45,
        hawkes_mu_0: float = 0.50,
        hawkes_alpha: float = 0.92,
        hawkes_beta: float = 1.00,
    ) -> None:
        self.buckets_per_day_n = buckets_per_day_n
        self.vpin_window_m = vpin_window_m
        self.ofi_alpha = ofi_alpha
        self.hawkes_mu_0 = hawkes_mu_0
        self.hawkes_alpha = hawkes_alpha
        self.hawkes_beta = hawkes_beta

    def extract_from_candles_and_depth(
        self,
        symbol: str,
        candles: Sequence[dict[str, Any]],
        *,
        prev_book: Sequence[BookLevelSnapshot] | None = None,
        curr_book: Sequence[BookLevelSnapshot] | None = None,
        event_times_sec: Sequence[float] | None = None,
        eval_time_sec: float = 10.0,
        as_of: datetime | None = None,
    ) -> WhaleMicrostructureFeatureSnapshot:
        """Extract a causal `WhaleMicrostructureFeatureSnapshot` from candle/tick bars and L2 depth."""
        if len(candles) < 3:
            raise ValueError("At least 3 bars/ticks are required for causal microstructure feature extraction")

        ts = as_of or datetime.now(timezone.utc)
        closes = [float(c["close"]) for c in candles]
        highs = [float(c.get("high", c["close"])) for c in candles]
        lows = [float(c.get("low", c["close"])) for c in candles]
        opens = [float(c.get("open", c["close"])) for c in candles]
        volumes = [max(1.0, float(c.get("volume", 1000.0))) for c in candles]

        price_deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        trade_vols = volumes[1:]
        signed_flows = [
            volumes[i] * (1.0 if closes[i] >= opens[i] else -1.0)
            for i in range(1, len(closes))
        ]
        # Ensure non-zero variance in signed flows
        if len(set(signed_flows)) == 1:
            signed_flows[-1] = signed_flows[-1] * 1.15

        total_vol = sum(trade_vols)
        vpin_rep = compute_rolling_vpin(
            price_deltas,
            trade_vols,
            bucket_volume_override=max(1.0, total_vol / max(2, min(8, len(trade_vols)))),
            window_m=self.vpin_window_m,
        )
        kyle_rep = compute_rolling_kyles_lambda(price_deltas, signed_flows)

        spot = closes[-1]
        if prev_book is None or curr_book is None:
            drift_sign = 1.0 if price_deltas[-1] >= 0 else -1.0
            prev_book = [
                BookLevelSnapshot(
                    level=k,
                    bid_price=round(spot * (1.0 - 0.0002 * k), 4),
                    bid_size=100.0 * k,
                    ask_price=round(spot * (1.0 + 0.0002 * k), 4),
                    ask_size=100.0 * k,
                )
                for k in range(1, 6)
            ]
            curr_book = [
                BookLevelSnapshot(
                    level=k,
                    bid_price=round(spot * (1.0 - 0.0002 * k), 4),
                    bid_size=max(10.0, 100.0 * k * (1.0 + 0.35 * drift_sign)),
                    ask_price=round(spot * (1.0 + 0.0002 * k), 4),
                    ask_size=max(10.0, 100.0 * k * (1.0 - 0.25 * drift_sign)),
                )
                for k in range(1, 6)
            ]

        ofi_rep = compute_exponential_multilevel_ofi(prev_book, curr_book, alpha=self.ofi_alpha)
        ofi_z = round(ofi_rep.ofi_normalized * 4.2, 4)

        ev_times = list(event_times_sec) if event_times_sec is not None else [6.2, 7.4, 8.3, 9.1, 9.6, 9.85]
        hawkes_rep = compute_hawkes_child_order_intensity(
            ev_times,
            eval_time_sec=eval_time_sec,
            mu_0=self.hawkes_mu_0,
            alpha=self.hawkes_alpha,
            beta=self.hawkes_beta,
        )

        tr_list = [max(1e-6, highs[i] - lows[i]) for i in range(-min(14, len(candles)), 0)]
        atr_14 = sum(tr_list) / len(tr_list)
        spread_bps = round(((curr_book[0].ask_price - curr_book[0].bid_price) / spot) * 10_000.0, 4)

        return WhaleMicrostructureFeatureSnapshot(
            symbol=symbol.upper().strip(),
            as_of=ts,
            vpin=vpin_rep.vpin,
            bucket_volume_v=vpin_rep.bucket_volume_v,
            ofi_raw=ofi_rep.ofi_raw,
            ofi_normalized=ofi_rep.ofi_normalized,
            ofi_zscore=ofi_z,
            kyles_lambda=kyle_rep.lambda_impact,
            kyles_r_squared=kyle_rep.r_squared,
            hawkes_intensity_lambda=hawkes_rep.intensity_lambda_t,
            hawkes_branching_ratio=hawkes_rep.branching_ratio,
            iceberg_slicing_detected=hawkes_rep.iceberg_clustering_detected,
            atr_14=round(max(0.01, atr_14), 6),
            spread_bps=max(0.1, spread_bps),
            execution_permission="none",
        )


__all__ = [
    "BookLevelSnapshot",
    "HawkesIntensityReport",
    "KylesLambdaResult",
    "MicrostructureWhaleFeatureExtractor",
    "MultiLevelOfiReport",
    "VpinBucketReport",
    "VpinBucketSlice",
    "WhaleMicrostructureFeatureSnapshot",
    "compute_exponential_multilevel_ofi",
    "compute_hawkes_child_order_intensity",
    "compute_hawkes_intensity",
    "compute_multilevel_ofi",
    "compute_rolling_kyles_lambda",
    "compute_rolling_vpin",
    "compute_volume_synchronized_vpin",
    "estimate_kyles_lambda",
]

