"""End to end with the real stand-in JVMs. Skipped when no JDK is installed."""
import shutil
from collections import Counter
from pathlib import Path

import pytest

from wirepay_core.config import load_spec
from wirepay_core.engine import run_dual, run_replay
from wirepay_core.generator import generate_requests
from wirepay_core.runtime import standin_adapters

pytestmark = pytest.mark.skipif(shutil.which("javac") is None, reason="needs a JDK")
ROOT = Path(__file__).resolve().parents[1]
SPEC = load_spec()
PROC = "2026-10-19"


@pytest.fixture(scope="module")
def traffic():
    reqs, cats = generate_requests(600, 3, PROC)
    return reqs, cats


def verdicts(run):
    return {r.request_id: r.verdict for r in run.results}


def test_planted_gaps_are_found_and_nothing_clean_is_flagged(traffic):
    reqs, cats = traffic
    old, new, _ = standin_adapters(ROOT, parity_fix=False)
    run = run_dual(reqs, old, new, SPEC)
    v = verdicts(run)
    by = Counter((c, v[q["requestId"]]) for q, c in zip(reqs, cats))
    assert by[("clean", "MISMATCH")] == 0 and by[("clean", "EXPECTED_DIFFERENCE")] == 0   # no false alarms
    assert by[("same_day", "MISMATCH")] > 0 and by[("same_day", "MATCH")] == 0           # boundary gap caught
    assert by[("fee_tie", "MISMATCH")] > 0                                                 # rounding gap caught
    assert by[("iban_checksum", "EXPECTED_DIFFERENCE")] > 0                                # new feature explained
    assert {p["category"] for p in run.patterns} == {"IMPLEMENTATION_DEFECT", "ROUNDING_MODE"}


def test_with_gaps_fixed_only_documented_differences_remain(traffic):
    reqs, _ = traffic
    old, new, _ = standin_adapters(ROOT, parity_fix=True)
    run = run_dual(reqs, old, new, SPEC)
    assert run.counts["mismatch"] == 0 and run.counts["parity_pct"] == 100.0
    assert run.counts["expected"] > 0
    assert all(r["status"] != "INVALIDATED" for r in run.rule_report)


def test_replay_of_recorded_traffic_equals_a_live_dual_run(traffic):
    reqs, _ = traffic
    old, new, _ = standin_adapters(ROOT)
    live = run_dual(reqs, old, new, SPEC)
    recorded = [{"request": q, "response": r} for q, r in zip(reqs, old.run(reqs))]
    replay = run_replay(recorded, new, SPEC)
    assert replay.counts == live.counts and verdicts(replay) == verdicts(live)


def test_special_characters_survive_json_and_xml_round_trip(traffic):
    reqs, cats = traffic
    old, new, _ = standin_adapters(ROOT, parity_fix=True)
    sel = [q for q, c in zip(reqs, cats) if c == "special_chars"]
    assert sel
    run = run_dual(sel, old, new, SPEC)
    assert run.counts["mismatch"] == 0


EXPECTED_SCENARIO_VERDICTS = {
    "Clean USD payment": "MATCH",
    "Long party name (> 35 chars)": "EXPECTED_DIFFERENCE",
    "Bad IBAN checksum": "EXPECTED_DIFFERENCE",
    "EUR on a TARGET2 holiday": "EXPECTED_DIFFERENCE",
    "Fee lands on an exact half cent": "MISMATCH",
    "Same-day value date": "MISMATCH",
    "Charge bearer OUR": "MATCH",
    "Special characters in names": "MATCH",
    "Over the payment limit": "MATCH",
    "Missing mandatory field": "MATCH",
    "Fraud flag: new code holds, old rejects": "EXPECTED_DIFFERENCE",
    "Resume a held payment (release)": "EXPECTED_DIFFERENCE",
    "Insufficient funds at posting": "MATCH",
}


def test_every_one_click_scenario_demonstrates_what_its_label_says():
    from wirepay_core.generator import SCENARIOS, scenario_request
    assert set(EXPECTED_SCENARIO_VERDICTS) == set(SCENARIOS)
    old, new, _ = standin_adapters(ROOT, parity_fix=False)
    for label, want in EXPECTED_SCENARIO_VERDICTS.items():
        for proc in ("2026-10-19", "2027-06-02"):           # also well past the bundled holiday list
            run = run_dual([scenario_request(label, proc)], old, new, SPEC)
            assert run.results[0].verdict == want, (label, proc, run.results[0].verdict)


def test_git_branches_compared(tmp_path):
    """Old = 'legacy' branch, new = 'modern' branch of one local repo; the fixed branch removes the planted gaps."""
    import subprocess, sys
    from pathlib import Path
    from wirepay_core import gitsource
    from datetime import date
    root = Path(__file__).resolve().parent.parent
    repo = tmp_path / "repo"
    subprocess.run([sys.executable, str(root / "demo" / "make_demo_repo.py"), str(repo)], check=True, capture_output=True)
    refs = gitsource.list_refs(str(repo))
    assert {"legacy", "modern", "modern-fixed"} <= set(refs)
    work = tmp_path / "work"
    old = gitsource.prepare(gitsource.GitSpec(str(repo), "legacy", main_class="com.bank.wire.legacy.Main", release=8), work, "old")
    new = gitsource.prepare(gitsource.GitSpec(str(repo), "modern", main_class="com.bank.wire.modern.Main", release=18), work, "new")
    fix = gitsource.prepare(gitsource.GitSpec(str(repo), "modern-fixed", main_class="com.bank.wire.modern.Main", release=18), work, "new")
    assert old.sha != new.sha and "modern" in new.label("new") and new.short in new.label("new")
    spec = SPEC
    reqs, _ = generate_requests(200, 3, date.today())
    bad = run_dual(reqs, old.adapter("old"), new.adapter("new"), spec)
    good = run_dual(reqs, old.adapter("old"), fix.adapter("new"), spec)
    assert bad.counts["mismatch"] > 0 and good.counts["mismatch"] == 0
    assert new.short in bad.meta["new"]


def test_git_rejects_unsafe_input():
    import pytest
    from wirepay_core import gitsource
    for repo, ref in (("-oops", "main"), ("ext::sh -c id", "main"), ("/tmp/x", "--upload-pack=id"), ("/tmp/x", "a..b")):
        with pytest.raises(gitsource.GitError):
            gitsource.validate(gitsource.GitSpec(repo, ref, main_class="a.B"))


def test_held_payment_resumes_from_the_fraud_step_and_old_code_cannot():
    """Same payment sent twice: first it is held, then resumed. The old code rejects the second as a duplicate."""
    old, new, _ = standin_adapters(ROOT, parity_fix=True)
    first = scenario_request_for_fraud()
    again = {**first, "resumeFrom": "FRAUD_CHECK", "fraudDecision": "RELEASE"}
    run = run_dual([first, again], old, new, SPEC)
    a, b = run.results
    assert a.old_response["errorCode"] == "E009" and a.new_response["status"] == "PDNG"
    assert b.old_response["errorCode"] == "E008" and b.new_response["status"] == "ACCP"
    hist = {h["state"]: h["status"] for h in b.new_response["workflow"]["history"]}
    assert hist["DUPLICATE_CHECK"] == "RESTORED" and hist["FRAUD_CHECK"] == "DONE" and hist["COMPLETED"] == "DONE"
    assert run.counts["mismatch"] == 0


def scenario_request_for_fraud():
    from wirepay_core.generator import scenario_request
    return scenario_request("Fraud flag: new code holds, old rejects", "2026-10-19")


def test_old_and_new_stage_order_agree_on_duplicate_and_no_funds():
    old, new, _ = standin_adapters(ROOT, parity_fix=True)
    from wirepay_core.generator import scenario_request
    ok = scenario_request("Clean USD payment", "2026-10-19")
    broke = {**scenario_request("Insufficient funds at posting", "2026-10-19")}
    run = run_dual([ok, dict(ok), broke], old, new, SPEC)
    assert [r.old_response.get("errorCode", "") for r in run.results] == ["", "E008", "E010"]
    assert [r.new_response["reasonCode"] for r in run.results] == ["", "DUPL", "AM04"]
    assert run.counts["mismatch"] == 0
