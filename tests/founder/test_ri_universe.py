"""Item 3: survivorship-safe point-in-time universe."""
from datetime import date

import numpy as np
import pandas as pd

from atlas.marketdata.pit.universe import PITUniverse, survivorship_check


def _u():
    u = PITUniverse()
    for s, l in (("AAA", "2010-01-01"), ("BBB", "2012-01-01"), ("DEAD", "2011-01-01"), ("NEW", "2024-06-01")):
        u.add_security(s, l); u.add_member("TSX60", s, l)
    u.delist("DEAD", "2020-03-15", "bankruptcy", -1.0)
    u.remove_member("TSX60", "BBB", "2019-01-01")
    u.set_sector("AAA", "Energy", "2010-01-01"); u.set_sector("AAA", "Utilities", "2021-01-01")
    return u


def test_delisted_kept_and_historical_membership():
    u = _u()
    assert u.members("TSX60", "2018-01-01") == ["AAA", "BBB", "DEAD"]
    assert u.members("TSX60", "2023-01-01") == ["AAA"]
    assert "DEAD" in u.ever_listed("2015-01-01", "2025-01-01") and "DEAD" not in u.tradable("2021-01-01")
    assert "NEW" not in u.members("TSX60", "2023-01-01")


def test_sector_as_of():
    u = _u()
    assert u.sector_of("AAA", "2015-01-01") == "Energy" and u.sector_of("AAA", "2022-01-01") == "Utilities"


def test_known_at_blocks_late_knowledge():
    u = PITUniverse()
    u.add_security("X", "2015-01-01"); u.add_member("IDX", "X", "2015-01-01", known_at="2016-01-01")
    assert u.members("IDX", "2015-06-01") == [] and u.members("IDX", "2015-06-01", known_as_of="2016-02-01") == ["X"]


def test_consolidation_adjustment_is_point_in_time():
    u = PITUniverse()
    u.add_security("JR", "2018-01-01", venue="TSXV")
    u.add_corp_action("JR", "2020-01-10", "consolidation", 0.1)   # 1-for-10
    bars = pd.DataFrame({"close": [0.10, 0.11, 1.10, 1.20], "volume": [1e6, 1e6, 1e5, 1e5]},
                        index=pd.to_datetime(["2020-01-08", "2020-01-09", "2020-01-10", "2020-01-13"]))
    before = u.adjust("JR", bars, "2020-01-09")
    assert before.close.iloc[0] == 0.10            # future consolidation not applied
    after = u.adjust("JR", bars, "2020-02-01")
    assert np.isclose(after.close.iloc[1], 1.10) and np.isclose(after.volume.iloc[0], 1e5)
    assert abs(after.close.pct_change().iloc[2]) < 1e-9


def test_delisting_return_and_survivorship_check():
    u = _u()
    close = pd.Series([10.0, 9.0, 8.0], index=pd.to_datetime(["2020-03-11", "2020-03-12", "2020-03-13"]))
    r = u.returns_with_delisting("DEAD", close)
    assert r.iloc[-1] == -1.0
    bad = survivorship_check(u, ["AAA", "BBB"], "2015-01-01", "2024-01-01")
    assert not bad["ok"] and bad["missing_delisted"] == ["DEAD"]
    assert survivorship_check(u, ["AAA", "BBB", "DEAD"], "2015-01-01", "2024-01-01")["ok"]
