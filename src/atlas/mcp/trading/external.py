"""External MCP CLIENT adapters (third-party data servers). Disabled by default.

Defence in depth, per the MCP security best practices (see trading-bot-review/mcp-autopilot-research.md §2):
* every server is `enabled: False` until the owner turns it on AND sets ATLAS_EXTERNAL_MCP=on;
* credentials come from env vars named in the spec (names only in code; never logged, never passed through to tools);
* per-server tool ALLOWLIST plus a global DENY pattern for anything that could trade / move money: even an allowlisted
  name matching the deny pattern is refused. This adapter has NO path to the broker, router or payments;
* tool definitions are pinned by SHA-256 (name + description + input schema) to catch "rug-pull" redefinitions;
* outputs are wrapped as untrusted data, control chars stripped and truncated; they may feed features / vetoes only;
* every call has a timeout.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from atlas.mcp.trading.autopilot_tools import untrusted

_DENY_PREFIX = ("order", "trade", "buy", "sell", "transfer", "withdraw", "deposit", "cancel", "place", "submit",
                "stake", "unstake", "convert", "swap", "send", "pay", "wallet", "margin", "leverage", "liquidat", "bridge",
                "approve", "exec", "mint", "borrow", "lend", "redeem", "deploy", "live")
_DENY_EXACT = ("fund", "funds", "funding", "sign", "close", "open", "short", "long", "move")


class _Deny:
    """Tool names are split into words (snake/kebab/camel case); any word starting with a money-moving verb is denied."""
    def search(self, name: str) -> bool:
        words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name or "")]
        return any(w.startswith(_DENY_PREFIX) or w in _DENY_EXACT for w in words)


DENY = _Deny()
MASTER_SWITCH = "ATLAS_EXTERNAL_MCP"


@dataclass(frozen=True)
class ExternalServerSpec:
    name: str
    url: str | None = None                 # Streamable HTTP endpoint
    command: tuple[str, ...] = ()          # or stdio command
    auth_env: str | None = None            # env var NAME holding the key / OAuth token
    allow: tuple[str, ...] = ()            # tools we may call (read-only data tools)
    pins: dict[str, str] = field(default_factory=dict)   # tool name -> sha256 of its definition
    enabled: bool = False
    supplies: tuple[str, ...] = ()         # feed kinds it could fill
    timeout_s: float = 15.0
    note: str = ""


DEFAULT_SERVERS: tuple[ExternalServerSpec, ...] = (
    ExternalServerSpec("eodhd", url="https://mcp.eodhd.com/v2/mcp", auth_env="EODHD_API_KEY",
                       allow=("get_eod_data", "get_intraday_data", "get_fundamentals", "get_news", "get_dividends"),
                       supplies=("bars", "fundamentals", "news"), note="TSX coverage; read-only data tools"),
    ExternalServerSpec("finnhub", url="https://mcp.finnhub.io/mcp", auth_env="FINNHUB_API_KEY",
                       allow=("quote", "company_news", "news_sentiment", "basic_financials", "earnings_calendar"),
                       supplies=("quotes", "news", "fundamentals")),
    ExternalServerSpec("massive", url="https://mcp.massive.com", auth_env="MASSIVE_API_KEY",
                       allow=("search", "query"), supplies=("bars", "quotes"), note="US equities/options/crypto aggregates"),
    ExternalServerSpec("kraken-market", command=("kraken", "mcp", "-s", "market"),
                       allow=("ticker", "ohlc", "depth", "spread"), supplies=("crypto",),
                       note="market service ONLY (-s market); trading services never enabled"),
    ExternalServerSpec("tradingview", url="https://mcp.tradingview.com/mcp", auth_env="TRADINGVIEW_TOKEN",
                       allow=("screener", "technical_summary"), supplies=("screener",)),
    ExternalServerSpec("alphavantage", url="https://mcp.alphavantage.co/mcp", auth_env="ALPHAVANTAGE_API_KEY",
                       allow=("TIME_SERIES_DAILY", "NEWS_SENTIMENT", "OVERVIEW"), supplies=("bars", "news", "fundamentals")),
    ExternalServerSpec("quantconnect", command=("quantconnect-mcp",), auth_env="QUANTCONNECT_API_TOKEN",
                       allow=("create_backtest", "read_backtest"), supplies=("backtest",),
                       note="backtests only; live-deploy tools excluded"),
)


def tool_hash(name: str, description: str | None, schema: Any) -> str:
    blob = json.dumps({"n": name, "d": description or "", "s": schema or {}}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class Session(Protocol):
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


class ExternalRefused(PermissionError):
    pass


def permitted(spec: ExternalServerSpec, tool: str) -> tuple[bool, str]:
    if DENY.search(tool):
        return False, "deny pattern (could trade or move money)"
    if tool not in spec.allow:
        return False, "not on this server's allowlist"
    return True, "ok"


class ExternalMCPClient:
    """Wraps one external MCP session. `session_factory` is injected (tests use a fake); real sessions are only
    created when the spec is enabled and the master switch is on."""

    def __init__(self, spec: ExternalServerSpec, session_factory: Callable[[], Awaitable[Session]] | None = None,
                 audit=None, env: dict[str, str] | None = None):
        self.spec, self._factory, self.audit = spec, session_factory, audit
        self.env = os.environ if env is None else env
        self._session: Session | None = None
        self.tools: dict[str, dict[str, Any]] = {}
        self.rejected: dict[str, str] = {}

    def active(self) -> tuple[bool, str]:
        if not self.spec.enabled:
            return False, "disabled in config"
        if self.env.get(MASTER_SWITCH, "off").lower() != "on":
            return False, f"{MASTER_SWITCH} is not 'on'"
        if self.spec.auth_env and not self.env.get(self.spec.auth_env):
            return False, f"env {self.spec.auth_env} not set"
        if self._factory is None:
            return False, "no transport configured"
        return True, "ok"

    def _log(self, kind: str, data: dict[str, Any]) -> None:
        if self.audit is not None:
            self.audit.append(f"external_mcp.{kind}", {"server": self.spec.name, **data}, actor="external_mcp")

    async def connect(self) -> dict[str, Any]:
        ok, why = self.active()
        if not ok:
            raise ExternalRefused(f"{self.spec.name}: {why}")
        self._session = await asyncio.wait_for(self._factory(), self.spec.timeout_s)
        listed = await asyncio.wait_for(self._session.list_tools(), self.spec.timeout_s)
        self.tools, self.rejected = {}, {}
        for t in getattr(listed, "tools", listed):
            name = getattr(t, "name", None) or t["name"]
            desc = getattr(t, "description", None) if not isinstance(t, dict) else t.get("description")
            schema = getattr(t, "inputSchema", None) if not isinstance(t, dict) else t.get("inputSchema")
            okp, reason = permitted(self.spec, name)
            if not okp:
                self.rejected[name] = reason
                continue
            h = tool_hash(name, desc, schema)
            pin = self.spec.pins.get(name)
            if pin and pin != h:
                self.rejected[name] = "definition changed since pinned (possible rug-pull); re-review before re-pinning"
                self._log("pin_mismatch", {"tool": name, "expected": pin[:12], "got": h[:12]})
                continue
            self.tools[name] = {"sha256": h, "pinned": bool(pin)}
        self._log("connected", {"allowed": sorted(self.tools), "rejected": len(self.rejected)})
        return {"allowed": self.tools, "rejected": self.rejected}

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        okp, reason = permitted(self.spec, tool)
        if not okp or tool not in self.tools or self._session is None:
            self._log("refused", {"tool": tool[:60], "reason": reason if not okp else "not connected / not verified"})
            raise ExternalRefused(f"{self.spec.name}.{tool}: {reason if not okp else 'not connected / not verified'}")
        res = await asyncio.wait_for(self._session.call_tool(tool, dict(arguments or {})), self.spec.timeout_s)
        content = getattr(res, "structuredContent", None) or getattr(res, "structured_content", None)
        if content is None:
            parts = getattr(res, "content", None) or (res if isinstance(res, list) else [res])
            content = [getattr(p, "text", p) for p in parts]
        self._log("call", {"tool": tool})
        return untrusted(f"mcp:{self.spec.name}.{tool}", content)


def catalogue(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """For the console / list_data_feeds: what each server could supply and why it is off."""
    out = []
    for s in DEFAULT_SERVERS:
        ok, why = ExternalMCPClient(s, env=env).active()
        out.append({"name": s.name, "endpoint": s.url or " ".join(s.command), "auth_env": s.auth_env, "allow": list(s.allow),
                    "supplies": list(s.supplies), "active": ok, "status": why, "note": s.note})
    return out
