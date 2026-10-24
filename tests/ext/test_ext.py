"""ATLAS ext-1 (seven-repo gap) tests: offline, no network, no sends."""
from __future__ import annotations

import json
import math
from decimal import Decimal

import pytest

from atlas.ext import agents, alerts, dcf, dossier, edgar, mcp, options, personas, pine, pricevol, var
from atlas.features.price_action.bars import Bar


def _bars(n=260, dur=86400, start=1_700_006_400, drift=0.002, seed=3):
    import random
    rnd, out, p = random.Random(seed), [], 100.0
    for i in range(n):
        o = p
        p = max(1.0, p * (1 + drift + rnd.gauss(0, 0.012)))
        hi, lo = max(o, p) * (1 + abs(rnd.gauss(0, 0.004))), min(o, p) * (1 - abs(rnd.gauss(0, 0.004)))
        out.append(Bar(start + i * dur, dur, o, hi, lo, p, 1000 + rnd.random() * 500))
    return out


# ---------- options ----------
def test_bs_price_and_parity():
    c = options.price(100, 100, 0.5, 0.2, 0.03, "call")
    p = options.price(100, 100, 0.5, 0.2, 0.03, "put")
    assert c - p == pytest.approx(100 - 100 * math.exp(-0.015), abs=1e-9)
    assert options.price(100, 100, 1, 0.2) == pytest.approx(7.9656, abs=1e-3)   # textbook ATM r=0


def test_greeks_signs_and_iv_roundtrip():
    g = options.greeks(100, 105, 0.25, 0.3, 0.01, "put")
    assert -1 < g["delta"] < 0 and g["gamma"] > 0 and g["vega"] > 0 and g["theta"] < 0
    px = options.price(100, 95, 0.4, 0.37, 0.02, "call")
    assert options.implied_vol(px, 100, 95, 0.4, 0.02, "call") == pytest.approx(0.37, abs=1e-5)
    assert options.implied_vol(0.0001, 100, 50, 0.4) is None            # below intrinsic -> no solution
    with pytest.raises(ValueError):
        options.price(-1, 100, 1, 0.2)


def test_options_chain_is_unavailable_not_fabricated():
    c = options.options_chain("SPY")
    assert c["status"] == "unavailable" and c["rows"] == []


# ---------- VaR ----------
def test_parametric_var_matches_normal():
    import random
    rnd = random.Random(1)
    x = [rnd.gauss(0, 0.01) for _ in range(20000)]
    v = var.parametric_var(x, 0.95)
    assert v["var"] == pytest.approx(1.645 * 0.01, rel=0.05)
    assert v["cvar"] > v["var"]
    rep = var.var_report(x)
    assert rep["parametric_95"]["var"] == pytest.approx(v["var"])


def test_portfolio_var_components_sum():
    import random
    rnd = random.Random(2)
    r = {"A": [rnd.gauss(0, .01) for _ in range(500)], "B": [rnd.gauss(0, .02) for _ in range(500)]}
    out = var.portfolio_parametric_var({"A": 1000, "B": 500}, r, 0.99)
    assert sum(out["component_var_usd"].values()) == pytest.approx(2.3263478740 * out["sigma_usd"], rel=1e-6)


# ---------- DCF ----------
def test_dcf_fcff_hand_computed():
    i = dcf.DCFInputs(100, (0.0,), 0.10, 0.0, net_debt=0, shares_outstanding=10)
    r = dcf.dcf_fcff(i)
    # one year of 100 discounted + perpetuity 100/0.1 discounted one year = 90.909 + 909.09
    assert r.enterprise_or_equity_value == pytest.approx(1000.0, rel=1e-9)
    assert r.per_share == pytest.approx(100.0)
    with pytest.raises(ValueError):
        dcf.dcf_fcff(dcf.DCFInputs(100, (0.05,), 0.02, 0.03))
    assert dcf.fcff_from_statements(100, 0.25, 10, 20, 5) == pytest.approx(60)


# ---------- EDGAR ----------
def _fact(v, end, filed, start=None, form="10-K"):
    d = {"val": v, "end": end, "filed": filed, "form": form, "accn": filed}
    if start:
        d["start"] = start
    return d


FACTS = {"cik": 320193, "entityName": "Test Co", "facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [_fact(1000, "2023-12-31", "2024-02-01", "2023-01-01"), _fact(1100, "2024-12-31", "2025-02-01", "2024-01-01"),
                                   _fact(1150, "2024-12-31", "2025-06-01", "2024-01-01", "10-K/A"),
                                   _fact(300, "2024-09-30", "2024-11-01", "2024-07-01", "10-Q")]}},
    "NetIncomeLoss": {"units": {"USD": [_fact(100, "2023-12-31", "2024-02-01", "2023-01-01"), _fact(150, "2024-12-31", "2025-02-01", "2024-01-01")]}},
    "Assets": {"units": {"USD": [_fact(2000, "2023-12-31", "2024-02-01"), _fact(2200, "2024-12-31", "2025-02-01")]}},
    "StockholdersEquity": {"units": {"USD": [_fact(800, "2024-12-31", "2025-02-01")]}}}},
    "dei": {}}


def test_edgar_point_in_time_and_restatement():
    early = edgar.normalise(FACTS, as_of="2024-06-01")
    assert [p["period_end"] for p in early["periods"]] == ["2023-12-31"]               # FY24 not yet filed
    late = edgar.normalise(FACTS, as_of="2025-03-01")
    assert late["periods"][0]["income"]["revenue"] == 1100                               # before the amendment
    amended = edgar.normalise(FACTS, as_of="2025-12-31")
    assert amended["periods"][0]["income"]["revenue"] == 1150                            # latest filing wins
    assert all(p["period_end"] != "2024-09-30" for p in amended["periods"])             # 10-Q ignored


def test_edgar_client_cache_rate_limit_and_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_SEC_USER_AGENT", raising=False)
    calls = []

    def fetch(url, headers):
        calls.append((url, headers["User-Agent"]))
        return json.dumps({"0": {"ticker": "TST", "cik_str": 320193}} if "tickers" in url else FACTS).encode()

    c = edgar.EdgarClient("ATLAS-Test test@example.com", cache_dir=tmp_path, fetch=fetch)
    f1 = edgar.fundamentals("TST", "2025-12-31", c)
    f2 = edgar.fundamentals("TST", "2025-12-31", c)
    assert f1["status"] == "ok" and f2["periods"] == f1["periods"] and len(calls) == 2   # second run from cache
    assert all(ua == "ATLAS-Test test@example.com" for _, ua in calls)
    nc = edgar.EdgarClient(None, cache_dir=tmp_path / "empty", fetch=fetch)
    nc.user_agent = None
    assert edgar.fundamentals("TST", client=nc)["status"] == "not_configured"
    m = edgar.derived_metrics(f1, price=10)
    assert m["roe"] == pytest.approx(150 / 800)


# ---------- price/volume ----------
def test_vwap_profile_zones_scan():
    b = _bars(120, dur=900, drift=0.0)
    v = pricevol.session_vwap(b)
    assert v[-1] is not None and min(x.low for x in b) <= v[-1] <= max(x.high for x in b)
    prof = pricevol.volume_profile(b, 30)
    assert prof["val"] <= prof["poc"] <= prof["vah"] and prof["value_area_pct"] >= 0.70
    av = pricevol.anchored_vwap(b, b[50].start)
    assert av[49] is None and av[50] is not None
    d = _bars(200, drift=0.0, seed=9)
    for z in pricevol.sr_zones(d, "TST"):
        assert z.touch_count >= 3 and z.lower_bound <= z.upper_bound and z.zone_type == "sr_high_touch"
    out = pricevol.scan_symbol("TST", b, d)
    assert out["status"] == "ok" and isinstance(out["events"], list)


# ---------- Pine ----------
def test_pine_generation_and_stats():
    for sid in pine.supported():
        src = pine.generate(sid)
        assert src.startswith("//@version=5") and "NOT the ATLAS engine" in src and pine.lint(src) == []
    s = pine.backtest_stats([1, -1, 2, -1, -1, 3])
    assert s["n_trades"] == 6 and s["win_rate"] == 0.5 and s["profit_factor"] == pytest.approx(2.0) and s["max_drawdown_r"] == 2
    assert pine.atlas_backtest("TST", [], "sfp")["status"] == "no_data"


# ---------- dossier / personas / PM ----------
def test_dossier_deterministic_and_bounded():
    d = _bars(260, drift=0.004)
    a, b = dossier.build_dossier("TST", d), dossier.build_dossier("TST", d)
    assert a == b
    c = a["conviction"]
    assert 1 <= c["score"] <= 100 and c["label"] in ("BUY", "WATCH", "SELL")
    assert c["score"] == round(max(1, min(100, 50 + sum(x["points"] for x in c["components"]))))
    assert a["news"]["status"] == "unavailable" and a["sentiment"]["status"] == "unavailable"
    lv = a["trade_levels"]
    if lv["side"] == "long":
        assert lv["stop"] < lv["entry"] < lv["target"]
    if lv["side"] == "short":
        assert lv["target"] < lv["entry"] < lv["stop"]
    assert dossier.build_dossier("X", [])["conviction"]["label"] == "NO_DATA"


def test_personas_and_pm_weights():
    good = {"roe": .3, "debt_to_equity": .3, "operating_margin": .3, "fcf": 1e9, "pe": 12, "pb": 1.2, "current_ratio": 2.5,
            "revenue_growth": .25, "eps": 5, "fcf_yield": .1, "net_margin": .2, "gross_margin": .6}
    bad = {k: (-abs(v) if isinstance(v, float) else v) for k, v in good.items()} | {"pe": 90, "pb": 15, "debt_to_equity": 4, "current_ratio": .5}
    t = dossier.technicals(_bars())
    per = {"G": [personas.score_persona(p, good, t) for p in personas.PERSONAS], "B": [personas.score_persona(p, bad, t) for p in personas.PERSONAS]}
    pm = personas.portfolio_manager(per, max_weight=0.25)
    assert pm["target_weights"]["G"] <= 0.25 and pm["target_weights"]["B"] == 0
    assert pm["cash_weight"] == pytest.approx(1 - sum(pm["target_weights"].values()))
    assert set(pm["weight_matrix"]["G"]) == set(personas.PERSONAS)
    assert personas.score_persona("buffett", {}, {})["signal"] == "insufficient_data"


# ---------- control plane preview ----------
def _engine():
    from atlas.control.engine import ActionableControlPlaneEngine
    return ActionableControlPlaneEngine()


def test_preview_matches_submit_and_books_nothing():
    from atlas.control.engine import ActionableOrderRequest
    e = _engine()
    for req in (ActionableOrderRequest(track="open_market", instrument_id="SPY", side="buy", notional_usd=Decimal("1000"),
                                       stop_kind="structure", stop_distance_bps=Decimal("150"), data_age_ms=0),
                ActionableOrderRequest(track="open_market", instrument_id="SPY", side="buy", notional_usd=Decimal("1000"),
                                       stop_kind="structure", stop_distance_bps=Decimal("150"), data_age_ms=1e12),
                ActionableOrderRequest(track="open_market", instrument_id="SPY", side="buy", notional_usd=Decimal("1e9"),
                                       stop_kind="structure", stop_distance_bps=Decimal("150"), data_age_ms=0)):
        seq, track = (e._order_seq, e._pos_seq), e.active_track
        pv = e.preview_order(req)
        assert (e._order_seq, e._pos_seq) == seq and e.active_track == track
        dec = e.submit_order(req)
        assert pv.compliance_passed == (dec.control_plane_decision == "authorized_and_executed")
        assert tuple(pv.violations) == tuple(dec.violations)
    assert not e.preview_order(ActionableOrderRequest(track="open_market", instrument_id="SPY", side="buy", notional_usd=Decimal("1e9"),
                                                      stop_kind="structure", stop_distance_bps=Decimal("150"))).compliance_passed


# ---------- agents ----------
def test_pipeline_never_submits():
    e = _engine()
    seq = (e._order_seq, e._pos_seq)
    for drift in (0.006, -0.006, 0.0):
        ds = dossier.build_dossier("SPY", _bars(260, drift=drift))
        out = agents.run_pipeline(ds, e, data_age_ms=0)
        assert out["portfolio_manager"]["submitted"] is False and out["execution_permission"] == "none" and out["llm_used"] is False
        assert out["debate"]["verdict"] in ("bull", "bear", "no_edge")
        if out["trader_proposal"] is None:
            assert out["risk_manager"]["status"] == "skipped"
        else:
            assert out["risk_manager"]["status"] in ("approved", "rejected")
    assert (e._order_seq, e._pos_seq) == seq


# ---------- Alpaca paper ----------
class MockHttp:
    def __init__(self, account="PA123"):
        self.calls, self.account = [], account

    def request(self, method, url, headers, json_body=None):
        self.calls.append((method, url, json_body))
        assert url.startswith("https://paper-api.alpaca.markets/")
        if url.endswith("/v2/account"):
            return {"account_number": self.account, "status": "ACTIVE", "cash": "100000", "equity": "100000", "buying_power": "200000"}
        if "/v2/orders" in url and method == "POST":
            return {"id": "o1", "status": "accepted", **json_body}
        if method == "DELETE":
            return []
        return [] if "positions" in url or "orders" in url else {"is_open": False}


KEYS = {"ALPACA_API_KEY_ID": "PKTESTKEY1234567890", "ALPACA_API_SECRET_KEY": "s" * 40}


def test_alpaca_not_configured_and_live_refused():
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    b = AlpacaPaperBroker(env={})
    assert b.describe()["status"] == "not_configured" and b.get_account()["status"] == "not_configured"
    live = AlpacaPaperBroker(env={**KEYS, "ALPACA_BASE_URL": "https://api.alpaca.markets"}, transport=MockHttp())
    assert live.status == "refused_live_endpoint" and live.adapter is None
    assert live.place_order(_engine(), symbol="SPY", qty=1, side="buy", reference_price=100, stop_loss=98)["sent"] is False


def test_alpaca_reads_and_live_account_refused():
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    b = AlpacaPaperBroker(env=KEYS, transport=MockHttp())
    if b.status != "ok":
        pytest.skip(f"key validation: {b.reason}")
    assert b.get_account()["data"]["account_number"] == "PA123"
    assert b.get_positions()["status"] == "ok" and b.get_clock()["status"] == "ok" and b.cancel_all_orders()["status"] == "ok"
    bad = AlpacaPaperBroker(env=KEYS, transport=MockHttp(account="LIVE999"))
    assert bad.get_account()["status"] == "refused_live_account"


def test_alpaca_order_gated_by_control_plane():
    from atlas.ext.alpaca_paper import AlpacaPaperBroker
    http = MockHttp()
    b = AlpacaPaperBroker(env=KEYS, transport=http)
    if b.status != "ok":
        pytest.skip(f"key validation: {b.reason}")
    e = _engine()
    huge = b.place_order(e, symbol="SPY", qty=1e7, side="buy", reference_price=100, stop_loss=98, take_profit=104)
    assert huge["status"] == "rejected_by_control_plane" and huge["sent"] is False
    assert not any(m == "POST" for m, *_ in http.calls)
    ok = b.place_order(e, symbol="SPY", qty=5, side="buy", reference_price=100, stop_loss=98, take_profit=104)
    if ok["control_plane"]["decision"] == "authorized_and_executed":
        assert ok["sent"] and ok["payload"]["order_class"] == "bracket" and ok["payload"]["stop_loss"]["stop_price"] == "98"
    with pytest.raises(ValueError):
        b.place_order(e, symbol="SPY", qty=1, side="buy", reference_price=100, stop_loss=101)


# ---------- alerts ----------
def test_alerts_never_send_by_default_or_under_pytest():
    posted = []
    text = alerts.format_alert(dossier.build_dossier("TST", _bars()))
    assert "research" in text and "paper only" in text
    off = alerts.dispatch(text, cfg={}, post=lambda u, b: posted.append(u) or 200)
    assert not off["any_sent"] and all("disabled" in r["reason"] for r in off["results"])
    on = alerts.dispatch(text, cfg={"ATLAS_ALERTS_ENABLED": "true", "SLACK_WEBHOOK_URL": "https://hooks.example/x"},
                         post=lambda u, b: posted.append(u) or 200)
    assert not on["any_sent"] and posted == []                       # pytest guard
    assert alerts.status({})["enabled"] is False


# ---------- MCP ----------
def test_mcp_registry_and_jsonrpc():
    names = {t["name"] for t in mcp.list_tools()}
    assert "options_greeks" in names and not any("order" in n for n in names)
    r = mcp.call_tool("options_greeks", {"spot": 100, "strike": 100, "tte_years": 1, "vol": 0.2})
    assert r["isError"] is False and r["content"]["price"] == pytest.approx(7.9656, abs=1e-3)
    assert mcp.call_tool("nope", {})["isError"] and mcp.call_tool("options_greeks", {"evil": 1})["isError"]
    out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert out["id"] == 1 and out["result"]["tools"]
    assert mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "bogus"})["error"]["code"] == -32601
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# ---------- API ----------
def test_api_routes_offline():
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    c = TestClient(app)
    assert c.get("/api/ext/options/greeks", params=dict(spot=100, strike=100, tte_years=1, vol=0.2)).json()["price"] == pytest.approx(7.9656, abs=1e-3)
    assert c.get("/api/ext/options/greeks", params=dict(spot=-1, strike=100, tte_years=1, vol=0.2)).status_code == 400
    assert c.get("/api/ext/options/chain", params={"symbol": "SPY"}).json()["status"] == "unavailable"
    assert c.post("/api/ext/dcf", json={"base_cash_flow": 100, "growth": [0.0], "discount_rate": 0.1, "terminal_growth": 0.0}).json()["result"]["enterprise_or_equity_value"] == pytest.approx(1000)
    for u in ("/api/ext/dossier", "/api/ext/pipeline", "/api/ext/scan", "/api/ext/pine", "/api/ext/alerts/status", "/api/ext/mcp/tools", "/api/ext/alpaca/status"):
        assert c.get(u).status_code == 200, u
    assert c.get("/api/ext/pipeline").json()["portfolio_manager"]["submitted"] is False
    assert c.get("/api/ext/alerts/preview").json()["sent"] is False
    assert c.post("/api/ext/mcp/call", json={"name": "options_greeks", "arguments": {"spot": 100, "strike": 100, "tte_years": 1, "vol": 0.2}}).json()["isError"] is False
