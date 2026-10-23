"""Step-up auth for payment approvers: passphrase (scrypt) + TOTP (RFC 6238).
Same model as tradingbot's owner CLI but a SEPARATE secrets file and separate
approver identities (the trading bot holds none of these). PLACEHOLDER for
WebAuthn/hardware keys. Secrets file is 0600, outside git (var/)."""
from __future__ import annotations
import base64, hmac, json, secrets, time
from pathlib import Path

class AuthError(PermissionError): ...

from atlas.governance.integrity.crypto import scrypt_kdf as _kdf, totp, totp_ok, write_secret_json  # noqa: F401 (shared)


class Approvers:
    MIN_LEN, MAX_FAIL, LOCK_S = 12, 5, 300

    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, d: dict):
        write_secret_json(self.path, d)

    def enroll(self, name: str, passphrase: str) -> str:
        if len(passphrase) < self.MIN_LEN:
            raise ValueError(f"passphrase must be >= {self.MIN_LEN} chars")
        d = self._load()
        if name in d:
            raise FileExistsError(f"approver {name} exists")
        salt = secrets.token_bytes(16)
        sec = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        d[name] = {"salt": salt.hex(), "hash": _kdf(passphrase, salt).hex(), "totp": sec, "fail": [], "used": []}
        self._save(d)
        return sec

    def names(self) -> list[str]:
        return list(self._load())

    def verify(self, name: str, passphrase: str, code: str) -> None:
        d = self._load(); a = d.get(name)
        if not a:
            raise AuthError("unknown approver")
        t = self.clock()
        a["fail"] = [f for f in a["fail"] if t - f < self.LOCK_S]
        if len(a["fail"]) >= self.MAX_FAIL:
            raise AuthError("locked out")
        ok_p = hmac.compare_digest(_kdf(passphrase, bytes.fromhex(a["salt"])).hex(), a["hash"])
        ok_c = totp_ok(a["totp"], code, t)
        if not (ok_p and ok_c) or code in a["used"]:
            a["fail"].append(t); self._save(d)
            raise AuthError("step-up failed")
        a["used"] = (a["used"] + [code])[-10:]
        self._save(d)
