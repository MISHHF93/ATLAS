"""Offline candles for the market candles endpoint.

These values are deterministic fixtures for wiring tests and local simulation.
"""

from atlas.market.schemas import Candle, CandlePage

_FIXTURES: dict[tuple[str, str], list[Candle]] = {
    ("BTC-USD", "1h"): [
        Candle(
            venue="fixture",
            symbol="BTC-USD",
            interval="1h",
            open_time="2026-10-19T00:00:00Z",
            open="67000.00",
            high="67250.00",
            low="66800.00",
            close="67110.50",
            volume="12.5",
            source="fixture",
        ),
        Candle(
            venue="fixture",
            symbol="BTC-USD",
            interval="1h",
            open_time="2026-10-19T01:00:00Z",
            open="67110.50",
            high="67400.00",
            low="67050.00",
            close="67320.00",
            volume="9.25",
            source="fixture",
        ),
    ]
}


def candle_page(symbol: str, interval: str) -> CandlePage:
    candles = _FIXTURES.get((symbol, interval), [])
    return CandlePage(symbol=symbol, interval=interval, source="fixture", candles=candles)
