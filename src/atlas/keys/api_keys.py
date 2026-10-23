"""Scoped, hashed, revocable, rate-limited API keys for the local ATLAS API and MCP endpoint.

- A key looks like ``atk_<key_id>_<secret>``. The plaintext is returned once by ``create`` and never stored:
  the store keeps ``sha256(salt || secret)`` with a random per-key salt and compares in constant time.
- Scopes: ``read`` (market/zones/setups/predict/status), ``research`` (adds replay/evidence), ``paper-trade``
  (adds paper-autopilot switch requests). Each scope includes the ones before it. No scope can place a live
  order, move money, approve the autopilot (owner step-up only) or reset the Safe stop.
- Revocation is immediate. Each key has its own token-bucket rate limit (requests per minute).
- Store: JSON file at ``ATLAS_API_KEYS_PATH`` (name only), default ``var/api_keys.json``; never committed.
  Keys are created and revoked only from the owner CLI (``python -m atlas.keys.cli``), never over HTTP.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCOPES = ("read", "research", "paper-trade")
DEFAULT_PATH = "var/api_keys.json"
PREFIX = "atk_"


class KeyError_(PermissionError):
    def __init__(self, code: str, status: int = 401):
        super().__init__(code)
        self.code, self.status = code, status


def _hash(salt: str, secret: str) -> str:
    return hashlib.sha256(bytes.fromhex(salt) + secret.encode()).hexdigest()


def scope_allows(granted: str, needed: str) -> bool:
    return SCOPES.index(granted) >= SCOPES.index(needed)


@dataclass
class KeyRecord:
    key_id: str
    name: str
    scope: str
    salt: str
    digest: str
    created_at: float
    rate_per_min: int = 60
    revoked_at: float | None = None
    last_used_at: float | None = None

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("salt"); d.pop("digest")
        return d


@dataclass
class _Bucket:
    tokens: float
    at: float = field(default_factory=time.monotonic)


class ApiKeyStore:
    def __init__(self, path: str | os.PathLike | None = None, clock=time.monotonic):
        self.path = Path(path or os.environ.get("ATLAS_API_KEYS_PATH", DEFAULT_PATH))
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._clock = clock

    def _load(self) -> dict[str, KeyRecord]:
        if not self.path.exists():
            return {}
        return {k: KeyRecord(**v) for k, v in json.loads(self.path.read_text()).items()}

    def _save(self, recs: dict[str, KeyRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in recs.items()}, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def create(self, name: str, scope: str, rate_per_min: int = 60) -> tuple[str, dict[str, Any]]:
        """Returns (plaintext_key, public_record). The plaintext is not recoverable afterwards."""
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        if not 1 <= int(rate_per_min) <= 6000:
            raise ValueError("rate_per_min must be 1..6000")
        kid, secret, salt = secrets.token_hex(6), secrets.token_urlsafe(32), secrets.token_hex(16)
        rec = KeyRecord(kid, name[:80], scope, salt, _hash(salt, secret), time.time(), int(rate_per_min))
        with self._lock:
            recs = self._load(); recs[kid] = rec; self._save(recs)
        return f"{PREFIX}{kid}_{secret}", rec.public()

    def revoke(self, key_id: str) -> bool:
        with self._lock:
            recs = self._load()
            if key_id not in recs or recs[key_id].revoked_at:
                return False
            recs[key_id].revoked_at = time.time(); self._save(recs)
            self._buckets.pop(key_id, None)
            return True

    def list(self) -> list[dict[str, Any]]:
        return [r.public() for r in self._load().values()]

    def verify(self, token: str | None, needed: str) -> dict[str, Any]:
        """Return the public record or raise KeyError_ (401 bad/revoked, 403 scope, 429 rate)."""
        if needed not in SCOPES:
            raise ValueError("unknown scope")
        if not token or not token.startswith(PREFIX) or token.count("_") < 2:
            raise KeyError_("missing_or_malformed_key")
        kid, secret = token[len(PREFIX):].split("_", 1)
        rec = self._load().get(kid)
        if rec is None or not hmac.compare_digest(rec.digest, _hash(rec.salt, secret)):
            raise KeyError_("invalid_key")
        if rec.revoked_at:
            raise KeyError_("revoked_key")
        if not scope_allows(rec.scope, needed):
            raise KeyError_("insufficient_scope", 403)
        with self._lock:
            now = self._clock()
            b = self._buckets.setdefault(kid, _Bucket(float(rec.rate_per_min), now))
            b.tokens = min(float(rec.rate_per_min), b.tokens + (now - b.at) * rec.rate_per_min / 60.0)
            b.at = now
            if b.tokens < 1:
                raise KeyError_("rate_limited", 429)
            b.tokens -= 1
        return rec.public()


def bearer(headers: Any) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get("x-atlas-key")
