import pytest

from atlas.accounts import audit, connectors, crypto

from .conftest import mkuser

SECRET = "sk-very-secret-value-1234567890"


def test_round_trip(acct_env):
    s = crypto.seal(SECRET, user_id="u1", connector="tiingo", field="api_key", version=1)
    assert SECRET not in repr(s) and SECRET.encode() not in s.ciphertext if isinstance(s.ciphertext, bytes) else SECRET not in str(s.ciphertext)
    assert crypto.open_secret(s, user_id="u1", connector="tiingo", field="api_key", version=1) == SECRET


def test_fresh_data_key_and_nonce_each_time(acct_env):
    a = crypto.seal(SECRET, user_id="u1", connector="c", field="f")
    b = crypto.seal(SECRET, user_id="u1", connector="c", field="f")
    assert a.wrapped_dek != b.wrapped_dek and a.ciphertext != b.ciphertext and a.nonce != b.nonce


def _flip(v):
    if isinstance(v, bytes):
        return bytes([v[0] ^ 1]) + v[1:]
    return ("A" if v[0] != "A" else "B") + v[1:]


@pytest.mark.parametrize("part", ["ciphertext", "nonce", "wrapped_dek", "wrap_nonce"])
def test_tamper_detected(acct_env, part):
    s = crypto.seal(SECRET, user_id="u1", connector="c", field="f")
    d = {"ciphertext": s.ciphertext, "nonce": s.nonce, "wrapped_dek": s.wrapped_dek, "wrap_nonce": s.wrap_nonce, "kid": s.kid, "alg": s.alg}
    d[part] = _flip(d[part])
    with pytest.raises(crypto.TamperError):
        crypto.open_secret(d, user_id="u1", connector="c", field="f")


@pytest.mark.parametrize("kw", [{"user_id": "u2"}, {"connector": "x"}, {"field": "g"}, {"version": 2}])
def test_ciphertext_bound_to_context(acct_env, kw):
    s = crypto.seal(SECRET, user_id="u1", connector="c", field="f", version=1)
    ctx = {"user_id": "u1", "connector": "c", "field": "f", "version": 1, **kw}
    with pytest.raises(crypto.TamperError):
        crypto.open_secret(s, **ctx)


def test_fails_closed_without_master_key(acct_env, monkeypatch):
    monkeypatch.delenv("ATLAS_MASTER_KEY")
    with pytest.raises(crypto.MasterKeyError):
        crypto.seal(SECRET, user_id="u", connector="c", field="f")
    assert crypto.master_key_configured() is False


@pytest.mark.parametrize("bad", ["", "short", "!!!notbase64!!!", "QUJD"])
def test_bad_master_key_rejected(acct_env, monkeypatch, bad):
    monkeypatch.setenv("ATLAS_MASTER_KEY", bad)
    with pytest.raises(crypto.MasterKeyError):
        crypto.seal(SECRET, user_id="u", connector="c", field="f")


def test_wrong_master_key_cannot_open(acct_env, monkeypatch):
    s = crypto.seal(SECRET, user_id="u", connector="c", field="f")
    monkeypatch.setenv("ATLAS_MASTER_KEY", crypto.generate_master_key())
    with pytest.raises(Exception):
        crypto.open_secret(s, user_id="u", connector="c", field="f")


def test_master_key_rotation_via_rewrap(conn, monkeypatch):
    u = mkuser(conn)
    connectors.save(conn, u.id, "tiingo", {"api_key": "abcd1234efgh5678"})
    old = crypto.generate_master_key  # noqa: F841
    import os
    prev = os.environ["ATLAS_MASTER_KEY"]
    monkeypatch.setenv("ATLAS_MASTER_KEY_PREVIOUS", prev)
    monkeypatch.setenv("ATLAS_MASTER_KEY", crypto.generate_master_key())
    assert connectors.load_values(conn, u.id, "tiingo")["api_key"] == "abcd1234efgh5678"  # old key still decrypts
    assert connectors.rewrap_all(conn)["rewrapped"] >= 1
    monkeypatch.delenv("ATLAS_MASTER_KEY_PREVIOUS")
    assert connectors.load_values(conn, u.id, "tiingo")["api_key"] == "abcd1234efgh5678"


def test_last4_never_leaks_short_secrets():
    assert crypto.last4("abcdefgh1234") == "1234"
    assert crypto.last4("abc") == "****"


def test_stored_row_has_no_plaintext(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "tiingo", {"api_key": SECRET + "x"})
    raw = b"".join(bytes(str(v), "utf8") if not isinstance(v, bytes) else v for r in conn.execute("SELECT * FROM connector_secrets") for v in tuple(r))
    assert (SECRET + "x").encode() not in raw


def test_audit_never_records_values(conn):
    u = mkuser(conn)
    connectors.save(conn, u.id, "tiingo", {"api_key": SECRET + "y"})
    connectors.rotate(conn, u.id, "tiingo", "api_key", SECRET + "z")
    connectors.delete(conn, u.id, "tiingo")
    dump = str(audit.recent(conn, None, 100))
    assert SECRET not in dump
    assert "connector.save" in dump and "connector.delete" in dump
    assert audit.verify_chain(conn)["ok"]
