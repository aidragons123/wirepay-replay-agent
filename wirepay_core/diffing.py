"""Compare two runs: what got fixed, what regressed, which patterns appeared or went away."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .engine import RunResult

ORDER = {"UNTESTED": 0, "INVALIDATED": 1, "VALIDATED": 2}


@dataclass
class RunDiff:
    kpis: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    patterns: dict[str, list[dict[str, Any]]]
    movement: dict[str, list[Any]]
    coverage_pct: float                       # share of payments present in both runs
    same_inputs: bool
    headline: str = ""
    totals: dict[str, int] = field(default_factory=dict)


def _pattern_key(p: dict[str, Any]) -> tuple:
    return (p["category"], tuple(p["rules"]))


def compare_runs(a: RunResult, b: RunResult, same_inputs: bool) -> RunDiff:
    ca, cb = a.counts, b.counts
    kpis = []
    for key, label, good_when_up in (("total", "Payments compared", None), ("match", "Exact match", True),
                                     ("expected", "Expected differences", None), ("mismatch", "Mismatches", False),
                                     ("parity_pct", "Parity %", True)):
        d = round(cb[key] - ca[key], 2)
        better = None if good_when_up is None or d == 0 else (d > 0) == good_when_up
        kpis.append({"key": key, "label": label, "a": ca[key], "b": cb[key], "delta": d, "better": better})

    ra = {r["id"]: r for r in a.rule_report}
    rules = []
    for r in b.rule_report:
        old = ra.get(r["id"])
        sa = old["status"] if old else "UNTESTED"
        change = "same" if sa == r["status"] else ("improved" if ORDER[r["status"]] > ORDER[sa] else "regressed")
        rules.append({"id": r["id"], "title": r["title"], "a_status": sa, "b_status": r["status"],
                      "a_mismatch": old["mismatch"] if old else 0, "b_mismatch": r["mismatch"], "change": change})

    pa = {_pattern_key(p): p for p in a.patterns}
    pb = {_pattern_key(p): p for p in b.patterns}
    patterns = {"resolved": [pa[k] for k in pa if k not in pb],
                "new": [pb[k] for k in pb if k not in pa],
                "persisting": [{**pb[k], "count_a": pa[k]["count"]} for k in pb if k in pa]}

    va = {r.request_id: r.verdict for r in a.results}
    vb = {r.request_id: r.verdict for r in b.results}
    both = va.keys() & vb.keys()
    mv: dict[str, list[Any]] = {"fixed": [], "regressed": [], "still_failing": [], "changed": [], "only_a": sorted(va.keys() - vb.keys()),
                                "only_b": sorted(vb.keys() - va.keys())}
    for pid in sorted(both):
        x, y = va[pid], vb[pid]
        if x == "MISMATCH" and y != "MISMATCH":
            mv["fixed"].append(pid)
        elif x != "MISMATCH" and y == "MISMATCH":
            mv["regressed"].append(pid)
        elif x == "MISMATCH" and y == "MISMATCH":
            mv["still_failing"].append(pid)
        elif x != y:
            mv["changed"].append((pid, x, y))
    union = len(va.keys() | vb.keys())
    coverage = round(100 * len(both) / union, 1) if union else 0.0

    nf, nr = len(mv["fixed"]), len(mv["regressed"])
    if not both:
        head = "The two runs share no payments, so they cannot be compared payment by payment."
    elif nf == 0 and nr == 0:
        head = "No payment changed between a mismatch and a non-mismatch."
    else:
        head = f"{nf} payment(s) fixed, {nr} regression(s)."
    return RunDiff(kpis, rules, patterns, mv, coverage, same_inputs, head, {k: len(v) for k, v in mv.items()})
