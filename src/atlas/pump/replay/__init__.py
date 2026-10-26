"""Event-driven historical replay and backtesting engine for Pump.fun & PumpSwap.

Models:
- Actual token discovery timing (no lookahead).
- Historical bonding-curve states & PumpSwap pool transitions.
- Curve/pool fees, Solana base + priority fees, slippage, and price impact.
- Transaction latency (`latency_ms`) and failed transactions.
- Realistic exit liquidity: positions are exited via `quote_curve_sell` / `quote_pumpswap`,
  NEVER at the last observed trade price.
- Inactive/failed tokens included to prevent survivorship bias.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..bonding_curve import BondingCurveState, quote_curve_buy_exact_quote_in, quote_curve_sell
from ..liquidity import estimate_solana_tx_fee
from ..pumpswap import PumpSwapPoolState, quote_pumpswap
from ..tokens import LAMPORTS_PER_SOL


@dataclass(frozen=True)
class ReplayFrame:
    mint: str
    symbol: str
    slot: int
    event_time: float
    venue: str  # "bonding_curve" | "pumpswap" | "inactive" | "missing_data"
    last_trade_price_sol: float
    curve: BondingCurveState | None = None
    pool: PumpSwapPoolState | None = None
    signal_action: str = "hold"  # "buy" | "sell" | "hold"
    tx_fails_on_chain: bool = False


@dataclass(frozen=True)
class ReplayResult:
    total_frames: int
    tokens_seen: int
    inactive_tokens_seen: int
    missing_data_frames: int
    attempted_trades: int
    failed_transactions: int
    completed_round_trips: int
    gross_pnl_sol: float
    total_fees_and_impact_sol: float
    net_pnl_sol: float
    win_rate: float
    marked_at_last_trade_price: bool  # Always False
    trades: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_event_driven_replay(
    frames: Sequence[ReplayFrame],
    *,
    order_size_sol: float = 0.5,
    latency_ms: int = 400,
    micro_lamports_per_cu: int = 25_000,
) -> ReplayResult:
    """Run an event-driven backtest over chronological on-chain frames."""
    ordered = sorted(frames, key=lambda f: (f.event_time, f.slot))
    fee_est = estimate_solana_tx_fee(micro_lamports_per_cu=micro_lamports_per_cu)

    open_positions: dict[str, dict[str, Any]] = {}
    trade_log: list[dict[str, Any]] = []
    attempted = 0
    failed_txs = 0
    inactive_mints: set[str] = set()
    missing_frames = 0
    all_mints: set[str] = set()

    for idx, frame in enumerate(ordered):
        all_mints.add(frame.mint)
        if frame.venue == "inactive":
            inactive_mints.add(frame.mint)
            continue
        if frame.venue == "missing_data":
            missing_frames += 1
            continue

        # Apply execution latency: if latency_ms > 0 and a subsequent frame exists for the same mint within latency window,
        # execute against the post-latency state rather than the signal frame.
        exec_frame = frame
        if latency_ms > 0:
            target_ts = frame.event_time + (latency_ms / 1000.0)
            for nxt in ordered[idx + 1:]:
                if nxt.mint == frame.mint and nxt.event_time <= target_ts and nxt.venue in ("bonding_curve", "pumpswap"):
                    exec_frame = nxt
                    break

        if frame.signal_action == "buy" and frame.mint not in open_positions:
            attempted += 1
            if exec_frame.tx_fails_on_chain:
                failed_txs += 1
                trade_log.append({
                    "mint": frame.mint, "side": "buy", "status": "failed_tx",
                    "network_fee_lost_sol": fee_est.total_fee_sol, "event_time": exec_frame.event_time,
                })
                continue

            lamports_in = int(round(order_size_sol * LAMPORTS_PER_SOL))
            if exec_frame.venue == "pumpswap" and exec_frame.pool is not None:
                q = quote_pumpswap(exec_frame.pool, "buy", lamports_in)
                tokens_out = q.amount_out_raw
                impact_bps = q.price_impact_bps
            elif exec_frame.curve is not None and not exec_frame.curve.complete:
                qc = quote_curve_buy_exact_quote_in(exec_frame.curve, lamports_in)
                tokens_out = qc.tokens_out_raw
                impact_bps = qc.price_impact_bps
            else:
                failed_txs += 1
                continue

            open_positions[frame.mint] = {
                "mint": frame.mint,
                "symbol": frame.symbol,
                "tokens_raw": tokens_out,
                "entry_cost_sol": order_size_sol + fee_est.total_fee_sol,
                "entry_spot_price_sol": exec_frame.last_trade_price_sol,
                "entry_impact_bps": impact_bps,
                "entry_time": exec_frame.event_time,
            }

        elif frame.signal_action == "sell" and frame.mint in open_positions:
            attempted += 1
            pos = open_positions.pop(frame.mint)
            # Exit MUST use curve/pool sell quote (never last_trade_price_sol)
            if exec_frame.venue == "pumpswap" and exec_frame.pool is not None:
                qs = quote_pumpswap(exec_frame.pool, "sell", pos["tokens_raw"])
                quote_out_sol = qs.amount_out_raw / LAMPORTS_PER_SOL
                exit_impact_bps = qs.price_impact_bps
            elif exec_frame.curve is not None and not exec_frame.curve.complete:
                qcs = quote_curve_sell(exec_frame.curve, pos["tokens_raw"])
                quote_out_sol = qcs.quote_out_raw / LAMPORTS_PER_SOL
                exit_impact_bps = qcs.price_impact_bps
            else:
                quote_out_sol = 0.0
                exit_impact_bps = 10_000.0

            net_proceeds_sol = max(0.0, quote_out_sol - fee_est.total_fee_sol)
            naive_proceeds_sol = (pos["tokens_raw"] / 1e6) * exec_frame.last_trade_price_sol
            net_pnl = round(net_proceeds_sol - pos["entry_cost_sol"], 6)
            cost_drag = round(max(0.0, naive_proceeds_sol - net_proceeds_sol) + fee_est.total_fee_sol, 6)
            trade_log.append({
                "mint": frame.mint,
                "symbol": frame.symbol,
                "side": "round_trip",
                "status": "filled",
                "venue_exit": exec_frame.venue,
                "entry_cost_sol": round(pos["entry_cost_sol"], 6),
                "realizable_exit_sol": round(net_proceeds_sol, 6),
                "naive_last_price_exit_sol": round(naive_proceeds_sol, 6),
                "net_pnl_sol": net_pnl,
                "fees_and_impact_sol": cost_drag,
                "exit_price_impact_bps": exit_impact_bps,
            })

    # Force mark-to-liquidation on any still-open positions at the end of the replay
    for mint, pos in list(open_positions.items()):
        last_frames = [f for f in ordered if f.mint == mint]
        lf = last_frames[-1] if last_frames else None
        if lf is None or lf.venue in ("inactive", "missing_data"):
            realizable_sol = 0.0
        elif lf.venue == "pumpswap" and lf.pool is not None:
            realizable_sol = max(0.0, (quote_pumpswap(lf.pool, "sell", pos["tokens_raw"]).amount_out_raw / LAMPORTS_PER_SOL) - fee_est.total_fee_sol)
        elif lf.curve is not None and not lf.curve.complete:
            realizable_sol = max(0.0, (quote_curve_sell(lf.curve, pos["tokens_raw"]).quote_out_raw / LAMPORTS_PER_SOL) - fee_est.total_fee_sol)
        else:
            realizable_sol = 0.0
        net_pnl = round(realizable_sol - pos["entry_cost_sol"], 6)
        trade_log.append({
            "mint": mint,
            "symbol": pos["symbol"],
            "side": "mark_to_liquidation",
            "status": "closed_at_end",
            "entry_cost_sol": round(pos["entry_cost_sol"], 6),
            "realizable_exit_sol": round(realizable_sol, 6),
            "net_pnl_sol": net_pnl,
            "fees_and_impact_sol": round(max(0.0, pos["entry_cost_sol"] - realizable_sol), 6),
        })

    rt = [t for t in trade_log if "net_pnl_sol" in t]
    net_total = round(sum(t["net_pnl_sol"] for t in rt), 6)
    fees_total = round(sum(t.get("fees_and_impact_sol", 0.0) for t in rt) + failed_txs * fee_est.total_fee_sol, 6)
    gross_total = round(net_total + fees_total, 6)
    wins = sum(1 for t in rt if t["net_pnl_sol"] > 0)

    return ReplayResult(
        total_frames=len(ordered),
        tokens_seen=len(all_mints),
        inactive_tokens_seen=len(inactive_mints),
        missing_data_frames=missing_frames,
        attempted_trades=attempted,
        failed_transactions=failed_txs,
        completed_round_trips=len(rt),
        gross_pnl_sol=gross_total,
        total_fees_and_impact_sol=fees_total,
        net_pnl_sol=net_total,
        win_rate=round(wins / len(rt), 4) if rt else 0.0,
        marked_at_last_trade_price=False,
        trades=tuple(trade_log),
    )

