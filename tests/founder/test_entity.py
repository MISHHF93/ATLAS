"""Entity features: fund allocation (pre-trade, pro-rata, fairness), NAV per unit, corp AAII/RDTOH.
Worked examples verified by hand. NOT TAX, LEGAL OR REGULATORY ADVICE."""
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from founder_conftest import intent, state
from atlas.governance.entity.allocation import AllocationBook, AllocationError, FundAllocationHook
from atlas.governance.entity.corp import PassiveIncome, corp_report, passive_income_from_tax_report
from atlas.governance.entity.nav import FundNav

T0 = datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)
W = {"A": 50, "B": 30, "C": 20}


# ---------------------------------------------------------------- allocation
def test_full_fill_pro_rata_same_avg_price():
    b = AllocationBook()
    b.record_pre_trade("o1", "XIC", "buy", 1000, W, T0, "pro-rata NAV")
    a = b.allocate("o1", [(600, D("10.00")), (400, D("10.10"))], T0 + timedelta(seconds=5))
    assert a.per_account == {"A": D(500), "B": D(300), "C": D(200)} and a.avg_price == D("10.040000") and not a.exceptions


def test_partial_fill_largest_remainder():
    b = AllocationBook()
    b.record_pre_trade("o1", "XIC", "buy", 1000, W, T0, "pro-rata NAV")
    a = b.allocate("o1", [(333, D("10"))])
    # entitlements 166.5 / 99.9 / 66.6 -> floors 166/99/66, 2 remainder lots to B (.9) and C (.6)
    assert a.per_account == {"A": D(166), "B": D(100), "C": D(67)}


def test_board_lots_and_odd_lot_exception():
    b = AllocationBook(lot=D(100))
    b.record_pre_trade("o1", "XIC", "buy", 1000, {"A": 1, "B": 1}, T0, "equal")
    a = b.allocate("o1", [(750, D("10"))])
    assert sum(a.per_account.values()) == D(700) and set(a.per_account.values()) == {D(300), D(400)}
    assert any("odd-lot" in e for e in a.exceptions)


def test_pre_trade_required_immutable_and_before_fill():
    b = AllocationBook()
    with pytest.raises(AllocationError, match="pre-trade"):
        b.allocate("nope", [(1, 1)])
    b.record_pre_trade("o1", "XIC", "buy", 10, W, T0, "x")
    with pytest.raises(AllocationError, match="immutable"):
        b.record_pre_trade("o1", "XIC", "buy", 10, {"A": 1}, T0, "x")
    a = b.allocate("o1", [(10, 1)], first_fill_ts=T0 - timedelta(seconds=1))
    assert any("after the first fill" in e for e in a.exceptions)
    with pytest.raises(AllocationError, match="more than"):
        b.record_pre_trade("o2", "XIC", "buy", 5, W, T0, "x"); b.allocate("o2", [(6, 1)])


def test_reallocation_owner_only_with_reason():
    b = AllocationBook()
    b.record_pre_trade("o1", "XIC", "buy", 10, W, T0, "x"); b.allocate("o1", [(10, 1)])
    with pytest.raises(PermissionError):
        b.reallocate("o1", {"A": 10, "B": 0, "C": 0}, "ai", "masharai", "because")
    with pytest.raises(PermissionError):
        b.reallocate("o1", {"A": 10, "B": 0, "C": 0}, "masharai", "masharai", " ")
    with pytest.raises(AllocationError):
        b.reallocate("o1", {"A": 11}, "masharai", "masharai", "error fix")
    a = b.reallocate("o1", {"A": 6, "B": 3, "C": 1}, "masharai", "masharai", "trade error correction")
    assert "re-allocated" in a.exceptions[-1] and b.fairness_report()["exceptions"]


def test_remainders_rotate_fairly_over_many_orders():
    b = AllocationBook()
    for k in range(30):  # equal weights, 1 lot each time: the odd lot must rotate
        b.record_pre_trade(f"o{k}", "XIC", "buy", 1, {"A": 1, "B": 1, "C": 1}, T0, "equal")
        b.allocate(f"o{k}", [(1, 10)])
    rep = b.fairness_report()
    got = {k: sum(a.per_account[k] for a in b.allocs.values()) for k in "ABC"}
    assert got == {"A": D(10), "B": D(10), "C": D(10)} and rep["fair"]


def test_fairness_random_orders():
    rng = random.Random(3)
    b = AllocationBook()
    for k in range(200):
        b.record_pre_trade(f"o{k}", "XIC", "buy", 1000, W, T0, "nav")
        b.allocate(f"o{k}", [(rng.randint(1, 1000), 10)])
    rep = b.fairness_report()
    assert rep["fair"] and rep["max_abs_cumulative_deviation_lots"] <= 1.0


def test_fund_hook_blocks_orders_without_pre_trade_allocation():
    b = AllocationBook()
    hook = FundAllocationHook(b)
    i = intent(qty=10)
    assert hook(i, state())[0]
    b.record_pre_trade(i.intent_id, i.symbol, i.side, 10, W, T0, "nav")
    assert hook(i, state()) == ([], [])
    assert hook(i.model_copy(update={"qty": 11}), state())[0]


# ---------------------------------------------------------------- NAV
def test_nav_worked_example_forward_pricing_and_fees():
    f = FundNav("Fund I")
    f.order_subscription("A", 100_000)
    r0 = f.value(date(2026, 1, 1), {})
    assert r0["navpu"] == "10.0000" and f.units["A"] == D("10000.0000")
    f.trade("XYZ", 1000, 90, fee_cad=10)
    f.order_subscription("B", D("20996.80"))
    r1 = f.value(date(2026, 1, 2), {"XYZ": D(95)})
    # gross 104,990.00; 1-day fee 104,990 x 2% / 365 = 5.75; NAV 104,984.25; NAVPU 10.4984
    assert (r1["gross_assets"], r1["mgmt_fee_accrued_today"], r1["nav"], r1["navpu"]) == ("104990.00", "5.75", "104984.25", "10.4984")
    assert f.units["B"] == D("2000.0000")   # B dealt at the NEXT NAV (forward pricing)
    f.order_redemption("A", 1000)
    r2 = f.value(date(2026, 1, 3), {"XYZ": D(95)})
    # gross 125,986.80; fee on 125,981.05 = 6.90; accrued 12.65; NAV 125,974.15 / 12,000 = 10.4978
    assert (r2["mgmt_fee_accrued_today"], r2["nav"], r2["navpu"]) == ("6.90", "125974.15", "10.4978")
    assert r2["dealt"][0]["amount"] == "10497.80" and f.units["A"] == D("9000.0000")
    assert f.investor_statement("B")["value"] == "20995.60" and "NOT TAX" in r2["disclaimer"]


def test_nav_fails_closed_without_price_and_redemption_limits():
    f = FundNav("F"); f.order_subscription("A", 1000); f.value(date(2026, 1, 1), {})
    f.trade("XYZ", 1, 10)
    with pytest.raises(ValueError, match="fail closed"):
        f.value(date(2026, 1, 2), {})
    with pytest.raises(ValueError):
        f.order_redemption("A", 101)


def test_performance_fee_high_water_mark():
    f = FundNav("F", mgmt_fee_annual=D(0), perf_fee_rate=D("0.20"))
    f.order_subscription("A", 10_000); f.value(date(2026, 1, 1), {})
    f.trade("XYZ", 100, 100)
    r = f.value(date(2026, 1, 2), {"XYZ": D(110)})   # NAV 11,000 -> NAVPU 11.00 pre-fee; fee 20% of 1,000 = 200
    assert r["navpu"] == "10.8000" and f.accrued_perf == D("200.00")
    r = f.value(date(2026, 1, 3), {"XYZ": D(105)})   # below HWM: no new perf fee
    assert f.accrued_perf == D("200.00") and r["navpu"] == "10.3000"


# ---------------------------------------------------------------- corp
def test_corp_aaii_grind_and_rdtoh():
    pi = PassiveIncome(taxable_capital_gains=D(60_000), interest=D(10_000), eligible_portfolio_dividends=D(20_000))
    r = corp_report(pi, prior_year_aaii=D(90_000), eligible_dividends_paid=D(30_000))
    assert r["aggregate_investment_income"] == "70000.00" and r["aaii"] == "90000.00"
    assert r["sbd_business_limit_reduction"] == "200000.00" and r["sbd_business_limit_remaining"] == "300000.00"
    assert r["part1_refundable_tax_to_nerdtoh"] == "21466.67" and r["part4_tax_eligible_to_erdtoh"] == "7666.67"
    assert r["dividend_refund_estimate"] == "7666.67" and r["erdtoh_closing"] == "0.00" and r["nerdtoh_closing"] == "21466.67"
    assert any("> $50,000" in f for f in r["flags"]) and "NOT TAX" in r["disclaimer"]


def test_corp_sbd_eliminated_and_losses_floor():
    r = corp_report(PassiveIncome(taxable_capital_gains=D(10_000), allowable_capital_losses=D(30_000), interest=D(160_000)))
    assert r["aggregate_investment_income"] == "160000.00"   # net TCG floored at 0
    assert r["sbd_business_limit_remaining"] == "0.00" and any("fully eliminated" in f for f in r["flags"])
    assert any("PRIOR-year" in f for f in r["flags"])


def test_corp_non_eligible_refund_draws_nerdtoh_then_erdtoh():
    pi = PassiveIncome(interest=D(3_000), eligible_portfolio_dividends=D(3_000))
    r = corp_report(pi, prior_year_aaii=D(0), non_eligible_dividends_paid=D(6_000))
    # NERDTOH 920.00, ERDTOH 1,150.00; refund cap 2,300 -> 920 + 1,150 = 2,070
    assert r["dividend_refund_estimate"] == "2070.00" and r["erdtoh_closing"] == "0.00" and r["nerdtoh_closing"] == "0.00"


def test_corp_business_flag_and_from_tax_report():
    from atlas.tax import Entity, TaxEngine, Trade
    from zoneinfo import ZoneInfo
    tor = ZoneInfo("America/Toronto")
    eng = TaxEngine([Entity("holdco", "corporation", "holdco")])
    ev = [Trade("t1", "holdco", "ibkr", datetime(2026, 2, 1, 12, tzinfo=tor), "XIC", "buy", D(100), D(30)),
          Trade("t2", "holdco", "ibkr", datetime(2026, 5, 1, 12, tzinfo=tor), "XIC", "sell", D(100), D(40))]
    pi = passive_income_from_tax_report(eng.run(ev), "holdco", 2026)
    assert pi.taxable_capital_gains == D("500.00")
    r = corp_report(pi, business_evidence={"pct_held_under_30d": 80, "trades": 10})
    assert any("business" in f for f in r["flags"])
