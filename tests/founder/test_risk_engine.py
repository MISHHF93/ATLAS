import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from founder_conftest import intent, pos, state


def reasons(d):
    return [k for k, v in d.checks.items() if not v]


def test_happy_path(engine):
    d = engine.evaluate(intent(qty=10), state())
    assert d.approved, d.reasons


# ---- loss limits
def test_daily_loss_blocks_buys(engine):
    s = state(cash=19_500, sod=20_000)  # 2.5% down
    d = engine.evaluate(intent(), s)
    assert not d.approved and "daily_loss" in reasons(d)


def test_daily_loss_just_below_ok(engine):
    s = state(cash=19_700, sod=20_000)  # 1.5%
    assert engine.evaluate(intent(), s).approved


def test_daily_loss_allows_risk_reducing_sell(engine):
    p = {"SPY": pos(qty=10, price=100)}
    s = state(cash=18_000, positions=p, sod=19_700)  # eq 19000, 3.5% day loss, <4% week
    d = engine.evaluate(intent(side="sell", qty=5), s)
    assert d.approved, d.reasons


def test_weekly_loss_blocks_and_halts(engine):
    s = state(cash=19_000, sod=19_100, sow=20_000)  # 5% week
    d = engine.evaluate(intent(), s)
    assert not d.approved and "weekly_loss" in reasons(d)
    assert engine.ks.engaged  # halt until owner review


def test_max_drawdown_blocks_and_halts(engine):
    s = state(cash=18_000, sod=18_100, sow=18_100, peak=20_500)  # ~12% DD
    d = engine.evaluate(intent(), s)
    assert not d.approved and "max_drawdown" in reasons(d) and engine.ks.engaged


# ---- position / capital / sleeve
def test_max_position_pct(engine):
    d = engine.evaluate(intent(qty=21), state())  # 2100 > 10% of 20000
    assert "max_position_pct" in reasons(d)


def test_max_position_pct_includes_existing(engine):
    s = state(cash=18_500, positions={"SPY": pos(qty=15)})
    d = engine.evaluate(intent(qty=6), s)  # 1500+600 > 2000
    assert "max_position_pct" in reasons(d)


def test_max_position_notional(cfg, audit, ks, clock):
    # with big account, 10% of bot capital > 5000 so the notional cap binds
    from atlas.risk import RiskEngine, Watchdog
    wd = Watchdog(5, 3, ks, clock=clock); wd.heartbeat()
    e = RiskEngine(cfg.risk, cfg.brokers, audit, ks, wd, clock=clock)
    d = e.evaluate(intent(qty=60), state(total=1_000_000, cash=200_000))
    assert reasons(d) == ["max_position_notional"]


def test_no_leverage_cash(engine):
    s = state(cash=1_000, positions={f"S{i}": pos(f"S{i}", qty=19, price=100, sleeve="core" if i < 7 else "active") for i in range(10)})
    d = engine.evaluate(intent(symbol="NEW", qty=15), s)  # 1500 > 1000 cash
    assert "no_leverage_cash" in reasons(d)


def test_bot_capital_cap_20pct(engine):
    # bot holds more cash than its 20% cap (e.g. after deposit): exposure capped at 20% of account
    ps = {f"S{i}": pos(f"S{i}", qty=19, price=100, sleeve="core" if i < 7 else "active") for i in range(10)}  # 19000
    s = state(total=100_000, cash=10_000, positions=ps)
    d = engine.evaluate(intent(symbol="NEW", qty=15, sleeve="active", asset_class="us_equity"), s)
    assert "bot_capital_cap" in reasons(d)


def test_sleeve_allocation_high_risk(engine):
    s = state(positions={"BTC": pos("BTC", qty=1, price=2_000, sleeve="high_risk")}, cash=18_000)
    d = engine.evaluate(intent(symbol="ETH-USD", qty=1.5, limit_price=1000, reference_price=1000,
                               sleeve="high_risk", asset_class="crypto_spot", broker="coinbase"), s)
    assert reasons(d) == ["sleeve_allocation"]  # 3500 > 15% of 20000


def test_sleeve_instrument_restriction(engine):
    d = engine.evaluate(intent(asset_class="crypto_spot"), state())
    assert "sleeve_instrument" in reasons(d)


def test_undefined_sleeve(engine):
    assert "sleeve_defined" in reasons(engine.evaluate(intent(sleeve="active_swing"), state()))


def test_derivatives_locked(engine):
    assert "sleeve_unlocked" in reasons(engine.evaluate(intent(sleeve="derivatives", asset_class="option"), state()))


def test_no_short(engine):
    assert "no_short" in reasons(engine.evaluate(intent(side="sell", qty=1), state()))


# ---- venue
@pytest.mark.parametrize("b", ["oanda", "robinhood_crypto", "wealthsimple"])
def test_disabled_or_unknown_broker(engine, b):
    assert "broker" in reasons(engine.evaluate(intent(broker=b), state()))


# ---- price collar
@pytest.mark.parametrize("lp,ok", [(102.0, True), (98.0, True), (102.01, False), (97.9, False)])
def test_price_collar(engine, lp, ok):
    d = engine.evaluate(intent(limit_price=lp), state())
    assert ("price_collar" not in reasons(d)) == ok


def test_market_order_requires_reference(engine):
    d = engine.evaluate(intent(order_type="market", limit_price=None, reference_price=None), state())
    assert "reference_price" in reasons(d)


# ---- rate limits
def test_orders_per_minute(engine, clock):
    for _ in range(10):
        assert engine.evaluate(intent(), state()).approved
    d = engine.evaluate(intent(), state())
    assert "order_rate" in reasons(d)
    clock.advance(60); engine.watchdog.heartbeat()
    assert engine.evaluate(intent(), state()).approved


def test_rejected_orders_do_not_consume_rate(engine):
    for _ in range(20):
        engine.evaluate(intent(qty=1000), state())
    assert engine.evaluate(intent(), state()).approved


def test_max_open_orders(engine):
    assert "open_orders" in reasons(engine.evaluate(intent(), state(open_orders=25)))


# ---- kill switch / watchdog in gate
def test_kill_switch_rejects_everything(engine):
    engine.ks.engage("test", "cli")
    for i in [intent(), intent(side="sell", qty=1)]:
        d = engine.evaluate(i, state(positions={"SPY": pos(qty=5)}, cash=19_500))
        assert not d.approved and d.halted and "kill_switch" in reasons(d)


def test_watchdog_stale_rejects_and_halts(engine, clock):
    clock.advance(16)
    d = engine.evaluate(intent(), state())
    assert "watchdog" in reasons(d) and engine.ks.engaged


def test_internal_error_fails_closed(engine, monkeypatch):
    monkeypatch.setattr(engine, "bot_capital", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    d = engine.evaluate(intent(), state())
    assert not d.approved and "internal_error" in reasons(d)


def test_every_decision_audited(engine, audit):
    engine.evaluate(intent(), state())
    engine.evaluate(intent(qty=999), state())
    assert len(audit.entries("risk.decision")) == 2 and audit.verify() >= 2


def test_policy_has_no_setter(engine):
    with pytest.raises(AttributeError):
        engine.policy = None
    with pytest.raises(Exception):
        engine.policy.position_limits.price_collar_pct = 50


# ---- property tests
@settings(max_examples=150, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(qty=st.floats(0.01, 1000), px=st.floats(1, 5000), dev=st.floats(-0.05, 0.05),
       cash=st.floats(0, 20_000), sleeve=st.sampled_from(["core", "active", "high_risk"]))
def test_prop_approved_buy_respects_all_limits(engine, clock, qty, px, dev, cash, sleeve):
    clock.advance(61); engine.watchdog.heartbeat()
    ac = {"core": "index_etf", "active": "us_equity", "high_risk": "crypto_spot"}[sleeve]
    s = state(cash=cash, sod=20_000, sow=20_000, peak=20_000) if cash > 0 else state(cash=0.0, sod=1, sow=1, peak=1)
    lp = round(px * (1 + dev), 6)
    d = engine.evaluate(intent(qty=qty, limit_price=lp, reference_price=px, sleeve=sleeve, asset_class=ac,
                               broker="coinbase" if sleeve == "high_risk" else "alpaca"), s)
    if d.approved:
        notional = qty * lp
        bot_cap = min(s.bot_equity, 20_000)
        assert notional <= cash + 1e-6
        assert notional <= 0.10 * bot_cap + 1e-6 and notional <= 5000 + 1e-6
        assert abs(lp - px) / px <= 0.02 + 1e-9
        assert (20_000 - s.bot_equity) / 20_000 < 0.02
    assert not engine.ks.engaged or not d.approved


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n=st.integers(0, 40))
def test_prop_never_more_than_rate_limit_per_minute(engine, clock, n):
    clock.advance(61); engine.watchdog.heartbeat()
    approved = sum(engine.evaluate(intent(), state()).approved for _ in range(n))
    assert approved == min(n, 10)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(side=st.sampled_from(["buy", "sell"]), qty=st.floats(0.01, 10))
def test_prop_kill_switch_absolute(engine, side, qty):
    engine.ks.engage("prop", "cli")
    assert not engine.evaluate(intent(side=side, qty=qty), state(positions={"SPY": pos(qty=10)}, cash=19_000)).approved
