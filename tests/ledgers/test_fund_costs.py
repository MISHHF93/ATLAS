import pytest
from decimal import Decimal
from atlas.ledgers.fund import Fund, GateError, StubNAV
from atlas.ledgers.costs import Costs
from atlas.ledgers import statements
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

@pytest.fixture
def fund(env): return Fund(env.c, env.tr.ledger, env.clock)

def test_kyc_gates(fund):
    i = fund.add_investor("A")
    with pytest.raises(GateError): fund.subscribe(i, "1000")
    fund.c.execute("UPDATE investors SET accredited=1 WHERE id=?", (i,))
    with pytest.raises(GateError, match="KYC"): fund.subscribe(i, "1000")
    fund.set_kyc(i, "approved"); assert fund.subscribe(i, "1000")

def _inv(fund, name="A", committed="0"):
    i = fund.add_investor(name, accredited=True, committed=committed); fund.set_kyc(i, "approved"); return i

def test_large_cash_flag_record_only(fund):
    i = _inv(fund); fund.subscribe(i, "10000", method="cash")
    assert [f["kind"] for f in fund.flags(i)] == ["large_cash"]
    fund.flag(i, "suspicious", "unusual pattern (record only)")
    assert len(fund.flags(i)) == 2

def test_forward_pricing_sub_and_redeem(fund):
    i = _inv(fund); fund.subscribe(i, "1000")
    assert fund.investor(i)["units"] == "0"  # not dealt until next NAV
    fund.deal(StubNAV("10")); assert Decimal(fund.investor(i)["units"]) == 100
    fund.redeem(i, "40"); fund.deal(StubNAV("12.5"))
    assert Decimal(fund.investor(i)["units"]) == 60
    assert fund.ledger.balance("liability:redemptions_payable") == Decimal("-500")
    with pytest.raises(ValueError): fund.redeem(i, "61")

def test_performance_fee_hwm(fund):
    i = _inv(fund); fund.subscribe(i, "1000"); fund.deal(StubNAV("10"))
    assert fund.performance_fee(i, StubNAV("9")) == 0           # below HWM
    fee = fund.performance_fee(i, StubNAV("12"), period="2026Q3")  # 100u * 2 * 20%
    assert fee == Decimal("40.00")
    assert Decimal(fund.investor(i)["hwm"]) == 12
    assert Decimal(fund.investor(i)["units"]) == Decimal("96.6667")
    assert fund.performance_fee(i, StubNAV("11")) == 0          # below new HWM: no fee
    assert fund.ledger.balance("income:fees") == Decimal("-40")

def test_management_fee(fund):
    i = _inv(fund); fund.subscribe(i, "36500"); fund.deal(StubNAV("10"))
    assert fund.management_fee(i, StubNAV("10"), "0.02", days=30) == Decimal("60.00")

def test_capital_calls(fund):
    i = _inv(fund, committed="100000")
    assert len(fund.capital_call(30, "2026-11-01")) == 1
    fund.capital_call(80, "2026-12-01")
    assert Decimal(fund.investor(i)["called"]) == 100000  # capped at commitment

def test_statements(fund):
    i = _inv(fund); fund.subscribe(i, "1000"); fund.deal(StubNAV("10"))
    csv_ = statements.to_csv(fund.c, i, StubNAV("11"))
    assert "subscription" in csv_ and "1100.00" in csv_
    pdf = statements.to_pdf(fund.c, i, StubNAV("11"))
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")

def test_costs_budget_recurring_fx_invoice(env, tmp_path):
    co = Costs(env.c, env.tr.fx, invoice_dir=tmp_path / "inv", clock=env.clock)
    poly = co.add_vendor("Polygon", "data_feeds", "USD"); aws = co.add_vendor("AWS", "servers", "USD")
    co.set_budget("data_feeds", "2026-10", "250"); co.set_budget("servers", "2026-10", "1000")
    b = co.add_bill(poly, "199", "2026-10", invoice_file=FIX / "invoice_polygon.txt")
    row = env.c.execute("SELECT * FROM bills WHERE id=?", (b,)).fetchone()
    assert Decimal(row["amount_cad"]) == Decimal("272.63") and Path(row["invoice_path"]).exists() and len(row["invoice_sha256"]) == 64
    co.add_recurring(aws, "100", "2026-09", 1)
    assert len(co.run_recurring("2026-11")) == 3
    assert len(co.run_recurring("2026-11")) == 0  # no duplicates
    rep = {(r["month"], r["category"]): r for r in co.report("2026-10", "2026-10")}
    assert rep[("2026-10", "data_feeds")]["over_budget"] is True
    assert rep[("2026-10", "servers")]["spent_cad"] == Decimal("137.00")
    assert "category" in co.report_csv("2026-09", "2026-11")
    with pytest.raises(ValueError): co.add_vendor("X", "bogus")

def test_bill_approval_then_payment_through_treasury(env, tmp_path):
    co = Costs(env.c, env.tr.fx, invoice_dir=tmp_path, clock=env.clock)
    v = co.add_vendor("Hetzner", "servers", "CAD"); b = co.add_bill(v, "80", "2026-10")
    co.approve_bill(b, env.tr.auth, *env.creds("owner"))
    pid = env.ready_payee("Hetzner")
    t = env.tr.request_transfer("finance", f"bill-{b}", pid, "80", "CAD", purpose=f"bill {b}")
    env.tr.approve_transfer(t, *env.creds("owner")); env.tr.execute(t, "bank"); co.mark_paid(b, t)
    assert env.c.execute("SELECT status FROM bills WHERE id=?", (b,)).fetchone()[0] == "paid"

def test_cli_smoke(tmp_path, capsys):
    from atlas.ledgers.cli import main
    main(["--var", str(tmp_path), "init"]); main(["--var", str(tmp_path), "kill", "--reason", "t"])
    main(["--var", str(tmp_path), "audit-verify"]); main(["--var", str(tmp_path), "status"])
    out = capsys.readouterr().out
    assert "ENGAGED" in out and "(True, None)" in out and '"kill_switch": true' in out
