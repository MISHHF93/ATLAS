"""Local console authentication.

* Login: username + passphrase (scrypt, file 0600 outside git). 5 failures in 5 min => lockout.
* Session: random 256-bit token in an HttpOnly, SameSite=Strict cookie; only its SHA-256 is kept
  server-side (memory). Idle timeout 30 min, absolute lifetime 8 h. Sessions are listable/revocable.
* CSRF: per-session random token, required as X-CSRF-Token on every state-changing request
  (constant-time compare) in addition to the Origin/Host checks done by the HTTP layer.
* Step-up (passphrase + TOTP) is NOT done here: each action is verified by the owning service's
  own step-up store (tradingbot StepUp for trading actions, payments Approvers for payments)."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from atlas.governance.integrity.crypto import scrypt_kdf, write_secret_json

IDLE_S = 30 * 60
ABSOLUTE_S = 8 * 3600
MAX_FAIL, LOCK_S = 5, 300
MIN_PASSPHRASE = 12


class AuthError(PermissionError):
    pass


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Session:
    sid: str                    # public id (shown in the UI, used to revoke); not the cookie value
    user: str
    csrf: str
    created: float
    last_seen: float
    user_agent: str = ""
    meta: dict = field(default_factory=dict)

    def public(self, current: bool = False) -> dict:
        return {"id": self.sid, "user": self.user, "created": self.created, "last_seen": self.last_seen,
                "user_agent": self.user_agent[:120], "current": current}


class Users:
    """Console login identities. File: {"users": {name: {salt, hash, created}}}."""

    def __init__(self, path: str | Path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self._fail: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {"users": {}}

    def enrolled(self, name: str) -> bool:
        return name in self._load()["users"]

    def names(self) -> list[str]:
        return sorted(self._load()["users"])

    def enroll(self, name: str, passphrase: str) -> None:
        if len(passphrase) < MIN_PASSPHRASE:
            raise ValueError(f"passphrase must be >= {MIN_PASSPHRASE} chars")
        d = self._load()
        if name in d["users"]:
            raise FileExistsError(name)
        salt = secrets.token_bytes(16)
        d["users"][name] = {"salt": salt.hex(), "hash": scrypt_kdf(passphrase, salt).hex(), "created": self.clock()}
        write_secret_json(self.path, d)

    def check(self, name: str, passphrase: str) -> None:
        with self._lock:
            now = self.clock()
            f = self._fail[name] = [t for t in self._fail.get(name, []) if now - t < LOCK_S]
            if len(f) >= MAX_FAIL:
                raise AuthError("locked out; try again later")
            u = self._load()["users"].get(name)
            ok = bool(u) and hmac.compare_digest(scrypt_kdf(passphrase, bytes.fromhex(u["salt"])).hex(), u["hash"])
            if not u:  # same cost for unknown users (no username oracle via timing)
                scrypt_kdf(passphrase, b"\0" * 16)
            if not ok:
                f.append(now)
                raise AuthError("invalid credentials")


class Sessions:
    def __init__(self, clock=time.time):
        self.clock = clock
        self._by_hash: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, user: str, user_agent: str = "") -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        s = Session(secrets.token_hex(6), user, secrets.token_urlsafe(32), now, now, user_agent)
        with self._lock:
            self._by_hash[_h(token)] = s
        return token, s

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        now = self.clock()
        with self._lock:
            s = self._by_hash.get(_h(token))
            if not s:
                return None
            if now - s.last_seen > IDLE_S or now - s.created > ABSOLUTE_S:
                self._by_hash.pop(_h(token), None)
                return None
            s.last_seen = now
            return s

    def destroy(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._by_hash.pop(_h(token), None)

    def list(self, user: str) -> list[Session]:
        with self._lock:
            return sorted((s for s in self._by_hash.values() if s.user == user), key=lambda s: -s.created)

    def revoke(self, user: str, sid: str) -> bool:
        with self._lock:
            for k, s in list(self._by_hash.items()):
                if s.user == user and s.sid == sid:
                    del self._by_hash[k]
                    return True
        return False


def csrf_ok(session: Session | None, header: str | None) -> bool:
    return bool(session) and bool(header) and hmac.compare_digest(session.csrf.encode(), header.encode())
