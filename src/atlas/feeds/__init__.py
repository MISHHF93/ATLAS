"""ATLAS unified feed layer. Public API (see docs/data-feeds.md):

    from atlas.feeds import get_feed
    feed = get_feed()                                   # var/feeds/atlas_feed.sqlite (ATLAS_FEED_DB)
    feed.bars("BTCUSDT", "15m", start, end, as_of=None) # authoritative confirmed bars (list[FeedBar])
    feed.quality_flags("SPY", "15m")                    # () == ok; else predict() abstains
    feed.health()                                       # providers + series freshness (health endpoint payload)
    feed.instruments.get("SPY")                         # instrument master record
"""
from .core import Capabilities, FeedBar, FeedObservation, FeedQuote, FeedTrade, Health, ProviderAdapter, ProviderError
from .feed import AtlasFeed, ProviderRegistry, get_feed
from .instruments import Instrument, InstrumentMaster
from .quality import Quality, assess, find_gaps
from .store import FeedStore

__all__ = ["AtlasFeed", "Capabilities", "FeedBar", "FeedObservation", "FeedQuote", "FeedStore", "FeedTrade", "Health",
           "Instrument", "InstrumentMaster", "ProviderAdapter", "ProviderError", "ProviderRegistry", "Quality", "assess",
           "find_gaps", "get_feed", "udf"]
from . import udf  # noqa: E402
