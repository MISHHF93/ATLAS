"""CPA-005 (simulation) writer/reader, wallet CPA-005 export, vault key rotation (+ CLI). Offline; synthetic data only."""
import datetime as dt
from decimal import Decimal

import pytest

from atlas.ledgers.banking import cpa005
from atlas.ledgers.db import connect
from atlas.ledgers.wallet import bankfiles
from atlas.ledgers.wallet.vault import Vault, VaultUnavailable, new_key, rotate

from walletkit import link_bank, make_wallet, onboard


@pytest.fixture
def w(tmp_path):
    return make_wallet(tmp_path)


def test_cpa005_roundtrip_and_checks():
    items = [{"amount": Decimal("1234.56"), "due_date": dt.date(2026, 10, 19), "institution": "003", "transit": "12345",
              "account": "1234567", "payee_name": "Hélène Côté", "cross_reference": f"REL-{k:04d}"} for k in range(7)]
    ret = {"institution": "001", "transit": "00011", "account": "9988776"}
    kw = dict(originator_id="SIMORIG001", file_number=12, created=dt.date(2026, 10, 16), data_centre="00000", currency="CAD",
              short_name="EXAMPLE FUND", long_name="EXAMPLE FUND LP", return_account=ret)
    text = cpa005.build(items=items, **kw)
    recs = text.split("\r\n")[:-1]
    assert [r[0] for r in recs] == ["A", "C", "C", "Z"] and all(len(r) == 1464 for r in recs)    # 7 items -> 6 + 1 segments
    assert cpa005.julian(dt.date(2026, 10, 19)) == "026292" and cpa005.from_julian("026292") == dt.date(2026, 10, 19)
    p = cpa005.parse(text)
    assert p["valid"] and len(p["items"]) == 7 and p["trailer"]["credit_total"] == 7 * 123456 and p["trailer"]["credit_count"] == 7
    assert p["items"][0]["payee_name"] == "HELENE COTE" and p["items"][0]["institution"] == "003" and p["header"]["file_number"] == 12
    tampered = text.replace("0000123456", "0000123457", 1)
    assert "trailer credit totals" in " ".join(cpa005.parse(tampered)["errors"])
    with pytest.raises(cpa005.CPA005Error, match="length"):
        cpa005.parse(text.replace("SIMORIG001", "SIMORIG01", 1))
    for bad, msg in (({"originator_id": "short"}, "originator"), ({"file_number": 0}, "1-9999"), ({"currency": "EUR"}, "currency")):
        with pytest.raises(cpa005.CPA005Error, match=msg):
            cpa005.build(items=items, **{**kw, **bad})
    with pytest.raises(cpa005.CPA005Error, match="item REL-X"):
        cpa005.build(items=[dict(items[0], account="12", cross_reference="REL-X")], **kw)


def test_cpa005_export_from_wallet(w):
    iid = onboard(w)
    link_bank(w, iid)
    for k in range(2):
        p = w.request_payout("console:ops", iid, str(200 + k), "vopay", "rebate", f"c{k}")
        w.approve_payout(p["id"], *w.creds("owner"))
        w.approve_payout(p["id"], *w.creds("cfo"))
    f = bankfiles.export_cpa005(w, "console:owner")
    assert f["kind"] == "cpa005" and f["n"] == 2 and f["total"] == "401.00" and f["xsd"] == "valid" and f["msg_id"].endswith("-0001")
    p = cpa005.parse(bankfiles.payfile(w, f["id"], with_xml=True)["xml"])
    assert {i["cross_reference"] for i in p["items"]} == {t["end_to_end_id"] for t in f["txs"]}
    with pytest.raises(bankfiles.BankFileError, match="no released"):
        bankfiles.export_pain001(w, "console:owner")                                 # one payment file per payout
    with pytest.raises(bankfiles.BankFileError, match="returns file"):
        bankfiles.simulate_bank_response(w, f["id"])


def test_vault_rotation(w, tmp_path):
    iid = onboard(w)
    link_bank(w, iid)
    before = w.pii(iid)
    old = w.vault
    k2 = new_key()
    from walletkit import KEY
    assert rotate(w.c, KEY, k2, dry_run=True)["dry_run"] and w.pii(iid) == before
    with pytest.raises(VaultUnavailable, match="same"):
        rotate(w.c, KEY, KEY)
    res = rotate(w.c, KEY, k2, clock=w.tclock)
    assert res["records"] >= 2 and res["old_key_id"] == old.key_id
    with pytest.raises(VaultUnavailable, match="different key"):
        w.pii(iid)                                                                     # old key no longer reads
    w._vault = Vault(w.c, k2, w.tclock)
    assert w.pii(iid) == before and w.c.execute("SELECT COUNT(*) FROM vault_rotations").fetchone()[0] == 1
    # a record under an unknown key blocks rotation; nothing is changed
    c = connect(str(tmp_path / "v.sqlite"))
    k3, k4 = new_key(), new_key()
    Vault(c, k3).put("x", "secret")
    Vault(c, k4).put("y", "other")
    with pytest.raises(VaultUnavailable, match="neither key"):
        rotate(c, k3, new_key())
    assert Vault(c, k3).get(1) == "secret"


def test_vault_rotate_cli_refuses_without_keys(tmp_path, monkeypatch, capsys):
    from atlas.ledgers.cli import main
    monkeypatch.delenv("ATLAS_VAULT_KEY_NEW", raising=False)
    monkeypatch.setenv("ATLAS_VAULT_KEY", new_key())
    assert main(["--var", str(tmp_path), "vault-rotate"]) == 2 and "refused" in capsys.readouterr().out


