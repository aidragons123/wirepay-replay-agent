"""Recorded old-system traffic: load, validate and (for the demo) synthesise a day of it."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable


class CaptureError(ValueError):
    pass


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    """One JSON object per line: {"request": {...}, "response": {...}}. `old_response` is accepted for `response`."""
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise CaptureError(f"line {n}: not valid JSON ({e.msg})") from e
        resp = obj.get("response", obj.get("old_response"))
        if not isinstance(obj.get("request"), dict) or not isinstance(resp, dict):
            raise CaptureError(f"line {n}: needs a 'request' object and a 'response' object")
        out.append({"request": obj["request"], "response": resp})
    return out


def parse_csv(text: str) -> list[dict[str, Any]]:
    """Columns prefixed req_ (request fields) and resp_ (the old system's response fields)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and not any(k.startswith("req_") for k in rows[0]):
        raise CaptureError("CSV needs columns prefixed req_ and resp_ (e.g. req_requestId, resp_status)")
    out = []
    for r in rows:
        out.append({"request": {k[4:]: v for k, v in r.items() if k.startswith("req_")},
                    "response": {k[5:]: v for k, v in r.items() if k.startswith("resp_")}})
    return out


def load(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    return parse_csv(text) if p.suffix.lower() == ".csv" else parse_jsonl(text)


def parse_bytes(data: bytes, filename: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    return parse_csv(text) if filename.lower().endswith(".csv") else parse_jsonl(text)


def validate(records: Iterable[dict[str, Any]]) -> list[str]:
    """Human-readable problems with a capture (empty list = fine)."""
    issues, seen = [], set()
    for i, r in enumerate(records, start=1):
        rid = str(r["request"].get("requestId", "")).strip()
        if not rid:
            issues.append(f"record {i}: request has no requestId")
        elif rid in seen:
            issues.append(f"record {i}: duplicate requestId {rid}")
        seen.add(rid)
        if not str(r["response"].get("status", "")).strip():
            issues.append(f"record {i} ({rid or '?'}): old response has no status")
    return issues[:50]


def dump_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
