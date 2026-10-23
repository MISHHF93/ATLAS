"""Sanctions screening (SIMULATION/offline): list parsers (CA SEMA/JVCFOA, UN, OFAC), fuzzy matching, two-person
hit review, money movement blocked while a hit is open/confirmed, fail-closed without lists, manual downloader."""
import importlib.util
import io
import json
from pathlib import Path

import pytest

from atlas.compliance import lists as L
from atlas.compliance.matching import name_score, normalise
from atlas.ledgers.wallet.service import SanctionsHold
from walletkit import fund, link_bank, make_wallet, onboard, person

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def w(tmp_path):
    return make_wallet(tmp_path)


def _doc(source, *names, dob=""):
    return {"source": source, "published": "2026-10-14", "sha256": "x" * 64, "file": "t.xml",
            "entries": [{"uid": f"T{i}", "kind": "individual", "name": n, "names": [n], "dobs": [dob] if dob else [], "countries": [],
                         "programs": ["TEST"], "listed_on": ""} for i, n in enumerate(names)]}


def test_sample_list_parsers():
    docs = {d["source"]: d for d in L.parse_dir(L.SAMPLE_DIR)}
    assert set(docs) == {"CA-SEMA", "UN", "OFAC-SDN"}
    sema = {e["name"]: e for e in docs["CA-SEMA"]["entries"]}
    assert sema["Ivan Petrovich Sidorenko"]["kind"] == "individual" and "I. P. Sidorenko" in sema["Ivan Petrovich Sidorenko"]["names"]
    assert sema["Northern Star"]["kind"] == "vessel" and sema["Volga Maritime Trading JSC"]["kind"] == "entity"
    assert sema["Jane Northwood"]["dobs"] == ["1975/06/02"]
    un = {e["uid"]: e for e in docs["UN"]["entries"]}
    assert un["QDi.990"]["names"] == ["SANCTIONED PERSON DEMO", "Sanctioned P. Demo"] and un["QDi.990"]["low_quality_aliases"] == ["The Demo"]
    assert un["KPe.992"]["kind"] == "entity" and un["TAi.991"]["dobs"] == ["1958"]
    ofac = {e["uid"]: e for e in docs["OFAC-SDN"]["entries"]}
    assert ofac["990001"]["names"] == ["Mohammed AL-RASHIDI", "Muhammad RASHIDI"] and ofac["990001"]["programs"] == ["SDGT"]
    assert ofac["990003"]["kind"] == "vessel" and docs["OFAC-SDN"]["published"] == "10/14/2026"


def test_parser_tolerates_variants_and_refuses_bad_files(tmp_path):
    (tmp_path / "a.xml").write_text("<data-set><record><FamilyName>Doe</FamilyName><GivenNames>John Q</GivenNames>"
                                    "<country>Testland</country><schedule>1</schedule><item>7</item></record></data-set>")
    d = L.parse_file(tmp_path / "a.xml")
    assert d["source"] == "CA-SEMA" and d["entries"][0]["name"] == "John Q Doe"
    (tmp_path / "old.xml").write_text('<sdnList xmlns="http://tempuri.org/sdnList.xsd"><sdnEntry><uid>1</uid><lastName>ACME FRONT</lastName>'
                                      '<sdnType>Entity</sdnType></sdnEntry></sdnList>')
    assert L.parse_file(tmp_path / "old.xml")["entries"][0]["kind"] == "entity"
    (tmp_path / "e.xml").write_text("<CONSOLIDATED_LIST/>")
    with pytest.raises(ValueError, match="empty"):
        L.parse_file(tmp_path / "e.xml")
    (tmp_path / "h.xml").write_text("<html><body>captive portal</body></html>")
    with pytest.raises(ValueError, match="unrecognised"):
        L.parse_file(tmp_path / "h.xml")
    (tmp_path / "x.xml").write_text('<!DOCTYPE x [<!ENTITY a "b">]><data-set/>')
    with pytest.raises(ValueError, match="DOCTYPE"):
        L.parse_file(tmp_path / "x.xml")
    with pytest.raises(ValueError, match="sha256"):
        L.parse_file(tmp_path / "a.xml", expected_sha256="0" * 64)


def test_matching_quality():
    assert name_score("Vladimir Putin", "PUTIN, Vladimir Vladimirovich") >= 0.9
    assert name_score("José Muñoz", "Jose Munoz") == 1.0 and normalise("Ørsted-Æble") == "orsted aeble"
    assert name_score("Northwind Holdings Ltd", "North Wind Holdings Limited") >= 0.9
    assert name_score("Mohammed Al-Rashidi", "Muhammad Rashidi") >= 0.9
    assert name_score("Jane Northwind", "Jane Northwood") >= 0.9            # close match -> human review
    for a, b in [("Alice Martin", "Ali Hemmatian"), ("Vladimir Putin", "Vladimir Turin"), ("Northwind Holdings", "North Group Holding Corp"),
                 ("Bank Rossiya", "Sina Bank"), ("Carol Nguyen", "Carol"), ("Vladimir Putin", "Vladimir P. Kononov")]:
        assert name_score(a, b) < 0.88, (a, b, name_score(a, b))


def test_dob_and_party_type_adjust_score(w):
    sc = w.screening
    exact = sc.match("Ivan Sidorenko", dob="1961-03-14")
    assert exact and exact[0]["score"] == 1.0 and "birth year matches" in exact[0]["reasons"]
    assert sc.match("Ivan Sidorenko", dob="1990-01-01") == [] or sc.match("Ivan Sidorenko", dob="1990-01-01")[0]["score"] <= 0.9
    assert all(h["kind"] == "vessel" for h in sc.match("Northern Star"))
    st = sc.status()
    assert st["required"] and {a["source"] for a in st["lists"]} == {"CA-SEMA", "UN", "OFAC-SDN"}
    assert any("SYNTHETIC" in x for x in st["warnings"])


def test_fail_closed_without_lists(tmp_path):
    w = make_wallet(tmp_path)
    w.c.execute("UPDATE s_lists SET active=0")
    with pytest.raises(SanctionsHold, match="no sanctions lists"):
        w.submit_onboarding("console:owner", w.create_investor("console:owner", person()))
    assert any("BLOCKED" in x for x in w.screening.status()["warnings"])
    w.c.execute("INSERT OR REPLACE INTO settings VALUES('sanctions_required','0')")    # testing only
    w.submit_onboarding("console:owner", 1)


def test_onboarding_hit_two_person_clear_then_suppressed(w):
    iid = w.create_investor("console:owner", person("Jane Northwood", dob_or_incorporation="1990-02-02", email="j@example.com"))
    with pytest.raises(SanctionsHold, match="under review"):
        w.submit_onboarding("console:owner", iid)
    h = w.screening.blocking_hits(iid)[0]
    assert h["source"] == "CA-SEMA" and h["status"] == "open" and h["context"] == "onboarding"
    with pytest.raises(ValueError, match="rationale"):
        w.screening.review(h["id"], *w.creds("owner"), "false_positive", "no")
    with pytest.raises(ValueError, match="decision"):
        w.screening.review(h["id"], *w.creds("owner"), "maybe", "long enough reason")
    r1 = w.screening.review(h["id"], *w.creds("owner"), "false_positive", "DOB 1990 vs listed 1975; different person")
    assert r1["status"] == "pending_second"
    with pytest.raises(PermissionError, match="different reviewer"):
        w.screening.review(h["id"], *w.creds("owner"), "false_positive", "again by the same reviewer")
    with pytest.raises(SanctionsHold):
        w.submit_onboarding("console:owner", iid)                 # still blocking after one review
    r2 = w.screening.review(h["id"], *w.creds("cfo"), "false_positive", "agree: DOB and nationality differ")
    assert r2["status"] == "cleared" and r2["decision"] == "false_positive" and len(r2["dispositions"]) == 2
    w.submit_onboarding("console:owner", iid)                     # re-screen suppresses the cleared pair
    assert w.investor(iid)["status"] == "submitted"
    assert w.c.execute("SELECT COUNT(*) FROM s_hits WHERE investor_id=?", (iid,)).fetchone()[0] == 1
    with pytest.raises(Exception, match="append-only"):
        w.c.execute("DELETE FROM s_dispositions")


def test_open_hit_blocks_payouts_and_money_movement(w):
    iid = onboard(w)
    link_bank(w, iid)
    fund(w, iid, "50000")
    p = w.request_payout("console:ops", iid, "250", "zumrails", "referral", "np1")
    w.approve_payout(p["id"], *w.creds("owner"))
    w.screening.load_docs("test", [_doc("OFAC-SDN", "Alice Martin")])             # newly listed after onboarding
    assert w.rescreen_all("test")["new_hits"] == 1
    for call in (lambda: w.approve_payout(p["id"], *w.creds("cfo")),
                 lambda: w.request_payout("console:ops", iid, "10", "zumrails", "x", "np2"),
                 lambda: w.request_subscription("console:owner", iid, "1000", "s2"),
                 lambda: w.request_redemption("console:owner", iid, "1", "r1")):
        with pytest.raises(SanctionsHold, match="sanctions hit under review"):
            call()
    assert w.payout(p["id"])["status"] == "pending_approval"
    h = w.screening.blocking_hits(iid)[0]
    w.screening.review(h["id"], *w.creds("owner"), "true_match", "same name and DOB as listed person")
    w.screening.review(h["id"], *w.creds("cfo"), "false_positive", "disagree; escalate")
    assert w.screening.hit(h["id"])["status"] == "escalated"
    with pytest.raises(SanctionsHold):
        w.approve_payout(p["id"], *w.creds("cfo"))
    done = w.screening.review(h["id"], *w.creds("ops"), "true_match", "third reviewer: confirmed match")
    assert done["status"] == "confirmed"
    with pytest.raises(SanctionsHold, match="confirmed sanctions match"):
        w.approve_payout(p["id"], *w.creds("cfo"))
    with pytest.raises(PermissionError, match="already confirmed"):
        w.screening.review(h["id"], *w.creds("owner"), "false_positive", "cannot reopen a closed hit")
    acts = {r[0] for r in w.c.execute("SELECT action FROM audit")}
    assert {"wallet.sanctions.hit", "wallet.sanctions.review", "wallet.sanctions.blocked", "wallet.sanctions.list_load"} <= acts


def test_list_reload_supersedes_and_staleness(w):
    w.screening.load_docs("test", [_doc("UN", "Someone Else")])
    act = {a["source"]: a for a in w.screening.active_lists()}
    assert act["UN"]["entries"] == 1 and act["UN"]["sample"] == 0
    assert w.c.execute("SELECT COUNT(*) FROM s_lists WHERE source='UN' AND active=0").fetchone()[0] == 1
    assert w.screening.match("Sanctioned Person Demo") == []                # old UN entries gone
    w.tclock.advance(9 * 86400)
    assert any("stale" in x for x in w.screening.status()["warnings"])


def _fetcher():
    spec = importlib.util.spec_from_file_location("fetch_sanctions_lists", ROOT / "tools" / "fetch_sanctions_lists.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_downloader_offline_with_fake_opener(tmp_path):
    m = _fetcher()
    samples = {"sema": (L.SAMPLE_DIR / "sema-lmes.sample.xml").read_bytes(), "consolidated": (L.SAMPLE_DIR / "un-consolidated.sample.xml").read_bytes(),
               "sdn": (L.SAMPLE_DIR / "ofac-sdn.sample.xml").read_bytes()}
    calls = []

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout):
        calls.append(req.full_url)
        assert req.full_url.startswith("https://")
        key = next(k for k in samples if k in req.full_url)
        return R(samples[key])
    res = m.run(tmp_path, opener=opener)
    assert all(v.startswith("ok") for v in res.values()) and len(calls) == 3
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert {f["source"] for f in man["files"]} == {"CA-SEMA", "UN", "OFAC-SDN"}
    assert {d["source"] for d in L.parse_dir(tmp_path)} == {"CA-SEMA", "UN", "OFAC-SDN"}   # sha256 verified
    # a captive-portal page never replaces a good file
    res = m.run(tmp_path, only=["UN"], opener=lambda req, timeout: R(b"<html>login</html>"))
    assert res["UN"].startswith("FAILED") and L.parse_file(tmp_path / "un-consolidated.xml")["source"] == "UN"
    (tmp_path / "ofac-sdn.xml").write_bytes(samples["sdn"].replace(b"SEA FALCON", b"SEA FALCOX"))
    with pytest.raises(ValueError, match="sha256"):
        L.parse_dir(tmp_path)
    with pytest.raises(ValueError, match="HTTPS"):
        m.fetch("http://example.com/x.xml", opener)


def test_cli_sanctions_and_calendar(tmp_path, capsys):
    from atlas.ledgers.cli import main
    assert main(["--var", str(tmp_path), "sanctions-load", "--samples"]) == 0
    out = capsys.readouterr().out
    assert "loaded CA-SEMA: 5 entries" in out and "loaded UN" in out
    main(["--var", str(tmp_path), "sanctions-screen", "Muhammad Rashidi"])
    assert '"source": "OFAC-SDN"' in capsys.readouterr().out
    main(["--var", str(tmp_path), "calendar", "2026"])
    assert "2026-09-30 Wed  National Day for Truth and Reconciliation" in capsys.readouterr().out
    assert main(["--var", str(tmp_path), "validate-id", "aba", "021000022"]) == 1
