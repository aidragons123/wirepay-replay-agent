"""Normalise the OLD flat response and the NEW pacs.008 response into one comparable shape."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"}


@dataclass
class Canon:
    side: str                              # "old" | "new"
    decision: str                          # "ACCEPTED" | "REJECTED" | "UNKNOWN"
    reason: str = ""
    raw_status: str = ""                   # status exactly as returned (ACCEPTED / ACCP ...)
    fields: dict[str, str] = field(default_factory=dict)
    # new-side only
    uetr: str = ""
    workflow: dict[str, Any] = field(default_factory=dict)
    xml_present: bool = False
    xml_error: str = ""
    xml_missing: list[str] = field(default_factory=list)


def canon_old(resp: dict[str, Any]) -> Canon:
    status = str(resp.get("status", "")).upper()
    decision = status if status in ("ACCEPTED", "REJECTED") else "UNKNOWN"
    keymap = {
        "payment_id": "paymentId", "amount": "amount", "currency": "currency", "fee": "fee",
        "settlement_date": "settlementDate", "debtor_name": "debtorName", "creditor_name": "creditorName",
        "debtor_account": "debtorAccount", "creditor_account": "creditorAccount",
        "creditor_bic": "creditorBic", "charge_bearer": "chargeBearer", "remittance": "remittanceInfo",
    }
    return Canon("old", decision, str(resp.get("errorCode", "")), status,
                 {k: str(resp.get(v, "") or "") for k, v in keymap.items()})


# Elements a structurally complete pacs.008 transaction must carry (N-006).
REQUIRED_PATHS = {
    "GrpHdr/MsgId": "p:FIToFICstmrCdtTrf/p:GrpHdr/p:MsgId",
    "PmtId/InstrId": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:PmtId/p:InstrId",
    "PmtId/UETR": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:PmtId/p:UETR",
    "IntrBkSttlmAmt": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:IntrBkSttlmAmt",
    "IntrBkSttlmDt": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:IntrBkSttlmDt",
    "ChrgBr": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:ChrgBr",
    "Dbtr/Nm": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:Dbtr/p:Nm",
    "DbtrAcct": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:DbtrAcct/p:Id",
    "DbtrAgt": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:DbtrAgt/p:FinInstnId/p:BICFI",
    "CdtrAgt": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:CdtrAgt/p:FinInstnId/p:BICFI",
    "Cdtr/Nm": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:Cdtr/p:Nm",
    "CdtrAcct": "p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:CdtrAcct/p:Id",
}


def _acct(root: ET.Element, tag: str) -> str:
    base = f"p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:{tag}/p:Id"
    iban = root.find(f"{base}/p:IBAN", NS)
    if iban is not None and iban.text:
        return iban.text
    other = root.find(f"{base}/p:Othr/p:Id", NS)
    return (other.text or "") if other is not None else ""


def canon_new(resp: dict[str, Any]) -> Canon:
    status = str(resp.get("status", "")).upper()
    decision = {"ACCP": "ACCEPTED", "RJCT": "REJECTED"}.get(status, "UNKNOWN")
    c = Canon("new", decision, str(resp.get("reasonCode", "")), status,
              {"payment_id": str(resp.get("paymentId", ""))},
              uetr=str(resp.get("uetr", "")), workflow=resp.get("workflow") or {})
    xml = resp.get("pacs008") or ""
    if not xml:
        return c
    c.xml_present = True
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        c.xml_error = str(e)
        return c
    c.xml_missing = [name for name, path in REQUIRED_PATHS.items() if root.find(path, NS) is None]

    def text(path: str) -> str:
        el = root.find(f"p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/{path}", NS)
        return (el.text or "") if el is not None else ""

    amt = root.find("p:FIToFICstmrCdtTrf/p:CdtTrfTxInf/p:IntrBkSttlmAmt", NS)
    c.fields.update({
        "payment_id": text("p:PmtId/p:InstrId"),
        "amount": (amt.text or "") if amt is not None else "",
        "currency": amt.get("Ccy", "") if amt is not None else "",
        "settlement_date": text("p:IntrBkSttlmDt"),
        "fee": text("p:ChrgsInf/p:Amt"),
        "charge_bearer": text("p:ChrgBr"),
        "debtor_name": text("p:Dbtr/p:Nm"),
        "creditor_name": text("p:Cdtr/p:Nm"),
        "debtor_account": _acct(root, "DbtrAcct"),
        "creditor_account": _acct(root, "CdtrAcct"),
        "creditor_bic": text("p:CdtrAgt/p:FinInstnId/p:BICFI"),
        "remittance": text("p:RmtInf/p:Ustrd"),
    })
    if not c.uetr:
        c.uetr = text("p:PmtId/p:UETR")
    return c
