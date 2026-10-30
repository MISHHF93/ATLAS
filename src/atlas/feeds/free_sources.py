"""Free-data policy: every market-data provider's cost, latency and limits, and the free-only gate the router applies.

HARD RULE (owner): all data is FREE. Paid providers are never selected, and unofficial/scraped endpoints are off,
unless ATLAS_ALLOW_PAID_DATA / ATLAS_ALLOW_UNOFFICIAL_DATA is explicitly "true" (neither is set by default; do not set).
Limits are the providers' published free-tier limits (checked 2026-10-24; see docs/data/free-sources.md)."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class SourceTerms:
    cost: str          # free | free_key | free_account | paid
    latency: str       # realtime | delayed_15m | eod | daily_reference | release
    limits: str
    terms_ok: bool     # official API whose terms allow automated personal use
    register: str = ""  # where to get the free key/account (blank = keyless)


SOURCES: dict[str, SourceTerms] = {
    "alpaca": SourceTerms("free_key", "realtime", "Basic: 200 req/min, 30 WS symbols, IEX only (SIP last 15 min restricted)", True, "https://app.alpaca.markets (paper account)"),
    "alpaca_crypto": SourceTerms("free", "realtime", "History keyless; 200 req/min", True),
    "coinbase": SourceTerms("free", "realtime", "Public REST ~10 req/s per IP; WS free", True),
    "kraken": SourceTerms("free", "realtime", "Public REST ~1 req/s; WS free", True),
    "polygon": SourceTerms("free_key", "eod", "Massive/Polygon Basic: 5 calls/min, 15m + daily bars up to the previous completed day, 2 years", True, "https://massive.com/dashboard/signup"),
    "tiingo": SourceTerms("free_key", "eod", "Free: 50 req/hour, 1000/day. Free plan forbids persistent storage and chart display (ToS 1.6): not in the automatic chain", True, "https://www.tiingo.com"),
    "finnhub": SourceTerms("free_key", "realtime", "Free: 60 calls/min; US quotes only, stock candles are premium: not in the automatic chain", True, "https://finnhub.io/register"),
    "twelvedata": SourceTerms("free_key", "delayed_15m", "Basic: 8 credits/min, 800/day, internal non-display use only: not in the automatic chain", True, "https://twelvedata.com/register"),
    "alphavantage": SourceTerms("free_key", "eod", "Free: 25 requests/day, 100 daily bars (compact), intraday is premium", True, "https://www.alphavantage.co/support/#api-key"),
    "fmp": SourceTerms("free_key", "eod", "Free: 250 calls/day, US only, EOD", True, "https://site.financialmodelingprep.com/register"),
    "fred": SourceTerms("free_key", "release", "120 req/min", True, "https://fredaccount.stlouisfed.org/apikeys"),
    "boc_valet": SourceTerms("free", "daily_reference", "No published cap (ATLAS 1 req/s)", True),
    "ecb_fx": SourceTerms("free", "daily_reference", "No published cap (ATLAS 1 req/s)", True),
    "us_treasury": SourceTerms("free", "daily_reference", "No published cap (ATLAS 1 req/s). Public domain; display/research context, not a trade series", True),
    "boc_rates": SourceTerms("free", "daily_reference", "No published cap (ATLAS 1 req/s). Benchmark GoC yields; context only", True),
    "eia": SourceTerms("free_key", "release", "Free key (needs verification: none set). Daily benchmark SPOT prices, not futures; context only", True, "https://www.eia.gov/opendata/register.php"),
    "oanda": SourceTerms("free_account", "realtime", "Practice account: 120 req/s; FX + CFDs incl. XAU", True, "https://www.oanda.com (demo account)"),
    "questrade": SourceTerms("free_account", "delayed_15m", "Needs a Questrade account; real-time is a paid data package", True),
    "yahoo": SourceTerms("free", "delayed_15m", "Unofficial endpoint; no public API terms", False),
    "databento": SourceTerms("paid", "realtime", "Usage-billed", True),
    "ibkr": SourceTerms("paid", "realtime", "Needs a funded IBKR account + paid market-data subscriptions (paper data is delayed; no ATLAS adapter yet)", True),
    "eodhd": SourceTerms("paid", "eod", "Free is 20 calls/day only; useful plans are paid", True),
    "cme": SourceTerms("paid", "realtime", "Licensed", True),
    "tmx": SourceTerms("paid", "realtime", "Licensed", True),
}


def _flag(env: Mapping[str, str], k: str) -> bool:
    return str(env.get(k, "")).strip().lower() in ("1", "true", "on", "yes")


def allowed(name: str, env: Mapping[str, str] | None = None) -> bool:
    """The free-only gate. Unknown providers are refused (fail closed)."""
    from atlas.accounts.credentials import effective_environ
    env = effective_environ() if env is None else env
    t = SOURCES.get(name)
    if t is None:
        return False
    if t.cost == "paid" and not _flag(env, "ATLAS_ALLOW_PAID_DATA"):
        return False
    if not t.terms_ok and not _flag(env, "ATLAS_ALLOW_UNOFFICIAL_DATA"):
        return False
    return True


def latency(name: str) -> str:
    t = SOURCES.get(name)
    return t.latency if t else "unknown"


_DELAY_S = {"realtime": 0, "delayed_15m": 900, "eod": 86400, "daily_reference": 86400, "release": None}


def delay_s(name: str) -> int | None:
    """Nominal data delay in seconds for a provider (0 = real time, None = unknown)."""
    return _DELAY_S.get(latency(name))


def is_realtime(name: str) -> bool | None:
    lat = latency(name)
    return None if lat == "unknown" else lat == "realtime"


def describe(name: str) -> dict:
    t = SOURCES.get(name)
    return {"provider": name, **(asdict(t) if t else {}), "allowed": allowed(name), "realtime": is_realtime(name), "delay_s": delay_s(name)}
