"""Library quotes stay off the directory and off the order path."""

from fastapi.testclient import TestClient

from atlas.api.app import app
from atlas.marketdata.library_quotes import _from_spark, select_symbols


def test_spark_parser_reads_a_yahoo_last_print() -> None:
    body = {
        "spark": {
            "result": [
                {
                    "symbol": "NVDA",
                    "response": [
                        {
                            "meta": {
                                "symbol": "NVDA",
                                "regularMarketPrice": 216.41,
                                "regularMarketChangePercent": -2.505,
                                "regularMarketTime": 1792677298,
                            }
                        }
                    ],
                }
            ]
        }
    }
    rows = _from_spark(body)
    assert rows[0]["yahoo_symbol"] == "NVDA"
    assert rows[0]["price"] == 216.41
    assert rows[0]["delayed"] is True
    assert rows[0]["execution_permission"] == "none"


def test_fillers_and_unlisted_names_are_not_quoted() -> None:
    chosen = select_symbols(["NVDA", "EQ0001", "PERP001-USD", "SPACEX", "BTC-USD", "ES", "NVDA"])
    assert chosen[0] == "NVDA"
    assert "EQ0001" not in chosen
    assert "PERP001-USD" not in chosen
    assert "SPACEX" not in chosen
    assert "BTC-USD" in chosen
    assert "ES" in chosen
    assert chosen.count("NVDA") == 1


def test_quote_route_stays_off_under_pytest_and_does_not_rewrite_the_directory() -> None:
    client = TestClient(app)
    before = client.get("/api/catalog/search", params={"q": "NVDA", "limit": 5}).json()
    stored = next(item for item in before["results"] if item["symbol"] == "NVDA")["last_price"]
    quoted = client.get("/api/catalog/quotes", params={"symbols": "NVDA,AAPL,BTC-USD,SPACEX,EQ0001"})
    assert quoted.status_code == 200
    body = quoted.json()
    assert body["quoted"] == 0
    assert body["quotes"] == []
    assert body["execution_permission"] == "none"
    assert "submit_order" not in quoted.text
    after = client.get("/api/catalog/search", params={"q": "NVDA", "limit": 5}).json()
    assert next(item for item in after["results"] if item["symbol"] == "NVDA")["last_price"] == stored
    disney = client.get("/api/catalog/search", params={"q": "DIS", "limit": 5}).json()
    assert next(item for item in disney["results"] if item["symbol"] == "DIS")["last_price"] in (0, None)
    assert after["is_live"] is False
