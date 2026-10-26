"""Pump.fun Bonding-Curve state decoding, signed virtual reserves, v3 trade math, and synthetic migration."""
from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from typing import Any

from ..tokens import DEFAULT_TOKEN_DECIMALS, LAMPORTS_PER_SOL, PUMP_PROGRAM_ID, WSOL_MINT

# Standard Pump.fun initial curve parameters (6-decimal token, 9-decimal SOL/quote)
INITIAL_VIRTUAL_TOKEN_RESERVES = 1_073_000_000 * (10**DEFAULT_TOKEN_DECIMALS)
INITIAL_VIRTUAL_SOL_RESERVES = 30 * LAMPORTS_PER_SOL
INITIAL_REAL_TOKEN_RESERVES = 793_100_000 * (10**DEFAULT_TOKEN_DECIMALS)
TOKEN_TOTAL_SUPPLY = 1_000_000_000 * (10**DEFAULT_TOKEN_DECIMALS)

# Default fee schedule on the bonding curve (in basis points): 95 bps protocol + 30 bps creator = 125 bps (1.25%)
DEFAULT_CURVE_PROTOCOL_FEE_BPS = 95
DEFAULT_CURVE_CREATOR_FEE_BPS = 30
BONDING_CURVE_DISCRIMINATOR = bytes([23, 183, 248, 55, 96, 216, 172, 96])


@dataclass
class BondingCurveState:
    """Decoded on-chain Pump.fun bonding-curve state (supports v3 unswept fees & signed virtual quote adjustments)."""
    mint: str
    bonding_curve_address: str
    virtual_token_reserves: int
    virtual_quote_reserves: int  # May include signed offset from unswept fees
    real_token_reserves: int
    real_quote_reserves: int
    token_total_supply: int = TOKEN_TOTAL_SUPPLY
    complete: bool = False
    creator: str = ""
    quote_mint: str = WSOL_MINT
    quote_decimals: int = 9
    token_decimals: int = DEFAULT_TOKEN_DECIMALS
    unswept_protocol_fees: int = 0
    unswept_creator_fees: int = 0
    signed_virtual_quote_adjustment: int = 0  # Signed i128 adjustment (can be negative when fees sit on curve)
    protocol_fee_bps: int = DEFAULT_CURVE_PROTOCOL_FEE_BPS
    creator_fee_bps: int = DEFAULT_CURVE_CREATOR_FEE_BPS
    slot: int = 0
    event_time: float = 0.0

    @property
    def total_fee_bps(self) -> int:
        return int(self.protocol_fee_bps) + int(self.creator_fee_bps)

    @property
    def effective_virtual_quote_reserves(self) -> int:
        """Active virtual quote reserves after applying signed virtual reserve offset and deducting unswept fees."""
        eff = int(self.virtual_quote_reserves) + int(self.signed_virtual_quote_reserves_offset)
        return max(0, eff)

    @property
    def signed_virtual_quote_reserves_offset(self) -> int:
        """Signed offset: explicit signed adjustment minus unswept fees still sitting in the curve account."""
        return int(self.signed_virtual_quote_adjustment) - int(self.unswept_protocol_fees) - int(self.unswept_creator_fees)

    @property
    def price_quote_per_token(self) -> float:
        """Instantaneous spot price in quote units (e.g. SOL) per 1 whole token."""
        if self.virtual_token_reserves <= 0 or self.effective_virtual_quote_reserves <= 0:
            return 0.0
        quote_whole = self.effective_virtual_quote_reserves / (10**self.quote_decimals)
        token_whole = self.virtual_token_reserves / (10**self.token_decimals)
        return quote_whole / token_whole if token_whole > 0 else 0.0

    @property
    def market_cap_quote(self) -> float:
        supply_whole = self.token_total_supply / (10**self.token_decimals)
        return self.price_quote_per_token * supply_whole

    @property
    def progress_pct(self) -> float:
        """Bonding curve completion percentage [0.0 .. 100.0] based on real_token_reserves consumed."""
        if self.complete or self.real_token_reserves <= 0:
            return 100.0
        sold = max(0, INITIAL_REAL_TOKEN_RESERVES - int(self.real_token_reserves))
        return min(100.0, round((sold / INITIAL_REAL_TOKEN_RESERVES) * 100.0, 4))

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "effective_virtual_quote_reserves": self.effective_virtual_quote_reserves,
            "signed_virtual_quote_reserves_offset": self.signed_virtual_quote_reserves_offset,
            "price_quote_per_token": self.price_quote_per_token,
            "market_cap_quote": self.market_cap_quote,
            "progress_pct": self.progress_pct,
            "program_id": PUMP_PROGRAM_ID,
        }


def encode_bonding_curve_account(
    virtual_token_reserves: int,
    virtual_quote_reserves: int,
    real_token_reserves: int,
    real_quote_reserves: int,
    token_total_supply: int = TOKEN_TOTAL_SUPPLY,
    complete: bool = False,
    unswept_protocol_fees: int = 0,
    unswept_creator_fees: int = 0,
    signed_virtual_quote_adjustment: int = 0,
) -> bytes:
    """Encode a Pump.fun BondingCurve account binary payload for deterministic decoding tests."""
    header = struct.pack(
        "<8sQQQQQ?",
        BONDING_CURVE_DISCRIMINATOR,
        int(virtual_token_reserves),
        int(virtual_quote_reserves),
        int(real_token_reserves),
        int(real_quote_reserves),
        int(token_total_supply),
        bool(complete),
    )
    # v3 extension trailer: unswept_protocol_fees (u64), unswept_creator_fees (u64), signed_adjustment (i64)
    trailer = struct.pack("<QQq", int(unswept_protocol_fees), int(unswept_creator_fees), int(signed_virtual_quote_adjustment))
    return header + trailer


def decode_bonding_curve_account(
    data: bytes | dict[str, Any],
    *,
    mint: str,
    bonding_curve_address: str,
    creator: str = "",
    slot: int = 0,
    event_time: float = 0.0,
) -> BondingCurveState:
    """Decode a Pump.fun bonding-curve account from raw bytes or structured RPC dict."""
    if isinstance(data, dict):
        return BondingCurveState(
            mint=mint,
            bonding_curve_address=bonding_curve_address,
            virtual_token_reserves=int(data["virtual_token_reserves"]),
            virtual_quote_reserves=int(data.get("virtual_quote_reserves", data.get("virtual_sol_reserves", 0))),
            real_token_reserves=int(data["real_token_reserves"]),
            real_quote_reserves=int(data.get("real_quote_reserves", data.get("real_sol_reserves", 0))),
            token_total_supply=int(data.get("token_total_supply", TOKEN_TOTAL_SUPPLY)),
            complete=bool(data.get("complete", False)),
            creator=str(data.get("creator", creator)),
            quote_mint=str(data.get("quote_mint", WSOL_MINT)),
            quote_decimals=int(data.get("quote_decimals", 9)),
            token_decimals=int(data.get("token_decimals", DEFAULT_TOKEN_DECIMALS)),
            unswept_protocol_fees=int(data.get("unswept_protocol_fees", 0)),
            unswept_creator_fees=int(data.get("unswept_creator_fees", 0)),
            signed_virtual_quote_adjustment=int(data.get("signed_virtual_quote_adjustment", 0)),
            protocol_fee_bps=int(data.get("protocol_fee_bps", DEFAULT_CURVE_PROTOCOL_FEE_BPS)),
            creator_fee_bps=int(data.get("creator_fee_bps", DEFAULT_CURVE_CREATOR_FEE_BPS)),
            slot=int(data.get("slot", slot)),
            event_time=float(data.get("event_time", event_time)),
        )
    if len(data) < 49:
        raise ValueError(f"BondingCurve account data too short: {len(data)} bytes")
    disc, vt, vq, rt, rq, supply, comp = struct.unpack("<8sQQQQQ?", data[:49])
    if disc != BONDING_CURVE_DISCRIMINATOR:
        raise ValueError("Invalid BondingCurve account discriminator")
    proto_fees, creator_fees, signed_adj = (0, 0, 0)
    if len(data) >= 73:
        proto_fees, creator_fees, signed_adj = struct.unpack("<QQq", data[49:73])
    return BondingCurveState(
        mint=mint,
        bonding_curve_address=bonding_curve_address,
        virtual_token_reserves=vt,
        virtual_quote_reserves=vq,
        real_token_reserves=rt,
        real_quote_reserves=rq,
        token_total_supply=supply,
        complete=comp,
        creator=creator,
        unswept_protocol_fees=proto_fees,
        unswept_creator_fees=creator_fees,
        signed_virtual_quote_adjustment=signed_adj,
        slot=slot,
        event_time=event_time,
    )


@dataclass(frozen=True)
class CurveQuote:
    mint: str
    side: str  # "buy" | "sell"
    instruction: str  # "buy_exact_quote_in_v3" | "buy_v3" | "sell_v3"
    quote_in_raw: int
    quote_out_raw: int
    tokens_out_raw: int
    tokens_in_raw: int
    protocol_fee_raw: int
    creator_fee_raw: int
    total_fee_raw: int
    spot_price_before: float
    execution_price: float
    spot_price_after: float
    price_impact_bps: float
    crosses_graduation: bool
    curve_tokens_filled_raw: int
    synthetic_migration_tokens_raw: int
    emitted_events: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def quote_curve_buy_exact_quote_in(
    state: BondingCurveState,
    quote_amount_in_raw: int,
    *,
    allow_synthetic_migration: bool = True,
) -> CurveQuote:
    """Quote ``buy_exact_quote_in_v3`` on a Pump.fun bonding curve, including v3 synthetic migration overflow."""
    if quote_amount_in_raw <= 0:
        raise ValueError("quote_amount_in_raw must be positive")
    if state.complete and not allow_synthetic_migration:
        raise ValueError(f"Bonding curve for {state.mint} is already complete; route to PumpSwap")

    eff_q = state.effective_virtual_quote_reserves
    vt = state.virtual_token_reserves
    if eff_q <= 0 or vt <= 0:
        raise ValueError(f"Invalid curve reserves for {state.mint}")

    spot_before = state.price_quote_per_token
    proto_fee = (quote_amount_in_raw * state.protocol_fee_bps) // 10_000
    creator_fee = (quote_amount_in_raw * state.creator_fee_bps) // 10_000
    total_fee = proto_fee + creator_fee
    net_quote_in = max(0, quote_amount_in_raw - total_fee)

    # Constant product: tokens_out = floor(vt * net_quote_in / (eff_q + net_quote_in))
    desired_tokens = (vt * net_quote_in) // (eff_q + net_quote_in)
    if desired_tokens <= state.real_token_reserves or state.complete:
        curve_tokens = min(desired_tokens, state.real_token_reserves) if not state.complete else 0
        synth_tokens = desired_tokens - curve_tokens
        crosses = synth_tokens > 0 or (curve_tokens == state.real_token_reserves and state.real_token_reserves > 0)
    else:
        if not allow_synthetic_migration:
            raise ValueError("Order exceeds remaining curve real_token_reserves and synthetic migration is disabled")
        curve_tokens = state.real_token_reserves
        # Quote needed to exhaust remaining real_token_reserves on the curve:
        quote_for_curve = (eff_q * curve_tokens) // max(1, vt - curve_tokens)
        rem_net_quote = max(0, net_quote_in - quote_for_curve)
        # Terminal curve price at graduation = (eff_q + quote_for_curve) / (vt - curve_tokens)
        term_q = eff_q + quote_for_curve
        term_t = max(1, vt - curve_tokens)
        synth_tokens = (rem_net_quote * term_t) // term_q
        crosses = True

    total_tokens = curve_tokens + synth_tokens
    new_vt = max(1, vt - curve_tokens)
    new_vq = eff_q + (net_quote_in if synth_tokens == 0 else (eff_q * curve_tokens) // new_vt)
    spot_after = (new_vq / (10**state.quote_decimals)) / (new_vt / (10**state.token_decimals))
    quote_whole = quote_amount_in_raw / (10**state.quote_decimals)
    tokens_whole = total_tokens / (10**state.token_decimals) if total_tokens > 0 else 0.0
    exec_price = (quote_whole / tokens_whole) if tokens_whole > 0 else spot_after
    impact_bps = max(0.0, ((exec_price / spot_before) - 1.0) * 10_000.0) if spot_before > 0 else 0.0

    events: list[str] = ["TradeEvent"]
    if crosses:
        events.append("CompleteEvent")
    if synth_tokens > 0:
        events.append("PostCompleteBuyEvent")

    return CurveQuote(
        mint=state.mint,
        side="buy",
        instruction="buy_exact_quote_in_v3",
        quote_in_raw=int(quote_amount_in_raw),
        quote_out_raw=0,
        tokens_out_raw=int(total_tokens),
        tokens_in_raw=0,
        protocol_fee_raw=int(proto_fee),
        creator_fee_raw=int(creator_fee),
        total_fee_raw=int(total_fee),
        spot_price_before=spot_before,
        execution_price=exec_price,
        spot_price_after=spot_after,
        price_impact_bps=round(impact_bps, 2),
        crosses_graduation=crosses,
        curve_tokens_filled_raw=int(curve_tokens),
        synthetic_migration_tokens_raw=int(synth_tokens),
        emitted_events=tuple(events),
    )


def quote_curve_sell(state: BondingCurveState, token_amount_in_raw: int) -> CurveQuote:
    """Quote ``sell_v3`` on a Pump.fun bonding curve."""
    if token_amount_in_raw <= 0:
        raise ValueError("token_amount_in_raw must be positive")
    if state.complete:
        raise ValueError(f"Bonding curve for {state.mint} is complete; sell on PumpSwap")

    eff_q = state.effective_virtual_quote_reserves
    vt = state.virtual_token_reserves
    if eff_q <= 0 or vt <= 0:
        raise ValueError(f"Invalid curve reserves for {state.mint}")

    spot_before = state.price_quote_per_token
    gross_quote_out = (eff_q * token_amount_in_raw) // (vt + token_amount_in_raw)
    gross_quote_out = min(gross_quote_out, state.real_quote_reserves)
    proto_fee = (gross_quote_out * state.protocol_fee_bps) // 10_000
    creator_fee = (gross_quote_out * state.creator_fee_bps) // 10_000
    total_fee = proto_fee + creator_fee
    net_quote_out = max(0, gross_quote_out - total_fee)

    new_vt = vt + token_amount_in_raw
    new_vq = max(1, eff_q - gross_quote_out)
    spot_after = (new_vq / (10**state.quote_decimals)) / (new_vt / (10**state.token_decimals))
    quote_whole = net_quote_out / (10**state.quote_decimals)
    tokens_whole = token_amount_in_raw / (10**state.token_decimals)
    exec_price = (quote_whole / tokens_whole) if tokens_whole > 0 else 0.0
    impact_bps = max(0.0, (1.0 - (exec_price / spot_before)) * 10_000.0) if spot_before > 0 else 0.0

    return CurveQuote(
        mint=state.mint,
        side="sell",
        instruction="sell_v3",
        quote_in_raw=0,
        quote_out_raw=int(net_quote_out),
        tokens_out_raw=0,
        tokens_in_raw=int(token_amount_in_raw),
        protocol_fee_raw=int(proto_fee),
        creator_fee_raw=int(creator_fee),
        total_fee_raw=int(total_fee),
        spot_price_before=spot_before,
        execution_price=exec_price,
        spot_price_after=spot_after,
        price_impact_bps=round(impact_bps, 2),
        crosses_graduation=False,
        curve_tokens_filled_raw=int(token_amount_in_raw),
        synthetic_migration_tokens_raw=0,
        emitted_events=("TradeEvent",),
    )

