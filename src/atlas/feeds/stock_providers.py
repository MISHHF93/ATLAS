"""Stock / ETF provider registry and the configurable primary (``ATLAS_STOCK_PROVIDER``).

Why this exists: Alpaca does not serve Canadian residents, so it cannot be the required primary. The chain is now built
from this registry. ``ATLAS_STOCK_PROVIDER`` names the primary; the rest of the default chain follows automatically as
failover. Nothing here sets a key, calls a vendor, or loosens the free-data gate (``free_sources.allowed`` still applies).

Default primary = ``polygon`` (Massive Stocks Basic): free, instant email signup, no brokerage account, personal display
allowed. It serves end-of-day bars (5 calls/min, 2 years). Intraday needs a free-account provider or a paid plan, so
stock charts are labelled daily-only until one is configured. Research and sources: docs/data/canada-sources.md.

``restricted`` providers (Tiingo, Twelve Data, Finnhub): their FREE plans forbid what ATLAS does (persistent storage and
chart display, or no candles at all). They are never in the automatic chain. They are used only when the owner names one in
``ATLAS_STOCK_PROVIDER`` (an explicit, informed opt-in, e.g. after buying a paid plan and setting ``ATLAS_<NAME>_PLAN=paid``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

INTRADAY = ("1m", "5m", "15m", "1h", "1d")
DAILY = ("1d",)


@dataclass(frozen=True)
class StockProvider:
    id: str
    title: str
    canada: str                  # open | account | unverified
    signup: str
    free_intervals: tuple        # what the FREE plan serves
    free_limits: str
    terms: str                   # one line on storage / display on the free plan
    terms_url: str
    restricted: bool = False     # free plan forbids ATLAS's storage/chart display, or has no candles
    needs_account: bool = False  # needs a brokerage / demo account, not just an email signup
    env_keys: tuple = ()


STOCK_PROVIDERS: dict[str, StockProvider] = {p.id: p for p in (
    StockProvider("polygon", "Massive (Polygon.io) Stocks Basic", "open", "https://massive.com/dashboard/signup", DAILY,
                  "5 calls/min, end-of-day, 2 years", "Personal, non-commercial; display for yourself is allowed; another viewer needs a Business plan",
                  "https://massive.com/legal/individuals-terms-of-service", env_keys=("POLYGON_API_KEY",)),
    StockProvider("alphavantage", "Alpha Vantage (free key)", "open", "https://www.alphavantage.co/support/#api-key", DAILY,
                  "25 requests/day, last 100 daily bars (compact); intraday is premium", "Personal, non-commercial; display on your own device",
                  "https://www.alphavantage.co/terms_of_service/", env_keys=("ALPHAVANTAGE_API_KEY",)),
    StockProvider("questrade", "Questrade API", "account", "https://www.questrade.com/api", INTRADAY,
                  "20 req/s; real time is a paid package, otherwise snap/delayed quotes", "Personal use under the API agreement",
                  "https://www.questrade.com/api/home", needs_account=True, env_keys=("QUESTRADE_REFRESH_TOKEN",)),
    StockProvider("tradier", "Tradier sandbox", "unverified", "https://developer.tradier.com/user/sign_up", INTRADAY,
                  "60 req/min, 15-min delayed", "Sandbox data for development", "https://tradier.com/legal/", needs_account=True,
                  env_keys=("TRADIER_ACCESS_TOKEN",)),
    StockProvider("alpaca", "Alpaca (optional; not offered to Canadian residents)", "unverified", "https://app.alpaca.markets/paper/dashboard/overview", INTRADAY,
                  "200 req/min, IEX only", "IEX feed, personal use", "https://alpaca.markets/disclosures", needs_account=True,
                  env_keys=("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")),
    StockProvider("tiingo", "Tiingo (free plan restricted)", "open", "https://www.tiingo.com/account/api/token", INTRADAY,
                  "50 req/h, 1000/day", "Free plan forbids persistent storage and chart display (ToS 1.6): paid plan only",
                  "https://app.tiingo.com/tos/", restricted=True, env_keys=("TIINGO_API_KEY",)),
    StockProvider("twelvedata", "Twelve Data (free plan restricted)", "open", "https://twelvedata.com/register", INTRADAY,
                  "8 credits/min, 800/day", "Basic plan is internal non-display use only: paid plan to chart it",
                  "https://twelvedata.com/terms", restricted=True, env_keys=("TWELVEDATA_API_KEY",)),
    StockProvider("finnhub", "Finnhub (free plan has no candles)", "open", "https://finnhub.io/register", (),
                  "60 calls/min; quotes only, stock candles are premium", "Free plan serves no bars", "https://finnhub.io/terms-of-service",
                  restricted=True, env_keys=("FINNHUB_API_KEY",)),
)}

DEFAULT_PRIMARY = "polygon"
# Automatic failover order after the primary. Free-plan terms must allow ATLAS's stored, charted use.
DEFAULT_CHAIN = ("polygon", "alphavantage", "questrade", "tradier", "alpaca")
# Sanity-only (never merged into the series); Yahoo stays policy-blocked unless ATLAS_ALLOW_UNOFFICIAL_DATA.
TAIL = ("yahoo",)


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    if env is not None:
        return env
    from atlas.accounts.credentials import effective_environ
    return effective_environ()


def configured_primary(env: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """(primary id, warning). Unknown values fall back to the default and say so."""
    raw = (_env(env).get("ATLAS_STOCK_PROVIDER") or "").strip().lower()
    if raw in ("", "auto", "default"):
        return DEFAULT_PRIMARY, None
    if raw in STOCK_PROVIDERS:
        return raw, None
    return DEFAULT_PRIMARY, f"ATLAS_STOCK_PROVIDER={raw!r} is not a known provider ({', '.join(STOCK_PROVIDERS)}); using {DEFAULT_PRIMARY}"


def equity_priority(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Failover order for every stock/ETF: the configured primary, then the rest of the default chain, then the blocked tail."""
    primary, _ = configured_primary(env)
    return (primary, *[p for p in DEFAULT_CHAIN if p != primary], *TAIL)


def plan_is_paid(name: str, env: Mapping[str, str] | None = None) -> bool:
    return str(_env(env).get(f"ATLAS_{name.upper()}_PLAN", "")).strip().lower() in ("paid", "premium", "pro", "grow", "power", "starter", "developer", "advanced")


def intervals_for(name: str, env: Mapping[str, str] | None = None) -> tuple[str, ...] | None:
    """Intervals a stock provider's plan can serve (free plan unless ATLAS_<NAME>_PLAN=paid). None = not a stock-registry provider."""
    p = STOCK_PROVIDERS.get(name)
    if p is None:
        return None
    if plan_is_paid(name, env):
        return INTRADAY
    return p.free_intervals


def summary(env: Mapping[str, str] | None = None) -> dict:
    primary, warn = configured_primary(env)
    return {"setting": "ATLAS_STOCK_PROVIDER", "primary": primary, "default_primary": DEFAULT_PRIMARY, "warning": warn,
            "chain": list(equity_priority(env)),
            "providers": [{**p.__dict__, "free_intervals": list(p.free_intervals), "env_keys": list(p.env_keys)} for p in STOCK_PROVIDERS.values()]}
