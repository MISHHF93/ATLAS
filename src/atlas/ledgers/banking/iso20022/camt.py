"""camt.053 (BankToCustomerStatement) and camt.054 (BankToCustomerDebitCreditNotification): parse into normalised,
signed entries for reconciliation; generate them for the offline custodian/bank simulation."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from atlas.ledgers.banking.iso20022.common import B, XMLError, amt_str, dec, iso_dt, kid, kids, local, message_id, safe_parse, text

STATUS_BOOKED = "BOOK"


def _acct_id(acct) -> str:
    return text(acct, "Id", "IBAN") or text(acct, "Id", "Othr", "Id") or ""


def _entry(n) -> dict:
    sign = 1 if text(n, "CdtDbtInd") == "CRDT" else -1
    a = kid(n, "Amt")
    if a is None:
        raise XMLError("Ntry/Amt missing")
    tx = kid(n, "NtryDtls", "TxDtls")
    refs = kid(tx, "Refs")
    ustrd = [x.text.strip() for x in (kids(kid(tx, "RmtInf"), "Ustrd") if tx is not None else []) if x.text]
    status = text(n, "Sts", "Cd") or text(n, "Sts")          # v08 choice (Cd/Prtry); older versions plain text
    dom = kid(n, "BkTxCd", "Domn")
    return {
        "amount": sign * dec(a.text), "currency": a.get("Ccy"), "cdt_dbt": text(n, "CdtDbtInd"),
        "status": status, "reversal": text(n, "RvslInd") == "true",
        "booking_date": text(n, "BookgDt", "Dt") or (text(n, "BookgDt", "DtTm") or "")[:10] or None,
        "value_date": text(n, "ValDt", "Dt") or (text(n, "ValDt", "DtTm") or "")[:10] or None,
        "entry_ref": text(n, "NtryRef"), "servicer_ref": text(n, "AcctSvcrRef"),
        "end_to_end_id": text(refs, "EndToEndId"), "instr_id": text(refs, "InstrId"),
        "remittance": " ".join(ustrd) or text(n, "AddtlNtryInf"),
        "counterparty": (text(tx, "RltdPties", "Dbtr", "Pty", "Nm") or text(tx, "RltdPties", "Dbtr", "Nm")) if sign > 0
        else (text(tx, "RltdPties", "Cdtr", "Pty", "Nm") or text(tx, "RltdPties", "Cdtr", "Nm")),
        "counterparty_country": text(tx, "RltdPties", "Dbtr" if sign > 0 else "Cdtr", "Pty", "PstlAdr", "Ctry")
        or text(tx, "RltdPties", "Dbtr" if sign > 0 else "Cdtr", "PstlAdr", "Ctry"),
        "counterparty_address": " ".join(x.text or "" for x in kids(kid(tx, "RltdPties", "Dbtr" if sign > 0 else "Cdtr", "Pty", "PstlAdr"), "AdrLine")) or None,
        "counterparty_account": text(tx, "RltdPties", "DbtrAcct" if sign > 0 else "CdtrAcct", "Id", "Othr", "Id")
        or text(tx, "RltdPties", "DbtrAcct" if sign > 0 else "CdtrAcct", "Id", "IBAN"),
        "booked_at": text(n, "BookgDt", "DtTm"),
        "bank_tx_code": "/".join(x for x in (text(dom, "Cd"), text(dom, "Fmly", "Cd"), text(dom, "Fmly", "SubFmlyCd")) if x) or text(n, "BkTxCd", "Prtry", "Cd"),
    }


def _balance(stmt, *codes):
    for b in kids(stmt, "Bal"):
        if text(b, "Tp", "CdOrPrtry", "Cd") in codes:
            sign = 1 if text(b, "CdtDbtInd") == "CRDT" else -1
            return {"type": text(b, "Tp", "CdOrPrtry", "Cd"), "amount": sign * dec(kid(b, "Amt").text),
                    "currency": kid(b, "Amt").get("Ccy"), "date": text(b, "Dt", "Dt") or (text(b, "Dt", "DtTm") or "")[:10]}
    return None


def parse(xml: str | bytes) -> dict:
    """Parse camt.053 or camt.054 (any 001.0x version; namespace-agnostic) into
    {"message", "msg_id", "created", "reports": [{"id", "account", "currency", "opening", "closing", "entries": [...],
     "check": {...}}]}. For camt.053, opening + booked entries must equal closing (reported in check)."""
    root = safe_parse(xml)
    msg = message_id(root)
    if not msg.startswith(("camt.053", "camt.054", "camt.052")):
        raise XMLError(f"expected camt.053/054, got {msg}")
    body = list(root)[0]
    rep_tag = {"BkToCstmrStmt": "Stmt", "BkToCstmrDbtCdtNtfctn": "Ntfctn", "BkToCstmrAcctRpt": "Rpt"}.get(local(body.tag))
    if not rep_tag:
        raise XMLError(f"unexpected camt body {local(body.tag)}")
    out = {"message": msg, "msg_id": text(body, "GrpHdr", "MsgId"), "created": text(body, "GrpHdr", "CreDtTm"), "reports": []}
    for s in kids(body, rep_tag):
        acct = kid(s, "Acct")
        entries = [_entry(n) for n in kids(s, "Ntry")]
        r = {"id": text(s, "Id"), "account": _acct_id(acct), "currency": text(acct, "Ccy"),
             "servicer": text(acct, "Svcr", "FinInstnId", "BICFI") or text(acct, "Svcr", "FinInstnId", "ClrSysMmbId", "MmbId"),
             "from": text(s, "FrToDt", "FrDtTm"), "to": text(s, "FrToDt", "ToDtTm"),
             "opening": _balance(s, "OPBD", "PRCD"), "closing": _balance(s, "CLBD"), "entries": entries}
        if r["opening"] and r["closing"]:
            booked = sum((e["amount"] for e in entries if e["status"] in (STATUS_BOOKED, None)), Decimal(0))
            diff = r["opening"]["amount"] + booked - r["closing"]["amount"]
            r["check"] = {"opening_plus_booked_equals_closing": diff == 0, "difference": str(diff)}
        out["reports"].append(r)
    return out


# --------------------------------------------------------------------------------------------- generation (SIM)
def _bal(b: B, s, code, amount: Decimal, ccy, day: str):
    bal = b.el(s, "Bal")
    b.el(b.el(b.el(bal, "Tp"), "CdOrPrtry"), "Cd", code)
    b.el(bal, "Amt", amt_str(abs(amount)), Ccy=ccy)
    b.el(bal, "CdtDbtInd", "CRDT" if amount >= 0 else "DBIT")
    b.el(b.el(bal, "Dt"), "Dt", day)


def _ntry(b: B, s, e: dict, ccy: str):
    amount = Decimal(str(e["amount"]))
    n = b.el(s, "Ntry")
    if e.get("entry_ref"):
        b.el(n, "NtryRef", str(e["entry_ref"])[:35])
    b.el(n, "Amt", amt_str(abs(amount)), Ccy=e.get("currency", ccy))
    b.el(n, "CdtDbtInd", "CRDT" if amount >= 0 else "DBIT")
    b.el(b.el(n, "Sts"), "Cd", e.get("status", STATUS_BOOKED))
    if e.get("booking_ts"):
        b.el(b.el(n, "BookgDt"), "DtTm", iso_dt(e["booking_ts"]))
    else:
        b.el(b.el(n, "BookgDt"), "Dt", e["booking_date"])
    b.el(b.el(n, "ValDt"), "Dt", e.get("value_date") or e["booking_date"])
    if e.get("servicer_ref"):
        b.el(n, "AcctSvcrRef", str(e["servicer_ref"])[:35])
    dom = b.el(b.el(n, "BkTxCd"), "Domn")
    b.el(dom, "Cd", "PMNT")
    fm = b.el(dom, "Fmly")
    b.el(fm, "Cd", "RCDT" if amount >= 0 else "ICDT")
    b.el(fm, "SubFmlyCd", e.get("sub_family", "DMCT"))      # DMCT domestic credit transfer, BOOK internal book transfer
    if e.get("end_to_end_id") or e.get("remittance") or e.get("counterparty"):
        tx = b.el(b.el(n, "NtryDtls"), "TxDtls")
        if e.get("end_to_end_id"):
            b.el(b.el(tx, "Refs"), "EndToEndId", str(e["end_to_end_id"])[:35])
        if e.get("counterparty"):
            rp = b.el(tx, "RltdPties")
            pty = b.el(b.el(rp, "Dbtr" if amount >= 0 else "Cdtr"), "Pty")
            b.el(pty, "Nm", str(e["counterparty"])[:140])
            if e.get("counterparty_country") or e.get("counterparty_address"):
                pa = b.el(pty, "PstlAdr")
                if e.get("counterparty_country"):
                    b.el(pa, "Ctry", e["counterparty_country"])
                if e.get("counterparty_address"):
                    b.el(pa, "AdrLine", str(e["counterparty_address"])[:70])
            if e.get("counterparty_account"):
                b.el(b.el(b.el(b.el(rp, "DbtrAcct" if amount >= 0 else "CdtrAcct"), "Id"), "Othr"), "Id", str(e["counterparty_account"])[:34])
        if e.get("remittance"):
            b.el(b.el(tx, "RmtInf"), "Ustrd", str(e["remittance"])[:140])


def _acct(b: B, s, account: str, ccy: str, servicer_bic: str | None):
    a = b.el(s, "Acct")
    b.el(b.el(b.el(a, "Id"), "Othr"), "Id", account[:34])
    b.el(a, "Ccy", ccy)
    if servicer_bic:
        b.el(b.el(b.el(a, "Svcr"), "FinInstnId"), "BICFI", servicer_bic)


def build_camt053(msg_id: str, created_ts: float, statements: list[dict], servicer_bic: str | None = None) -> str:
    """statements: [{"id", "account", "currency", "opening": Decimal, "from": date, "to": date, "entries":
    [{"amount" (signed), "booking_date", "value_date", "servicer_ref", "end_to_end_id", "remittance", "counterparty"}]}].
    Closing balance = opening + entries."""
    b = B("camt.053.001.08")
    root = b.root()
    body = b.el(root, "BkToCstmrStmt")
    gh = b.el(body, "GrpHdr")
    b.el(gh, "MsgId", msg_id[:35])
    b.el(gh, "CreDtTm", iso_dt(created_ts))
    for st in statements:
        s = b.el(body, "Stmt")
        b.el(s, "Id", st["id"][:35])
        b.el(s, "CreDtTm", iso_dt(created_ts))
        fr = b.el(s, "FrToDt")
        b.el(fr, "FrDtTm", f"{st['from']}T00:00:00")
        b.el(fr, "ToDtTm", f"{st['to']}T23:59:59")
        _acct(b, s, st["account"], st["currency"], servicer_bic)
        opening = Decimal(str(st["opening"]))
        closing = opening + sum((Decimal(str(e["amount"])) for e in st["entries"]), Decimal(0))
        _bal(b, s, "OPBD", opening, st["currency"], str(st["from"]))
        _bal(b, s, "CLBD", closing, st["currency"], str(st["to"]))
        for e in st["entries"]:
            _ntry(b, s, e, st["currency"])
    return B.dump(root)


def build_camt054(msg_id: str, created_ts: float, account: str, currency: str, entries: list[dict],
                  servicer_bic: str | None = None) -> str:
    b = B("camt.054.001.08")
    root = b.root()
    body = b.el(root, "BkToCstmrDbtCdtNtfctn")
    gh = b.el(body, "GrpHdr")
    b.el(gh, "MsgId", msg_id[:35])
    b.el(gh, "CreDtTm", iso_dt(created_ts))
    n = b.el(body, "Ntfctn")
    b.el(n, "Id", (msg_id + "-N")[:35])
    b.el(n, "CreDtTm", iso_dt(created_ts))
    _acct(b, n, account, currency, servicer_bic)
    for e in entries:
        _ntry(b, n, e, currency)
    return B.dump(root)


def today(ts: float) -> str:
    return dt.date.fromtimestamp(ts).isoformat()
