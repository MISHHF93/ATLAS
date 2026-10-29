"""Password hashing (argon2id) and policy (OWASP ASVS V2.1: length over composition, no truncation, breach-list-lite)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2 import Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LEN = 12
MAX_LEN = 128

# argon2-cffi defaults follow RFC 9106 "low memory" (t=3, m=64 MiB, p=4). Overridable for tests only via the constructor.
_HASHER = PasswordHasher(type=Type.ID)
_DUMMY = _HASHER.hash("atlas-dummy-password-for-constant-time-path")

_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "iloveyou1234", "administrator", "letmein123456", "welcome12345",
    "passwordpassword", "1234567890123", "000000000000", "111111111111", "changemechangeme", "atlasatlasatlas",
}


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, email: str = "") -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("password must be text")
    if len(password) < MIN_LEN:
        raise PasswordPolicyError(f"password must be at least {MIN_LEN} characters")
    if len(password) > MAX_LEN:
        raise PasswordPolicyError(f"password must be at most {MAX_LEN} characters")
    low = password.lower()
    if low in _COMMON or len(set(low)) < 5:
        raise PasswordPolicyError("password is too common or too repetitive")
    local = email.split("@", 1)[0].lower()
    if local and len(local) >= 4 and local in low:
        raise PasswordPolicyError("password must not contain your email name")


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-ish time: an unknown user still pays for one argon2 verification."""
    try:
        if not stored_hash:
            _HASHER.verify(_DUMMY, password)
            return False
        return _HASHER.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
