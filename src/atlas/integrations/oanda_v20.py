"""OANDA v20 (fxTrade Practice) helpers shared by the feed adapter, the Verify test and the read-only account snapshot.

Official docs: https://developer.oanda.com/rest-live-v20/development-guide/ (hosts, 120 req/s, 2 new connections/s, 20 streams) and
https://developer.oanda.com/rest-live-v20/account-ep/ (GET /v3/accounts lists the accounts the token can see; practice ids look like 101-xxx-xxxxxxx-xxx).
ATLAS talks to the PRACTICE hosts only. The live hosts are refused before any request is made. GET requests only: nothing here can trade."""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

REST_HOST = "api-fxpractice.oanda.com"
STREAM_HOST = "stream-fxpractice.oanda.com"
LIVE_HOSTS = ("api-fxtrade.oanda.com", "stream-fxtrade.oanda.com")
REST = f"https://{REST_HOST}"
STREAM = f"https://{STREAM_HOST}"
PRACTICE_ID = re.compile(r"101-\d{3}-\d{4,10}-\d{3}")
INSTRUMENT = re.compile(r"[A-Za-z0-9_]{2,24}")      # path-safe OANDA instrument names: EUR_USD, XAU_USD, SPX500_USD, DE30_EUR ...
GetJson = Callable[[str, dict[str, str]], Any]


class OandaLiveRefused(RuntimeError):
    """OANDA_ENV=live (or a live account) was requested. ATLAS never contacts the live hosts."""


def refuse_live(env: Mapping[str, str]) -> None:
    if (env.get("OANDA_ENV") or "practice").strip().lower() != "practice":
        raise OandaLiveRefused("OANDA_ENV must be 'practice': the live fxTrade hosts are refused and never contacted")
    acct = (env.get("OANDA_ACCOUNT_ID") or "").strip()
    if acct and not PRACTICE_ID.fullmatch(acct):
        raise OandaLiveRefused("OANDA_ACCOUNT_ID is not a practice account id (practice ids start with 101-); refused")


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "Accept-Datetime-Format": "UNIX"}


def practice_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if PRACTICE_ID.fullmatch(i or "")]


def discover_account_ids(get_json: GetJson, token: str) -> list[str]:
    """GET /v3/accounts on the practice host -> the practice account ids this token can see (live-shaped ids are dropped, never used)."""
    js = get_json(f"{REST}/v3/accounts", auth_headers(token)) or {}
    return practice_ids([str(a.get("id", "")) for a in (js.get("accounts") or []) if isinstance(a, dict)])


def pick_account(configured: str, discovered: list[str]) -> tuple[str | None, str]:
    """(account id to use, note). A configured id wins when the token can see it; otherwise the first discovered practice account."""
    if configured:
        if discovered and configured not in discovered:
            return None, "OANDA_ACCOUNT_ID is not one of the practice accounts this token can see"
        return configured, ""
    if not discovered:
        return None, "this token sees no practice account"
    return discovered[0], ("auto-discovered via /v3/accounts" + (f" (token sees {len(discovered)} practice accounts; using the first)" if len(discovered) > 1 else ""))
