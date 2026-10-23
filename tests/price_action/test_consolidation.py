"""Shim equivalence: the legacy call sites now delegate to price_action and must match the frozen
pre-consolidation implementations (legacy_reference.py) on seeded synthetic series, flat runs included."""
from types import SimpleNamespace

import numpy as np
import pytest

from atlas.api import udf
from atlas.features import microstructure, pine_features
from atlas.mcp.trading import research
from tests.price_action import legacy_reference as ref


def _series(seed, n=120, flat=True):
    r = np.random.default_rng(seed)
    c = 100 + np.cumsum(r.normal(0, 1, n))
    if flat:
        c[30:50] = c[30]
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + r.uniform(0, 1, n) * (np.arange(n) % 7 != 0)
    l = np.minimum(o, c) - r.uniform(0, 1, n) * (np.arange(n) % 5 != 0)
    return [list(map(float, v)) for v in (o, h, l, c)]


def _eq(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert (x is None and y is None) or x == pytest.approx(y, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("n", [1, 5, 14, 20])
def test_shims_match_legacy(seed, n):
    o, h, l, c = _series(seed)
    flat = [5.0] * 40
    for xs in (c, flat, c[: n - 1], c[:n]):
        _eq(pine_features._ema(xs, n), ref.pine_ema(xs, n))
        _eq(research._ema(xs, n), ref.research_ema(xs, n))
        _eq(pine_features._rsi(xs, n), ref.pine_rsi(xs, n))
        _eq(research._rsi(xs, n), ref.research_rsi(xs, n))
    _eq(pine_features.average_true_range(h, l, c, n), ref.pine_average_true_range(h, l, c, n))
    bars = [SimpleNamespace(high=a, low=b, close=d) for a, b, d in zip(h, l, c)]
    _eq(research._atr(bars, n), ref.research_atr(bars, n))
    assert microstructure.compute_atr(h, l, c, window=n) == pytest.approx(ref.micro_compute_atr(h, l, c, window=n), rel=1e-12)
    rows = [(i, a, b, d, e, 1.0) for i, (a, b, d, e) in enumerate(zip(o, h, l, c))]
    for idx in (0, 1, 5, 13, 14, 60, len(rows) - 1):
        assert udf._atr(rows, idx) == pytest.approx(ref.udf_atr(rows, idx), rel=1e-12, abs=1e-12)


def test_compute_atr_errors_preserved():
    with pytest.raises(ValueError):
        microstructure.compute_atr([1, 2], [0, 1], [1, 2], window=14)


def test_legacy_price_zone_adapts_to_lifecycle_zone():
    from datetime import datetime, timezone

    from atlas.features.zones import PriceZone, ZoneBoundary, ZoneDirection, ZoneType

    pz = PriceZone(zone_id="z1", symbol="SPY", zone_type=ZoneType.OPENING, direction=ZoneDirection.BULLISH,
                   boundary=ZoneBoundary(high=102.0, low=99.0), start_time=datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc),
                   end_time=datetime(2026, 1, 5, 15, 30, tzinfo=timezone.utc), metadata={}, execution_permission="none")
    z = pz.to_lifecycle_zone(3600)
    assert (z.lower_bound, z.upper_bound, z.direction, z.zone_type) == (99.0, 102.0, "bullish", "legacy_opening")
    assert z.height == 3.0 and z.midpoint == 100.5 and z.source_event == "z1"


def _syn_df(n=40, seed=3):
    """Synthetic fixture (tests only)."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.5, n)); c[-1] = c[-2] + 6
    o = np.r_[c[0], c[:-1]]
    ts = pd.date_range("2026-01-05 14:30", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": o, "high": np.maximum(o, c) + 0.3, "low": np.minimum(o, c) - 0.3, "close": c})


def test_zone_engine_facade_matches_dual_band_detector_and_builds_all_boxes():
    from atlas.features.price_action.detectors import DualBollingerDetector
    from atlas.features.price_action.engine import PriceActionEngine
    from atlas.features.price_action.zones import Zone
    from atlas.features.zones import ZoneDirection, ZoneEngine, ZoneType, _bars_from_df

    df = _syn_df()
    eng = ZoneEngine("spy")
    zs = eng.update_zones(df, session_start=df["timestamp"].iloc[0].to_pydatetime(), event_time=df["timestamp"].iloc[5].to_pydatetime())
    bo = zs[ZoneType.BREAKOUT]
    pa = PriceActionEngine("SPY", 3600)
    last = [e for b in _bars_from_df(df) for e in pa.update(b) if isinstance(e, Zone) and e.zone_type == "dual_band_breakout"]
    assert bo is not None and bo.direction is ZoneDirection.BULLISH
    assert last and last[-1].formed_at == int(df["timestamp"].iloc[-1].timestamp())
    assert (last[-1].lower_bound, last[-1].upper_bound) == (bo.boundary.low, bo.boundary.high)
    op = zs[ZoneType.OPENING]
    assert op.boundary.high == df["high"].iloc[0] and op.execution_permission == "none"
    assert zs[ZoneType.EVENT].boundary.low == df["low"].iloc[5]
    assert op.to_lifecycle_zone(3600).zone_type == "legacy_opening"


def test_zone_engine_anchor_rule_unchanged_vs_frozen_reference():
    from atlas.features.zones import ZoneEngine
    from tests.price_action.legacy_reference import legacy_anchor_box

    df = _syn_df(60, seed=9)
    for k in range(3, len(df) + 1):
        new, old = ZoneEngine("SPY").detect_anchor_box(df.iloc[:k]), legacy_anchor_box(df.iloc[:k])
        assert (new is None) == (old is None)
        if new:
            assert (new.zone_id, new.direction.name, new.boundary.high, new.boundary.low) == old
