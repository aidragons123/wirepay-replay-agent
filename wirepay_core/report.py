"""Export a RunResult as JSON, CSV or a single self-contained HTML evidence report."""
from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from .engine import RunResult

TITLES = {"replay": "Replay agent — recorded old traffic vs new code",
          "dual-run": "Dual-run agent — same request to old and new code"}
VERDICT_LABEL = {"MATCH": "Match", "EXPECTED_DIFFERENCE": "Expected difference", "MISMATCH": "Mismatch"}


def to_dict(run: RunResult, include_records: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {"mode": run.mode, "meta": run.meta, "counts": run.counts, "rule_report": run.rule_report,
                         "patterns": run.patterns,
                         "trace": [{"step": s.name, "seconds": round(s.seconds, 3), "detail": s.detail} for s in run.trace]}
    if include_records:
        d["records"] = [{"request_id": r.request_id, "verdict": r.verdict,
                         "checks": [c.__dict__ for c in r.checks if c.status != "MATCH"],
                         "request": r.request, "old_response": r.old_response,
                         "new_response": {k: v for k, v in r.new_response.items() if k != "pacs008"}}
                        for r in run.results]
    return d


def to_json(run: RunResult) -> str:
    return json.dumps(to_dict(run), indent=2, ensure_ascii=False)


def to_csv(run: RunResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["request_id", "verdict", "old_status", "old_error", "new_status", "new_reason",
                "rules_expected", "rules_mismatch", "categories", "explanation"])
    for r in run.results:
        w.writerow([r.request_id, r.verdict, r.old_response.get("status", ""), r.old_response.get("errorCode", ""),
                    r.new_response.get("status", ""), r.new_response.get("reasonCode", ""),
                    ";".join(c.rule_id for c in r.expected), ";".join(c.rule_id for c in r.mismatches),
                    ";".join(sorted({c.category for c in r.mismatches})),
                    " | ".join(c.explanation for c in r.mismatches or r.expected)])
    return buf.getvalue()


def to_html(run: RunResult) -> str:
    e = html.escape
    c = run.counts
    rows = "".join(
        f"<tr><td>{e(r['id'])}</td><td>{e(r['title'])}</td><td>{r['checked']}</td><td>{r['match']}</td>"
        f"<td>{r['expected']}</td><td>{r['mismatch']}</td><td class='s-{r['status']}'>{r['status']}</td></tr>"
        for r in run.rule_report)
    pats = "".join(
        f"<tr><td>{e(p['pattern_id'])}</td><td>{e(p['category'])}</td><td>{p['count']}</td>"
        f"<td>{e(', '.join(p['rules']))}</td><td>{e(p['explanation'])}</td><td>{e(p['fix'])}</td>"
        f"<td>{e(', '.join(p['examples'][:4]))}</td></tr>" for p in run.patterns) or \
        "<tr><td colspan='7'>No mismatches.</td></tr>"
    steps = "".join(f"<tr><td>{e(s.name)}</td><td>{s.seconds:.3f}s</td><td>{e(s.detail)}</td></tr>" for s in run.trace)
    mism = "".join(
        f"<tr><td>{e(r.request_id)}</td><td>{e('; '.join(f'{x.rule_id}: {x.old} → {x.new}' for x in r.mismatches))}</td>"
        f"<td>{e(' | '.join(x.explanation for x in r.mismatches))}</td></tr>"
        for r in run.results if r.verdict == "MISMATCH")[:200_000]
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Wire payment migration report</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;color:#16233b;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#f7f8f5}}
h1{{font-size:1.5rem;margin-bottom:.2rem}} h2{{margin-top:2rem;font-size:1.1rem}} .sub{{color:#6b7280}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:1rem 0}} .k{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:10px 16px;min-width:130px}}
.k b{{display:block;font-size:1.5rem}} table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
th,td{{border:1px solid #e3e6ea;padding:6px 9px;text-align:left;vertical-align:top}} th{{background:#eef0f3}}
.s-VALIDATED{{color:#0a6b0a;font-weight:600}} .s-INVALIDATED{{color:#a52323;font-weight:600}} .s-UNTESTED{{color:#6b7280}}
</style>
<h1>{e(TITLES.get(run.mode, run.mode))}</h1>
<div class="sub">Generated {e(str(run.meta.get('finished_at', '')))} · spec {e(str(run.meta.get('spec', '')))}</div>
<div class="kpis">
<div class="k"><b>{c['total']}</b>payments</div><div class="k"><b>{c['match']}</b>exact match</div>
<div class="k"><b>{c['expected']}</b>expected difference</div><div class="k"><b>{c['mismatch']}</b>mismatch</div>
<div class="k"><b>{c['parity_pct']}%</b>parity</div></div>
<h2>Rule-by-rule verdict</h2><table><tr><th>Rule</th><th>What it checks</th><th>Checked</th><th>Match</th><th>Expected</th><th>Mismatch</th><th>Verdict</th></tr>{rows}</table>
<h2>Mismatch patterns</h2><table><tr><th>#</th><th>Category</th><th>Payments</th><th>Rules</th><th>What happens</th><th>Suggested fix</th><th>Examples</th></tr>{pats}</table>
<h2>Mismatched payments</h2><table><tr><th>Payment</th><th>Fields</th><th>Why</th></tr>{mism or '<tr><td colspan="3">None.</td></tr>'}</table>
<h2>Run trace</h2><table><tr><th>Step</th><th>Time</th><th>Detail</th></tr>{steps}</table>
<p class="sub">Verdicts come from deterministic comparison. "Expected" differences are re-derived independently (IBAN checksum, TARGET2 calendar, name length), never taken on trust from the new code.</p>
</html>"""
