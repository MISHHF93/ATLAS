"""Feature (5): Authorized Market-Data Connectors & Entitlement Auditor (`src/atlas/assets/connectors.py`).

Establishes documented API contracts, entitlements, update frequencies, redistribution permissions,
delayed-vs-real-time labels, licensing cost tiers, and live SQLite store health checks across:
- Official Central Banks (Bank of Canada Valet, European Central Bank SDMX 2.1)
- Official Securities Regulators & Macro Authorities (SEC EDGAR XBRL, St. Louis Fed FRED)
- Authorized Broker & Market-Data Vendors (Alpaca IEX & Crypto, Massive/Polygon, Databento CME/Nasdaq, Questrade TSX)
- Public Spot Digital-Asset Venues (Coinbase Exchange, Binance, Kraken)
- Explicitly Labelled Unofficial Delayed Fallback (Yahoo Finance — internal research only, never commercial redistribution)
- Decommissioned Speculative Token Launchpads (Pump.fun / PumpSwap — disabled on active product roadmap).

Never invents market prices or assumes publicly visible quotes may be redistributed commercially.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

EXECUTION_PERMISSION = "none"


@dataclass(frozen=True)
class AuthorizedMarketDataConnector:
    connector_id: str
    title: str
    provider_type: Literal[
        "official_central_bank",
        "official_securities_regulator",
        "authorized_broker_or_vendor",
        "public_spot_digital_exchange",
        "unofficial_delayed_fallback",
        "decommissioned_speculative_launchpad",
    ]
    asset_classes_covered: tuple[str, ...]
    official_docs_url: str
    endpoint_contract: str
    auth_mechanism: str
    update_frequency: str
    latency_label: Literal["real_time", "delayed_15m", "end_of_day_reference", "as_filed_pit", "disabled"]
    delay_minutes: int
    cost_tier: Literal["free_open_government", "free_tier_with_key", "free_public_api", "paid_opt_in_disabled", "unofficial_free", "decommissioned"]
    commercial_redistribution_permitted: bool
    redistribution_and_licensing_terms: str
    enabled_on_active_roadmap: bool
    feed_provider_keys: tuple[str, ...]
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


AUTHORIZED_MARKET_DATA_CONNECTORS: tuple[AuthorizedMarketDataConnector, ...] = (
    AuthorizedMarketDataConnector(
        connector_id="bank_of_canada_valet",
        title="Bank of Canada Valet API (FXUSDCAD, CORRA, GoC Benchmark Yields)",
        provider_type="official_central_bank",
        asset_classes_covered=("fx_spot_reference", "fixed_income_bond", "cash_equivalent"),
        official_docs_url="https://www.bankofcanada.ca/valet/docs",
        endpoint_contract="GET https://www.bankofcanada.ca/valet/observations/{series_name}/json",
        auth_mechanism="Keyless official public REST endpoint",
        update_frequency="Daily business days (~16:30 ET)",
        latency_label="end_of_day_reference",
        delay_minutes=0,
        cost_tier="free_open_government",
        commercial_redistribution_permitted=True,
        redistribution_and_licensing_terms="Permitted under Bank of Canada Terms of Use with mandatory source attribution ('Source: Bank of Canada') and no implied endorsement.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("boc_valet",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="ecb_sdmx_fx",
        title="European Central Bank Statistical Data Portal (SDMX 2.1 EXR Reference Rates)",
        provider_type="official_central_bank",
        asset_classes_covered=("fx_spot_reference",),
        official_docs_url="https://data.ecb.europa.eu/help/api/data",
        endpoint_contract="GET https://data-api.ecb.europa.eu/service/data/EXR/D.USD+CAD.EUR.SP00.A",
        auth_mechanism="Keyless official SDMX 2.1 REST / XML endpoint",
        update_frequency="Daily TARGET business days (~16:00 CET)",
        latency_label="end_of_day_reference",
        delay_minutes=0,
        cost_tier="free_open_government",
        commercial_redistribution_permitted=True,
        redistribution_and_licensing_terms="Free reuse permitted under ECB Statistics Reuse Policy subject to explicit source attribution ('Source: European Central Bank').",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("ecb_fx",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="sec_edgar_xbrl",
        title="U.S. SEC EDGAR As-Filed XBRL Company Facts & Submissions API",
        provider_type="official_securities_regulator",
        asset_classes_covered=("public_equity", "etf_fund"),
        official_docs_url="https://www.sec.gov/os/accessing-edgar-data",
        endpoint_contract="GET https://data.sec.gov/api/xbrl/companyfacts/CIK{10_digit_cik}.json",
        auth_mechanism="Declared User-Agent header via ATLAS_SEC_USER_AGENT (<=10 req/s fair access)",
        update_frequency="Real-time as-filed point-in-time (acceptance_datetime)",
        latency_label="as_filed_pit",
        delay_minutes=0,
        cost_tier="free_open_government",
        commercial_redistribution_permitted=True,
        redistribution_and_licensing_terms="U.S. Government public-domain filing data; subject to SEC Fair Access <=10 requests/second rate limit.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("sec_edgar",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="fred_stlouisfed",
        title="Federal Reserve Economic Data (FRED / ALFRED — U.S. Treasury Yields & Macro)",
        provider_type="official_securities_regulator",
        asset_classes_covered=("fixed_income_bond", "cash_equivalent"),
        official_docs_url="https://fred.stlouisfed.org/docs/api/fred/",
        endpoint_contract="GET https://api.stlouisfed.org/fred/series/observations?series_id={id}",
        auth_mechanism="Query parameter api_key via FRED_API_KEY",
        update_frequency="Daily / Release-scheduled",
        latency_label="end_of_day_reference",
        delay_minutes=0,
        cost_tier="free_tier_with_key",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Public-domain Federal Reserve series may be displayed with attribution; third-party copyrighted series on FRED (e.g. ICE/S&P indices) may not be redistributed commercially.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("fred",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="alpaca_iex_and_crypto",
        title="Alpaca Markets REST v2 (IEX Equities & ETFs) + v1beta3 (US Crypto)",
        provider_type="authorized_broker_or_vendor",
        asset_classes_covered=("public_equity", "etf_fund", "cash_equivalent", "major_digital_asset"),
        official_docs_url="https://docs.alpaca.markets/docs/about-market-data-api",
        endpoint_contract="GET https://data.alpaca.markets/v2/stocks/bars (IEX) & /v1beta3/crypto/us/bars",
        auth_mechanism="APCA-API-KEY-ID / APCA-API-SECRET-KEY for IEX; keyless for v1beta3 crypto",
        update_frequency="1-minute & intraday bars (200 req/min free tier)",
        latency_label="real_time",
        delay_minutes=0,
        cost_tier="free_tier_with_key",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Free Basic plan covers single-user / internal research display via IEX exchange feed. Commercial multi-user redistribution or CTA/UTP SIP feeds require paid vendor & exchange licensing. Live trading endpoint (api.alpaca.markets) is strictly refused.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("alpaca", "alpaca_crypto"),
    ),
    AuthorizedMarketDataConnector(
        connector_id="polygon_massive",
        title="Massive.com (formerly Polygon.io) Market Data v2/v3 Aggregates",
        provider_type="authorized_broker_or_vendor",
        asset_classes_covered=("public_equity", "etf_fund", "fx_spot_reference"),
        official_docs_url="https://massive.com/docs/rest/stocks/aggregates/custom-bars",
        endpoint_contract="GET https://api.massive.com/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{from}/{to}",
        auth_mechanism="POLYGON_API_KEY or MASSIVE_API_KEY (5 req/min free Basic tier)",
        update_frequency="Previous-day bars (15m + daily) on free Basic tier",
        latency_label="end_of_day_reference",
        delay_minutes=15,
        cost_tier="free_tier_with_key",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Free Basic tier is restricted to personal/non-commercial research. Commercial display or redistribution requires a Massive/Polygon Business license and underlying exchange (Nasdaq/NYSE/OPRA) agreements.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("polygon",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="databento_glbx",
        title="Databento Institutional Historical & Live (CME Globex GLBX.MDP3 / Nasdaq XNAS.ITCH)",
        provider_type="authorized_broker_or_vendor",
        asset_classes_covered=("precious_metals", "regulated_derivative", "public_equity", "etf_fund"),
        official_docs_url="https://databento.com/docs/api-reference-historical",
        endpoint_contract="POST https://hist.databento.com/v0/timeseries.get_range",
        auth_mechanism="DATABENTO_API_KEY + ATLAS_DATABENTO_DATASET (disabled when ATLAS_ALLOW_PAID_DATA=false)",
        update_frequency="Tick / 1s / 1m / 1h / 1d (metered per GB)",
        latency_label="disabled",
        delay_minutes=0,
        cost_tier="paid_opt_in_disabled",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Billed institutional feed; kept disabled by default under ATLAS free-data rule (ATLAS_ALLOW_PAID_DATA=false). Commercial redistribution requires CME Group / Nasdaq display distributor licenses.",
        enabled_on_active_roadmap=False,
        feed_provider_keys=("databento",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="public_spot_crypto_exchanges",
        title="Coinbase Exchange, Binance & Kraken Public Spot Market Data",
        provider_type="public_spot_digital_exchange",
        asset_classes_covered=("major_digital_asset",),
        official_docs_url="https://docs.cdp.coinbase.com/exchange/docs/websocket-overview",
        endpoint_contract="wss://ws-feed.exchange.coinbase.com & REST /products/{id}/candles",
        auth_mechanism="Keyless public REST & WebSocket feeds",
        update_frequency="Real-time WebSocket ticks + 1m/15m/1h/1d candles",
        latency_label="real_time",
        delay_minutes=0,
        cost_tier="free_public_api",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Public venue APIs for internal research and paper simulation; subject to venue rate limits and terms of service.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("binance", "coinbase", "kraken", "bybit", "okx"),
    ),
    AuthorizedMarketDataConnector(
        connector_id="yahoo_finance_fallback",
        title="Yahoo Finance Chart v8 Fallback (Unofficial Delayed Research Fallback)",
        provider_type="unofficial_delayed_fallback",
        asset_classes_covered=("precious_metals", "etf_fund", "public_equity", "fixed_income_bond", "regulated_derivative", "fx_spot_reference"),
        official_docs_url="",
        endpoint_contract="GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        auth_mechanism="Keyless unofficial HTTP endpoint (disabled when ATLAS_DISABLE_UNOFFICIAL_DATA=true)",
        update_frequency="Polled intraday / daily fallback (15–20m exchange delay on futures/equities)",
        latency_label="delayed_15m",
        delay_minutes=15,
        cost_tier="unofficial_free",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="STRICTLY UNOFFICIAL FALLBACK: Tagged 'unofficial_delayed_source' across all UI and API responses. Never permitted for commercial redistribution or production SLA reliance.",
        enabled_on_active_roadmap=True,
        feed_provider_keys=("yahoo",),
    ),
    AuthorizedMarketDataConnector(
        connector_id="pump_fun_pumpswap_decommissioned",
        title="Pump.fun & PumpSwap Speculative Token Launchpad Indexer (Decommissioned)",
        provider_type="decommissioned_speculative_launchpad",
        asset_classes_covered=(),
        official_docs_url="https://github.com/pump-fun/pump-public-docs",
        endpoint_contract="Disabled on active product roadmap",
        auth_mechanism="Disabled (ATLAS_ENABLE_SPECULATIVE_LAUNCHPADS=false)",
        update_frequency="Disabled",
        latency_label="disabled",
        delay_minutes=0,
        cost_tier="decommissioned",
        commercial_redistribution_permitted=False,
        redistribution_and_licensing_terms="Removed from active ATLAS product roadmap under product scope and risk policy; historical audit and replay tests remain isolated for regression verification only.",
        enabled_on_active_roadmap=False,
        feed_provider_keys=(),
    ),
)


def audit_market_data_connectors(now: float | None = None) -> dict[str, Any]:
    """Inspect live SQLite feed store (`var/feeds/atlas_feed.sqlite`), provider health, and entitlement flags."""
    from atlas.feeds import feed as feed_mod
    from atlas.integrations.registry import load_env

    now_ts = float(now or time.time())
    env = load_env()
    db_path = feed_mod.DEFAULT_STORE

    provider_bar_counts: dict[str, dict[str, Any]] = {}
    provider_quote_counts: dict[str, int] = {}

    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        try:
            try:
                for prov, cnt, min_t, max_t, inst_cnt in conn.execute(
                    "SELECT provider, COUNT(*), MIN(event_time), MAX(event_time), COUNT(DISTINCT instrument) "
                    "FROM bars GROUP BY provider"
                ):
                    provider_bar_counts[str(prov)] = {
                        "stored_bars": int(cnt),
                        "distinct_instruments": int(inst_cnt),
                        "earliest_bar_epoch": int(min_t),
                        "latest_bar_epoch": int(max_t),
                        "latest_bar_age_seconds": max(0, int(now_ts - int(max_t))),
                    }
            except sqlite3.OperationalError:
                pass
            try:
                for prov, q_cnt in conn.execute("SELECT provider, COUNT(*) FROM last_quotes GROUP BY provider"):
                    provider_quote_counts[str(prov)] = int(q_cnt)
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

    connector_reports = []
    for c in AUTHORIZED_MARKET_DATA_CONNECTORS:
        bars_total = sum(provider_bar_counts.get(k, {}).get("stored_bars", 0) for k in c.feed_provider_keys)
        inst_total = sum(provider_bar_counts.get(k, {}).get("distinct_instruments", 0) for k in c.feed_provider_keys)
        quotes_total = sum(provider_quote_counts.get(k, 0) for k in c.feed_provider_keys)
        latest_epochs = [provider_bar_counts[k]["latest_bar_epoch"] for k in c.feed_provider_keys if k in provider_bar_counts]
        latest_epoch = max(latest_epochs) if latest_epochs else None

        configured = True
        if c.connector_id == "alpaca_iex_and_crypto":
            configured = bool(env.get("ALPACA_API_KEY_ID") and env.get("ALPACA_API_SECRET_KEY"))
        elif c.connector_id == "sec_edgar_xbrl":
            configured = bool(env.get("ATLAS_SEC_USER_AGENT"))
        elif c.connector_id == "fred_stlouisfed":
            configured = bool(env.get("FRED_API_KEY"))
        elif c.connector_id == "polygon_massive":
            configured = bool(env.get("POLYGON_API_KEY") or env.get("MASSIVE_API_KEY"))
        elif c.connector_id == "databento_glbx":
            configured = False
        elif c.connector_id == "pump_fun_pumpswap_decommissioned":
            configured = False

        connector_reports.append({
            **c.as_dict(),
            "credentials_or_access_configured": configured,
            "stored_bars_in_feed_db": bars_total,
            "distinct_instruments_in_feed_db": inst_total,
            "stored_quotes_in_feed_db": quotes_total,
            "latest_bar_epoch": latest_epoch,
            "health_status": (
                "decommissioned_by_policy"
                if not c.enabled_on_active_roadmap
                else ("active_with_stored_data" if (bars_total > 0 or quotes_total > 0) else ("ready_awaiting_env_key" if not configured else "standby"))
            ),
        })

    return {
        "feature_id": "feature_05_authorized_market_data_connectors",
        "as_of_epoch": int(now_ts),
        "feed_sqlite_path": db_path,
        "provider_bar_summary": provider_bar_counts,
        "provider_quote_summary": provider_quote_counts,
        "connectors": connector_reports,
        "commercial_redistribution_policy": (
            "Publicly visible or free-tier market data (Yahoo Finance, Alpaca Basic IEX, Massive Free Tier, Coinbase/Binance public WS) "
            "is restricted to internal research display and paper simulation. Commercial multi-user redistribution requires direct "
            "exchange/vendor distribution agreements (e.g., TMX Datalinx, CME Group Market Data, Nasdaq Basic/CTA SIP). "
            "Official Bank of Canada Valet and ECB SDMX reference series permit redistribution with mandatory source attribution."
        ),
        "execution_permission": EXECUTION_PERMISSION,
    }
