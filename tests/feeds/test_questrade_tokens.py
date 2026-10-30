"""Questrade refresh-token persistence, practice login and token hygiene (mocked HTTP, no network)."""
from __future__ import annotations

import json
import logging
import threading
import urllib.parse

import pytest

from atlas.feeds.core import ProviderError, RateLimiter
from atlas.feeds.providers.questrade import LOGIN_URLS, QuestradeAdapter

NOW = 1_800_000_000
SEED = "seed-token-AAAA"


class FakeHTTP:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        for key, resp in self.routes.items():
            if key in url:
                st, hd, body = resp.pop(0) if len(resp) > 1 else resp[0]
                return st, hd, body if isinstance(body, bytes) else json.dumps(body).encode()
        raise OSError("no route (test must not hit network): " + url)


def tok(access, refresh):
    return (200, {}, {"access_token": access, "api_server": "https://api01.iq.questrade.com/", "refresh_token": refresh, "expires_in": 1800})


def mk(routes, tmp_path, **extra):
    QuestradeAdapter._TOKENS.clear()   # a fresh process: nothing in memory
    env = {"QUESTRADE_REFRESH_TOKEN": SEED, "QUESTRADE_TOKEN_FILE": str(tmp_path / "var" / "questrade_token.json"), **extra}
    http = FakeHTTP(routes)
    a = QuestradeAdapter(transport=http, env=env, clock=lambda: NOW, sleep=lambda s: None, limiter=RateLimiter(1000, sleep=lambda s: None))
    return a, http


def sent_refresh(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["refresh_token"]


def test_rotated_refresh_token_is_persisted_atomically(tmp_path):
    a, http = mk({"oauth2/token": [tok("acc1", "ROT-1"), tok("acc2", "ROT-2")]}, tmp_path)
    a._session(NOW)
    path = tmp_path / "var" / "questrade_token.json"
    d = json.loads(path.read_text())
    assert d["refresh"] == "ROT-1" and d["env"] == "live" and SEED not in path.read_text()
    a._session(NOW + 4000)   # access token expired: refresh again with the rotated token, not the seed
    assert sent_refresh(http.calls[0][0]) == SEED and sent_refresh(http.calls[1][0]) == "ROT-1"
    assert json.loads(path.read_text())["refresh"] == "ROT-2"
    assert [p.name for p in path.parent.iterdir()] == ["questrade_token.json"]   # no temp file left behind


def test_restart_prefers_saved_token_over_spent_seed(tmp_path):
    a, _ = mk({"oauth2/token": [tok("acc1", "ROT-1")]}, tmp_path)
    a._session(NOW)
    b, http = mk({"oauth2/token": [tok("acc2", "ROT-2")]}, tmp_path)   # "restart": memory cleared, same .env seed
    b._session(NOW)
    assert sent_refresh(http.calls[0][0]) == "ROT-1"


def test_new_seed_in_env_wins_over_older_state_file(tmp_path):
    a, _ = mk({"oauth2/token": [tok("acc1", "ROT-1")]}, tmp_path)
    a._session(NOW)
    QuestradeAdapter._TOKENS.clear()
    env = {"QUESTRADE_REFRESH_TOKEN": "brand-new-seed", "QUESTRADE_TOKEN_FILE": str(tmp_path / "var" / "questrade_token.json")}
    http = FakeHTTP({"oauth2/token": [tok("acc3", "ROT-9")]})
    b = QuestradeAdapter(transport=http, env=env, clock=lambda: NOW, sleep=lambda s: None, limiter=RateLimiter(1000, sleep=lambda s: None))
    b._session(NOW)
    assert sent_refresh(http.calls[0][0]) == "brand-new-seed"
    assert json.loads((tmp_path / "var" / "questrade_token.json").read_text())["refresh"] == "ROT-9"


@pytest.mark.parametrize("content", ["not json", "[]", json.dumps({"env": "live", "refresh": ""}), json.dumps({"env": "practice", "seed_fp": "x", "refresh": "z"})])
def test_missing_or_invalid_state_file_falls_back_to_seed(tmp_path, content):
    path = tmp_path / "var" / "questrade_token.json"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    a, http = mk({"oauth2/token": [tok("acc", "ROT-1")]}, tmp_path)
    a._session(NOW)
    assert sent_refresh(http.calls[0][0]) == SEED


def test_login_host_defaults_to_live_and_practice_is_selectable(tmp_path):
    a, http = mk({"oauth2/token": [tok("acc", "R1")]}, tmp_path)
    a._session(NOW)
    assert http.calls[0][0].startswith("https://login.questrade.com/oauth2/token?")
    p, http = mk({"oauth2/token": [tok("acc", "R1")]}, tmp_path / "p", QUESTRADE_ENV="practice")
    p._session(NOW)
    assert http.calls[0][0].startswith("https://practicelogin.questrade.com/oauth2/token?")
    assert LOGIN_URLS == {"live": "https://login.questrade.com/oauth2/token", "practice": "https://practicelogin.questrade.com/oauth2/token"}
    bad, _ = mk({"oauth2/token": [tok("acc", "R1")]}, tmp_path / "b", QUESTRADE_ENV="sandbox")
    with pytest.raises(ProviderError):
        bad._session(NOW)


def test_state_file_from_the_other_environment_is_ignored(tmp_path):
    a, _ = mk({"oauth2/token": [tok("acc", "LIVE-ROT")]}, tmp_path)
    a._session(NOW)
    p, http = mk({"oauth2/token": [tok("acc", "P1")]}, tmp_path, QUESTRADE_ENV="practice")
    p._session(NOW)
    assert sent_refresh(http.calls[0][0]) == SEED


def test_tokens_never_logged_or_leaked_in_errors(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    a, _ = mk({"oauth2/token": [(400, {}, b'{"message":"bad token ' + SEED.encode() + b'"}')]}, tmp_path)
    with pytest.raises(ProviderError) as e:
        a._session(NOW)
    assert SEED not in str(a.health().last_error or "")
    assert SEED not in str(e.value) and SEED not in caplog.text
    # a failing save logs a warning that names no token
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, so mkdir under it fails")
    b, _ = mk({"oauth2/token": [tok("acc", "SECRET-ROT")]}, tmp_path, QUESTRADE_TOKEN_FILE=str(blocker / "sub" / "t.json"))
    assert b._session(NOW)["refresh"] == "SECRET-ROT"   # still usable from memory
    assert "SECRET-ROT" not in caplog.text and SEED not in caplog.text and "could not save" in caplog.text


def test_concurrent_sessions_refresh_once_and_candles_flow(tmp_path):
    routes = {"oauth2/token": [tok("acc1", "ROT-1"), tok("acc2", "ROT-2")],
              "symbols/search": [(200, {}, {"symbols": [{"symbolId": 8049}]})],
              "candles/8049": [(200, {}, {"candles": [{"start": "2026-09-21T09:30:00-04:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9}]})]}
    a, http = mk(routes, tmp_path)
    ts = [threading.Thread(target=a._session, args=(NOW,)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum("oauth2/token" in u for u, _ in http.calls) == 1
    assert len(a.history("SPY", "15m", NOW - 20_000_000, NOW)) == 1
    assert http.calls[-1][1]["Authorization"] == "Bearer acc1"

