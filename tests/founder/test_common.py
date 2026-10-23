import json, os
from atlas.governance.integrity.crypto import totp, totp_ok, scrypt_kdf, write_secret_json
from atlas.governance.integrity.hashchain import GENESIS, link
from atlas.governance.integrity.fx import STATIC_RATES_TO_CAD


def test_totp_rfc6238_vector():
    # RFC 6238 SHA1 secret "12345678901234567890" at t=59 -> 94287082 (8 digits)
    import base64
    s = base64.b32encode(b"12345678901234567890").decode()
    assert totp(s, 59, digits=8) == "94287082"
    assert totp_ok(s, totp(s, 1000), 1030) and not totp_ok(s, totp(s, 1000), 1200)


def test_kdf_and_chain_and_secret(tmp_path):
    assert scrypt_kdf("x" * 12, b"s" * 16) == scrypt_kdf("x" * 12, b"s" * 16)
    assert link(GENESIS, "a") != link(GENESIS, "b")
    p = tmp_path / "s.json"; write_secret_json(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1} and oct(os.stat(p).st_mode)[-3:] == "600"
    assert STATIC_RATES_TO_CAD["USD"] == "1.37"
