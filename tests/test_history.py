"""History store, release gate, run comparison, custom rules and the requests-upload parser."""
import json
import shutil
from pathlib import Path

import pytest

from wirepay_core import capture
from wirepay_core.config import load_spec
from wirepay_core.diffing import compare_runs
from wirepay_core.engine import run_dual
from wirepay_core.gate import Gate, evaluate
from wirepay_core.generator import generate_requests
from wirepay_core.runtime import standin_adapters
from wirepay_core.store import Store

needs_jdk = pytest.mark.skipif(shutil.which("javac") is None, reason="needs a JDK")
ROOT = Path(__file__).resolve().parents[1]


def counts(m, e, x):
    n = m + e + x
    return {"total": n, "match": m, "expected": e, "mismatch": x, "parity_pct": round(100 * (m + e) / n, 2)}


def test_gate_go_and_no_go_with_reasons():
    assert evaluate(counts(90, 10, 0), Gate()).passed
    r = evaluate(counts(90, 5, 5), Gate())
    assert not r.passed and r.label == "NO-GO" and len(r.reasons) == 2
    assert evaluate(counts(90, 5, 5), Gate(max_mismatches=5, min_parity_pct=90.0)).passed


@pytest.fixture(scope="module")
def two_runs():
    reqs, _ = generate_requests(300, 5, "2026-10-19")
    spec = load_spec()
    old, gaps, _ = standin_adapters(ROOT, False)
    _, fixed, _ = standin_adapters(ROOT, True)
    return run_dual(reqs, old, gaps, spec), run_dual(reqs, old, fixed, spec)


@needs_jdk
def test_store_round_trip_pin_delete_and_bundle(two_runs, tmp_path):
    a, _ = two_runs
    s = Store(tmp_path / "h")
    rid = s.save_run(a, "dualrun", "first", "note")
    assert [r["id"] for r in s.list_runs()] == [rid]
    summary, back = s.load_run(rid)
    assert back.counts == a.counts and [r.verdict for r in back.results] == [r.verdict for r in a.results]
    assert summary["gate"]["passed"] is (a.counts["mismatch"] == 0)
    s.update(rid, pinned=True, label="renamed")
    assert s.list_runs()[0]["pinned"] and s.list_runs()[0]["label"] == "renamed"
    bundle = s.export_bundle()
    other = Store(tmp_path / "o")
    assert other.import_bundle(bundle) == 1 and other.import_bundle(bundle) == 0     # idempotent
    s.delete(rid)
    assert s.list_runs() == []


@needs_jdk
def test_compare_runs_shows_gaps_fixed_without_regressions(two_runs):
    gaps, fixed = two_runs
    d = compare_runs(gaps, fixed, True)
    assert d.movement["regressed"] == [] and len(d.movement["fixed"]) == gaps.counts["mismatch"] > 0
    assert d.patterns["new"] == [] and len(d.patterns["resolved"]) == len(gaps.patterns)
    assert fixed.counts["mismatch"] == 0


def test_settings_and_custom_rules_persist_and_validate(tmp_path):
    s = Store(tmp_path)
    cfg = s.load_settings()
    cfg["gate"] = Gate(3, 99.0).as_dict()
    s.save_settings(cfg)
    assert Store(tmp_path).load_settings()["gate"]["max_mismatches"] == 3
    rule = {"id": "C-001", "title": "Remittance carried over", "field": "remittance", "compare": "exact",
            "applies": "both_accepted", "old_ref": "remittanceInfo", "new_ref": "remittance"}
    s.save_custom_rules([rule])
    spec = load_spec(extra_rules=s.load_custom_rules())
    assert spec.mapping_rules[-1]["id"] == "C-001" and spec.mapping_rules[-1]["custom"]
    with pytest.raises(ValueError):
        load_spec(extra_rules=[{"id": "C-002"}])


def test_requests_upload_parses_jsonl_and_csv_and_adds_ids():
    jl = b'{"debtorName":"A","amount":"1.00"}\n{"requestId":"X1","debtorName":"B","amount":"2.00"}\n'
    reqs = capture.parse_requests_bytes(jl, "r.jsonl")
    assert len(reqs) == 2 and reqs[0]["requestId"].startswith("UP") and reqs[1]["requestId"] == "X1"
    csv = b"requestId,debtorName,amount\nR1,A,1.00\nR2,B,2.00\n"
    assert [r["requestId"] for r in capture.parse_requests_bytes(csv, "r.csv")] == ["R1", "R2"]
    with pytest.raises(capture.CaptureError):
        capture.parse_requests_bytes(b"not json", "r.jsonl")
