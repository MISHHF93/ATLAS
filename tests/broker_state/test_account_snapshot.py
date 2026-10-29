"""Phase 1 account awareness: schema, paper sim, Alpaca/OANDA adapters (idle until verified, paper/practice only), features, API."""
from __future__ import annotations

import dataclasses
import json

import pytest

from atlas.broker_state import adapters as ad
from atlas.broker_state.features import context_text, round_trip_fee_bps, sizing_feasibility, snapshot_features
from atlas.broker_state.snapshot import AccountSnapshot, Balances, FeeSchedule, TradingRules, mask, num


def verified(monkeypatch, sid="alpaca", state="verified"):
    monkeypatch.setattr(ad, "verification_state", lambda s, env: {"state": state if s == sid else "needs_verification", "detail": f"{state}"})


class FakeAlpaca:
    def __init__(self, acct_no="PA123456789"):
        self.calls, self.acct_no = [], acct_no

    def request(self, method, url, headers, json_body=None):
        self.calls.append((method, url))
        path = url.split("alpaca.markets")[1]
        if path == "/v2/account":
            return {"account_number": self.acct_no, "status": "ACTIVE", "currency": "USD", "cash": "1.25", "equity": "1.30", "buying_power": "1.25",
                    "multiplier": "1", "pattern_day_trader": False, "trading_blocked": False, "shorting_enabled": False}
        if path.startswith("/v2/positions"):
            return [{"symbol": "SPY", "qty": "0.002", "side": "long", "avg_entry_price": "500", "market_value": "1.05", "unrealized_pl": "0.05", "asset_class": "us_equity"}]
        if path.startswith("/v2/orders"):
            return [{"id": "o1", "symbol": "QQQ", "side": "buy", "notional": "1", "type": "market", "status": "new"}]
        if path == "/v2/clock":
            return {"is_open": False, "next_open": "2026-10-30T09:30:00-04:00", "next_close": "2026-10-30T16:00:00-04:00"}
        raise AssertionError(path)


ENV = {"ALPACA_API_KEY_ID": "PKTESTTESTTEST", "ALPACA_API_SECRET_KEY": "s" * 40}


def test_schema_is_read_only_and_never_live():
    s = AccountSnapshot(broker="x")
    assert s.read_only and s.execution_permission == "none"
    s.execution_permission = "live"
    s.__post_init__()
    assert s.execution_permission == "none"
    with pytest.raises(ValueError):
        AccountSnapshot(broker="x", environment="live")
    with pytest.raises(ValueError):
        AccountSnapshot(broker="x", status="weird")
    assert num("1.5") == 1.5 and num(None) is None and num("nan") is None and num("x") is None
    assert mask("PA123456789") == "…6789"


def test_paper_sim_one_dollar_account():
    snap = ad.PaperSimAdapter(start_equity=1.0).fetch()
    assert snap.usable and snap.environment == "simulated"
    assert snap.balances.equity == 1.0 and snap.balances.cash == 1.0 and not snap.positions
    assert snap.rules.pdt_applies is False and snap.fees.commission_per_order == 1.0
    json.dumps(snap.to_dict())  # serialisable


def test_paper_sim_reflects_positions():
    from atlas.execution.paper.broker import PaperBroker
    from atlas.risk.models import Position
    b = PaperBroker(total_account_equity_base=1000, bot_cash_base=900)
    b.positions["SPY"] = Position(symbol="SPY", qty=2, avg_price=45, last_price=50, sleeve="core")
    snap = ad.PaperSimAdapter(book=b).fetch()
    assert snap.balances.equity == pytest.approx(1000) and snap.positions[0].market_value == pytest.approx(100)
    assert snap.positions[0].unrealized_pl == pytest.approx(10)


@pytest.mark.parametrize("state", ["needs_verification", "failed"])
def test_alpaca_is_a_noop_until_verified(monkeypatch, state):
    verified(monkeypatch, state=state)
    t = FakeAlpaca()
    snap = ad.AlpacaPaperStateAdapter(transport=t).fetch(ENV)
    assert snap.status in ("needs_verification", "verification_failed") and not snap.usable
    assert t.calls == [] and snap.balances.equity is None


def test_alpaca_verified_maps_account(monkeypatch):
    verified(monkeypatch)
    t = FakeAlpaca()
    snap = ad.AlpacaPaperStateAdapter(transport=t).fetch(ENV)
    assert snap.usable and snap.environment == "paper" and snap.account_ref == "…6789"
    assert snap.balances.equity == 1.30 and snap.balances.buying_power == 1.25 and snap.rules.min_order_notional == 1.0
    assert snap.positions[0].symbol == "SPY" and snap.open_orders[0].notional == 1.0 and snap.market.is_open is False
    assert all(m == "GET" for m, _ in t.calls)                   # read-only
    assert all("paper-api.alpaca.markets" in u for _, u in t.calls)
    assert "PA123456789" not in json.dumps(snap.to_dict())     # account number is masked
    assert "PKTESTTESTTEST" not in json.dumps(snap.to_dict())


def test_alpaca_refuses_live_account_and_live_url(monkeypatch):
    verified(monkeypatch)
    snap = ad.AlpacaPaperStateAdapter(transport=FakeAlpaca(acct_no="AB999999")).fetch(ENV)
    assert snap.status == "refused_live" and not snap.usable
    live = ad.AlpacaPaperStateAdapter(transport=FakeAlpaca()).fetch({**ENV, "ALPACA_BASE_URL": "https://api.alpaca.markets"})
    assert live.status == "refused_live"


def test_alpaca_not_configured_without_keys(monkeypatch):
    verified(monkeypatch)
    t = FakeAlpaca()
    snap = ad.AlpacaPaperStateAdapter(transport=t).fetch({})
    assert snap.status == "not_configured" and t.calls == []


OANDA_ENV = {"OANDA_API_TOKEN": "t" * 30, "OANDA_ACCOUNT_ID": "101-004-1435156-001"}


def oanda_get(calls):
    def get(url, headers):
        calls.append(url)
        assert "api-fxpractice.oanda.com" in url and headers["Authorization"].startswith("Bearer ")
        if url.endswith("/summary"):
            return {"account": {"currency": "CAD", "balance": "50.00", "NAV": "49.50", "marginUsed": "2.00", "marginAvailable": "47.50", "marginRate": "0.02"}}
        if url.endswith("/openPositions"):
            return {"positions": [{"instrument": "EUR_USD", "long": {"units": "0"}, "short": {"units": "-100"}, "unrealizedPL": "-0.5"}]}
        if url.endswith("/pendingOrders"):
            return {"orders": [{"id": "7", "instrument": "USD_CAD", "units": "50", "type": "LIMIT", "state": "PENDING"}]}
        if "/instruments" in url:
            return {"instruments": [{"name": "EUR_USD", "minimumTradeSize": "1", "tradeUnitsPrecision": 0}]}
        raise AssertionError(url)
    return get


def test_oanda_noop_until_verified(monkeypatch):
    verified(monkeypatch, sid="oanda", state="needs_verification")
    calls = []
    snap = ad.OandaPracticeStateAdapter(get_json=oanda_get(calls)).fetch(OANDA_ENV)
    assert snap.status == "needs_verification" and calls == []


def test_oanda_verified_maps_account(monkeypatch):
    verified(monkeypatch, sid="oanda")
    calls = []
    snap = ad.OandaPracticeStateAdapter(get_json=oanda_get(calls)).fetch(OANDA_ENV)
    assert snap.usable and snap.environment == "practice" and snap.currency == "CAD"
    assert snap.balances.equity == 49.5 and snap.balances.leverage_max == pytest.approx(50)
    assert snap.rules.min_order_qty == 1.0 and snap.positions[0].side == "short" and snap.positions[0].qty == 100
    assert snap.open_orders[0].side == "buy" and "101-004-1435156-001" not in json.dumps(snap.to_dict())


def test_oanda_live_env_refused_without_a_request(monkeypatch):
    verified(monkeypatch, sid="oanda")
    calls = []
    snap = ad.OandaPracticeStateAdapter(get_json=oanda_get(calls)).fetch({**OANDA_ENV, "OANDA_ENV": "live"})
    assert snap.status == "refused_live" and calls == []


def test_oanda_error_is_a_status_not_an_exception(monkeypatch):
    verified(monkeypatch, sid="oanda")

    def boom(url, headers):
        raise RuntimeError("HTTP 401")
    snap = ad.OandaPracticeStateAdapter(get_json=boom).fetch(OANDA_ENV)
    assert snap.status == "error" and "401" in snap.reason and "ttt" not in snap.reason


def test_adapters_have_no_write_methods():
    for cls in (ad.PaperSimAdapter, ad.AlpacaPaperStateAdapter, ad.OandaPracticeStateAdapter):
        names = {n for n in dir(cls) if not n.startswith("_")}
        assert not names & {"submit", "place_order", "cancel", "cancel_all", "flatten_all", "transfer"}, cls


def snap_with(eq, mn=1.0, **kw):
    return AccountSnapshot(broker="t", balances=Balances(cash=eq, equity=eq, buying_power=eq, **kw), rules=TradingRules(min_order_notional=mn, fractional=True))


def test_sizing_feasibility_one_dollar_cannot_meet_policy():
    f = sizing_feasibility(snap_with(1.0), risk_fraction=0.005, stop_distance_frac=0.02)
    assert f["ideal_notional"] == 0.25 and f["feasible"] is False
    assert f["forced_risk_fraction"] == 0.02          # the $1 minimum would risk 2% of the account, 4x the 0.5% policy
    assert f["min_equity_for_policy"] == 4.0


def test_sizing_feasibility_larger_account_ok_and_unknowns_stay_none():
    f = sizing_feasibility(snap_with(1000.0))
    assert f["feasible"] is True and f["ideal_notional"] == 250.0
    empty = AccountSnapshot(broker="t", status="needs_verification")
    assert sizing_feasibility(empty)["feasible"] is None


def test_features_missing_stays_none_and_context_is_one_line():
    s = AccountSnapshot(broker="alpaca", environment="paper", status="needs_verification", reason="Press Verify.")
    f = snapshot_features(s)
    assert f["acct_usable"] is False and f["acct_equity"] is None and f["acct_cash_frac"] is None
    assert "needs_verification" in context_text(s) and "\n" not in context_text(s)
    ok = snapshot_features(snap_with(100.0))
    assert ok["acct_cash_frac"] == 1.0 and ok["acct_max_distinct_min_lots"] == 100 and ok["acct_min_order_pct_equity"] == 0.01
    assert "execution_permission=none" in context_text(snap_with(100.0))


def test_round_trip_fee_bps_flat_fee_dominates_tiny_orders():
    s = snap_with(100.0)
    s.fees = FeeSchedule(commission_per_order=1.0)
    assert round_trip_fee_bps(s, 10.0) == 2000.0     # $1 in + $1 out on a $10 trade = 20%
    assert round_trip_fee_bps(s, 1000.0) == 20.0
    assert round_trip_fee_bps(s, 0) is None


def test_api_endpoint_paper_sim_and_gated_brokers(monkeypatch):
    from fastapi.testclient import TestClient
    from atlas.api.app import app
    c = TestClient(app)
    r = c.get("/api/account/snapshot?sim_equity=1")
    assert r.status_code == 200
    d = r.json()
    assert d["execution_permission"] == "none" and d["snapshot"]["balances"]["equity"] == 1.0 and d["snapshot"]["read_only"] is True
    assert d["sizing"]["feasible"] is None or d["sizing"]["feasible"] is False
    assert {b["broker"] for b in d["brokers"]} == {"paper_sim", "alpaca", "oanda"}
    for b in ("alpaca", "oanda"):
        j = c.get(f"/api/account/snapshot?broker={b}").json()
        assert j["snapshot"]["status"] in ("needs_verification", "not_configured") and j["snapshot"]["balances"]["equity"] is None
    j = c.get("/api/account/snapshot?broker=ibkr").json()
    assert j["snapshot"]["status"] == "not_configured" and "phase 2" in j["snapshot"]["reason"]
    assert c.get("/api/account/snapshot?sim_equity=0").status_code == 422
    assert dataclasses.is_dataclass(AccountSnapshot)
