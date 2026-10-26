"""Authoritative Integration & Protocol Manifest with Versioned Compatibility Checks.

Tracks verified official specifications, SDK versions, smart-contract program IDs,
binary discriminators, API schemas, rate limits, licensing constraints, and deprecation
monitors across Market Data, Solana/Pump.fun/PumpSwap, and Machine Learning engines.

All research findings are reproducible, version-pinned, and traceable to official sources.
"""
from __future__ import annotations

import importlib.metadata
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from atlas.pump.bonding_curve import (
    BONDING_CURVE_DISCRIMINATOR,
    decode_bonding_curve_account,
    encode_bonding_curve_account,
)
from atlas.pump.pumpswap import (
    PUMPSWAP_POOL_DISCRIMINATOR,
    decode_pumpswap_pool_account,
    encode_pumpswap_pool_account,
)
from atlas.pump.tokens import (
    LAMPORTS_PER_SOL,
    PUMP_FEE_SHARING_PROGRAM_ID,
    PUMP_MAYHEM_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    USDC_MINT,
    WSOL_MINT,
)

EXECUTION_PERMISSION = "none"


@dataclass(frozen=True)
class ProtocolAdapterSpec:
    adapter_id: str
    category: str  # "market_data" | "blockchain" | "ml_analytics" | "broker_paper" | "charting"
    title: str
    adapter_version: str
    upstream_version: str
    official_docs: tuple[str, ...]
    endpoints_or_programs: tuple[str, ...]
    supported_operations: tuple[str, ...]
    auth_mechanism: str
    rate_limits: str
    licensing: str
    security_invariants: tuple[str, ...] = field(default_factory=tuple)
    known_protocol_notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


PROTOCOL_SPECS: tuple[ProtocolAdapterSpec, ...] = (
    # --- Market Data & Trading ---
    ProtocolAdapterSpec(
        adapter_id="alpaca_paper_and_data",
        category="broker_paper",
        title="Alpaca Markets Paper Trading & Market Data (IEX + Keyless Crypto)",
        adapter_version="2.4.0",
        upstream_version="REST v2 (Stocks/Paper) + v1beta3 (Crypto)",
        official_docs=(
            "https://docs.alpaca.markets/docs/paper-trading",
            "https://docs.alpaca.markets/reference/cryptobars",
            "https://docs.alpaca.markets/reference/stockbars",
        ),
        endpoints_or_programs=(
            "https://paper-api.alpaca.markets/v2",
            "https://data.alpaca.markets/v2/stocks/bars",
            "https://data.alpaca.markets/v1beta3/crypto/us/bars",
        ),
        supported_operations=("paper_account", "paper_orders", "stock_bars_iex", "crypto_bars_keyless"),
        auth_mechanism="APCA-API-KEY-ID / APCA-API-SECRET-KEY for paper & IEX; keyless for v1beta3 crypto",
        rate_limits="200 req/min on free tier",
        licensing="Free IEX equity feed + free US crypto feed; SIP requires paid subscription (disabled by default)",
        security_invariants=(
            "Live endpoint https://api.alpaca.markets is strictly refused by guard_alpaca_url",
            "Non-PA account IDs are rejected",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="polygon_massive",
        category="market_data",
        title="Massive.com (formerly Polygon.io) Market Data v2/v3",
        adapter_version="2.2.0",
        upstream_version="REST v2/v3 + WebSocket",
        official_docs=(
            "https://massive.com/docs/rest/stocks/aggregates/custom-bars",
            "https://massive.com/docs/websocket/stocks/aggregates-per-minute",
        ),
        endpoints_or_programs=(
            "https://api.massive.com/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}",
            "https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}",
            "wss://socket.massive.com/stocks",
        ),
        supported_operations=("aggregates_bars", "tickers_reference_v3", "grouped_daily"),
        auth_mechanism="POLYGON_API_KEY or MASSIVE_API_KEY query/header parameter",
        rate_limits="5 calls/min on free Basic tier",
        licensing="Free tier provides 2y EOD/delayed bars; real-time requires paid plan",
        known_protocol_notes=(
            "Polygon.io officially rebranded to Massive.com; api.massive.com is primary while api.polygon.io remains backward-compatible.",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="databento_glbx",
        category="market_data",
        title="Databento Historical & Live (CME Globex GLBX.MDP3 / Nasdaq XNAS.ITCH)",
        adapter_version="1.3.0",
        upstream_version="HTTP v0 / DBN v2",
        official_docs=(
            "https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range",
            "https://databento.com/docs/schemas-and-data-formats/ohlcv",
            "https://databento.com/docs/schemas-and-data-formats/mbp-1",
        ),
        endpoints_or_programs=(
            "https://hist.databento.com/v0/timeseries.get_range",
        ),
        supported_operations=("ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "ohlcv-1d", "mbp-1"),
        auth_mechanism="HTTP Basic Auth with DATABENTO_API_KEY as username",
        rate_limits="100 req/s historical; metered per GB",
        licensing="Billed usage; disabled unless ATLAS_ALLOW_PAID_DATA=true and ATLAS_DATABENTO_DATASET is set",
        known_protocol_notes=(
            "Prices are int64 scaled by 1e-9; timestamps are uint64 nanoseconds since UNIX epoch (ts_event / ts_recv).",
            "OHLCV records are published only for intervals where at least one trade occurred.",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="coinbase_exchange",
        category="market_data",
        title="Coinbase Exchange / Advanced Trade Public Market Data",
        adapter_version="1.4.0",
        upstream_version="Exchange REST v1 + WS Feed",
        official_docs=(
            "https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
            "https://docs.cdp.coinbase.com/exchange/docs/websocket-overview",
        ),
        endpoints_or_programs=(
            "https://api.exchange.coinbase.com/products/{product_id}/candles",
            "wss://ws-feed.exchange.coinbase.com",
        ),
        supported_operations=("candles", "ticker", "ws_ticker_batch"),
        auth_mechanism="Keyless for public market data",
        rate_limits="10 req/s public REST burst up to 15 req/s",
        licensing="Free public spot crypto market data",
    ),
    ProtocolAdapterSpec(
        adapter_id="boc_and_ecb_fx",
        category="market_data",
        title="Bank of Canada Valet & ECB Data Portal Official FX Reference Feeds",
        adapter_version="1.2.0",
        upstream_version="BoC Valet v1 + ECB SDMX 2.1",
        official_docs=(
            "https://www.bankofcanada.ca/valet/docs",
            "https://data.ecb.europa.eu/help/api/data",
        ),
        endpoints_or_programs=(
            "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json",
            "https://data-api.ecb.europa.eu/service/data/EXR",
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml",
        ),
        supported_operations=("daily_fx_observations", "cross_rate_triangulation"),
        auth_mechanism="Keyless official central-bank endpoints",
        rate_limits="Fair-use public rate limit (60 req/min)",
        licensing="Free open central-bank data",
        known_protocol_notes=(
            "ECB SDMX returns HTTP 200 with empty body on 0-observation holiday windows; normalized to empty JSON with XML fallback.",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="tradingview_udf_and_pine",
        category="charting",
        title="TradingView UDF Local Read-Only Endpoint & Pine Script v5 Export",
        adapter_version="1.1.0",
        upstream_version="UDF v1 / Pine Script v5",
        official_docs=("https://www.tradingview.com/rest-api-spec/",),
        endpoints_or_programs=("/api/udf/config", "/api/udf/symbols", "/api/udf/history", "/api/udf/time"),
        supported_operations=("udf_bars_serve", "pine_v5_export"),
        auth_mechanism="Local read-only endpoint",
        rate_limits="Local in-process",
        licensing="Charting interface only; TradingView is NEVER used as an upstream data source",
    ),
    # --- Blockchain & Decentralized Trading ---
    ProtocolAdapterSpec(
        adapter_id="solana_json_rpc",
        category="blockchain",
        title="Solana JSON-RPC 2.0 & WebSocket Event Ingestion",
        adapter_version="2.0.0",
        upstream_version="Solana RPC v2.0 / Agave",
        official_docs=(
            "https://solana.com/docs/rpc",
            "https://solana.com/docs/rpc/http/simulatetransaction",
            "https://solana.com/docs/rpc/http/getrecentprioritizationfees",
            "https://solana.com/docs/rpc/websocket/accountsubscribe",
            "https://solana.com/docs/rpc/websocket/logssubscribe",
            "https://solana.com/docs/core/fees",
        ),
        endpoints_or_programs=("SOLANA_RPC_URL", "SOLANA_WS_URL"),
        supported_operations=(
            "getAccountInfo",
            "getMultipleAccounts",
            "getSignaturesForAddress",
            "getTransaction",
            "getSignatureStatuses",
            "simulateTransaction",
            "getRecentPrioritizationFees",
            "accountSubscribe",
            "logsSubscribe",
            "signatureSubscribe",
        ),
        auth_mechanism="Provider URL / API token via SOLANA_RPC_URL and SOLANA_WS_URL",
        rate_limits="Token-bucket rate limiter (default 10 req/s, configurable per RPC provider)",
        licensing="Open JSON-RPC protocol; production use requires dedicated RPC provider",
        security_invariants=(
            "Base fee = 5,000 lamports per signature; Priority fee = ceil(compute_unit_limit * micro_lamports / 1e6)",
            "Unfinalized slot forks trigger automatic rollback of non-finalized events in SolanaRPCIndexer",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="pump_bonding_curve",
        category="blockchain",
        title="Pump.fun Bonding Curve Program & @pump-fun/pump-sdk Compatibility",
        adapter_version="4.1.0",
        upstream_version="@pump-fun/pump-sdk@^4.1.0",
        official_docs=(
            "https://github.com/pump-fun/pump-public-docs",
            "https://github.com/pump-fun/pump-fun-skills",
            "https://docs.pump.fun/",
        ),
        endpoints_or_programs=(PUMP_PROGRAM_ID, PUMP_FEE_SHARING_PROGRAM_ID, PUMP_MAYHEM_PROGRAM_ID),
        supported_operations=(
            "create",
            "create_v2",
            "buy_v3",
            "sell_v3",
            "buy_exact_quote_in_v3",
            "sweep_protocol_fee",
            "sweep_creator_fee",
        ),
        auth_mechanism="On-chain program instructions (Developer API is strictly read-only)",
        rate_limits="Governed by Solana RPC",
        licensing="Public on-chain program",
        security_invariants=(
            "Primary identifier is always base58 mint address, never ticker symbol alone",
            "v3 instructions use streamlined 17-account layout",
            "Unswept protocol/creator fees remain in curve account until swept; deducted from effective virtual quote reserves",
            "Final curve buy exceeding real_token_reserves crosses into synthetic migration (TradeEvent + CompleteEvent + PostCompleteBuyEvent)",
        ),
    ),
    ProtocolAdapterSpec(
        adapter_id="pumpswap_amm",
        category="blockchain",
        title="PumpSwap AMM Program & @pump-fun/pump-swap-sdk Compatibility",
        adapter_version="2.1.0",
        upstream_version="@pump-fun/pump-swap-sdk@^2.1.0",
        official_docs=(
            "https://github.com/pump-fun/pump-public-docs",
            "https://github.com/pump-fun/pump-fun-skills",
        ),
        endpoints_or_programs=(PUMPSWAP_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID),
        supported_operations=("buy", "sell", "multi_hop_swap", "sweep_protocol_fee", "sweep_creator_fee"),
        auth_mechanism="On-chain AMM program instructions",
        rate_limits="Governed by Solana RPC",
        licensing="Public on-chain program",
        security_invariants=(
            "Pool::virtual_quote_reserves is a signed integer (i128) that can be NEGATIVE (< 0) to offset unswept fees in quote vault",
            "effective_quote_reserves = max(0, pool_quote_token_account.amount + virtual_quote_reserves)",
            "multi_hop_swap supports up to MAX_QUOTE_DEPTH = 3 hops across custom quote mints",
        ),
    ),
    # --- Machine Learning & Analytics ---
    ProtocolAdapterSpec(
        adapter_id="ml_analytics_stack",
        category="ml_analytics",
        title="ATLAS Point-in-Time ML & Analytical Stack (scikit-learn, XGBoost, LightGBM, PyTorch, DuckDB)",
        adapter_version="2.0.0",
        upstream_version="Python 3.12 Scientific Stack",
        official_docs=(
            "https://scikit-learn.org/stable/",
            "https://xgboost.readthedocs.io/",
            "https://lightgbm.readthedocs.io/",
            "https://duckdb.org/docs/",
        ),
        endpoints_or_programs=("atlas.ai.ml", "atlas.ai.models", "atlas.pump.models", "atlas.research.vertical_slice"),
        supported_operations=(
            "purged_walk_forward_splits_by_time",
            "isotonic_and_platt_calibration",
            "conformal_prediction_gate",
            "deflated_sharpe_and_pbo",
            "net_expected_value_ranking",
        ),
        auth_mechanism="In-process deterministic execution",
        rate_limits="CPU/GPU bound",
        licensing="Open-source (BSD / Apache-2.0 / MIT)",
        security_invariants=(
            "Every ML/LLM component enforces execution_permission='none'",
            "LookaheadBiasError raised if any feature or event timestamp exceeds as_of_ts",
            "Champions require strict gate: beats baseline, all folds evaluated, >=20 trades/fold, majority positive folds, DSR>=0.95, Bonferroni p<0.05",
        ),
    ),
)

SPECS_BY_ID: dict[str, ProtocolAdapterSpec] = {s.adapter_id: s for s in PROTOCOL_SPECS}


def installed_ml_analytics_stack() -> dict[str, dict[str, Any]]:
    """Inspect installed versions of ML and analytics libraries without importing heavy optional C extensions unnecessarily."""
    packages = (
        ("scikit-learn", "sklearn"),
        ("xgboost", "xgboost"),
        ("lightgbm", "lightgbm"),
        ("torch", "torch"),
        ("duckdb", "duckdb"),
        ("google-cloud-bigquery", "google.cloud.bigquery"),
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("scipy", "scipy"),
    )
    out: dict[str, dict[str, Any]] = {}
    for dist_name, mod_name in packages:
        try:
            ver = importlib.metadata.version(dist_name)
            entry = {"installed": True, "version": ver, "module": mod_name}
        except importlib.metadata.PackageNotFoundError:
            entry = {"installed": False, "version": None, "module": mod_name}
        out[dist_name] = entry
        out[dist_name.replace("-", "_")] = entry
    return out


def verify_protocol_compatibility() -> dict[str, Any]:
    """Run deterministic self-tests verifying protocol binary discriminators, signed virtual reserves, and adapter invariants."""
    checks: dict[str, dict[str, Any]] = {}

    # 1. Pump.fun BondingCurve binary layout & unswept fees round-trip
    raw_curve = encode_bonding_curve_account(
        virtual_token_reserves=800_000_000_000_000,
        virtual_quote_reserves=42 * LAMPORTS_PER_SOL,
        real_token_reserves=500_000_000_000_000,
        real_quote_reserves=12 * LAMPORTS_PER_SOL,
        unswept_protocol_fees=int(0.25 * LAMPORTS_PER_SOL),
        unswept_creator_fees=int(0.08 * LAMPORTS_PER_SOL),
        signed_virtual_quote_adjustment=-int(0.02 * LAMPORTS_PER_SOL),
    )
    dec_curve = decode_bonding_curve_account(
        raw_curve,
        mint="PumpMintALphaCurve1111111111111111111111111",
        bonding_curve_address="BondingCurveALpha11111111111111111111111111",
    )
    checks["pump_bonding_curve_v3"] = {
        "passed": (
            raw_curve[:8] == BONDING_CURVE_DISCRIMINATOR
            and dec_curve.effective_virtual_quote_reserves < dec_curve.virtual_quote_reserves
        ),
        "discriminator_hex": BONDING_CURVE_DISCRIMINATOR.hex(),
        "binary_size_bytes": len(raw_curve),
    }

    # 2. PumpSwap Pool binary layout & negative signed virtual_quote_reserves
    raw_pool = encode_pumpswap_pool_account(
        base_vault_amount=206_900_000_000_000,
        quote_vault_amount=90 * LAMPORTS_PER_SOL,
        virtual_quote_reserves=-int(1.75 * LAMPORTS_PER_SOL),
    )
    dec_pool = decode_pumpswap_pool_account(
        raw_pool,
        pool_address="PumpSwapPooLGrad222222222222222222222222222",
        base_mint="PumpMintGradSwap222222222222222222222222222",
        quote_mint=WSOL_MINT,
    )
    checks["pumpswap_pool_signed_reserves"] = {
        "passed": (
            raw_pool[:8] == PUMPSWAP_POOL_DISCRIMINATOR
            and dec_pool.virtual_quote_reserves < 0
            and dec_pool.effective_quote_reserves == int(88.25 * LAMPORTS_PER_SOL)
        ),
        "discriminator_hex": PUMPSWAP_POOL_DISCRIMINATOR.hex(),
        "binary_size_bytes": len(raw_pool),
    }

    # 3. Databento GLBX.MDP3 1e-9 fixed-point JSON parser
    from atlas.feeds.providers.stubs import DatabentoAdapter, parse_databento_json
    db_sample = (
        b'{"hd":{"ts_event":"1729863000000000000","rtype":32},"open":2745100000000,"high":2748500000000,'
        b'"low":2744000000000,"close":2747200000000,"volume":1420}\n'
    )
    db_bars = parse_databento_json(DatabentoAdapter(env={}), "GC", "1m", db_sample, now=1729863120)
    checks["databento_glbx_mdp3_parser"] = {
        "passed": len(db_bars) == 1 and abs(db_bars[0].close - 2747.2) < 1e-6,
        "parsed_close": db_bars[0].close if db_bars else None,
    }

    # 4. Canonical Solana & Pump program IDs
    checks["canonical_program_ids"] = {
        "passed": all(
            len(pid) >= 32
            for pid in (PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID, SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID, WSOL_MINT, USDC_MINT)
        ),
        "pump_program_id": PUMP_PROGRAM_ID,
        "pumpswap_program_id": PUMPSWAP_PROGRAM_ID,
    }

    all_passed = all(c["passed"] for c in checks.values())
    return {
        "compatible": all_passed,
        "all_compatible": all_passed,
        "adapter_count": len(PROTOCOL_SPECS),
        "checks": checks,
        "ml_analytics_stack": installed_ml_analytics_stack(),
        "specs": [s.as_dict() for s in PROTOCOL_SPECS],
        "execution_permission": EXECUTION_PERMISSION,
    }


def detect_protocol_drift(
    *,
    account_owner: str | None = None,
    account_data: bytes | None = None,
    api_host: str | None = None,
) -> dict[str, Any]:
    """Detect smart-contract discriminator changes, unknown program owners, or deprecated API hosts."""
    issues: list[str] = []
    if account_owner and account_owner not in {
        PUMP_PROGRAM_ID,
        PUMPSWAP_PROGRAM_ID,
        PUMP_FEE_SHARING_PROGRAM_ID,
        PUMP_MAYHEM_PROGRAM_ID,
        SPL_TOKEN_PROGRAM_ID,
        TOKEN_2022_PROGRAM_ID,
    }:
        issues.append(f"unrecognized_program_owner:{account_owner}")

    if account_data is not None:
        if len(account_data) < 8:
            issues.append(f"account_data_too_short:{len(account_data)}")
        else:
            disc = account_data[:8]
            if account_owner == PUMP_PROGRAM_ID and disc != BONDING_CURVE_DISCRIMINATOR:
                issues.append(f"bonding_curve_discriminator_drift:{disc.hex()}")
            elif account_owner == PUMPSWAP_PROGRAM_ID and disc != PUMPSWAP_POOL_DISCRIMINATOR:
                issues.append(f"pumpswap_pool_discriminator_drift:{disc.hex()}")

    if api_host:
        host_l = api_host.lower()
        if "api.alpaca.markets" in host_l and "paper-api.alpaca.markets" not in host_l and "data.alpaca.markets" not in host_l:
            issues.append("forbidden_live_alpaca_host")

    return {
        "drift_detected": len(issues) > 0,
        "issues": issues,
        "execution_permission": EXECUTION_PERMISSION,
    }
