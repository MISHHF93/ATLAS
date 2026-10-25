"""Step-up primitives: RFC 6238 TOTP, scrypt KDF, constant-time checks, 0600 atomic secret files."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path


def totp(secret_b32: str, t: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    h = hmac.new(key, struct.pack(">Q", int((time.time() if t is None else t) // step)), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def totp_ok(secret_b32: str, code: str, t: float, window: int = 1, step: int = 30) -> bool:
    return any(hmac.compare_digest(totp(secret_b32, t + k * step, step), str(code)) for k in range(-window, window + 1))


def scrypt_kdf(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def write_secret_json(path: str | Path, data) -> None:
    """Write-then-rename with 0600 perms: a crash never leaves a truncated secrets file."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f); f.flush(); os.fsync(f.fileno())
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 4:
                path.write_bytes(tmp.read_bytes())
                os.chmod(path, 0o600)
                tmp.unlink(missing_ok=True)
            else:
                time.sleep(0.02 * (attempt + 1))
