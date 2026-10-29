from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from atlas.integrations import oanda_v20 as O

from ..core import INTERVALS, Capabilities, ProviderAdapter, ProviderError

NY = ZoneInfo("America/New_York")


def _ts(s):
    if isinstance(s, (int, float)):
        return float(s)
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


class OandaAdapter(ProviderAdapter):
    caps = Capabilities(
        name='oanda', title='OANDA v20 REST', status="interface_fixture_tested",
        asset_classes=('fx', 'cfd'), schemas=('bars', 'quotes'), intervals=('1m', '5m', '15m', '1h', '4h', '1d'),
        history_depth='Multi-year candles, 5000 per request',
        live_stream='HTTP stream: https://stream-fxpractice.oanda.com/v3/accounts/<id>/pricing/stream',
        rate_limits='120 requests/s per connection; 2 new connections/s',
        auth_env=('OANDA_API_TOKEN',),
        official_docs=('https://developer.oanda.com/rest-live-v20/pricing-ep/', 'https://developer.oanda.com/rest-live-v20/best-practices/'),
        terms_url='https://www.oanda.com/us-en/legal/',
        notes='PRACTICE hosts only (api-fxpractice / stream-fxpractice); OANDA_ENV=live is refused and the live hosts are never contacted. OANDA_ACCOUNT_ID is optional: it is discovered with GET /v3/accounts. Mid candles (FX, XAU_USD, index CFDs such as SPX500_USD where the account offers them), 5000 candles per request are paged, complete flag maps to confirmed.')

    PAGE = 5000   # official maximum candles per request

    def _headers(self):
        return O.auth_headers(self.env["OANDA_API_TOKEN"])

    def _guard(self, instrument: str) -> str:
        try:
            O.refuse_live(self.env)
        except O.OandaLiveRefused as ex:
            raise ProviderError(f"oanda: {ex}", retryable=False) from ex
        sym = self.provider_symbol(instrument)
        if not O.INSTRUMENT.fullmatch(sym):
            raise ProviderError(f"oanda: {sym!r} is not a safe OANDA instrument name (e.g. EUR_USD, XAU_USD, SPX500_USD)", retryable=False)
        return sym

    def _history(self, instrument, interval, start, end, now):
        g = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D"}[interval]
        sym = self._guard(instrument)
        step, out, t = INTERVALS[interval], [], int(start)
        while t < end:
            stop = min(end, t + step * self.PAGE)
            js = self.get_json(f"{O.REST}/v3/instruments/{sym}/candles", {"granularity": g, "from": t, "to": stop, "price": "M"}, headers=self._headers())
            out += [self._bar(instrument, interval, float(c["time"]), c["mid"]["o"], c["mid"]["h"], c["mid"]["l"], c["mid"]["c"], c.get("volume", 0), now, final=c.get("complete", True))
                    for c in js.get("candles", []) if c.get("mid")]
            t = stop
        return out

    # ---- account id discovery + pricing (read-only) ----
    def account_id(self) -> str:
        """OANDA_ACCOUNT_ID if set, else the first practice account GET /v3/accounts shows for this token (cached for the process)."""
        O.refuse_live(self.env)
        cfg = (self.env.get("OANDA_ACCOUNT_ID") or "").strip()
        if cfg:
            return cfg
        if getattr(self, "_acct", None):
            return self._acct
        acct, note = O.pick_account("", O.discover_account_ids(lambda u, h: self.get_json(u, headers=h), self.env["OANDA_API_TOKEN"]))
        if not acct:
            raise ProviderError("oanda: " + note, retryable=False)
        self._acct = acct
        return acct

    def quotes(self, instruments):
        """GET /v3/accounts/{id}/pricing?instruments=... on the practice host. Returns bid/ask/mid per instrument; never places an order."""
        syms = [self._guard(i) for i in instruments]
        js = self.get_json(f"{O.REST}/v3/accounts/{self.account_id()}/pricing", {"instruments": ",".join(syms)}, headers=self._headers())
        out = []
        for p in js.get("prices", []):
            bids, asks = p.get("bids") or [], p.get("asks") or []
            if not bids or not asks:
                continue
            out.append({"instrument": p.get("instrument"), "bid": float(bids[0]["price"]), "ask": float(asks[0]["price"]),
                        "mid": (float(bids[0]["price"]) + float(asks[0]["price"])) / 2.0, "time": p.get("time"), "tradeable": bool(p.get("tradeable", False))})
        return out

    def stream_url(self, instruments):
        sym = ",".join(self._guard(i) for i in instruments)
        return f"{O.STREAM}/v3/accounts/{self.account_id()}/pricing/stream?instruments={sym}"
