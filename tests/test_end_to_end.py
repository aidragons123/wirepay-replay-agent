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
}


def test_every_one_click_scenario_demonstrates_what_its_label_says():
    from wirepay_core.generator import SCENARIOS, scenario_request
    assert set(EXPECTED_SCENARIO_VERDICTS) == set(SCENARIOS)
    old, new, _ = standin_adapters(ROOT, parity_fix=False)
    for label, want in EXPECTED_SCENARIO_VERDICTS.items():
        for proc in ("2026-10-19", "2027-06-02"):           # also well past the bundled holiday list
            run = run_dual([scenario_request(label, proc)], old, new, SPEC)
            assert run.results[0].verdict == want, (label, proc, run.results[0].verdict)
