"""Multi-resolution features: causality (no lookahead), alignment of 1m/5m/15m/1h on the 15m decision clock, honest NaNs."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from atlas.ai.ml import multires as M
from atlas.feeds.trades1s import TradeBarStore

NY = ZoneInfo("America/New_York")
T0 = 1_792_000_000 // 3600 * 3600          # an hour boundary
N_MIN = 4 * 24 * 60


def synth_1m(seed=1, n=N_MIN, skip=()):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.0007, n)))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.0004, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.0004, n))
    v = rng.uniform(1, 10, n)
    rows = [(T0 + 60 * i, o[i], h[i], l[i], c[i], v[i]) for i in range(n) if i not in skip]
    return rows


def agg(rows, dur):
    by = {}
    for r in rows:
        by.setdefault(r[0] // dur * dur, []).append(r)
    out = []
    for k in sorted(by):
        g = by[k]
        if len(g) * 60 != dur:
            continue                                   # only complete buckets, like a real provider's closed bars
        out.append((k, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)))
    return out


def make_inputs(rows=None):
    rows = rows or synth_1m()
    return M.Inputs("BTCUSDT", s1m=M.Bars.from_rows("1m", rows), s15=M.Bars.from_rows("15m", agg(rows, 900)), s1h=M.Bars.from_rows("1h", agg(rows, 3600)))


def truncate(inp, T):
    def cut(b):
        if b is None:
            return None
        k = b.n_closed(T)
        return M.Bars(b.interval, b.ts[:k], b.o[:k], b.h[:k], b.l[:k], b.c[:k], b.v[:k])
    return M.Inputs(inp.instrument, cut(inp.s1m), cut(inp.s15), cut(inp.s1h))


def same(a, b):
    assert a.keys() == b.keys()
    for k in a:
        assert (math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k], k


def test_grid_is_900s_and_matches_et_quarter_hours_across_dst():
    for start in (1_772_000_000, 1_794_000_000):       # one in EST, one in EDT
        g = M.decision_grid(start, start + 3 * 86400)
        assert all(t % 900 == 0 for t in g) and all(b - a == 900 for a, b in zip(g, g[1:]))
        assert all(datetime.fromtimestamp(t, NY).minute in (0, 15, 30, 45) for t in g)
    assert M.decision_grid(901, 1801) == [1800]


def test_truncation_invariance_no_lookahead():
    inp = make_inputs()
    for T in M.decision_grid(T0 + 3 * 86400, T0 + 3 * 86400 + 20 * 900):
        same(M.features_at(inp, T), M.features_at(truncate(inp, T), T))


def test_mutating_anything_after_T_changes_nothing():
    inp = make_inputs()
    T = T0 + 2 * 86400 + 5 * 900
    ref = M.features_at(inp, T)

    def poison(b):
        m = b.ts >= T - b.dur + 1                       # every bar that is not closed by T (end > T)
        c = b.c.copy(); h = b.h.copy(); v = b.v.copy()
        c[m], h[m], v[m] = 1e9, 2e9, 1e9
        return M.Bars(b.interval, b.ts, b.o, h, b.l, c, v)
    bad = M.Inputs(inp.instrument, poison(inp.s1m), poison(inp.s15), poison(inp.s1h))
    same(ref, M.features_at(bad, T))


def test_1m_5m_15m_1h_consistency_on_the_decision_clock():
    rows = synth_1m()
    inp = make_inputs(rows)
    close = {r[0]: r[4] for r in rows}
    T = T0 + 2 * 86400                                  # on an hour boundary so every layer has a bar ending at T
    f = M.features_at(inp, T)
    c = lambda end: close[end - 60]                     # close of the last 1m bar of a period ending at ``end``
    assert math.isclose(f["m15_ret1"], math.log(c(T) / c(T - 900)), rel_tol=1e-12)
    assert math.isclose(f["m15_ret4"], math.log(c(T) / c(T - 3600)), rel_tol=1e-12)
    assert math.isclose(f["h1_ret1"], math.log(c(T) / c(T - 3600)), rel_tol=1e-12)
    assert math.isclose(f["m5_ret1"], math.log(c(T) / c(T - 300)), rel_tol=1e-12)
    assert math.isclose(f["m1_ret15"], math.log(c(T) / c(T - 900)), rel_tol=1e-12)
    # 15m return is the sum of its three 5m returns
    parts = sum(math.log(c(T - 300 * i) / c(T - 300 * (i + 1))) for i in range(3))
    assert math.isclose(f["m15_ret1"], parts, rel_tol=1e-9)


def test_missing_minute_makes_the_window_nan_instead_of_being_filled():
    skip = {N_MIN - 1000}
    rows = synth_1m(skip=skip)
    inp = make_inputs(rows)
    gap_ts = T0 + (N_MIN - 1000) * 60
    T = (gap_ts // 900 + 1) * 900
    assert T - 900 <= gap_ts < T
    f = M.features_at(inp, T)
    assert math.isnan(f["m1_ret15"])


def test_stale_series_gives_nan_not_last_value():
    inp = make_inputs()
    T = T0 + N_MIN * 60 + 6 * 3600                      # six hours after the last bar
    f = M.features_at(inp, T)
    assert all(math.isnan(f[k]) for k in M.GROUP_FEATURES["m15"] + M.GROUP_FEATURES["m1"])


def test_no_spread_feature_without_bid_ask():
    assert M.SPREAD_AVAILABLE is False
    assert not any("spread" in n for n in M.FEATURE_NAMES)


def test_flow_and_trade_intensity_only_use_collector_alive_minutes(tmp_path: Path):
    st = TradeBarStore(tmp_path / "t.sqlite")
    base = T0 + 3 * 86400
    rows = []
    for i in range(30 * 60):                            # 30 minutes of one trade per second on kraken BTC
        rows.append(("kraken", "BTCUSDT", base + i, 100, 100.1, 99.9, 100.0, 1.0, 0.7, 0.3, 1, 100.0))
        rows.append(("kraken", "ETHUSDT", base + i, 10, 10.1, 9.9, 10.0, 1.0, 0.5, 0.5, 1, 10.0))
    st.write_bars(rows)
    st.rollup_minutes(base + 30 * 60)
    inp = M.load_inputs(st, "BTCUSDT", provider="kraken", start=base, end=base + 3600, trade_store=st, venue="kraken", intervals=())
    T = base + 20 * 60
    f = M.features_at(inp, T)
    assert f["f_ofi15"] > 0 and abs(f["f_ofi15"] - 0.4) < 1e-9          # (0.7 - 0.3) / 1.0
    assert f["f_active15"] > 0.99
    # after the collector stopped there is no flow, so those features are NaN instead of zero-filled
    f2 = M.features_at(inp, base + 50 * 60)
    assert math.isnan(f2["f_ofi15"]) or math.isnan(f2["f_ti15"])
    # truncation invariance for the 1s / flow layers
    full = M.features_at(inp, T)
    cut = M.Inputs(inp.instrument, flow=M.Flow(*(getattr(inp.flow, n)[inp.flow.ts + 60 <= T] for n in ("ts", "vol", "buy", "sell", "ntr", "vnum", "active_s", "close")),
                                                alive_ts=inp.flow.alive_ts[inp.flow.alive_ts + 60 <= T]),
                   secs=M.Secs(*(getattr(inp.secs, n)[inp.secs.ts + 1 <= T] for n in ("ts", "c", "vol", "buy", "sell", "ntr"))))
    same(full, M.features_at(cut, T))


def test_multires_never_reads_predicted_gap_fill():
    src = Path(M.__file__).read_text(encoding="ascii")
    assert "gapfill1s" not in src and "pred_1s" not in src and "nowcast_xgb" not in src
