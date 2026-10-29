"""Listings name the session clock. A closed cash session does not open a position or close one."""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.ai.ml.market_islands import desk_attention
from atlas.market.sessions import classify_symbol_venue, listing_market, open_market_venues

ET = ZoneInfo("America/New_York")
SATURDAY = datetime(2026, 10, 24, 12, 0, tzinfo=ET)
CASH_OPEN = datetime(2026, 10, 28, 10, 0, tzinfo=ET)
# Sunday night before Nasdaq 23/5 (effective 2026-12-06 21:00 ET).
BEFORE_OVERNIGHT = datetime(2026, 11, 29, 22, 0, tzinfo=ET)


def test_crypto_stays_open_when_us_cash_is_closed() -> None:
    btc = listing_market("BTC-USD", now=SATURDAY)
    spy = listing_market("SPY", now=SATURDAY)
    assert btc["market_id"] == "CRYPTO_24_7"
    assert btc["market_open"] is True
    assert btc["market_name"]
    assert spy["market_id"] == "US_EQUITIES_ETFS"
    assert spy["market_open"] is False
    assert spy["market_admitted"] is False
    open_ids = {row["market_id"] for row in open_market_venues(SATURDAY) if row["market_open"]}
    assert "CRYPTO_24_7" in open_ids
    assert "US_EQUITIES_ETFS" not in open_ids


def test_us_cash_is_open_during_the_regular_session() -> None:
    spy = listing_market("SPY", now=CASH_OPEN)
    assert spy["market_open"] is True
    assert spy["market_status"] == "REGULAR_SESSION"
    assert spy["market_admitted"] is True


def test_nasdaq_overnight_is_closed_before_its_effective_date() -> None:
    spy = listing_market("SPY", now=BEFORE_OVERNIGHT)
    assert spy["market_open"] is False


def test_listed_futures_roots_use_the_globex_clock() -> None:
    assert classify_symbol_venue("PL") == "CME_COMEX_FUTURES"
    assert classify_symbol_venue("6E") == "CME_COMEX_FUTURES"
    assert classify_symbol_venue("ZN") == "CME_COMEX_FUTURES"
    assert classify_symbol_venue("SPY") == "US_EQUITIES_ETFS"
    platinum = listing_market("PL", now=SATURDAY)
    assert platinum["market_id"] == "CME_COMEX_FUTURES"
    assert platinum["market_open"] is False


def test_attention_looks_at_open_markets_and_leaves_positions() -> None:
    attention = desk_attention(SATURDAY)
    assert attention["execution_permission"] == "none"
    assert attention["closes_other_positions"] is False
    assert attention["may_propose_order"] is False
    assert attention["cash_valid"] is True
    assert attention["scored_book"] == "CRYPTO_24_7"
    assert "CRYPTO_24_7" in attention["open_islands"]
    assert "US_EQUITIES_ETFS" not in {row["market_id"] for row in attention["open_markets"]}
    crypto = next(row for row in attention["open_markets"] if row["market_id"] == "CRYPTO_24_7")
    assert crypto["look_symbol"] == "BTC-USD"


def test_listings_and_catalog_name_the_market_without_flipping_provenance() -> None:
    client = TestClient(app)
    listings = client.get("/api/listings")
    assert listings.status_code == 200
    body = listings.json()
    assert body["execution_permission"] == "none"
    assert body["market_attention"]["closes_other_positions"] is False
    btc = next(row for row in body["listings"] if row["symbol"] == "BTC-USD")
    assert btc["market_id"] == "CRYPTO_24_7"
    assert btc["market_open"] is True
    assert btc["market_name"]
    assert any(row["market_id"] == "CRYPTO_24_7" and row["market_open"] for row in body["open_markets"])

    search = client.get("/api/catalog/search", params={"q": "BTC-USD", "limit": 5})
    assert search.status_code == 200
    page = search.json()
    assert page["source"] == "synthetic_fixture"
    assert page["is_live"] is False
    assert page["execution_permission"] == "none"
    row = next(item for item in page["results"] if item["symbol"] == "BTC-USD")
    assert row["market_id"] == "CRYPTO_24_7"
    assert row["market_open"] is True
    assert row["analytics_source"] == "synthetic_fixture"
    assert row["last_price"] is None or row.get("quote_source")
    assert any(item["market_open"] for item in page["open_markets"])


def test_add_listing_takes_the_market_from_the_clock() -> None:
    from atlas.api.routes_platform import _LIVE_LISTINGS_STATE

    client = TestClient(app)
    instrument_id = "test:spy-clock:v1"
    try:
        response = client.post(
            "/api/listings/action",
            json={
                "instrument_id": instrument_id,
                "symbol": "SPY",
                "name": "Clock check",
                "track": "competition",
                "price": "1.00",
                "action": "add_listing",
            },
        )
        assert response.status_code == 200
        row = next(item for item in response.json()["listings"] if item["instrument_id"] == instrument_id)
        assert row["market_id"] == "US_EQUITIES_ETFS"
        assert row["venue"] == row["market_name"]
        assert row["price"] is None or row.get("quote_source")
    finally:
        _LIVE_LISTINGS_STATE[:] = [row for row in _LIVE_LISTINGS_STATE if row.get("instrument_id") != instrument_id]
