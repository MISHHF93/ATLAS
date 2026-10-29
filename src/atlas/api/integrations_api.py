"""/api/integrations/status: every third-party service, configured or not, reachable or not, paper or live-refused.
Never returns a secret value (names and booleans only). ``probe=true`` runs read-only calls; no order, no alert."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

router = APIRouter()


@router.get("/status")
def integrations_status(probe: bool = Query(False)) -> dict[str, Any]:
    from atlas.integrations.registry import status
    return status(probe=probe)


@router.post("/verify")
def integrations_verify(body: dict = Body(...)) -> dict[str, Any]:
    """Press Verify: ONE read-only call with the key currently entered for this service (owner .env, or the signed-in user's saved
    connector). Records needs_verification -> verified/failed. Never returns or stores a secret; no order, alert or message is sent."""
    from atlas.accounts.credentials import effective_environ
    from atlas.integrations import verify as v
    from atlas.integrations.registry import ALL_VARS, load_env
    sid = str(body.get("service") or "")[:40]
    env = load_env(environ=dict(effective_environ()))
    return v.verify(sid, env)


@router.get("/verification")
def integrations_verification() -> dict[str, Any]:
    from atlas.accounts.credentials import effective_environ
    from atlas.integrations import verify as v
    from atlas.integrations.registry import load_env
    states = v.all_states(load_env(environ=dict(effective_environ())))
    return {"states": states, "secrets_echoed": False, "execution_permission": "none"}


@router.get("/checklist")
def integrations_checklist() -> dict[str, Any]:
    """Every env var and connector, ordered by impact, with verified / needs_verification / optional. Names and booleans only."""
    from atlas.accounts.credentials import effective_environ
    from atlas.integrations import checklist as c
    from atlas.integrations.registry import load_env
    return c.build(load_env(environ=dict(effective_environ())))


@router.get("/golive-readiness")
def integrations_golive_readiness() -> dict[str, Any]:
    """READ-ONLY gates that must pass before real-money trading could even be considered. Cannot enable anything."""
    from atlas.integrations import golive
    return golive.report()


@router.get("/massive-live")
def massive_live(symbol: str = Query("SPY")) -> dict[str, Any]:
    """How fresh Massive stock data is right now (plain language) and the newest stored bar for ``symbol``. Read-only; no key echoed."""
    from atlas.accounts.credentials import effective_environ
    from atlas.feeds import massive_live as ML
    from atlas.feeds.feed import get_feed
    from atlas.integrations.registry import load_env
    env = dict(load_env(environ=dict(effective_environ())))
    return ML.status_for(get_feed(), symbol.strip().upper(), env)


@router.get("/live-predictions")
def live_predictions(symbols: str = Query("BTCUSDT,ETHUSDT,SPY,AAPL,QQQ,NVDA")) -> dict[str, Any]:
    """Directional research model on the newest closed bar, crypto on 1m and stocks on 15m, with each source's delay stated. Research only."""
    from atlas.accounts.credentials import effective_environ
    from atlas.feeds import massive_live as ML
    from atlas.feeds.feed import get_feed
    from atlas.integrations.registry import load_env
    env = dict(load_env(environ=dict(effective_environ())))
    syms = [x.strip().upper() for x in symbols.split(",") if x.strip()][:12]
    return {"status": "ok", "capability": ML.capability(env), "rows": ML.live_predictions(get_feed(), syms, env),
            "execution_permission": "none", "paper_only": True}


# ---- chart sources: Alpaca IEX bars become selectable once ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are set ----
CHART_TF = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


def chart_sources(environ: dict[str, str] | None = None) -> list[dict[str, Any]]:
    from atlas.feeds.providers.alpaca import AlpacaAdapter
    a = AlpacaAdapter(env=environ)
    feed = (a.env.get("ALPACA_DATA_FEED") or "iex").lower()
    return [{"id": "atlas", "label": "ATLAS feed (default)", "available": True, "reason": None},
            {"id": "alpaca", "label": f"Alpaca {feed.upper()} stock/ETF bars", "available": a.enabled,
             "reason": None if a.enabled else "not_configured: set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in .env, then restart"},
            {"id": "alpaca_crypto", "label": "Alpaca crypto bars (keyless)", "available": True, "reason": None}]


def alpaca_bars(symbol: str, tf: str, limit: int, crypto: bool = False, environ: dict[str, str] | None = None, transport=None, now: float | None = None) -> dict[str, Any]:
    import time
    from atlas.feeds.providers.alpaca import AlpacaAdapter, AlpacaCryptoAdapter
    if tf not in CHART_TF:
        return {"status": "error", "reason": "unknown tf", "bars": []}
    cls = AlpacaCryptoAdapter if crypto else AlpacaAdapter
    a = cls(env=environ, transport=transport) if transport else cls(env=environ)
    sym = symbol.upper().strip()
    if not a.enabled:
        return {"status": "not_configured", "source": "alpaca", "symbol": sym, "bars": [],
                "reason": "set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in .env, then restart"}
    end = int(now or time.time())
    span = CHART_TF[tf] * limit * (5 if tf == "1d" else 4)  # cover nights/weekends
    try:
        bars = a.history(sym, tf, end - span, end)[-limit:]
    except Exception as ex:  # never echo headers/keys
        return {"status": "error", "source": "alpaca", "symbol": sym, "bars": [], "reason": type(ex).__name__ + ": " + str(ex)[:200]}
    from atlas.feeds.free_sources import latency as _lat
    lat = _lat(a.name)
    return {"status": "ok", "source": a.name, "provider": a.name, "latency": lat, "feed": (a.env.get("ALPACA_DATA_FEED") or "iex"), "symbol": sym, "tf": tf,
            "execution_permission": "none",
            "bars": [{"time": b.event_time, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume,
                      "confirmed": b.confirmed, "provider": getattr(b, "provider", a.name), "latency": lat} for b in bars]}


@router.get("/chart/sources")
def api_chart_sources() -> dict[str, Any]:
    return {"sources": chart_sources()}


@router.get("/chart/bars")
def api_chart_bars(source: str = Query("alpaca"), symbol: str = Query("SPY"), tf: str = Query("15m"),
                   limit: int = Query(300, ge=10, le=2000)) -> dict[str, Any]:
    if source not in ("alpaca", "alpaca_crypto"):
        return {"status": "error", "reason": "use the ATLAS chart for the default feed", "bars": []}
    return alpaca_bars(symbol, tf, limit, crypto=source == "alpaca_crypto")
