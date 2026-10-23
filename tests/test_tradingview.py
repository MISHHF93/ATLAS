"""TradingView widget map: same symbol and resolution the model is asked to read."""

from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.marketdata.tradingview import describe_chart


def test_flagship_symbols_use_tradingview_listings() -> None:
    btc = describe_chart("BTC-USD", timeframe="1m")
    assert btc["available"] is True
    assert btc["tradingview_symbol"] == "COINBASE:BTCUSD"
    assert btc["interval"] == "1"
    assert btc["bucket_seconds"] == 60
    assert btc["bars_from_tradingview"] is False
    assert btc["studies_readable"] is False
    assert btc["drawings_readable"] is False
    assert btc["crosshair_readable"] is False
    assert btc["execution_permission"] == "none"
    assert "s.tradingview.com/widgetembed/" in str(btc["embed_url"])
    assert "symbol=COINBASE%3ABTCUSD" in str(btc["embed_url"])
    assert "interval=1" in str(btc["embed_url"])
    assert "interval=1S" not in str(btc["embed_url"])

    spy = describe_chart("SPY", timeframe="1D")
    assert spy["tradingview_symbol"] == "AMEX:SPY"
    assert spy["interval"] == "D"

    es = describe_chart("ES", timeframe="1h")
    assert es["tradingview_symbol"] == "CME_MINI:ES1!"
    assert es["interval"] == "60"

    sol = describe_chart("SOL-USD", bucket_seconds=900)
    assert sol["timeframe"] == "15m"
    assert sol["tradingview_symbol"] == "COINBASE:SOLUSD"
    assert sol["interval"] == "15"


def test_fixture_ids_and_one_second_bars_do_not_borrow_a_chart() -> None:
    equity = describe_chart("EQ0001", timeframe="1m")
    assert equity["available"] is False
    assert equity["embed_url"] is None
    assert equity["reason"] == "not_a_tradingview_symbol"

    perp = describe_chart("PERP001-USD", timeframe="5m")
    assert perp["available"] is False
    assert perp["tradingview_symbol"] is None

    seconds = describe_chart("NVDA", timeframe="1s")
    assert seconds["available"] is False
    assert seconds["reason"] == "resolution_not_in_widget"
    assert seconds["tradingview_symbol"] == "NASDAQ:NVDA"
    assert seconds["bucket_seconds"] == 1
    assert seconds["embed_url"] is None
    assert seconds["studies_readable"] is False
    assert seconds["bars_from_tradingview"] is False


def test_companion_widgets_share_the_symbol_and_do_not_feed_the_model() -> None:
    btc = describe_chart("BTC-USD", timeframe="1h")
    ids = [pane["id"] for pane in btc["widgets"]]
    assert ids == ["symbol-info", "technical-analysis", "symbol-profile", "financials", "timeline"]
    for pane in btc["widgets"]:
        assert pane["feeds_model"] is False
        assert pane["execution_permission"] == "none"
        assert "COINBASE%3ABTCUSD" in str(pane["embed_url"])
        assert str(pane["embed_url"]).startswith("https://s.tradingview.com/embed-widget/")
    assert "calendar=0" in str(btc["embed_url"])
    assert "details=1" in str(btc["embed_url"])

    spy = describe_chart("SPY", timeframe="1D")
    assert "calendar=1" in str(spy["embed_url"])
    rating = next(pane for pane in spy["widgets"] if pane["id"] == "technical-analysis")
    assert "1D" in str(rating["embed_url"])
    assert "showIntervalTabs" in str(rating["embed_url"])
    assert "not the ATLAS model" in str(rating["note"])
    fundamentals = next(pane for pane in spy["widgets"] if pane["id"] == "financials")
    assert "adaptive" in str(fundamentals["embed_url"])
    assert spy["information_page"] == "stock"
    assert btc["information_page"] == "listing"
    assert describe_chart("NVDA", timeframe="1D")["information_page"] == "stock"
    assert describe_chart("EQ0001", timeframe="1m")["information_page"] == "none"

    withheld = describe_chart("NVDA", timeframe="1s")
    assert withheld["embed_url"] is None
    assert [pane["id"] for pane in withheld["widgets"]] == ["symbol-info", "symbol-profile", "financials", "timeline"]

    missing = describe_chart("EQ0001", timeframe="1m")
    assert missing["widgets"] == []


def test_tape_lists_both_books() -> None:
    from atlas.marketdata.tradingview import describe_tape

    tape = describe_tape()
    assert tape["symbols"] == ["BTC-USD", "ETH-USD", "SOL-USD", "SPY", "NVDA", "AAPL", "MSFT", "QQQ", "TSLA"]
    assert tape["feeds_model"] is False
    assert tape["origin_accepted"] is False
    assert "embed-widget/ticker-tape/" in str(tape["embed_url"])
    assert "COINBASE%3ABTCUSD" in str(tape["embed_url"])
    assert "AMEX%3ASPY" in str(tape["embed_url"])
    assert "%7Bsymbolname%7D" not in str(tape["embed_url"])

    local = describe_tape("http://127.0.0.1:3000")
    assert local["origin_accepted"] is True
    assert "%7Bsymbolname%7D" in str(local["embed_url"])
    assert "127.0.0.1%3A3000" in str(local["embed_url"])

    foreign = describe_tape("https://evil.example")
    assert foreign["origin_accepted"] is False
    assert "evil.example" not in str(foreign["embed_url"])


def test_qualified_symbols_chart_and_only_readable_listings_reach_the_model() -> None:
    aapl = describe_chart("NASDAQ:AAPL", timeframe="1D")
    assert aapl["tradingview_symbol"] == "NASDAQ:AAPL"
    assert aapl["model_symbol"] == "AAPL"
    assert aapl["available"] is True
    assert "calendar=1" in str(aapl["embed_url"])

    eth = describe_chart("coinbase:ethusd", timeframe="1h")
    assert eth["tradingview_symbol"] == "COINBASE:ETHUSD"
    assert eth["model_symbol"] == "ETH-USD"
    assert eth["model_reads"] == "same_symbol_and_resolution_on_the_public_candle_path"

    es = describe_chart("CME_MINI:ES1!", timeframe="1h")
    assert es["tradingview_symbol"] == "CME_MINI:ES1!"
    assert es["model_symbol"] == "ES"

    binance = describe_chart("BINANCE:BTCUSDT", timeframe="1h")
    assert binance["available"] is True
    assert binance["tradingview_symbol"] == "BINANCE:BTCUSDT"
    assert binance["model_symbol"] is None
    assert binance["model_reads"] == "no_public_candle_series"
    assert "calendar=0" in str(binance["embed_url"])
    assert "no public-candle series" in str(binance["reason_text"])

    withheld = describe_chart("EQ0001", timeframe="1m")
    assert withheld["model_symbol"] is None
    assert withheld["widgets"] == []
    assert describe_chart("AMEX:EQ0001", timeframe="1m")["embed_url"] is None


def test_market_catalogs_stay_on_tradingview_and_reject_a_foreign_origin() -> None:
    from atlas.marketdata.tradingview import describe_markets

    markets = describe_markets("http://localhost:3000")
    assert markets["feeds_model"] is False
    assert markets["execution_permission"] == "none"
    assert markets["bars_from_tradingview"] is False
    assert markets["origin_accepted"] is True
    assert [pane["id"] for pane in markets["widgets"]] == [
        "us-stocks",
        "crypto",
        "etfs",
        "forex",
        "stock-heatmap",
        "crypto-heatmap",
        "crypto-market",
        "economic-calendar",
        "forex-cross-rates",
        "forex-heat-map",
        "us-hotlists",
        "market-overview",
        "market-quotes",
        "tickers",
        "top-stories",
    ]
    for pane in markets["widgets"]:
        assert pane["feeds_model"] is False
        assert pane["execution_permission"] == "none"
        assert str(pane["embed_url"]).startswith("https://s.tradingview.com/embed-widget/")
    stock = markets["widgets"][0]
    crypto = markets["widgets"][1]
    etf = markets["widgets"][2]
    forex = markets["widgets"][3]
    assert "screener/" in str(stock["embed_url"])
    assert "most_capitalized" in str(stock["embed_url"])
    assert "%22market%22%3A%22us%22" in str(stock["embed_url"])
    assert "%7Bsymbolname%7D" in str(stock["embed_url"])
    assert "%22market%22%3A%22crypto%22" in str(crypto["embed_url"])
    assert "top_gainers" in str(crypto["embed_url"])
    assert "etf-heatmap/" in str(etf["embed_url"])
    assert "AllUSEtf" in str(etf["embed_url"])
    assert "%7Btvexchange%7D" in str(etf["embed_url"])
    assert "%22market%22%3A%22forex%22" in str(forex["embed_url"])
    by_id = {pane["id"]: pane for pane in markets["widgets"]}
    assert "stock-heatmap/" in str(by_id["stock-heatmap"]["embed_url"])
    assert "SPX500" in str(by_id["stock-heatmap"]["embed_url"])
    assert "crypto-coins-heatmap/" in str(by_id["crypto-heatmap"]["embed_url"])
    assert "24h_close_change" in str(by_id["crypto-heatmap"]["embed_url"])
    assert "crypto-mkt-screener/" in str(by_id["crypto-market"]["embed_url"])
    assert "embed-widget/events/" in str(by_id["economic-calendar"]["embed_url"])
    assert "forex-cross-rates/" in str(by_id["forex-cross-rates"]["embed_url"])
    assert "forex-heat-map/" in str(by_id["forex-heat-map"]["embed_url"])
    assert "hotlists/" in str(by_id["us-hotlists"]["embed_url"])
    assert "%22exchange%22%3A%22US%22" in str(by_id["us-hotlists"]["embed_url"])
    assert "market-overview/" in str(by_id["market-overview"]["embed_url"])
    assert "COINBASE%3ABTCUSD" in str(by_id["market-overview"]["embed_url"])
    assert "market-quotes/" in str(by_id["market-quotes"]["embed_url"])
    assert "tickers/" in str(by_id["tickers"]["embed_url"])
    assert "feedMode" in str(by_id["top-stories"]["embed_url"])
    assert "all_symbols" in str(by_id["top-stories"]["embed_url"])
    assert "Seasonal Chart" in str(markets["note"])
    for pane in markets["widgets"]:
        assert "interval=1S" not in str(pane["embed_url"])

    btc = describe_chart("BTC-USD", timeframe="1m")
    assert [pane["id"] for pane in btc["symbol_artifacts"]] == [
        "symbol-overview",
        "mini-symbol-overview",
        "single-quote",
    ]
    for pane in btc["symbol_artifacts"]:
        assert pane["feeds_model"] is False
        assert pane["execution_permission"] == "none"
        assert "COINBASE%3ABTCUSD" in str(pane["embed_url"])
    assert describe_chart("EQ0001", timeframe="1m")["symbol_artifacts"] == []

    foreign = describe_markets("https://evil.example/phish")
    assert foreign["origin_accepted"] is False
    for pane in foreign["widgets"]:
        assert "evil.example" not in str(pane["embed_url"])
        assert "%7Bsymbolname%7D" not in str(pane["embed_url"])
        assert "%7Btvexchange%7D" not in str(pane["embed_url"])


def test_http_map_and_chart_read_name_the_same_widget() -> None:
    client = TestClient(app)
    mapped = client.get("/api/market/tradingview", params={"symbol": "ETH-USD", "timeframe": "1h"})
    assert mapped.status_code == 200
    body = mapped.json()
    assert body["tradingview_symbol"] == "COINBASE:ETHUSD"
    assert body["interval"] == "60"
    assert body["bars_from_tradingview"] is False

    read = client.get("/api/ml/chart-read", params={"symbol": "ETH-USD", "bucket_seconds": 3600})
    assert read.status_code == 200
    body_read = read.json()
    picture = body_read["tradingview"]
    assert picture["tradingview_symbol"] == "COINBASE:ETHUSD"
    assert picture["interval"] == "60"
    assert picture["execution_permission"] == "none"
    track = body_read["chart_track"]
    assert track["picture"] == "COINBASE:ETHUSD"
    assert track["interval"] == "60"
    # An available widget does not establish a matching model feed when the
    # model is reading fixture or shortened ring-buffer history.
    assert track["follows"] == "picture_only"
    assert track["bars_from_tradingview"] is False
    assert track["execution_permission"] == "none"
    # The shared ring may already hold a shorter ETH tape from an earlier paper ingest.
    # The reader then forms the finest bucket that still has four bars. The widget stays on 1h.
    used_bucket = int(read.json()["active"]["bucket_seconds"])
    assert used_bucket == 3600 or (used_bucket < 3600 and 3600 % used_bucket == 0)
    assert "technical-analysis" in [pane["id"] for pane in picture["widgets"]]

    tape = client.get("/api/market/tradingview/tape")
    assert tape.status_code == 200
    assert tape.json()["symbols"][0] == "BTC-USD"
    assert tape.json()["feeds_model"] is False

    qualified = client.get("/api/market/tradingview", params={"symbol": "NASDAQ:MSFT", "timeframe": "1D"})
    assert qualified.status_code == 200
    assert qualified.json()["model_symbol"] == "MSFT"
    assert qualified.json()["tradingview_symbol"] == "NASDAQ:MSFT"
    assert qualified.json()["execution_permission"] == "none"

    markets = client.get("/api/market/tradingview/markets", params={"origin": "http://127.0.0.1:3000"})
    assert markets.status_code == 200
    catalog = markets.json()
    assert catalog["feeds_model"] is False
    assert catalog["execution_permission"] == "none"
    assert catalog["widgets"][0]["id"] == "us-stocks"
    assert catalog["widgets"][-1]["id"] == "top-stories"
    assert len(catalog["widgets"]) == 15

    blocked = client.get("/api/market/tradingview/markets", params={"origin": "https://evil.example"})
    assert blocked.status_code == 200
    assert blocked.json()["origin_accepted"] is False
    assert "evil.example" not in blocked.text
