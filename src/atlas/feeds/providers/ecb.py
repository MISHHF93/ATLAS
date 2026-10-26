"""European Central Bank Data Portal API: official daily euro FX reference rates (free, keyless, reuse allowed)."""
from __future__ import annotations

import datetime as dt
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Mapping

from ..core import Capabilities, ProviderAdapter, ProviderError, RateLimiter, urllib_transport

# Direct EUR pairs: ATLAS FX id -> (ECB currency code, invert). ECB quotes foreign currency units per 1 EUR.
SERIES: dict[str, tuple[str, bool]] = {
    "EUR_USD": ("USD", False),
    "USD_EUR": ("USD", True),
    "EUR_CAD": ("CAD", False),
    "CAD_EUR": ("CAD", True),
    "EUR_GBP": ("GBP", False),
    "GBP_EUR": ("GBP", True),
    "EUR_JPY": ("JPY", False),
    "JPY_EUR": ("JPY", True),
    "EUR_CHF": ("CHF", False),
    "CHF_EUR": ("CHF", True),
}

# Cross-rate pairs derived from two ECB EUR legs: ATLAS FX id -> (numerator_ccy, denominator_ccy) so rate = num / den.
CROSS_SERIES: dict[str, tuple[str, str]] = {
    "USD_CAD": ("CAD", "USD"),
    "CAD_USD": ("USD", "CAD"),
}

DEFAULT_HOSTS = ("https://data-api.ecb.europa.eu/service/data/EXR",)
XML_FALLBACK_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"


def _normalize_body(status: int, hdrs: Mapping[str, str], body: bytes) -> tuple[int, Mapping[str, str], bytes]:
    # ECB SDMX returns HTTP 200 with an empty body when a holiday window has 0 observations.
    if status == 200 and not (body or b"").strip():
        return 200, hdrs, b"{}"
    return status, hdrs, body


def ecb_transport(url: str, headers: Mapping[str, str], timeout: float = 20.0) -> tuple[int, Mapping[str, str], bytes]:
    """HTTP transport with certifi CA fallback when the OS trust store raises a TLS error on ECB hosts."""
    req_headers = {"User-Agent": "atlas-feed/1.0", "Accept": "application/json, application/xml;q=0.9, */*;q=0.8", **headers}
    try:
        st, hd, bd = urllib_transport(url, req_headers, timeout=timeout)
        return _normalize_body(st, hd, bd)
    except (ssl.SSLError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        if not isinstance(reason, ssl.SSLError) and "SSL" not in str(exc).upper() and "CERTIFICATE" not in str(exc).upper():
            raise
        try:
            import certifi  # type: ignore[import-untyped]
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            raise exc
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return _normalize_body(r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() or b""


def parse_sdmx_json(js: dict) -> dict[str, float]:
    """Extract {YYYY-MM-DD: float_rate} from an ECB SDMX-JSON payload (or simplified fixture dict)."""
    if not isinstance(js, dict):
        return {}
    if "observations" in js and isinstance(js["observations"], list):
        out: dict[str, float] = {}
        for row in js["observations"]:
            d_str = row.get("d") or row.get("date")
            v = row.get("v") if "v" in row else row.get("value")
            if d_str and v not in (None, ""):
                out[str(d_str)[:10]] = float(v)
        return out
    datasets = js.get("dataSets") or []
    if not datasets:
        return {}
    series_map = datasets[0].get("series") or {}
    if not series_map:
        return {}
    first_series = next(iter(series_map.values()), {})
    obs_map = first_series.get("observations") or {}
    dims = ((js.get("structure") or {}).get("dimensions") or {}).get("observation") or []
    time_dim = next((d for d in dims if d.get("id") == "TIME_PERIOD" or d.get("role") == "time"), dims[0] if dims else {})
    dates = [v.get("id") or v.get("name") for v in (time_dim.get("values") or [])]
    out = {}
    for idx_str, arr in obs_map.items():
        try:
            idx = int(idx_str.split(":")[0])
            val = arr[0] if isinstance(arr, (list, tuple)) and arr else None
            if val is not None and 0 <= idx < len(dates) and dates[idx]:
                out[str(dates[idx])[:10]] = float(val)
        except (ValueError, TypeError, IndexError):
            continue
    return out


def parse_eurofxref_xml(xml_bytes: bytes, ccy: str) -> dict[str, float]:
    """Extract {YYYY-MM-DD: float_rate} for ``ccy`` from ECB's eurofxref XML feed."""
    out: dict[str, float] = {}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    target = ccy.upper()
    for day_cube in root.iter():
        day = day_cube.attrib.get("time")
        if not day:
            continue
        for rate_cube in day_cube:
            if (rate_cube.attrib.get("currency") or "").upper() == target:
                try:
                    out[day[:10]] = float(rate_cube.attrib["rate"])
                except (KeyError, ValueError, TypeError):
                    pass
    return out


class ECBFXAdapter(ProviderAdapter):
    caps = Capabilities(
        name="ecb_fx",
        title="European Central Bank Data Portal (daily euro FX reference rates)",
        status="working",
        asset_classes=("fx",),
        schemas=("bars",),
        intervals=("1d",),
        history_depth="Daily euro reference rates since 1999-01-04",
        live_stream="none (published once per TARGET business day ~16:00 CET)",
        rate_limits="No published cap; ATLAS limits to 1 req/s",
        auth_env=(),
        official_docs=("https://data.ecb.europa.eu/help/api/data",),
        terms_url="https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html",
        notes="Delayed (end-of-day reference rate). One value per day, so open=high=low=close.",
    )

    def __init__(self, *a, **kw):
        if kw.get("transport") is None and not a:
            kw["transport"] = ecb_transport
        kw.setdefault("limiter", RateLimiter(1, 1.0, sleep=kw.get("sleep") or __import__("time").sleep))
        super().__init__(*a, **kw)
        hosts_env = (self.env.get("ATLAS_ECB_REST_HOSTS") or "").strip()
        self.hosts = tuple(h.strip().rstrip("/") for h in hosts_env.split(",") if h.strip()) or DEFAULT_HOSTS

    def _fetch_ccy(self, ccy: str, start_date: str, end_date: str) -> dict[str, float]:
        last_err: ProviderError | None = None
        for host in self.hosts:
            url = f"{host}/D.{ccy}.EUR.SP00.A"
            try:
                js = self.get_json(
                    url,
                    {"format": "jsondata", "startPeriod": start_date, "endPeriod": end_date},
                    headers={"Accept": "application/json"},
                    attempts=2,
                )
                return parse_sdmx_json(js)
            except ValueError:
                return {}
            except ProviderError as err:
                last_err = err
                continue
        # Fallback to the static eurofxref XML feed if SDMX REST hosts failed (e.g. legacy SDW TLS error)
        try:
            self.limiter.acquire()
            self._health.requests += 1
            status, _hdrs, body = self.transport(XML_FALLBACK_URL, {"Accept": "application/xml"})
            if status == 200 and body:
                parsed = {
                    d: v for d, v in parse_eurofxref_xml(body, ccy).items()
                    if start_date <= d <= end_date
                }
                if parsed:
                    self._health.last_ok = int(self.clock())
                    self._health.consecutive_errors = 0
                    return parsed
        except OSError as exc:
            now = int(self.clock())
            last_err = ProviderError(f"{self.name} TLS/transport error: {exc}", None, retryable=True)
            self._health.last_error, self._health.last_error_at = str(last_err), now
            self._health.consecutive_errors += 1
        if last_err is not None:
            raise last_err
        return {}

    def _history(self, instrument: str, interval: str, start: int, end: int, now: int):
        sym = self.provider_symbol(instrument)
        key = instrument if (instrument in SERIES or instrument in CROSS_SERIES) else sym
        d = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%Y-%m-%d")
        s_date, e_date = d(start), d(end)

        rates_by_date: dict[str, float] = {}
        if key in SERIES:
            ccy, inv = SERIES[key]
            raw = self._fetch_ccy(ccy, s_date, e_date)
            for d_str, val in raw.items():
                if val and val > 0:
                    rates_by_date[d_str] = (1.0 / float(val)) if inv else float(val)
        elif key in CROSS_SERIES:
            num_ccy, den_ccy = CROSS_SERIES[key]
            num_map = self._fetch_ccy(num_ccy, s_date, e_date)
            den_map = self._fetch_ccy(den_ccy, s_date, e_date)
            for d_str in sorted(set(num_map) & set(den_map)):
                num_v, den_v = num_map[d_str], den_map[d_str]
                if num_v and den_v and num_v > 0 and den_v > 0:
                    rates_by_date[d_str] = float(num_v) / float(den_v)
        else:
            return []

        out = []
        for d_str in sorted(rates_by_date):
            px = rates_by_date[d_str]
            t = int(dt.datetime.fromisoformat(d_str).replace(tzinfo=dt.timezone.utc).timestamp())
            out.append(self._bar(instrument, "1d", t, px, px, px, px, 0, now))
        return out
