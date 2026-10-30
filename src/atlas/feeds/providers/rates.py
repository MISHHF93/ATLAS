"""Official rates/energy reference series for a Canadian trader (evo-19). Series observations, never bars and never a trade series.

- ``us_treasury``: US Treasury Daily Par Yield Curve (CC0 public domain, keyless). Yields are rates, not prices.
- ``boc_rates``: Bank of Canada Valet benchmark Government of Canada bond yields (keyless, BoC terms: respect limits, no overloading).
- ``eia``: US EIA Open Data v2, daily WTI / Henry Hub benchmark SPOT prices (free key, public-domain US-government work). Spot is not a futures price.

All three are daily reference data (display / risk context / research features). Keys stay unset until the user supplies one."""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET

from ..core import Capabilities, FeedObservation, ProviderAdapter, ProviderError, RateLimiter

UST_TAGS = {"UST_1M": "BC_1MONTH", "UST_3M": "BC_3MONTH", "UST_6M": "BC_6MONTH", "UST_1Y": "BC_1YEAR", "UST_2Y": "BC_2YEAR", "UST_5Y": "BC_5YEAR",
            "UST_10Y": "BC_10YEAR", "UST_20Y": "BC_20YEAR", "UST_30Y": "BC_30YEAR"}
BOC_YIELDS = {"CAN_2Y": "BD.CDN.2YR.DQ.YLD", "CAN_3Y": "BD.CDN.3YR.DQ.YLD", "CAN_5Y": "BD.CDN.5YR.DQ.YLD", "CAN_7Y": "BD.CDN.7YR.DQ.YLD",
              "CAN_10Y": "BD.CDN.10YR.DQ.YLD", "CAN_LONG": "BD.CDN.LONG.DQ.YLD"}
EIA_SERIES = {"EIA_WTI_SPOT": ("petroleum/pri/spt", "RWTC"), "EIA_BRENT_SPOT": ("petroleum/pri/spt", "RBRTE"),
              "EIA_HENRYHUB_SPOT": ("natural-gas/pri/fut", "RNGWHHD")}
_UST_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"


def _day(s: str) -> str:
    return str(s)[:10]


class _Rates(ProviderAdapter):
    def _history(self, *a, **k):       # series only: there are no bars
        return []

    def _raw(self, url: str, headers=None) -> bytes:
        self.limiter.acquire()
        self._health.requests += 1
        status, _h, body = self.transport(url, headers or {})
        now = int(self.clock())
        if status != 200:
            err = ProviderError(f"{self.name} HTTP {status}: {(body or b'')[:120]!r}", status, status is None or status == 429 or (status or 0) >= 500)
            self._health.last_error, self._health.last_error_at, self._health.consecutive_errors = str(err), now, self._health.consecutive_errors + 1
            raise err
        self._health.last_ok, self._health.consecutive_errors = now, 0
        return body


class UsTreasuryYieldAdapter(_Rates):
    caps = Capabilities(
        name="us_treasury", title="US Treasury Daily Par Yield Curve (XML feed)", status="interface_fixture_tested",
        asset_classes=("macro",), schemas=("series",), intervals=("1d",),
        history_depth="Par yield curve since 1990; one year per request (field_tdr_date_value=YYYY) or month (field_tdr_date_value_month=YYYYMM)",
        live_stream="none (published each business day after the close)", rate_limits="No published cap; ATLAS limits to 1 req/s and fetches one month or year at a time",
        auth_env=(), official_docs=("https://home.treasury.gov/treasury-daily-interest-rate-xml-feed", "https://fiscaldata.treasury.gov/api-documentation/"),
        terms_url="https://www.treasurydirect.gov/legal-information/developers/web-api-terms/",
        notes="Public domain (CC0 on the data.gov catalog entry). Attribution to the source, never imply Treasury endorsement. Yields in percent. "
              "Confirm the terms page yourself before relying on it.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(1, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def observations(self, series_id: str, year_month: str | None = None, year: int | None = None) -> list[FeedObservation]:
        tag = UST_TAGS.get(series_id)
        if not tag:
            raise ProviderError(f"us_treasury: unknown series {series_id}", 400)
        q = {"data": "daily_treasury_yield_curve"}
        if year_month:
            q["field_tdr_date_value_month"] = year_month
        else:
            q["field_tdr_date_value"] = str(year or dt.date.today().year)
        root = ET.fromstring(self._raw(_UST_URL + "?" + urllib.parse.urlencode(q)))
        now = int(self.clock())
        out = []
        for props in root.iter("{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties"):
            d = {re.sub(r"^\{.*\}", "", c.tag): (c.text or "").strip() for c in props}
            if d.get("NEW_DATE") and d.get(tag):
                out.append(FeedObservation(series_id, _day(d["NEW_DATE"]), float(d[tag]), _day(d["NEW_DATE"]), self.name, now))
        return sorted(out, key=lambda o: o.date)


class BankOfCanadaRatesAdapter(_Rates):
    caps = Capabilities(
        name="boc_rates", title="Bank of Canada Valet (Government of Canada benchmark bond yields)", status="interface_fixture_tested",
        asset_classes=("macro",), schemas=("series",), intervals=("1d",),
        history_depth="Daily benchmark yields (see Valet series detail)", live_stream="none (daily)",
        rate_limits="No published hard cap; ATLAS limits to 1 req/s (terms forbid overloading the service)", auth_env=(),
        official_docs=("https://www.bankofcanada.ca/valet/docs", "https://www.bankofcanada.ca/valet-api-how-to/"),
        terms_url="https://www.bankofcanada.ca/terms/",
        notes="Keyless. Yields in percent. Read the Bank's terms before any redistribution; ATLAS uses it for display and research context.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(1, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def observations(self, series_id: str, start: str, end: str) -> list[FeedObservation]:
        vs = BOC_YIELDS.get(series_id)
        if not vs:
            raise ProviderError(f"boc_rates: unknown series {series_id}", 400)
        js = self.get_json(f"https://www.bankofcanada.ca/valet/observations/{vs}/json", {"start_date": start, "end_date": end})
        now = int(self.clock())
        return [FeedObservation(series_id, o["d"], float(o[vs]["v"]), o["d"], self.name, now)
                for o in js.get("observations", []) if (o.get(vs) or {}).get("v") not in (None, "")]


class EIAAdapter(_Rates):
    caps = Capabilities(
        name="eia", title="US EIA Open Data v2 (daily benchmark spot prices)", status="interface_fixture_tested",
        asset_classes=("macro",), schemas=("series",), intervals=("1d",),
        history_depth="Daily spot series; length/offset paging (max 5000 rows per page)", live_stream="none (daily, published with a lag)",
        rate_limits="No published numeric cap; ATLAS limits to 1 req/s", auth_env=("EIA_API_KEY",),
        official_docs=("https://www.eia.gov/opendata/documentation.php",), terms_url="https://www.eia.gov/about/copyrights_reuse.php",
        notes="NEEDS VERIFICATION: free key not set; route/series ids come from EIA docs and were not called with a key. Spot benchmarks, NOT futures "
              "prices, so never a trade series for CL/MCL/NG.")

    def __init__(self, *a, **kw):
        kw.setdefault("limiter", RateLimiter(1, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)

    def observations(self, series_id: str, start: str | None = None, length: int = 500) -> list[FeedObservation]:
        if series_id not in EIA_SERIES:
            raise ProviderError(f"eia: unknown series {series_id}", 400)
        route, code = EIA_SERIES[series_id]
        p = {"api_key": self.env.get("EIA_API_KEY"), "frequency": "daily", "data[0]": "value", "facets[series][]": code,
             "sort[0][column]": "period", "sort[0][direction]": "desc", "length": min(int(length), 5000)}
        if start:
            p["start"] = start
        js = self.get_json(f"https://api.eia.gov/v2/{route}/data/", p)
        now = int(self.clock())
        rows = (js.get("response") or {}).get("data") or []
        return sorted((FeedObservation(series_id, r["period"], float(r["value"]), r["period"], self.name, now)
                       for r in rows if r.get("value") not in (None, "")), key=lambda o: o.date)
