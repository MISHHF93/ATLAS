"""PumpSwap AMM (`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`) pool state, signed virtual quote reserves, and multi-hop routing."""
from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..bonding_curve import BondingCurveState, quote_curve_buy_exact_quote_in, quote_curve_sell
from ..tokens import DEFAULT_TOKEN_DECIMALS, PUMPSWAP_PROGRAM_ID, WSOL_MINT

DEFAULT_PUMPSWAP_LP_FEE_BPS = 20
DEFAULT_PUMPSWAP_PROTOCOL_FEE_BPS = 5
DEFAULT_PUMPSWAP_CREATOR_FEE_BPS = 5
PUMPSWAP_POOL_DISCRIMINATOR = bytes([241, 154, 109, 4, 17, 177, 109, 188])


@dataclass
class PumpSwapPoolState:
    """Decoded PumpSwap pool state supporting signed `virtual_quote_reserves` (`i128`).

    Per official October 2026 PumpSwap protocol rules:
    protocol and creator fees remain in the pool quote vault until swept via
    `sweep_protocol_fee` / `sweep_creator_fee`, so `virtual_quote_reserves` can be
    NEGATIVE (`< 0`) to offset unswept fees.
    Effective quote reserves = `quote_vault_amount + virtual_quote_reserves`.
    """
    pool_address: str
    base_mint: str
    quote_mint: str = WSOL_MINT
    lp_mint: str = ""
    pool_base_token_account: str = ""
    pool_quote_token_account: str = ""
    base_vault_amount: int = 0
    quote_vault_amount: int = 0
    virtual_quote_reserves: int = 0  # Signed integer (can be negative!)
    base_decimals: int = DEFAULT_TOKEN_DECIMALS
    quote_decimals: int = 9
    lp_fee_bps: int = DEFAULT_PUMPSWAP_LP_FEE_BPS
    protocol_fee_bps: int = DEFAULT_PUMPSWAP_PROTOCOL_FEE_BPS
    coin_creator_fee_bps: int = DEFAULT_PUMPSWAP_CREATOR_FEE_BPS
    lp_burned: bool = True
    creator: str = ""
    slot: int = 0
    event_time: float = 0.0

    @property
    def total_fee_bps(self) -> int:
        return int(self.lp_fee_bps) + int(self.protocol_fee_bps) + int(self.coin_creator_fee_bps)

    @property
    def effective_quote_reserves(self) -> int:
        """`pool_quote_token_account.amount + Pool::virtual_quote_reserves` (clamped at 0)."""
        return max(0, int(self.quote_vault_amount) + int(self.virtual_quote_reserves))

    @property
    def effective_base_reserves(self) -> int:
        return max(0, int(self.base_vault_amount))

    @property
    def price_quote_per_token(self) -> float:
        if self.effective_base_reserves <= 0 or self.effective_quote_reserves <= 0:
            return 0.0
        q_whole = self.effective_quote_reserves / (10**self.quote_decimals)
        b_whole = self.effective_base_reserves / (10**self.base_decimals)
        return q_whole / b_whole if b_whole > 0 else 0.0

    @property
    def liquidity_quote(self) -> float:
        return (self.effective_quote_reserves / (10**self.quote_decimals)) * 2.0

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "effective_quote_reserves": self.effective_quote_reserves,
            "effective_base_reserves": self.effective_base_reserves,
            "price_quote_per_token": self.price_quote_per_token,
            "liquidity_quote": self.liquidity_quote,
            "program_id": PUMPSWAP_PROGRAM_ID,
        }


def encode_pumpswap_pool_account(
    base_vault_amount: int,
    quote_vault_amount: int,
    virtual_quote_reserves: int,
    *,
    lp_fee_bps: int = DEFAULT_PUMPSWAP_LP_FEE_BPS,
    protocol_fee_bps: int = DEFAULT_PUMPSWAP_PROTOCOL_FEE_BPS,
    coin_creator_fee_bps: int = DEFAULT_PUMPSWAP_CREATOR_FEE_BPS,
    lp_burned: bool = True,
) -> bytes:
    """Encode a PumpSwap Pool binary fixture with signed `virtual_quote_reserves`."""
    return struct.pack(
        "<8sQQqHHH?",
        PUMPSWAP_POOL_DISCRIMINATOR,
        int(base_vault_amount),
        int(quote_vault_amount),
        int(virtual_quote_reserves),
        int(lp_fee_bps),
        int(protocol_fee_bps),
        int(coin_creator_fee_bps),
        bool(lp_burned),
    )


def decode_pumpswap_pool_account(
    data: bytes | dict[str, Any],
    *,
    pool_address: str,
    base_mint: str,
    quote_mint: str = WSOL_MINT,
    slot: int = 0,
    event_time: float = 0.0,
) -> PumpSwapPoolState:
    """Decode a PumpSwap Pool account from raw bytes or structured RPC dict."""
    if isinstance(data, dict):
        return PumpSwapPoolState(
            pool_address=pool_address,
            base_mint=base_mint,
            quote_mint=str(data.get("quote_mint", quote_mint)),
            lp_mint=str(data.get("lp_mint", "")),
            pool_base_token_account=str(data.get("pool_base_token_account", "")),
            pool_quote_token_account=str(data.get("pool_quote_token_account", "")),
            base_vault_amount=int(data["base_vault_amount"]),
            quote_vault_amount=int(data["quote_vault_amount"]),
            virtual_quote_reserves=int(data.get("virtual_quote_reserves", 0)),
            base_decimals=int(data.get("base_decimals", DEFAULT_TOKEN_DECIMALS)),
            quote_decimals=int(data.get("quote_decimals", 9)),
            lp_fee_bps=int(data.get("lp_fee_bps", DEFAULT_PUMPSWAP_LP_FEE_BPS)),
            protocol_fee_bps=int(data.get("protocol_fee_bps", DEFAULT_PUMPSWAP_PROTOCOL_FEE_BPS)),
            coin_creator_fee_bps=int(data.get("coin_creator_fee_bps", DEFAULT_PUMPSWAP_CREATOR_FEE_BPS)),
            lp_burned=bool(data.get("lp_burned", True)),
            creator=str(data.get("creator", "")),
            slot=int(data.get("slot", slot)),
            event_time=float(data.get("event_time", event_time)),
        )
    if len(data) < 39:
        raise ValueError(f"PumpSwap Pool account data too short: {len(data)} bytes")
    disc, base_amt, quote_amt, signed_vq, lp_bps, proto_bps, creator_bps, burned = struct.unpack("<8sQQqHHH?", data[:39])
    if disc != PUMPSWAP_POOL_DISCRIMINATOR:
        raise ValueError("Invalid PumpSwap Pool discriminator")
    return PumpSwapPoolState(
        pool_address=pool_address,
        base_mint=base_mint,
        quote_mint=quote_mint,
        base_vault_amount=base_amt,
        quote_vault_amount=quote_amt,
        virtual_quote_reserves=signed_vq,
        lp_fee_bps=lp_bps,
        protocol_fee_bps=proto_bps,
        coin_creator_fee_bps=creator_bps,
        lp_burned=burned,
        slot=slot,
        event_time=event_time,
    )


@dataclass(frozen=True)
class PumpSwapQuote:
    pool_address: str
    base_mint: str
    quote_mint: str
    side: str  # "buy" (quote -> base) | "sell" (base -> quote)
    amount_in_raw: int
    amount_out_raw: int
    lp_fee_raw: int
    protocol_fee_raw: int
    creator_fee_raw: int
    total_fee_raw: int
    spot_price_before: float
    execution_price: float
    spot_price_after: float
    price_impact_bps: float
    effective_quote_reserves_used: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def quote_pumpswap(pool: PumpSwapPoolState, side: str, amount_in_raw: int) -> PumpSwapQuote:
    """Quote a buy (`quote -> base`) or sell (`base -> quote`) on a PumpSwap pool using effective reserves."""
    if amount_in_raw <= 0:
        raise ValueError("amount_in_raw must be positive")
    eff_q = pool.effective_quote_reserves
    eff_b = pool.effective_base_reserves
    if eff_q <= 0 or eff_b <= 0:
        raise ValueError(f"PumpSwap pool {pool.pool_address} has non-positive effective reserves")

    spot_before = pool.price_quote_per_token
    if side == "buy":
        lp_fee = (amount_in_raw * pool.lp_fee_bps) // 10_000
        proto_fee = (amount_in_raw * pool.protocol_fee_bps) // 10_000
        creator_fee = (amount_in_raw * pool.coin_creator_fee_bps) // 10_000
        total_fee = lp_fee + proto_fee + creator_fee
        net_in = max(0, amount_in_raw - total_fee)
        out_raw = (eff_b * net_in) // (eff_q + net_in)
        new_q = eff_q + net_in - lp_fee  # LP fee stays in pool, protocol/creator fees offset by virtual_quote_reserves
        new_b = max(1, eff_b - out_raw)
        spot_after = (new_q / (10**pool.quote_decimals)) / (new_b / (10**pool.base_decimals))
        q_whole = amount_in_raw / (10**pool.quote_decimals)
        b_whole = out_raw / (10**pool.base_decimals) if out_raw > 0 else 0.0
        exec_px = (q_whole / b_whole) if b_whole > 0 else spot_after
        impact_bps = max(0.0, ((exec_px / spot_before) - 1.0) * 10_000.0) if spot_before > 0 else 0.0
    elif side == "sell":
        gross_q_out = (eff_q * amount_in_raw) // (eff_b + amount_in_raw)
        lp_fee = (gross_q_out * pool.lp_fee_bps) // 10_000
        proto_fee = (gross_q_out * pool.protocol_fee_bps) // 10_000
        creator_fee = (gross_q_out * pool.coin_creator_fee_bps) // 10_000
        total_fee = lp_fee + proto_fee + creator_fee
        out_raw = max(0, gross_q_out - total_fee)
        new_b = eff_b + amount_in_raw
        new_q = max(1, eff_q - gross_q_out + lp_fee)
        spot_after = (new_q / (10**pool.quote_decimals)) / (new_b / (10**pool.base_decimals))
        q_whole = out_raw / (10**pool.quote_decimals)
        b_whole = amount_in_raw / (10**pool.base_decimals)
        exec_px = (q_whole / b_whole) if b_whole > 0 else 0.0
        impact_bps = max(0.0, (1.0 - (exec_px / spot_before)) * 10_000.0) if spot_before > 0 else 0.0
    else:
        raise ValueError(f"Unsupported side {side!r}; expected 'buy' or 'sell'")

    return PumpSwapQuote(
        pool_address=pool.pool_address,
        base_mint=pool.base_mint,
        quote_mint=pool.quote_mint,
        side=side,
        amount_in_raw=int(amount_in_raw),
        amount_out_raw=int(out_raw),
        lp_fee_raw=int(lp_fee),
        protocol_fee_raw=int(proto_fee),
        creator_fee_raw=int(creator_fee),
        total_fee_raw=int(total_fee),
        spot_price_before=spot_before,
        execution_price=exec_px,
        spot_price_after=spot_after,
        price_impact_bps=round(impact_bps, 2),
        effective_quote_reserves_used=eff_q,
    )


@dataclass(frozen=True)
class MultiHopQuote:
    instruction: str
    path_mints: tuple[str, ...]
    venues: tuple[str, ...]
    amount_in_raw: int
    final_amount_out_raw: int
    combined_price_impact_bps: float
    hops: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def quote_multi_hop(
    legs: Sequence[ tuple[str, BondingCurveState | PumpSwapPoolState, str] ],
    initial_amount_in_raw: int,
) -> MultiHopQuote:
    """Quote a `multi_hop_swap` across sequential bonding curves and/or PumpSwap pools."""
    if not legs:
        raise ValueError("multi_hop_swap requires at least 1 leg")
    amt = int(initial_amount_in_raw)
    hops: list[dict[str, Any]] = []
    venues: list[str] = []
    path: list[str] = []
    compounded_factor = 1.0

    for idx, (venue_kind, state, side) in enumerate(legs):
        if isinstance(state, BondingCurveState):
            if idx == 0:
                path.append(state.quote_mint if side == "buy" else state.mint)
            path.append(state.mint if side == "buy" else state.quote_mint)
            q = quote_curve_buy_exact_quote_in(state, amt) if side == "buy" else quote_curve_sell(state, amt)
            amt = q.tokens_out_raw if side == "buy" else q.quote_out_raw
            compounded_factor *= 1.0 + (q.price_impact_bps / 10_000.0)
            venues.append(f"bonding_curve:{state.bonding_curve_address}")
            hops.append(q.as_dict())
        elif isinstance(state, PumpSwapPoolState):
            if idx == 0:
                path.append(state.quote_mint if side == "buy" else state.base_mint)
            path.append(state.base_mint if side == "buy" else state.quote_mint)
            q2 = quote_pumpswap(state, side, amt)
            amt = q2.amount_out_raw
            compounded_factor *= 1.0 + (q2.price_impact_bps / 10_000.0)
            venues.append(f"pumpswap:{state.pool_address}")
            hops.append(q2.as_dict())
        else:
            raise TypeError(f"Unsupported leg state type {type(state)!r} in multi_hop_swap")

    total_impact_bps = round((compounded_factor - 1.0) * 10_000.0, 2)
    return MultiHopQuote(
        instruction="multi_hop_swap",
        path_mints=tuple(path),
        venues=tuple(venues),
        amount_in_raw=int(initial_amount_in_raw),
        final_amount_out_raw=int(amt),
        combined_price_impact_bps=total_impact_bps,
        hops=tuple(hops),
    )

