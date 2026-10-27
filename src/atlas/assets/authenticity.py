"""Feature (6): Instrument Authenticity, Identifier Checksums & Data Quality Engine (`src/atlas/assets/authenticity.py`).

Responsibilities:
- Verify instrument identity through authoritative mathematical checksums:
  - ISO 6166 ISIN (12-char alphanumeric Luhn mod-10)
  - ANSI X9.6 CUSIP (9-char alphanumeric mod-10)
  - ISO 17442 LEI (20-char alphanumeric mod-97-10)
  - SEC EDGAR CIK (10-digit zero-padded Central Index Key)
  - ISO 10383 MIC (4-char Market Identifier Code)
  - ISO 4217 Currency & Precious Metal codes
- Reconcile conflicting market-data sources (e.g. ECB SDMX vs Yahoo on EUR_USD; BoC Valet vs Yahoo on USD_CAD;
  Binance vs Coinbase on BTC) and report divergence in basis points.
- Detect stale prices, duplicate symbol collisions, delisted/unlisted private entities (e.g. SPACEX, STRIPE, OPENAI),
  corporate-action split/dividend jump anomalies, and unvetted speculative launchpad tokens.
- Strictly separate **Instrument Authenticity** (whether an instrument's identity, issuer, and exchange listing are
  verifiably registered) from **Investment Safety or Custodian Reliability** (`investment_safety_score = None`).
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

EXECUTION_PERMISSION = "none"

AUTHENTICITY_VS_SAFETY_DISCLOSURE = (
    "Instrument authenticity verification confirms only that the ticker, ISIN/CUSIP/CIK/LEI identifier, issuer, "
    "and exchange or central-bank reference correspond to a documented registration record. It is NOT an "
    "investment safety score, credit rating, custodian guarantee, or recommendation to buy, sell, or hold any security."
)

KNOWN_UNLISTED_PRIVATE_ENTITIES: frozenset[str] = frozenset({
    "SPACEX", "STRIPE", "OPENAI", "ANTHROPIC", "DATABRICKS", "BYTEDANCE", "ANDURIL", "CANVA", "SHEIN", "VALVE",
})

VALID_ISO10383_MICS: frozenset[str] = frozenset({
    "XNAS",  # Nasdaq — All Markets
    "XNYS",  # New York Stock Exchange
    "ARCX",  # NYSE Arca
    "BATS",  # Cboe BZX
    "XTSE",  # Toronto Stock Exchange (TSX)
    "XTSX",  # TSX Venture Exchange
    "XCEC",  # COMEX (CME Group)
    "XCME",  # Chicago Mercantile Exchange
    "XNYM",  # New York Mercantile Exchange (NYMEX)
    "XCBT",  # Chicago Board of Trade (CBOT)
    "BOC",   # Bank of Canada Reference
    "ECB",   # European Central Bank Reference
    "LBMA",  # London Bullion Market Association Reference
    "UST",   # U.S. Department of the Treasury Direct / Fiscal Reference
    "GOC",   # Government of Canada Debt Reference
    "SPOT",  # Regulated Digital Asset Spot Aggregation
})

VALID_ISO4217_CODES: frozenset[str] = frozenset({
    "USD", "CAD", "EUR", "JPY", "GBP", "CHF", "AUD", "XAU", "XAG", "XPT", "XPD",
})


def compute_cusip_check_digit(cusip8: str) -> str:
    """Compute ANSI X9.6 mod-10 check digit for an 8-character CUSIP base."""
    clean = cusip8.strip().upper()
    if len(clean) != 8 or not re.match(r"^[0-9A-Z*@#]{8}$", clean):
        raise ValueError(f"Invalid 8-character CUSIP base: {cusip8!r}")
    total = 0
    for idx, ch in enumerate(clean):
        if "0" <= ch <= "9":
            val = ord(ch) - ord("0")
        elif "A" <= ch <= "Z":
            val = ord(ch) - ord("A") + 10
        elif ch == "*":
            val = 36
        elif ch == "@":
            val = 37
        else:
            val = 38
        if idx % 2 == 1:
            val *= 2
        total += (val // 10) + (val % 10)
    return str((10 - (total % 10)) % 10)


def make_cusip(cusip8: str) -> str:
    """Build a valid 9-character CUSIP from an 8-character base."""
    base = cusip8.strip().upper()[:8]
    return base + compute_cusip_check_digit(base)


def validate_cusip(cusip: str | None) -> bool:
    """Validate a 9-character ANSI X9.6 CUSIP checksum."""
    if not cusip or len(cusip.strip()) != 9:
        return False
    clean = cusip.strip().upper()
    if not re.match(r"^[0-9A-Z*@#]{9}$", clean):
        return False
    try:
        return compute_cusip_check_digit(clean[:8]) == clean[8]
    except ValueError:
        return False


def compute_isin_check_digit(isin11: str) -> str:
    """Compute ISO 6166 Luhn mod-10 check digit for an 11-character ISIN prefix (2-char country + 9-char NSIN)."""
    clean = isin11.strip().upper()
    if len(clean) != 11 or not re.match(r"^[A-Z]{2}[0-9A-Z]{9}$", clean):
        raise ValueError(f"Invalid 11-character ISIN prefix: {isin11!r}")
    expanded = "".join(str(ord(ch) - 55) if "A" <= ch <= "Z" else ch for ch in clean)
    total = 0
    # Rightmost digit of the payload is doubled in Luhn check digit calculation
    for idx, digit_ch in enumerate(reversed(expanded)):
        d = int(digit_ch)
        if idx % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)


def make_isin(country_code: str, cusip_or_nsin9: str) -> str:
    """Construct a mathematically valid 12-character ISO 6166 ISIN."""
    cc = country_code.strip().upper()
    nsin = cusip_or_nsin9.strip().upper()
    if len(nsin) == 8:
        nsin = make_cusip(nsin)
    prefix = f"{cc}{nsin}"
    return prefix + compute_isin_check_digit(prefix)


def validate_isin(isin: str | None) -> bool:
    """Validate a 12-character ISO 6166 ISIN checksum."""
    if not isin or len(isin.strip()) != 12:
        return False
    clean = isin.strip().upper()
    if not re.match(r"^[A-Z]{2}[0-9A-Z]{9}[0-9]$", clean):
        return False
    try:
        return compute_isin_check_digit(clean[:11]) == clean[11]
    except ValueError:
        return False


def make_lei(prefix18: str) -> str:
    """Construct a valid 20-character ISO 17442 LEI from an 18-character alphanumeric prefix."""
    clean = prefix18.strip().upper()
    if len(clean) != 18 or not re.match(r"^[0-9A-Z]{18}$", clean):
        raise ValueError(f"Invalid 18-character LEI prefix: {prefix18!r}")
    numeric_str = "".join(str(ord(ch) - 55) if "A" <= ch <= "Z" else ch for ch in clean) + "00"
    check = 98 - (int(numeric_str) % 97)
    return f"{clean}{check:02d}"


def validate_lei(lei: str | None) -> bool:
    """Validate a 20-character ISO 17442 Legal Entity Identifier (mod-97-10 == 1)."""
    if not lei or len(lei.strip()) != 20:
        return False
    clean = lei.strip().upper()
    if not re.match(r"^[0-9A-Z]{18}[0-9]{2}$", clean):
        return False
    numeric_str = "".join(str(ord(ch) - 55) if "A" <= ch <= "Z" else ch for ch in clean)
    return int(numeric_str) % 97 == 1


def validate_sec_cik(cik: str | None) -> bool:
    """Validate a 10-digit zero-padded SEC EDGAR Central Index Key."""
    if not cik:
        return False
    clean = cik.strip()
    return bool(re.match(r"^0[0-9]{9}$", clean)) and int(clean) > 0


@dataclass(frozen=True)
class AuthenticityVerificationReport:
    symbol: str
    instrument_id: str | None
    identity_verified: bool
    verification_status: str  # "verified_authentic" | "unlisted_private_entity" | "unvetted_speculative_token" | "unverified_identifier"
    identifier_checks: Mapping[str, bool | None]
    source_reconciliation: Mapping[str, Any]
    freshness_check: Mapping[str, Any]
    corporate_action_flags: tuple[str, ...]
    duplicate_listing_collision: bool
    investment_safety_score: None = None
    custodian_reliability_guarantee: None = None
    authenticity_vs_safety_disclosure: str = AUTHENTICITY_VS_SAFETY_DISCLOSURE
    execution_permission: str = EXECUTION_PERMISSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconcile_instrument_sources(symbol: str, now: float | None = None) -> dict[str, Any]:
    """Compare stored quotes and bars across providers in `atlas_feed.sqlite` for cross-source reconciliation."""
    from atlas.api.feeds_api import _feed
    from atlas.feeds.universe import resolve

    now_ts = float(now or time.time())
    feed = _feed()
    iid = resolve(symbol) or symbol.strip().upper()
    if feed is None or iid not in feed.instruments:
        return {
            "instrument": iid,
            "reconciled": False,
            "providers_checked": [],
            "max_divergence_bps": None,
            "status": "no_feed_series",
        }

    inst = feed.instruments.get(iid)
    all_providers = list(dict.fromkeys([*inst.provider_priority, *inst.sanity_providers]))
    prices_by_provider: dict[str, float] = {}
    timestamps_by_provider: dict[str, int] = {}

    for prov in all_providers:
        for iv in ("1d", "1h", "15m", "1m"):
            bars = feed.store.bars(iid, iv, None, int(now_ts) + 86400, provider=prov, confirmed_only=False)
            if bars:
                prices_by_provider[prov] = float(bars[-1].close)
                timestamps_by_provider[prov] = int(bars[-1].event_time)
                break

    for q in feed.store.last_quotes(iid):
        prov = str(q.get("provider") or "")
        price = float(q.get("price") or 0.0)
        if prov and price > 0 and prov not in prices_by_provider:
            prices_by_provider[prov] = price
            timestamps_by_provider[prov] = int(q.get("event_time") or 0)

    if len(prices_by_provider) >= 2:
        vals = list(prices_by_provider.values())
        mid = sum(vals) / len(vals)
        max_div_bps = round(((max(vals) - min(vals)) / mid) * 10_000.0, 2) if mid > 0 else 0.0
        status = "reconciled_within_tolerance" if max_div_bps <= 150.0 else "provider_divergence_flagged"
    elif len(prices_by_provider) == 1:
        max_div_bps = 0.0
        status = "single_provider_observed"
    else:
        max_div_bps = None
        status = "no_stored_prints"

    return {
        "instrument": iid,
        "reconciled": status in ("reconciled_within_tolerance", "single_provider_observed"),
        "providers_checked": list(prices_by_provider.keys()),
        "prices_by_provider": prices_by_provider,
        "timestamps_by_provider": timestamps_by_provider,
        "max_divergence_bps": max_div_bps,
        "status": status,
    }


def detect_corporate_action_or_split_flags(symbol: str) -> tuple[str, ...]:
    """Scan recent daily bars for >25% single-session discontinuities indicative of splits, distributions, or roll events."""
    from atlas.api.feeds_api import _feed
    from atlas.feeds.universe import resolve

    feed = _feed()
    iid = resolve(symbol) or symbol.strip().upper()
    if feed is None or iid not in feed.instruments:
        return ()
    bars = feed.store.bars(iid, "1d", None, None, confirmed_only=True)[-60:]
    flags: list[str] = []
    for prev_b, cur_b in zip(bars, bars[1:]):
        if prev_b.close > 0:
            jump_pct = abs(cur_b.open - prev_b.close) / prev_b.close * 100.0
            if jump_pct >= 25.0:
                flags.append(
                    f"overnight_discontinuity_{jump_pct:.1f}pct_at_{cur_b.event_time}_verify_split_or_contract_roll"
                )
    return tuple(flags)


def verify_instrument_authenticity(
    symbol: str,
    *,
    master_record: Any | None = None,
    all_symbols: Sequence[str] | None = None,
    now: float | None = None,
) -> AuthenticityVerificationReport:
    """Run full Feature (6) authenticity, checksum, cross-source reconciliation, and freshness verification."""
    from atlas.api.feeds_api import feed_quotes
    from atlas.assets.master import get_canonical_asset_master

    clean = symbol.strip().upper()
    now_ts = float(now or time.time())

    # 1. Reject unlisted private companies
    if clean in KNOWN_UNLISTED_PRIVATE_ENTITIES:
        return AuthenticityVerificationReport(
            symbol=clean,
            instrument_id=None,
            identity_verified=False,
            verification_status="unlisted_private_entity",
            identifier_checks={"public_listing": False, "isin": None, "cusip": None, "cik": None, "mic": False},
            source_reconciliation={"status": "unlisted_private_company_no_public_market_quote"},
            freshness_check={"status": "no_data", "stale": True, "reason": "Private company — not listed on a public exchange"},
            corporate_action_flags=(),
            duplicate_listing_collision=False,
        )

    # 2. Reject base58 Solana mints / speculative bonding-curve tokens on the authentic catalog surface
    if len(symbol.strip()) >= 32 and re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", symbol.strip()):
        return AuthenticityVerificationReport(
            symbol=symbol.strip(),
            instrument_id=None,
            identity_verified=False,
            verification_status="unvetted_speculative_token",
            identifier_checks={"public_listing": False, "isin": False, "cusip": False, "cik": False, "mic": False},
            source_reconciliation={"status": "excluded_speculative_token_launchpad"},
            freshness_check={"status": "excluded_by_product_policy", "stale": True},
            corporate_action_flags=("speculative_launchpad_excluded_from_authentic_catalog",),
            duplicate_listing_collision=False,
        )

    master = get_canonical_asset_master()
    rec = master_record or master.get_instrument(clean)
    if rec is None:
        return AuthenticityVerificationReport(
            symbol=clean,
            instrument_id=None,
            identity_verified=False,
            verification_status="unverified_identifier",
            identifier_checks={"in_canonical_master": False},
            source_reconciliation={"status": "unknown_symbol"},
            freshness_check={"status": "no_data", "stale": True},
            corporate_action_flags=(),
            duplicate_listing_collision=False,
        )

    ids = rec.identifiers
    issuer = master.get_issuer(rec.issuer_id)
    isin_ok = validate_isin(ids.isin) if ids.isin else None
    cusip_ok = validate_cusip(ids.cusip) if ids.cusip else None
    cik_ok = validate_sec_cik(ids.cik) if ids.cik else (validate_sec_cik(issuer.cik) if issuer and issuer.cik else None)
    lei_ok = validate_lei(ids.lei) if ids.lei else (validate_lei(issuer.lei) if issuer and issuer.lei else None)
    mic_ok = rec.primary_exchange_mic in VALID_ISO10383_MICS
    ccy_ok = rec.currency in VALID_ISO4217_CODES

    id_checks: dict[str, bool | None] = {
        "in_canonical_master": True,
        "isin_luhn_mod10": isin_ok,
        "cusip_ansi_mod10": cusip_ok,
        "sec_cik_10digit": cik_ok,
        "issuer_lei_iso17442": lei_ok,
        "exchange_mic_iso10383": mic_ok,
        "currency_iso4217": ccy_ok,
    }

    # Check that every present identifier passed its mathematical checksum
    present_checks = [v for v in id_checks.values() if v is not None]
    identity_verified = bool(present_checks) and all(present_checks)

    # Quote freshness & source reconciliation
    q_map = feed_quotes([rec.identifiers.feed_instrument_id or rec.symbol], now_ts)
    q = next(iter(q_map.values()), {})
    q_status = str(q.get("status") or "no_data")
    age_s = q.get("age_seconds")
    freshness = {
        "quote_status": q_status,
        "price": q.get("price"),
        "source": q.get("source"),
        "observed_at_toronto": q.get("observed_at_toronto"),
        "age_seconds": age_s,
        "stale": q_status in ("stale", "no_data") and rec.trading_status == "active",
    }

    reconcile = reconcile_instrument_sources(rec.identifiers.feed_instrument_id or rec.symbol, now_ts)
    corp_flags = detect_corporate_action_or_split_flags(rec.identifiers.feed_instrument_id or rec.symbol)

    symbol_pool = list(all_symbols) if all_symbols is not None else [i.symbol for i in master.list_instruments()]
    dup_collision = symbol_pool.count(rec.symbol) > 1

    return AuthenticityVerificationReport(
        symbol=rec.symbol,
        instrument_id=rec.instrument_id,
        identity_verified=identity_verified,
        verification_status="verified_authentic" if identity_verified else "unverified_identifier",
        identifier_checks=id_checks,
        source_reconciliation=reconcile,
        freshness_check=freshness,
        corporate_action_flags=corp_flags,
        duplicate_listing_collision=dup_collision,
    )

