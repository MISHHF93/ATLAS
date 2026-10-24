"""Section 22 macro (keyless FRED, release-lagged) + HTF context: no lookahead."""
from datetime import date, datetime, timezone

import numpy as np

from atlas.feeds.providers import fred_public as F
from atlas.feeds.store import FeedStore
from atlas.ml import context as C
from atlas.ml.evolution import GENES, feature_list, gid

CSV = "observation_date,DGS10\n2026-10-15,4.10\n2026-10-16,.\n2026-10-19,4.20\n"


def ts(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def test_release_lags_are_conservative():
    assert F._lag_daily(date(2026, 10, 15)) == date(2026, 10, 17)   # Thu -> Fri publish -> usable Sat
    assert F._lag_daily(date(2026, 10, 16)) == date(2026, 10, 20)   # Fri -> Mon publish -> usable Tue
    assert F._lag_monthly(date(2026, 9, 1)) == date(2026, 11, 1)
    assert F._lag_monthly(date(2026, 12, 1)) == date(2027, 2, 1)
    assert F._lag_weekly_h10(date(2026, 10, 16)) == date(2026, 10, 26)


def test_parse_skips_missing_and_stamps_availability():
    obs = F.parse_csv("DGS10", CSV, receipt_time=1)
    assert [(o.date, o.value, o.realtime_start) for o in obs] == [("2026-10-15", 4.10, "2026-10-17"), ("2026-10-19", 4.20, "2026-10-21")]
    assert all(o.provider == F.PROVIDER for o in obs)


def test_macro_frame_never_uses_unpublished_values(tmp_path):
    st = FeedStore(tmp_path / "f.sqlite")
    assert st.ingest_observations(F.parse_csv("DGS10", CSV, 1)) == 2
    mf = C.macro_frame(st, [ts("2026-10-16T23:00:00"), ts("2026-10-17T00:00:00"), ts("2026-10-20T23:59:00"), ts("2026-10-21T00:00:00")])
    v = mf.m_dgs10.to_numpy()
    assert np.isnan(v[0]) and v[1] == 4.10 and v[2] == 4.10 and v[3] == 4.20


def test_macro_gated_when_no_observations(tmp_path):
    mf = C.macro_frame(FeedStore(tmp_path / "e.sqlite"), [ts("2026-10-20T00:00:00")])
    assert mf.isna().all().all()


class B:
    def __init__(self, start, c):
        self.start, self.duration, self.open, self.high, self.low, self.close = start, 3600, c, c + 1, c - 1, c


def test_htf_uses_only_closed_days():
    t0 = ts("2026-01-01T00:00:00")
    bars = [B(t0 + i * 3600, 100 + i) for i in range(24 * 10)]
    h = C.htf_frame(bars)
    # the 23:00 bar of day 1 closes day 1, so its row may see day 1; the 22:00 bar may only see day 0.
    d2_last, d2_prev = t0 + 2 * 86400 - 3600, t0 + 2 * 86400 - 7200
    assert np.isclose(h.loc[d2_last, "d1_ret1"], np.log((100 + 47) / (100 + 23)))
    assert np.isnan(h.loc[d2_prev, "d1_ret1"])          # only day 0 closed -> no daily return yet


def test_context_gene():
    assert GENES["context"] == ("none", "htf", "macro", "htf_macro")
    base = {"model": "hgb", "features": "full", "regime": "none", "bar_type": "time"}
    assert gid(base).endswith("context=none")
    f = feature_list({**base, "context": "htf_macro"})
    assert set(C.HTF_FEATURES) <= set(f) and set(C.MACRO_FEATURES) <= set(f)
    assert not set(C.MACRO_FEATURES) & set(feature_list(base))
