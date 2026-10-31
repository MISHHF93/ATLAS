"""Horizon screen: labels use only the bars at T and T+h, stock horizons never cross a session, noise is not 'kept'."""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from atlas.ai.ml import horizon_tune as H
from atlas.ai.ml import multires as M

NY = ZoneInfo("America/New_York")


def bars15(start, n, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    ts = start + 900 * np.arange(n)
    return M.Bars("15m", ts.astype(np.int64), c, c, c, c, np.ones(n)), c


def test_forward_return_uses_exactly_the_bar_ending_at_T_plus_h():
    start = 1_800_000_000 // 900 * 900
    b, c = bars15(start, 200)
    grid = [int(b.end[10]), int(b.end[150])]
    r = H.forward_returns(b, grid, (1, 4, 96), same_session=False)
    assert math.isclose(r.loc[grid[0], "r4"], math.log(c[14] / c[10]))
    assert math.isnan(r.loc[grid[1], "r96"])                      # the T+24h bar does not exist yet: NaN, never a stand-in


def test_missing_future_bar_gives_nan_not_a_neighbour():
    start = 1_800_000_000 // 900 * 900
    b, c = bars15(start, 100)
    keep = np.ones(100, bool); keep[14] = False
    b2 = M.Bars("15m", b.ts[keep], b.o[keep], b.h[keep], b.l[keep], b.c[keep], b.v[keep])
    r = H.forward_returns(b2, [int(b.end[10])], (4,), same_session=False)
    assert math.isnan(r.iloc[0]["r4"])


def test_stock_horizon_cannot_cross_the_session_end():
    open_ = int(datetime(2026, 10, 29, 9, 30, tzinfo=NY).timestamp())
    ts = np.concatenate([open_ + 900 * np.arange(26), open_ + 86400 + 900 * np.arange(26)]).astype(np.int64)
    c = np.linspace(100, 110, 52)
    b = M.Bars("15m", ts, c, c, c, c, np.ones(52))
    T = int(b.end[20])                                         # 14:45 ET Thursday
    r = H.forward_returns(b, [T], (2, 96), same_session=True)
    assert not math.isnan(r.iloc[0]["r2"]) and math.isnan(r.iloc[0]["r96"])    # +30m is inside the session, +24h would be Friday
    r2 = H.forward_returns(b, [T], (96,), same_session=False)
    assert not math.isnan(r2.iloc[0]["r96"])


def test_noise_is_not_kept_and_selection_is_a_subset_of_candidates():
    rng = np.random.default_rng(5)
    n = 6000
    idx = pd.Index(1_800_000_000 + 900 * np.arange(n), name="decision_ts")
    df = pd.DataFrame({f: rng.normal(size=n) for f in H.LAYERS}, index=idx)
    for h in (1, 4):
        df[f"r{h}"] = rng.normal(0, 0.01, n)
    res = H.tune_class(df, (1, 4), cost_bps=4.0)
    assert [r["h_bars"] for r in res] == [1, 4]
    assert all(r["n_train"] > 1000 and r["n_test"] > 300 for r in res)
    assert not any(r["kept"] for r in res)                       # random labels must not look like signal
    for cls in H.SELECTED_FOR_D.values():
        assert set(cls) <= set(M.CANDIDATE_HORIZON_BARS)


def test_purge_gap_separates_train_labels_from_test_period():
    n = 5000
    idx = pd.Index(1_800_000_000 + 900 * np.arange(n), name="decision_ts")
    rng = np.random.default_rng(1)
    df = pd.DataFrame({f: rng.normal(size=n) for f in H.LAYERS}, index=idx)
    df["r96"] = rng.normal(size=n)
    i_te = int(n * (1 - H.TEST_FRAC))
    res = H.tune_class(df, (96,), cost_bps=4.0, embargo_bars=96)[0]
    gap = (96 + 96) * 900
    expected_train = int(((idx.to_numpy()[: int(n * H.TRAIN_FRAC)]) <= idx.to_numpy()[i_te] - gap).sum())
    assert res["n_train"] == expected_train
