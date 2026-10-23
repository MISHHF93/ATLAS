"""Shared XML helpers: safe parsing (no DTDs/entities), namespace-agnostic access, builder, validation."""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

XSD_DIR = Path(__file__).resolve().parent / "xsd"
MESSAGES = {"pain.001.001.09", "pain.002.001.10", "camt.053.001.08", "camt.054.001.08"}
NS_RE = re.compile(r"urn:iso:std:iso:20022:tech:xsd:([a-z]{4}\.\d{3}\.\d{3}\.\d{2})")
MAX_BYTES = 50 * 1024 * 1024


class XMLError(ValueError):
    ...


def safe_parse(xml: str | bytes) -> ET.Element:
    """Parse untrusted XML: size cap, DTDs/entity declarations rejected (XXE / billion-laughs), no network."""
    b = xml.encode("utf-8") if isinstance(xml, str) else bytes(xml)
    if len(b) > MAX_BYTES:
        raise XMLError("XML document too large")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", b, re.I):
        raise XMLError("XML with DOCTYPE/ENTITY declarations is refused")
    try:
        return ET.fromstring(b)
    except ET.ParseError as e:
        raise XMLError(f"malformed XML: {e}") from e


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def message_id(root: ET.Element) -> str:
    """'pain.001.001.09' etc. from the Document namespace."""
    m = NS_RE.fullmatch(root.tag[1:].split("}")[0]) if root.tag.startswith("{") else None
    if not m or local(root.tag) != "Document":
        raise XMLError("not an ISO 20022 Document (missing urn:iso:std:iso:20022:tech:xsd namespace)")
    return m.group(1)


def kids(e, name):
    return [c for c in list(e) if local(c.tag) == name] if e is not None else []


def kid(e, *path):
    """Child by local-name path (first match), or None."""
    for p in path:
        if e is None:
            return None
        e = next((c for c in list(e) if local(c.tag) == p), None)
    return e


def text(e, *path, default=None):
    x = kid(e, *path)
    return x.text.strip() if x is not None and x.text is not None else default


def dec(s, what="amount") -> Decimal:
    try:
        d = Decimal(str(s))
    except (InvalidOperation, TypeError):
        raise XMLError(f"invalid {what}: {s!r}") from None
    if not d.is_finite():
        raise XMLError(f"invalid {what}")
    return d


def amt_str(x) -> str:
    d = Decimal(str(x)).quantize(Decimal("0.01"))
    if d < 0:
        raise XMLError("ISO 20022 amounts are unsigned; use CdtDbtInd")
    return f"{d:.2f}"


def iso_dt(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).replace(microsecond=0).isoformat()


class B:
    """Tiny ordered builder: B(ns).el(parent, 'Tag', text, Ccy='CAD')."""

    def __init__(self, msg: str):
        self.ns = f"urn:iso:std:iso:20022:tech:xsd:{msg}"
        ET.register_namespace("", self.ns)

    def root(self):
        return ET.Element(f"{{{self.ns}}}Document")

    def el(self, parent, tag, value=None, **attrs):
        e = ET.SubElement(parent, f"{{{self.ns}}}{tag}", {k: str(v) for k, v in attrs.items()})
        if value is not None:
            e.text = str(value)
        return e

    @staticmethod
    def dump(root) -> str:
        ET.indent(root)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def xsd_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("xmlschema") is not None


@lru_cache(maxsize=8)
def _schema(msg: str):
    import xmlschema
    return xmlschema.XMLSchema(str(XSD_DIR / f"{msg}.xsd"))


def validate(xml: str | bytes, expect: str | None = None) -> dict:
    """Structural validation (always) + XSD validation when xmlschema is installed. Returns
    {"message": ..., "xsd": "valid" | "unavailable", "errors": []}; raises XMLError on failure."""
    root = safe_parse(xml)
    msg = message_id(root)
    if msg not in MESSAGES:
        raise XMLError(f"unsupported message {msg}; supported: {sorted(MESSAGES)}")
    if expect and not msg.startswith(expect):
        raise XMLError(f"expected {expect}, got {msg}")
    errs = structural_errors(root, msg)
    if errs:
        raise XMLError("structural validation failed: " + "; ".join(errs[:10]))
    xsd = "unavailable"
    if xsd_available():
        sch = _schema(msg)
        e = [str(x.reason or x)[:200] + f" @ {x.path}" for x in sch.iter_errors(xml if isinstance(xml, str) else xml.decode())]
        if e:
            raise XMLError("XSD validation failed: " + "; ".join(e[:5]))
        xsd = "valid"
    return {"message": msg, "xsd": xsd, "errors": []}


def structural_errors(root, msg) -> list[str]:
    errs: list[str] = []
    body = list(root)[0] if len(root) else None
    want = {"pain.001": "CstmrCdtTrfInitn", "pain.002": "CstmrPmtStsRpt", "camt.053": "BkToCstmrStmt",
            "camt.054": "BkToCstmrDbtCdtNtfctn"}[msg[:8]]
    if body is None or local(body.tag) != want:
        return [f"root element must be {want}"]
    gh = kid(body, "GrpHdr")
    for f in ("MsgId", "CreDtTm"):
        if not text(gh, f):
            errs.append(f"GrpHdr/{f} missing")
    if text(gh, "MsgId") and len(text(gh, "MsgId")) > 35:
        errs.append("GrpHdr/MsgId > 35 chars")
    if msg.startswith("pain.001"):
        pis = kids(body, "PmtInf")
        txs = [t for p in pis for t in kids(p, "CdtTrfTxInf")]
        if not pis or not txs:
            errs.append("at least one PmtInf with CdtTrfTxInf required")
        if text(gh, "NbOfTxs") != str(len(txs)):
            errs.append(f"GrpHdr/NbOfTxs {text(gh, 'NbOfTxs')} != {len(txs)} transactions")
        tot = sum((dec(text(t, "Amt", "InstdAmt") or "x") for t in txs), Decimal(0)) if txs else Decimal(0)
        if text(gh, "CtrlSum") is not None and dec(text(gh, "CtrlSum")) != tot:
            errs.append(f"GrpHdr/CtrlSum {text(gh, 'CtrlSum')} != {tot}")
        e2e = [text(t, "PmtId", "EndToEndId") for t in txs]
        if len(set(e2e)) != len(e2e) or not all(e2e):
            errs.append("EndToEndId must be present and unique")
        for t in txs:
            a = kid(t, "Amt", "InstdAmt")
            if a is None or not a.get("Ccy") or dec(a.text) <= 0:
                errs.append("InstdAmt with Ccy and positive value required")
    if msg.startswith("pain.002") and kid(body, "OrgnlGrpInfAndSts") is None:
        errs.append("OrgnlGrpInfAndSts required")
    if msg.startswith("camt"):
        rep = "Stmt" if msg.startswith("camt.053") else "Ntfctn"
        if not kids(body, rep):
            errs.append(f"at least one {rep} required")
        for s in kids(body, rep):
            if kid(s, "Acct", "Id") is None:
                errs.append(f"{rep}/Acct/Id missing")
            for n in kids(s, "Ntry"):
                if text(n, "CdtDbtInd") not in ("CRDT", "DBIT"):
                    errs.append("Ntry/CdtDbtInd must be CRDT or DBIT")
    return errs
