"""Owner step-up authentication: local passphrase (scrypt) + TOTP (RFC 6238).

Secrets live in a local file outside git (default var/owner_stepup.json, 0600),
created by `atlas-owner init-stepup`. This is a PLACEHOLDER for a real
step-up provider (WebAuthn / hardware key / OIDC step-up)."""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
from pathlib import Path


from atlas.governance.integrity.crypto import scrypt_kdf as _scrypt, totp, totp_ok, write_secret_json  # noqa: F401 (shared)


class StepUp:
    MIN_PASSPHRASE = 12
    MAX_FAILURES = 5
    LOCKOUT_S = 300

    def __init__(self, path: str | Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    def init(self, passphrase: str, owner: str) -> str:
        if len(passphrase) < self.MIN_PASSPHRASE:
            raise ValueError(f"passphrase must be >= {self.MIN_PASSPHRASE} chars")
        if self.path.exists():
            raise FileExistsError(f"{self.path} exists; delete it manually to re-initialise")
        salt = secrets.token_bytes(16)
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"owner": owner, "salt": salt.hex(), "hash": _scrypt(passphrase, salt).hex(), "totp_secret": secret,
                "failures": [], "used_codes": []}
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return secret  # shown once so the owner can add it to an authenticator app

    def _load(self) -> dict:
        return json.loads(self.path.read_text())

    def _save(self, d: dict) -> None:
        write_secret_json(self.path, d)  # atomic, keeps 0600

    def verify(self, owner: str, passphrase: str, code: str) -> bool:
        """True only if owner, passphrase and current TOTP (±1 step, single-use) match. Fails closed."""
        try:
            d = self._load()
        except Exception:
            return False
        now = self.clock()
        d["failures"] = [f for f in d.get("failures", []) if now - f < self.LOCKOUT_S]
        if len(d["failures"]) >= self.MAX_FAILURES:
            return False
        ok_pw = hmac.compare_digest(_scrypt(passphrase, bytes.fromhex(d["salt"])).hex(), d["hash"])
        ok_code = totp_ok(d["totp_secret"], code, now) and code not in d.get("used_codes", [])
        ok = ok_pw and ok_code and owner == d["owner"]
        if ok:
            d["used_codes"] = (d.get("used_codes", []) + [code])[-10:]
        else:
            d["failures"].append(now)
        self._save(d)
        return ok
