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
    issues = []
    for i, r in enumerate(records, start=1):
        # The same requestId may appear more than once on purpose: real traffic contains re-sent payments
        # (duplicates) and payments resumed after a fraud hold. Both are replayed in order.
        rid = str(r["request"].get("requestId", "")).strip()
        if not rid:
            issues.append(f"record {i}: request has no requestId")
        if not str(r["response"].get("status", "")).strip():
            issues.append(f"record {i} ({rid or '?'}): old response has no status")
    return issues[:50]


def dump_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def parse_requests_bytes(data: bytes, filename: str) -> list[dict[str, Any]]:
    """A file of plain requests (no recorded responses): JSONL with one request object per line, or a CSV whose header
    row is the request field names."""
    text = data.decode("utf-8-sig")
    if filename.lower().endswith(".csv"):
        rows = [dict(r) for r in csv.DictReader(io.StringIO(text))]
    else:
        rows = []
        for n, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise CaptureError(f"line {n}: not valid JSON ({e.msg})") from e
                rows.append(obj.get("request", obj) if isinstance(obj, dict) else obj)
    if not rows or not all(isinstance(r, dict) for r in rows):
        raise CaptureError("no request objects found")
    for i, r in enumerate(rows, start=1):
        r.setdefault("requestId", f"UP{i:06d}")
    return rows
