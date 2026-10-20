"""WF-03: Order Flow Imbalance (OFI) & Multi-Level Depth Imbalance (`src/atlas/microstructure/orderbook.py`).

Implements:
    OFI_t = sum_{k=1}^K w_k * [ I(P_k^b >= P_{k,t-1}^b) Delta q_k^b - I(P_k^a <= P_{k,t-1}^a) Delta q_k^a ]
and Shannon book depth entropy across K levels. All outputs carry `execution_permission = "none"`.
"""
from __future__ import annotations

import math

from atlas.marketdata.microstructure import (
    BookLevelSnapshot,
    MultiLevelOfiReport,
    compute_multilevel_ofi,
)


def compute_book_shannon_entropy(book_levels: tuple[BookLevelSnapshot, ...] | list[BookLevelSnapshot]) -> float:
    """Compute Shannon entropy H = -sum(p_k * ln(p_k)) across L2/L3 bid+ask depth levels."""
    depths = [max(1e-9, float(lvl.bid_size) + float(lvl.ask_size)) for lvl in book_levels]
    total = sum(depths)
    if total <= 0 or not depths:
        return 0.0
    probs = [d / total for d in depths]
    return round(-sum(p * math.log(p) for p in probs), 6)


__all__ = [
    "BookLevelSnapshot",
    "MultiLevelOfiReport",
    "compute_book_shannon_entropy",
    "compute_multilevel_ofi",
]

