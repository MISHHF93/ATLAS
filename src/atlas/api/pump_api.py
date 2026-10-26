"""FastAPI router for ATLAS Pump Intelligence (`/api/pump/*`)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.pump import (
    MINT_ALPHA_CURVE,
    MINT_ALPHA_RUG,
    MINT_GRAD_SWAP,
    ReplayFrame,
    WalletSecurityError,
    get_pump_engine,
    is_valid_pubkey,
    quote_curve_buy_exact_quote_in,
    quote_curve_sell,
    quote_pumpswap,
    run_event_driven_replay,
)
from atlas.pump.tokens import LAMPORTS_PER_SOL

router = APIRouter(tags=["pump-solana"])


class QuoteRequest(BaseModel):
    mint: str
    side: str = Field(default="buy", pattern="^(buy|sell)$")
    size_sol: float = Field(default=0.5, gt=0.0, le=50.0)
    tokens_in_raw: int | None = None
    slippage_bps: float = Field(default=150.0, ge=1.0, le=2000.0)


class PaperOrderRequest(BaseModel):
    client_order_id: str
    mint: str
    side: str = Field(default="buy", pattern="^(buy|sell)$")
    size_sol: float = Field(default=0.5, gt=0.0, le=50.0)
    slippage_bps: float = Field(default=150.0, ge=1.0, le=2000.0)
    requested_mode: str = "paper"
    origin: str = "execution_adapter"


class KillSwitchRequest(BaseModel):
    active: bool


@router.get("/workbench")
def get_workbench(q: str = Query(default="")) -> dict[str, Any]:
    eng = get_pump_engine()
    return eng.workbench_snapshot(query=q)


@router.get("/tokens/{mint}")
def get_token_detail(mint: str, order_size_sol: float = Query(default=0.5, gt=0.0, le=50.0)) -> dict[str, Any]:
    if not is_valid_pubkey(mint):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Solana mint address {mint!r}: tokens must be queried by base58 mint address, never by symbol alone.",
        )
    eng = get_pump_engine()
    try:
        return eng.evaluate_token_pipeline(mint, order_size_sol=order_size_sol)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/quote")
def post_quote(req: QuoteRequest) -> dict[str, Any]:
    if not is_valid_pubkey(req.mint):
        raise HTTPException(status_code=400, detail="Invalid base58 mint address")
    eng = get_pump_engine()
    try:
        tok = eng.discovery.get_by_mint(req.mint)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    curve = eng.discovery.curve_for(req.mint)
    pool = eng.discovery.pool_for(req.mint)
    lamports = int(round(req.size_sol * LAMPORTS_PER_SOL))

    try:
        if tok.lifecycle_state.value == "PUMPSWAP_ACTIVE" and pool is not None:
            amt = lamports if req.side == "buy" else int(req.tokens_in_raw or 1_000_000_000)
            q = quote_pumpswap(pool, req.side, amt)
            tx_sim = eng.execution.build_and_simulate_transaction(
                client_order_id="quote-preview",
                token=tok,
                side=req.side,
                size_sol=req.size_sol,
                slippage_bps=req.slippage_bps,
                pool=pool,
                tokens_to_sell_raw=amt if req.side == "sell" else None,
            )
            return {"venue": "pumpswap", "quote": q.as_dict(), "simulation": tx_sim, "execution_permission": "none"}
        if curve is not None:
            if req.side == "buy":
                qc = quote_curve_buy_exact_quote_in(curve, lamports)
            else:
                qc = quote_curve_sell(curve, int(req.tokens_in_raw or 1_000_000_000))
            tx_sim = eng.execution.build_and_simulate_transaction(
                client_order_id="quote-preview",
                token=tok,
                side=req.side,
                size_sol=req.size_sol,
                slippage_bps=req.slippage_bps,
                curve=curve,
                tokens_to_sell_raw=int(req.tokens_in_raw or 1_000_000_000) if req.side == "sell" else None,
            )
            return {"venue": "bonding_curve", "quote": qc.as_dict(), "simulation": tx_sim, "execution_permission": "none"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail=f"Token {req.mint} has no quotable curve or pool")


@router.post("/paper-order")
def post_paper_order(req: PaperOrderRequest) -> dict[str, Any]:
    if not is_valid_pubkey(req.mint):
        raise HTTPException(status_code=400, detail="Invalid base58 mint address")
    eng = get_pump_engine()
    try:
        return eng.execute_end_to_end_order(
            client_order_id=req.client_order_id,
            mint=req.mint,
            side=req.side,
            size_sol=req.size_sol,
            slippage_bps=req.slippage_bps,
            requested_mode=req.requested_mode,
            origin=req.origin,
        )
    except WalletSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/replay")
def post_replay() -> dict[str, Any]:
    eng = get_pump_engine()
    now = float(eng.clock())
    c1 = eng.discovery.curve_for(MINT_ALPHA_CURVE)
    p2 = eng.discovery.pool_for(MINT_GRAD_SWAP)
    frames = [
        ReplayFrame(MINT_ALPHA_CURVE, "ALPHA", 312_500_010, now - 180.0, "bonding_curve", c1.price_quote_per_token if c1 else 0.00004, curve=c1, signal_action="buy"),
        ReplayFrame(MINT_ALPHA_CURVE, "ALPHA", 312_500_020, now - 60.0, "bonding_curve", (c1.price_quote_per_token * 1.08) if c1 else 0.000043, curve=c1, signal_action="sell"),
        ReplayFrame(MINT_GRAD_SWAP, "SOLPUMP", 312_500_025, now - 120.0, "pumpswap", p2.price_quote_per_token if p2 else 0.0004, pool=p2, signal_action="buy"),
        ReplayFrame(MINT_GRAD_SWAP, "SOLPUMP", 312_500_035, now - 30.0, "pumpswap", p2.price_quote_per_token if p2 else 0.0004, pool=p2, signal_action="sell"),
        ReplayFrame(MINT_ALPHA_RUG, "ALPHA", 312_500_040, now - 20.0, "inactive", 0.0),
    ]
    res = run_event_driven_replay(frames, order_size_sol=0.5, latency_ms=400)
    return {**res.as_dict(), "execution_permission": "none"}


@router.post("/kill-switch")
def post_kill_switch(req: KillSwitchRequest) -> dict[str, Any]:
    from dataclasses import replace
    eng = get_pump_engine()
    eng.risk_engine.limits = replace(eng.risk_engine.limits, kill_switch_active=bool(req.active))
    return {"kill_switch_active": eng.risk_engine.limits.kill_switch_active, "limits": eng.risk_engine.limits.as_dict()}

