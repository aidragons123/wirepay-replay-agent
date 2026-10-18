"""Persistent run history, settings and custom rules (plain files under <repo>/.wirepay).

Every run is saved in full (gzip JSON) so it can be re-opened, inspected payment by payment and compared with
any other run. On Streamlit Community Cloud the disk resets when the app restarts - use the history bundle
(export/import) to keep it.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import secrets
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compare import Check, RecordResult
from .config import REPO_ROOT
from .engine import RunResult, StepTrace
from .gate import Gate, evaluate

SCHEMA = 1


def run_to_dict(run: RunResult) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "mode": run.mode, "meta": run.meta, "counts": run.counts,
        "rule_report": run.rule_report, "patterns": run.patterns,
        "trace": [asdict(s) for s in run.trace],
        "results": [{"request_id": r.request_id, "verdict": r.verdict, "request": r.request,
                     "old_response": r.old_response, "new_response": r.new_response,
                     "checks": [asdict(c) for c in r.checks]} for r in run.results],
    }


def run_from_dict(d: dict[str, Any]) -> RunResult:
    results = [RecordResult(r["request_id"], r["verdict"], [Check(**c) for c in r["checks"]],
                            r["request"], r["old_response"], r["new_response"]) for r in d["results"]]
    return RunResult(d["mode"], results, d["rule_report"], d["patterns"],
                     [StepTrace(**s) for s in d["trace"]], d["counts"], d.get("meta", {}))


def fingerprint(run: RunResult) -> str:
    ids = sorted(r.request_id for r in run.results)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()[:12]


DEFAULT_SETTINGS: dict[str, Any] = {
    "gate": Gate().as_dict(),
    "old": {"kind": "standin", "url": "", "timeout": 30},
    "new": {"kind": "standin_gaps", "url": "", "timeout": 30},
    "baseline_id": "",
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


class Store:
    def __init__(self, home: str | Path | None = None):
        self.home = Path(home or os.environ.get("WIREPAY_HOME") or REPO_ROOT / ".wirepay")
        self.runs_dir = self.home / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ runs
    @property
    def _index(self) -> Path:
        return self.home / "index.json"

    def _read_index(self) -> list[dict[str, Any]]:
        if self._index.exists():
            try:
                return json.loads(self._index.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return self._rebuild_index()

    def _write_index(self, rows: list[dict[str, Any]]) -> None:
        seen: set[str] = set()
        rows = [r for r in rows if not (r["id"] in seen or seen.add(r["id"]))]   # one entry per run id
        tmp = self._index.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._index)

    def _rebuild_index(self) -> list[dict[str, Any]]:
        rows = []
        for f in self.runs_dir.glob("*.json.gz"):
            try:
                rows.append(json.loads(gzip.decompress(f.read_bytes()))["summary"])
            except Exception:
                continue
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        self._write_index(rows)
        return rows

    def list_runs(self) -> list[dict[str, Any]]:
        return sorted(self._read_index(), key=lambda r: r["created_at"], reverse=True)

    def save_run(self, run: RunResult, agent: str, label: str = "", notes: str = "", kind: str | None = None,
                 source: str = "", gate: Gate | None = None) -> str:
        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)
        gate = gate or Gate()
        res = evaluate(run.counts, gate)
        kind = kind or ("single" if run.counts["total"] == 1 else run.mode)
        summary = {
            "id": run_id, "created_at": now.isoformat(timespec="seconds"), "agent": agent, "mode": run.mode,
            "kind": kind, "label": label or f"Run {now.strftime('%d %b %H:%M')}", "notes": notes, "pinned": False,
            "counts": run.counts, "duration": round(sum(s.seconds for s in run.trace), 3),
            "gate": {**gate.as_dict(), "passed": res.passed, "reasons": res.reasons},
            "fingerprint": fingerprint(run), "patterns": len(run.patterns), "source": source,
            "old": run.meta.get("old", ""), "new": run.meta.get("new", ""),
        }
        payload = {"summary": summary, "run": run_to_dict(run)}
        existing = self._read_index()                      # read BEFORE writing so a rebuild cannot see the new file
        (self.runs_dir / f"{run_id}.json.gz").write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode()))
        self._write_index([summary] + existing)
        return run_id

    def load_run(self, run_id: str) -> tuple[dict[str, Any], RunResult]:
        raw = json.loads(gzip.decompress((self.runs_dir / f"{run_id}.json.gz").read_bytes()))
        return raw["summary"], run_from_dict(raw["run"])

    def update(self, run_id: str, **fields: Any) -> None:
        path = self.runs_dir / f"{run_id}.json.gz"
        raw = json.loads(gzip.decompress(path.read_bytes()))
        raw["summary"].update(fields)
        path.write_bytes(gzip.compress(json.dumps(raw, ensure_ascii=False).encode()))
        self._write_index([raw["summary"] if r["id"] == run_id else r for r in self._read_index()])

    def delete(self, run_id: str) -> None:
        (self.runs_dir / f"{run_id}.json.gz").unlink(missing_ok=True)
        self._write_index([r for r in self._read_index() if r["id"] != run_id])

    def clear(self) -> int:
        n = 0
        for f in self.runs_dir.glob("*.json.gz"):
            f.unlink()
            n += 1
        self._write_index([])
        return n

    def disk_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.runs_dir.glob("*.json.gz"))

    # ------------------------------------------------------------ settings & custom rules
    def load_settings(self) -> dict[str, Any]:
        p = self.home / "settings.json"
        try:
            return _merge(DEFAULT_SETTINGS, json.loads(p.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError):
            return _merge(DEFAULT_SETTINGS, {})

    def save_settings(self, settings: dict[str, Any]) -> None:
        (self.home / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def load_custom_rules(self) -> list[dict[str, Any]]:
        try:
            return json.loads((self.home / "custom_rules.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_custom_rules(self, rules: list[dict[str, Any]]) -> None:
        (self.home / "custom_rules.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ bundle (move history between machines)
    def export_bundle(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.runs_dir.glob("*.json.gz"):
                z.write(f, f"runs/{f.name}")
            for name in ("settings.json", "custom_rules.json"):
                if (self.home / name).exists():
                    z.write(self.home / name, name)
        return buf.getvalue()

    def import_bundle(self, data: bytes) -> int:
        added = 0
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.startswith("runs/") and name.endswith(".json.gz") and "/" not in name[5:] and ".." not in name:
                    target = self.runs_dir / name[5:]
                    if not target.exists():
                        target.write_bytes(z.read(name))
                        added += 1
            if "custom_rules.json" in z.namelist() and not (self.home / "custom_rules.json").exists():
                (self.home / "custom_rules.json").write_bytes(z.read("custom_rules.json"))
        self._rebuild_index()
        return added


_default: Store | None = None


def default_store() -> Store:
    global _default
    if _default is None:
        _default = Store()
    return _default
