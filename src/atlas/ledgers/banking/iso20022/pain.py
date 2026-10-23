"""pain.001.001.09 (CustomerCreditTransferInitiation) generation and pain.002.001.10 (CustomerPaymentStatusReport)
parsing. Canadian agents are identified by clearing-system member id: ClrSysId/Cd = CACPA (Canadian Payments
Association) + MmbId = DPRN 0YYYXXXXX. Foreign agents by BICFI. EndToEndId carries our payout release reference so
status reports and statement entries can be matched back without guessing."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from atlas.ledgers.banking.bankids import InvalidIdentifier, validate_bic, validate_ca_account, validate_iban
from atlas.ledgers.banking.iso20022.common import B, XMLError, amt_str, iso_dt, kid, kids, message_id, safe_parse, text

TX_STATUS = {"ACTC": "accepted_technical", "ACCP": "accepted_customer_profile", "ACSP": "accepted_settlement_in_process",
             "ACSC": "accepted_settlement_completed", "ACWC": "accepted_with_change", "PDNG": "pending", "RJCT": "rejected",
             "PART": "partially_accepted", "RCVD": "received"}
FINAL_OK = {"ACSC"}
REJECTED = {"RJCT"}
REASONS = {"AC01": "incorrect account number", "AC04": "closed account", "AC06": "blocked account",
           "AG01": "transaction forbidden", "AM04": "insufficient funds", "BE04": "missing creditor address",
           "MS03": "reason not specified", "RC01": "bank identifier incorrect", "RR03": "missing creditor name or address",
           "FF01": "invalid file format", "DUPL": "duplicate payment", "NARR": "narrative"}


def _agent(b: B, parent, tag: str, party: dict):
    fi = b.el(b.el(parent, tag), "FinInstnId")
    if party.get("bic"):
        b.el(fi, "BICFI", validate_bic(party["bic"]))
    if party.get("institution") and party.get("transit"):
        cm = b.el(fi, "ClrSysMmbId")
        b.el(b.el(cm, "ClrSysId"), "Cd", "CACPA")
        b.el(cm, "MmbId", "0" + party["institution"] + party["transit"])
    if not (party.get("bic") or party.get("transit")):
        raise InvalidIdentifier(f"{tag}: BIC or Canadian institution+transit required")


def _account(b: B, parent, tag: str, party: dict):
    i = b.el(b.el(parent, tag), "Id")
    if party.get("iban"):
        b.el(i, "IBAN", validate_iban(party["iban"]))
    else:
        b.el(b.el(i, "Othr"), "Id", str(party["account"])[:34])


def _postal(b: B, parent, addr: dict | None):
    if not addr:
        return
    pa = b.el(parent, "PstlAdr")
    for k_in, tag in (("street", "StrtNm"), ("building", "BldgNb"), ("postal_code", "PstCd"), ("town", "TwnNm"),
                      ("subdivision", "CtrySubDvsn"), ("country", "Ctry")):
        if addr.get(k_in):
            b.el(pa, tag, str(addr[k_in])[:70 if tag in ("StrtNm", "TwnNm") else 35 if tag != "Ctry" else 2])
    for line in (addr.get("lines") or [])[:7]:
        b.el(pa, "AdrLine", str(line)[:70])


def _check_ca(party: dict):
    if party.get("transit") and not party.get("iban"):
        validate_ca_account(party["institution"], party["transit"], party["account"])


def build_pain001(msg_id: str, created_ts: float, debtor: dict, execution_date, txs: list[dict],
                  initiating_party: str | None = None) -> str:
    """debtor: {"name", "account", "institution", "transit"} or {"name", "iban", "bic"};
    txs: [{"end_to_end_id", "amount", "currency", "creditor": {"name", "account", "institution", "transit" | "iban",
    "bic", "address": {...}}, "remittance", "instr_id"}]. Amounts are positive; one PmtInf per currency."""
    if not txs:
        raise XMLError("no transactions")
    _check_ca(debtor)
    for t in txs:
        _check_ca(t["creditor"])
        if not t["creditor"].get("name"):
            raise XMLError("creditor name required (travel rule)")
    ids = [t["end_to_end_id"] for t in txs]
    if len(set(ids)) != len(ids) or any(len(i) > 35 for i in ids):
        raise XMLError("EndToEndId must be unique and <= 35 chars")
    b = B("pain.001.001.09")
    root = b.root()
    body = b.el(root, "CstmrCdtTrfInitn")
    total = sum((Decimal(str(t["amount"])) for t in txs), Decimal(0))
    gh = b.el(body, "GrpHdr")
    b.el(gh, "MsgId", msg_id[:35])
    b.el(gh, "CreDtTm", iso_dt(created_ts))
    b.el(gh, "NbOfTxs", len(txs))
    b.el(gh, "CtrlSum", amt_str(total))
    b.el(b.el(gh, "InitgPty"), "Nm", (initiating_party or debtor["name"])[:140])
    by_ccy: dict[str, list[dict]] = {}
    for t in txs:
        by_ccy.setdefault(t.get("currency", "CAD"), []).append(t)
    for n, (ccy, group) in enumerate(sorted(by_ccy.items()), 1):
        pi = b.el(body, "PmtInf")
        b.el(pi, "PmtInfId", f"{msg_id[:30]}-{n}")
        b.el(pi, "PmtMtd", "TRF")
        b.el(pi, "BtchBookg", "false")
        b.el(pi, "NbOfTxs", len(group))
        b.el(pi, "CtrlSum", amt_str(sum((Decimal(str(t["amount"])) for t in group), Decimal(0))))
        b.el(b.el(pi, "ReqdExctnDt"), "Dt", str(execution_date))
        dbtr = b.el(pi, "Dbtr")
        b.el(dbtr, "Nm", debtor["name"][:140])
        _postal(b, dbtr, debtor.get("address"))
        _account(b, pi, "DbtrAcct", debtor)
        _agent(b, pi, "DbtrAgt", debtor)
        b.el(pi, "ChrgBr", "SLEV" if debtor.get("iban") else "SHAR")
        for t in group:
            tx = b.el(pi, "CdtTrfTxInf")
            pid = b.el(tx, "PmtId")
            if t.get("instr_id"):
                b.el(pid, "InstrId", str(t["instr_id"])[:35])
            b.el(pid, "EndToEndId", t["end_to_end_id"])
            b.el(b.el(tx, "Amt"), "InstdAmt", amt_str(t["amount"]), Ccy=ccy)
            cr = t["creditor"]
            _agent(b, tx, "CdtrAgt", cr)
            c = b.el(tx, "Cdtr")
            b.el(c, "Nm", cr["name"][:140])
            _postal(b, c, cr.get("address"))
            _account(b, tx, "CdtrAcct", cr)
            if t.get("remittance"):
                b.el(b.el(tx, "RmtInf"), "Ustrd", str(t["remittance"])[:140])
    return B.dump(root)


def parse_pain001(xml) -> dict:
    """Read back a pain.001 (for the simulated bank and for audit display)."""
    root = safe_parse(xml)
    if not message_id(root).startswith("pain.001"):
        raise XMLError("expected pain.001")
    body = list(root)[0]
    txs = []
    for pi in kids(body, "PmtInf"):
        for t in kids(pi, "CdtTrfTxInf"):
            a = kid(t, "Amt", "InstdAmt")
            txs.append({"pmt_inf_id": text(pi, "PmtInfId"), "end_to_end_id": text(t, "PmtId", "EndToEndId"),
                        "instr_id": text(t, "PmtId", "InstrId"), "amount": Decimal(a.text), "currency": a.get("Ccy"),
                        "creditor": text(t, "Cdtr", "Nm"), "creditor_account": text(t, "CdtrAcct", "Id", "Othr", "Id") or text(t, "CdtrAcct", "Id", "IBAN"),
                        "creditor_agent": text(t, "CdtrAgt", "FinInstnId", "ClrSysMmbId", "MmbId") or text(t, "CdtrAgt", "FinInstnId", "BICFI"),
                        "execution_date": text(pi, "ReqdExctnDt", "Dt") or text(pi, "ReqdExctnDt")})
    gh = kid(body, "GrpHdr")
    return {"msg_id": text(gh, "MsgId"), "created": text(gh, "CreDtTm"), "nb_of_txs": int(text(gh, "NbOfTxs")),
            "ctrl_sum": text(gh, "CtrlSum"), "debtor": text(kids(body, "PmtInf")[0], "Dbtr", "Nm"), "txs": txs}


def parse_pain002(xml) -> dict:
    """{"msg_id", "orig_msg_id", "orig_msg_type", "group_status", "group_reasons", "txs": [{"end_to_end_id", "status",
    "status_text", "reason", "reason_text", "info"}]}. A group-level RJCT with no tx detail rejects every tx."""
    root = safe_parse(xml)
    if not message_id(root).startswith("pain.002"):
        raise XMLError("expected pain.002")
    body = list(root)[0]
    og = kid(body, "OrgnlGrpInfAndSts")

    def reasons(e):
        out = []
        for r in kids(e, "StsRsnInf"):
            code = text(r, "Rsn", "Cd") or text(r, "Rsn", "Prtry")
            out.append({"code": code, "text": REASONS.get(code or "", code), "info": " ".join(x.text or "" for x in kids(r, "AddtlInf")).strip()})
        return out
    txs = []
    for pi in kids(body, "OrgnlPmtInfAndSts"):
        for t in kids(pi, "TxInfAndSts"):
            rs = reasons(t)
            st = text(t, "TxSts") or text(pi, "PmtInfSts")
            txs.append({"end_to_end_id": text(t, "OrgnlEndToEndId"), "instr_id": text(t, "OrgnlInstrId"), "status": st,
                        "status_text": TX_STATUS.get(st or "", st), "reason": rs[0]["code"] if rs else None,
                        "reason_text": rs[0]["text"] if rs else None, "info": rs[0]["info"] if rs else ""})
    return {"msg_id": text(body, "GrpHdr", "MsgId"), "created": text(body, "GrpHdr", "CreDtTm"),
            "orig_msg_id": text(og, "OrgnlMsgId"), "orig_msg_type": text(og, "OrgnlMsgNmId"),
            "group_status": text(og, "GrpSts"), "group_reasons": reasons(og), "txs": txs}


def build_pain002(msg_id: str, created_ts: float, pain001_xml, rejects: dict[str, str] | None = None,
                  status_ok: str = "ACSC") -> str:
    """SIMULATED bank response to a pain.001: every transaction gets status_ok unless its EndToEndId is in rejects
    ({e2e: reason_code}) -> RJCT."""
    rejects = rejects or {}
    orig = parse_pain001(pain001_xml)
    b = B("pain.002.001.10")
    root = b.root()
    body = b.el(root, "CstmrPmtStsRpt")
    gh = b.el(body, "GrpHdr")
    b.el(gh, "MsgId", msg_id[:35])
    b.el(gh, "CreDtTm", iso_dt(created_ts))
    og = b.el(body, "OrgnlGrpInfAndSts")
    b.el(og, "OrgnlMsgId", orig["msg_id"])
    b.el(og, "OrgnlMsgNmId", "pain.001.001.09")
    b.el(og, "OrgnlNbOfTxs", orig["nb_of_txs"])
    b.el(og, "OrgnlCtrlSum", orig["ctrl_sum"])
    n_rej = sum(t["end_to_end_id"] in rejects for t in orig["txs"])
    b.el(og, "GrpSts", status_ok if not n_rej else ("RJCT" if n_rej == len(orig["txs"]) else "PART"))
    by_pi: dict[str, list] = {}
    for t in orig["txs"]:
        by_pi.setdefault(t["pmt_inf_id"], []).append(t)
    for pid, group in by_pi.items():
        pi = b.el(body, "OrgnlPmtInfAndSts")
        b.el(pi, "OrgnlPmtInfId", pid)
        for t in group:
            tx = b.el(pi, "TxInfAndSts")
            b.el(tx, "OrgnlEndToEndId", t["end_to_end_id"])
            rej = rejects.get(t["end_to_end_id"])
            b.el(tx, "TxSts", "RJCT" if rej else status_ok)
            if rej:
                ri = b.el(tx, "StsRsnInf")
                b.el(b.el(ri, "Rsn"), "Cd", rej)
                b.el(ri, "AddtlInf", REASONS.get(rej, "rejected")[:105])
    return B.dump(root)


def execution_date_for(ts: float, region: str = "CA") -> str:
    from atlas.ledgers.banking.calendars import value_date
    return value_date(dt.date.fromtimestamp(ts), region).isoformat()
