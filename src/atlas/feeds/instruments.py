"""Instrument master (spec 2.1). One record per ATLAS instrument id; provider symbols + priority live here."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Instrument:
    id: str
    asset_class: str            # crypto | equity | etf | index | fx | future | option | macro
    venue: str
    currency: str
    timezone: str
    session: str                # "24x7" | "us_equity_rth" | "cme_globex" | "fx_24x5"
    tick_size: float
    lot_size: float
    multiplier: float = 1.0
    status: str = "active"      # active | halted | delisted
    provider_symbols: dict = field(default_factory=dict)   # provider -> symbol/conid
    provider_priority: tuple = ()                          # failover order
    sanity_providers: tuple = ()                           # cross-checks (may be proxies, e.g. USD vs USDT)
    description: str = ""

    def as_dict(self):
        d = asdict(self)
        d["provider_priority"], d["sanity_providers"] = list(self.provider_priority), list(self.sanity_providers)
        return d


def _crypto(sym, base, tick):
    return Instrument(sym, "crypto", "BINANCE", "USDT", "UTC", "24x7", tick, 0.00001,
                      provider_symbols={"alpaca_crypto": f"{base}/USD", "binance": sym, "okx": f"{base}-USDT", "kraken": f"{'XBT' if base == 'BTC' else base}USDT",
                                        "coinbase": f"{base}-USD", "bybit": sym},
                      provider_priority=("alpaca_crypto", "binance", "okx", "bybit", "kraken"), sanity_providers=("coinbase", "kraken", "okx"),
                      description=f"{base}/USDT spot")


from .stock_providers import equity_priority as _equity_priority  # noqa: E402

_EQUITY_PRIORITY = _equity_priority({})


def _etf(sym, desc):
    return Instrument(sym, "etf", "ARCX" if sym == "SPY" else ("XNAS" if sym == "QQQ" else "ARCX"), "USD", "America/New_York",
                      "us_equity_rth", 0.01, 1, provider_symbols={p: sym for p in ("alpaca", "tiingo", "polygon", "finnhub", "twelvedata",
                                                                                     "alphavantage", "questrade", "yahoo")},
                      provider_priority=_EQUITY_PRIORITY,
                      sanity_providers=("yahoo", "alpaca"), description=desc)


from .contracts import CONTRACT_TERMS as _CT  # noqa: E402  single source for futures terms
_ES_TICK, _ES_MULT = _CT["ES"]

DEFAULT_INSTRUMENTS = {i.id: i for i in (
    _crypto("BTCUSDT", "BTC", 0.01), _crypto("ETHUSDT", "ETH", 0.01),
    _etf("SPY", "SPDR S&P 500 ETF"), _etf("QQQ", "Invesco QQQ Trust"), _etf("IWM", "iShares Russell 2000 ETF"),
    Instrument("EUR_USD", "fx", "OTC", "USD", "UTC", "fx_24x5", 0.00001, 1,
               provider_symbols={"oanda": "EUR_USD", "twelvedata": "EUR/USD", "ecb_fx": "EUR_USD", "yahoo": "EURUSD=X"},
               provider_priority=("oanda", "twelvedata", "finnhub", "ecb_fx", "yahoo"),
               sanity_providers=("ecb_fx",), description="EUR/USD spot FX"),
    Instrument("USD_CAD", "fx", "OTC", "CAD", "UTC", "fx_24x5", 0.00001, 1,
               provider_symbols={"oanda": "USD_CAD", "twelvedata": "USD/CAD", "boc_valet": "FXUSDCAD", "ecb_fx": "USD_CAD", "yahoo": "USDCAD=X"},
               provider_priority=("oanda", "twelvedata", "finnhub", "boc_valet", "ecb_fx", "yahoo"),
               sanity_providers=("boc_valet", "ecb_fx"), description="USD/CAD spot FX"),
    Instrument("ES", "future", "XCME", "USD", "America/Chicago", "cme_globex", _ES_TICK, 1, _ES_MULT,
               provider_symbols={"databento": "ES.c.0", "yahoo": "ES=F"}, provider_priority=("databento", "yahoo"),
               description="E-mini S&P 500 continuous front month"),
)}


def _default_universe() -> dict:
    """The original research instruments plus every symbol the UI lists (atlas.feeds.universe)."""
    from .universe import ui_instruments
    return {**ui_instruments(), **DEFAULT_INSTRUMENTS}


class InstrumentMaster:
    def __init__(self, instruments: dict | None = None):
        self._by_id = dict(instruments or _default_universe())

    @classmethod
    def load(cls, path: str | Path | None = None):
        m = cls()
        if path and Path(path).exists():
            for d in json.loads(Path(path).read_text()):
                for k in ("provider_priority", "sanity_providers"):
                    d[k] = tuple(d.get(k, ()))
                m.upsert(Instrument(**d))
        return m

    def upsert(self, inst: Instrument):
        self._by_id[inst.id] = inst

    def get(self, id: str) -> Instrument:
        inst = self._by_id[id]
        if inst.asset_class in ("equity", "etf") and inst.provider_priority and inst.provider_priority[-1] == "yahoo" and "polygon" in inst.provider_priority:
            # stock chain follows ATLAS_STOCK_PROVIDER (re-read per call so Settings changes apply without a restart)
            from .stock_providers import equity_priority
            pri = equity_priority()
            if pri != tuple(inst.provider_priority):
                from dataclasses import replace
                return replace(inst, provider_priority=pri)
        return inst

    def __contains__(self, id):
        return id in self._by_id

    def all(self):
        return [self.get(i) for i in self._by_id]

    def symbol(self, id: str, provider: str) -> str:
        return self.get(id).provider_symbols.get(provider, id)
