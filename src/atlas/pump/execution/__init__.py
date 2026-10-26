"""Pump.fun / PumpSwap Execution Adapter & Dedicated Trading Wallet Security Guard.

Enforces:
- Private keys are NEVER exposed to frontend JS, logs, prompts, LLM outputs, or telemetry.
- Arbitrary LLM/AI-generated transactions are blocked from reaching the signer (`WalletSecurityError`).
- Strict per-tx and daily SOL spending limits.
- Venue detection (`bonding_curve` v3 17-account layout vs `pumpswap` vs `multi_hop`).
- Transaction simulation before signing/execution.
- Idempotency tracking: never assumes a submitted transaction executed, and never retries a
  potentially executed transaction without checking `getSignatureStatuses` and idempotency state.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from atlas.risk.safety import assert_paper_only

from ..bonding_curve import BondingCurveState, quote_curve_buy_exact_quote_in, quote_curve_sell
from ..liquidity import (
    DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS_PER_CU,
    DEFAULT_SWAP_COMPUTE_UNITS,
    estimate_solana_tx_fee,
)
from ..portfolio import PumpPortfolioBook, PumpRiskDecision
from ..pumpswap import PumpSwapPoolState, quote_pumpswap
from ..tokens import (
    ASSOCIATED_TOKEN_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    LAMPORTS_PER_SOL,
    PUMP_FEE_SHARING_PROGRAM_ID,
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    PumpTokenRecord,
    TokenLifecycleState,
    assert_mint_identifier,
)

ALLOWED_SIGNER_PROGRAM_IDS = frozenset({
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    PUMP_FEE_SHARING_PROGRAM_ID,
    SPL_TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    ASSOCIATED_TOKEN_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
})

FORBIDDEN_ORIGINS = frozenset({"llm", "ai", "agent", "model_prompt", "tool_output", "untrusted_plugin"})
_SECRET_PATTERNS = re.compile(r"(private[_-]?key|secret[_-]?key|seed[_-]?phrase|mnemonic)", re.IGNORECASE)


class WalletSecurityError(RuntimeError):
    """Raised when a wallet security invariant is violated."""


@dataclass
class DedicatedTradingWalletGuard:
    """Secure signing boundary for the dedicated Solana trading wallet."""
    wallet_pubkey: str = "AtLaSpUmPWaLLeT1111111111111111111111111111"
    max_sol_per_tx: float = 1.5
    max_daily_sol_spend: float = 5.0
    daily_sol_spent: float = 0.0
    live_signing_authorized: bool = False

    def scrub_telemetry(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Strip any key resembling a secret/private key or raw byte array before logging or returning to UI/LLM."""
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if _SECRET_PATTERNS.search(str(k)):
                out[k] = "[REDACTED_WALLET_SECRET]"
            elif isinstance(v, dict):
                out[k] = self.scrub_telemetry(v)
            elif isinstance(v, str) and len(v) >= 64 and all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in v):
                # Base58 64-byte keypair string pattern -> redact
                out[k] = "[REDACTED_BASE58_KEYPAIR]"
            else:
                out[k] = v
        return out

    def validate_transaction_for_signing(
        self,
        tx_envelope: Mapping[str, Any],
        *,
        origin: str,
        risk_decision: PumpRiskDecision,
    ) -> dict[str, Any]:
        """Verify origin, program allowlist, risk approval, and spending limits before signing."""
        if origin.strip().lower() in FORBIDDEN_ORIGINS:
            raise WalletSecurityError(
                f"Rejected transaction from forbidden origin {origin!r}: arbitrary LLM/AI transactions cannot reach the signer."
            )
        if not risk_decision.approved:
            raise WalletSecurityError(
                f"Rejected transaction: deterministic risk engine did not approve order ({risk_decision.reject_reasons})"
            )
        if tx_envelope.get("adapter_generated") is not True:
            raise WalletSecurityError("Rejected transaction: only validated adapter-generated transactions are permitted.")

        programs = tx_envelope.get("program_ids") or ()
        disallowed = [p for p in programs if p not in ALLOWED_SIGNER_PROGRAM_IDS]
        if disallowed:
            raise WalletSecurityError(f"Rejected transaction containing unapproved program IDs: {disallowed}")

        sol_spend = float(tx_envelope.get("quote_spend_sol", 0.0)) + float(tx_envelope.get("network_fee_sol", 0.0))
        if sol_spend > self.max_sol_per_tx:
            raise WalletSecurityError(f"Spending limit exceeded: {sol_spend:.4f} SOL > max_sol_per_tx {self.max_sol_per_tx:.4f} SOL")
        if self.daily_sol_spent + sol_spend > self.max_daily_sol_spend:
            raise WalletSecurityError(
                f"Daily spending limit exceeded: {self.daily_sol_spent + sol_spend:.4f} SOL > {self.max_daily_sol_spend:.4f} SOL"
            )

        return {"valid": True, "signer": self.wallet_pubkey, "sol_spend": round(sol_spend, 9)}

    def status(self) -> dict[str, Any]:
        return {
            "wallet_pubkey": self.wallet_pubkey,
            "live_signing_authorized": False,
            "private_key_exposed_to_frontend": False,
            "llm_signing_access": "denied",
            "max_sol_per_tx": self.max_sol_per_tx,
            "max_daily_sol_spend": self.max_daily_sol_spend,
            "daily_sol_spent": round(self.daily_sol_spent, 6),
            "remaining_daily_sol_budget": round(max(0.0, self.max_daily_sol_spend - self.daily_sol_spent), 6),
        }


@dataclass
class OrderExecutionRecord:
    client_order_id: str
    mint: str
    side: str
    venue: str
    instruction: str
    status: str  # "simulated" | "submitted" | "confirmed" | "finalized" | "failed" | "rejected"
    mode: str  # "paper"
    quote_amount_sol: float
    tokens_amount_raw: int
    min_output_raw: int
    slippage_bps: float
    price_impact_bps: float
    protocol_fee_raw: int
    creator_fee_raw: int
    network_fee_sol: float
    tx_signature: str
    simulation_logs: tuple[str, ...] = field(default_factory=tuple)
    account_count: int = 17
    ts: float = 0.0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PumpExecutionAdapter:
    """Pump.fun (`buy_v3`/`sell_v3` 17-account layout) and PumpSwap execution & paper simulation adapter."""

    def __init__(self, wallet_guard: DedicatedTradingWalletGuard | None = None) -> None:
        self.wallet = wallet_guard or DedicatedTradingWalletGuard()
        self._orders_by_client_id: dict[str, OrderExecutionRecord] = {}
        self._tx_statuses: dict[str, dict[str, Any]] = {}

    def detect_venue(self, token: PumpTokenRecord) -> str:
        if token.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE:
            return "pumpswap"
        if token.lifecycle_state in (TokenLifecycleState.CURVE_ACTIVE, TokenLifecycleState.MIGRATION_PENDING):
            return "bonding_curve"
        return "none"

    def build_and_simulate_transaction(
        self,
        *,
        client_order_id: str,
        token: PumpTokenRecord,
        side: str,
        size_sol: float,
        slippage_bps: float,
        curve: BondingCurveState | None = None,
        pool: PumpSwapPoolState | None = None,
        tokens_to_sell_raw: int | None = None,
        compute_unit_limit: int = DEFAULT_SWAP_COMPUTE_UNITS,
        micro_lamports_per_cu: int = DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS_PER_CU,
    ) -> dict[str, Any]:
        """Construct a deterministic v3 bonding-curve or PumpSwap transaction and simulate it."""
        assert_mint_identifier(token.mint)
        venue = self.detect_venue(token)
        if venue == "none":
            raise ValueError(f"Token {token.mint} has no active execution venue (state={token.lifecycle_state.value})")

        fee_est = estimate_solana_tx_fee(
            signatures=1, compute_unit_limit=compute_unit_limit, micro_lamports_per_cu=micro_lamports_per_cu
        )
        lamports_in = max(1, int(round(size_sol * LAMPORTS_PER_SOL)))

        if venue == "pumpswap":
            if pool is None:
                raise ValueError(f"Missing PumpSwapPoolState for graduated token {token.mint}")
            amt_in = lamports_in if side == "buy" else int(tokens_to_sell_raw or 0)
            q = quote_pumpswap(pool, side, amt_in)
            min_out = int(q.amount_out_raw * (1.0 - slippage_bps / 10_000.0))
            program_id = PUMPSWAP_PROGRAM_ID
            ix_name = "pumpswap_buy" if side == "buy" else "pumpswap_sell"
            acct_count = 17
            tokens_raw = q.amount_out_raw if side == "buy" else amt_in
            quote_sol = size_sol if side == "buy" else (q.amount_out_raw / LAMPORTS_PER_SOL)
            proto_fee = q.protocol_fee_raw
            creator_fee = q.creator_fee_raw
            impact_bps = q.price_impact_bps
        else:
            if curve is None:
                raise ValueError(f"Missing BondingCurveState for curve token {token.mint}")
            if side == "buy":
                q_c = quote_curve_buy_exact_quote_in(curve, lamports_in)
                min_out = int(q_c.tokens_out_raw * (1.0 - slippage_bps / 10_000.0))
                ix_name = "buy_exact_quote_in_v3"
                tokens_raw = q_c.tokens_out_raw
                quote_sol = size_sol
            else:
                sell_raw = int(tokens_to_sell_raw or 0)
                q_c = quote_curve_sell(curve, sell_raw)
                min_out = int(q_c.quote_out_raw * (1.0 - slippage_bps / 10_000.0))
                ix_name = "sell_v3"
                tokens_raw = sell_raw
                quote_sol = q_c.quote_out_raw / LAMPORTS_PER_SOL
            program_id = PUMP_PROGRAM_ID
            acct_count = 17  # Streamlined v3 17-account footprint
            proto_fee = q_c.protocol_fee_raw
            creator_fee = q_c.creator_fee_raw
            impact_bps = q_c.price_impact_bps

        sim_ok = impact_bps <= max(slippage_bps * 1.5, 500.0) and min_out > 0
        logs = (
            f"Program {COMPUTE_BUDGET_PROGRAM_ID} invoke [1]",
            f"Program log: SetComputeUnitLimit({compute_unit_limit}), SetComputeUnitPrice({micro_lamports_per_cu})",
            f"Program {program_id} invoke [1]",
            f"Program log: Instruction: {ix_name} (accounts={acct_count}, min_out={min_out})",
            f"Program {program_id} success" if sim_ok else f"Program log: AnchorError: TooMuchSlippage (impact={impact_bps}bps)",
        )

        return {
            "adapter_generated": True,
            "client_order_id": client_order_id,
            "mint": token.mint,
            "side": side,
            "venue": venue,
            "instruction": ix_name,
            "account_count": acct_count,
            "program_ids": (COMPUTE_BUDGET_PROGRAM_ID, program_id, token.token_program),
            "quote_spend_sol": round(size_sol if side == "buy" else 0.0, 9),
            "quote_amount_sol": round(quote_sol, 9),
            "tokens_amount_raw": int(tokens_raw),
            "min_output_raw": int(min_out),
            "slippage_bps": float(slippage_bps),
            "price_impact_bps": float(impact_bps),
            "protocol_fee_raw": int(proto_fee),
            "creator_fee_raw": int(creator_fee),
            "network_fee_sol": fee_est.total_fee_sol,
            "simulation_passed": sim_ok,
            "simulation_logs": logs,
        }

    def execute_paper_order(
        self,
        *,
        client_order_id: str,
        token: PumpTokenRecord,
        side: str,
        size_sol: float,
        slippage_bps: float,
        risk_decision: PumpRiskDecision,
        portfolio: PumpPortfolioBook,
        curve: BondingCurveState | None = None,
        pool: PumpSwapPoolState | None = None,
        tokens_to_sell_raw: int | None = None,
        origin: str = "execution_adapter",
        now_ts: float = 0.0,
    ) -> OrderExecutionRecord:
        """Execute a paper order through wallet guard, simulation, confirmation tracking, and book reconciliation."""
        assert_paper_only()
        # Idempotency guard: never retry a potentially executed order without checking existing status
        existing = self._orders_by_client_id.get(client_order_id)
        if existing is not None and existing.status in ("submitted", "confirmed", "finalized"):
            return existing

        tx_env = self.build_and_simulate_transaction(
            client_order_id=client_order_id,
            token=token,
            side=side,
            size_sol=size_sol,
            slippage_bps=slippage_bps,
            curve=curve,
            pool=pool,
            tokens_to_sell_raw=tokens_to_sell_raw,
        )

        # Validate through wallet security boundary (blocks LLM origins, unapproved programs, overspending)
        self.wallet.validate_transaction_for_signing(tx_env, origin=origin, risk_decision=risk_decision)

        if not tx_env["simulation_passed"] or tx_env["price_impact_bps"] > slippage_bps:
            rec = OrderExecutionRecord(
                client_order_id=client_order_id,
                mint=token.mint,
                side=side,
                venue=tx_env["venue"],
                instruction=tx_env["instruction"],
                status="rejected",
                mode="paper",
                quote_amount_sol=tx_env["quote_amount_sol"],
                tokens_amount_raw=tx_env["tokens_amount_raw"],
                min_output_raw=tx_env["min_output_raw"],
                slippage_bps=slippage_bps,
                price_impact_bps=tx_env["price_impact_bps"],
                protocol_fee_raw=tx_env["protocol_fee_raw"],
                creator_fee_raw=tx_env["creator_fee_raw"],
                network_fee_sol=tx_env["network_fee_sol"],
                tx_signature="",
                simulation_logs=tuple(tx_env["simulation_logs"]),
                account_count=tx_env["account_count"],
                ts=now_ts,
                error=f"slippage_or_simulation_rejected:impact={tx_env['price_impact_bps']}bps>slippage={slippage_bps}bps",
            )
            self._orders_by_client_id[client_order_id] = rec
            return rec

        sig_digest = hashlib.sha256(f"{client_order_id}:{token.mint}:{side}:{now_ts}".encode()).hexdigest()[:44]
        sig = f"5PaperSim{sig_digest}"

        if side == "buy":
            self.wallet.daily_sol_spent = round(
                self.wallet.daily_sol_spent + size_sol + tx_env["network_fee_sol"], 9
            )
            portfolio.record_buy_fill(
                mint=token.mint,
                symbol=token.symbol,
                creator_wallet=token.creator_wallet,
                quote_mint=token.quote_mint,
                tokens_out_raw=tx_env["tokens_amount_raw"],
                token_decimals=token.decimals,
                quote_spent_sol=size_sol,
                network_fee_sol=tx_env["network_fee_sol"],
                venue=tx_env["venue"],
                ts=now_ts,
                tx_signature=sig,
            )
        else:
            portfolio.record_sell_fill(
                mint=token.mint,
                tokens_in_raw=tx_env["tokens_amount_raw"],
                quote_received_sol=tx_env["quote_amount_sol"],
                network_fee_sol=tx_env["network_fee_sol"],
                venue=tx_env["venue"],
                ts=now_ts,
                tx_signature=sig,
            )

        rec = OrderExecutionRecord(
            client_order_id=client_order_id,
            mint=token.mint,
            side=side,
            venue=tx_env["venue"],
            instruction=tx_env["instruction"],
            status="confirmed",
            mode="paper",
            quote_amount_sol=tx_env["quote_amount_sol"],
            tokens_amount_raw=tx_env["tokens_amount_raw"],
            min_output_raw=tx_env["min_output_raw"],
            slippage_bps=slippage_bps,
            price_impact_bps=tx_env["price_impact_bps"],
            protocol_fee_raw=tx_env["protocol_fee_raw"],
            creator_fee_raw=tx_env["creator_fee_raw"],
            network_fee_sol=tx_env["network_fee_sol"],
            tx_signature=sig,
            simulation_logs=tuple(tx_env["simulation_logs"]),
            account_count=tx_env["account_count"],
            ts=now_ts,
        )
        self._orders_by_client_id[client_order_id] = rec
        self._tx_statuses[sig] = {
            "signature": sig,
            "client_order_id": client_order_id,
            "confirmation_status": "confirmed",
            "slot": token.last_slot,
            "err": None,
        }
        return rec

    def get_signature_status(self, signature: str) -> dict[str, Any] | None:
        return self._tx_statuses.get(signature)

    def orders(self) -> list[dict[str, Any]]:
        return [o.as_dict() for o in self._orders_by_client_id.values()]

