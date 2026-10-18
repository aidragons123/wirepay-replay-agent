"""Rule-driven comparison of one payment: OLD response vs NEW response.

Verdicts per payment
  MATCH                 every applicable rule agrees
  EXPECTED_DIFFERENCE   differences exist, but every one is explained by a documented
                        new feature AND independently re-derived here
  MISMATCH              at least one difference that nothing documents (a regression to review),
                        or a new feature that does not behave
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from . import explain
from .canonical import Canon, canon_new, canon_old
from .config import Spec

MATCH, EXPECTED, MISMATCH = "MATCH", "EXPECTED", "MISMATCH"

CAT_ENHANCEMENT = "EXPECTED_ENHANCEMENT"
CAT_DEFECT = "IMPLEMENTATION_DEFECT"
CAT_ROUNDING = "ROUNDING_MODE"
CAT_REASON = "REASON_CODE"
CAT_FEATURE = "NEW_FEATURE_DEFECT"
CAT_UNEXPLAINED = "UNEXPLAINED"


@dataclass
class Check:
    rule_id: str
    title: str
    status: str
    old: str = ""
    new: str = ""
    category: str = ""
    feature_id: str = ""
    explanation: str = ""
    fix: str = ""
    pattern: str = ""      # payment-independent wording, used when grouping mismatches into patterns


@dataclass
class RecordResult:
    request_id: str
    verdict: str
    checks: list[Check]
    request: dict[str, Any]
    old_response: dict[str, Any]
    new_response: dict[str, Any]

    @property
    def mismatches(self) -> list[Check]:
        return [c for c in self.checks if c.status == MISMATCH]

    @property
    def expected(self) -> list[Check]:
        return [c for c in self.checks if c.status == EXPECTED]


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _proc_date(req: dict) -> date:
    return _date(str(req.get("processingDate", ""))) or date.today()


def _same_day(req: dict) -> bool:
    vd = _date(str(req.get("valueDate", "")).strip())
    return vd is not None and vd == _proc_date(req)


BOUNDARY_PATTERN = ("Same-day payments (value date = processing date) are rejected by the new code with DT01 "
                    "but accepted by the old code: an off-by-one in the past-date check.")
BOUNDARY_FIX = ("Treat a value date equal to the processing date as valid (same-day payment); "
                "reject only dates strictly before it.")


def _decision_check(rule: dict, req: dict, co: Canon, cn: Canon, spec: Spec) -> Check:
    base = dict(rule_id=rule["id"], title=rule["title"], old=co.raw_status, new=cn.raw_status)
    expected_new = spec.decision_map.get(co.raw_status)
    if expected_new is not None and expected_new == cn.raw_status:
        return Check(status=MATCH, **base)
    if co.decision == "ACCEPTED" and cn.decision == "REJECTED":
        if cn.reason == "AC01":
            if explain.any_iban_invalid(req):
                return Check(status=EXPECTED, category=CAT_ENHANCEMENT, feature_id="N-001", **base,
                             explanation="Old code accepted this payment because it only checks IBAN shape. "
                                         "The IBAN fails the mod-97 checksum (independently verified), so the new "
                                         "code rightly rejects it.")
            return Check(status=MISMATCH, category=CAT_FEATURE, feature_id="N-001", **base,
                         explanation="New code rejected with AC01 but both accounts pass the IBAN checksum.",
                         fix="Review the account validation in the new code.")
        if cn.reason == "DT01" and _same_day(req):
            return Check(status=MISMATCH, category=CAT_DEFECT, **base,
                         explanation="Value date equals the processing date. Old code accepts same-day payments; "
                                     "new code rejects them (off-by-one in the past-date check).",
                         fix=BOUNDARY_FIX, pattern=BOUNDARY_PATTERN)
    if co.decision == "REJECTED" and cn.decision == "ACCEPTED":
        return Check(status=MISMATCH, category=CAT_UNEXPLAINED, **base,
                     explanation=f"Old code rejected ({co.reason}) but new code accepted the payment.",
                     fix="Find which validation the new code dropped.")
    return Check(status=MISMATCH, category=CAT_UNEXPLAINED, **base,
                 explanation=f"Decision differs: old {co.raw_status or '?'} vs new {cn.raw_status or '?'} "
                             f"(reason {cn.reason or '-'}).",
                 fix="Compare the validation order and thresholds of both services.")


def _reason_check(rule: dict, req: dict, co: Canon, cn: Canon, spec: Spec) -> Check:
    base = dict(rule_id=rule["id"], title=rule["title"], old=co.reason, new=cn.reason)
    expected_new = spec.reason_code_map.get(co.reason)
    if expected_new is not None and expected_new == cn.reason:
        return Check(status=MATCH, **base)
    if cn.reason == "DT01" and _same_day(req):
        return Check(status=MISMATCH, category=CAT_DEFECT, **base,
                     explanation="New code rejects a same-day value date before it reaches the check that "
                                 f"rejected this payment in the old code ({co.reason}).",
                     fix=BOUNDARY_FIX, pattern=BOUNDARY_PATTERN)
    why = (f"Old code {co.reason} should map to {expected_new}, new code returned {cn.reason}."
           if expected_new else f"Old reason {co.reason!r} has no entry in reason_code_map.")
    return Check(status=MISMATCH, category=CAT_REASON, **base, explanation=why,
                 fix="Align the validation order, or extend reason_code_map if the new code is intentionally different.")


def _field_check(rule: dict, req: dict, co: Canon, cn: Canon, spec: Spec) -> Check:
    f, kind = rule["field"], rule["compare"]
    o, n = co.fields.get(f, ""), cn.fields.get(f, "")
    base = dict(rule_id=rule["id"], title=rule["title"], old=o, new=n)

    def unexplained(msg: str = "") -> Check:
        return Check(status=MISMATCH, category=CAT_UNEXPLAINED, **base,
                     explanation=msg or f"{rule['title']} differs and no documented feature explains it.",
                     fix="Review the mapping of this field.")

    if kind == "decimal":
        od, nd = _dec(o), _dec(n)
        if od is not None and nd is not None and od == nd:
            return Check(status=MATCH, **base)
        if f == "fee" and od is not None and nd is not None:
            amt = _dec(co.fields.get("amount", ""))
            if amt is not None:
                v = explain.fee_variants(amt, explain.effective_bearer(str(req.get("chargeBearer", "")).strip()))
                if od == v["HALF_UP"] and nd == v["HALF_EVEN"]:
                    return Check(status=MISMATCH, category=CAT_ROUNDING, **base,
                                 explanation=f"Fee is an exact half-cent tie: old rounds HALF_UP to {od}, "
                                             f"new rounds HALF_EVEN (banker's rounding) to {nd}.",
                                 fix="Use RoundingMode.HALF_UP for the wire fee, or record banker's rounding as an "
                                     "approved business change.",
                                 pattern="Fees that land on an exact half cent are rounded HALF_UP by the old code but HALF_EVEN "
                                         "(banker's rounding) by the new code, so they differ by 0.01.")
        return unexplained()

    if kind == "date":
        if o == n:
            return Check(status=MATCH, **base)
        vd = _date(str(req.get("valueDate", "")).strip())
        ccy = co.fields.get("currency", "")
        if vd and ccy == "EUR" and n == explain.settlement_date(vd, "EUR", True).isoformat() \
                and o == explain.settlement_date(vd, "EUR", False).isoformat():
            return Check(status=EXPECTED, category=CAT_ENHANCEMENT, feature_id="N-002", **base,
                         explanation=f"{vd} is a TARGET2 closing day (independently verified). Old code settled on "
                                     f"{o}; new code correctly moves to the next business day, {n}.")
        return unexplained()

    if kind == "bearer":
        mapped = spec.charge_bearer_map.get(o, "")
        return Check(status=MATCH, **base) if mapped and mapped == n else unexplained(
            f"Old charge bearer {o} should map to {mapped or '?'}, new code returned {n}.")

    if kind == "name":
        if o == n:
            return Check(status=MATCH, **base)
        if len(n) > explain.NAME_LIMIT_OLD and o == n[:explain.NAME_LIMIT_OLD]:
            return Check(status=EXPECTED, category=CAT_ENHANCEMENT, feature_id="N-003", **base,
                         explanation=f"Old model cut the name to {explain.NAME_LIMIT_OLD} characters; "
                                     f"new code keeps all {len(n)} (pacs.008 allows 140).")
        return unexplained()

    return Check(status=MATCH, **base) if o == n else unexplained()


def _new_feature_checks(req: dict, cn: Canon) -> list[Check]:
    out: list[Check] = []

    # N-005 workflow audit trail (accepted and rejected payments)
    wf = cn.workflow or {}
    hist = wf.get("history") or []
    problems: list[str] = []
    if not hist:
        problems.append("history is empty")
    else:
        if hist[0].get("state") != "RECEIVED":
            problems.append("first state is not RECEIVED")
        for i, step in enumerate(hist, start=1):
            if step.get("seq") != i:
                problems.append(f"step {i} has seq {step.get('seq')}")
                break
        for a, b in zip(hist, hist[1:]):
            if b.get("state") not in explain.ALLOWED_TRANSITIONS.get(a.get("state"), set()):
                problems.append(f"illegal transition {a.get('state')} -> {b.get('state')}")
                break
        final = hist[-1].get("state")
        want = {"ACCEPTED": "ACCEPTED", "REJECTED": "REJECTED"}.get(cn.decision)
        if wf.get("finalState") != final:
            problems.append("finalState does not equal last history state")
        if want and final != want:
            problems.append(f"decision is {cn.decision} but workflow ends in {final}")
    out.append(Check("N-005", "Workflow audit trail", MISMATCH if problems else MATCH,
                     new=" → ".join(s.get("state", "?") for s in hist),
                     category=CAT_FEATURE if problems else "", feature_id="N-005",
                     explanation="; ".join(problems),
                     fix="Fix the workflow engine so every payment records a legal, complete path." if problems else ""))

    if cn.decision == "ACCEPTED":
        ok_uetr = bool(explain.UETR_RE.match(cn.uetr or ""))
        out.append(Check("N-004", "UETR assigned", MATCH if ok_uetr else MISMATCH, new=cn.uetr,
                         category="" if ok_uetr else CAT_FEATURE, feature_id="N-004",
                         explanation="" if ok_uetr else "UETR missing or not a UUIDv4.",
                         fix="" if ok_uetr else "Generate a UUIDv4 UETR for every accepted payment."))
        bad = cn.xml_error or (("missing: " + ", ".join(cn.xml_missing)) if cn.xml_missing else "") \
            or ("" if cn.xml_present else "no pacs.008 message returned")
        out.append(Check("N-006", "pacs.008 structure", MISMATCH if bad else MATCH, new=bad or "complete",
                         category=CAT_FEATURE if bad else "", feature_id="N-006", explanation=bad,
                         fix="Populate every mandatory pacs.008 element." if bad else ""))
        shaped = [a for a in (str(req.get("debtorAccount", "")).strip(), str(req.get("creditorAccount", "")).strip())
                  if explain.is_iban_shaped(a)]
        if shaped:
            bad_iban = explain.any_iban_invalid(req)
            out.append(Check("N-001", "IBAN checksum enforced", MISMATCH if bad_iban else MATCH,
                             new="accepted", category=CAT_FEATURE if bad_iban else "", feature_id="N-001",
                             explanation="New code accepted an IBAN that fails the mod-97 checksum." if bad_iban else "",
                             fix="Enforce the mod-97 check on both accounts." if bad_iban else ""))
    return out


def compare_record(req: dict[str, Any], old_resp: dict[str, Any], new_resp: dict[str, Any], spec: Spec) -> RecordResult:
    co, cn = canon_old(old_resp), canon_new(new_resp)
    both_acc = co.decision == "ACCEPTED" and cn.decision == "ACCEPTED"
    both_rej = co.decision == "REJECTED" and cn.decision == "REJECTED"
    checks: list[Check] = []
    for rule in spec.mapping_rules:
        applies = rule.get("applies", "always")
        if applies == "both_accepted" and not both_acc:
            continue
        if applies == "both_rejected" and not both_rej:
            continue
        if rule["compare"] == "decision":
            c = _decision_check(rule, req, co, cn, spec)
        elif rule["compare"] == "reason":
            c = _reason_check(rule, req, co, cn, spec)
        else:
            c = _field_check(rule, req, co, cn, spec)
        checks.append(c)
    checks.extend(_new_feature_checks(req, cn))

    if any(c.status == MISMATCH for c in checks):
        verdict = MISMATCH
    elif any(c.status == EXPECTED for c in checks):
        verdict = "EXPECTED_DIFFERENCE"
    else:
        verdict = MATCH
    rid = str(req.get("requestId", "")) or str(new_resp.get("paymentId", ""))
    return RecordResult(rid, verdict, checks, req, old_resp, new_resp)
