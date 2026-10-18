#!/usr/bin/env python3
"""Replay agent CLI.

  python run_replay.py sample [--n 1000] [--seed 7] [--date 2026-10-19]
        Synthesise a day of 'production' traffic by running the stand-in OLD service,
        and write it as a capture file (only needed for the demo).

  python run_replay.py replay [--capture FILE] [--parity-fix] [--out out]
        Feed every recorded request to the NEW code, compare with the recorded OLD
        responses, and write report.html / report.csv / report.json.
        Exit code 1 if any payment mismatches (so it can gate a pipeline).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wirepay_core import capture, report  # noqa: E402
from wirepay_core.config import load_agent_config, load_spec  # noqa: E402
from wirepay_core.engine import run_replay  # noqa: E402
from wirepay_core.generator import generate_requests  # noqa: E402
from wirepay_core.runtime import adapters_from_config, standin_adapters  # noqa: E402


def cmd_sample(a) -> int:
    old, _, notes = standin_adapters(ROOT)
    reqs, _ = generate_requests(a.n, a.seed, a.date)
    resps = old.run(reqs)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(capture.dump_jsonl([{"request": q, "response": r} for q, r in zip(reqs, resps)]), encoding="utf-8")
    print(f"wrote {len(reqs)} recorded payments -> {out}")
    return 0


def cmd_replay(a) -> int:
    cfg = load_agent_config(a.config)
    if a.parity_fix:
        cfg.setdefault("new", {"type": "standin"})["parity_fix"] = True
    _, new, notes = adapters_from_config(cfg, ROOT)
    for n in notes:
        print("note:", n)
    cap_path = Path(a.capture or cfg.get("capture", "data/sample_capture_1000.jsonl"))
    if not cap_path.is_absolute():
        cap_path = ROOT / cap_path
    records = capture.load(cap_path)
    problems = capture.validate(records)
    if problems:
        print("capture problems:\n  " + "\n  ".join(problems))
        return 2
    run = run_replay(records, new, load_spec(a.spec), meta={"capture": cap_path.name})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.to_html(run), encoding="utf-8")
    (out / "report.csv").write_text(report.to_csv(run), encoding="utf-8")
    (out / "report.json").write_text(report.to_json(run), encoding="utf-8")

    c = run.counts
    print(f"\nReplayed {c['total']} recorded payments through the new code")
    print(f"  exact match          {c['match']}")
    print(f"  expected differences {c['expected']}   (documented new features, independently verified)")
    print(f"  MISMATCHES           {c['mismatch']}")
    print(f"  parity               {c['parity_pct']}%\n")
    for r in run.rule_report:
        mark = {"VALIDATED": "ok  ", "INVALIDATED": "FAIL", "UNTESTED": "n/a "}[r["status"]]
        print(f"  [{mark}] {r['id']}  {r['title']:<42} checked {r['checked']:>5}  expected {r['expected']:>4}  mismatch {r['mismatch']:>4}")
    for p in run.patterns:
        print(f"\n  {p['pattern_id']} {p['category']} - {p['count']} payment(s), rules {', '.join(p['rules'])}")
        print(f"      {p['explanation']}\n      fix: {p['fix']}\n      e.g. {', '.join(p['examples'][:4])}")
    print(f"\nReports written to {out}/")
    return 1 if (c["mismatch"] and not a.no_fail) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=1000)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--date", default="2026-10-19")
    s.add_argument("--out", default=str(ROOT / "data" / "sample_capture_1000.jsonl"))
    s.set_defaults(fn=cmd_sample)
    r = sub.add_parser("replay")
    r.add_argument("--config", default=str(ROOT / "agent.yaml"))
    r.add_argument("--spec", default=None)
    r.add_argument("--capture", default=None)
    r.add_argument("--parity-fix", action="store_true", help="stand-in only: run the new code with the planted gaps fixed")
    r.add_argument("--out", default=str(ROOT / "out"))
    r.add_argument("--no-fail", action="store_true", help="exit 0 even when there are mismatches")
    r.set_defaults(fn=cmd_replay)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
