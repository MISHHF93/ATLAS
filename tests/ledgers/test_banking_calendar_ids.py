"""Business-day calendars (Payments Canada closures, provincial overlays, US Fed) and identifier validators
(Canadian DPRN/MICR/account, IBAN, BIC, ABA, PAN detection), plus their wiring into wallet dates and bank linking."""
import ast
import datetime as dt
from pathlib import Path

import pytest

from atlas.ledgers.banking import bankids as b
from atlas.ledgers.banking import calendars as cal
from atlas.ledgers.wallet.service import WalletError
from walletkit import make_wallet, onboard, person

D = dt.date
SRC = Path(__file__).resolve().parents[2] / "src" / "atlas"
NET = {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "tradingbot", "ssl", "paramiko", "ftplib", "smtplib"}


def test_payments_canada_2026_matches_published_schedule():
    assert set(cal.holidays(2026)) == cal.PUBLISHED[("CA", 2026)]
    assert cal.holiday_name("2026-09-30") == "National Day for Truth and Reconciliation"
    assert cal.holiday_name("2026-12-28") == "Boxing Day (observed)"


def test_payments_canada_2027_rules():
    assert set(cal.holidays(2027)) == {D(2027, 1, 1), D(2027, 3, 26), D(2027, 5, 24), D(2027, 7, 1), D(2027, 9, 6),
                                       D(2027, 9, 30), D(2027, 10, 11), D(2027, 11, 11), D(2027, 12, 27), D(2027, 12, 28)}
    # weekend shifts in other years: Canada Day 2023 Sat -> Mon Jul 3; Sep 30 2023 Sat -> Mon Oct 2
    assert D(2023, 7, 3) in cal.holidays(2023) and D(2023, 10, 2) in cal.holidays(2023)


def test_not_system_closures_but_provincial():
    for d in ("2026-04-06", "2026-08-03", "2026-02-16"):  # Easter Monday, Civic Holiday, Family Day
        assert cal.is_business_day(d)
    assert not cal.is_business_day("2026-02-16", "CA-ON")
    assert not cal.is_business_day("2026-06-24", "CA-QC") and cal.is_business_day("2026-06-24", "CA-ON")
    assert not cal.is_business_day("2026-08-03", "CA-BC")
    assert cal.holiday_name("2026-02-16", "CA-MB") == "Louis Riel Day"
    with pytest.raises(ValueError):
        cal.holidays(2026, "CA-XX")


def test_us_fed_calendar():
    us = cal.holidays(2026, "US")
    assert D(2026, 7, 3) not in us and D(2026, 7, 4) not in us     # Saturday holiday not observed by the Fed
    assert D(2026, 11, 26) in us and D(2026, 6, 19) in us and D(2026, 1, 19) in us
    assert D(2027, 7, 5) in cal.holidays(2027, "US") or D(2027, 7, 4).weekday() != 6


def test_business_day_arithmetic():
    assert cal.last_business_day_of_month("2026-09-03") == D(2026, 9, 29)      # Sep 30 closure
    assert cal.last_business_day_of_month("2026-10-15") == D(2026, 10, 30)     # Oct 31 Saturday
    assert cal.last_business_day_of_month("2026-12-01") == D(2026, 12, 31)
    assert cal.next_business_day("2026-09-29") == D(2026, 10, 1)
    assert cal.add_business_days("2026-12-24", 1) == D(2026, 12, 29)
    assert cal.add_business_days("2026-10-01", -1) == D(2026, 9, 29)
    assert cal.business_days_between("2026-12-24", "2026-12-31") == 3
    assert cal.value_date("2026-09-30") == D(2026, 10, 1) and cal.value_date("2026-10-01") == D(2026, 10, 1)
    assert cal.easter(2026) == D(2026, 4, 5) and cal.easter(2027) == D(2027, 3, 28)
    assert {r["date"] for r in cal.calendar_view(2026)} == {d.isoformat() for d in cal.PUBLISHED[("CA", 2026)]}


def test_wallet_dates_use_calendar():
    from atlas.ledgers.manual import next_business_day
    from atlas.ledgers.wallet.partners import month_end
    assert month_end(D(2026, 9, 10)) == D(2026, 9, 29)
    assert next_business_day(D(2026, 9, 29)) == D(2026, 10, 1)
    assert next_business_day(D(2026, 12, 24)) == D(2026, 12, 29)


def test_canadian_routing_and_accounts():
    a = b.validate_ca_account("004", "12345", "1234567")
    assert a.dprn == "000412345" and a.micr == "12345-004" and a.institution_name.startswith("The Toronto")
    assert b.micr_to_dprn("12345-004") == "000412345" and b.dprn_to_micr("000412345") == "12345-004"
    assert b.parse_dprn("000312345") == ("003", "12345")
    for bad in [("04", "12345", "1234567"), ("004", "1234", "1234567"), ("004", "12345", "12ab567"),
                ("004", "12345", "123456"), ("003", "12345", "12345678")]:   # RBC accounts are 7 digits
        with pytest.raises(b.InvalidIdentifier):
            b.validate_ca_account(*bad)
    with pytest.raises(b.InvalidIdentifier):
        b.parse_dprn("100412345")
    with pytest.raises(b.InvalidIdentifier):
        b.validate_institution("999", known_only=True)


def test_iban_bic_aba():
    assert b.validate_iban("GB82 WEST 1234 5698 7654 32") == "GB82WEST12345698765432"
    assert b.format_iban("DE89370400440532013000") == "DE89 3704 0044 0532 0130 00"
    for bad in ("GB82WEST12345698765431", "DE8937040044053201300", "CA82WEST12345698765432", "12"):
        with pytest.raises(b.InvalidIdentifier):
            b.validate_iban(bad)
    assert b.validate_bic("roycCAT2") == "ROYCCAT2" and b.validate_bic("DEUTDEFF500") == "DEUTDEFF500"
    for bad in ("ROYCCAT", "ROYCZZT2", "ROYC CA T2X", "1OYCCAT2", "ROYCCAT0"):
        with pytest.raises(b.InvalidIdentifier):
            b.validate_bic(bad)
    assert b.validate_aba("021000021") == "021000021" and b.validate_aba("011000015")
    for bad in ("021000022", "991000021", "02100002"):
        with pytest.raises(b.InvalidIdentifier):
            b.validate_aba(bad)
    assert b.validate_any("dprn", "000412345")["micr"] == "12345-004"
    assert b.validate_any("ca_account", "1234567", institution="004", transit="12345")["dprn"] == "000412345"


def test_pan_detection():
    assert b.contains_pan("4111 1111 1111 1111") and b.contains_pan("x5555-5555-5555-4444y")
    assert not b.contains_pan("4111 1111 1111 1112")       # Luhn fails
    assert not b.contains_pan("+1 416 555 1234") and not b.contains_pan("1980-01-01")


def test_wallet_refuses_card_numbers_and_invalid_bank(tmp_path):
    w = make_wallet(tmp_path)
    with pytest.raises(ValueError, match="card"):
        w.create_investor("owner", person(occupation="card 4111111111111111"))
    iid = onboard(w)
    bv = w.p.bank_verification
    orig = bv.fetch
    bv.fetch = lambda pub: {**orig(pub), "transit": "12"}
    with pytest.raises(WalletError, match="invalid Canadian account"):
        w.bank_link_complete("owner", iid, w.bank_link_start(iid), "td")
    bv.fetch = orig
    assert w.bank_link_complete("owner", iid, w.bank_link_start(iid), "td")["status"] == "verified"


def test_banking_and_compliance_have_no_network_imports():
    for pkg in ("ledgers/banking", "compliance", "ledgers/wallet"):
        for f in (SRC / pkg).rglob("*.py"):
            mods = set()
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    mods |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    mods.add(n.module.split(".")[0])
            assert not mods & NET, (f, mods)
