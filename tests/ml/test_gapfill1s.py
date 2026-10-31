"""Predicted 1s gap fill: flagged predicted + uses_future, stored apart from real bars, never read by the features."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from atlas.ai.ml import gapfill1s as G
from atlas.feeds.trades1s import TradeBarStore

T0 = 1_800_000_000


def real_row(ts, px, venue="kraken", ins="BTCUSDT", n=2):
    return (venue, ins, ts, px, px, px, px, 1.0, 0.5, 0.5, n, px)


def store_with(tmp_path: Path, secs_px):
    st = TradeBarStore(tmp_path / "t.sqlite")
    st.write_bars([real_row(T0 + s, px) for s, px in secs_px])
    return st


def n_real(st):
    with st._ro() as c:
        return c.execute("SELECT COUNT(*) FROM bars_1s").fetchone()[0]


def test_bridge_hits_endpoints_and_is_geometric_between():
    assert G.bridge(0, 100.0, 10, 110.0, 0) == pytest.approx(100.0)
    assert G.bridge(0, 100.0, 10, 110.0, 10) == pytest.approx(110.0)
    assert G.bridge(0, 100.0, 4, 121.0, 2) == pytest.approx(110.0)


def test_fill_only_between_two_real_bars_and_marks_every_row_predicted(tmp_path):
    st = store_with(tmp_path, [(0, 100.0), (1, 100.0), (5, 104.0), (10, 104.0), (400, 120.0)])
    ps = G.PredStore(":memory:")
    before = n_real(st)
    out = G.fill(st, ps, "kraken", "BTCUSDT", T0, T0 + 500, now=T0 + 600)
    secs = sorted(r["ts"] - T0 for r in out)
    assert secs == [2, 3, 4, 6, 7, 8, 9]                     # the 390 s hole is longer than MAX_GAP: left empty, not guessed
    assert all(r["predicted"] and r["uses_future"] and r["label"] == G.LABEL for r in out)
    assert all(r["interval"] == "uncalibrated" and r["lo"] is None for r in out)   # no calibration yet, so no interval is claimed
    rows = ps.rows("kraken", "BTCUSDT", T0, T0 + 500)
    assert len(rows) == 7 and all(r[7] == 1 and r[8] == 1 for r in rows)
    assert n_real(st) == before                              # the real 1s store is never written
    assert not (set(secs) & {0, 1, 5, 10})                   # real seconds are never overwritten


def test_predicted_flags_cannot_be_cleared():
    ps = G.PredStore(":memory:")
    ps.put([("kraken", "BTCUSDT", T0, 100.0, None, None, 3, G.METHOD, 0, T0)])
    with pytest.raises(sqlite3.IntegrityError):
        ps._c.execute("UPDATE pred_1s SET predicted=0")
    with pytest.raises(sqlite3.IntegrityError):
        ps._c.execute("UPDATE pred_1s SET uses_future=0")


def test_calibration_masks_real_seconds_and_withholds_small_samples():
    rng = np.random.default_rng(2)
    ts = np.arange(0, 400, 3, dtype=np.int64)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, len(ts))))
    cal = G.calibrate([(ts, c)])
    assert cal and any(v["n"] < G.MIN_CALIB for v in cal.values())
    assert all((v["q80_abs"] is None) == (v["n"] < G.MIN_CALIB) for v in cal.values())     # too little data: no interval
    big = G.calibrate([(np.arange(0, 6000, 2, dtype=np.int64), 100 * np.exp(np.cumsum(rng.normal(0, 1e-4, 3000))))])
    k = max(big, key=lambda b: big[b]["n"])
    assert big[k]["n"] >= G.MIN_CALIB and big[k]["q80_abs"] > 0
    assert big[k]["mae_bridge"] <= big[k]["mae_carry"] * 1.5


def test_intervals_appear_once_calibrated_and_widen_with_gap_length(tmp_path):
    st = store_with(tmp_path, [(0, 100.0), (4, 100.4), (40, 101.0)])
    ps = G.PredStore(":memory:")
    ps.save_calib("kraken", {"3-5": {"n": 500, "q80_abs": 0.0001, "mae_bridge": 0.00005, "mae_carry": 0.00007},
                              "16-60": {"n": 500, "q80_abs": 0.001, "mae_bridge": 0.0005, "mae_carry": 0.0007}}, T0)
    out = {r["ts"] - T0: r for r in G.fill(st, ps, "kraken", "BTCUSDT", T0, T0 + 100, now=T0 + 200)}
    a, b = out[2], out[20]
    assert a["interval"] == "80%" and a["lo"] < a["est_close"] < a["hi"]
    assert math.log(b["hi"] / b["lo"]) > math.log(a["hi"] / a["lo"])


def test_gap_fill_is_isolated_from_the_feature_code():
    from atlas.ai.ml import multires
    src = Path(multires.__file__).read_text(encoding="ascii")
    assert "gapfill1s" not in src and "pred_1s" not in src
