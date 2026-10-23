from __future__ import annotations

from ..core import Capabilities, ProviderAdapter, ProviderError

IV = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
RANGE = {"1m": "7d", "5m": "60d", "15m": "60d", "1h": "730d", "1d": "max"}


class YahooAdapter(ProviderAdapter):
    caps = Capabilities(
        name="yahoo", title="Yahoo Finance chart endpoint (UNOFFICIAL fallback)", status="working",
        asset_classes=("equity", "etf", "index", "fx", "crypto", "future"), schemas=("bars",), intervals=tuple(IV),
        history_depth="Intraday limited: 1m=7d, 5m/15m=60d, 60m=730d; daily=max",
        live_stream="none (polling only)",
        rate_limits="Undocumented; ATLAS self-limits to 1 req/s and backs off on 429",
        auth_env=(), unofficial=True,
        official_docs=("https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",),
        terms_url="https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html",
        notes="No official public API/docs; endpoint query1.finance.yahoo.com/v8/finance/chart is unofficial and may change. "
              "Labelled fallback only; personal/research use per Yahoo terms. Bars are 15m-delayed-ish; last bar may be partial.")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        from ..core import RateLimiter
        self.limiter = RateLimiter(1, 1.0, sleep=self.sleep)

    def _history(self, instrument, interval, start, end, now):
        sym = self.provider_symbol(instrument)
        js = self.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                           {"interval": IV[interval], "range": RANGE[interval], "includePrePost": "false"},
                           headers={"User-Agent": "Mozilla/5.0"})
        res = (js.get("chart") or {}).get("result")
        if not res:
            raise ProviderError(f"yahoo: {js.get('chart', {}).get('error')}")
        r = res[0]
        q = r["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(r.get("timestamp") or []):
            vals = [q[k][i] for k in ("open", "high", "low", "close")]
            if None in vals:
                continue
            out.append(self._bar(instrument, interval, t, *vals, q["volume"][i] or 0, now))
        return out
