"""ISO 20022 (SIMULATION/offline): camt.053/054 parsing + reconciliation, pain.001 generation, pain.002 parsing and
application; XSD-valid against the official schemas (when xmlschema is installed) plus structural checks."""
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.ledgers.banking.iso20022 import XMLError, camt, pain, validate
from atlas.ledgers.banking.iso20022.common import safe_parse, xsd_available
from atlas.ledgers.wallet import bankfiles, recon
from atlas.ledgers.wallet.partners import ACCOUNT_IDS, TRUST
from walletkit import fund, link_bank, make_wallet, onboard

FIX = Path(__file__).parent / "fixtures" / "iso20022"
DEBTOR = {"name": "Trust", "account": "9988776", "institution": "001", "transit": "00011"}
CRED = {"name": "Alice Martin", "account": "1234567", "institution": "003", "transit": "12345",
        "address": {"street": "King St W", "building": "1", "postal_code": "M5H 1A1", "town": "Toronto", "subdivision": "ON", "country": "CA"}}


@pytest.fixture
def w(tmp_path):
    return make_wallet(tmp_path)


def _p001(**kw):
    txs = kw.pop("txs", [{"end_to_end_id": "REL-1", "amount": "100.10", "currency": "CAD", "creditor": CRED, "remittance": "r"}])
    return pain.build_pain001("MSG-1", 1_790_000_000, DEBTOR, "2026-10-15", txs, **kw)


def test_xsd_bundled_and_used():
    pytest.importorskip("xmlschema")
    assert xsd_available()
    v = validate(_p001())
    assert v == {"message": "pain.001.001.09", "xsd": "valid", "errors": []}


def test_pain001_canadian_and_iban_creditors_schema_valid():
    pytest.importorskip("xmlschema")
    xml = _p001(txs=[{"end_to_end_id": "A", "amount": "5", "currency": "CAD", "creditor": CRED},
                     {"end_to_end_id": "B", "amount": "7.5", "currency": "EUR",
                      "creditor": {"name": "Hans Muster", "iban": "DE89370400440532013000", "bic": "DEUTDEFF",
                                   "address": {"country": "DE", "lines": ["Hauptstr. 1", "10115 Berlin"]}}}])
    assert validate(xml)["xsd"] == "valid"
    assert "<ClrSysMmbId>" in xml and "<Cd>CACPA</Cd>" in xml and "<MmbId>000312345</MmbId>" in xml
    p = pain.parse_pain001(xml)
    assert p["nb_of_txs"] == 2 and p["ctrl_sum"] == "12.50" and {t["currency"] for t in p["txs"]} == {"CAD", "EUR"}
    assert p["txs"][0]["creditor_agent"] == "000312345"


def test_pain001_input_checks():
    with pytest.raises(XMLError, match="unique"):
        _p001(txs=[{"end_to_end_id": "X", "amount": 1, "creditor": CRED}, {"end_to_end_id": "X", "amount": 2, "creditor": CRED}])
    with pytest.raises(ValueError):
        _p001(txs=[{"end_to_end_id": "X", "amount": 1, "creditor": {**CRED, "transit": "12"}}])
    with pytest.raises(XMLError, match="name"):
        _p001(txs=[{"end_to_end_id": "X", "amount": 1, "creditor": {**CRED, "name": ""}}])
    with pytest.raises(XMLError, match="unsigned"):
        _p001(txs=[{"end_to_end_id": "X", "amount": -1, "creditor": CRED}])


def test_structural_validation_catches_tampering():
    xml = _p001().replace("<NbOfTxs>1</NbOfTxs>", "<NbOfTxs>2</NbOfTxs>", 1)
    with pytest.raises(XMLError, match="NbOfTxs"):
        validate(xml)
    xml = _p001().replace("<CtrlSum>100.10</CtrlSum>", "<CtrlSum>999.00</CtrlSum>", 1)
    with pytest.raises(XMLError, match="CtrlSum"):
        validate(xml)
    with pytest.raises(XMLError, match="expected pain.002"):
        validate(_p001(), "pain.002")
    with pytest.raises(XMLError, match="ISO 20022"):
        validate("<a/>")


def test_xxe_and_dtd_refused():
    evil = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><Document>&x;</Document>'
    with pytest.raises(XMLError, match="DOCTYPE"):
        safe_parse(evil)
    with pytest.raises(XMLError, match="malformed"):
        safe_parse("<Document>")


def test_pain002_roundtrip_and_parse():
    pytest.importorskip("xmlschema")
    p1 = _p001(txs=[{"end_to_end_id": "A", "amount": 1, "creditor": CRED}, {"end_to_end_id": "B", "amount": 2, "creditor": CRED}])
    p2 = pain.build_pain002("ST-1", 1_790_000_100, p1, {"B": "AC04"})
    assert validate(p2)["xsd"] == "valid"
    r = pain.parse_pain002(p2)
    assert r["orig_msg_id"] == "MSG-1" and r["group_status"] == "PART"
    assert [(t["end_to_end_id"], t["status"], t["reason"]) for t in r["txs"]] == [("A", "ACSC", None), ("B", "RJCT", "AC04")]
    assert r["txs"][1]["reason_text"] == "closed account"


def test_camt053_v02_bank_fixture_parses():
    doc = camt.parse((FIX / "camt053_v02_bank_sample.xml").read_text())
    assert doc["message"] == "camt.053.001.02"
    r = doc["reports"][0]
    assert r["account"] == "001-00011-9988776" and r["closing"]["amount"] == Decimal("26750.00")
    assert r["check"]["opening_plus_booked_equals_closing"]
    e1, e2 = r["entries"]
    assert e1["remittance"].startswith("SUB-0A1B2C3D") and e1["bank_tx_code"] == "PMNT/RCDT/DMCT" and e1["status"] == "BOOK"
    assert e1["counterparty"] == "NORTHWIND HOLDINGS"
    assert e2["bank_tx_code"] == "WIRE-IN" and e2["remittance"] == "INCOMING WIRE NO REFERENCE" and e2["value_date"] == "2026-10-15"


def test_camt_generated_by_custodian_is_schema_valid(w):
    pytest.importorskip("xmlschema")
    iid = onboard(w)
    fund(w, iid, "50000")
    x53, x54 = w.p.custodian.camt053(), w.p.custodian.camt054()
    assert validate(x53)["xsd"] == "valid" and validate(x54)["xsd"] == "valid"
    doc = camt.parse(x53)
    trust = next(r for r in doc["reports"] if r["account"] == ACCOUNT_IDS[TRUST])
    assert trust["closing"]["amount"] == Decimal("50000.00") and all(r["check"]["opening_plus_booked_equals_closing"] for r in doc["reports"])
    n = camt.parse(x54)["reports"][0]["entries"]
    assert len(n) == 1 and n[0]["remittance"].startswith("incoming subscription SUB-")


def test_recon_uses_camt_and_flags_unidentified_receipts(w):
    iid = onboard(w)
    fund(w, iid, "50000")
    w.sync("system")
    r = recon.run(w)
    assert r["status"] == "clean", r["breaks"]
    assert r["summary"]["custodian_source"].startswith("camt.053 CAMT053-") and r["summary"]["receipts_checked"] == 1
    w.p.administrator.sim.line(TRUST, Decimal("750"), "INCOMING WIRE NO REFERENCE")
    r = recon.run(w)
    checks = {b["check"] for b in r["breaks"]}
    assert "receipts" in checks and "trust_cash_in_transit" in checks
    rb = next(b for b in r["breaks"] if b["check"] == "receipts")
    assert rb["custodian"] == "750.00" and "return" in rb["note"]


def test_recon_with_uploaded_unbalanced_statement(w):
    bad = (FIX / "camt053_v02_bank_sample.xml").read_text().replace("26750.00", "26700.00")
    r = recon.run(w, camt053=bad, camt054=(FIX / "camt053_v02_bank_sample.xml").read_text().replace("camt.053", "camt.054")
                  .replace("BkToCstmrStmt", "BkToCstmrDbtCdtNtfctn").replace("<Stmt>", "<Ntfctn>").replace("</Stmt>", "</Ntfctn>"))
    checks = [b["check"] for b in r["breaks"]]
    assert "custodian_statement" in checks
    assert r["summary"]["custodian_source"] == "camt.053 BANKSTMT20261014"
    # SUB-0A1B2C3D is not a known subscription, the no-reference wire neither -> 2 receipt breaks
    assert checks.count("receipts") == 2


def _paid_payouts(w, n=2):
    iid = onboard(w)
    link_bank(w, iid)
    ids = []
    for k in range(n):
        p = w.request_payout("console:ops", iid, str(100 + k), "vopay", "rebate", f"np{k}")
        w.approve_payout(p["id"], *w.creds("owner"))
        ids.append(w.approve_payout(p["id"], *w.creds("cfo"))["id"])
    return ids


def test_pain001_export_and_pain002_application(w):
    ids = _paid_payouts(w)
    f = bankfiles.export_pain001(w, "console:owner")
    assert f["n"] == 2 and f["total"] == "201.00" and f["status"] == "generated"
    assert f["xsd"] in ("valid", "unavailable") and (f["xsd"] == "valid") == xsd_available()
    full = bankfiles.payfile(w, f["id"], with_xml=True)
    parsed = pain.parse_pain001(full["xml"])
    assert {t["end_to_end_id"] for t in parsed["txs"]} == {w.payout(i)["release_ref"] for i in ids}
    assert parsed["txs"][0]["creditor"] == "Alice Martin" and parsed["txs"][0]["creditor_account"].isdigit()
    assert parsed["txs"][0]["execution_date"] >= "2026-09-21"
    with pytest.raises(bankfiles.BankFileError, match="no released"):
        bankfiles.export_pain001(w, "console:owner")              # already filed
    rej = w.payout(ids[1])["release_ref"]
    rep = bankfiles.simulate_bank_response(w, f["id"], {rej: "AC01"})
    out = bankfiles.apply_pain002(w, "console:owner", rep)
    assert out["returned"] == [ids[1]] and out["file_status"] == "partially_rejected"
    assert w.payout(ids[1])["status"] == "returned" and "AC01" in w.payout(ids[1])["note"]
    assert w.payout(ids[0])["status"] == "paid"
    with pytest.raises(bankfiles.BankFileError, match="already applied"):
        bankfiles.apply_pain002(w, "console:owner", rep)
    other = pain.build_pain002("ST-X", 1, _p001())
    with pytest.raises(bankfiles.BankFileError, match="unknown payment file"):
        bankfiles.apply_pain002(w, "console:owner", other)
    # reconciliation surfaces the returned payout (partner reported paid, internal says returned)
    assert any(b["check"] == "payouts" for b in recon.run(w)["breaks"])
