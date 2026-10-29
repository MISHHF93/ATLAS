"""OAuth hook (not enabled). The ``oauth_identities`` table (provider, subject, user_id) already exists so adding Google / GitHub login later is
an additive change: implement a provider below, return it from ``providers()``, and link by (provider, subject), never by email alone.
Until then every OAuth route answers 501 and ``/api/account/config`` lists no providers."""
from __future__ import annotations

from typing import Protocol


class OAuthProvider(Protocol):
    name: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...
    def exchange(self, code: str, redirect_uri: str) -> tuple[str, str]:
        """Return (provider_subject, verified_email_or_empty)."""


def providers() -> dict[str, OAuthProvider]:
    return {}
