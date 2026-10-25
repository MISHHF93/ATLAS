"""Bank of Canada Valet API: official daily FX reference rates (free, keyless, automated use allowed under BoC terms)."""
from __future__ import annotations

import datetime as dt

from ..core import Capabilities, ProviderAdapter, RateLimiter

# ATLAS FX id -> (Valet series, invert). Valet quotes CAD per unit of foreign currency.
SERIES = {"USD_CAD": ("FXUSDCAD", False), "EUR_CAD": ("FXEURCAD", False), "CAD_USD": ("FXUSDCAD", True)}


class BankOfCanadaFXAdapter(ProviderAdapter):
    caps = Capabilities(
        name="boc_valet", title="Bank of Canada Valet (daily FX reference rates)", status="interface_fixture_tested",
        asset_classes=("fx",), schemas=("bars",), intervals=("1d",),
        history_depth="FX daily since 2017 (older series archived)", live_stream="none (published once per business day ~16:30 ET)",
        rate_limits="No published cap; ATLAS limits to 1 req/s", auth_env=(),
        official_docs=("https://www.bankofcanada.ca/valet/docs",), terms_url="https://www.bankofcanada.ca/terms/",
        notes="Delayed (end-of-day reference rate). One value per day, so open=high=low=close.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(1, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def _history(self, instrument, interval, start, end, now):
        if instrument not in SERIES:
            return []
        series, inv = SERIES[instrument]
        d = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d")
        js = self.get_json(f"https://www.bankofcanada.ca/valet/observations/{series}/json", {"start_date": d(start), "end_date": d(end)})
        out = []
        for o in js.get("observations", []):
            v = (o.get(series) or {}).get("v")
            if v in (None, ""):
                continue
            px = 1.0 / float(v) if inv else float(v)
            t = int(dt.datetime.fromisoformat(o["d"]).replace(tzinfo=dt.timezone.utc).timestamp())
            out.append(self._bar(instrument, "1d", t, px, px, px, px, 0, now))
        return out
