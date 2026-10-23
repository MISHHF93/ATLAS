"""Structured postal addresses (ISO 20022 PostalAddress24 fields: no free-text-only addresses for payments).

Canada: province/territory code + postal code (A1A 1A1; first letter checked against the province). US: state code
+ ZIP / ZIP+4. Elsewhere: town + ISO country required. Pure validation, no network lookups."""
from __future__ import annotations

import re

from atlas.ledgers.banking.bankids import InvalidIdentifier

CA_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
CA_POSTAL_FIRST = {"A": {"NL"}, "B": {"NS"}, "C": {"PE"}, "E": {"NB"}, "G": {"QC"}, "H": {"QC"}, "J": {"QC"},
                   "K": {"ON"}, "L": {"ON"}, "M": {"ON"}, "N": {"ON"}, "P": {"ON"}, "R": {"MB"}, "S": {"SK"},
                   "T": {"AB"}, "V": {"BC"}, "X": {"NT", "NU"}, "Y": {"YT"}}
CA_POSTAL = re.compile(r"^([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]) ?(\d[ABCEGHJ-NPRSTV-Z]\d)$")
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
                "PA RI SC SD TN TX UT VT VA WA WV WI WY PR GU VI AS MP".split())
FIELDS = ("unit", "building", "street", "city", "province", "postal_code", "country")
MAX = {"unit": 16, "building": 16, "street": 70, "city": 35, "province": 35, "postal_code": 16, "country": 2}


def validate_address(a: dict) -> dict:
    """Return a normalised structured address or raise InvalidIdentifier (a ValueError)."""
    if not isinstance(a, dict):
        raise InvalidIdentifier("address_structured must be an object")
    d = {k: " ".join(str(a.get(k) or "").split()) for k in FIELDS}
    d["country"], d["province"] = d["country"].upper(), d["province"].upper() if len(d["province"]) <= 3 else d["province"]
    for k in ("street", "city", "country"):
        if not d[k]:
            raise InvalidIdentifier(f"address: {k} is required")
    if not re.fullmatch(r"[A-Z]{2}", d["country"]):
        raise InvalidIdentifier("address: country must be an ISO 3166 alpha-2 code")
    for k, n in MAX.items():
        if len(d[k]) > n:
            raise InvalidIdentifier(f"address: {k} longer than {n} characters (ISO 20022 limit)")
    if d["country"] == "CA":
        if d["province"] not in CA_PROVINCES:
            raise InvalidIdentifier("address: province must be a Canadian province/territory code (e.g. ON, QC)")
        m = CA_POSTAL.match(d["postal_code"].upper().replace("-", " ").strip())
        if not m:
            raise InvalidIdentifier("address: invalid Canadian postal code (A1A 1A1)")
        d["postal_code"] = f"{m.group(1)} {m.group(2)}"
        if d["province"] not in CA_POSTAL_FIRST[d["postal_code"][0]]:
            raise InvalidIdentifier(f"address: postal code {d['postal_code']} is not in {d['province']}")
    elif d["country"] == "US":
        if d["province"] not in US_STATES:
            raise InvalidIdentifier("address: state must be a US state code")
        if not re.fullmatch(r"\d{5}(-\d{4})?", d["postal_code"]):
            raise InvalidIdentifier("address: invalid US ZIP code")
    return {k: v for k, v in d.items() if v}


def address_lines(d: dict) -> list[str]:
    """Two display lines (for cheques/statements); payments use the structured fields."""
    first = " ".join(x for x in (f"{d['unit']}-" if d.get("unit") else "", d.get("building", ""), d.get("street", "")) if x).replace("- ", "-")
    return [first, " ".join(x for x in (d.get("city"), d.get("province"), d.get("postal_code"), d.get("country")) if x)]
