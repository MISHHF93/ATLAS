"""Per-request credential resolution.

The middleware sets the request identity; feeds / integrations call ``effective_environ()`` instead of ``os.environ``.

* no identity (auth off, or a background daemon)  -> ``os.environ`` exactly as before (the owner's .env keys keep working).
* role ``owner``                                  -> the owner's saved connectors win, ``os.environ`` / .env is the FALLBACK.
* any other user                                  -> ONLY that user's own saved connectors. Credential-shaped names from the host
  environment (and the host's .env file) are never visible, so one user can never ride on the owner's keys.
Execution authority is untouched: nothing here can enable live trading, and ML ``execution_permission`` stays ``none``.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar, Token
from typing import Mapping

EXECUTION_PERMISSION = "none"
_CRED_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|DSN|WEBHOOK|ACCOUNT|USER_AGENT|CHAT_ID|TOPIC|PING_URL|NTFY|_URL$)", re.I)


class Identity:
    __slots__ = ("user_id", "role", "_env")

    def __init__(self, user_id: str, role: str):
        self.user_id, self.role, self._env = user_id, role, None


_CTX: ContextVar[Identity | None] = ContextVar("atlas_identity", default=None)


def set_identity(user_id: str | None, role: str = "user") -> Token:
    return _CTX.set(Identity(user_id, role) if user_id else None)


def reset_identity(token: Token) -> None:
    _CTX.reset(token)


def current_identity() -> Identity | None:
    return _CTX.get()


def owner_scope() -> bool:
    """True when the host owner's .env / process env may be used (no identity = legacy single-user mode, or the owner)."""
    i = _CTX.get()
    return i is None or i.role == "owner"


def _is_credential_name(name: str) -> bool:
    if _CRED_NAME.search(name):
        return True
    try:
        from atlas.integrations.registry import ALL_VARS
        if name in ALL_VARS:
            return True
    except Exception:  # noqa: BLE001
        pass
    return name.startswith(("ALPACA_", "OANDA_", "IBKR_", "STRIPE_", "ATLAS_MASTER"))


def connector_env(user_id: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Env-name -> value from one user's saved connectors. Empty (never an exception) if the master key is missing or a row is bad."""
    from . import connectors, crypto
    from .catalog import BY_ID
    from .db import connect
    out: dict[str, str] = {}
    if not crypto.master_key_configured(dict(env) if env is not None else None):
        return out
    try:
        with connect() as conn:
            for cid in [r["connector_id"] for r in conn.execute("SELECT connector_id FROM connectors WHERE user_id=?", (user_id,))]:
                spec = BY_ID.get(cid)
                if not spec:
                    continue
                try:
                    vals = connectors.load_values(conn, user_id, cid, dict(env) if env is not None else None)
                except Exception:  # noqa: BLE001 - tampered / unreadable row: skip that connector, fail closed
                    continue
                if not vals:
                    continue
                for f in spec.fields:
                    if vals.get(f.name):
                        out[f.env] = vals[f.name]
                out.update(dict(spec.constants))
    except Exception:  # noqa: BLE001
        return {}
    return out


def effective_environ() -> Mapping[str, str]:
    i = _CTX.get()
    if i is None:
        return os.environ
    if i._env is None:
        base = dict(os.environ) if i.role == "owner" else {k: v for k, v in os.environ.items() if not _is_credential_name(k)}
        base.update(connector_env(i.user_id))
        i._env = base
    return i._env
