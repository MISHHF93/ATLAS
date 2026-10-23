import pytest
from decimal import Decimal
from atlas.ledgers import audit
from atlas.ledgers.db import connect
from atlas.ledgers.providers import ProviderDisabled, default_adapters
from atlas.ledgers.stepup import AuthError
from atlas.ledgers.treasury import ControlError, Treasury
from atlas.ledgers.recon import load_statement, reconcile
from ledger_conftest import PW
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

def test_adapters_disabled_by_default():
    for a in default_adapters().values():
        assert not a.enabled
        with pytest.raises(ProviderDisabled):
            a.submit({"rail": "EFT", "idem_key": "x"})

def test_live_mode_not_implemented():
    a = default_adapters()["bank"]; a.enabled = True; a.simulate = False
    with pytest.raises(NotImplementedError):
        a.submit({"rail": "EFT", "idem_key": "x"})

def test_happy_path_and_ledger(env):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "vendor-1", pid, "1000", "CAD")
    with pytest.raises(ControlError):
        env.tr.execute(tid, "bank")  # not yet approved
    env.tr.approve_transfer(tid, *env.creds("owner"))
    ref = env.tr.execute(tid, "bank")
    assert ref.startswith("SIM-bank-")
    assert env.tr.ledger.balance("asset:bank:cad") == Decimal("-1000")
    assert env.tr.ledger.trial_balance_cad() == 0
    assert audit.verify(env.c) == (True, None)

def test_unapproved_and_cooling_off(env):
    pid = env.tr.request_payee("ops", "New", "bank", "EFT", "CAD", "X")
    with pytest.raises(ControlError, match="allowlist"):
        env.tr.request_transfer("ops", "k", pid, "10", "CAD")
    env.tr.approve_payee(pid, *env.creds("owner"))
    with pytest.raises(ControlError, match="cooling-off"):
        env.tr.request_transfer("ops", "k", pid, "10", "CAD")
    env.clock.advance(24 * 3600)
    assert env.tr.request_transfer("ops", "k", pid, "10", "CAD")

def test_stepup_bad_creds_and_lockout(env):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "k", pid, "10", "CAD")
    for _ in range(5):
        with pytest.raises(AuthError):
            env.tr.approve_transfer(tid, "owner", PW, "000000")
    with pytest.raises(AuthError, match="locked"):
        env.tr.approve_transfer(tid, *env.creds("owner"))

def test_totp_replay_rejected(env):
    pid = env.ready_payee()
    t1 = env.tr.request_transfer("ops", "a", pid, "10", "CAD")
    t2 = env.tr.request_transfer("ops", "b", pid, "10", "CAD")
    creds = env.creds("owner")
    env.tr.approve_transfer(t1, *creds)
    with pytest.raises(AuthError):
        env.tr.approve_transfer(t2, *creds)

def test_dual_control(env):
    env.tr.set_setting("dual_control", "1", *env.creds("owner"))
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "k", pid, "10", "CAD")
    assert env.tr.approve_transfer(tid, *env.creds("owner"))["status"] == "pending_approval"
    with pytest.raises(ControlError):
        env.tr.execute(tid, "bank")
    # same approver twice does not count twice
    env.tr.approve_transfer(tid, *env.creds("owner"))
    assert env.tr.transfer(tid)["status"] == "pending_approval"
    assert env.tr.approve_transfer(tid, *env.creds("cofounder"))["status"] == "approved"

def test_limits(env):
    pid = env.ready_payee()
    with pytest.raises(ControlError, match="per-transfer"):
        env.tr.request_transfer("ops", "big", pid, "50001", "CAD")
    env.tr.request_transfer("ops", "a", pid, "50000", "CAD")
    env.tr.request_transfer("ops", "b", pid, "50000", "CAD")
    with pytest.raises(ControlError, match="daily"):
        env.tr.request_transfer("ops", "c", pid, "1", "CAD")

def test_monthly_limit(env):
    env.tr.set_setting("limit_monthly_cad", "150", *env.creds("owner"))
    pid = env.ready_payee()
    env.tr.request_transfer("ops", "a", pid, "100", "CAD")
    env.clock.advance(3600 * 30)  # next day, maybe same month
    import datetime as dt
    if dt.datetime.fromtimestamp(env.clock()).day != 1:
        with pytest.raises(ControlError, match="monthly"):
            env.tr.request_transfer("ops", "b", pid, "100", "CAD")

def test_interac_cap_and_currency_rail(env):
    pid = env.ready_payee(rail="INTERAC")
    with pytest.raises(ControlError, match="INTERAC"):
        env.tr.request_transfer("ops", "a", pid, "3001", "CAD")
    with pytest.raises(ControlError, match="mismatch"):
        env.tr.request_transfer("ops", "b", pid, "10", "USD")

def test_idempotency(env):
    pid = env.ready_payee()
    a = env.tr.request_transfer("ops", "same", pid, "10", "CAD")
    assert env.tr.request_transfer("ops", "same", pid, "10", "CAD") == a
    with pytest.raises(ControlError, match="idempotency"):
        env.tr.request_transfer("ops", "same", pid, "11", "CAD")
    env.tr.approve_transfer(a, *env.creds("owner")); env.tr.execute(a, "bank")
    with pytest.raises(ControlError):
        env.tr.execute(a, "bank")  # no double execution

def test_kill_switch(env):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "a", pid, "10", "CAD")
    env.tr.approve_transfer(tid, *env.creds("owner"))
    env.tr.kill("ops", "incident")
    with pytest.raises(ControlError, match="kill"):
        env.tr.execute(tid, "bank")
    with pytest.raises(ControlError, match="kill"):
        env.tr.request_transfer("ops", "b", pid, "10", "CAD")
    with pytest.raises(AuthError):
        env.tr.unkill("owner", "wrong passphrase!!", "123456")
    env.tr.unkill(*env.creds("owner"))
    assert env.tr.execute(tid, "bank")

def test_crypto_only_to_allowlisted_wallet(env):
    with pytest.raises(ValueError):
        env.tr.request_payee("ops", "W", "wallet", "EFT", "BTC", "bc1q...")
    pid = env.ready_payee("Cold wallet", rail="CRYPTO", ccy="BTC", kind="wallet", dest="bc1qplaceholder")
    tid = env.tr.request_transfer("ops", "w1", pid, "0.1", "BTC", source="asset:broker:kraken")
    env.tr.approve_transfer(tid, *env.creds("owner"))
    with pytest.raises(ValueError):
        env.tr.execute(tid, "bank")  # bank doesn't do crypto
    assert env.tr.execute(tid, "kraken").startswith("SIM-kraken-")
    assert env.tr.ledger.balance("asset:broker:kraken", "BTC") == Decimal("-0.1")

def test_bank_to_broker_funding(env):
    pid = env.ready_payee("IBKR deposit", rail="WIRE", ccy="USD", dest="IBKR-deposit-instructions-placeholder")
    tid = env.tr.request_transfer("ops", "fund-ibkr", pid, "1000", "USD", source="asset:bank:usd",
                                  debit_account="asset:broker:ibkr", purpose="broker deposit")
    env.tr.approve_transfer(tid, *env.creds("owner")); env.tr.execute(tid, "bank")
    assert env.tr.ledger.balance("asset:broker:ibkr") == Decimal("1000")

def test_disabled_adapter_blocks_execution(env):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "a", pid, "10", "CAD")
    env.tr.approve_transfer(tid, *env.creds("owner"))
    env.tr.adapters["bank"].enabled = False
    with pytest.raises(ProviderDisabled):
        env.tr.execute(tid, "bank")
    assert env.tr.transfer(tid)["status"] == "approved"

def test_audit_tamper_detected(env):
    env.ready_payee()
    assert audit.verify(env.c)[0]
    env.c.execute("UPDATE audit SET data='{\"x\":1}' WHERE id=1")
    assert audit.verify(env.c) == (False, 1)

def test_reconciliation(env):
    pid = env.ready_payee()
    for k, amt in (("vendor-1", "1000"), ("vendor-2", "250"), ("vendor-3", "5")):
        t = env.tr.request_transfer("ops", k, pid, amt, "CAD")
        env.tr.approve_transfer(t, *env.creds("owner")); env.tr.execute(t, "bank")
    r = reconcile(env.c, load_statement(FIX / "bank_statement.csv"), "SIM-bank-")
    assert len(r["matched"]) == 2 and len(r["missing_from_statement"]) == 1
    assert r["unexpected_on_statement"] == ["BANKFEE-001"] and not r["ok"]

def test_trading_side_view_is_read_only(env):
    import sqlite3
    from atlas.ledgers.readonly import BalanceView
    v = BalanceView(str(env.path))
    assert "kill_switch" in v.summary()
    assert not any(n.startswith(("request", "approve", "execute", "post")) for n in dir(v))
    with pytest.raises(sqlite3.OperationalError):
        v._c.execute("INSERT INTO settings VALUES('kill','0')")

def test_dashboard_render(env):
    from atlas.ledgers.dashboard import render
    from atlas.ledgers.readonly import BalanceView
    assert "read-only" in render(BalanceView(str(env.path)))
