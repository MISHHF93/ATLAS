"""/api/ext/*: seven-repo extension surfaces (options greeks/IV, VaR, DCF, EDGAR fundamentals, VWAP/volume profile,
S/R zones, watchlist scan, Pine v5 export + ATLAS backtest, dossier/conviction, personas + PM matrix, agent pipeline,
Alpaca PAPER broker, alerts status/preview, MCP-style tool registry). Research-only (execution_permission none) except
the Alpaca paper actions, which go through the control plane and only run when the owner configured paper keys."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from atlas.api.feeds_api import _feed
from atlas.ext import EXECUTION_PERMISSION, alerts, dcf, dossier, edgar, options, personas, pine, pricevol, var
from atlas.intel.data import TF_SECONDS, freshness_for, load_bars

router = APIRouter()


def _bars(sym: str, tf: str):
    if tf not in TF_SECONDS:
        raise HTTPException(400, "unsupported_timeframe")
    return load_bars(_feed(), sym.upper(), tf)


def _engine():
    from atlas.api.app import control_engine
    return control_engine


def _w(bars, body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "freshness": freshness_for(bars), "execution_permission": EXECUTION_PERMISSION}


def _bad(e: Exception):
    raise HTTPException(400, str(e))


@router.get("/options/greeks")
def greeks(spot: float, strike: float, tte_years: float, vol: float, r: float = 0.0, q: float = 0.0, right: str = "call") -> dict[str, Any]:
    try:
        return {"price": options.price(spot, strike, tte_years, vol, r, right, q), "greeks": options.greeks(spot, strike, tte_years, vol, r, right, q),
                "model": "Black-Scholes-Merton (European)", "execution_permission": EXECUTION_PERMISSION}
    except ValueError as e:
        _bad(e)


@router.get("/options/iv")
def iv(price: float, spot: float, strike: float, tte_years: float, r: float = 0.0, q: float = 0.0, right: str = "call") -> dict[str, Any]:
    try:
        v = options.implied_vol(price, spot, strike, tte_years, r, right, q)
    except ValueError as e:
        _bad(e)
    return {"implied_vol": v, "status": "ok" if v is not None else "no_solution", "execution_permission": EXECUTION_PERMISSION}


@router.get("/options/chain")
def chain(symbol: str = Query(min_length=1)) -> dict[str, Any]:
    return options.options_chain(symbol)


@router.get("/var")
def var_ep(symbol: str = Query("BTCUSDT"), tf: str = Query("1d")) -> dict[str, Any]:
    b = _bars(symbol, tf)
    rets = [b[i].close / b[i - 1].close - 1 for i in range(1, len(b)) if b[i - 1].close]
    return _w(b, {"symbol": symbol.upper(), "tf": tf, "observations": len(rets), "report": var.var_report(rets) if len(rets) >= 20 else None,
                  "status": "ok" if len(rets) >= 20 else "insufficient_data", "units": "fraction of position value per bar"})


class DCFIn(BaseModel):
    method: str = Field("FCFF", pattern="^(FCFF|FCFE)$")
    base_cash_flow: float
    growth: list[float] = Field(min_length=1, max_length=20)
    discount_rate: float
    terminal_growth: float = 0.02
    net_debt: float = 0.0
    shares_outstanding: float | None = None
    mid_year: bool = False


@router.post("/dcf")
def dcf_ep(body: DCFIn) -> dict[str, Any]:
    i = dcf.DCFInputs(body.base_cash_flow, tuple(body.growth), body.discount_rate, body.terminal_growth, body.net_debt, body.shares_outstanding, body.mid_year)
    try:
        res = (dcf.dcf_fcff if body.method == "FCFF" else dcf.dcf_fcfe)(i)
        sens = dcf.sensitivity(i, body.method)
    except ValueError as e:
        _bad(e)
    return {"result": res.to_dict(), "sensitivity": sens, "note": "model output from owner inputs; not a price target",
            "execution_permission": EXECUTION_PERMISSION}


@router.get("/fundamentals")
def fundamentals_ep(ticker: str = Query(min_length=1, max_length=10), as_of: str | None = None, price: float | None = None) -> dict[str, Any]:
    f = edgar.fundamentals(ticker, as_of)
    return {**f, "metrics": edgar.derived_metrics(f, price) if f.get("status") == "ok" else {}, "execution_permission": EXECUTION_PERMISSION}


@router.get("/vwap")
def vwap_ep(symbol: str = Query("BTCUSDT"), tf: str = Query("15m"), anchor_ts: int | None = None, bins: int = Query(40, ge=5, le=200)) -> dict[str, Any]:
    b = _bars(symbol, tf)[-500:]
    sv = pricevol.session_vwap(b)
    av = pricevol.anchored_vwap(b, anchor_ts) if anchor_ts else None
    return _w(b, {"symbol": symbol.upper(), "tf": tf, "session_vwap": sv[-1] if sv else None, "anchored_vwap": (av or [None])[-1],
                  "anchor_ts": anchor_ts, "profile": pricevol.volume_profile(b, bins), "last_close": b[-1].close if b else None})


@router.get("/sr")
def sr_ep(symbol: str = Query("BTCUSDT"), tf: str = Query("1d"), min_touches: int = Query(3, ge=2, le=10)) -> dict[str, Any]:
    b = _bars(symbol, tf)
    z = pricevol.sr_zones(b, symbol.upper(), min_touches=min_touches) if len(b) >= 30 else []
    return _w(b, {"symbol": symbol.upper(), "tf": tf, "zones": [x.to_dict() for x in z], "rule": f">= {min_touches} swing touches within 0.5×ATR14"})


@router.get("/scan")
def scan_ep(symbols: str = Query("BTCUSDT,ETHUSDT,GC,ES"), tf: str = Query("15m")) -> dict[str, Any]:
    out = []
    for s in [x.strip().upper() for x in symbols.split(",") if x.strip()][:20]:
        b, d = _bars(s, tf), _bars(s, "1d")
        out.append({**pricevol.scan_symbol(s, b[-300:], d), "freshness": freshness_for(b)})
    return {"tf": tf, "results": out, "execution_permission": EXECUTION_PERMISSION}


@router.get("/pine")
def pine_list() -> dict[str, Any]:
    return {"strategies": pine.supported(), "note": "Pine v5 text export only; ATLAS has no TradingView connection and does not run Pine"}


@router.get("/pine/{sid}")
def pine_gen(sid: str, symbol: str = Query("BTCUSDT"), tf: str = Query("15m")) -> dict[str, Any]:
    if sid not in pine.supported():
        raise HTTPException(404, "unknown_strategy")
    src = pine.generate(sid)
    b = _bars(symbol, tf)
    return _w(b, {"strategy_id": sid, "pine": src, "lint": pine.lint(src), "atlas_backtest": pine.atlas_backtest(symbol.upper(), b, sid)})


def _dossier(symbol: str, tf: str, with_fundamentals: bool):
    d, intra = _bars(symbol, "1d"), _bars(symbol, tf)
    f = m = None
    if with_fundamentals:
        f = edgar.fundamentals(symbol)
        m = edgar.derived_metrics(f, d[-1].close if d else None) if f.get("status") == "ok" else None
    return d, dossier.build_dossier(symbol, d, intra, f, m)


@router.get("/dossier")
def dossier_ep(symbol: str = Query("BTCUSDT"), tf: str = Query("15m"), fundamentals: bool = False) -> dict[str, Any]:
    d, out = _dossier(symbol, tf, fundamentals)
    return {**out, "freshness": freshness_for(d)}


@router.get("/personas")
def personas_ep(tickers: str = Query("AAPL,MSFT"), as_of: str | None = None) -> dict[str, Any]:
    per, status = {}, {}
    for t in [x.strip().upper() for x in tickers.split(",") if x.strip()][:10]:
        f = edgar.fundamentals(t, as_of)
        status[t] = f.get("status")
        if f.get("status") != "ok":
            continue
        d = _bars(t, "1d")
        m = edgar.derived_metrics(f, d[-1].close if d else None)
        per[t] = [personas.score_persona(p, m, dossier.technicals(d)) for p in personas.PERSONAS]
    return {"fundamentals_status": status, "per_ticker": per, "portfolio_manager": personas.portfolio_manager(per) if per else None,
            "execution_permission": EXECUTION_PERMISSION}


@router.get("/pipeline")
def pipeline_ep(symbol: str = Query("BTCUSDT"), tf: str = Query("15m"), fundamentals: bool = False) -> dict[str, Any]:
    from atlas.ext.agents import run_pipeline
    d, ds = _dossier(symbol, tf, fundamentals)
    fr = freshness_for(d)
    return {**run_pipeline(ds, _engine(), data_age_ms=1e12 if fr.get("age_s") is None else float(fr["age_s"]) * 1000), "freshness": fr}


def _broker():
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    return AlpacaPaperBroker()


@router.get("/alpaca/status")
def alpaca_status() -> dict[str, Any]:
    return _broker().describe()


@router.get("/alpaca/{what}")
def alpaca_get(what: str) -> dict[str, Any]:
    b = _broker()
    if what == "reconcile":
        from atlas.ext.alpaca_reconcile import reconcile
        return reconcile(b)
    fn = {"account": b.get_account, "positions": b.get_positions, "clock": b.get_clock, "orders": b.get_orders, "fills": b.get_fills}.get(what)
    if fn is None:
        raise HTTPException(404, "unknown")
    return fn()


class OrderIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    qty: float = Field(gt=0)
    side: str = Field(pattern="^(buy|sell)$")
    reference_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float | None = None
    order_type: str = Field("market", pattern="^(market|limit)$")
    limit_price: float | None = None


@router.post("/alpaca/orders")
def alpaca_place(body: OrderIn) -> dict[str, Any]:
    try:
        return _broker().place_order(_engine(), **body.model_dump())
    except ValueError as e:
        _bad(e)


@router.delete("/alpaca/orders")
def alpaca_cancel() -> dict[str, Any]:
    return _broker().cancel_all_orders()


@router.get("/alerts/status")
def alerts_status() -> dict[str, Any]:
    return alerts.status()


@router.get("/alerts/preview")
def alerts_preview(symbol: str = Query("BTCUSDT")) -> dict[str, Any]:
    _, d = _dossier(symbol, "15m", False)
    return {"text": alerts.format_alert(d), "status": alerts.status(), "sent": False}


@router.get("/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    from atlas.ext.mcp import list_tools
    return {"tools": list_tools()}


@router.get("/mcp/resources")
def mcp_resources() -> dict[str, Any]:
    from atlas.ext.mcp import list_resources
    return {"resources": list_resources()}


class CallIn(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


@router.post("/mcp/call")
def mcp_call(body: CallIn) -> dict[str, Any]:
    from atlas.ext.mcp import call_tool
    return call_tool(body.name, body.arguments)
