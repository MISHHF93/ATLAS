import json
import logging
import sqlite3

import pytest

from atlas.governance.audit import AuditLog, AuditTamperError
from atlas.telemetry.logging_setup import REDACTED, JsonRedactingFormatter, redact, redact_text


def test_chain_verifies():
    a = AuditLog()
    for i in range(5):
        a.append("e", {"i": i})
    assert a.verify() == 5
    es = a.entries()
    assert es[1]["prev_hash"] == es[0]["hash"]


def test_update_and_delete_blocked():
    a = AuditLog()
    a.append("e", {"x": 1})
    with pytest.raises(sqlite3.DatabaseError):
        a.connection.execute("UPDATE audit SET payload='{}'")
    with pytest.raises(sqlite3.DatabaseError):
        a.connection.execute("DELETE FROM audit")


def test_tamper_detected():
    a = AuditLog()
    a.append("e", {"x": 1})
    a.append("e", {"x": 2})
    a.connection.execute("DROP TRIGGER audit_no_update")
    a.connection.execute("UPDATE audit SET payload='{\"x\":99}' WHERE seq=1")
    with pytest.raises(AuditTamperError):
        a.verify()


def test_audit_redacts_secrets():
    a = AuditLog()
    a.append("e", {"api_key": "AKIA123", "note": "POLYGON_API_KEY=abc123"})
    p = a.entries()[0]["payload"]
    assert p["api_key"] == REDACTED and "abc123" not in p["note"]


def test_persistent_file(tmp_path):
    f = str(tmp_path / "a.sqlite")
    AuditLog(f).append("e", {"a": 1})
    b = AuditLog(f)
    b.append("e", {"a": 2})
    assert b.verify() == 2


@pytest.mark.parametrize("text,secret", [
    ("ALPACA_API_SECRET_KEY=sk_live_xyz", "sk_live_xyz"),
    ("Authorization: Bearer eyJhbGciOi.abc", "eyJhbGciOi.abc"),
    ("postgresql://u:hunter2@db:5432/x", "hunter2"),
    ("-----BEGIN EC PRIVATE KEY-----\nMHcCAQ\n-----END EC PRIVATE KEY-----", "MHcCAQ"),
])
def test_redact_text(text, secret):
    assert secret not in redact_text(text)


def test_redact_nested_keys():
    out = redact({"creds": {"password": "p", "user": "u"}, "list": [{"token": "t"}]})
    assert out["creds"]["password"] == REDACTED and out["creds"]["user"] == "u" and out["list"][0]["token"] == REDACTED


def test_formatter_redacts():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "connecting with OANDA_API_TOKEN=tok123", None, None)
    rec.fields = {"secret": "s3", "symbol": "SPY"}
    line = json.loads(JsonRedactingFormatter().format(rec))
    assert "tok123" not in line["msg"] and line["fields"]["secret"] == REDACTED and line["fields"]["symbol"] == "SPY"
