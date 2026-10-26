"""Pump.fun & Solana token identity, metadata, constants, and causal lifecycle state machine.

Primary identifier rule: every token is identified by its base58 Solana mint address (`mint`),
NEVER by ticker symbol alone (symbol collisions are routine on Pump.fun).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# Official Solana & Pump.fun program IDs (verified against github.com/pump-fun/pump-public-docs)
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_FEE_SHARING_PROGRAM_ID = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
PUMP_MAYHEM_PROGRAM_ID = "MAyhSmzXzV1pTf7LsNkrNwkWKTo4ougAJ1PPg47MD4e"

SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

# Canonical quote mints
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CANONICAL_QUOTE_MINTS = {
    WSOL_MINT: {"symbol": "SOL", "decimals": 9},
    USDC_MINT: {"symbol": "USDC", "decimals": 6},
}
MAX_QUOTE_DEPTH = 2  # create_v2 allows Pump coins as quote mints up to bounded hierarchy depth

DEFAULT_TOKEN_DECIMALS = 6
LAMPORTS_PER_SOL = 1_000_000_000

_BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def is_valid_pubkey(addr: str) -> bool:
    """Validate a base58 Solana public key / mint address."""
    if not isinstance(addr, str) or not (32 <= len(addr) <= 44):
        return False
    return all(ch in _BASE58_ALPHABET for ch in addr)


def assert_mint_identifier(identifier: str) -> str:
    """Enforce that callers pass a valid base58 mint address, never a bare ticker symbol."""
    if not is_valid_pubkey(identifier):
        raise ValueError(
            f"Invalid Solana mint address {identifier!r}: tokens must be identified by base58 mint address, never by symbol alone."
        )
    return identifier


class TokenLifecycleState(str, Enum):
    """Causal token lifecycle states."""
    DISCOVERED = "DISCOVERED"
    CURVE_ACTIVE = "CURVE_ACTIVE"
    MIGRATION_PENDING = "MIGRATION_PENDING"
    PUMPSWAP_ACTIVE = "PUMPSWAP_ACTIVE"
    UNSUPPORTED = "UNSUPPORTED"
    SUSPENDED = "SUSPENDED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
    RISK_REJECTED = "RISK_REJECTED"


# Allowed causal transitions. Any active state may transition to status/rejection states,
# and DATA_UNAVAILABLE / SUSPENDED may recover once fresh verified state arrives.
ALLOWED_TRANSITIONS: dict[TokenLifecycleState, set[TokenLifecycleState]] = {
    TokenLifecycleState.DISCOVERED: {
        TokenLifecycleState.CURVE_ACTIVE,
        TokenLifecycleState.MIGRATION_PENDING,
        TokenLifecycleState.PUMPSWAP_ACTIVE,
        TokenLifecycleState.UNSUPPORTED,
        TokenLifecycleState.SUSPENDED,
        TokenLifecycleState.DATA_UNAVAILABLE,
        TokenLifecycleState.RISK_REJECTED,
    },
    TokenLifecycleState.CURVE_ACTIVE: {
        TokenLifecycleState.MIGRATION_PENDING,
        TokenLifecycleState.PUMPSWAP_ACTIVE,
        TokenLifecycleState.SUSPENDED,
        TokenLifecycleState.DATA_UNAVAILABLE,
        TokenLifecycleState.RISK_REJECTED,
        TokenLifecycleState.UNSUPPORTED,
    },
    TokenLifecycleState.MIGRATION_PENDING: {
        TokenLifecycleState.PUMPSWAP_ACTIVE,
        TokenLifecycleState.SUSPENDED,
        TokenLifecycleState.DATA_UNAVAILABLE,
        TokenLifecycleState.RISK_REJECTED,
    },
    TokenLifecycleState.PUMPSWAP_ACTIVE: {
        TokenLifecycleState.SUSPENDED,
        TokenLifecycleState.DATA_UNAVAILABLE,
        TokenLifecycleState.RISK_REJECTED,
    },
    TokenLifecycleState.DATA_UNAVAILABLE: {
        TokenLifecycleState.DISCOVERED,
        TokenLifecycleState.CURVE_ACTIVE,
        TokenLifecycleState.MIGRATION_PENDING,
        TokenLifecycleState.PUMPSWAP_ACTIVE,
        TokenLifecycleState.RISK_REJECTED,
        TokenLifecycleState.UNSUPPORTED,
    },
    TokenLifecycleState.SUSPENDED: {
        TokenLifecycleState.CURVE_ACTIVE,
        TokenLifecycleState.PUMPSWAP_ACTIVE,
        TokenLifecycleState.RISK_REJECTED,
    },
    TokenLifecycleState.UNSUPPORTED: set(),
    TokenLifecycleState.RISK_REJECTED: set(),
}


@dataclass(frozen=True)
class LifecycleTransition:
    from_state: str
    to_state: str
    slot: int
    event_time: float
    reason: str
    venue_before: str
    venue_after: str


@dataclass
class PumpTokenRecord:
    """Authoritative point-in-time record for one Pump.fun / PumpSwap token keyed by `mint`."""
    mint: str
    symbol: str
    name: str
    creation_tx: str
    creation_slot: int
    creation_timestamp: float
    creator_wallet: str
    quote_mint: str = WSOL_MINT
    quote_symbol: str = "SOL"
    quote_decimals: int = 9
    quote_depth: int = 1
    decimals: int = DEFAULT_TOKEN_DECIMALS
    token_program: str = SPL_TOKEN_PROGRAM_ID
    token_extensions: tuple[str, ...] = ()
    mint_authority_active: bool = False
    freeze_authority_active: bool = False
    bonding_curve_address: str = ""
    pumpswap_pool_address: str | None = None
    lifecycle_state: TokenLifecycleState = TokenLifecycleState.DISCOVERED
    graduation_state: str = "on_curve"  # on_curve | migrating | graduated | unsupported
    active_venue: str = "bonding_curve"  # bonding_curve | synthetic_migration | pumpswap | none
    price_quote: float = 0.0
    price_usd: float | None = None
    market_cap_quote: float = 0.0
    volume_24h_quote: float = 0.0
    trade_count_24h: int = 0
    unique_buyers_24h: int = 0
    unique_sellers_24h: int = 0
    liquidity_quote: float = 0.0
    curve_progress_pct: float = 0.0
    creator_holding_pct: float = 0.0
    top1_holder_pct: float = 0.0
    top10_holder_pct: float = 0.0
    holder_count: int = 0
    data_provenance: str = "live"  # live | historical | simulated | unavailable
    last_slot: int = 0
    last_updated_ts: float = 0.0
    uri: str = ""
    transitions: list[LifecycleTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert_mint_identifier(self.mint)

    def is_tradable(self) -> bool:
        return self.lifecycle_state in (
            TokenLifecycleState.CURVE_ACTIVE,
            TokenLifecycleState.MIGRATION_PENDING,
            TokenLifecycleState.PUMPSWAP_ACTIVE,
        )

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lifecycle_state"] = self.lifecycle_state.value
        d["tradable"] = self.is_tradable()
        return d


def transition_lifecycle(
    token: PumpTokenRecord,
    new_state: TokenLifecycleState,
    *,
    slot: int,
    event_time: float,
    reason: str,
) -> PumpTokenRecord:
    """Apply a validated causal state-machine transition to ``token``."""
    if slot < token.last_slot and token.lifecycle_state != TokenLifecycleState.DATA_UNAVAILABLE:
        raise ValueError(
            f"Non-causal lifecycle transition on {token.mint}: slot {slot} < last_slot {token.last_slot}"
        )
    current = token.lifecycle_state
    if current == new_state:
        token.last_slot = max(token.last_slot, int(slot))
        token.last_updated_ts = max(token.last_updated_ts, float(event_time))
        return token
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_state not in allowed:
        raise ValueError(
            f"Illegal lifecycle transition for {token.mint}: {current.value} -> {new_state.value} ({reason})"
        )
    venue_before = token.active_venue
    if new_state == TokenLifecycleState.CURVE_ACTIVE:
        token.active_venue = "bonding_curve"
        token.graduation_state = "on_curve"
    elif new_state == TokenLifecycleState.MIGRATION_PENDING:
        token.active_venue = "synthetic_migration"
        token.graduation_state = "migrating"
    elif new_state == TokenLifecycleState.PUMPSWAP_ACTIVE:
        token.active_venue = "pumpswap"
        token.graduation_state = "graduated"
    elif new_state in (
        TokenLifecycleState.UNSUPPORTED,
        TokenLifecycleState.SUSPENDED,
        TokenLifecycleState.DATA_UNAVAILABLE,
        TokenLifecycleState.RISK_REJECTED,
    ):
        token.active_venue = "none"
        if new_state == TokenLifecycleState.UNSUPPORTED:
            token.graduation_state = "unsupported"

    token.lifecycle_state = new_state
    token.last_slot = max(token.last_slot, int(slot))
    token.last_updated_ts = max(token.last_updated_ts, float(event_time))
    token.transitions.append(
        LifecycleTransition(
            from_state=current.value,
            to_state=new_state.value,
            slot=int(slot),
            event_time=float(event_time),
            reason=reason,
            venue_before=venue_before,
            venue_after=token.active_venue,
        )
    )
    return token

