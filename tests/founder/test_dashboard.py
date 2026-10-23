import json
import socket
import urllib.error
import urllib.request

import pytest

from founder_conftest import CONFIG_DIR
from atlas.ops.dashboard.server import build_state, serve_in_thread
from atlas.mcp.trading import build_service

TOKEN = "dash-token-0123456789abcdefXYZ"
ORDER = dict(symbol="SPY", side="buy", qty=1, order_type="limit", limit_price=100, reference_price=100,
             sleeve="core", asset_class="index_etf", broker="alpaca", quote_age_s=1.0)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def dash():
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    port = free_port()
    srv = serve_in_thread(svc, port, TOKEN)
    yield svc, port
    srv.shutdown(); srv.server_close()


def req(port, path, method="GET", body=None, headers=None):
    h = {"Host": f"127.0.0.1:{port}"} | (headers or {})
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_state_payload():
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    svc.propose_order(**ORDER)
    st = build_state(svc)
    assert st["status"]["mode"] == "paper" and len(st["approvals"]) == 1
    assert {s["name"] for s in st["sleeves"]} == {"core", "active", "high_risk", "derivatives"}
    json.dumps(st, default=str)


def test_serves_page_and_assets_with_csp(dash):
    svc, port = dash
    code, body, h = req(port, "/")
    assert code == 200 and b"PAPER ONLY" in body and b"KILL SWITCH" in body
    assert "default-src 'self'" in h["Content-Security-Policy"] and h["X-Frame-Options"] == "DENY"
    assert b"Live" not in body.replace(b"live disabled", b"")  # no live toggle
    for a in ("/static/app.js", "/static/style.css"):
        assert req(port, a)[0] == 200
    assert req(port, "/static/../server.py")[0] == 404


def test_api_state(dash):
    svc, port = dash
    code, body, _ = req(port, "/api/state")
    assert code == 200 and json.loads(body)["status"]["live_available"] is False


def test_bad_host_rejected(dash):
    svc, port = dash
    assert req(port, "/api/state", headers={"Host": "evil.example:80"})[0] == 421


def test_kill_requires_token(dash):
    svc, port = dash
    body = json.dumps({"reason": "x"}).encode()
    assert req(port, "/api/kill", "POST", body, {"Content-Type": "application/json"})[0] == 401
    assert req(port, "/api/kill", "POST", body, {"Content-Type": "application/json", "X-Dashboard-Token": "nope"})[0] == 401
    assert not svc.ks.engaged


def test_kill_cross_origin_rejected(dash):
    svc, port = dash
    code = req(port, "/api/kill", "POST", b'{"reason":"x"}', {"Content-Type": "application/json", "X-Dashboard-Token": TOKEN,
                                                              "Origin": "https://evil.example"})[0]
    assert code == 403 and not svc.ks.engaged


def test_kill_works(dash):
    svc, port = dash
    code, body, _ = req(port, "/api/kill", "POST", b'{"reason":"dashboard drill"}',
                        {"Content-Type": "application/json", "X-Dashboard-Token": TOKEN, "Origin": f"http://127.0.0.1:{port}"})
    assert code == 200 and json.loads(body)["halted"] and svc.ks.engaged
    assert svc.audit.entries("kill_switch.engage")[-1]["actor"] == "dashboard"


def test_no_other_mutations(dash):
    svc, port = dash
    for m in ("PUT", "DELETE", "PATCH"):
        assert req(port, "/api/kill", m, b"{}")[0] == 405
    assert req(port, "/api/reset", "POST", b"{}", {"X-Dashboard-Token": TOKEN})[0] == 404


def test_kill_disabled_without_token():
    svc = build_service(CONFIG_DIR); svc.heartbeat()
    port = free_port()
    srv = serve_in_thread(svc, port, token="")
    try:
        assert req(port, "/api/kill", "POST", b'{"reason":"x"}', {"Content-Type": "application/json", "X-Dashboard-Token": ""})[0] == 401
    finally:
        srv.shutdown(); srv.server_close()


def test_placeholder_token_refused():
    svc = build_service(CONFIG_DIR)
    with pytest.raises(ValueError):
        serve_in_thread(svc, free_port(), "<random-32+-char-token>")


def test_binds_localhost_only(dash):
    svc, port = dash
    s = socket.socket()
    try:
        s.settimeout(1)
        ip = socket.gethostbyname(socket.gethostname())
        if ip.startswith("127."):
            pytest.skip("no non-loopback interface")
        assert s.connect_ex((ip, port)) != 0
    finally:
        s.close()
