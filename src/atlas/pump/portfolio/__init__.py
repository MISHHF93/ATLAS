"""Deterministic Risk Control Plane & Portfolio Accounting for Pump.fun & Solana trading.

All Pump.fun/PumpSwap trades pass through `PumpDeterministicRiskEngine`.
Unrealized P&L in `PumpPortfolioBook` is marked at the realizable net exit quote
after sell price impact and fees, never naively at the last observed trade price.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from atlas.risk.safe_stop import shared_safe_stop
from atlas.risk.safety import LiveTradingForbidden, assert_paper_only

from ..bonding_curve import BondingCurveState, quote_curve_sell
from ..liquidity import LiquidityAndImpactProfile
from ..pumpswap import PumpSwapPoolState, quote_pumpswap
from ..token_risk import TokenSafetyReport
from ..tokens import LAMPORTS_PER_SOL, PumpTokenRecord, TokenLifecycleState, assert_mint_identifier


@dataclass(frozen=True)
class PumpRiskLimits:
    """Deterministic risk limits enforced on every Pump.fun / PumpSwap order."""
    max_sol_exposure: float = 10.0
    max_position_size_sol: float = 1.5
    max_trade_loss_budget_sol: float = 0.35
    max_daily_loss_sol: float = 1.25
    max_portfolio_loss_sol: float = 3.0
    max_token_concentration_pct: float = 25.0
    max_slippage_bps: float = 250.0
    max_price_impact_bps: float = 300.0
    max_transaction_fee_sol: float = 0.01
    min_exit_liquidity_sol: float = 8.0
    max_data_age_seconds: float = 30.0
    max_correlated_creator_exposure_sol: float = 2.0
    max_consecutive_losses: int = 4
    kill_switch_active: bool = False
    allow_live_execution: bool = False  # Default False: paper trading only

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PumpRiskDecision:
    approved: bool
    mode: str  # "paper" | "live_refused"
    mint: str
    side: str
    requested_size_sol: float
    approved_size_sol: float
    checks: dict[str, bool]
    reject_reasons: tuple[str, ...]
    limits_snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PumpPosition:
    mint: str
    symbol: str
    creator_wallet: str
    quote_mint: str
    tokens_raw: int
    token_decimals: int
    cost_basis_sol: float
    avg_entry_price_sol: float
    opened_at_ts: float
    last_venue: str
    last_observed_price_sol: float = 0.0
    realizable_exit_value_sol: float = 0.0
    unrealized_pnl_sol: float = 0.0

    @property
    def tokens_whole(self) -> float:
        return self.tokens_raw / (10**self.token_decimals)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "tokens_whole": self.tokens_whole}


class PumpPortfolioBook:
    """SOL + token portfolio accounting with liquidation-adjusted mark-to-market."""

    def __init__(self, initial_cash_sol: float = 25.0) -> None:
        self.initial_cash_sol = float(initial_cash_sol)
        self.cash_sol = float(initial_cash_sol)
        self.positions: dict[str, PumpPosition] = {}
        self.realized_pnl_sol: float = 0.0
        self.daily_realized_pnl_sol: float = 0.0
        self.consecutive_losses: int = 0
        self.ledger: list[dict[str, Any]] = []

    def total_exposure_sol(self) -> float:
        return round(sum(p.cost_basis_sol for p in self.positions.values()), 6)

    def creator_exposure_sol(self, creator_wallet: str) -> float:
        return round(sum(p.cost_basis_sol for p in self.positions.values() if p.creator_wallet == creator_wallet), 6)

    def mark_position(
        self,
        mint: str,
        *,
        token: PumpTokenRecord,
        curve: BondingCurveState | None = None,
        pool: PumpSwapPoolState | None = None,
        exit_fee_sol: float = 0.000008,
    ) -> PumpPosition | None:
        """Mark position at realizable net exit quote after sell impact & fees (never last trade price)."""
        pos = self.positions.get(mint)
        if pos is None or pos.tokens_raw <= 0:
            return None
        pos.last_observed_price_sol = token.price_quote
        pos.last_venue = token.active_venue
        realizable_sol = 0.0
        try:
            if token.lifecycle_state == TokenLifecycleState.PUMPSWAP_ACTIVE and pool is not None:
                q = quote_pumpswap(pool, "sell", pos.tokens_raw)
                realizable_sol = max(0.0, (q.amount_out_raw / LAMPORTS_PER_SOL) - exit_fee_sol)
            elif curve is not None and not curve.complete:
                q2 = quote_curve_sell(curve, pos.tokens_raw)
                realizable_sol = max(0.0, (q2.quote_out_raw / LAMPORTS_PER_SOL) - exit_fee_sol)
        except Exception:
            realizable_sol = 0.0
        pos.realizable_exit_value_sol = round(realizable_sol, 6)
        pos.unrealized_pnl_sol = round(pos.realizable_exit_value_sol - pos.cost_basis_sol, 6)
        return pos

    def record_buy_fill(
        self,
        *,
        mint: str,
        symbol: str,
        creator_wallet: str,
        quote_mint: str,
        tokens_out_raw: int,
        token_decimals: int,
        quote_spent_sol: float,
        network_fee_sol: float,
        venue: str,
        ts: float,
        tx_signature: str,
    ) -> PumpPosition:
        assert_mint_identifier(mint)
        total_cost = round(float(quote_spent_sol) + float(network_fee_sol), 9)
        self.cash_sol = round(self.cash_sol - total_cost, 9)
        existing = self.positions.get(mint)
        if existing is None:
            tokens_whole = tokens_out_raw / (10**token_decimals)
            avg_px = total_cost / tokens_whole if tokens_whole > 0 else 0.0
            pos = PumpPosition(
                mint=mint,
                symbol=symbol,
                creator_wallet=creator_wallet,
                quote_mint=quote_mint,
                tokens_raw=int(tokens_out_raw),
                token_decimals=token_decimals,
                cost_basis_sol=round(total_cost, 6),
                avg_entry_price_sol=avg_px,
                opened_at_ts=ts,
                last_venue=venue,
                realizable_exit_value_sol=round(quote_spent_sol * 0.97, 6),
                unrealized_pnl_sol=round(quote_spent_sol * 0.97 - total_cost, 6),
            )
            self.positions[mint] = pos
        else:
            existing.tokens_raw += int(tokens_out_raw)
            existing.cost_basis_sol = round(existing.cost_basis_sol + total_cost, 6)
            existing.avg_entry_price_sol = (
                existing.cost_basis_sol / existing.tokens_whole if existing.tokens_whole > 0 else 0.0
            )
            existing.last_venue = venue
            pos = existing

        self.ledger.append({
            "ts": ts, "side": "buy", "mint": mint, "symbol": symbol, "tokens_raw": int(tokens_out_raw),
            "quote_sol": round(quote_spent_sol, 6), "network_fee_sol": round(network_fee_sol, 9),
            "venue": venue, "tx_signature": tx_signature,
        })
        return pos

    def record_sell_fill(
        self,
        *,
        mint: str,
        tokens_in_raw: int,
        quote_received_sol: float,
        network_fee_sol: float,
        venue: str,
        ts: float,
        tx_signature: str,
    ) -> dict[str, Any]:
        assert_mint_identifier(mint)
        pos = self.positions.get(mint)
        if pos is None or pos.tokens_raw < tokens_in_raw:
            raise ValueError(f"Insufficient position for {mint} sell fill")
        fraction = tokens_in_raw / pos.tokens_raw if pos.tokens_raw > 0 else 1.0
        allocated_cost = pos.cost_basis_sol * fraction
        net_proceeds = float(quote_received_sol) - float(network_fee_sol)
        realized = round(net_proceeds - allocated_cost, 6)

        self.cash_sol = round(self.cash_sol + net_proceeds, 9)
        self.realized_pnl_sol = round(self.realized_pnl_sol + realized, 6)
        self.daily_realized_pnl_sol = round(self.daily_realized_pnl_sol + realized, 6)
        if realized < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        pos.tokens_raw -= int(tokens_in_raw)
        pos.cost_basis_sol = round(max(0.0, pos.cost_basis_sol - allocated_cost), 6)
        if pos.tokens_raw <= 0:
            self.positions.pop(mint, None)

        entry = {
            "ts": ts, "side": "sell", "mint": mint, "symbol": pos.symbol, "tokens_raw": int(tokens_in_raw),
            "quote_sol": round(quote_received_sol, 6), "network_fee_sol": round(network_fee_sol, 9),
            "realized_pnl_sol": realized, "venue": venue, "tx_signature": tx_signature,
        }
        self.ledger.append(entry)
        return entry

    def summary(self) -> dict[str, Any]:
        unrealized = round(sum(p.unrealized_pnl_sol for p in self.positions.values()), 6)
        realizable_val = round(sum(p.realizable_exit_value_sol for p in self.positions.values()), 6)
        equity_sol = round(self.cash_sol + realizable_val, 6)
        return {
            "initial_cash_sol": self.initial_cash_sol,
            "cash_sol": round(self.cash_sol, 6),
            "open_positions_count": len(self.positions),
            "total_cost_exposure_sol": self.total_exposure_sol(),
            "realizable_positions_value_sol": realizable_val,
            "equity_sol": equity_sol,
            "realized_pnl_sol": self.realized_pnl_sol,
            "daily_realized_pnl_sol": self.daily_realized_pnl_sol,
            "unrealized_pnl_sol": unrealized,
            "total_pnl_sol": round(self.realized_pnl_sol + unrealized, 6),
            "consecutive_losses": self.consecutive_losses,
            "positions": [p.as_dict() for p in self.positions.values()],
            "recent_ledger": self.ledger[-25:],
        }


class PumpDeterministicRiskEngine:
    """Deterministic risk gate enforcing all 14 Pump.fun / Solana limits plus ATLAS Safe-Stop."""

    def __init__(self, limits: PumpRiskLimits | None = None) -> None:
        self.limits = limits or PumpRiskLimits()

    def evaluate_order(
        self,
        *,
        token: PumpTokenRecord,
        side: str,
        size_sol: float,
        slippage_bps: float,
        liquidity_profile: LiquidityAndImpactProfile,
        safety_report: TokenSafetyReport,
        portfolio: PumpPortfolioBook,
        data_age_seconds: float,
        requested_mode: str = "paper",
        stop_loss_pct: float = 0.12,
    ) -> PumpRiskDecision:
        assert_mint_identifier(token.mint)
        if requested_mode != "paper":
            try:
                assert_paper_only()
            except LiveTradingForbidden:
                pass
            return PumpRiskDecision(
                approved=False,
                mode="live_refused",
                mint=token.mint,
                side=side,
                requested_size_sol=size_sol,
                approved_size_sol=0.0,
                checks={"paper_only_interlock": False},
                reject_reasons=("live_execution_refused:paper_only_default",),
                limits_snapshot=self.limits.as_dict(),
            )

        lim = self.limits
        safe_stop_tripped = bool(shared_safe_stop().engaged)
        summary = portfolio.summary()
        equity = max(0.01, float(summary["equity_sol"]))
        new_exposure = portfolio.total_exposure_sol() + (size_sol if side == "buy" else 0.0)
        existing_pos = portfolio.positions.get(token.mint)
        token_post_sol = (existing_pos.cost_basis_sol if existing_pos else 0.0) + (size_sol if side == "buy" else 0.0)
        token_conc_pct = (token_post_sol / equity) * 100.0
        creator_post_sol = portfolio.creator_exposure_sol(token.creator_wallet) + (size_sol if side == "buy" else 0.0)
        trade_loss_est_sol = size_sol * max(stop_loss_pct, liquidity_profile.round_trip_cost_bps / 10_000.0)
        portfolio_drawdown_sol = max(0.0, portfolio.initial_cash_sol - equity)
        daily_loss_sol = max(0.0, -portfolio.daily_realized_pnl_sol)
        impact_bps = (
            liquidity_profile.buy_price_impact_bps if side == "buy" else liquidity_profile.sell_price_impact_bps
        )

        # Allow exits (sells) to reduce risk unless kill-switch or token untradable
        if side == "sell":
            checks = {
                "kill_switch_inactive": not lim.kill_switch_active and not safe_stop_tripped,
                "token_tradable": token.is_tradable(),
                "position_exists": existing_pos is not None and existing_pos.tokens_raw > 0,
                "max_slippage": slippage_bps <= lim.max_slippage_bps * 2,
                "max_transaction_fee": liquidity_profile.solana_fee_sol <= lim.max_transaction_fee_sol,
            }
        else:
            checks = {
                "kill_switch_inactive": not lim.kill_switch_active and not safe_stop_tripped,
                "token_tradable": token.is_tradable(),
                "token_safety_passed": safety_report.safety_status != "rejected",
                "max_sol_exposure": new_exposure <= lim.max_sol_exposure,
                "max_position_size": 0.0 < size_sol <= lim.max_position_size_sol,
                "max_trade_loss_budget": trade_loss_est_sol <= lim.max_trade_loss_budget_sol,
                "max_daily_loss": daily_loss_sol < lim.max_daily_loss_sol,
                "max_portfolio_loss": portfolio_drawdown_sol < lim.max_portfolio_loss_sol,
                "max_token_concentration": token_conc_pct <= lim.max_token_concentration_pct,
                "max_slippage": slippage_bps <= lim.max_slippage_bps,
                "max_price_impact": impact_bps <= lim.max_price_impact_bps,
                "max_transaction_fee": liquidity_profile.solana_fee_sol <= lim.max_transaction_fee_sol,
                "min_exit_liquidity": (
                    liquidity_profile.effective_liquidity_sol >= lim.min_exit_liquidity_sol
                    and liquidity_profile.sell_simulation_passed
                ),
                "min_data_freshness": 0.0 <= data_age_seconds <= lim.max_data_age_seconds,
                "max_correlated_exposure": creator_post_sol <= lim.max_correlated_creator_exposure_sol,
                "max_consecutive_losses": portfolio.consecutive_losses < lim.max_consecutive_losses,
                "sufficient_cash_sol": portfolio.cash_sol >= size_sol + liquidity_profile.solana_fee_sol,
            }

        failed = tuple(k for k, ok in checks.items() if not ok)
        approved = len(failed) == 0
        return PumpRiskDecision(
            approved=approved,
            mode="paper",
            mint=token.mint,
            side=side,
            requested_size_sol=size_sol,
            approved_size_sol=size_sol if approved else 0.0,
            checks=checks,
            reject_reasons=failed,
            limits_snapshot=lim.as_dict(),
        )
