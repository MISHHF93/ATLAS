from __future__ import annotations

from ..core import Capabilities, ProviderAdapter, ProviderError

IV = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}


class BybitAdapter(ProviderAdapter):
    caps = Capabilities(
        name="bybit", title="Bybit V5 public market data", status="working",
        asset_classes=("crypto",), schemas=("bars", "trades", "quotes"), intervals=tuple(IV),
        history_depth="/v5/market/kline multi-year, 1000 bars/request",
        live_stream="websocket: wss://stream.bybit.com/v5/public/spot (kline.<interval>.<symbol>)",
        rate_limits="600 requests / 5s per IP for public endpoints",
        auth_env=(),
        official_docs=("https://bybit-exchange.github.io/docs/v5/market/kline",
                       "https://bybit-exchange.github.io/docs/v5/websocket/public/kline",
                       "https://bybit-exchange.github.io/docs/v5/rate-limit"),
        terms_url="https://www.bybit.com/en/terms-service/",
        notes="Geo-blocked from this box (CloudFront 403); adapter is implemented + fixture-tested; failover skips it.")

    def _history(self, instrument, interval, start, end, now):
        out, e = [], end * 1000
        while True:
            js = self.get_json("https://api.bybit.com/v5/market/kline",
                               {"category": "spot", "symbol": instrument, "interval": IV[interval], "start": start * 1000, "end": e - 1, "limit": 1000})
            if js.get("retCode") != 0:
                raise ProviderError(f"bybit: {js.get('retMsg')}", retryable=js.get("retCode") == 10006)
            rows = js["result"]["list"]  # newest first [start, o, h, l, c, vol, turnover]
            if not rows:
                break
            out += [self._bar(instrument, interval, int(r[0]) // 1000, r[1], r[2], r[3], r[4], r[5], now) for r in rows]
            e = int(rows[-1][0])
            if len(rows) < 1000 or e // 1000 <= start:
                break
        return out
