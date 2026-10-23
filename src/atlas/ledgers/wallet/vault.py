"""Encrypted local vault for bank details (AES-256-GCM, `cryptography`).

Key: env ATLAS_VAULT_KEY = urlsafe-base64 of 32 random bytes (`python -m atlas.ledgers.wallet.vault`
prints a new one). A missing or placeholder key fails closed: nothing can be stored or read. Each record is
bound to its purpose/id via AES-GCM associated data, so a ciphertext copied to another row will not decrypt.
Only masked values (last 4) leave this module, except to an adapter that needs the full number."""
from __future__ import annotations

import base64
import os
import secrets

ENV = "ATLAS_VAULT_KEY"
PLACEHOLDERS = {"", "changeme", "placeholder", "<vault-key>", "REPLACE_ME"}


class VaultUnavailable(RuntimeError):
    pass


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def mask(value: str, keep: int = 4) -> str:
    v = "".join(ch for ch in str(value) if ch.isalnum())
    return ("•" * min(max(len(v) - keep, 0), 6)) + v[-keep:] if v else ""


class Vault:
    def __init__(self, c, key: str | None = None, clock=None):
        import time
        self.c, self.clock = c, clock or time.time
        raw = key if key is not None else os.environ.get(ENV, "")
        if raw.strip() in PLACEHOLDERS:
            raise VaultUnavailable(f"{ENV} not set (or placeholder); bank details cannot be stored or read")
        try:
            k = base64.urlsafe_b64decode(raw.encode())
        except Exception as e:  # noqa: BLE001
            raise VaultUnavailable(f"{ENV} is not valid base64") from e
        if len(k) != 32:
            raise VaultUnavailable(f"{ENV} must decode to 32 bytes")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as e:  # pragma: no cover
            raise VaultUnavailable("the 'cryptography' package is required for the vault") from e
        self._aead = AESGCM(k)
        import hashlib
        self.key_id = hashlib.sha256(b"atlas-vault-key-id" + k).hexdigest()[:12]
        c.execute("CREATE TABLE IF NOT EXISTS vault(id INTEGER PRIMARY KEY, purpose TEXT, key_id TEXT, nonce BLOB, "
                  "ciphertext BLOB, created_at REAL)")

    def put(self, purpose: str, plaintext: str) -> int:
        vid = self.c.execute("INSERT INTO vault(purpose,key_id,nonce,ciphertext,created_at) VALUES(?,?,?,?,?)",
                             (purpose, self.key_id, b"", b"", self.clock())).lastrowid
        nonce = secrets.token_bytes(12)
        ct = self._aead.encrypt(nonce, plaintext.encode(), f"{vid}:{purpose}".encode())
        self.c.execute("UPDATE vault SET nonce=?, ciphertext=? WHERE id=?", (nonce, ct, vid))
        return vid

    def get(self, vid: int) -> str:
        r = self.c.execute("SELECT * FROM vault WHERE id=?", (vid,)).fetchone()
        if not r:
            raise KeyError(vid)
        if r["key_id"] != self.key_id:
            raise VaultUnavailable("record was encrypted with a different key")
        return self._aead.decrypt(r["nonce"], r["ciphertext"], f"{vid}:{r['purpose']}".encode()).decode()


NEW_ENV = "ATLAS_VAULT_KEY_NEW"


def rotate(c, old_key: str, new_key: str, actor: str = "cli", dry_run: bool = False, clock=None) -> dict:
    """Re-encrypt every vault record from old_key to new_key in one transaction. Each record is decrypted with
    the old key, re-encrypted under a fresh nonce with the same associated data, then read back with the new key
    before commit; any failure rolls everything back, so the database is never left with mixed keys. Keys are
    never logged; only their 12-hex key ids are recorded in vault_rotations."""
    import time
    old, new = Vault(c, old_key, clock), Vault(c, new_key, clock)
    if old.key_id == new.key_id:
        raise VaultUnavailable("the new key is the same as the current key")
    c.execute("CREATE TABLE IF NOT EXISTS vault_rotations(id INTEGER PRIMARY KEY, ts REAL, actor TEXT, old_key_id TEXT, new_key_id TEXT, records INTEGER)")
    rows = c.execute("SELECT id, purpose, key_id FROM vault ORDER BY id").fetchall()
    foreign = [r["id"] for r in rows if r["key_id"] not in (old.key_id, new.key_id)]
    if foreign:
        raise VaultUnavailable(f"{len(foreign)} record(s) are under neither key (first id {foreign[0]}); refusing to rotate")
    todo = [r for r in rows if r["key_id"] == old.key_id]
    if dry_run:
        for r in todo:
            old.get(r["id"])                  # proves every record decrypts with the current key
        return {"records": len(todo), "old_key_id": old.key_id, "new_key_id": new.key_id, "dry_run": True}
    from atlas.ledgers.db import tx
    with tx(c):                               # any exception rolls back every record
        for r in todo:
            plain = old.get(r["id"])
            nonce = secrets.token_bytes(12)
            ct = new._aead.encrypt(nonce, plain.encode(), f"{r['id']}:{r['purpose']}".encode())
            c.execute("UPDATE vault SET key_id=?, nonce=?, ciphertext=? WHERE id=?", (new.key_id, nonce, ct, r["id"]))
            if new.get(r["id"]) != plain:
                raise VaultUnavailable(f"read-back mismatch on record {r['id']}")
        c.execute("INSERT INTO vault_rotations(ts,actor,old_key_id,new_key_id,records) VALUES(?,?,?,?,?)",
                  ((clock or time.time)(), actor, old.key_id, new.key_id, len(todo)))
    return {"records": len(todo), "old_key_id": old.key_id, "new_key_id": new.key_id, "dry_run": False}


if __name__ == "__main__":
    print(new_key())
