"""Causal per-source-bar features from an alternative representation.

For source bar i (index = its ``end``), only alt bars with completed_at <= end_i are visible. Features (``rep_*``):
  rep_dir_last   direction of the last completed alt bar (+1/-1/0)
  rep_run        signed length of the current same-direction run of completed alt bars
  rep_dir_sum8   sum of directions of the last 8 completed alt bars / 8
  rep_rate64     alt bars completed in the last 64 source bars / 64 (activity; ~1 for time/HA)
  rep_dist_atr   (source close - last alt close) / source ATR(14)   (for HA: real close minus HA close)
  rep_age        source bars since the last alt bar completed (capped at 64) / 64
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Sequence

import numpy as np
import pandas as pd

from atlas.features.price_action.bars import Bar
from atlas.features.representations.builders import AltBar, _atr_series, build

REP_FEATURES = ("rep_dir_last", "rep_run", "rep_dir_sum8", "rep_rate64", "rep_dist_atr", "rep_age")


def rep_features(bars: Sequence[Bar], kind: str, alt: Sequence[AltBar] | None = None) -> pd.DataFrame:
    idx = [b.end for b in bars]
    if kind == "time":
        return pd.DataFrame(index=idx, columns=list(REP_FEATURES), dtype=float)
    alt = list(alt if alt is not None else build(kind, bars))
    comp = [a.completed_at for a in alt]
    dirs = np.array([a.direction for a in alt], float)
    atr = _atr_series(bars)
    rows = np.full((len(bars), len(REP_FEATURES)), np.nan)
    pos = {b.end: i for i, b in enumerate(bars)}
    run = 0
    last_j = -1
    for i, b in enumerate(bars):
        j = bisect_right(comp, b.end) - 1           # last alt bar completed at or before this bar's end
        if j < 0:
            continue
        for k in range(last_j + 1, j + 1):
            run = run + dirs[k] if run * dirs[k] > 0 else dirs[k]
        last_j = j
        lo = bisect_right(comp, bars[max(0, i - 63)].start)
        a = atr[i]
        age = i - pos.get(comp[j], i)
        rows[i] = [dirs[j], run, dirs[max(0, j - 7): j + 1].sum() / 8, (j + 1 - lo) / 64,
                   (b.close - alt[j].close) / a if a else np.nan, min(age, 64) / 64]
    return pd.DataFrame(rows, index=idx, columns=list(REP_FEATURES))
