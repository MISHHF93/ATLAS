import asyncio

import pytest

from founder_conftest import CONFIG_DIR, intent
from atlas.execution.paper import PaperBroker
from atlas.execution.paper.broker import CostModel
from atlas.mcp.trading import build_service
from atlas.risk import RiskDecision

TOKEN = "test-token-0123456789abcdef-xyz"
ORDER = dict(symbol="SPY", side="buy", qty=1, order_type="limit", limit_price=100, reference_price=100,
             sleeve="core", asset_class="index_etf", broker="alpaca", quote_age_s=1.0)


def ok(i):
    return RiskDecision(intent_id=i.intent_id, approved=True, reasons=[], checks={}, halted=False, policy_version=4)


def test_paper_broker_requires_approved_decision():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000)
    i = intent()
    with pytest.raises(PermissionError):
        b.submit(i, ok(intent()))  # mismatched intent id
    with pytest.raises(PermissionError):
        b.submit(i, ok(i).model_copy(update={"approved": False}))


def test_paper_broker_fill_slippage_commission():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, costs=CostModel(slippage_bps=10, commission_per_order=1))
    i = intent(qty=10, order_type="market", limit_price=None)
    b.submit(i, ok(i))
    f = b.fills[0]
    assert f.price == pytest.approx(100.1) and f.commission == 1
    assert b.bot_cash_base == pytest.approx(20_000 - 1001 - 1)


def test_limit_never_worse_than_limit():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, costs=CostModel(slippage_bps=50))
    i = intent(qty=1, limit_price=100.1)
    b.submit(i, ok(i))
    assert b.fills[0].price <= 100.1


def test_resting_limit_then_fill_and_cancel_all():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000)
    i = intent(qty=1, limit_price=99)
    b.submit(i, ok(i))
    assert len(b.open_orders) == 1 and not b.fills
    b.on_price("SPY", 99.5)
    assert len(b.open_orders) == 1
    b.on_price("SPY", 98.9)
    assert not b.open_orders and b.fills[0].price <= 99
    for _ in range(3):
        j = intent(qty=1, limit_price=90)
        b.submit(j, ok(j))
    assert b.cancel_all() == 3 and not b.open_orders


def test_settlement_t_plus_1():
    from datetime import date
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, costs=CostModel(0, 0), today=date(2026, 10, 14))
    i = intent(qty=10); b.submit(i, ok(i))
    s = intent(side="sell", qty=10); b.submit(s, ok(s))
    assert b.unsettled == pytest.approx(1000) and b.settled_cash == pytest.approx(19_000)
    b.roll_day(date(2026, 10, 15))
    assert b.unsettled == 0 and b.settled_cash == pytest.approx(20_000)


def test_crypto_settles_immediately():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000, costs=CostModel(0, 0))
    i = intent(symbol="BTC", asset_class="crypto_spot", qty=0.01, limit_price=100, sleeve="high_risk")
    b.submit(i, ok(i))
    s = intent(symbol="BTC", asset_class="crypto_spot", side="sell", qty=0.01, sleeve="high_risk")
    b.submit(s, ok(s))
    assert b.unsettled == 0


def test_no_short():
    b = PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000)
    s = intent(side="sell", qty=1)
    with pytest.raises(ValueError):
        b.submit(s, ok(s))


@pytest.fixture
def svc():
    s = build_service(CONFIG_DIR)
    s.heartbeat()
    return s


def test_service_tools(svc):
    st = svc.get_status()
    assert st["mode"] == "paper" and st["live_available"] is False and not st["halted"]
    assert svc.get_positions() == [] and svc.get_risk_limits()["read_only"] is True


def test_propose_creates_approval_but_never_executes(svc):
    r = svc.propose_order(**ORDER)
    assert r["approved"] and r["executes"] is False and r["status"] == "pending_owner_approval"
    assert svc.broker.fills == [] and len(svc.list_approvals()) == 1


def test_owner_approval_executes_on_paper(svc):
    r = svc.propose_order(**ORDER)
    with pytest.raises(PermissionError):
        svc.owner_approve(r["approval_id"], "ai", True)
    out = svc.owner_approve(r["approval_id"], "masharai", True)
    assert out["executes"] and len(svc.broker.fills) == 1
    assert svc.reconcile() == [] and not svc.ks.engaged


def test_approval_ttl_expiry():
    from founder_conftest import FakeClock
    from atlas.governance.audit import AuditLog
    from atlas.control.policy import load_all
    from atlas.mcp.trading.service import TradingService
    c = FakeClock()
    s = TradingService(load_all(CONFIG_DIR), PaperBroker(total_account_equity_base=100_000, bot_cash_base=20_000), AuditLog(), clock=c)
    s.heartbeat()
    r = s.propose_order(**ORDER)
    c.advance(121)
    with pytest.raises(ValueError, match="expired"):
        s.owner_approve(r["approval_id"], "masharai", True)


def test_approval_rechecks_risk(svc):
    r = svc.propose_order(**ORDER)
    svc.kill_switch("halt before approval")
    out = svc.owner_approve(r["approval_id"], "masharai", True)
    assert not out["executes"] and svc.broker.fills == []


def test_propose_cannot_spoof_source(svc):
    svc.propose_order(**ORDER, source="owner")
    assert svc.audit.entries("risk.decision")[-1]["actor"] == "ai"


def test_propose_invalid_intent(svc):
    r = svc.propose_order(symbol="SPY", side="buy", qty=-1, order_type="limit")
    assert not r["approved"] and "invalid intent" in r["reasons"][0]


def test_propose_without_quote_age_rejected(svc):
    o = dict(ORDER); o.pop("quote_age_s")
    r = svc.propose_order(**o)
    assert not r["approved"] and not r["checks"]["stale_quote"]


def test_kill_switch_tool(svc):
    assert svc.kill_switch("ai saw anomaly")["halted"] and svc.get_status()["halted"]
    assert not svc.propose_order(**ORDER)["approved"]


@pytest.mark.parametrize("tok", [None, "", "<random-32+-char-token>", "short", "placeholder-placeholder-placeholder"])
def test_mcp_refuses_bad_token(svc, tok):
    from atlas.mcp.trading.server import AuthError, create_server
    with pytest.raises(AuthError):
        create_server(svc, tok)


def test_mcp_tool_surface(svc):
    pytest.importorskip("mcp")
    from atlas.mcp.trading.server import create_server
    names = {t.name for t in asyncio.run(create_server(svc, TOKEN).list_tools())}
    assert names == {"get_status", "get_positions", "get_risk_limits", "list_approvals", "propose_order", "kill_switch",
                     "get_bars", "get_quote", "compute_indicators",
                     # autopilot / research (read-mostly; autopilot_start only files an owner step-up request)
                     "autopilot_status", "autopilot_start", "autopilot_stop", "get_snapshot", "get_market_clock", "get_news",
                     "get_fundamentals", "run_scanner", "run_backtest", "get_portfolio_analytics", "get_risk_budget",
                     "explain_decision", "list_data_feeds", "feed_health"}
    assert not names & {"reset_kill_switch", "set_policy", "approve", "place_order", "execute_order", "set_mode"}


def _is_err(res):
    return bool(getattr(res, "is_error", getattr(res, "isError", False)))


def test_mcp_auth_enforced(svc):
    from atlas.mcp.trading.server import create_server
    app = create_server(svc, TOKEN)
    try:
        bad = asyncio.run(app.call_tool("get_status", {"auth_token": "wrong"}))
        assert _is_err(bad)
    except Exception as e:
        assert "auth" in str(e).lower()
    assert svc.audit.entries("mcp.auth_failed")
    good = asyncio.run(app.call_tool("propose_order", {"auth_token": TOKEN, **ORDER}))
    assert not _is_err(good) and svc.audit.verify() >= 2
