import csv, json
import pytest
from decimal import Decimal
from pathlib import Path
from atlas.ledgers import audit
from atlas.ledgers.db import connect
from atlas.ledgers.manual import Manual, mask
from atlas.ledgers.stepup import AuthError
from atlas.ledgers.treasury import ControlError, Treasury, DEFAULT_SETTINGS

@pytest.fixture
def m(env, tmp_path):
    env.tr._set("execution_mode", "manual")
    return Manual(env.tr, tmp_path / "sheets")

def _approved(env, key="t1", amount="1000", **payee):
    pid = env.ready_payee(**payee)
    kw = payee.pop("_kw", {})
    tid = env.tr.request_transfer("ops", key, pid, amount, payee.get("ccy", "CAD"), **kw)
    env.tr.approve_transfer(tid, *env.creds("owner"))
    return tid

def test_manual_is_default_and_blocks_adapter_execute(tmp_path):
    assert DEFAULT_SETTINGS["execution_mode"] == "manual"
    from atlas.ledgers.stepup import Approvers
    tr = Treasury(connect(), Approvers(tmp_path / "a.json"))
    assert tr.get("execution_mode") == "manual"

def test_full_manual_flow(env, m):
    tid = _approved(env, dest="CA-001-12345-9876543")
    with pytest.raises(ControlError, match="manual"):
        env.tr.execute(tid, "bank")
    files = m.prepare(tid)
    ref = files["reference"]
    md = Path(files["md"]).read_text()
    assert "1000" in md and "CAD" in md and "EFT" in md and ref in md and "Checklist" in md
    assert "6543" in md and "9876543" not in md  # masked except last 4
    assert Path(files["pdf"]).read_bytes().startswith(b"%PDF") and ref in Path(files["csv"]).read_text()
    assert env.tr.transfer(tid)["status"] == "instructed"
    with pytest.raises(ControlError):
        m.prepare(tid)  # no second instruction
    with pytest.raises(AuthError):
        m.mark_executed(tid, "CONF1", "owner", "bad passphrase!!", "000000")
    m.mark_executed(tid, "BANKCONF-777", *env.creds("owner"))
    assert env.tr.transfer(tid)["status"] == "pending_settlement"
    assert env.tr.ledger.balance("asset:bank:cad") == Decimal("-1000")
    assert [p["id"] for p in m.pending()] == [tid]
    stmt = [{"date": "x", "ref": "BNK-1", "amount": Decimal("-1000.00"), "currency": "CAD", "memo": f"EFT {ref}"},
            {"date": "x", "ref": "FEE", "amount": Decimal("-15"), "currency": "CAD", "memo": "fee"}]
    r = m.reconcile(stmt)
    assert r["settled"] == [tid] and r["unmatched_lines"] == ["FEE"]
    assert env.tr.transfer(tid)["status"] == "settled" and m.pending() == []
    assert audit.verify(env.c)[0]

def test_mismatch_and_overdue(env, m):
    a = _approved(env, "a", "100"); b = _approved(env, "b", "200")
    ra = m.prepare(a)["reference"]; m.prepare(b)
    m.mark_executed(a, "C1", *env.creds("owner")); m.mark_executed(b, "C2", *env.creds("owner"))
    r = m.reconcile([{"ref": ra, "amount": Decimal("-99"), "currency": "CAD"}])
    assert r["amount_mismatch"] == [a] and r["overdue"] == []
    env.clock.advance(10 * 86400)
    r = m.reconcile([])
    assert b in r["overdue"]
    flags = {p["id"]: p["flag"] for p in m.pending()}
    assert flags[a].startswith("amount_mismatch") and flags[b] == "overdue"

def test_expiry(env, m):
    tid = _approved(env); m.prepare(tid)
    env.clock.advance(73 * 3600)
    assert m.reconcile([])["expired"] == [tid]
    assert env.tr.transfer(tid)["status"] == "expired"
    with pytest.raises(ControlError):
        m.mark_executed(tid, "C", *env.creds("owner"))

def test_unapproved_and_kill_block_sheet(env, m):
    pid = env.ready_payee()
    tid = env.tr.request_transfer("ops", "x", pid, "10", "CAD")
    with pytest.raises(ControlError, match="approved"):
        m.prepare(tid)
    env.tr.approve_transfer(tid, *env.creds("owner")); env.tr.kill("ops")
    with pytest.raises(ControlError, match="kill"):
        m.prepare(tid)

@pytest.mark.parametrize("rail,ccy,kind,kw,needle", [
    ("WIRE", "USD", "bank", {"source": "asset:bank:usd", "debit_account": "asset:broker:ibkr"}, "IBKR Portal"),
    ("WIRE", "USD", "bank", {"source": "asset:broker:ibkr", "debit_account": "asset:bank:usd"}, "Withdraw"),
    ("INTERAC", "CAD", "bank", {}, "Interac"),
    ("LYNX", "CAD", "bank", {}, "Lynx"),
    ("CRYPTO", "BTC", "wallet", {"source": "asset:broker:kraken"}, "test transfer"),
    ("CRYPTO", "ETH", "wallet", {"source": "asset:broker:coinbase"}, "character-by-character"),
])
def test_rail_checklists(env, m, rail, ccy, kind, kw, needle):
    pid = env.ready_payee(rail=rail, ccy=ccy, kind=kind, dest="DEST-ABCDEFGH1234")
    tid = env.tr.request_transfer("ops", f"k-{rail}-{ccy}-{len(kw)}", pid, "0.1" if kind == "wallet" else "100", ccy, **kw)
    env.tr.approve_transfer(tid, *env.creds("owner"))
    md = Path(m.prepare(tid)["md"]).read_text()
    assert needle in md and "1234" in md and "ABCDEFGH" not in md

def test_batch_fee_run(env, m):
    ids = [_approved(env, f"fee-{i}", str(100 * (i + 1)), name=f"Vendor{i}") for i in range(3)]
    out = m.batch(ids, "2026-10-16-fee-run")
    assert out["totals"] == {"CAD": "600"}
    rows = list(csv.DictReader(open(out["csv"])))
    assert len(rows) == 3 and len({r["reference"] for r in rows}) == 3
    assert Path(out["pdf"]).read_bytes().startswith(b"%PDF")
    assert all(env.tr.transfer(i)["status"] == "instructed" for i in ids)

def test_mask():
    assert mask("123456789") == "*****6789" and mask("12") == "12"

def test_dashboard_shows_pending(env, m):
    from atlas.ledgers.dashboard import render
    from atlas.ledgers.readonly import BalanceView
    tid = _approved(env); ref = m.prepare(tid)["reference"]
    v = BalanceView(str(env.path))
    assert v.summary()["pending_manual"][0]["reference"] == ref and ref in render(v)

def test_cli_manual(tmp_path, capsys, monkeypatch):
    from atlas.ledgers.cli import main
    from atlas.ledgers.stepup import Approvers, totp
    from atlas.ledgers.db import connect
    var = tmp_path / "v"; main(["--var", str(var), "init"])
    c = connect(str(var / "payments.sqlite")); ap = Approvers(var / "approvers.json")
    sec = ap.enroll("owner", "correct horse battery staple")
    tr = Treasury(c, ap)
    pid = tr.request_payee("t", "P", "bank", "EFT", "CAD", "ACCT99998888")
    c.execute("UPDATE payees SET status='approved', approved_at=0, active_from=0 WHERE id=?", (pid,))
    tid = tr.request_transfer("t", "k", pid, "50", "CAD")
    c.execute("UPDATE transfers SET status='approved' WHERE id=?", (tid,))
    main(["--var", str(var), "sheet", str(tid)])
    assert "reference" in capsys.readouterr().out
    monkeypatch.setattr("getpass.getpass", lambda *_: "correct horse battery staple")
    monkeypatch.setattr("builtins.input", lambda *_: totp(sec))
    main(["--var", str(var), "mark-executed", str(tid), "--confirmation", "X1", "--approver", "owner"])
    main(["--var", str(var), "pending"])
    assert '"pending_settlement"' in capsys.readouterr().out
