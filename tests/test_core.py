"""Unit tests for the comparison engine. No JVM needed - responses are hand-built."""
import copy
import json
import random
from datetime import date

import pytest
import yaml

from wirepay_core import capture, explain
from wirepay_core.compare import compare_record
from wirepay_core.config import DEFAULT_SPEC, load_spec
from wirepay_core.engine import run_replay
from wirepay_core.generator import generate_requests, make_iban

SPEC = load_spec()

REQ = {"requestId": "T1", "debtorName": "Acme Ltd", "debtorAccount": "DE89370400440532013000",
       "creditorName": "Müller GmbH", "creditorAccount": "FR1420041010050500013M02606", "creditorBic": "DEUTDEFF",
       "amount": "1000.00", "currency": "USD", "valueDate": "2026-10-22", "chargeBearer": "SHA",
       "remittanceInfo": "Inv 1", "processingDate": "2026-10-19"}


def old_ok(**kw):
    r = {"paymentId": "WP-T1", "status": "ACCEPTED", "errorCode": "", "errorMessage": "", "debtorName": "Acme Ltd",
         "debtorAccount": REQ["debtorAccount"], "creditorName": "Müller GmbH", "creditorAccount": REQ["creditorAccount"],
         "creditorBic": "DEUTDEFF", "amount": "1000.00", "currency": "USD", "fee": "15.00",
         "settlementDate": "2026-10-22", "chargeBearer": "SHA", "remittanceInfo": "Inv 1"}
    r.update(kw)
    return r


def xml(amount="1000.00", ccy="USD", date_="2026-10-22", cb="SHAR", fee="15.00", dn="Acme Ltd", cn="Müller GmbH"):
    return f"""<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08"><FIToFICstmrCdtTrf>
<GrpHdr><MsgId>WP-T1</MsgId></GrpHdr><CdtTrfTxInf>
<PmtId><InstrId>WP-T1</InstrId><EndToEndId>WP-T1</EndToEndId><UETR>76356f8c-3b67-48d2-9d41-f2a3a91eb37b</UETR></PmtId>
<IntrBkSttlmAmt Ccy="{ccy}">{amount}</IntrBkSttlmAmt><IntrBkSttlmDt>{date_}</IntrBkSttlmDt><ChrgBr>{cb}</ChrgBr>
<ChrgsInf><Amt Ccy="{ccy}">{fee}</Amt></ChrgsInf><Dbtr><Nm>{dn}</Nm></Dbtr>
<DbtrAcct><Id><IBAN>{REQ['debtorAccount']}</IBAN></Id></DbtrAcct>
<DbtrAgt><FinInstnId><BICFI>BANKUS33XXX</BICFI></FinInstnId></DbtrAgt>
<CdtrAgt><FinInstnId><BICFI>DEUTDEFF</BICFI></FinInstnId></CdtrAgt><Cdtr><Nm>{cn}</Nm></Cdtr>
<CdtrAcct><Id><IBAN>{REQ['creditorAccount']}</IBAN></Id></CdtrAcct><RmtInf><Ustrd>Inv 1</Ustrd></RmtInf>
</CdtTrfTxInf></FIToFICstmrCdtTrf></Document>"""


STAGES = ["RECEIVED", "BASIC_VALIDATION", "DUPLICATE_CHECK", "FRAUD_CHECK", "BANK_DETAILS_CHECK", "POSTING", "COMPLETED"]


def hist(states=STAGES, status="DONE", last_status=None):
    out = [{"seq": i, "state": st, "status": status} for i, st in enumerate(states, start=1)]
    if last_status:
        out[-1]["status"] = last_status
    return out


HIST_OK = hist()
HIST_REJ = [{"seq": 1, "state": "RECEIVED", "status": "DONE"}, {"seq": 2, "state": "BASIC_VALIDATION", "status": "FAILED"},
            {"seq": 3, "state": "REJECTED", "status": "DONE"}]


def new_ok(xml_=None, hist=None, **kw):
    hist_ = hist
    r = {"paymentId": "WP-T1", "status": "ACCP", "reasonCode": "", "uetr": "76356f8c-3b67-48d2-9d41-f2a3a91eb37b",
         "workflow": {"finalState": "COMPLETED", "history": hist_ or HIST_OK}, "pacs008": xml_ or xml()}
    r.update(kw)
    return r


def new_rej(code, hist_=None):
    return {"paymentId": "WP-T1", "status": "RJCT", "reasonCode": code, "uetr": "",
            "workflow": {"finalState": "REJECTED", "history": hist_ or HIST_REJ},
            "pacs008": ""}


def verdict(req, old, new):
    return compare_record(req, old, new, SPEC)


def test_identical_behaviour_is_a_match():
    r = verdict(REQ, old_ok(), new_ok())
    assert r.verdict == "MATCH", [c for c in r.checks if c.status != "MATCH"]


def test_amount_difference_is_unexplained_mismatch():
    r = verdict(REQ, old_ok(), new_ok(xml_=xml(amount="999.00")))
    assert r.verdict == "MISMATCH"
    assert any(c.rule_id == "M-004" and c.category == "UNEXPLAINED" for c in r.mismatches)


def test_long_name_truncation_is_expected_not_a_mismatch():
    long = "International Consolidated Industrial Holdings Corporation"
    r = verdict({**REQ, "debtorName": long}, old_ok(debtorName=long[:35]), new_ok(xml_=xml(dn=long)))
    assert r.verdict == "EXPECTED_DIFFERENCE"
    assert [c.feature_id for c in r.expected] == ["N-003"]


def test_name_difference_that_is_not_truncation_is_a_mismatch():
    r = verdict(REQ, old_ok(debtorName="Acme Ltd"), new_ok(xml_=xml(dn="Acme Limited")))
    assert r.verdict == "MISMATCH"


def test_bad_iban_rejected_by_new_is_expected_only_when_checksum_really_fails():
    bad = REQ["creditorAccount"][:-1] + "7"
    assert explain.iban_invalid(bad)
    r = verdict({**REQ, "creditorAccount": bad}, old_ok(creditorAccount=bad), new_rej("AC01"))
    assert r.verdict == "EXPECTED_DIFFERENCE"
    # ...but if the IBAN is actually fine, rejecting it is a defect in the new code.
    r2 = verdict(REQ, old_ok(), new_rej("AC01"))
    assert r2.verdict == "MISMATCH"
    assert r2.mismatches[0].category == "NEW_FEATURE_DEFECT"


def test_new_code_accepting_a_bad_iban_is_a_feature_defect():
    bad = REQ["creditorAccount"][:-1] + "7"
    r = verdict({**REQ, "creditorAccount": bad}, old_ok(creditorAccount=bad), new_ok())
    assert any(c.rule_id == "N-001" and c.status == "MISMATCH" for c in r.checks)


def test_holiday_settlement_expected_but_wrong_date_is_not():
    req = {**REQ, "currency": "EUR", "valueDate": "2026-12-25"}
    old = old_ok(currency="EUR", settlementDate="2026-12-25")
    ok = verdict(req, old, new_ok(xml_=xml(ccy="EUR", date_="2026-12-28")))
    assert ok.verdict == "EXPECTED_DIFFERENCE" and ok.expected[0].feature_id == "N-002"
    wrong = verdict(req, old, new_ok(xml_=xml(ccy="EUR", date_="2026-12-29")))
    assert wrong.verdict == "MISMATCH"


def test_half_cent_rounding_gap_is_diagnosed_as_rounding_mode():
    req = {**REQ, "amount": "20005.00"}   # fee 20.005 is an exact half-cent tie
    old = old_ok(amount="20005.00", fee="20.01")
    r = verdict(req, old, new_ok(xml_=xml(amount="20005.00", fee="20.00")))
    assert r.verdict == "MISMATCH" and r.mismatches[0].category == "ROUNDING_MODE"


def test_same_day_rejection_is_diagnosed_as_boundary_defect():
    req = {**REQ, "valueDate": "2026-10-19"}
    r = verdict(req, old_ok(settlementDate="2026-10-19"), new_rej("DT01"))
    assert r.verdict == "MISMATCH" and r.mismatches[0].category == "IMPLEMENTATION_DEFECT"


def test_reason_codes_are_mapped_not_compared_literally():
    old = {"paymentId": "WP-T1", "status": "REJECTED", "errorCode": "E003"}
    assert verdict(REQ, old, new_rej("AM03")).verdict == "MATCH"
    assert verdict(REQ, old, new_rej("AM02")).verdict == "MISMATCH"


def test_illegal_workflow_transition_is_flagged():
    bad = [{"seq": 1, "state": "RECEIVED", "status": "DONE"}, {"seq": 2, "state": "POSTING", "status": "DONE"},
           {"seq": 3, "state": "COMPLETED", "status": "DONE"}]
    r = verdict(REQ, old_ok(), new_ok(hist=bad))
    assert any(c.rule_id == "N-005" and c.status == "MISMATCH" for c in r.checks)


def test_missing_pacs008_elements_are_flagged():
    broken = xml().replace("<UETR>76356f8c-3b67-48d2-9d41-f2a3a91eb37b</UETR>", "")
    r = verdict(REQ, old_ok(), new_ok(xml_=broken, uetr=""))
    ids = {c.rule_id for c in r.mismatches}
    assert {"N-004", "N-006"} <= ids


def test_independent_calendar_matches_known_dates():
    assert explain.easter_sunday(2026) == date(2026, 4, 5)
    assert explain.target2_holiday(date(2026, 4, 3)) and explain.target2_holiday(date(2026, 4, 6))
    assert explain.easter_sunday(2027) == date(2027, 3, 28)
    assert explain.target2_holiday(date(2027, 3, 26)) and explain.target2_holiday(date(2027, 3, 29))
    assert not explain.target2_holiday(date(2026, 10, 19))
    assert explain.settlement_date(date(2026, 12, 25), "EUR", True) == date(2026, 12, 28)
    assert explain.settlement_date(date(2026, 12, 25), "USD", True) == date(2026, 12, 25)


def test_fee_tie_variants():
    v = explain.fee_variants(explain.Decimal("20005.00"), "SHA")
    assert str(v["HALF_UP"]) == "20.01" and str(v["HALF_EVEN"]) == "20.00"


def test_generated_ibans_are_valid():
    rng = random.Random(1)
    assert all(explain.iban_checksum_ok(make_iban(c, rng)) for c in ["DE", "FR", "GB", "NL", "CH"] * 10)


def test_generator_is_deterministic():
    assert generate_requests(50, 3, "2026-10-19") == generate_requests(50, 3, "2026-10-19")


def test_capture_roundtrip_and_validation():
    recs = [{"request": REQ, "response": old_ok()}]
    again = capture.parse_jsonl(capture.dump_jsonl(recs))
    assert again == recs and capture.validate(again) == []
    assert capture.validate(recs + recs)[0].endswith("duplicate requestId T1")
    with pytest.raises(capture.CaptureError):
        capture.parse_jsonl('{"request": {"a": 1}}')
    csv_text = "req_requestId,req_amount,resp_status\nA1,10.00,ACCEPTED\n"
    assert capture.parse_csv(csv_text)[0]["response"]["status"] == "ACCEPTED"


def test_a_rule_added_in_yaml_is_picked_up_without_code_changes(tmp_path):
    raw = yaml.safe_load(DEFAULT_SPEC.read_text())
    raw["mapping_rules"].append({"id": "M-099", "title": "Debtor account (again)", "field": "debtor_account",
                                 "compare": "exact", "applies": "both_accepted", "old_ref": "x", "new_ref": "y"})
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(raw))
    spec = load_spec(p)

    class Echo:
        def describe(self):
            return "echo"

        def run(self, reqs):
            return [new_ok() for _ in reqs]

    run = run_replay([{"request": REQ, "response": old_ok()}], Echo(), spec)
    row = next(r for r in run.rule_report if r["id"] == "M-099")
    assert row["checked"] == 1 and row["status"] == "VALIDATED"


def test_metrics_buckets_add_up():
    from types import SimpleNamespace as S
    from wirepay_core import metrics
    ok = {"status": "ACCEPTED"}
    new_ok = {"status": "ACCP"}
    rs = [S(request_id="1", verdict="MATCH", old_response=ok, new_response=new_ok),
          S(request_id="2", verdict="EXPECTED_DIFFERENCE", old_response=ok, new_response=new_ok),
          S(request_id="3", verdict="MISMATCH", old_response=ok, new_response={"status": "RJCT"}),
          S(request_id="4", verdict="MISMATCH", old_response=ok, new_response={})]
    m = metrics.compute(rs)
    assert (m["match"], m["explained"], m["failure"], m["error"]) == (1, 1, 1, 1)
    assert m["success_pct"] == 50.0 and m["error_pct"] == 25.0
    assert round(m["match_pct"] + m["explained_pct"] + m["failure_pct"] + m["error_pct"], 1) == 100.0


FRAUD_REQ = {**REQ, "creditorName": "Offshore Holdings Ltd"}
FRAUD_OLD = {"paymentId": "WP-T1", "status": "REJECTED", "errorCode": "E009"}


def new_pending(hist_=None, **kw):
    r = {"paymentId": "WP-T1", "status": "PDNG", "reasonCode": "FRAD", "uetr": "",
         "workflow": {"finalState": "FRAUD_CHECK", "resumeFrom": "FRAUD_CHECK",
                      "history": hist_ or hist(STAGES[:4], last_status="PAUSED")}, "pacs008": ""}
    r.update(kw)
    return r


def test_fraud_hold_is_an_explained_difference_not_a_mismatch():
    r = verdict(FRAUD_REQ, FRAUD_OLD, new_pending())
    assert r.verdict == "EXPECTED_DIFFERENCE" and [c.feature_id for c in r.expected] == ["N-007"]
    assert any(c.rule_id == "N-007" and c.status == "MATCH" for c in r.checks)


def test_hold_on_an_unflagged_payment_is_a_mismatch():
    r = verdict(REQ, FRAUD_OLD, new_pending())
    assert r.verdict == "MISMATCH" and any(c.rule_id == "M-001" for c in r.mismatches)


def test_pause_that_cannot_be_resumed_is_flagged():
    bad = new_pending()
    bad["workflow"].pop("resumeFrom")
    r = verdict(FRAUD_REQ, FRAUD_OLD, bad)
    assert any(c.rule_id == "N-007" and c.status == "MISMATCH" for c in r.checks)


RESUME_REQ = {**FRAUD_REQ, "resumeFrom": "FRAUD_CHECK", "fraudDecision": "RELEASE"}


def resumed_hist(restored=("RECEIVED", "BASIC_VALIDATION", "DUPLICATE_CHECK")):
    return [{"seq": i, "state": st, "status": "RESTORED" if st in restored else "DONE"} for i, st in enumerate(STAGES, start=1)]


def test_resume_completes_where_old_code_could_only_reject():
    old = {"paymentId": "WP-T1", "status": "REJECTED", "errorCode": "E008"}
    r = verdict(RESUME_REQ, old, new_ok(hist=resumed_hist()))
    assert r.verdict == "EXPECTED_DIFFERENCE" and r.expected[0].feature_id == "N-008"
    assert any(c.rule_id == "N-008" and c.status == "MATCH" for c in r.checks)


def test_resume_that_reruns_earlier_steps_is_flagged():
    old = {"paymentId": "WP-T1", "status": "REJECTED", "errorCode": "E008"}
    r = verdict(RESUME_REQ, old, new_ok(hist=resumed_hist(restored=("RECEIVED",))))
    assert any(c.rule_id == "N-008" and c.status == "MISMATCH" for c in r.checks)


def test_blocked_resume_after_duplicate_in_old_is_explained():
    old = {"paymentId": "WP-T1", "status": "REJECTED", "errorCode": "E008"}
    req = {**RESUME_REQ, "fraudDecision": "BLOCK"}
    h = [{"seq": 1, "state": "RECEIVED", "status": "RESTORED"}, {"seq": 2, "state": "BASIC_VALIDATION", "status": "RESTORED"},
         {"seq": 3, "state": "DUPLICATE_CHECK", "status": "RESTORED"}, {"seq": 4, "state": "FRAUD_CHECK", "status": "FAILED"},
         {"seq": 5, "state": "REJECTED", "status": "DONE"}]
    r = verdict(req, old, new_rej("FRAD", h))
    assert r.verdict == "EXPECTED_DIFFERENCE" and r.expected[0].feature_id == "N-008"
