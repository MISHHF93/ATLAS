"""Pump.fun token launch discovery service.

Discovers token launches from authorized on-chain instructions (`create`, `create_v2`)
and read-only Pump.fun developer metadata. Enforces mint-address primary identity and
validates quote-mint hierarchy depth (`MAX_QUOTE_DEPTH`) and token programs.
"""
from __future__ import annotations

from typing import Any

from ..bonding_curve import BondingCurveState
from ..pumpswap import PumpSwapPoolState
from ..tokens import (
    CANONICAL_QUOTE_MINTS,
    DEFAULT_TOKEN_DECIMALS,
    MAX_QUOTE_DEPTH,
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    PumpTokenRecord,
    TokenLifecycleState,
    assert_mint_identifier,
    is_valid_pubkey,
    transition_lifecycle,
)

SUPPORTED_TOKEN_PROGRAMS = {SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}


class PumpTokenDiscoveryService:
    """Registry and discovery index of Pump.fun / PumpSwap tokens keyed strictly by `mint`."""

    def __init__(self) -> None:
        self._tokens: dict[str, PumpTokenRecord] = {}
        self._curves: dict[str, BondingCurveState] = {}
        self._pools: dict[str, PumpSwapPoolState] = {}

    def discover_launch(
        self,
        *,
        mint: str,
        symbol: str,
        name: str,
        creation_tx: str,
        creation_slot: int,
        creation_timestamp: float,
        creator_wallet: str,
        bonding_curve_address: str,
        quote_mint: str = "So11111111111111111111111111111111111111112",
        decimals: int = DEFAULT_TOKEN_DECIMALS,
        token_program: str = SPL_TOKEN_PROGRAM_ID,
        token_extensions: tuple[str, ...] = (),
        mint_authority_active: bool = False,
        freeze_authority_active: bool = False,
        data_provenance: str = "live",
        uri: str = "",
    ) -> PumpTokenRecord:
        """Register a newly discovered Pump.fun token launch by its mint address."""
        assert_mint_identifier(mint)
        if not is_valid_pubkey(creator_wallet):
            raise ValueError(f"Invalid creator_wallet pubkey: {creator_wallet!r}")

        # Resolve quote mint hierarchy depth (create_v2 allows Pump coins as quote mints up to MAX_QUOTE_DEPTH)
        if quote_mint in CANONICAL_QUOTE_MINTS:
            q_sym = str(CANONICAL_QUOTE_MINTS[quote_mint]["symbol"])
            q_dec = int(CANONICAL_QUOTE_MINTS[quote_mint]["decimals"])
            q_depth = 1
            quote_supported = True
        elif quote_mint in self._tokens:
            parent = self._tokens[quote_mint]
            q_sym = parent.symbol
            q_dec = parent.decimals
            q_depth = parent.quote_depth + 1
            quote_supported = q_depth <= MAX_QUOTE_DEPTH and parent.is_tradable()
        else:
            q_sym = "UNKNOWN"
            q_dec = 6
            q_depth = MAX_QUOTE_DEPTH + 1
            quote_supported = False

        rec = PumpTokenRecord(
            mint=mint,
            symbol=symbol.strip(),
            name=name.strip(),
            creation_tx=creation_tx,
            creation_slot=int(creation_slot),
            creation_timestamp=float(creation_timestamp),
            creator_wallet=creator_wallet,
            quote_mint=quote_mint,
            quote_symbol=q_sym,
            quote_decimals=q_dec,
            quote_depth=q_depth,
            decimals=int(decimals),
            token_program=token_program,
            token_extensions=tuple(token_extensions),
            mint_authority_active=bool(mint_authority_active),
            freeze_authority_active=bool(freeze_authority_active),
            bonding_curve_address=bonding_curve_address,
            data_provenance=data_provenance,
            last_slot=int(creation_slot),
            last_updated_ts=float(creation_timestamp),
            uri=uri,
        )

        if token_program not in SUPPORTED_TOKEN_PROGRAMS or not quote_supported:
            transition_lifecycle(
                rec,
                TokenLifecycleState.UNSUPPORTED,
                slot=creation_slot,
                event_time=creation_timestamp,
                reason=f"Unsupported token_program={token_program} or quote_mint={quote_mint} (depth={q_depth})",
            )

        self._tokens[mint] = rec
        return rec

    def get_by_mint(self, mint: str) -> PumpTokenRecord:
        """Retrieve a token strictly by its base58 mint address."""
        assert_mint_identifier(mint)
        if mint not in self._tokens:
            raise KeyError(f"Unknown Pump.fun mint: {mint}")
        return self._tokens[mint]

    def search(self, query: str = "", *, lifecycle: str | None = None) -> list[PumpTokenRecord]:
        """Search discovered tokens. Exact mint match takes priority; symbol matches return all colliding mints."""
        q = (query or "").strip()
        if is_valid_pubkey(q) and q in self._tokens:
            tok = self._tokens[q]
            if lifecycle and tok.lifecycle_state.value != lifecycle:
                return []
            return [tok]
        ql = q.lower()
        out = []
        for tok in self._tokens.values():
            if lifecycle and tok.lifecycle_state.value != lifecycle:
                continue
            if not ql or ql in tok.mint.lower() or ql in tok.symbol.lower() or ql in tok.name.lower():
                out.append(tok)
        out.sort(key=lambda t: (t.last_updated_ts, t.creation_slot), reverse=True)
        return out

    def attach_curve_state(self, curve: BondingCurveState) -> None:
        self._curves[curve.mint] = curve

    def attach_pool_state(self, pool: PumpSwapPoolState) -> None:
        self._pools[pool.base_mint] = pool

    def curve_for(self, mint: str) -> BondingCurveState | None:
        return self._curves.get(mint)

    def pool_for(self, mint: str) -> PumpSwapPoolState | None:
        return self._pools.get(mint)

    def all_tokens(self) -> list[PumpTokenRecord]:
        return list(self._tokens.values())

    def find_symbol_collisions(self, symbol: str) -> list[PumpTokenRecord]:
        """Return all discovered tokens sharing a ticker symbol (proving mint-address disambiguation)."""
        sym_u = symbol.strip().upper()
        return [t for t in self._tokens.values() if t.symbol.upper() == sym_u]

    def snapshot_for_mint(self, mint: str) -> dict[str, Any]:
        tok = self.get_by_mint(mint)
        c = self._curves.get(mint)
        p = self._pools.get(mint)
        return {
            "token": tok.as_dict(),
            "bonding_curve": c.as_dict() if c else None,
            "pumpswap_pool": p.as_dict() if p else None,
        }

