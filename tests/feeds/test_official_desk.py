"""Official desk: Yahoo is not a proof source, and the status report submits nothing."""
from __future__ import annotations

import time

from atlas.feeds.core import FeedBar
from atlas.feeds.feed import AtlasFeed
from atlas.feeds.official import counts_for_proof, daily_frame, desk_status
from atlas.feeds.store import FeedStore


def test_yahoo_does_not_count_and_official_names_do():
    assert counts_for_proof("public_market_candles", "yahoo_chart_public") is False
    assert counts_for_proof("public_market_candles", "alpaca_crypto") is True
    assert counts_for_proof("synthetic_fixture_training", "alpaca_crypto") is False


def test_daily_frame_reads_official_bars_only(tmp_path):
    store = FeedStore(tmp_path / "f.sqlite")
    feed = AtlasFeed(store=store, clock=lambda: 2_000_000.0)
    start = int(time.time()) - 40 * 86400
    start -= start % 86400
    yahoo = [FeedBar("USD_CAD", "1d", start + i * 86400, 1.3, 1.4, 1.2, 1.35, 0, "yahoo", start + i * 86400, True, "USDCAD=X") for i in range(30)]
    official = [FeedBar("USD_CAD", "1d", start + i * 86400, 1.3, 1.4, 1.2, 1.31, 0, "boc_valet", start + i * 86400, True, "FXUSDCAD") for i in range(30)]
    store.ingest(yahoo + official)
    frame = daily_frame("USD_CAD", feed, min_bars=21)
    assert frame is not None
    assert frame["feed_origin"] == "boc_valet"
    assert frame["data_mode"] == "public_market_candles"
    assert abs(frame["candles"][-1]["close"] - 1.31) < 1e-9


def test_desk_status_submits_nothing():
    desk = desk_status({})
    assert desk["execution_permission"] == "none"
    assert desk["orders_submitted"] == 0
    assert desk["may_propose_order"] is False
    assert desk["live_endpoint"] == "refused"
    assert desk["paper_broker"] == "internal_simulator"
    assert "yahoo" not in desk["keyless_official"]
    assert "alpaca_crypto" in desk["keyless_official"]
    assert "submit_order" not in desk["notice"]
