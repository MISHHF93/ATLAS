"""Ledger input events. Money amounts are Decimal. Timestamps are tz-aware;
the trade DATE (America/Toronto) is used for FX and the 30-day windows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from atlas.tax.fx import FxQuote

AssetType = Literal["security", "crypto"]


@dataclass(frozen=True)
class CryptoFee:
    property: str
    qty: Decimal
    fmv_cad: Decimal


@dataclass(frozen=True)
class Trade:
    id: str
    entity: str
    venue: str
    ts: datetime
    property: str                 # identical-property key (e.g. ISIN, or crypto ticker)
    side: Literal["buy", "sell"]
    qty: Decimal
    price: Decimal                # per unit, in `currency`
    currency: str = "CAD"
    fee: Decimal = Decimal(0)     # in `currency`
    crypto_fee: CryptoFee | None = None   # fee paid in a crypto asset (itself a disposition)
    asset_type: AssetType = "security"
    foreign: bool = False         # specified foreign property (T1135)
    automated: bool = True
    fx: FxQuote | None = None     # filled by the engine if None


@dataclass(frozen=True)
class Swap:
    """Crypto-to-crypto: disposition of `give` at FMV of what is received; acquisition of `get` at that FMV."""
    id: str
    entity: str
    venue: str
    ts: datetime
    give_property: str
    give_qty: Decimal
    get_property: str
    get_qty: Decimal
    fmv_cad: Decimal
    crypto_fee: CryptoFee | None = None
    automated: bool = True


@dataclass(frozen=True)
class Transfer:
    """Wallet/venue transfer between accounts of the SAME taxpayer: not a disposition,
    but out/in legs must link by transfer_id. A network fee paid in the asset is a disposition."""
    id: str
    transfer_id: str
    entity: str
    venue: str
    ts: datetime
    property: str
    qty: Decimal
    direction: Literal["out", "in"]
    network_fee_qty: Decimal = Decimal(0)
    network_fee_fmv_cad: Decimal = Decimal(0)


@dataclass(frozen=True)
class Income:
    """Staking/rewards: income at FMV, acquisition with cost = FMV."""
    id: str
    entity: str
    venue: str
    ts: datetime
    property: str
    qty: Decimal
    fmv_cad: Decimal
    kind: str = "staking"


@dataclass(frozen=True)
class Dividend:
    id: str
    entity: str
    ts: datetime
    property: str
    gross: Decimal
    currency: str
    withheld: Decimal = Decimal(0)
    country: str = "US"
    fx: FxQuote | None = None
