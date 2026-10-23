"""CPA Standard 005 (Payments Canada AFT file, 1464-byte records), SIMULATION writer + reader.

Layout used (the common bank implementation of Standard 005): a header 'A', logical records 'C' (credits) or 'D'
(debits) each holding up to six 240-byte payment segments after a 24-byte record prefix, and a trailer 'Z' with
control totals. Each bank publishes its own variant (originator ID, data centre, transaction codes, filler use);
treat this as a format reference and test file only. Nothing here transmits anything."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from decimal import Decimal

from atlas.ledgers.banking.bankids import InvalidIdentifier, validate_ca_account

REC = 1464
SEG = 240
PREFIX = 24
# segment fields: (name, width)
SEGMENT = (("txn_type", 3), ("amount", 10), ("due_date", 6), ("payee_institution", 9), ("payee_account", 12), ("item_trace", 22),
           ("stored_txn_type", 3), ("originator_short_name", 15), ("payee_name", 30), ("originator_long_name", 30),
           ("originator_user_id", 10), ("cross_reference", 19), ("return_institution", 9), ("return_account", 12),
           ("sundry", 15), ("filler", 22), ("settlement_code", 2), ("invalid_data", 11))
assert sum(w for _, w in SEGMENT) == SEG and PREFIX + 6 * SEG == REC


class CPA005Error(ValueError):
    pass


def julian(d: dt.date) -> str:
    """0YYDDD (CPA date)."""
    return f"0{d:%y}{d.timetuple().tm_yday:03d}"


def from_julian(s: str) -> dt.date:
    if not re.fullmatch(r"0\d{5}", s):
        raise CPA005Error(f"bad CPA date {s!r}")
    return dt.date(2000 + int(s[1:3]), 1, 1) + dt.timedelta(days=int(s[3:]) - 1)


def _txt(s, n: int) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9 &'(),./-]", " ", s)
    return s[:n].ljust(n)


def _num(v, n: int) -> str:
    s = str(int(v))
    if len(s) > n or int(v) < 0:
        raise CPA005Error(f"value {v} does not fit {n} digits")
    return s.zfill(n)


def _inst(institution: str, transit: str) -> str:
    return "0" + _num(institution, 3) + _num(transit, 5)


def build(*, originator_id: str, file_number: int, created: dt.date, data_centre: str, currency: str, items: list[dict],
          short_name: str, long_name: str, return_account: dict, kind: str = "C", txn_type: str = "450") -> str:
    """items: amount (Decimal CAD), due_date (date), institution, transit, account, payee_name, cross_reference."""
    if kind not in ("C", "D"):
        raise CPA005Error("kind C (credits) or D (debits)")
    if not re.fullmatch(r"[A-Z0-9]{10}", originator_id):
        raise CPA005Error("originator ID: 10 alphanumerics assigned by the bank")
    if currency not in ("CAD", "USD"):
        raise CPA005Error("currency CAD or USD")
    if not 1 <= int(file_number) <= 9999:
        raise CPA005Error("file creation number 1-9999 (must not repeat)")
    if not items:
        raise CPA005Error("no items")
    validate_ca_account(return_account["institution"], return_account["transit"], return_account["account"])
    hdr = lambda t, n: t + _num(n, 9) + originator_id + _num(file_number, 4)   # noqa: E731
    recs = [(hdr("A", 1) + julian(created) + _num(data_centre, 5) + " " * 20 + currency).ljust(REC)]
    segs, total = [], 0
    for it in items:
        try:
            validate_ca_account(it["institution"], it["transit"], it["account"])
        except InvalidIdentifier as e:
            raise CPA005Error(f"item {it.get('cross_reference')}: {e}") from e
        cents = int((Decimal(str(it["amount"])) * 100).to_integral_value())
        if cents <= 0:
            raise CPA005Error("amounts must be positive")
        total += cents
        vals = {"txn_type": _num(txn_type, 3), "amount": _num(cents, 10), "due_date": julian(it["due_date"]),
                "payee_institution": _inst(it["institution"], it["transit"]), "payee_account": str(it["account"]).ljust(12),
                "item_trace": "0" * 22, "stored_txn_type": "000", "originator_short_name": _txt(short_name, 15),
                "payee_name": _txt(it["payee_name"], 30), "originator_long_name": _txt(long_name, 30),
                "originator_user_id": originator_id, "cross_reference": _txt(it.get("cross_reference", ""), 19),
                "return_institution": _inst(return_account["institution"], return_account["transit"]),
                "return_account": str(return_account["account"]).ljust(12), "sundry": " " * 15, "filler": " " * 22,
                "settlement_code": "  ", "invalid_data": "0" * 11}
        seg = "".join(vals[k].ljust(w)[:w] for k, w in SEGMENT)
        assert len(seg) == SEG
        segs.append(seg)
    for i in range(0, len(segs), 6):
        recs.append((hdr(kind, len(recs) + 1) + "".join(segs[i:i + 6])).ljust(REC))
    debit = (total, len(segs)) if kind == "D" else (0, 0)
    credit = (total, len(segs)) if kind == "C" else (0, 0)
    recs.append((hdr("Z", len(recs) + 1) + _num(debit[0], 14) + _num(debit[1], 8) + _num(credit[0], 14) + _num(credit[1], 8)
                 + "0" * 44).ljust(REC))
    return "\r\n".join(recs) + "\r\n"


def parse(text: str) -> dict:
    """Read and check a Standard 005 file: record lengths, sequence, header/trailer IDs, control totals."""
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln]
    errors, items = [], []
    if not lines:
        raise CPA005Error("empty file")
    for i, ln in enumerate(lines, 1):
        if len(ln) != REC:
            raise CPA005Error(f"record {i}: length {len(ln)} (expected {REC})")
        if ln[1:10] != f"{i:09d}":
            errors.append(f"record {i}: record count field {ln[1:10]!r}")
    a, z = lines[0], lines[-1]
    if a[0] != "A" or z[0] != "Z":
        raise CPA005Error("file must start with an A header and end with a Z trailer")
    orig, fcn = a[10:20], a[20:24]
    head = {"originator_id": orig, "file_number": int(fcn), "created": from_julian(a[24:30]).isoformat(), "data_centre": a[30:35],
            "currency": a[55:58]}
    kinds = set()
    for ln in lines[1:-1]:
        if ln[0] not in "CD":
            errors.append(f"unexpected record type {ln[0]!r}")
            continue
        if ln[10:20] != orig or ln[20:24] != fcn:
            errors.append(f"record {ln[1:10]}: originator/file number differs from header")
        kinds.add(ln[0])
        for k in range(6):
            seg = ln[PREFIX + k * SEG: PREFIX + (k + 1) * SEG]
            if not seg.strip():
                continue
            pos, f = 0, {}
            for name, w in SEGMENT:
                f[name] = seg[pos:pos + w]
                pos += w
            items.append({"kind": ln[0], "txn_type": f["txn_type"], "amount": Decimal(int(f["amount"])) / 100,
                          "due_date": from_julian(f["due_date"]).isoformat(), "institution": f["payee_institution"][1:4],
                          "transit": f["payee_institution"][4:9], "account": f["payee_account"].strip(), "payee_name": f["payee_name"].strip(),
                          "cross_reference": f["cross_reference"].strip(), "originator_short_name": f["originator_short_name"].strip()})
    cents = lambda k: sum(int(i["amount"] * 100) for i in items if i["kind"] == k)   # noqa: E731
    count = lambda k: sum(1 for i in items if i["kind"] == k)                          # noqa: E731
    tr = {"debit_total": int(z[24:38]), "debit_count": int(z[38:46]), "credit_total": int(z[46:60]), "credit_count": int(z[60:68])}
    if (tr["debit_total"], tr["debit_count"]) != (cents("D"), count("D")):
        errors.append("trailer debit totals do not match the items")
    if (tr["credit_total"], tr["credit_count"]) != (cents("C"), count("C")):
        errors.append("trailer credit totals do not match the items")
    if z[10:20] != orig or z[20:24] != fcn:
        errors.append("trailer originator/file number differs from header")
    return {"header": head, "items": items, "trailer": tr, "errors": errors, "valid": not errors}


__all__ = ["build", "parse", "julian", "from_julian", "CPA005Error", "REC"]
