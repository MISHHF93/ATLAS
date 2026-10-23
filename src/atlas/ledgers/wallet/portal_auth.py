"""Investor portal identities (separate role from staff/owner): passphrase (scrypt) + TOTP step-up.
File 0600 (var/payments/investor_logins.json). Each login maps to exactly one wallet investor id, and portal
sessions can only read that investor's own data (enforced by the console's portal routes)."""
from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from pathlib import Path

from atlas.governance.integrity.crypto import scrypt_kdf, totp_ok, write_secret_json

MIN_LEN, MAX_FAIL, LOCK_S = 12, 5, 300


class InvestorAuthError(PermissionError):
    pass


class InvestorLogins:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def enroll(self, username: str, passphrase: str, investor_id: int) -> str:
        if len(passphrase) < MIN_LEN:
            raise ValueError(f"passphrase must be >= {MIN_LEN} chars")
        d = self._load()
        if username in d:
            raise FileExistsError(username)
        salt = secrets.token_bytes(16)
        sec = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        d[username] = {"investor_id": int(investor_id), "salt": salt.hex(), "hash": scrypt_kdf(passphrase, salt).hex(),
                       "totp": sec, "fail": [], "used": [], "created": self.clock()}
        write_secret_json(self.path, d)
        return sec

    def investor_id(self, username: str) -> int | None:
        u = self._load().get(username)
        return u["investor_id"] if u else None

    def users(self) -> list[dict]:
        return [{"username": k, "investor_id": v["investor_id"]} for k, v in sorted(self._load().items())]

    def _check(self, username, passphrase, code=None) -> int:
        d = self._load()
        u = d.get(username)
        t = self.clock()
        if not u:
            scrypt_kdf(passphrase, b"\0" * 16)
            raise InvestorAuthError("invalid credentials")
        u["fail"] = [f for f in u["fail"] if t - f < LOCK_S]
        if len(u["fail"]) >= MAX_FAIL:
            write_secret_json(self.path, d)
            raise InvestorAuthError("locked out; try again later")
        ok = hmac.compare_digest(scrypt_kdf(passphrase, bytes.fromhex(u["salt"])).hex(), u["hash"])
        if code is not None:
            ok = ok and totp_ok(u["totp"], str(code), t) and str(code) not in u["used"]
        if not ok:
            u["fail"].append(t)
            write_secret_json(self.path, d)
            raise InvestorAuthError("invalid credentials" if code is None else "step-up failed")
        if code is not None:
            u["used"] = (u["used"] + [str(code)])[-10:]
        write_secret_json(self.path, d)
        return u["investor_id"]

    def check(self, username: str, passphrase: str) -> int:
        """Login (passphrase). Returns the investor id."""
        return self._check(username, passphrase)

    def verify(self, username: str, passphrase: str, code: str) -> int:
        """Step-up (passphrase + single-use TOTP) for redemption requests and bank-account changes."""
        return self._check(username, passphrase, code)
