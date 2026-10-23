"""Regression tests for payments findings in trading-bot-review/audit.md."""
import json
import pytest
from decimal import Decimal
from atlas.ledgers.db import connect, tx
from atlas.ledgers.fund import Fund, StubNAV
from atlas.ledgers.manual import Manual
from atlas.ledgers.treasury import ControlError

from test_manual import _approved


@pytest.fixture
def fund(env): return Fund(env.c, env.tr.ledger, env.clock)


def _inv(fund):
    i = fund.add_investor("A", accredited=True); fund.set_kyc(i, "approved"); return i


def test_pending_redemptions_cannot_over_redeem(fund):
    i = _inv(fund); fund.subscribe(i, "1000"); fund.deal(StubNAV("10"))
    fund.redeem(i, "100")
    with pytest.raises(ValueError):
        fund.redeem(i, "1")  # all 100 units already pending redemption
    fund.deal(StubNAV("10"))
    assert Decimal(fund.investor(i)["units"]) == 0


def test_bad_nav_rejected(fund):
    i = _inv(fund); fund.subscribe(i, "1000")
    for bad in ("0", "-1", "NaN"):
        with pytest.raises(ValueError):
            fund.deal(StubNAV(bad))
    assert fund.investor(i)["units"] == "0"


def test_fee_not_charged_twice_for_same_period(fund):
    i = _inv(fund); fund.subscribe(i, "36500"); fund.deal(StubNAV("10"))
    fund.management_fee(i, StubNAV("10"), period="2026-10")
    with pytest.raises(ValueError, match="already charged"):
        fund.management_fee(i, StubNAV("10"), period="2026-10")
    assert fund.ledger.balance("income:fees") == Decimal("-60.00")


def test_tx_rolls_back_and_is_reentrant(env):
    with pytest.raises(RuntimeError):
        with tx(env.c):
            with tx(env.c):
                env.c.execute("INSERT INTO settings VALUES('x','1')")
            raise RuntimeError
    assert env.c.execute("SELECT 1 FROM settings WHERE k='x'").fetchone() is None


def test_mark_executed_second_process_cannot_double_post(env, tmp_path):
    m = Manual(env.tr, out_dir=str(tmp_path / "sheets"))
    tid = _approved(env); m.prepare(tid)
    # another process claims first (simulated with a second connection on the same DB)
    c2 = connect(str(env.path)); c2.execute("UPDATE transfers SET status='marking' WHERE id=?", (tid,))
    t = m._row(tid)
    with pytest.raises(ControlError):
        m.mark_executed(tid, "C1", *env.creds("owner"))
    n = env.c.execute("SELECT COUNT(*) FROM journal WHERE ref=?", (t["reference"],)).fetchone()[0]
    assert n == 0


def test_adapter_execute_claims_once(env):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "k1", pid, "10", "CAD")
    env.tr.approve_transfer(tid, *env.creds("owner"))
    env.tr.execute(tid, "bank")
    with pytest.raises(ControlError):
        env.tr.execute(tid, "bank")
    assert env.c.execute("SELECT COUNT(*) FROM journal WHERE memo LIKE ?", (f"transfer {tid} %",)).fetchone()[0] == 1


def test_approve_does_not_resurrect_rejected(env):
    env.tr._set("dual_control", "1")
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "k2", pid, "10", "CAD")
    env.tr.approve_transfer(tid, *env.creds("owner"))
    env.tr.reject_transfer(tid, "owner")
    with pytest.raises(ControlError):
        env.tr.approve_transfer(tid, *env.creds("cofounder"))
    assert env.tr.transfer(tid)["status"] == "rejected"


def test_approvers_file_written_atomically(env, tmp_path):
    p = tmp_path / "approvers.json"
    assert json.loads(p.read_text()) and oct(p.stat().st_mode)[-3:] == "600"
    assert not list(tmp_path.glob("approvers.json.*.tmp"))
