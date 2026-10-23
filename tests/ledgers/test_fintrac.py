"""FINTRAC record-keeping (records only; nothing filed): LCTR / EFTR / LVCTR thresholds with the 24-hour rule,
holiday-aware deadlines, travel-rule completeness, structured ID-verification records, LPEPR on a confirmed sanctions
match, 5-year retention enforced by the database, legal hold."""
import datetime as dt
from decimal import Decimal

import pytest

from atlas.ledgers.banking.iso20022 import camt, validate
from atlas.ledgers.banking.iso20022.common import xsd_available
from atlas.compliance.fintrac import Fintrac, FintracError, due_date, retain_until
from atlas.ledgers.db import connect
from walletkit import Clock, fund, make_wallet, onboard

FULL = {"originator_name": "Hans Muster", "originator_address": "Hauptstr. 1, Berlin DE", "originator_account": "DE89370400440532013000",
        "beneficiary_name": "Fund Admin in trust", "beneficiary_address": "Toronto ON", "beneficiary_account": "001-00011-9988776"}


def ts(y, m, d, h=12):
    return dt.datetime(y, m, d, h).timestamp()


@pytest.fixture
def f(tmp_path):
    clock = Clock(ts(2026, 10, 1))
    fx = Fintrac(connect(str(tmp_path / "f.sqlite")), clock)
    fx.tclock = clock
    return fx


def test_deadlines_on_business_day_calendar():
    assert due_date("EFTR_IN", ts(2026, 12, 22)) == "2026-12-31"        # skips Dec 25 and Dec 28 (Boxing Day observed)
    assert due_date("LVCTR", ts(2026, 9, 25)) == "2026-10-05"           # skips Sep 30 closure + weekend
    assert due_date("LCTR", ts(2026, 12, 22)) == "2027-01-06"           # 15 calendar days
    assert due_date("LPEPR", ts(2026, 10, 14)) == "2026-10-14"          # immediately
    assert retain_until(ts(2024, 2, 29)) == "2029-02-28" and retain_until(ts(2026, 10, 1)) == "2031-10-01"


def test_threshold_and_24_hour_rule(f):
    r1 = f.observe("t", 1, "cash", "6000", "CAD", ts(2026, 10, 1, 9), "c1")
    assert r1["record"] is None
    r2 = f.observe("t", 1, "cash", "4000", "CAD", ts(2026, 10, 2, 8), "c2")     # 23h later -> aggregate 10,000
    rec = f.records()[0]
    assert r2["record"] == rec["id"] and rec["kind"] == "LCTR" and Decimal(rec["amount"]) == 10000 and rec["due_date"] == "2026-10-16"
    f.observe("t", 1, "cash", "500", "CAD", ts(2026, 10, 2, 9), "c3")           # within 24h of c2 -> extends the record
    assert len(f.records()) == 1 and Decimal(f.records()[0]["amount"]) == 10500 and len(f.records()[0]["transactions"]) == 3
    assert f.observe("t", 1, "cash", "500", "CAD", ts(2026, 10, 2, 9), "c3")["duplicate"]
    f.observe("t", 2, "cash", "9999.99", "CAD", ts(2026, 10, 3), "c4")          # other person, below threshold
    f.observe("t", 1, "cash", "9000", "CAD", ts(2026, 10, 5), "c5")             # outside the 24h window
    assert len(f.records()) == 1
    f.observe("t", 3, "virtual_currency", "10000", "CAD", ts(2026, 10, 5), "v1")
    assert f.records("LVCTR")[0]["due_date"] == "2026-10-13"                     # Thanksgiving Oct 12 skipped
    with pytest.raises(FintracError, match="exchange rate"):
        f.observe("t", 4, "wire_international", "8000", "USD", ts(2026, 10, 5), "u1")
    f.observe("t", 4, "wire_international", "8000", "USD", ts(2026, 10, 5), "u1", details=FULL, cad_rate=Decimal("1.37"))
    e = f.records("EFTR_IN")[0]
    assert Decimal(e["amount"]) == Decimal("10960.00") and e["travel_rule_missing"] == []


def test_travel_rule_and_workflow(f):
    det = dict(FULL, originator_address="")
    f.observe("t", 1, "wire_international", "25000", "CAD", ts(2026, 10, 1), "w1", details=det)
    r = f.records("EFTR_IN")[0]
    assert r["travel_rule_missing"] == ["originator_address"]
    with pytest.raises(FintracError, match="travel-rule"):
        f.mark("t", r["id"], "ready")
    with pytest.raises(FintracError, match="reason"):
        f.mark("t", r["id"], "not_required", note="no")
    f.tclock.advance(10 * 86400)
    assert f.records()[0]["overdue"] and f.status()["overdue"] == 1
    f.mark("t", r["id"], "not_required", note="duplicate of administrator's own report EFTR-123 (confirmed by phone)")
    assert not f.records()[0]["overdue"]
    assert f.observe("t", 9, "eft", "1500", "CAD", ts(2026, 10, 1), "e1", details={"originator_name": "X"})["travel_rule_missing"]


def test_id_verification_records(f):
    gid = f.record_id_verification("t", 1, "government_photo_id", {"doc_type": "passport", "issuing_jurisdiction": "CA",
                                   "doc_number_last4": "1234", "expiry": "2030-01-01", "verified_on": "2026-10-01", "manner": "in_person"}, "staff")
    assert f.id_verifications(1)[0]["id"] == gid
    bad = [("selfie", {}), ("government_photo_id", {"doc_type": "passport"}),
           ("government_photo_id", {"doc_type": "passport", "issuing_jurisdiction": "CA", "doc_number_last4": "AB123456",
                                    "expiry": "2030", "verified_on": "2026-10-01", "manner": "in_person"}),
           ("government_photo_id", {"doc_type": "passport", "issuing_jurisdiction": "CA", "doc_number_last4": "1234",
                                    "expiry": "2030", "verified_on": "2026-10-01", "manner": "video call"}),
           ("dual_process", {"source_1": "Equifax", "source_1_info": "name_address", "source_2": "equifax", "source_2_info": "name_dob", "verified_on": "x"}),
           ("dual_process", {"source_1": "Equifax", "source_1_info": "name_address", "source_2": "Hydro bill", "source_2_info": "name_address", "verified_on": "x"}),
           ("credit_file", {"bureau": "TransUnion", "file_reference_last4": "9", "file_age_years": "2", "verified_on": "x"}),
           ("credit_file", {"bureau": "TransUnion", "file_reference_last4": "9", "file_reference": "123456789", "file_age_years": "9", "verified_on": "x"})]
    for m, d in bad:
        with pytest.raises(FintracError):
            f.record_id_verification("t", 1, m, d, "staff")
    f.record_id_verification("t", 1, "dual_process", {"source_1": "Equifax", "source_1_info": "name_address", "source_2": "Hydro One bill",
                                                      "source_2_info": "name_dob", "verified_on": "2026-10-01"}, "staff")
    assert len(f.id_verifications(1)) == 2


def test_retention_enforced_by_database(f):
    f.observe("t", 1, "cash", "12000", "CAD", ts(2026, 10, 1), "c1")
    rid = f.records()[0]["id"]
    with pytest.raises(Exception, match="retention"):
        f.c.execute("DELETE FROM f_records")
    assert f.purge_expired("t")["records"] == 0
    f.tclock.advance(5 * 366 * 86400)
    f.legal_hold("t", rid, True, "litigation hold")
    assert f.purge_expired("t")["records"] == 0
    f.legal_hold("t", rid, False, "hold released")
    assert f.purge_expired("t")["records"] == 1 and f.records() == []
    with pytest.raises(Exception, match="append-only"):
        f.c.execute("DELETE FROM f_retention_log")


def test_wallet_integration_eftr_idv_and_lpepr(tmp_path):
    w = make_wallet(tmp_path)
    iid = onboard(w, "Hans Muster", country="DE", province="BE", email="h@example.com")
    idv = w.fintrac.id_verifications(iid)
    assert idv and idv[0]["method"] == "government_photo_id" and idv[0]["details"]["doc_number_last4"] == "1234"
    s = w.request_subscription("console:owner", iid, "150000", "s1")
    w.p.administrator.receive_payment(s["reference"], Decimal("150000"), "wire_international",
                                      {"name": "Hans Muster", "address": "Hauptstr. 1, 10115 Berlin", "country": "DE", "account": "DE89370400440532013000"})
    x54 = w.p.custodian.camt054()
    if xsd_available():
        assert validate(x54)["xsd"] == "valid"
    e = camt.parse(x54)["reports"][0]["entries"][0]
    assert e["bank_tx_code"] == "PMNT/RCDT/XBCT" and e["counterparty_country"] == "DE" and e["counterparty_account"].startswith("DE89")
    out = w.sync("system")
    assert out["fintrac_records"] == 1 and w.sync("system")["fintrac_records"] == 0     # idempotent
    r = w.fintrac.records("EFTR_IN")[0]
    assert r["investor_id"] == iid and Decimal(r["amount"]) == 150000 and r["travel_rule_missing"] == []
    assert r["details"]["reference"] == s["reference"] and r["due_date"] == due_date("EFTR_IN", r["first_ts"])
    # a wire whose originator has a country but no street address is a travel-rule gap (country alone is not an address)
    s2 = w.request_subscription("console:owner", iid, "25000", "s2")
    w.p.administrator.receive_payment(s2["reference"], Decimal("25000"), "wire_international",
                                      {"name": "Hans Muster", "country": "DE", "account": "DE89370400440532013000"})
    w.sync("system")
    (gap,) = w.fintrac.records("EFTR_IN")                     # same 24h window: the open record is extended
    assert Decimal(gap["amount"]) == 175000 and len(gap["transactions"]) == 2
    assert gap["travel_rule_missing"] == ["originator_address"]
    # a domestic EFT subscription creates no record
    iid2 = onboard(w, "Bob Domestic", email="b@example.com")
    fund(w, iid2, "30000")
    w.sync("system")
    assert len(w.fintrac.records()) == 1
    # confirmed sanctions match -> LPEPR draft, legal hold, property listed
    w.screening.load_docs("test", [{"source": "UN", "published": "x", "sha256": "y", "file": "t", "entries": [
        {"uid": "Z1", "kind": "individual", "name": "Hans Muster", "names": ["Hans Muster"], "dobs": [], "countries": [], "programs": ["T"], "listed_on": ""}]}])
    w.rescreen_all("test")
    h = w.screening.blocking_hits(iid)[0]
    w.screening.review(h["id"], *w.creds("owner"), "true_match", "same name, DOB and passport")
    w.screening.review(h["id"], *w.creds("cfo"), "true_match", "agree, confirmed match")
    lp = w.fintrac.records("LPEPR")[0]
    assert lp["investor_id"] == iid and lp["legal_hold"] == 1 and lp["due_date"] == dt.date.fromtimestamp(w.clock()).isoformat()
    assert lp["details"]["list"] == "UN" and any(p["type"].startswith("subscription cash") for p in lp["details"]["property"])


def test_cli_fintrac(tmp_path, capsys):
    from atlas.ledgers.cli import main
    assert main(["--var", str(tmp_path), "fintrac-status"]) == 0
    assert '"note": "records only' in capsys.readouterr().out
    assert main(["--var", str(tmp_path), "fintrac-purge"]) == 0 and '"records": 0' in capsys.readouterr().out
