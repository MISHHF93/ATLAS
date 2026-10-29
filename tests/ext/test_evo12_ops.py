"""evo-12: Healthchecks dead-man ping, Sentry init, ntfy alert channel, Alpaca env aliases. All no-ops unless configured."""
from __future__ import annotations

import pytest

from atlas import envalias
from atlas.ext import alerts
from atlas.ops import healthchecks, sentry_init

URL = "https://hc-ping.com/00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def _reset():
    healthchecks.reset_for_tests()
    yield
    healthchecks.reset_for_tests()


# ---------------- Healthchecks ----------------
def test_healthchecks_noop_without_url():
    assert healthchecks.ping(env={}, post=lambda u: 200) == {"sent": False, "reason": "not configured"}
    assert not healthchecks.configured({})


def test_healthchecks_rejects_non_http_urls():
    for bad in ("file:///etc/passwd", "ftp://x/y", "hc-ping.com/abc", "javascript:alert(1)"):
        assert healthchecks.ping(env={"HEALTHCHECKS_PING_URL": bad}, post=lambda u: 200)["reason"] == "not configured"


def test_healthchecks_sends_and_throttles_and_fail_bypasses():
    got = []
    env = {"HEALTHCHECKS_PING_URL": URL + "/"}
    r = healthchecks.ping(env=env, post=lambda u: got.append(u) or 200, sync=True, now=1000.0)
    assert r == {"sent": True, "http_status": 200} and got == [URL]
    assert healthchecks.ping(env=env, post=lambda u: 200, sync=True, now=1030.0)["reason"] == "throttled"
    assert healthchecks.ping(env=env, post=lambda u: got.append(u) or 200, sync=True, now=1061.0)["sent"]
    f = healthchecks.fail(env=env, post=lambda u: got.append(u) or 200, sync=True, now=1062.0)
    assert f["sent"] and got[-1] == URL + "/fail"


def test_healthchecks_errors_never_raise_and_never_echo_url():
    def boom(u):
        raise OSError("down " + u)
    r = healthchecks.ping(env={"HEALTHCHECKS_PING_URL": URL}, post=boom, sync=True, now=5.0)
    assert r["sent"] is False and URL not in repr(r)


def test_healthchecks_never_sends_under_pytest_without_injected_post():
    assert healthchecks.ping(env={"HEALTHCHECKS_PING_URL": URL})["reason"] == "never sends under pytest"


def test_healthchecks_async_does_not_block():
    import threading
    gate, seen = threading.Event(), []

    def slow(u):
        seen.append(u)
        gate.wait(2)
        return 200
    env = {"HEALTHCHECKS_PING_URL": URL}
    assert healthchecks.ping(env=env, post=slow, now=1.0)["sent"]
    assert healthchecks.ping("fail", env=env, post=slow, now=2.0)["reason"] == "ping in flight"
    gate.set()


def test_runner_beats_after_safety_step(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(healthchecks, "beat", lambda **k: calls.append("beat"))
    from atlas.ops import runner
    runner.main(["--config", "config/founder", "--var", str(tmp_path), "--iterations", "1"])
    assert calls == ["beat"]


# ---------------- Sentry ----------------
def test_sentry_noop_without_dsn_or_under_pytest(monkeypatch):
    assert sentry_init.init(env={})["enabled"] is False
    monkeypatch.setenv("SENTRY_DSN", "https://k@o0.ingest.sentry.io/1")
    assert sentry_init.init_from_env() == {"enabled": False, "reason": "disabled under pytest"}


def test_sentry_before_send_strips_secrets():
    ev = {"request": {"url": "https://x/settings?reset=TOKEN123", "query_string": "reset=TOKEN123", "cookies": {"atlas_session": "S"},
                      "data": {"password": "pw"}, "headers": {"Cookie": "atlas_session=S", "Authorization": "Bearer z", "User-Agent": "ua"}},
          "user": {"email": "a@b.c"}, "extra": {"api_key": "K", "n": 1}}
    out = sentry_init.before_send(ev)
    s = repr(out)
    for secret in ("TOKEN123", "atlas_session=S", "Bearer z", "pw", "a@b.c", "'K'"):
        assert secret not in s
    assert out["request"]["headers"]["User-Agent"] == "ua" and out["extra"]["n"] == 1


def test_sentry_init_with_dsn_uses_conservative_defaults():
    sentry_sdk = pytest.importorskip("sentry_sdk")
    sent = []

    class T(sentry_sdk.transport.Transport):
        def capture_envelope(self, envelope):
            sent.append(envelope)
    r = sentry_init.init(env={"SENTRY_DSN": "https://pub@o0.ingest.sentry.io/1", "ATLAS_ENV": "production",
                              "SENTRY_TRACES_SAMPLE_RATE": "7"}, transport=T())
    try:
        assert r == {"enabled": True, "traces_sample_rate": 1.0, "environment": "production"}
        opts = sentry_sdk.get_client().options
        assert not opts.get("send_default_pii") and opts["before_send"] is sentry_init.before_send
        sentry_sdk.capture_message("hello")
        sentry_sdk.flush(2)
        assert sent
    finally:
        sentry_sdk.get_client().close()


def test_sentry_bad_dsn_does_not_crash():
    pytest.importorskip("sentry_sdk")
    assert sentry_init.init(env={"SENTRY_DSN": "not a dsn"})["enabled"] is False


# ---------------- ntfy ----------------
def test_ntfy_disabled_by_default_and_under_pytest():
    cfg = {"NTFY_TOPIC": "a-long-random-topic"}
    assert alerts.status(cfg)["enabled"] is False and alerts.status(cfg)["channels_configured"]["ntfy"] is True
    r = alerts.dispatch("hi", ("ntfy",), cfg=cfg, post=lambda *a, **k: pytest.fail("must not send"))
    assert r["any_sent"] is False and "disabled" in r["results"][0]["reason"]
    r = alerts.dispatch("hi", ("ntfy",), cfg={**cfg, "ATLAS_ALERTS_ENABLED": "true"}, post=lambda *a, **k: pytest.fail("must not send"))
    assert r["results"][0]["reason"] == "never sends under pytest"


def test_ntfy_payload_and_token(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    sent = []
    cfg = {"ATLAS_ALERTS_ENABLED": "true", "NTFY_TOPIC": "a-long-random-topic", "NTFY_URL": "https://ntfy.example.org/"}
    r = alerts.dispatch("body text", ("ntfy",), cfg=cfg, post=lambda url, body: sent.append((url, body)) or 200)
    assert r["any_sent"] and sent[0][0] == "https://ntfy.example.org"
    assert sent[0][1]["topic"] == "a-long-random-topic" and sent[0][1]["message"] == "body text"
    hdr = []
    alerts.dispatch("x", ("ntfy",), cfg={**cfg, "NTFY_TOKEN": "tk_abc"}, post=lambda url, body, headers: hdr.append(headers) or 200)
    assert hdr == [{"Authorization": "Bearer tk_abc"}]


def test_ntfy_default_server_and_bad_config(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    sent = []
    alerts.dispatch("x", ("ntfy",), cfg={"ATLAS_ALERTS_ENABLED": "true", "NTFY_TOPIC": "topic-12345"}, post=lambda u, b: sent.append(u) or 200)
    assert sent == ["https://ntfy.sh"]
    for topic in ("", "has space", "../x", "x" * 65):
        r = alerts.dispatch("x", ("ntfy",), cfg={"ATLAS_ALERTS_ENABLED": "true", "NTFY_TOPIC": topic}, post=lambda u, b: pytest.fail("no"))
        assert r["results"][0]["reason"] == "channel not configured"
    r = alerts.dispatch("x", ("ntfy",), cfg={"ATLAS_ALERTS_ENABLED": "true", "NTFY_TOPIC": "topic-12345", "NTFY_URL": "javascript:x"}, post=lambda u, b: pytest.fail("no"))
    assert r["results"][0]["reason"] == "NTFY_URL must be http(s)"


def test_registry_lists_new_services_off_by_default():
    from atlas.integrations import registry
    ids = {s.id: s for s in registry.SERVICES}
    for k in ("alerts_ntfy", "healthchecks", "sentry"):
        assert k in ids and ids[k].default_on is False
    rep = registry.status(env={})
    assert {r["id"]: r["mode"] for r in rep["services"]}["alerts_ntfy"] == "off"


# ---------------- Alpaca env aliases ----------------
def test_alpaca_aliases_fill_canonical_names():
    for kid, sec in (("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"), ("ALPACA_API_KEY", "ALPACA_API_SECRET")):
        env = envalias.apply({kid: "PKTEST12345678", sec: "s3cr3t"})
        assert env["ALPACA_API_KEY_ID"] == "PKTEST12345678" and env["ALPACA_API_SECRET_KEY"] == "s3cr3t"


def test_canonical_wins_and_placeholders_are_blank():
    env = envalias.apply({"ALPACA_API_KEY_ID": "CANON", "ALPACA_API_KEY": "OLD", "ALPACA_API_SECRET_KEY": "<paste>", "ALPACA_SECRET_KEY": "sec"})
    assert env["ALPACA_API_KEY_ID"] == "CANON" and env["ALPACA_API_SECRET_KEY"] == "sec"


def test_alias_in_dotenv_and_environ_reach_every_reader(tmp_path, monkeypatch):
    from atlas.control.policy.loader import parse_env_file
    from atlas.envfile import load_env_file
    from atlas.execution.adapters.alpaca import AlpacaPaperBroker
    from atlas.integrations import registry
    f = tmp_path / ".env"
    f.write_text("ALPACA_API_KEY=PKFILE1234567\nALPACA_SECRET_KEY=filesecret\n")
    assert parse_env_file(f)["ALPACA_API_KEY_ID"] == "PKFILE1234567"
    for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert AlpacaPaperBroker(env_file=f, transport=object()).status == "ok"
    assert registry.load_env(f)["ALPACA_API_KEY_ID"] == "PKFILE1234567"
    env: dict[str, str] = {}
    load_env_file(f, env)
    assert env["ALPACA_API_KEY_ID"] == "PKFILE1234567" and env["ALPACA_API_SECRET_KEY"] == "filesecret"
    monkeypatch.setenv("APCA_API_KEY_ID", "PKPROC123456")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "procsecret")
    from atlas.accounts import credentials
    assert credentials.effective_environ()["ALPACA_API_KEY_ID"] == "PKPROC123456"
    assert registry.load_env(tmp_path / "none")["ALPACA_API_SECRET_KEY"] == "procsecret"
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
