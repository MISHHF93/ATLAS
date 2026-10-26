"""Token graduation, synthetic migration, and venue transition tracker."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..bonding_curve import BondingCurveState
from ..pumpswap import PumpSwapPoolState
from ..tokens import PumpTokenRecord, TokenLifecycleState, transition_lifecycle


@dataclass(frozen=True)
class MigrationEvent:
    mint: str
    slot: int
    event_time: float
    tx_signature: str
    bonding_curve_address: str
    pumpswap_pool_address: str | None
    migration_kind: str  # "curve_complete" | "synthetic_migration_buy" | "canonical_pool_seeded"
    synthetic_tokens_bought_raw: int = 0
    seeded_quote_amount_raw: int = 0
    seeded_base_amount_raw: int = 0
    lp_burned: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MigrationTracker:
    """Tracks token graduation from Pump.fun bonding curves to canonical PumpSwap pools."""

    def __init__(self) -> None:
        self._events_by_mint: dict[str, list[MigrationEvent]] = {}

    def on_curve_update(self, token: PumpTokenRecord, curve: BondingCurveState, tx_signature: str = "") -> PumpTokenRecord:
        token.curve_progress_pct = curve.progress_pct
        token.price_quote = curve.price_quote_per_token
        token.market_cap_quote = curve.market_cap_quote
        token.liquidity_quote = (curve.effective_virtual_quote_reserves / (10**curve.quote_decimals))
        if curve.complete or curve.real_token_reserves == 0:
            if token.lifecycle_state in (TokenLifecycleState.DISCOVERED, TokenLifecycleState.CURVE_ACTIVE):
                transition_lifecycle(
                    token,
                    TokenLifecycleState.MIGRATION_PENDING,
                    slot=curve.slot,
                    event_time=curve.event_time,
                    reason="Bonding curve exhausted (CompleteEvent); awaiting or executing PumpSwap migration",
                )
                self._record(
                    MigrationEvent(
                        mint=token.mint,
                        slot=curve.slot,
                        event_time=curve.event_time,
                        tx_signature=tx_signature,
                        bonding_curve_address=curve.bonding_curve_address,
                        pumpswap_pool_address=token.pumpswap_pool_address,
                        migration_kind="curve_complete",
                    )
                )
        elif token.lifecycle_state == TokenLifecycleState.DISCOVERED:
            transition_lifecycle(
                token,
                TokenLifecycleState.CURVE_ACTIVE,
                slot=curve.slot,
                event_time=curve.event_time,
                reason="Bonding curve active with non-zero reserves",
            )
        return token

    def on_synthetic_migration_buy(
        self,
        token: PumpTokenRecord,
        *,
        slot: int,
        event_time: float,
        tx_signature: str,
        synthetic_tokens_bought_raw: int,
    ) -> PumpTokenRecord:
        if token.lifecycle_state in (TokenLifecycleState.DISCOVERED, TokenLifecycleState.CURVE_ACTIVE):
            transition_lifecycle(
                token,
                TokenLifecycleState.MIGRATION_PENDING,
                slot=slot,
                event_time=event_time,
                reason="Last curve buy overflowed into synthetic migration (PostCompleteBuyEvent)",
            )
        self._record(
            MigrationEvent(
                mint=token.mint,
                slot=slot,
                event_time=event_time,
                tx_signature=tx_signature,
                bonding_curve_address=token.bonding_curve_address,
                pumpswap_pool_address=token.pumpswap_pool_address,
                migration_kind="synthetic_migration_buy",
                synthetic_tokens_bought_raw=int(synthetic_tokens_bought_raw),
            )
        )
        return token

    def on_pumpswap_pool_active(
        self,
        token: PumpTokenRecord,
        pool: PumpSwapPoolState,
        tx_signature: str = "",
    ) -> PumpTokenRecord:
        token.pumpswap_pool_address = pool.pool_address
        token.price_quote = pool.price_quote_per_token
        token.liquidity_quote = pool.liquidity_quote
        token.curve_progress_pct = 100.0
        if token.lifecycle_state in (
            TokenLifecycleState.DISCOVERED,
            TokenLifecycleState.CURVE_ACTIVE,
            TokenLifecycleState.MIGRATION_PENDING,
        ):
            transition_lifecycle(
                token,
                TokenLifecycleState.PUMPSWAP_ACTIVE,
                slot=pool.slot,
                event_time=pool.event_time,
                reason=f"Graduated to canonical PumpSwap pool {pool.pool_address} (lp_burned={pool.lp_burned})",
            )
            self._record(
                MigrationEvent(
                    mint=token.mint,
                    slot=pool.slot,
                    event_time=pool.event_time,
                    tx_signature=tx_signature,
                    bonding_curve_address=token.bonding_curve_address,
                    pumpswap_pool_address=pool.pool_address,
                    migration_kind="canonical_pool_seeded",
                    seeded_quote_amount_raw=pool.effective_quote_reserves,
                    seeded_base_amount_raw=pool.effective_base_reserves,
                    lp_burned=pool.lp_burned,
                )
            )
        return token

    def _record(self, ev: MigrationEvent) -> None:
        self._events_by_mint.setdefault(ev.mint, []).append(ev)

    def events_for(self, mint: str) -> list[dict[str, Any]]:
        return [e.as_dict() for e in self._events_by_mint.get(mint, ())]

    def all_events(self) -> list[dict[str, Any]]:
        out = [e for evs in self._events_by_mint.values() for e in evs]
        out.sort(key=lambda e: (e.slot, e.event_time))
        return [e.as_dict() for e in out]

