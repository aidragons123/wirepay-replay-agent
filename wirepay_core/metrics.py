"""Outcome metrics for a run: success, failure and technical-error rates.

Every payment lands in exactly one bucket, so the percentages add up to 100:
  error    - a service returned no usable answer (status neither accepted nor rejected) or an unparseable pacs.008
  failure  - the answers are usable but at least one rule shows an unexplained mismatch
  explained- differences exist but every one is an expected, documented change
  match    - identical on every rule
Success = match + explained (the rules found nothing wrong).
"""
from __future__ import annotations

from typing import Any

from .canonical import canon_new, canon_old


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def is_error(r) -> bool:
    co, cn = canon_old(r.old_response), canon_new(r.new_response)
    return co.decision == "UNKNOWN" or cn.decision == "UNKNOWN" or bool(cn.xml_error)


def compute(results: list) -> dict[str, Any]:
    total = len(results)
    err = [r for r in results if is_error(r)]
    err_ids = {r.request_id for r in err}
    match = sum(1 for r in results if r.request_id not in err_ids and r.verdict == "MATCH")
    expl = sum(1 for r in results if r.request_id not in err_ids and r.verdict == "EXPECTED_DIFFERENCE")
    fail = sum(1 for r in results if r.request_id not in err_ids and r.verdict == "MISMATCH")
    old_acc = sum(1 for r in results if canon_old(r.old_response).decision == "ACCEPTED")
    new_acc = sum(1 for r in results if canon_new(r.new_response).decision == "ACCEPTED")
    return {
        "total": total, "match": match, "explained": expl, "failure": fail, "error": len(err),
        "success": match + expl,
        "match_pct": _pct(match, total), "explained_pct": _pct(expl, total), "failure_pct": _pct(fail, total),
        "error_pct": _pct(len(err), total), "success_pct": _pct(match + expl, total),
        "old_accept_pct": _pct(old_acc, total), "new_accept_pct": _pct(new_acc, total),
        "new_pending_pct": _pct(sum(1 for r in results if canon_new(r.new_response).decision == "PENDING"), total),
        "old_reject_pct": _pct(sum(1 for r in results if canon_old(r.old_response).decision == "REJECTED"), total),
        "new_reject_pct": _pct(sum(1 for r in results if canon_new(r.new_response).decision == "REJECTED"), total),
    }
