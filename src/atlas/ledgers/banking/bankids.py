"""Account-identifier validators (offline, pure functions).

Canada: electronic Direct Payment Routing Number (DPRN) "0YYYXXXXX" = leading 0 + 3-digit institution + 5-digit
branch transit; MICR/paper form "XXXXX-YYY" (transit first). Payments Canada Rule F8 and the Financial Institution
numeric list (https://www.payments.ca/sites/default/files/f8eng.pdf). Account numbers are institution-specific;
7-12 digits is the generic envelope (some institutions publish exact lengths, see ACCOUNT_LENGTHS).
IBAN: ISO 13616 (mod-97 = 1, per-country length). BIC: ISO 9362 (4 letters institution, 2 letters country,
2 alphanumeric location, optional 3 alphanumeric branch). ABA: 9 digits, weights 3-7-1 checksum, first two digits
in the Federal Reserve ranges. Also a PAN (card number) detector so card data is refused at intake (we are out of
PCI DSS scope and stay that way)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Subset of the Payments Canada Financial Institution numeric list (institution number -> name). Extend from the
# published list (https://www.payments.ca/sites/default/files/2025-06-27-Banks_Numeric_List.pdf) as partners require.
INSTITUTIONS = {
    "001": "Bank of Montreal", "002": "The Bank of Nova Scotia", "003": "Royal Bank of Canada",
    "004": "The Toronto-Dominion Bank", "006": "National Bank of Canada", "010": "Canadian Imperial Bank of Commerce",
    "016": "HSBC Bank Canada (now RBC)", "030": "Canadian Western Bank", "039": "Laurentian Bank of Canada",
    "177": "Bank of Canada", "219": "ATB Financial", "260": "Citibank Canada", "309": "Citizens Bank of Canada",
    "326": "President's Choice Financial", "338": "Canadian Tire Bank", "540": "Manulife Bank of Canada",
    "614": "Tangerine Bank", "621": "Peoples Trust Company", "623": "Equitable Bank", "815": "Fédération des caisses Desjardins du Québec",
    "828": "Central 1 Credit Union", "837": "Meridian Credit Union", "839": "Credit Union Heritage (Nova Scotia)",
    "865": "Caisse populaire acadienne", "889": "Credit Union Central of Saskatchewan", "899": "Credit Union Central Alberta",
}
ACCOUNT_LENGTHS = {"001": (7, 7), "003": (7, 7), "815": (7, 7)}  # (min, max) where an institution publishes it

IBAN_LENGTHS = {  # ISO 13616 registry (subset: SEPA + common corridors)
    "AD": 24, "AE": 23, "AT": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GI": 23, "GR": 27, "HR": 21, "HU": 28, "IE": 22,
    "IL": 23, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15,
    "PL": 28, "PT": 25, "QA": 29, "RO": 24, "SA": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26, "UA": 29,
    "VA": 22, "XK": 20,
}
ISO_COUNTRIES = set(IBAN_LENGTHS) | {"CA", "US", "MX", "JP", "CN", "HK", "SG", "AU", "NZ", "IN", "KR", "ZA", "KY", "BM", "BS"}


class InvalidIdentifier(ValueError):
    ...


@dataclass(frozen=True)
class CanadianAccount:
    institution: str
    transit: str
    account: str

    @property
    def dprn(self) -> str:
        return "0" + self.institution + self.transit

    @property
    def micr(self) -> str:
        return f"{self.transit}-{self.institution}"

    @property
    def institution_name(self) -> str | None:
        return INSTITUTIONS.get(self.institution)


def _digits(x, name, n=None, lo=None, hi=None) -> str:
    s = re.sub(r"[\s-]", "", str(x or ""))
    if not s.isdigit():
        raise InvalidIdentifier(f"{name} must be digits")
    if n is not None and len(s) != n:
        raise InvalidIdentifier(f"{name} must be {n} digits")
    if lo is not None and not lo <= len(s) <= hi:
        raise InvalidIdentifier(f"{name} must be {lo}-{hi} digits")
    return s


def validate_institution(x, known_only: bool = False) -> str:
    s = _digits(x, "institution number", 3)
    if known_only and s not in INSTITUTIONS:
        raise InvalidIdentifier(f"institution {s} is not on the configured Payments Canada list")
    return s


def validate_transit(x) -> str:
    return _digits(x, "transit (branch) number", 5)


def validate_ca_account(institution, transit, account, known_only: bool = False) -> CanadianAccount:
    inst = validate_institution(institution, known_only)
    tr = validate_transit(transit)
    acct = _digits(account, "account number", lo=5, hi=12)
    lo, hi = ACCOUNT_LENGTHS.get(inst, (7, 12))
    if not lo <= len(acct) <= hi:
        raise InvalidIdentifier(f"account number for institution {inst} must be {lo}-{hi} digits" if lo != hi
                                else f"account number for institution {inst} must be {lo} digits")
    return CanadianAccount(inst, tr, acct)


def parse_dprn(x) -> tuple[str, str]:
    s = _digits(x, "routing number (DPRN)", 9)
    if s[0] != "0":
        raise InvalidIdentifier("Canadian electronic routing number starts with 0 (0YYYXXXXX)")
    return s[1:4], s[4:]


def micr_to_dprn(micr: str) -> str:
    m = re.fullmatch(r"\s*(\d{5})-?(\d{3})\s*", str(micr))
    if not m:
        raise InvalidIdentifier("MICR routing must be XXXXX-YYY (transit-institution)")
    return "0" + m.group(2) + m.group(1)


def dprn_to_micr(dprn: str) -> str:
    inst, tr = parse_dprn(dprn)
    return f"{tr}-{inst}"


def iban_checksum_ok(iban: str) -> bool:
    s = iban[4:] + iban[:4]
    n = "".join(str(int(ch, 36)) for ch in s)
    r = 0
    for i in range(0, len(n), 9):
        r = int(str(r) + n[i:i + 9]) % 97
    return r == 1


def validate_iban(x) -> str:
    s = re.sub(r"\s", "", str(x or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", s):
        raise InvalidIdentifier("IBAN format: 2 letters + 2 check digits + up to 30 alphanumerics")
    cc = s[:2]
    if cc not in IBAN_LENGTHS:
        raise InvalidIdentifier(f"country {cc} does not use IBAN (or is not configured)")
    if len(s) != IBAN_LENGTHS[cc]:
        raise InvalidIdentifier(f"IBAN for {cc} must be {IBAN_LENGTHS[cc]} characters")
    if not iban_checksum_ok(s):
        raise InvalidIdentifier("IBAN check digits do not validate (mod-97)")
    return s


def format_iban(iban: str) -> str:
    s = validate_iban(iban)
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def validate_bic(x) -> str:
    s = re.sub(r"\s", "", str(x or "")).upper()
    if not re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", s):
        raise InvalidIdentifier("BIC must be 8 or 11 characters: AAAA BB CC (DDD)")
    if s[4:6] not in ISO_COUNTRIES:
        raise InvalidIdentifier(f"BIC country code {s[4:6]} not recognised")
    if s[7] == "0":
        raise InvalidIdentifier("BIC location code with second character '0' is a test BIC")
    return s


def validate_aba(x) -> str:
    s = _digits(x, "ABA routing number", 9)
    p = int(s[:2])
    if not (0 <= p <= 12 or 21 <= p <= 32 or 61 <= p <= 72 or p == 80):
        raise InvalidIdentifier("ABA routing prefix outside Federal Reserve ranges")
    w = (3, 7, 1) * 3
    if sum(int(c) * k for c, k in zip(s, w)) % 10:
        raise InvalidIdentifier("ABA routing checksum fails")
    return s


def luhn_ok(s: str) -> bool:
    tot, alt = 0, False
    for ch in reversed(s):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        tot += d
        alt = not alt
    return tot % 10 == 0


_PAN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def contains_pan(text: str) -> bool:
    """True if the text contains something that looks like a payment card number (13-19 digits, Luhn-valid,
    issuer prefix 2-6). Used to refuse card data at intake."""
    for m in _PAN.finditer(str(text or "")):
        s = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(s) <= 19 and s[0] in "23456" and luhn_ok(s):
            return True
    return False


def validate_any(kind: str, value, **kw):
    """Dispatcher used by the API: kind in ca_account | iban | bic | aba | dprn | micr."""
    if kind == "ca_account":
        a = validate_ca_account(kw.get("institution"), kw.get("transit"), value)
        return {"valid": True, "dprn": a.dprn, "micr": a.micr, "institution_name": a.institution_name}
    if kind == "iban":
        return {"valid": True, "iban": validate_iban(value), "formatted": format_iban(value)}
    if kind == "bic":
        return {"valid": True, "bic": validate_bic(value)}
    if kind == "aba":
        return {"valid": True, "aba": validate_aba(value)}
    if kind == "dprn":
        i, t = parse_dprn(value)
        return {"valid": True, "institution": i, "transit": t, "micr": f"{t}-{i}", "institution_name": INSTITUTIONS.get(i)}
    if kind == "micr":
        d = micr_to_dprn(value)
        return {"valid": True, "dprn": d}
    raise InvalidIdentifier(f"unknown identifier kind {kind}")
