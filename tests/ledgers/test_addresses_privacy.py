"""Structured addresses, close-match bank-holder review, consent log, privacy incident register and access-request
export. Offline; synthetic data only."""
import json

import pytest

from atlas.ledgers.banking.addresses import address_lines, validate_address
from atlas.ledgers.banking.bankids import InvalidIdentifier
from atlas.compliance.privacy import PrivacyError
from atlas.ledgers.wallet import bankfiles
from atlas.ledgers.wallet.service import WalletError

from walletkit import link_bank, make_wallet, onboard

ADDR = {"unit": "1201", "street": "100 King St W", "city": "Toronto", "province": "on", "postal_code": "m5x1a9", "country": "ca"}


@pytest.fixture
def w(tmp_path):
    return make_wallet(tmp_path)


def test_structured_address_validation():
    a = validate_address(ADDR)
    assert a["postal_code"] == "M5X 1A9" and a["province"] == "ON" and a["country"] == "CA"
    assert address_lines(a) == ["1201-100 King St W", "Toronto ON M5X 1A9 CA"]
    assert validate_address({"street": "1 Main St", "city": "Seattle", "province": "WA", "postal_code": "98101-1234", "country": "US"})
    assert validate_address({"street": "Hauptstr. 1", "city": "Berlin", "postal_code": "10115", "country": "DE"})
    for bad, msg in ((dict(ADDR, postal_code="H2X 1Y4"), "not in ON"), (dict(ADDR, postal_code="D1A 1A1"), "postal code"),
                     (dict(ADDR, province="XX"), "province"), (dict(ADDR, city=""), "city"), (dict(ADDR, country="CAN"), "alpha-2"),
                     (dict(ADDR, street="x" * 71), "70"), ({"street": "1 Main", "city": "X", "province": "WA", "postal_code": "9810",
                                                          "country": "US"}, "ZIP")):
        with pytest.raises(InvalidIdentifier, match=msg):
            validate_address(bad)


def test_structured_address_flows_into_pain001(w):
    iid = onboard(w, address_structured=ADDR)
    pii = w.pii(iid)
    assert pii["address_structured"]["postal_code"] == "M5X 1A9" and pii["address"] == "1201-100 King St W, Toronto ON M5X 1A9 CA"
    with pytest.raises(ValueError, match="province does not match"):
        w.create_investor("console:owner", {**pii, "legal_name": "Q Test", "province": "QC", "address_structured": ADDR})
    link_bank(w, iid)
    p = w.request_payout("console:ops", iid, "150", "vopay", "rebate", "a1")
    w.approve_payout(p["id"], *w.creds("owner"))
    w.approve_payout(p["id"], *w.creds("cfo"))
    xml = bankfiles.payfile(w, bankfiles.export_pain001(w, "console:owner")["id"], with_xml=True)["xml"]
    assert "<PstCd>M5X 1A9</PstCd>" in xml and "<CtrySubDvsn>ON</CtrySubDvsn>" in xml and "<AdrLine>" not in xml


def test_close_match_holder_name_goes_to_review(w):
    iid = onboard(w)
    assert link_bank(w, iid, "joint")["status"] == "rejected_name_mismatch"          # sole-name accounts only
    b = link_bank(w, iid, "close", cool=False)                                        # "Alice Q. Martin"
    assert b["status"] == "pending_name_review" and not b["usable"]
    (rv,) = w.name_reviews("pending")
    assert rv["holder_name"] == "Alice Q. Martin" and rv["score"] >= 0.8
    with pytest.raises(WalletError, match="10\\+"):
        w.review_bank_name("console:owner", b["id"], True, "ok")
    ok = w.review_bank_name("console:owner", b["id"], True, "Passport shows middle name Quinn; same person")
    assert ok["status"] == "verified" and ok["name_match"] == 1 and not ok["usable"]   # cooling-off restarts at approval
    w.tclock.advance(25 * 3600)
    assert w.bank(b["id"])["usable"] and w._payout_account(iid, b["id"])["holder_name"] == "Alice Q. Martin"
    with pytest.raises(WalletError, match="no pending"):
        w.review_bank_name("console:owner", b["id"], False, "second look, changed mind")
    b2 = link_bank(w, iid, "close", cool=False)
    assert w.review_bank_name("console:cfo", b2["id"], False, "documents do not match bank record")["status"] == "rejected_name_mismatch"
    assert link_bank(w, iid, "third_party")["status"] == "rejected_name_mismatch" and len(w.name_reviews()) == 2


def test_consent_log_append_only(w):
    iid = onboard(w)
    pv = w.privacy
    pv.record_consent("portal:alice", iid, "service", True, "2026-01", "portal_checkbox")
    pv.record_consent("portal:alice", iid, "marketing", True, "2026-01", "portal_checkbox")
    pv.record_consent("portal:alice", iid, "marketing", False, "2026-01", "portal_checkbox")
    cur = {c["purpose"]: c for c in pv.consents(iid)["current"]}
    assert cur["service"]["granted"] and not cur["marketing"]["granted"] and len(pv.consents(iid)["history"]) == 3
    assert pv.has_consent(iid, "service") and not pv.has_consent(iid, "marketing")
    for args, msg in ((("service", False, "2026-01", "portal_checkbox"), "required"), (("ads", True, "v", "portal_checkbox"), "unknown"),
                      (("marketing", True, "", "portal_checkbox"), "notice"), (("marketing", True, "v", "pre-ticked"), "method")):
        with pytest.raises(PrivacyError, match=msg):
            pv.record_consent("x", iid, *args)
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("UPDATE p_consents SET granted=1")
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("DELETE FROM p_consents")


def test_incident_register_and_access_request_export(w):
    iid = onboard(w)
    link_bank(w, iid)
    pv = w.privacy
    inc = pv.record_incident("console:owner", summary="Statement PDF emailed to the wrong investor", detected_at="2026-10-01",
                             data_types=["name", "holdings"], individuals=1, investor_ids=[iid])
    assert pv.incident(inc)["retain_until"] == "2028-09-30" and pv.status()["open_incidents"] == 1
    with pytest.raises(PrivacyError, match="must be notified"):
        pv.assess_incident("console:owner", inc, True, "financial data, recipient unknown", close=True)
    done = pv.assess_incident("console:owner", inc, True, "financial data, recipient unknown", "2026-10-03", "2026-10-03", close=True)
    assert done["status"] == "closed" and done["rrosh"] == "yes" and len(done["history"]) == 1
    assert pv.purge_incidents("t") == 0                                               # 24-month retention
    req = pv.open_access_request("console:owner", iid, "2026-10-01")
    assert req["due_on"] == "2026-10-31"
    assert pv.extend_access_request("console:owner", req["id"], "large volume of records to compile")["due_on"] == "2026-11-30"
    with pytest.raises(PrivacyError, match="once"):
        pv.extend_access_request("console:owner", req["id"], "another reason, longer")
    exp = w.access_export("console:owner", iid, req["id"])
    blob = json.dumps(exp["data"], default=str)
    assert exp["data"]["investor"]["legal_name"] == "Alice Martin" and exp["data"]["bank_accounts"][0]["account_masked"].startswith("•")
    assert "account_number" not in blob and "s_hits" not in blob and any("sanctions" in x for x in exp["data"]["withheld"])
    assert pv.access_request(req["id"])["status"] == "completed" and pv.access_request(req["id"])["export_sha256"] == exp["sha256"]
    late = pv.open_access_request("console:owner", iid, "2020-01-01")
    assert pv.access_request(late["id"])["overdue"] and pv.status()["overdue_access_requests"] == 1
