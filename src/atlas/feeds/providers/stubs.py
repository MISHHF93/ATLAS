"""Interface-complete adapters that need a local gateway / SDK / licence, plus documented stubs."""
from __future__ import annotations

import datetime as dt

from ..core import Capabilities, ProviderAdapter, ProviderError


class DatabentoAdapter(ProviderAdapter):
    caps = Capabilities(
        name="databento", title="Databento Historical + Live", status="interface_fixture_tested",
        asset_classes=("equity", "future", "option"), schemas=("bars", "trades", "quotes", "mbo", "mbp"),
        intervals=("1m", "1h", "1d"),
        history_depth="Venue-dependent, e.g. CME Globex (GLBX.MDP3) since 2010, XNAS.ITCH since 2018",
        live_stream="Databento Live (raw TCP gateway / official python client)",
        rate_limits="Historical per IP: 100 concurrent connections, 100 timeseries requests/s; 429 + Retry-After; metered per GB (metadata.get_cost is free)",
        auth_env=("DATABENTO_API_KEY",),
        official_docs=("https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range",
                       "https://databento.com/docs/schemas-and-data-formats/ohlcv"),
        terms_url="https://databento.com/terms",
        notes="HTTP API: https://hist.databento.com/v0/timeseries.get_range (Basic auth, key as username). Prices in 1e-9 fixed point. Usage is billed: ATLAS never calls it unless DATABENTO_API_KEY is set AND ATLAS_DATABENTO_DATASET is set.")
    SCHEMA = {"1m": "ohlcv-1m", "1h": "ohlcv-1h", "1d": "ohlcv-1d"}

    def _history(self, instrument, interval, start, end, now):
        import base64
        ds = self.env.get("ATLAS_DATABENTO_DATASET")
        if not ds:
            raise ProviderError("databento: set ATLAS_DATABENTO_DATASET (e.g. GLBX.MDP3) to opt in to billed usage")
        auth = base64.b64encode((self.env["DATABENTO_API_KEY"] + ":").encode()).decode()
        iso = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).isoformat()
        import json
        status, _, body = self.transport(
            "https://hist.databento.com/v0/timeseries.get_range?" + __import__("urllib.parse").parse.urlencode(
                {"dataset": ds, "symbols": self.provider_symbol(instrument), "schema": self.SCHEMA[interval],
                 "start": iso(start), "end": iso(end), "encoding": "json", "stype_in": "raw_symbol"}),
            {"Authorization": "Basic " + auth})
        if status != 200:
            raise ProviderError(f"databento HTTP {status}", status, status == 429 or status >= 500)
        return parse_databento_json(self, instrument, interval, body, now)


def parse_databento_json(adapter, instrument, interval, body: bytes, now: int):
    import json
    out = []
    for line in body.decode().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        t = int(r["hd"]["ts_event"]) // 10**9
        px = lambda k: int(r[k]) / 1e9
        out.append(adapter._bar(instrument, interval, t, px("open"), px("high"), px("low"), px("close"), int(r["volume"]), now))
    return out


class IBKRAdapter(ProviderAdapter):
    caps = Capabilities(
        name="ibkr", title="Interactive Brokers (Client Portal Web API / TWS API)", status="interface_fixture_tested",
        asset_classes=("equity", "etf", "future", "option", "fx", "index"), schemas=("bars", "quotes"),
        intervals=("1m", "5m", "15m", "1h", "1d"),
        history_depth="iserver/marketdata/history: period up to years for daily, ~1000 bars/request; pacing rules apply",
        live_stream="Client Portal websocket wss://localhost:5000/v1/api/ws (smd+conid) or TWS reqRealTimeBars",
        rate_limits="CP Web API: 10 req/s global; history endpoint 5 concurrent; TWS: 50 msgs/s, historical pacing 60 req/10 min",
        auth_env=("IBKR_CP_GATEWAY_URL",),
        official_docs=("https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/",
                       "https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/"),
        terms_url="https://www.interactivebrokers.com/en/general/about/legal.php",
        notes="Requires a locally running, user-authenticated Client Portal Gateway (IBKR_CP_GATEWAY_URL e.g. https://localhost:5000). "
              "Market data subscriptions required. Instruments must carry an ibkr conid in the instrument master.")

    def _history(self, instrument, interval, start, end, now):
        base = self.env["IBKR_CP_GATEWAY_URL"].rstrip("/")
        bar = {"1m": "1min", "5m": "5mins", "15m": "15mins", "1h": "1h", "1d": "1d"}[interval]
        days = max(1, (end - start) // 86400 + 1)
        js = self.get_json(f"{base}/v1/api/iserver/marketdata/history",
                           {"conid": self.provider_symbol(instrument), "bar": bar, "period": f"{days}d", "outsideRth": "false"})
        return [self._bar(instrument, interval, r["t"] // 1000, r["o"], r["h"], r["l"], r["c"], r.get("v", 0), now) for r in js.get("data", [])]


def _stub(name, title, ac, docs, terms, notes):
    return type(name.upper() + "Stub", (ProviderAdapter,), {
        "caps": Capabilities(name=name, title=title, status="documented_stub", asset_classes=ac, schemas=("bars", "trades", "quotes"),
                             intervals=(), history_depth="licensed; see docs", live_stream="licensed feed (not implemented)",
                             rate_limits="n/a", auth_env=(), official_docs=docs, terms_url=terms, notes=notes),
        "_history": lambda self, *a: (_ for _ in ()).throw(ProviderError(f"{name}: documented stub, not implemented"))})


CMEStub = _stub("cme", "CME Group market data (MDP 3.0 / DataMine)", ("future", "option"),
                ("https://www.cmegroup.com/market-data/real-time-futures-and-options-data-api.html",
                 "https://www.cmegroup.com/market-data/datamine-historical-data.html"),
                "https://www.cmegroup.com/market-data/license-data.html",
                "Direct CME data needs a licence + distributor agreement. Practical route: Databento GLBX.MDP3 (adapter above).")
TMXStub = _stub("tmx", "TMX Group / TSX market data (TMX Datalinx)", ("equity", "etf", "future", "option"),
                ("https://www.tmxinfoservices.com/",),
                "https://www.tmxinfoservices.com/",
                "Licensed vendor feed; no public self-serve API. Practical route for TSX symbols: Questrade/IBKR adapters or Yahoo '.TO' fallback.")
