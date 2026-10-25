"""Integrations registry, status endpoint, connectivity script and Alpaca paper reconciliation. All HTTP is mocked."""
from __future__ import annotations

import json

import pytest

from atlas.integrations import registry

SECRETS = {"ALPACA_API_KEY_ID": "PKTESTKEY1234567890", "ALPACA_API_SECRET_KEY": "s" * 40, "FRED_API_KEY": "f" * 32,
           "ATLAS_SEC_USER_AGENT": "ATLASResearch ops@example.com", "POLYGON_API_KEY": "polysecretvalue123",
           "TELEGRAM_BOT_TOKEN": "123:telegramsecret", "TELEGRAM_CHAT_ID": "42"}


class AlpacaHttp:
    def __init__(self, account="PA123", fills=None, orders=None, positions=None):
        self.calls, self.account = [], account
        self.fills = fills or []
        self.orders = orders or []
        self.positions = positions or []

    def request(self, method, url, headers, json_body=None):
        self.calls.append((method, url))
        assert url.startswith("https://paper-api.alpaca.markets/") and method == "GET", (method, url)
        if url.endswith("/v2/account"):
            return {"account_number": self.account, "status": "ACTIVE", "currency": "USD", "cash": "90000", "equity": "100500", "buying_power": "180000"}
        if "/v2/clock" in url:
            return {"is_open": False}
        if "activities/FILL" in url:
            return self.fills
        if "/v2/orders" in url:
            return self.orders
        if "/v2/positions" in url:
            return self.positions
        raise AssertionError(url)


def _no_net(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("real network call attempted")
    monkeypatch.setattr("urllib.request.urlopen", boom)


def test_inventory_covers_known_services():
    ids = {s.id for s in registry.SERVICES}
    assert {"alpaca", "sec_edgar", "fred", "polygon", "finnhub", "tiingo", "twelvedata", "alphavantage", "databento", "oanda",
            "tradier", "questrade", "ibkr", "alerts_telegram", "alerts_discord", "alerts_slack", "external_mcp"} <= ids
    for v in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ATLAS_SEC_USER_AGENT", "FRED_API_KEY", "ATLAS_ALERTS_ENABLED"):
        assert v in registry.ALL_VARS


def test_env_example_lists_every_var_with_no_secret_values():
    from pathlib import Path
    text = Path(__file__).resolve().parents[2].joinpath(".env.example").read_text()
    keys = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            keys[k] = v
    paid = {l.split(": ", 1)[1].split("=", 1)[0] for l in text.splitlines() if l.startswith("# not used (paid): ")}
    for v in registry.ALL_VARS:
        assert v in keys or v in paid, v
    for k, v in keys.items():
        if any(t in k for t in ("KEY", "SECRET", "TOKEN", "WEBHOOK", "CHAT_ID")) or k == "ATLAS_SEC_USER_AGENT":
            assert v == "", k
    assert keys["ALPACA_BASE_URL"] == "https://paper-api.alpaca.markets" and keys["ATLAS_ALERTS_ENABLED"] == "false"


def test_status_not_configured_by_default(monkeypatch):
    _no_net(monkeypatch)
    rep = registry.status(env={}, probe=True)
    by = {r["id"]: r for r in rep["services"]}
    assert not by["alpaca"]["configured"] and by["alpaca"]["mode"] == "paper" and by["alpaca"]["reachable"] is None
    assert by["alerts_slack"]["mode"] == "off" and rep["execution_permission"] == "none"


def test_status_never_echoes_secrets_and_probes_are_mocked(monkeypatch):
    _no_net(monkeypatch)
    probes = {"alpaca": lambda env: registry.probe_alpaca(env, transport=_adapt(AlpacaHttp())),
              "sec_edgar": lambda env: registry.probe_sec_edgar(env, get=lambda u, h: {"cik": "320193"}),
              "fred": lambda env: registry.probe_fred(env, get=lambda u, h: (_ for _ in ()).throw(RuntimeError(f"boom {u}")))}
    rep = registry.status(env=dict(SECRETS), probe=True, probes=probes)
    blob = json.dumps(rep)
    for v in SECRETS.values():
        if len(v) > 4 and "@" not in v:
            assert v not in blob, "secret echoed"
    by = {r["id"]: r for r in rep["services"]}
    assert by["alpaca"]["configured"] and by["alpaca"]["reachable"] is True
    assert by["sec_edgar"]["reachable"] is True and by["fred"]["reachable"] is False and "***" in by["fred"]["detail"]


def test_live_alpaca_refused_and_not_contacted(monkeypatch):
    _no_net(monkeypatch)
    called = []
    rep = registry.status(env={**SECRETS, "ALPACA_BASE_URL": "https://api.alpaca.markets"}, probe=True,
                          probes={"alpaca": lambda env: called.append(1) or {"reachable": True, "detail": ""}})
    by = {r["id"]: r for r in rep["services"]}
    assert by["alpaca"]["mode"] == "live_refused" and not called and rep["summary"]["live_refused"] == ["alpaca"]
    assert registry.mode_for(next(s for s in registry.SERVICES if s.id == "oanda"), {"OANDA_ENV": "live"}) == "live_refused"


def test_live_account_refused_by_probe():
    r = registry.probe_alpaca(dict(SECRETS), transport=_adapt(AlpacaHttp(account="LIVE9")))
    assert r["reachable"] is None and r["detail"] == "refused_live_account"


def _adapt(http):
    class T:
        def request(self, method, url, headers, json_body=None):
            return http.request(method, url, headers, json_body)
    return T()


def test_check_script_read_only_and_checklist(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    _no_net(monkeypatch)
    p = Path(__file__).resolve().parents[2] / "scripts" / "check_integrations.py"
    spec = importlib.util.spec_from_file_location("check_integrations", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    http = AlpacaHttp()
    probes = {"alpaca": lambda env: registry.probe_alpaca(env, transport=_adapt(http)),
              "sec_edgar": lambda env: {"reachable": True, "detail": "ok"}, "fred": lambda env: {"reachable": True, "detail": "ok"}}
    rc = mod.main([], env=dict(SECRETS), probes=probes)
    out = capsys.readouterr().out
    assert rc == 0 and "Checklist" in out and "FINNHUB_API_KEY" in out
    assert all(m == "GET" for m, _ in http.calls)
    for v in SECRETS.values():
        if len(v) > 4 and "@" not in v:
            assert v not in out
    assert mod.main([], env={}, probes=probes) == 0 and "ALPACA_API_KEY_ID" in capsys.readouterr().out


def test_reconcile_paper_account():
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    from atlas.ext.alpaca_reconcile import reconcile
    orders = [{"id": "o1", "client_order_id": "atlas-cp1", "symbol": "SPY", "side": "buy", "qty": "5", "filled_qty": "5", "status": "filled"},
              {"id": "o2", "client_order_id": "manual", "symbol": "AAPL", "side": "buy", "qty": "1", "filled_qty": "1", "status": "filled"}]
    fills = [{"id": "f1", "order_id": "o1", "symbol": "SPY", "side": "buy", "qty": "5", "price": "100"},
             {"id": "f2", "order_id": "o2", "symbol": "AAPL", "side": "buy", "qty": "1", "price": "200"}]
    positions = [{"symbol": "SPY", "qty": "5", "side": "long", "avg_entry_price": "100"}, {"symbol": "AAPL", "qty": "1", "side": "long"}]
    http = AlpacaHttp(fills=fills, orders=orders, positions=positions)
    b = AlpacaPaperBroker(env=dict(SECRETS), transport=http)
    if b.status != "ok":
        pytest.skip(b.reason)
    r = reconcile(b)
    assert r["status"] == "ok" and r["account"]["equity"] == 100500.0 and r["account"]["cash"] == 90000.0
    assert r["execution_permission"] == "none" and r["paper_only"] is True
    chk = {c["check"]: c["ok"] for c in r["checks"]}
    assert chk == {"fills_match_orders": True, "orders_via_control_plane": False, "positions_match_fills": True}
    assert r["orders"][0]["control_plane_order_id"] == "cp1" and r["orders"][1]["origin"] == "outside_control_plane"
    assert all(m == "GET" for m, _ in http.calls)
    live = AlpacaPaperBroker(env=dict(SECRETS), transport=AlpacaHttp(account="LIVE1"))
    assert reconcile(live)["status"] == "refused_live_account"
    assert live.get_positions()["status"] == "refused_live_account"


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    _no_net(monkeypatch)
    for k in registry.ALL_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(registry, "load_env", lambda *a, **k: dict(SECRETS))
    c = TestClient(app)
    body = c.get("/api/integrations/status").text
    assert "configured" in body and all(v not in body for v in SECRETS.values() if "@" not in v)
    assert c.get("/api/ext/alpaca/reconcile").status_code == 200


def test_envfile_loader_keeps_existing_and_skips_blank(tmp_path):
    from atlas.envfile import load_env_file
    p = tmp_path / ".env"
    p.write_text("A=1\nB=\nC=<placeholder>\nD=new  # comment\n")
    env = {"D": "old"}
    assert load_env_file(p, env) == ["A"] and env == {"D": "old", "A": "1"}
