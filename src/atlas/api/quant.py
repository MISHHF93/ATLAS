"""Read-only price-action endpoints. Candidates are proposals for the deterministic control plane;
nothing here submits, sizes, or authorizes an order (execution_permission: none)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.features.price_action import PRESETS, EngineConfig, PriceActionEngine, bars_from_rows
from atlas.features.price_action.proposals import candidate_to_signal, evaluate
from atlas.features.price_action.replay import ReplayConfig, replay

quant_router = APIRouter(prefix="/api/quant", tags=["quant"])


class BarsIn(BaseModel):
    instrument: str = Field(min_length=1)
    timeframe: int = Field(gt=0)
    rows: list[list[float]] = Field(description="[t_start_unix, o, h, l, c, v]")
    session: str | None = None
    data_label: str = Field(default="caller_supplied", description="e.g. synthetic_fixture")


def _engine(instrument: str, timeframe: int, session: str | None) -> PriceActionEngine:
    if session is not None and session not in PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown session; choose one of {sorted(PRESETS)}")
    return PriceActionEngine(instrument, timeframe, EngineConfig(session=PRESETS.get(session) if session else None))


def _payload(eng: PriceActionEngine, origin: Any) -> dict[str, Any]:
    out = eng.summary()
    out["evaluations"], out["proposals"] = [], []
    for c in eng.candidates:
        pred, ev = evaluate(c)   # default registry: no validated setup model -> abstains
        out["evaluations"].append({"candidate_id": c.candidate_id, "prediction": pred.to_dict(), "evaluation": ev.to_dict()})
        if not ev.abstained:
            out["proposals"].append({"candidate_id": c.candidate_id, "signal": candidate_to_signal(c, ev).model_dump(mode="json"),
                                     "submitted": False, "authority": "ActionableControlPlaneEngine"})
    out["feed_origin"] = origin
    return out


def _visible(symbol: str, resolution: str) -> tuple[list, Any, int]:
    from atlas.api.app import live_market_gateway
    from atlas.api.udf import _desk_symbol, _projected_rows, causal_bars, resolution_seconds

    bucket = resolution_seconds(resolution)
    if bucket is None:
        raise HTTPException(status_code=400, detail="unsupported_resolution")
    rows, report = _projected_rows(live_market_gateway, _desk_symbol(symbol), bucket)
    now = int(datetime.now(timezone.utc).timestamp())
    visible = causal_bars(rows, bucket_seconds=bucket, start=0, end=now + 1, as_of=now)
    return visible, report, bucket


def _desk(symbol: str, resolution: str, session: str | None) -> dict[str, Any]:
    now = int(datetime.now(timezone.utc).timestamp())
    visible, report, bucket = _visible(symbol, resolution)
    eng = _engine(symbol.upper(), bucket, session)
    eng.run_batch(bars_from_rows(visible, bucket), now=now)
    out = _payload(eng, report.get("feed_origin"))
    out["bars_used"] = len(visible)
    out["bars"] = [list(r) for r in visible]
    if not visible:
        out["note"] = "no confirmed bars available for this symbol"
    return out


@quant_router.get("/zones")
def quant_zones(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None) -> dict[str, Any]:
    out = _desk(symbol, resolution, session)
    return {k: out[k] for k in ("instrument", "timeframe", "zones", "bars_used", "feed_origin", "execution_permission")}


@quant_router.get("/setups")
def quant_setups(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None) -> dict[str, Any]:
    return _desk(symbol, resolution, session)


@quant_router.post("/analyze")
def quant_analyze(body: BarsIn) -> dict[str, Any]:
    """Stateless analysis of caller-supplied bars (read-only; nothing persisted)."""
    eng = _engine(body.instrument, body.timeframe, body.session)
    try:
        eng.run_batch(bars_from_rows(body.rows, body.timeframe))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _payload(eng, body.data_label)


@quant_router.get("/replay")
def quant_replay(symbol: str = Query(min_length=1), resolution: str = "60", session: str | None = None,
                 cost_per_unit: float = Query(0.0, ge=0), max_hold_bars: int = Query(8, ge=1, le=500)) -> dict[str, Any]:
    """Conservative OHLC paper replay over the platform's confirmed bars (live detection path). Research only."""
    visible, report, bucket = _visible(symbol, resolution)
    eng = _engine(symbol.upper(), bucket, session)
    res = replay(symbol.upper(), bucket, bars_from_rows(visible, bucket), engine_cfg=eng.cfg,
                 cfg=ReplayConfig(cost_per_unit=cost_per_unit, max_hold_bars=max_hold_bars),
                 data_label=f"real:{report.get('feed_origin')}" if visible else "no_data")
    out = res.to_dict()
    out["feed_origin"] = report.get("feed_origin")
    out["note"] = "descriptive replay only; not a validated performance estimate"
    return out


# ---------- price-level suite + strategy registry (research; execution_permission none) ----------
from dataclasses import asdict as _asdict  # noqa: E402

from atlas.features.price_action.strategies import BY_ID as _STRAT, StrategyRegistry  # noqa: E402
from atlas.features.price_action.suite import StrategyToggles, SuiteConfig, is_gold  # noqa: E402

_CAL = {"GC": "COMEX", "MGC": "COMEX", "SI": "COMEX", "HG": "COMEX", "CL": "NYMEX", "ES": "CMES", "NQ": "CMES"}


class ToggleIn(BaseModel):
    enabled: bool


@quant_router.get("/strategies")
def quant_strategies() -> dict[str, Any]:
    return {"strategies": StrategyRegistry().listing(), "execution_permission": "none",
            "note": "toggles choose which detectors run and which candidates the selector may rank; they never authorize orders"}


@quant_router.post("/strategies/{sid}")
def quant_strategy_toggle(sid: str, body: ToggleIn) -> dict[str, Any]:
    if sid not in _STRAT:
        raise HTTPException(status_code=404, detail="unknown strategy")
    try:
        StrategyRegistry().set(sid, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return quant_strategies()


@quant_router.post("/strategies/{sid}/retired/{interval}")
def quant_strategy_retire(sid: str, interval: str, body: ToggleIn) -> dict[str, Any]:
    """Research retirement toggle per (strategy, interval); ``enabled`` true = retired. Reversible; never authorizes."""
    if sid not in _STRAT or interval not in ("15m", "1h", "4h"):
        raise HTTPException(status_code=404, detail="unknown strategy or interval")
    StrategyRegistry().set_retired(sid, interval, body.enabled)
    return quant_strategies()


def _suite_calendar(sym: str) -> str:
    if sym in _CAL:
        return _CAL[sym]
    return "crypto" if sym.endswith(("USDT", "USD", "USDC")) else "XNYS"


@quant_router.get("/levels")
def quant_levels(symbol: str = Query(min_length=1), resolution: str = "15") -> dict[str, Any]:
    """Potential liquidity reference levels, interaction events, SFP / gold-box candidates and NO_TRADE reasons."""
    sym = symbol.upper()
    reg = StrategyRegistry()
    visible, report, bucket = _visible(symbol, resolution)
    try:
        daily_rows, _, _ = _visible(symbol, "D")
    except HTTPException:
        daily_rows = []
    now = int(datetime.now(timezone.utc).timestamp())
    toggles = StrategyToggles(reg.enabled("sfp"), reg.enabled("gold_snapback"), reg.enabled("gold_orb_breakout"))
    sc = SuiteConfig(toggles=toggles, calendar=_suite_calendar(sym), daily=tuple((int(r[0]), r[2], r[3], r[4]) for r in daily_rows))
    eng = PriceActionEngine(sym, bucket, EngineConfig(suite=sc))
    eng.run_batch(bars_from_rows(visible, bucket), now=now)
    su = eng.detectors[-1]
    on = reg.enabled_detectors()
    return {
        "instrument": sym, "timeframe": bucket, "calendar": sc.calendar, "gold_rules_applied": is_gold(sym),
        "label": "POTENTIAL LIQUIDITY REFERENCE LEVELS",
        "levels": [_asdict(lv) for lv in su.registry.levels[-300:]],
        "events": [_asdict(e) for e in su.level_events[-500:]],
        "zones": [z.to_dict() for z in su.zones],
        "candidates": [c.to_dict() for c in su.candidates if c.detector in on],
        "no_trades": su.no_trades[-300:], "transitions": [_asdict(t) for t in su.transitions[-300:]],
        "htf": su.htf(now), "strategies": reg.listing(),
        "bars": [list(r) for r in visible], "bars_used": len(visible), "feed_origin": report.get("feed_origin"),
        "data_gaps": {"order_flow": "missing", "economic_calendar": "missing"},
        "overlays": overlays(sym, bars_from_rows(visible, bucket), now, report.get("feed_origin")),
        "execution_permission": "none",
    }


def freshness(last_end: int | None, now: int, bucket: int, origin: Any) -> dict[str, Any]:
    """Data-freshness label: live / delayed / historical / simulated / unavailable (never upgraded)."""
    o = str(origin or "unknown").lower()
    if last_end is None:
        label = "unavailable"
    elif any(k in o for k in ("fixture", "synthetic", "simulat")):
        label = "simulated"
    elif now - last_end <= min(2 * bucket, 3600):
        # capped: a daily/4h bar that closed many hours ago (e.g. Friday's close read on Saturday) is not "live"
        label = "live"
    elif now - last_end <= 86400:
        label = "delayed"
    else:
        label = "historical"
    return {"label": label, "last_bar_end": last_end, "age_s": None if last_end is None else now - last_end,
            "source": str(origin or "unknown"), "computed_at": now}


def _feed_1m(sym: str, now: int) -> list:
    from atlas.features.price_action.bars import Bar
    try:
        from atlas.feeds.feed import get_feed
        rows = list(get_feed().bars(sym, "1m"))
    except Exception:  # noqa: BLE001 - feed unavailable -> insufficient, never fabricated
        return []
    out, last = [], None
    for b in rows:
        t = int(b.event_time)
        if (last is not None and t <= last) or t + 60 > now:
            continue
        try:
            out.append(Bar(t, 60, b.open, b.high, b.low, b.close, b.volume or 0.0))
        except ValueError:
            continue
        last = t
    return out


def overlays(sym: str, bars: list, now: int, origin: Any) -> dict[str, Any]:
    """Indicator, structure and (gold-only) session overlays computed from the same confirmed bars as the chart."""
    from atlas.features.price_action.gold_models import session_day_ranges
    from atlas.features.price_action.library import donchian_batch, sma_batch, trend_band_batch
    from atlas.features.price_action.structure import analyze_structure

    if not bars:
        return {"freshness": freshness(None, now, 0, origin), "series": {}, "structure": [], "gold_sessions": {"status": "INSUFFICIENT_DATA"}}
    bucket = bars[0].duration
    T = [b.start for b in bars]; H = [b.high for b in bars]; L = [b.low for b in bars]; C = [b.close for b in bars]
    ser = lambda vals: [[t, round(v, 6)] for t, v in zip(T, vals) if v is not None]
    tb = trend_band_batch(H, L, C, 20, 1.0); dc = donchian_batch(H, L, 20)
    series = {
        "sma50": ser(sma_batch(C, 50)), "sma200": ser(sma_batch(C, 200)),
        "trend_upper": ser([x[0] if x else None for x in tb]), "trend_lower": ser([x[2] if x else None for x in tb]),
        "donchian_upper": ser([x[0] if x and x[0] is not None else None for x in dc]),
        "donchian_lower": ser([x[1] if x and x[1] is not None else None for x in dc]),
    }
    structure = [e.to_dict() for e in analyze_structure(bars, sym)][-300:]
    gold: dict[str, Any] = {"status": "NOT_APPLICABLE", "reason": "gold-only model"}
    if is_gold(sym):
        b1 = _feed_1m(sym, now)   # real ATLAS feed 1m only; synthetic projections are never used for session boxes
        if not b1:
            gold = {"status": "INSUFFICIENT_DATA", "reason": "no 1m bars in the ATLAS feed"}
        else:
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            ny = ZoneInfo("America/New_York")
            last = datetime.fromtimestamp(b1[-1].end, ny).date()
            days = []
            for k in range(5, -1, -1):
                d = last - timedelta(days=k)
                r = session_day_ranges(sym, b1, datetime(d.year, d.month, d.day, tzinfo=ny), now)
                days.append({"day": str(d), **{w: r.get(w) for w in ("asian", "early", "premarket_orb", "opening_orb")},
                             "orb_alignment": r.get("orb_alignment"), "insufficient": r.get("insufficient")})
            gold = {"status": "OK", "timeframe": 60, "days": days,
                    "gap_policy": "asian<=10% missing, early<=5% missing, ORB windows strict; gaps reported, never filled",
                    "freshness": freshness(b1[-1].end, now, 60, "atlas_feed 1m")}
    return {"freshness": freshness(bars[-1].end, now, bucket, origin), "series": series, "structure": structure,
            "gold_sessions": gold, "provenance": "ATLAS confirmed bars; indicators computed server-side (features/price_action/library.py)"}
