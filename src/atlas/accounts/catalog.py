"""The connectors library, defined in code. Seeded from docs-research/integration_loop.md (free tiers, paper / practice only).

Each entry: id, name, category (loop stage), docs link, fields (with the env var each maps to), free-tier note and a
``test`` function. Tests are read-only: they never place an order, change an account or (except Healthchecks.io, which is a
single ping to the user's own check) send anything. Secrets are scrubbed from every message that leaves a test.
"""
from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlparse

from atlas.risk.safety import LiveTradingForbidden

from . import safety
from .http import HttpFn, HttpResult, fetch

# (category id, wizard step title, loop stage label)
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("broker_paper", "Paper brokers", "6 · Paper execution (also carries data)"),
    ("market_data", "Market data", "1 · Data / feed"),
    ("macro_filings", "Macro & filings", "2 · Context"),
    ("alerts", "Alerts", "Ops · Alerts"),
    ("monitoring", "Monitoring", "Ops · Monitoring"),
)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    env: str
    secret: bool = True
    required: bool = True
    placeholder: str = ""
    help: str = ""
    default: str = ""
    choices: tuple[str, ...] = ()
    pattern: str = ""          # full-match regex; "" = free text
    max_len: int = 400

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "env": self.env, "secret": self.secret, "required": self.required,
                "placeholder": self.placeholder, "help": self.help, "default": self.default, "choices": list(self.choices)}


@dataclass
class TestContext:
    http: HttpFn = fetch
    is_owner: bool = False
    resolve: Callable = socket.getaddrinfo
    connect: Callable = socket.create_connection


@dataclass
class TestResult:
    ok: bool
    detail: str
    state: str = ""            # "" -> ok / failed from ``ok``; "format_only" = saved and well-formed but not verified live


TestFn = Callable[[dict[str, str], TestContext], TestResult]


@dataclass(frozen=True)
class ConnectorSpec:
    id: str
    name: str
    category: str
    docs_url: str
    signup_url: str
    free_tier: str
    fields: tuple[FieldSpec, ...]
    test: TestFn
    mode: str = "data_only"                      # paper | practice | data_only | alerts | monitoring
    constants: tuple[tuple[str, str], ...] = ()   # env vars always set for this connector (e.g. OANDA_ENV=practice)
    safety_note: str = ""
    owner_only_test: bool = False
    loop_use: str = ""

    def field(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    def public(self) -> dict[str, Any]:
        cat = next((c for c in CATEGORIES if c[0] == self.category), None)
        return {"id": self.id, "name": self.name, "category": self.category, "stage": cat[2] if cat else "", "docs_url": self.docs_url,
                "signup_url": self.signup_url, "free_tier": self.free_tier, "mode": self.mode, "safety_note": self.safety_note,
                "loop_use": self.loop_use, "fields": [f.public() for f in self.fields], "env_names": [f.env for f in self.fields]}


# ---------------- helpers ----------------
def _scrub(msg: str, values: dict[str, str]) -> str:
    for v in values.values():
        if v and len(v) >= 4:
            msg = msg.replace(v, "***").replace(quote(v, safe=""), "***")
    return msg[:200]


def _guard(fn: TestFn, spec_values_secret: bool = True) -> TestFn:
    def run(values: dict[str, str], ctx: TestContext) -> TestResult:
        try:
            return fn(values, ctx)
        except LiveTradingForbidden as ex:
            return TestResult(False, str(ex)[:200])
        except Exception as ex:  # noqa: BLE001 - network / parse: never echo headers or keys
            return TestResult(False, _scrub(f"{type(ex).__name__}: {ex}", values))
    return run


def _http_status(r: HttpResult, ok_codes=(200,), what: str = "request") -> TestResult | None:
    if r.status in ok_codes:
        return None
    hint = {401: "key rejected (401)", 403: "key rejected or not permitted (403)", 404: "not found (404)", 429: "rate limited (429): try later"}.get(r.status)
    return TestResult(False, f"{what} failed: {hint or 'HTTP ' + str(r.status)}")


# ---------------- tests ----------------
def _t_alpaca(v, ctx):
    from atlas.execution.adapters.guards import guard_alpaca_account, guard_alpaca_url
    base = guard_alpaca_url("https://paper-api.alpaca.markets")
    r = ctx.http("GET", base + "/v2/account", headers={"APCA-API-KEY-ID": v["key_id"], "APCA-API-SECRET-KEY": v["secret_key"]})
    bad = _http_status(r, what="Alpaca paper account")
    if bad:
        return bad
    guard_alpaca_account(r.json or {})
    return TestResult(True, f"paper account {str((r.json or {}).get('account_number'))[:2]}… status {(r.json or {}).get('status', 'ok')}")


def _t_oanda(v, ctx):
    r = ctx.http("GET", f"https://api-fxpractice.oanda.com/v3/accounts/{quote(v['account_id'], safe='')}/summary",
                 headers={"Authorization": "Bearer " + v["api_token"]})
    bad = _http_status(r, what="OANDA practice account")
    return bad or TestResult(True, "practice account summary OK")


def _t_ibkr(v, ctx):
    if not ctx.is_owner:
        return TestResult(False, "IB Gateway runs on the machine that hosts ATLAS, so only the owner of this server can test it")
    from atlas.execution.adapters.guards import guard_ibkr_account, guard_ibkr_port
    guard_ibkr_account(v["account_id"]); guard_ibkr_port(int(v["port"]))
    if not safety.is_loopback_host(v["host"]):
        return TestResult(False, "IB Gateway host must be this machine (127.0.0.1 / localhost)")
    try:
        ctx.connect((v["host"], int(v["port"])), timeout=3).close()
    except OSError:
        return TestResult(False, f"nothing is listening on {v['host']}:{v['port']} (start IB Gateway in paper mode)")
    return TestResult(True, f"IB Gateway paper port {v['port']} is accepting connections")


def _simple_get(url_fn, what, headers_fn=None, params_fn=None, check=None):
    def t(v, ctx):
        r = ctx.http("GET", url_fn(v), headers=headers_fn(v) if headers_fn else None, params=params_fn(v) if params_fn else None)
        bad = _http_status(r, what=what)
        if bad:
            return bad
        if check and not check(r):
            return TestResult(False, f"{what}: unexpected response")
        return TestResult(True, f"{what} OK")
    return t


_t_tiingo = _simple_get(lambda v: "https://api.tiingo.com/api/test", "Tiingo", lambda v: {"Authorization": "Token " + v["api_key"]})
_t_finnhub = _simple_get(lambda v: "https://finnhub.io/api/v1/quote", "Finnhub", lambda v: {"X-Finnhub-Token": v["api_key"]},
                         lambda v: {"symbol": "AAPL"}, lambda r: isinstance(r.json, dict) and "c" in r.json)
_t_twelve = _simple_get(lambda v: "https://api.twelvedata.com/api_usage", "Twelve Data", lambda v: {"Authorization": "apikey " + v["api_key"]},
                        check=lambda r: isinstance(r.json, dict) and r.json.get("status") != "error" and "code" not in r.json)
_t_av = _simple_get(lambda v: "https://www.alphavantage.co/query", "Alpha Vantage", None,
                    lambda v: {"function": "SYMBOL_SEARCH", "keywords": "ibm", "apikey": v["api_key"]},
                    lambda r: isinstance(r.json, dict) and "bestMatches" in r.json)
_t_fmp = _simple_get(lambda v: "https://financialmodelingprep.com/stable/profile", "Financial Modeling Prep", None,
                     lambda v: {"symbol": "AAPL", "apikey": v["api_key"]}, lambda r: isinstance(r.json, list) and bool(r.json))
_t_massive = _simple_get(lambda v: "https://api.massive.com/v3/reference/tickers", "Massive", None,
                         lambda v: {"limit": "1", "apiKey": v["api_key"]}, lambda r: isinstance(r.json, dict) and r.json.get("status") in ("OK", "DELAYED"))
_t_gecko = _simple_get(lambda v: "https://api.coingecko.com/api/v3/ping", "CoinGecko", lambda v: {"x-cg-demo-api-key": v["demo_key"]})
_t_fred = _simple_get(lambda v: "https://api.stlouisfed.org/fred/series", "FRED", None,
                      lambda v: {"series_id": "GDP", "api_key": v["api_key"], "file_type": "json"}, lambda r: isinstance(r.json, dict) and "seriess" in r.json)


def _t_bls(v, ctx):
    r = ctx.http("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", headers={"Content-Type": "application/json"},
                 json_body={"seriesid": ["CUUR0000SA0"], "startyear": "2024", "endyear": "2024", "registrationkey": v["api_key"]})
    bad = _http_status(r, what="BLS")
    if bad:
        return bad
    st = (r.json or {}).get("status")
    if st != "REQUEST_SUCCEEDED":
        return TestResult(False, "BLS: " + str((r.json or {}).get("message", ["request not accepted"])[:1])[:150])
    return TestResult(True, "BLS v2 query OK")


def _t_edgar(v, ctx):
    from atlas.marketdata.sec_edgar import validate_sec_user_agent
    try:
        ua = validate_sec_user_agent(v["user_agent"])
    except ValueError:
        return TestResult(False, "needs a descriptive User-Agent with a contact email, e.g. 'ATLAS Research you@example.com'")
    r = ctx.http("GET", "https://data.sec.gov/submissions/CIK0000320193.json", headers={"User-Agent": ua, "Accept": "application/json"})
    bad = _http_status(r, what="SEC EDGAR")
    return bad or TestResult(True, "submissions endpoint OK (Apple CIK 320193)")


def _t_telegram(v, ctx):
    r = ctx.http("GET", f"https://api.telegram.org/bot{v['bot_token']}/getMe")
    bad = _http_status(r, what="Telegram getMe")
    if bad:
        return bad
    if not (r.json or {}).get("ok"):
        return TestResult(False, "Telegram rejected the bot token")
    return TestResult(True, "bot token valid (no message sent)")


def _t_discord(v, ctx):
    r = ctx.http("GET", v["webhook_url"])
    bad = _http_status(r, what="Discord webhook")
    return bad or TestResult(True, "webhook exists (no message sent)")


def _t_ntfy(v, ctx):
    server = (v.get("server_url") or "https://ntfy.sh").rstrip("/")
    safety.assert_public_https(server, ctx.resolve)
    r = ctx.http("GET", f"{server}/{quote(v['topic'], safe='')}/json", params={"poll": "1", "since": "1m"})
    bad = _http_status(r, what="ntfy")
    return bad or TestResult(True, "ntfy server reachable, topic readable (nothing published)")


def _t_healthchecks(v, ctx):
    r = ctx.http("GET", v["ping_url"])
    bad = _http_status(r, what="Healthchecks.io ping")
    return bad or TestResult(True, "one ping sent to your check")


def _t_sentry(v, ctx):
    return TestResult(True, "DSN format is valid. Not verified live (Sentry has no read-only probe; no event sent)", state="format_only")


# ---------------- validators ----------------
def _hostname_in(url: str, hosts: tuple[str, ...]) -> bool:
    h = urlparse(url).hostname or ""
    return urlparse(url).scheme == "https" and any(h == x or h.endswith("." + x) for x in hosts)


def validate_values(spec: ConnectorSpec, values: dict[str, str]) -> dict[str, str]:
    """Per-field shape checks plus the paper-only rules. Returns cleaned values or raises ``safety.SafetyRefusal`` / ``ValueError``."""
    out: dict[str, str] = {}
    for f in spec.fields:
        v = (values.get(f.name) or "").strip()
        if not v and f.default:
            v = f.default
        if f.required and not v:
            raise ValueError(f"{f.label} is required")
        if not v:
            continue
        if len(v) > f.max_len or any(c in v for c in "\r\n\x00"):
            raise ValueError(f"{f.label} is not valid")
        if f.choices and v not in f.choices:
            raise ValueError(f"{f.label} must be one of {', '.join(f.choices)}")
        if f.pattern and not re.fullmatch(f.pattern, v):
            raise ValueError(f"{f.label} does not look right")
        out[f.name] = v
    safety.refuse_live_strings(out)
    if spec.id == "alpaca" and out["key_id"].upper().startswith("AK"):
        raise safety.SafetyRefusal("refused: this looks like a LIVE Alpaca key (AK…). Use the paper key (PK…)")
    if spec.id == "oanda" and not out["account_id"].startswith("101-"):
        raise safety.SafetyRefusal("refused: OANDA practice account ids start with 101-. This looks like a live account")
    if spec.id == "ibkr":
        from atlas.execution.adapters.guards import guard_ibkr_account, guard_ibkr_port
        guard_ibkr_account(out["account_id"]); guard_ibkr_port(int(out["port"]))
        if not safety.is_loopback_host(out["host"]):
            raise safety.SafetyRefusal("refused: IB Gateway must run on this machine (127.0.0.1)")
    if spec.id == "sec_edgar":
        from atlas.marketdata.sec_edgar import validate_sec_user_agent
        validate_sec_user_agent(out["user_agent"])
    if spec.id == "discord" and not _hostname_in(out["webhook_url"], ("discord.com", "discordapp.com")):
        raise ValueError("Discord webhook URL must be https://discord.com/api/webhooks/…")
    if spec.id == "healthchecks" and not _hostname_in(out["ping_url"], ("hc-ping.com",)):
        raise ValueError("Healthchecks ping URL must be https://hc-ping.com/…")
    if spec.id == "ntfy" and out.get("server_url"):
        safety.assert_public_https(out["server_url"])
    return out


def _f(name, label, env, **kw):
    return FieldSpec(name, label, env, **kw)


_KEY = lambda env, label="API key", **kw: _f("api_key", label, env, placeholder="paste your key", **kw)  # noqa: E731

CATALOG: tuple[ConnectorSpec, ...] = (
    ConnectorSpec("alpaca", "Alpaca (paper)", "broker_paper", "https://docs.alpaca.markets/docs/about-market-data-api", "https://app.alpaca.markets/paper/dashboard/overview",
                  "Optional (not offered to Canadian residents). Free paper account, IEX data free (single venue); SIP is paid and not offered here. 200 req/min.",
                  (_f("key_id", "Paper key ID", "ALPACA_API_KEY_ID", placeholder="PK…", pattern=r"[A-Za-z0-9]{12,40}"),
                   _f("secret_key", "Paper secret key", "ALPACA_API_SECRET_KEY", pattern=r"[A-Za-z0-9/+=_\-]{20,80}"),
                   _f("data_feed", "Data feed", "ALPACA_DATA_FEED", secret=False, required=False, default="iex", choices=("iex",))),
                  _guard(_t_alpaca), "paper", (("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),),
                  "Paper only. The live endpoint, live (AK…) keys and non-PA accounts are refused.", loop_use="equities + crypto bars; paper fills (optional; Massive is the default stock source)"),
    ConnectorSpec("oanda", "OANDA (practice)", "broker_paper", "https://developer.oanda.com/rest-live-v20/introduction/", "https://www.oanda.com/demo-account/tpa/personal_token",
                  "Free practice (demo) account and token.",
                  (_f("api_token", "Practice API token", "OANDA_API_TOKEN", pattern=r"[A-Za-z0-9\-]{20,120}"),
                   _f("account_id", "Practice account id", "OANDA_ACCOUNT_ID", secret=False, placeholder="101-001-1234567-001", pattern=r"[0-9\-]{10,30}")),
                  _guard(_t_oanda), "practice", (("OANDA_ENV", "practice"),),
                  "Practice only (api-fxpractice). Live hosts and live (001-…) account ids are refused.", loop_use="FX bars + practice fills"),
    ConnectorSpec("ibkr", "Interactive Brokers (paper)", "broker_paper", "https://www.interactivebrokers.com/en/trading/ib-api.php", "https://www.interactivebrokers.com/en/trading/free-trial.php",
                  "Free paper account. Needs IB Gateway or TWS running locally in paper mode.",
                  (_f("host", "Gateway host", "IBKR_HOST", secret=False, default="127.0.0.1", pattern=r"[A-Za-z0-9.\-]{1,100}"),
                   _f("port", "Paper port", "IBKR_PORT", secret=False, default="4002", choices=("4002", "7497")),
                   _f("account_id", "Paper account (DU…)", "IBKR_ACCOUNT_ID", secret=False, placeholder="DU1234567", pattern=r"[Dd][Uu][0-9]{4,12}")),
                  _guard(_t_ibkr), "paper", (), "Paper ports 4002 / 7497 and DU… accounts only. Live ports 4001 / 7496 are refused. Owner-only test (local gateway).",
                  owner_only_test=True, loop_use="optional last-choice paper venue"),
    ConnectorSpec("tiingo", "Tiingo", "market_data", "https://www.tiingo.com/documentation/general/overview", "https://www.tiingo.com/account/api/token",
                  "Starter $0: 500 unique symbols/mo, 50 req/h, 1,000 req/day. Licence is internal use only.", (_KEY("TIINGO_API_KEY", "API token"),),
                  _guard(_t_tiingo), loop_use="deep history + IEX failover"),
    ConnectorSpec("finnhub", "Finnhub", "market_data", "https://finnhub.io/docs/api", "https://finnhub.io/dashboard",
                  "Free key: quotes, company news, filings list, earnings calendar (about 60 calls/min; candles are premium).", (_KEY("FINNHUB_API_KEY"),),
                  _guard(_t_finnhub), loop_use="quotes + company news"),
    ConnectorSpec("twelvedata", "Twelve Data", "market_data", "https://twelvedata.com/docs", "https://twelvedata.com/account/api-keys",
                  "Basic $0: 8 req/min, 800/day. Internal non-display use only.", (_KEY("TWELVEDATA_API_KEY"),), _guard(_t_twelve), loop_use="failover bars (equity/FX/crypto)"),
    ConnectorSpec("alphavantage", "Alpha Vantage", "market_data", "https://www.alphavantage.co/documentation/", "https://www.alphavantage.co/support/#api-key",
                  "25 requests/day free. A test uses one of them.", (_KEY("ALPHAVANTAGE_API_KEY"),), _guard(_t_av), loop_use="last-resort EOD / FX"),
    ConnectorSpec("fmp", "Financial Modeling Prep", "market_data", "https://site.financialmodelingprep.com/developer/docs", "https://site.financialmodelingprep.com/developer/docs/dashboard",
                  "Basic free: 250 calls/day. Display / redistribution needs a separate agreement.", (_KEY("FMP_API_KEY"),), _guard(_t_fmp), loop_use="fundamentals / EOD cross-check"),
    ConnectorSpec("massive", "Massive (ex-Polygon)", "market_data", "https://massive.com/docs", "https://massive.com/dashboard/keys",
                  "Recommended default stock/ETF source (email signup, works from Canada). Free plan: end-of-day daily bars, 5 calls/min, 2 years, personal use.", (_KEY("POLYGON_API_KEY"),), _guard(_t_massive), loop_use="US stock/ETF daily bars (default primary)"),
    ConnectorSpec("coingecko", "CoinGecko (demo)", "market_data", "https://docs.coingecko.com/", "https://www.coingecko.com/en/api/pricing",
                  "Demo plan: 100 calls/min, 10,000/month. Attribution ('Data provided by CoinGecko') required.",
                  (_f("demo_key", "Demo API key", "COINGECKO_DEMO_KEY", placeholder="CG-…"),), _guard(_t_gecko), loop_use="crypto reference price (not bars)"),
    ConnectorSpec("fred", "FRED", "macro_filings", "https://fred.stlouisfed.org/docs/api/fred/", "https://fredaccount.stlouisfed.org/apikeys",
                  "Free key, up to 120 req/min. Some series are copyrighted.", (_KEY("FRED_API_KEY", pattern=r"[a-z0-9]{32}"),),
                  _guard(_t_fred), loop_use="macro series + release dates"),
    ConnectorSpec("bls", "BLS Public Data API", "macro_filings", "https://www.bls.gov/developers/api_faqs.htm", "https://data.bls.gov/registrationEngine/",
                  "Registered v2 key: 500 queries/day, 50 series/query. Public US-government data.", (_KEY("BLS_API_KEY", "Registration key"),), _guard(_t_bls),
                  loop_use="CPI / jobs primary source"),
    ConnectorSpec("sec_edgar", "SEC EDGAR", "macro_filings", "https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data", "https://www.sec.gov/os/accessing-edgar-data",
                  "No key. 10 requests/s max; a descriptive User-Agent with a contact email is required.",
                  (_f("user_agent", "User-Agent (name + email)", "ATLAS_SEC_USER_AGENT", secret=False, placeholder="ATLAS Research you@example.com", max_len=120),),
                  _guard(_t_edgar), loop_use="8-K / 10-Q / 10-K / Form 4"),
    ConnectorSpec("telegram", "Telegram bot", "alerts", "https://core.telegram.org/bots#how-do-i-create-a-bot", "https://t.me/BotFather",
                  "Free. About 1 message/s per chat. Alerts stay off until ATLAS_ALERTS_ENABLED is on.",
                  (_f("bot_token", "Bot token", "TELEGRAM_BOT_TOKEN", placeholder="123456:ABC…", pattern=r"[0-9]{6,12}:[A-Za-z0-9_\-]{20,60}"),
                   _f("chat_id", "Chat id", "TELEGRAM_CHAT_ID", secret=False, placeholder="123456789", pattern=r"-?[0-9]{5,20}")),
                  _guard(_t_telegram), "alerts", loop_use="first-choice alert channel"),
    ConnectorSpec("discord", "Discord webhook", "alerts", "https://support.discord.com/hc/en-us/articles/228383668", "https://support.discord.com/hc/en-us/articles/228383668",
                  "Free. Per-route rate limits; 429 with Retry-After.",
                  (_f("webhook_url", "Webhook URL", "DISCORD_WEBHOOK_URL", placeholder="https://discord.com/api/webhooks/…"),), _guard(_t_discord), "alerts", loop_use="second alert channel"),
    ConnectorSpec("ntfy", "ntfy", "alerts", "https://docs.ntfy.sh/", "https://ntfy.sh/",
                  "Free, no signup. Public topics are unauthenticated: use a long random topic or self-host.",
                  (_f("server_url", "Server", "NTFY_URL", secret=False, required=False, default="https://ntfy.sh", placeholder="https://ntfy.sh"),
                   _f("topic", "Topic (treat as a secret)", "NTFY_TOPIC", pattern=r"[A-Za-z0-9_\-]{8,64}", placeholder="a-long-random-topic")),
                  _guard(_t_ntfy), "alerts", loop_use="push alerts to your phone"),
    ConnectorSpec("healthchecks", "Healthchecks.io", "monitoring", "https://healthchecks.io/docs/", "https://healthchecks.io/",
                  "Hobbyist $0: 20 checks. Dead-man switch: alerts you when ATLAS stops pinging. A test sends one ping.",
                  (_f("ping_url", "Ping URL", "HEALTHCHECKS_PING_URL", placeholder="https://hc-ping.com/…"),), _guard(_t_healthchecks), "monitoring", loop_use="heartbeat / dead-man switch"),
    ConnectorSpec("sentry", "Sentry", "monitoring", "https://docs.sentry.io/concepts/key-terms/dsn-explainer/", "https://sentry.io/signup/",
                  "Developer $0: about 5,000 errors/month, 1 user. Plan terms change: re-check before relying.",
                  (_f("dsn", "DSN", "SENTRY_DSN", placeholder="https://<key>@o0.ingest.sentry.io/0",
                      pattern=r"https://[A-Za-z0-9]{16,64}@[A-Za-z0-9.\-]+/[0-9]+"),), _guard(_t_sentry), "monitoring", loop_use="exception tracking"),
)
BY_ID: dict[str, ConnectorSpec] = {c.id: c for c in CATALOG}
assert len(BY_ID) == len(CATALOG)
