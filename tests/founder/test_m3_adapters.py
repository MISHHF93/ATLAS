import pytest

from founder_conftest import intent
from atlas.marketdata.pit.providers.base import ProviderDisabled
from atlas.execution.adapters import AlpacaPaperAdapter, ExecutionRouter, IbkrPaperAdapter
from atlas.execution.adapters.guards import guard_alpaca_url, guard_ibkr_account, guard_ibkr_port
from atlas.risk import RiskDecision
from atlas.risk.safety import LiveTradingForbidden

KEY, SECRET = "PKFIXTURE0000000000", "fixture-secret-not-real-0000"


def ok(i):
    return RiskDecision(intent_id=i.intent_id, approved=True, reasons=[], checks={}, halted=False, policy_version=4)


class MockHttp:
    def __init__(self, account_number="PA1234567"):
        self.calls = []
        self.account_number = account_number

    def request(self, method, url, headers, json=None):
        self.calls.append((method, url, headers, json))
        if url.endswith("/v2/account"):
            return {"account_number": self.account_number, "cash": "20000.00", "status": "ACTIVE"}
        if method == "POST" and url.endswith("/v2/orders"):
            return {"id": "ord-1", "client_order_id": json["client_order_id"], "status": "accepted"}
        if method == "DELETE" and "/v2/orders" in url:
            return [{"id": "a"}, {"id": "b"}]
        if method == "DELETE" and "/v2/positions" in url:
            return [{"symbol": "SPY"}]
        if url.endswith("/v2/positions"):
            return [{"symbol": "SPY", "qty": "3"}]
        raise KeyError(url)


@pytest.mark.parametrize("url", ["https://api.alpaca.markets", "http://paper-api.alpaca.markets",
                                 "https://paper-api.alpaca.markets.evil.com", "https://paper-api.alpaca.markets:8443"])
def test_alpaca_live_or_odd_urls_blocked(url):
    with pytest.raises(LiveTradingForbidden):
        AlpacaPaperAdapter(KEY, SECRET, base_url=url)


@pytest.mark.parametrize("port", [4001, 7496, 80, 0])
def test_ibkr_live_ports_blocked(port):
    with pytest.raises(LiveTradingForbidden):
        IbkrPaperAdapter(port=port)


@pytest.mark.parametrize("acct", ["U1234567", "", "F123"])
def test_ibkr_live_account_blocked(acct):
    with pytest.raises(LiveTradingForbidden):
        IbkrPaperAdapter(port=4002, account=acct, enabled=True, client=object())


def test_guards_accept_paper():
    assert guard_alpaca_url("https://paper-api.alpaca.markets/v2/orders")
    assert guard_ibkr_port(4002) == 4002 and guard_ibkr_port(7497) == 7497
    assert guard_ibkr_account("DU123")


def test_alpaca_off_by_default():
    a = AlpacaPaperAdapter(KEY, SECRET)
    with pytest.raises(ProviderDisabled):
        a.cash()
    with pytest.raises(ProviderDisabled):
        AlpacaPaperAdapter(KEY, SECRET, enabled=True).cash()  # offline transport


def test_alpaca_placeholder_keys_rejected():
    with pytest.raises(ProviderDisabled):
        AlpacaPaperAdapter("<your-alpaca-key-id>", SECRET, enabled=True, transport=MockHttp()).cash()


def test_alpaca_submit_flow_and_idempotency():
    t = MockHttp()
    a = AlpacaPaperAdapter(KEY, SECRET, enabled=True, transport=t)
    i = intent(qty=2, limit_price=101)
    assert a.submit(i, ok(i)) == "ord-1"
    post = [c for c in t.calls if c[0] == "POST"][0]
    assert post[3]["client_order_id"] == i.intent_id and post[3]["limit_price"] == "101.0"
    assert all(c[1].startswith("https://paper-api.alpaca.markets/") for c in t.calls)
    assert a.cancel_all() == 2 and a.flatten_all() == 1 and a.positions_qty() == {"SPY": 3.0}
    assert KEY not in repr(a) and SECRET not in repr(a)


def test_alpaca_refuses_live_account():
    a = AlpacaPaperAdapter(KEY, SECRET, enabled=True, transport=MockHttp(account_number="123456789"))
    i = intent()
    with pytest.raises(LiveTradingForbidden):
        a.submit(i, ok(i))


def test_alpaca_requires_approval():
    a = AlpacaPaperAdapter(KEY, SECRET, enabled=True, transport=MockHttp())
    i = intent()
    with pytest.raises(PermissionError):
        a.submit(i, ok(i).model_copy(update={"approved": False}))


class FakeIb:
    def __init__(self, accounts=("DU999",)):
        self.accounts, self.orders, self.connected = list(accounts), [], None

    def connect(self, host, port, client_id, readonly):
        self.connected = (host, port)

    def managed_accounts(self):
        return self.accounts

    def place_order(self, contract, order):
        self.orders.append((contract, order)); return f"ib-{len(self.orders)}"

    def global_cancel(self):
        return 4

    def positions(self):
        return [{"account": "DU999", "position": 10, "contract": {"symbol": "XIC", "secType": "STK"}},
                {"account": "DU999", "position": 0, "contract": {"symbol": "ZERO"}}]

    def cash_balance(self, account, ccy):
        return 1234.5


def test_ibkr_submit_contract_mapping():
    ib = FakeIb()
    a = IbkrPaperAdapter(port=4002, account="DU999", enabled=True, client=ib)
    i = intent(symbol="XIC", currency="CAD")
    assert a.submit(i, ok(i)) == "ib-1"
    c, o = ib.orders[0]
    assert c["primaryExchange"] == "TSE" and o["orderType"] == "LMT" and o["orderRef"] == i.intent_id
    assert ib.connected == ("127.0.0.1", 4002)
    assert a.cancel_all() == 4 and a.flatten_all() == 1 and a.positions_qty()["XIC"] == 10 and a.cash() == 1234.5


def test_ibkr_rejects_connection_with_live_account():
    a = IbkrPaperAdapter(port=4002, account="DU999", enabled=True, client=FakeIb(accounts=("DU999", "U555")))
    with pytest.raises(LiveTradingForbidden):
        a.cancel_all()


def test_ibkr_off_by_default():
    with pytest.raises(ProviderDisabled):
        IbkrPaperAdapter().cancel_all()


def test_ibkr_no_crypto():
    with pytest.raises(ValueError):
        IbkrPaperAdapter.contract(intent(asset_class="crypto_spot"))


def test_router_gates_and_routes(engine, audit):
    from founder_conftest import state
    t = MockHttp()
    alp = AlpacaPaperAdapter(KEY, SECRET, enabled=True, transport=t)
    r = ExecutionRouter(engine, {"alpaca": alp}, audit)
    out = r.execute(intent(qty=1), state())
    assert out["executes"] and out["venue"] == "alpaca"
    bad = r.execute(intent(qty=10_000), state())
    assert not bad["executes"] and len([c for c in t.calls if c[0] == "POST"]) == 1
    engine.ks.engage("x", "cli")  # kill switch cancels through adapter
    assert any(c[0] == "DELETE" and "/v2/orders" in c[1] for c in t.calls)


def test_router_broker_error_counts_as_reject(engine, audit):
    from founder_conftest import state

    class Boom:
        enabled, name = True, "alpaca"
        def submit(self, i, d): raise RuntimeError("503")
        def cancel_all(self, r=""): return 0
    out = ExecutionRouter(engine, {"alpaca": Boom()}, audit).execute(intent(), state())
    assert not out["executes"] and "broker error" in out["reasons"][0]


def test_router_falls_back_to_sim_when_adapter_off(engine, audit):
    from founder_conftest import state
    from atlas.execution.paper import PaperBroker
    sim = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000)
    out = ExecutionRouter(engine, {"alpaca": AlpacaPaperAdapter(KEY, SECRET)}, audit, fallback=sim).execute(intent(), state())
    assert out["executes"] and out["venue"] == "paper_sim" and sim.fills
