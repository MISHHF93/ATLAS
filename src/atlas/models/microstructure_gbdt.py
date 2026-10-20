"""WF-05: GBDT Depth Imbalance & Microstructure Spread Predictor (`src/atlas/models/microstructure_gbdt.py`).

Implements:
    y_hat = sum_{m=1}^M f_m(OFI, VPIN, BookEntropy, SpreadRatio)
to predict short-term spread widening (in bps) and emit a passive order cancellation
advisory before adverse selection hits resting quotes. All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, FiniteFloat

from atlas.models.schemas import Probability, Record


class MicrostructureSpreadPrediction(Record):
    """Additive GBDT spread-widening prediction over (OFI, VPIN, BookEntropy, SpreadRatio)."""

    ofi_normalized: FiniteFloat
    vpin: Probability
    book_shannon_entropy: FiniteFloat = Field(ge=0)
    spread_ratio_l2_l1: FiniteFloat = Field(gt=0)
    predicted_spread_widening_bps: FiniteFloat = Field(ge=0)
    cancel_passive_resting_orders: bool
    tree_contributions_bps: tuple[FiniteFloat, ...]
    execution_permission: Literal["none"] = "none"


def predict_microstructure_spread_gbdt(
    *,
    ofi_normalized: float,
    vpin: float,
    depth_levels: tuple[float, ...] | list[float],
    l1_spread_bps: float,
    l2_spread_bps: float,
    cancellation_threshold_bps: float = 3.0,
) -> MicrostructureSpreadPrediction:
    """Evaluate additive GBDT trees over (OFI, VPIN, BookEntropy, SpreadRatio)."""
    if l1_spread_bps <= 0 or l2_spread_bps <= 0:
        raise ValueError("l1_spread_bps and l2_spread_bps must be positive")
    if not depth_levels:
        raise ValueError("depth_levels must be non-empty")

    clean_depths = [max(1e-6, float(d)) for d in depth_levels]
    tot = sum(clean_depths)
    probs = [d / tot for d in clean_depths]
    entropy = -sum(p * math.log(p) for p in probs)
    spread_ratio = float(l2_spread_bps) / float(l1_spread_bps)

    # 4 depth-2 regression trees calibrated on microstructure toxicity regimes
    f1_vpin = 1.85 if vpin >= 0.45 else (0.95 if vpin >= 0.30 else 0.25)
    f2_ofi = 1.55 if abs(ofi_normalized) >= 0.65 else (0.75 if abs(ofi_normalized) >= 0.35 else 0.20)
    f3_entropy = 1.25 if entropy < 1.35 else 0.20
    f4_spread = 0.95 if spread_ratio >= 1.80 else 0.15

    trees = (round(f1_vpin, 4), round(f2_ofi, 4), round(f3_entropy, 4), round(f4_spread, 4))
    y_hat = round(sum(trees), 4)

    return MicrostructureSpreadPrediction(
        ofi_normalized=round(float(ofi_normalized), 6),
        vpin=round(max(0.0, min(1.0, float(vpin))), 6),
        book_shannon_entropy=round(entropy, 6),
        spread_ratio_l2_l1=round(spread_ratio, 6),
        predicted_spread_widening_bps=y_hat,
        cancel_passive_resting_orders=y_hat >= cancellation_threshold_bps,
        tree_contributions_bps=trees,
    )

