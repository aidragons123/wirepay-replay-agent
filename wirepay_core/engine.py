"""Run orchestration shared by both agents: get responses -> compare -> diagnose -> summarise."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .adapters import Adapter
from .compare import (CAT_UNEXPLAINED, EXPECTED, MATCH, MISMATCH, Check, RecordResult, compare_record)
from .config import Spec

Progress = Callable[[str], None]


@dataclass
class StepTrace:
    name: str
    seconds: float
    detail: str


@dataclass
class RunResult:
    mode: str                                   # "replay" | "dual-run"
    results: list[RecordResult]
    rule_report: list[dict[str, Any]]
    patterns: list[dict[str, Any]]
    trace: list[StepTrace]
    counts: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def by_verdict(self, verdict: str) -> list[RecordResult]:
        return [r for r in self.results if r.verdict == verdict]


def _rule_report(results: list[RecordResult], spec: Spec) -> list[dict[str, Any]]:
    tally: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        for c in r.checks:
            tally[c.rule_id][c.status] += 1
            if c.status != MATCH and c.feature_id and c.feature_id != c.rule_id:
                tally[c.feature_id][c.status] += 1
    rows = []
    for kind, items in (("mapping rule", spec.mapping_rules), ("new feature", spec.new_features)):
        for it in items:
            t = tally.get(it["id"], Counter())
            checked = t[MATCH] + t[EXPECTED] + t[MISMATCH]
            status = "UNTESTED" if checked == 0 else ("INVALIDATED" if t[MISMATCH] else "VALIDATED")
            rows.append({"id": it["id"], "kind": kind, "title": it["title"], "checked": checked,
                         "match": t[MATCH], "expected": t[EXPECTED], "mismatch": t[MISMATCH], "status": status,
                         "old_ref": it.get("old_ref", ""), "new_ref": it.get("new_ref", ""), "note": it.get("note", "")})
    return rows


def _patterns(results: list[RecordResult]) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, Any]] = {}
    for r in results:
        for c in r.mismatches:
            key = (c.category, c.rule_id) if c.category == CAT_UNEXPLAINED else (c.category, c.fix)
            g = groups.setdefault(key, {"category": c.category, "fix": c.fix, "explanation": c.pattern or c.explanation,
                                        "rules": set(), "records": []})
            g["rules"].add(c.rule_id)
            if r.request_id not in g["records"]:
                g["records"].append(r.request_id)
    out = []
    for i, g in enumerate(sorted(groups.values(), key=lambda g: -len(g["records"])), start=1):
        out.append({"pattern_id": f"P-{i}", "category": g["category"], "rules": sorted(g["rules"]),
                    "count": len(g["records"]), "explanation": g["explanation"], "fix": g["fix"],
                    "examples": g["records"][:8]})
    return out


def _summarise(results: list[RecordResult]) -> dict[str, Any]:
    n = len(results)
    c = Counter(r.verdict for r in results)
    return {"total": n, "match": c["MATCH"], "expected": c["EXPECTED_DIFFERENCE"], "mismatch": c["MISMATCH"],
            "parity_pct": round(100 * (c["MATCH"] + c["EXPECTED_DIFFERENCE"]) / n, 2) if n else 0.0,
            "exact_pct": round(100 * c["MATCH"] / n, 2) if n else 0.0}


def compare_all(requests: list[dict], old: list[dict], new: list[dict], spec: Spec) -> list[RecordResult]:
    if not (len(requests) == len(old) == len(new)):
        raise ValueError(f"length mismatch: {len(requests)} requests, {len(old)} old, {len(new)} new responses")
    return [compare_record(q, o, n, spec) for q, o, n in zip(requests, old, new)]


def _finish(mode: str, results, trace, spec: Spec, meta) -> RunResult:
    t0 = time.perf_counter()
    rules = _rule_report(results, spec)
    pats = _patterns(results)
    counts = _summarise(results)
    trace.append(StepTrace("Diagnose & summarise", time.perf_counter() - t0,
                           f"{len(pats)} distinct mismatch pattern(s) across {counts['mismatch']} record(s)"))
    meta = {**meta, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "spec": str(spec.path.name)}
    return RunResult(mode, results, rules, pats, trace, counts, meta)


def run_replay(records: list[dict[str, Any]], new_adapter: Adapter, spec: Spec,
               progress: Progress | None = None, meta: dict | None = None) -> RunResult:
    """AGENT 1. `records` = [{"request": {...}, "response": {...}}] captured from the running OLD system."""
    say = progress or (lambda _m: None)
    trace: list[StepTrace] = []
    requests = [r["request"] for r in records]
    old = [r["response"] for r in records]
    trace.append(StepTrace("Load recorded old-system traffic", 0.0, f"{len(records)} request/response pairs"))

    say("Replaying recorded requests through the new implementation…")
    t = time.perf_counter()
    new = new_adapter.run(requests)
    dt = time.perf_counter() - t
    trace.append(StepTrace("Replay through new code", dt, f"{len(new)} responses from {new_adapter.describe()}"))

    say("Comparing recorded old responses with new responses…")
    t = time.perf_counter()
    results = compare_all(requests, old, new, spec)
    trace.append(StepTrace("Compare field by field", time.perf_counter() - t, f"{len(spec.mapping_rules)} mapping rules + {len(spec.new_features)} new-feature checks per payment"))
    return _finish("replay", results, trace, spec, {**(meta or {}), "new": new_adapter.describe(), "replay_seconds": round(dt, 3)})


def run_dual(requests: list[dict[str, Any]], old_adapter: Adapter, new_adapter: Adapter, spec: Spec,
             progress: Progress | None = None, meta: dict | None = None) -> RunResult:
    """AGENT 2. The SAME requests are sent to both implementations at the same time."""
    say = progress or (lambda _m: None)
    trace: list[StepTrace] = [StepTrace("Prepare identical requests", 0.0, f"{len(requests)} request(s)")]

    say("Sending the requests to the old implementation…")
    t = time.perf_counter()
    old = old_adapter.run(requests)
    trace.append(StepTrace("Run old code", time.perf_counter() - t, old_adapter.describe()))

    say("Sending the same requests to the new implementation…")
    t = time.perf_counter()
    new = new_adapter.run(requests)
    trace.append(StepTrace("Run new code", time.perf_counter() - t, new_adapter.describe()))

    say("Comparing responses…")
    t = time.perf_counter()
    results = compare_all(requests, old, new, spec)
    trace.append(StepTrace("Compare field by field", time.perf_counter() - t, f"{len(spec.mapping_rules)} mapping rules + {len(spec.new_features)} new-feature checks per payment"))
    return _finish("dual-run", results, trace, spec, {**(meta or {}), "old": old_adapter.describe(), "new": new_adapter.describe()})
