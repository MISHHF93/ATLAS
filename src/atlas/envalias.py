"""Environment variable aliases. Alpaca's own docs, SDKs and many tutorials use different names for the same two secrets, so a key pasted
under the "wrong" name used to leave the integration silently "not configured".

Canonical names (what ATLAS reads everywhere): ``ALPACA_API_KEY_ID`` and ``ALPACA_API_SECRET_KEY``. Accepted aliases, in order:

* ``ALPACA_API_KEY_ID``     <- ``ALPACA_API_KEY``, ``APCA_API_KEY_ID``
* ``ALPACA_API_SECRET_KEY`` <- ``ALPACA_SECRET_KEY``, ``ALPACA_API_SECRET``, ``APCA_API_SECRET_KEY``

The canonical name always wins when it holds a real value; an alias only fills a blank / placeholder. Nothing is ever logged.
"""
from __future__ import annotations

from typing import MutableMapping

ALIASES: dict[str, tuple[str, ...]] = {
    "ALPACA_API_KEY_ID": ("ALPACA_API_KEY", "APCA_API_KEY_ID"),
    "ALPACA_API_SECRET_KEY": ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET", "APCA_API_SECRET_KEY"),
}
ALIAS_NAMES = frozenset(a for v in ALIASES.values() for a in v)


def _real(v: str | None) -> bool:
    v = (v or "").strip()
    return bool(v) and not v.startswith("<")


def apply(env: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Fill canonical names from their aliases, in place. Idempotent and cheap; returns ``env``."""
    for canon, aliases in ALIASES.items():
        if _real(env.get(canon)):
            continue
        for a in aliases:
            if _real(env.get(a)):
                env[canon] = env[a]
                break
    return env


def normalized(env: dict[str, str]) -> dict[str, str]:
    return apply(dict(env))
