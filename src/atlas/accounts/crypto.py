"""Envelope encryption for per-user connector secrets.

* Each secret gets its own random 256-bit data key (DEK). The secret is sealed with AES-256-GCM under that DEK.
* The DEK is wrapped (sealed again with AES-256-GCM) by the master key from ``ATLAS_MASTER_KEY`` (base64url, 32 bytes).
* AAD binds every ciphertext to its owner: ``user_id | connector | field | version`` for the secret and ``dek | kid`` for
  the wrapped key, so a row copied to another user, connector or field fails authentication (tamper detection).
* The master key is read from the environment on every call, never stored, never logged. If it is missing or malformed the
  system FAILS CLOSED: ``MasterKeyError`` (the API maps it to 503). ``ATLAS_MASTER_KEY_PREVIOUS`` (comma separated) lets old
  rows decrypt during a master key rotation; ``rewrap`` moves rows to the current key without touching the secret.
Generate a key:  python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALG = "AES-256-GCM+DEK-wrap-v1"


class MasterKeyError(RuntimeError):
    """ATLAS_MASTER_KEY missing or invalid: secret storage is disabled (fail closed)."""


class TamperError(ValueError):
    """Ciphertext failed authentication (modified, wrong owner, or wrong master key)."""


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode())


def _parse_key(raw: str) -> bytes:
    raw = (raw or "").strip()
    if not raw:
        raise MasterKeyError("ATLAS_MASTER_KEY is not set")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as ex:  # noqa: BLE001
        raise MasterKeyError("ATLAS_MASTER_KEY is not valid base64url") from ex
    if len(key) != 32:
        raise MasterKeyError("ATLAS_MASTER_KEY must decode to exactly 32 bytes")
    return key


def generate_master_key() -> str:
    """A fresh 32-byte key, base64url. Printed once by the CLI; never stored by ATLAS."""
    return _b64e(os.urandom(32))


def key_id(key: bytes) -> str:
    """Public, non-reversible fingerprint used to pick the right master key for a row."""
    return hashlib.sha256(b"atlas-kid-v1" + key).hexdigest()[:16]


def master_key(env: dict[str, str] | None = None) -> tuple[bytes, str]:
    env = os.environ if env is None else env
    key = _parse_key(env.get("ATLAS_MASTER_KEY", ""))
    return key, key_id(key)


def master_keys_for_decrypt(env: dict[str, str] | None = None) -> dict[str, bytes]:
    env = os.environ if env is None else env
    cur, kid = master_key(env)
    keys = {kid: cur}
    for raw in (env.get("ATLAS_MASTER_KEY_PREVIOUS") or "").split(","):
        if raw.strip():
            k = _parse_key(raw)
            keys[key_id(k)] = k
    return keys


def master_key_configured(env: dict[str, str] | None = None) -> bool:
    try:
        master_key(env)
        return True
    except MasterKeyError:
        return False


@dataclass(frozen=True)
class SealedSecret:
    ciphertext: str
    nonce: str
    wrapped_dek: str
    wrap_nonce: str
    kid: str
    alg: str = ALG


def _aad(user_id: str, connector: str, field: str, version: int) -> bytes:
    return f"atlas.secret.v1|{user_id}|{connector}|{field}|{int(version)}".encode()


def _wrap_aad(kid: str, user_id: str, connector: str, field: str, version: int) -> bytes:
    return f"atlas.dek.v1|{kid}|{user_id}|{connector}|{field}|{int(version)}".encode()


def seal(plaintext: str, *, user_id: str, connector: str, field: str, version: int = 1, env: dict[str, str] | None = None) -> SealedSecret:
    key, kid = master_key(env)
    dek = AESGCM.generate_key(bit_length=256)
    nonce, wrap_nonce = os.urandom(12), os.urandom(12)
    ct = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), _aad(user_id, connector, field, version))
    wrapped = AESGCM(key).encrypt(wrap_nonce, dek, _wrap_aad(kid, user_id, connector, field, version))
    return SealedSecret(_b64e(ct), _b64e(nonce), _b64e(wrapped), _b64e(wrap_nonce), kid)


def open_secret(s: SealedSecret | dict, *, user_id: str, connector: str, field: str, version: int = 1, env: dict[str, str] | None = None) -> str:
    g = (lambda k: s[k]) if isinstance(s, dict) else (lambda k: getattr(s, k))
    keys = master_keys_for_decrypt(env)
    kid = g("kid")
    if kid not in keys:
        raise MasterKeyError("no master key available for this secret (rotate: set ATLAS_MASTER_KEY_PREVIOUS)")
    try:
        dek = AESGCM(keys[kid]).decrypt(_b64d(g("wrap_nonce")), _b64d(g("wrapped_dek")), _wrap_aad(kid, user_id, connector, field, version))
        return AESGCM(dek).decrypt(_b64d(g("nonce")), _b64d(g("ciphertext")), _aad(user_id, connector, field, version)).decode("utf-8")
    except (InvalidTag, ValueError) as ex:
        raise TamperError("secret failed authentication") from ex


def rewrap(s: dict, *, user_id: str, connector: str, field: str, version: int, env: dict[str, str] | None = None) -> SealedSecret:
    """Move a secret's DEK to the current master key. The secret ciphertext is unchanged."""
    keys = master_keys_for_decrypt(env)
    cur, new_kid = master_key(env)
    old = keys.get(s["kid"])
    if old is None:
        raise MasterKeyError("no master key available for this secret")
    try:
        dek = AESGCM(old).decrypt(_b64d(s["wrap_nonce"]), _b64d(s["wrapped_dek"]), _wrap_aad(s["kid"], user_id, connector, field, version))
    except (InvalidTag, ValueError) as ex:
        raise TamperError("wrapped key failed authentication") from ex
    wrap_nonce = os.urandom(12)
    wrapped = AESGCM(cur).encrypt(wrap_nonce, dek, _wrap_aad(new_kid, user_id, connector, field, version))
    return SealedSecret(s["ciphertext"], s["nonce"], _b64e(wrapped), _b64e(wrap_nonce), new_kid)


def last4(secret: str) -> str:
    """Only the last four characters are ever shown, and only for values long enough that this reveals little."""
    s = secret.strip()
    return s[-4:] if len(s) >= 12 else ("*" * 4)
