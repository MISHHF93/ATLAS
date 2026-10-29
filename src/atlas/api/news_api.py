"""/api/news/*: per-user News feed, watchlist, refresh and the LLM Reviewer. Advisory only (execution_permission none); guarded by the AI node."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.news import reviewer as RV
from atlas.news import service as SV
from atlas.news import store as S

router = APIRouter()


class Watchlist(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=SV.MAX_WATCH)


class RefreshReq(BaseModel):
    tickers: list[str] | None = Field(None, max_length=SV.MAX_WATCH)
    annotate: bool = True


class ReviewReq(BaseModel):
    symbol: str = Field(max_length=20)
    side: Literal["long", "short"]
    interval: str | None = Field(None, max_length=6)
    probability: float | None = Field(None, ge=0.0, le=1.0)
    marker_id: str | None = Field(None, max_length=80)
    situation: str = Field("", max_length=2000)


@router.get("/status")
def status() -> dict:
    return SV.status()


@router.get("/feed")
def feed(ticker: str | None = Query(None, max_length=12), limit: int = Query(80, ge=1, le=300), days: int = Query(SV.FEED_DAYS, ge=1, le=90)) -> dict:
    return SV.feed([ticker.upper()] if ticker else None, limit, days)


@router.get("/watchlist")
def get_watchlist() -> dict:
    return {"tickers": S.get_watchlist(S.current_scope()), "available": SV.stock_names(), "execution_permission": "none"}


@router.api_route("/watchlist", methods=["PUT", "POST"])
def put_watchlist(body: Watchlist) -> dict:
    good, bad = SV.valid_tickers(body.tickers)
    return {"tickers": S.set_watchlist(S.current_scope(), good), "rejected": bad, "execution_permission": "none"}


@router.post("/refresh")
def refresh(body: RefreshReq) -> dict:
    return SV.refresh(body.tickers, body.annotate)


@router.post("/review")
def review(body: ReviewReq) -> dict:
    try:
        return RV.review(body.model_dump(exclude={"situation"}), situation=body.situation)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/reviews")
def reviews(limit: int = Query(50, ge=1, le=200), symbol: str | None = Query(None, max_length=20)) -> dict:
    return {"reviews": RV.reviews_for(S.current_scope(), limit, None, symbol.upper() if symbol else None), "execution_permission": "none"}


@router.get("/reviewer/effect")
def effect() -> dict:
    return RV.gate_eligibility(S.current_scope())
