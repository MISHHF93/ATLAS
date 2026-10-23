"""Scoped MCP client tokens (hashed at rest, expiring, revocable) + failed-auth lockout.

File (default var/mcp_tokens.json, gitignored) holds only sha256 hashes.
Scopes: read (status/positions/limits/approvals), propose, kill.
Legacy MCP_AUTH_TOKEN env grants all scopes (kept for local dev)."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

SCOPES = {"read", "propose", "kill"}


class TokenRegistry:
    MAX_FAILURES = 5
    WINDOW_S = 60

    def __init__(self, path: str | Path | None = None, legacy_token: str | None = None, clock=time.time):
        self.path = Path(path) if path else None
        self.legacy = legacy_token
        self.clock = clock
        self._failures: list[float] = []

    def _load(self) -> dict:
        if self.path and self.path.exists():
            return json.loads(self.path.read_text())
        return {"tokens": {}}

    def create(self, client: str, scopes: set[str], ttl_days: float = 30) -> str:
        if not scopes or not scopes <= SCOPES:
            raise ValueError(f"scopes must be a subset of {sorted(SCOPES)}")
        if self.path is None:
            raise ValueError("no token file configured")
        tok = "tbk_" + secrets.token_urlsafe(32)
        d = self._load()
        d["tokens"][client] = {"sha256": hashlib.sha256(tok.encode()).hexdigest(), "scopes": sorted(scopes),
                               "expires": self.clock() + ttl_days * 86400}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d))
        self.path.chmod(0o600)
        return tok  # shown once

    def revoke(self, client: str) -> None:
        d = self._load()
        d["tokens"].pop(client, None)
        if self.path:
            self.path.write_text(json.dumps(d))

    def locked(self) -> bool:
        now = self.clock()
        self._failures = [f for f in self._failures if now - f < self.WINDOW_S]
        return len(self._failures) >= self.MAX_FAILURES

    def check(self, token: str | None, scope: str) -> str:
        """Returns client id or raises PermissionError."""
        if self.locked():
            raise PermissionError("too many failed auth attempts; locked out")
        t = (token or "").encode()
        if self.legacy and hmac.compare_digest(t, self.legacy.encode()):
            return "legacy-env"
        h = hashlib.sha256(t).hexdigest()
        for client, e in self._load().get("tokens", {}).items():
            if hmac.compare_digest(h, e["sha256"]):
                if self.clock() > e["expires"]:
                    break
                if scope not in e["scopes"]:
                    raise PermissionError(f"token for {client} lacks scope {scope!r}")
                return client
        self._failures.append(self.clock())
        raise PermissionError("invalid or expired auth token")
