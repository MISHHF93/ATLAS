"""One registry of every third-party service ATLAS can talk to, and a secret-free status report.

* ``SERVICES`` lists each service, the environment variables it reads, whether it is free, and how ATLAS uses it.
* ``status()`` reports, per service: configured (all required variables present), mode (paper / practice / sandbox /
  live-refused / data-only) and, only when ``probe=True``, whether a read-only call succeeds.
* Values are read from the process environment, then the local gitignored ``.env``. The report NEVER contains a
  value: only variable names and booleans. Probes never place, change or cancel an order and never send an alert.
* Alpaca is paper-only. A non-paper ``ALPACA_BASE_URL`` is reported as ``live_refused`` and is not contacted."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

EXECUTION_PERMISSION = "none"


@dataclass(frozen=True)
class Service:
    id: str
    title: str
    category: str                     # broker_paper | filings | macro | market_data | alerts | external_mcp | ai
    required: tuple[str, ...]         # all must be set for "configured"; empty = keyless
    optional: tuple[str, ...] = ()
    cost: str = "free"                # free | free_tier | paid | free_with_account
    signup: str = ""
    used_by: str = ""
    probe: str | None = None          # name of the read-only probe, if any
    notes: str = ""
    default_on: bool = True


SERVICES: tuple[Service, ...] = (
    Service("alpaca", "Alpaca (paper trading + market data)", "broker_paper",
            ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"), ("ALPACA_BASE_URL", "ALPACA_DATA_FEED"), "free",
            "https://app.alpaca.markets/paper/dashboard/overview", "src/atlas/ext/alpaca_paper.py, src/atlas/feeds/providers/alpaca.py",
            "alpaca", "Paper only: https://paper-api.alpaca.markets. The live endpoint and non-PA accounts are refused. IEX data is free; SIP is paid."),
    Service("sec_edgar", "SEC EDGAR (fundamentals, filings)", "filings", ("ATLAS_SEC_USER_AGENT",), (), "free",
            "https://www.sec.gov/os/accessing-edgar-data", "src/atlas/ext/edgar.py", "sec_edgar",
            "No key: a User-Agent 'AppName you@example.com' is required by SEC fair-access rules."),
    Service("fred", "FRED / ALFRED (St. Louis Fed macro, vintages)", "macro", ("FRED_API_KEY",), (), "free",
            "https://fredaccount.stlouisfed.org/apikeys", "src/atlas/feeds/providers/fred.py, src/atlas/autopilot/feeds.py", "fred"),
    Service("polygon", "Massive (formerly Polygon.io)", "market_data", ("POLYGON_API_KEY",), ("POLYGON_BASE_URL", "MASSIVE_API_KEY", "MASSIVE_BASE_URL"), "free_tier",
            "https://massive.com/dashboard/keys", "src/atlas/feeds/providers/polygon.py, src/atlas/marketdata/pit/providers/polygon.py",
            notes="Free tier: 5 calls/min, end-of-day. Accepts either POLYGON_API_KEY or MASSIVE_API_KEY; primary host api.massive.com."),
    Service("finnhub", "Finnhub (quotes, news, fundamentals)", "market_data", ("FINNHUB_API_KEY",), (), "free_tier",
            "https://finnhub.io/dashboard", "src/atlas/feeds/providers/finnhub.py, src/atlas/marketdata/pit/providers/finnhub.py"),
    Service("tiingo", "Tiingo (EOD + IEX intraday)", "market_data", ("TIINGO_API_KEY",), (), "free_tier",
            "https://www.tiingo.com/account/api/token", "src/atlas/feeds/providers/tiingo.py"),
    Service("twelvedata", "Twelve Data", "market_data", ("TWELVEDATA_API_KEY",), (), "free_tier",
            "https://twelvedata.com/account/api-keys", "src/atlas/feeds/providers/twelvedata.py"),
    Service("alphavantage", "Alpha Vantage", "market_data", ("ALPHAVANTAGE_API_KEY",), (), "free_tier",
            "https://www.alphavantage.com/support/#api-key", "src/atlas/feeds/providers/alphavantage.py, external MCP"),
    Service("fmp", "Financial Modeling Prep", "market_data", ("FMP_API_KEY",), (), "free_tier",
            "https://site.financialmodelingprep.com/developer/docs/dashboard", "src/atlas/autopilot/feeds.py"),
    Service("eodhd", "EODHD (TSX/TSXV end-of-day)", "market_data", ("EODHD_API_KEY",), (), "paid",
            "https://eodhd.com/cp/settings", "src/atlas/autopilot/feeds.py, external MCP", notes="Free plan is 20 calls/day; practical use is paid."),
    Service("databento", "Databento (futures/equities tick)", "market_data", ("DATABENTO_API_KEY", "ATLAS_DATABENTO_DATASET"), (), "paid",
            "https://databento.com/portal/keys", "src/atlas/feeds/providers/stubs.py", notes="Usage is billed; the dataset variable is an explicit opt-in."),
    Service("oanda", "OANDA (FX practice data)", "market_data", ("OANDA_API_TOKEN",), ("OANDA_ACCOUNT_ID", "OANDA_ENV"), "free_with_account",
            "https://www.oanda.com/demo-account/tpa/personal_token", "src/atlas/feeds/providers/oanda.py", notes="Use OANDA_ENV=practice."),
    Service("tradier", "Tradier (sandbox data)", "market_data", ("TRADIER_ACCESS_TOKEN",), ("TRADIER_ENV",), "free_with_account",
            "https://developer.tradier.com/user/sign_up", "src/atlas/feeds/providers/tradier.py", notes="Use TRADIER_ENV=sandbox."),
    Service("questrade", "Questrade (Canadian quotes)", "market_data", ("QUESTRADE_REFRESH_TOKEN",), (), "free_with_account",
            "https://login.questrade.com/APIAccess/UserApps.aspx", "src/atlas/feeds/providers/questrade.py",
            notes="Refresh tokens are single-use and expire after 7 days."),
    Service("ibkr", "Interactive Brokers Client Portal gateway (data)", "market_data", ("IBKR_CP_GATEWAY_URL",), (), "free_with_account",
            "https://www.interactivebrokers.com/en/trading/ib-api.php", "src/atlas/feeds/providers/stubs.py",
            notes="Local gateway URL, not a key. Use a paper (DU...) login."),
    Service("public_crypto", "Binance / Bybit / Coinbase / Kraken / OKX public data", "market_data", (), ("ATLAS_BINANCE_REST_HOSTS",), "free",
            "", "src/atlas/feeds/providers/{binance,bybit,coinbase,kraken,okx}.py", notes="Keyless public endpoints."),
    Service("solana_rpc", "Solana JSON-RPC (speculative launchpad indexing disabled by product policy)", "market_data", (), ("SOLANA_RPC_URL", "SOLANA_WS_URL"), "free",
            "https://solana.com/docs/rpc", "src/atlas/pump/indexing/__init__.py", "solana_rpc",
            notes="Disabled on active product roadmap (default_on=False); ATLAS focuses on authentic verified financial instruments.", default_on=False),
    Service("yahoo", "Yahoo Finance (unofficial, keyless)", "market_data", (), (), "free", "", "src/atlas/feeds/providers/yahoo.py",
            notes="Unofficial; may break or rate-limit."),
    Service("alerts_telegram", "Telegram alerts", "alerts", ("ATLAS_ALERTS_ENABLED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"), (), "free",
            "https://core.telegram.org/bots#how-do-i-create-a-bot", "src/atlas/ext/alerts.py", default_on=False),
    Service("alerts_discord", "Discord alerts", "alerts", ("ATLAS_ALERTS_ENABLED", "DISCORD_WEBHOOK_URL"), (), "free",
            "https://support.discord.com/hc/en-us/articles/228383668", "src/atlas/ext/alerts.py", default_on=False),
    Service("alerts_ntfy", "ntfy push alerts", "alerts", ("ATLAS_ALERTS_ENABLED", "NTFY_TOPIC"), ("NTFY_URL", "NTFY_TOKEN"), "free",
            "https://docs.ntfy.sh/", "src/atlas/ext/alerts.py", default_on=False,
            notes="Topic is the secret on the public ntfy.sh: use a long random one, or self-host and set NTFY_URL (+ NTFY_TOKEN)."),
    Service("healthchecks", "Healthchecks.io dead-man ping", "alerts", ("HEALTHCHECKS_PING_URL",), ("HEALTHCHECKS_INTERVAL_S",), "free",
            "https://healthchecks.io/", "src/atlas/ops/healthchecks.py", default_on=False,
            notes="No-op unless the ping URL is set. The core loop pings it each safety step; you are told when pings stop."),
    Service("sentry", "Sentry error reporting (Python)", "alerts", ("SENTRY_DSN",), ("SENTRY_TRACES_SAMPLE_RATE",), "free_tier",
            "https://sentry.io/", "src/atlas/ops/sentry_init.py", default_on=False,
            notes="No-op unless the DSN is set and sentry-sdk is installed. No PII, cookies or request bodies are sent."),
    Service("alerts_slack", "Slack alerts", "alerts", ("ATLAS_ALERTS_ENABLED", "SLACK_WEBHOOK_URL"), (), "free",
            "https://api.slack.com/messaging/webhooks", "src/atlas/ext/alerts.py", default_on=False),
    Service("external_mcp", "External data MCP servers (EODHD, Finnhub, Massive, TradingView, Alpha Vantage, QuantConnect)", "external_mcp",
            ("ATLAS_EXTERNAL_MCP",), ("TRADINGVIEW_TOKEN", "QUANTCONNECT_API_TOKEN"), "free_tier", "",
            "src/atlas/mcp/trading/external.py", notes="Off unless ATLAS_EXTERNAL_MCP=on; read-only allowlists, money-moving tools denied.",
            default_on=False),
    Service("gemini", "Google Gemini (assistant)", "ai", ("GEMINI_API_KEY",), ("ATLAS_GEMINI_MODEL", "ATLAS_GEMINI_DEEP_MODEL", "ATLAS_GEMINI_TIER"), "paid",
            "https://aistudio.google.com/apikey", "src/atlas/ai/gemini_provider.py"),
    Service("llm_other", "OpenAI / Anthropic / xAI (assistant, optional)", "ai", (), ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"), "paid",
            "", "src/atlas/ai/assistant/providers.py"),
)

ALL_VARS: tuple[str, ...] = tuple(dict.fromkeys(v for s in SERVICES for v in (*s.required, *s.optional)))


def load_env(env_file: str | Path = ".env", environ: dict[str, str] | None = None) -> dict[str, str]:
    from atlas.control.policy.loader import parse_env_file
    from atlas.accounts import credentials
    environ = credentials.effective_environ() if environ is None else environ
    file = parse_env_file(Path(env_file)) if credentials.owner_scope() else {}   # the host's .env is the OWNER's fallback only
    from atlas import envalias
    environ = envalias.normalized(dict(environ))
    return {k: environ.get(k) or file.get(k, "") for k in ALL_VARS}


def _is_set(env: dict[str, str], k: str) -> bool:
    v = (env.get(k) or "").strip()
    if k == "ATLAS_ALERTS_ENABLED" or k == "ATLAS_EXTERNAL_MCP":
        return v.lower() in ("true", "on", "1")
    if k == "POLYGON_API_KEY" and not v:
        v = (env.get("MASSIVE_API_KEY") or "").strip()
    return bool(v) and not v.startswith("<")


def mode_for(s: Service, env: dict[str, str]) -> str:
    if s.id == "alpaca":
        from atlas.execution.adapters.guards import guard_alpaca_url
        from atlas.risk.safety import LiveTradingForbidden
        base = (env.get("ALPACA_BASE_URL") or "https://paper-api.alpaca.markets").rstrip("/")
        base = base[:-3] if base.endswith("/v2") else base
        try:
            guard_alpaca_url(base)
            return "paper"
        except LiveTradingForbidden:
            return "live_refused"
    if s.id == "oanda":
        return "live_refused" if env.get("OANDA_ENV", "").lower() == "live" else "practice"
    if s.id == "tradier":
        return "live_refused" if env.get("TRADIER_ENV", "").lower() == "production" else "sandbox"
    if s.category == "alerts":
        return "send_enabled" if _is_set(env, "ATLAS_ALERTS_ENABLED") else "off"
    return "data_only"


# ---------- read-only probes (injectable HTTP for tests) ----------
Getter = Callable[[str, dict[str, str]], Any]


def _http_get_json(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed https hosts below
        return json.loads(r.read() or b"null")


def _scrub(msg: str, env: dict[str, str]) -> str:
    for k in ALL_VARS:
        v = env.get(k) or ""
        if len(v) >= 4:
            msg = msg.replace(v, "***")
    return msg[:200]


def probe_alpaca(env: dict[str, str], transport=None) -> dict[str, Any]:
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    b = AlpacaPaperBroker(env=env, transport=transport)
    if b.adapter is None:
        return {"reachable": None, "detail": b.status}
    a = b.get_account()
    if a["status"] != "ok":
        return {"reachable": False if a["status"] == "error" else None, "detail": a["status"]}
    c = b.get_clock()
    return {"reachable": c["status"] == "ok", "detail": "paper account + clock OK" if c["status"] == "ok" else c["status"]}


def probe_sec_edgar(env: dict[str, str], get: Getter = _http_get_json) -> dict[str, Any]:
    from atlas.marketdata.sec_edgar import validate_sec_user_agent
    try:
        ua = validate_sec_user_agent(env.get("ATLAS_SEC_USER_AGENT") or "")
    except ValueError:
        return {"reachable": None, "detail": "ATLAS_SEC_USER_AGENT missing or not 'AppName email@domain'"}
    js = get("https://data.sec.gov/submissions/CIK0000320193.json", {"User-Agent": ua, "Accept": "application/json"})
    return {"reachable": bool(js and js.get("cik")), "detail": "submissions endpoint OK (Apple CIK 320193)"}


def probe_fred(env: dict[str, str], get: Getter = _http_get_json) -> dict[str, Any]:
    q = urllib.parse.urlencode({"series_id": "GDP", "api_key": env.get("FRED_API_KEY", ""), "file_type": "json"})
    js = get(f"https://api.stlouisfed.org/fred/series?{q}", {})
    return {"reachable": bool(js and js.get("seriess")), "detail": "series metadata OK (GDP)"}


def probe_solana_rpc(env: dict[str, str], rpc_fn=None) -> dict[str, Any]:
    from atlas.pump.indexing import SolanaRPCIndexer
    url = (env.get("SOLANA_RPC_URL") or "").strip()
    if not url and rpc_fn is None:
        return {"reachable": None, "detail": "SOLANA_RPC_URL not set (simulated reference mode)"}
    indexer = SolanaRPCIndexer(rpc_url=url or "https://api.mainnet-beta.solana.com")
    slot = rpc_fn("getSlot", []) if rpc_fn is not None else indexer.rpc_call("getSlot", [])
    return {"reachable": slot is not None, "detail": f"slot={slot}" if slot is not None else "probe_failed"}


PROBES = {"alpaca": probe_alpaca, "sec_edgar": probe_sec_edgar, "fred": probe_fred, "solana_rpc": probe_solana_rpc}


def status(env: dict[str, str] | None = None, probe: bool = False, probes: dict[str, Callable[..., dict]] | None = None) -> dict[str, Any]:
    env = load_env() if env is None else env
    probes = PROBES if probes is None else probes
    rows = []
    for s in SERVICES:
        req = {k: _is_set(env, k) for k in s.required}
        opt = {k: _is_set(env, k) for k in s.optional}
        configured = all(req.values()) if s.required else (any(opt.values()) if s.category == "ai" else True)
        mode = mode_for(s, env)
        reach: dict[str, Any] = {"reachable": None, "detail": "not probed"}
        if probe and s.probe and s.probe in probes:
            if not configured:
                reach = {"reachable": None, "detail": "not configured"}
            elif mode == "live_refused":
                reach = {"reachable": None, "detail": "live endpoint refused; not contacted"}
            else:
                try:
                    reach = probes[s.probe](env)
                except Exception as ex:  # network / http / parse
                    reach = {"reachable": False, "detail": _scrub(f"{type(ex).__name__}: {ex}", env)}
        rows.append({"id": s.id, "title": s.title, "category": s.category, "cost": s.cost, "configured": configured,
                     "required_vars": req, "optional_vars": opt, "mode": mode, "reachable": reach["reachable"],
                     "detail": reach["detail"], "probe_available": s.probe is not None, "default_on": s.default_on,
                     "signup": s.signup, "notes": s.notes})
    return {"services": rows, "probed": probe, "paper_only": True, "secrets_echoed": False,
            "data_providers": data_providers(env),
            "execution_permission": EXECUTION_PERMISSION,
            "summary": {"total": len(rows), "configured": sum(r["configured"] for r in rows),
                        "live_refused": [r["id"] for r in rows if r["mode"] == "live_refused"]}}


PROVIDER_AUTH = {"alpaca": ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"), "polygon": ("POLYGON_API_KEY",), "tiingo": ("TIINGO_API_KEY",),
                 "twelvedata": ("TWELVEDATA_API_KEY",), "finnhub": ("FINNHUB_API_KEY",), "tradier": ("TRADIER_ACCESS_TOKEN",),
                 "alphavantage": ("ALPHAVANTAGE_API_KEY",), "oanda": ("OANDA_API_TOKEN",), "databento": ("DATABENTO_API_KEY",)}


def data_providers(env: dict[str, str]) -> list[dict]:
    """Bar/quote provider choice per asset class: priority order and the one in use now (first with its keys set).
    Alpaca is preferred for US equities/ETFs (IEX, keys) and crypto (keyless history); public sources are fallbacks."""
    from atlas.feeds.instruments import DEFAULT_INSTRUMENTS
    seen, out = set(), []
    for ins in DEFAULT_INSTRUMENTS.values():
        if ins.asset_class in seen:
            continue
        seen.add(ins.asset_class)
        from atlas.feeds.free_sources import allowed, describe
        allp = list(ins.provider_priority)
        pri = [p for p in allp if allowed(p, env)]
        ready = [p for p in pri if all(_is_set(env, k) for k in PROVIDER_AUTH.get(p, ()))]
        out.append({"asset_class": ins.asset_class, "example": ins.id, "priority": pri, "active": ready[0] if ready else None,
                    "fallbacks": ready[1:], "needs_keys": [p for p in pri if p not in ready],
                    "excluded": [p for p in allp if p not in pri],
                    "sources": {p: describe(p) for p in allp}})
    return out
