"""The AI analyst: Claude explains results and suggests fixes. It never decides a verdict.

Every verdict (exact match / explained difference / mismatch) and the GO / NO-GO gate come from the rule engine.
Claude only receives the facts the engine produced and writes explanations, fix suggestions, briefs and draft rules.
No code here is imported unless the AI features are used, and nothing is sent anywhere without an API key.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from .compare import RecordResult
from .engine import RunResult

DEFAULT_MODEL = os.environ.get("WIREPAY_AI_MODEL", "claude-sonnet-5-5")
RULE_FIELDS = ["payment_id", "amount", "currency", "fee", "settlement_date", "debtor_name", "creditor_name", "debtor_account",
               "creditor_account", "creditor_bic", "charge_bearer", "remittance"]
RULE_COMPARES = ["exact", "decimal", "date", "name", "bearer"]
RULE_APPLIES = ["both_accepted", "both_rejected", "always"]

SYSTEM = (
    "You are the analysis assistant inside a tool that tests a migration of wire-payment creation from an old Java 8 service "
    "(flat model, no workflow) to a new Java 18 service (workflow, ISO 20022 pacs.008). A deterministic rule engine has already "
    "decided every verdict: exact match, explained difference (a documented new feature, independently verified) or mismatch. "
    "Never contradict or re-decide a verdict or the release gate. Use only the facts you are given; if they do not support a "
    "claim, say what is unknown. Cite rule ids such as M-007 and payment ids when you refer to them. Write plainly for an "
    "engineer or business analyst: short paragraphs or short bullets, no preamble, no closing offers."
)


class AIError(RuntimeError):
    """A problem the user can act on (no key, bad key, rate limit, network)."""


# ---------------------------------------------------------------- transport
_backend: Callable[..., str] | None = None


def set_backend(fn: Callable[..., str] | None) -> None:
    """Test seam: replace the network call. Never used by the app itself."""
    global _backend
    _backend = fn


def complete(system: str, messages: list[dict[str, str]], *, api_key: str, model: str = "", max_tokens: int = 900) -> str:
    model = model or DEFAULT_MODEL
    if _backend is not None:
        return _backend(system=system, messages=messages, model=model, max_tokens=max_tokens)
    if not api_key:
        raise AIError("No API key. Add your Anthropic API key under Settings, AI assistant.")
    try:
        import anthropic
    except ImportError as exc:                                              # pragma: no cover
        raise AIError("The 'anthropic' package is not installed. Run: pip install anthropic") from exc
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=90.0)
        msg = client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
    except anthropic.AuthenticationError as exc:
        raise AIError("Anthropic rejected the API key. Check it under Settings, AI assistant.") from exc
    except anthropic.NotFoundError as exc:
        raise AIError(f"The model “{model}” was not found for this key. Change the model under Settings, AI assistant.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Rate limit reached. Wait a moment and try again.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Could not reach the Anthropic API. Check the network connection.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(_explain_status(exc)) from exc
    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    if not text:
        raise AIError("The model returned an empty answer. Try again.")
    return text


def _explain_status(exc: Any) -> str:
    """Say what Anthropic actually said, plus the usual fix, instead of a bare status code."""
    detail = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        detail = str(err.get("message", "")) if isinstance(err, dict) else ""
    detail = (detail or getattr(exc, "message", "") or str(exc)).strip()[:300]
    low = detail.lower()
    hint = ""
    if "credit balance" in low or "billing" in low:
        hint = " Add credit under Plans & Billing in the Claude Console, then try again."
    elif "model" in low:
        hint = " Clear the Model box in Settings, AI assistant, or enter a model your key can use."
    elif "max_tokens" in low or "too long" in low or "context" in low:
        hint = " The request was too large. Try a smaller run."
    return f"Anthropic API error {getattr(exc, 'status_code', '')}: {detail}{hint}"


# ---------------------------------------------------------------- privacy
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")


def mask_text(s: str) -> str:
    return _IBAN.sub(lambda m: f"{m.group(0)[:4]}…{m.group(0)[-2:]}", s)


def mask(obj: Any, on: bool = True) -> Any:
    """Hide account numbers (IBANs) before anything leaves the machine. Names are left in; turn masking off only for test data."""
    if not on:
        return obj
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask(v, on) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v, on) for v in obj]
    return obj


# ---------------------------------------------------------------- code context
_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"^\s*//.*$", re.M)


def strip_java_comments(src: str) -> str:
    """Send code, not our own annotations: the model must find the cause from the logic itself."""
    src = _BLOCK.sub("", src)
    src = _LINE.sub("", src)
    return re.sub(r"\n{3,}", "\n\n", src).strip()


def new_service_code(root: Path, limit: int = 14000) -> str:
    p = root / "java" / "new" / "src" / "com" / "bank" / "wire" / "modern" / "WirePaymentProcessor.java"
    try:
        return strip_java_comments(p.read_text(encoding="utf-8"))[:limit]
    except OSError:
        return ""


# ---------------------------------------------------------------- prompts
def _checks(r: RecordResult) -> list[dict[str, str]]:
    return [{"rule": c.rule_id, "title": c.title, "status": c.status, "old": c.old, "new": c.new, "engine_explanation": c.explanation}
            for c in r.checks if c.status != "MATCH"]


def payment_prompt(r: RecordResult, do_mask: bool = True) -> str:
    facts = {"payment": r.request_id, "verdict": r.verdict, "request": r.request, "old_response": r.old_response,
             "new_response": {k: v for k, v in r.new_response.items() if k != "pacs008"}, "differing_checks": _checks(r)}
    return ("Explain this payment result.\n- Say in two or three sentences why old and new differ.\n- Say whether that is expected "
            "and why, using the verdict as given.\n- If it is a mismatch, name the most likely cause in the new code's behaviour.\n\n"
            f"FACTS (JSON):\n{json.dumps(mask(facts, do_mask), ensure_ascii=False, indent=1)[:9000]}")


def pattern_prompt(p: dict[str, Any], examples: list[RecordResult], code: str, do_mask: bool = True) -> str:
    facts = {"pattern": {k: p[k] for k in ("pattern_id", "category", "count", "rules", "explanation")},
             "examples": [{"payment": e.request_id, "request": e.request, "old_status": e.old_response.get("status"),
                           "new_status": e.new_response.get("status"), "differing_checks": _checks(e)} for e in examples[:3]]}
    body = ("Find the root cause of this mismatch pattern and propose the fix.\n1. Root cause in one or two sentences.\n"
            "2. The exact change to make, as a short before/after code snippet when code is provided.\n3. How to confirm the fix "
            "(which rule should turn to match, and on which example).\n")
    if code:
        body += f"\nNEW SERVICE CODE (comments removed):\n```java\n{code}\n```\n"
    else:
        body += "\nNo source code was provided, so describe the change in words and say which code area to look at.\n"
    return body + f"\nFACTS (JSON):\n{json.dumps(mask(facts, do_mask), ensure_ascii=False, indent=1)[:9000]}"


def run_context(sm: dict[str, Any], run: RunResult, do_mask: bool = True, examples: int = 6) -> dict[str, Any]:
    rules = [{k: r[k] for k in ("id", "title", "kind", "checked", "match", "expected", "mismatch", "status")}
             for r in run.rule_report if r["mismatch"] or r["expected"]]
    ex = [{"payment": r.request_id, "checks": _checks(r)} for r in run.by_verdict("MISMATCH")[:examples]]
    return mask({"run": sm["label"], "kind": sm["kind"], "notes": sm.get("notes", ""), "counts": run.counts,
                 "gate": {"passed": sm["gate"]["passed"], "max_mismatches": sm["gate"]["max_mismatches"],
                          "min_parity_pct": sm["gate"]["min_parity_pct"], "reasons": sm["gate"]["reasons"]},
                 "rules_with_differences": rules,
                 "mismatch_patterns": [{k: p[k] for k in ("pattern_id", "category", "count", "rules", "explanation", "fix")} for p in run.patterns],
                 "example_mismatches": ex, "old": sm.get("old") or "recorded traffic", "new": sm.get("new", "")}, do_mask)


def brief_prompt(ctx: dict[str, Any]) -> str:
    return ("Write a release-readiness brief for a delivery manager, under 220 words, with these four short headed parts:\n"
            "**Decision** (state the gate result exactly as given and the one number behind it)\n**Expected changes** (new behaviour "
            "that shows as explained differences, in plain words)\n**Problems** (each mismatch pattern: what is wrong, how many "
            "payments, which rules)\n**Next step** (the one action that most changes the outcome)\n\n"
            f"FACTS (JSON):\n{json.dumps(ctx, ensure_ascii=False, indent=1)[:12000]}")


def ask_system(ctx: dict[str, Any]) -> str:
    return (SYSTEM + "\n\nYou are answering questions about ONE test run. Its facts follow. If the answer is not in them, say so and "
            "say which page of the app (Payments, Rules, Run history) would show it.\n\nRUN FACTS (JSON):\n"
            + json.dumps(ctx, ensure_ascii=False)[:14000])


def rule_prompt(description: str) -> str:
    return ("Turn this plain-English requirement into ONE field-comparison rule for the tool. Reply with a single JSON object and "
            "nothing else, with exactly these keys:\n"
            f'{{"title": short sentence, "field": one of {RULE_FIELDS}, "compare": one of {RULE_COMPARES} '
            '(exact = identical text, decimal = same number, date = same day, name = tolerates the new 140-character limit, '
            f'bearer = through the charge-bearer map), "applies": one of {RULE_APPLIES}}}\n'
            'If the requirement cannot be expressed this way, reply {"error": "<one sentence why>"}.\n\n'
            f"REQUIREMENT: {description.strip()[:600]}")


def parse_rule(text: str) -> dict[str, str]:
    """Validate the model's draft: only values the engine understands get through."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("The model did not return a rule. Try rewording the requirement.")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise AIError("The model's rule was not valid JSON. Try again.") from exc
    if "error" in d:
        raise AIError(f"That cannot be written as a field rule: {d['error']}")
    title = str(d.get("title", "")).strip()
    if not title or d.get("field") not in RULE_FIELDS or d.get("compare") not in RULE_COMPARES or d.get("applies") not in RULE_APPLIES:
        raise AIError("The draft used a field or comparison the engine does not support. Try rewording the requirement.")
    return {"title": title[:120], "field": d["field"], "compare": d["compare"], "applies": d["applies"]}


# ---------------------------------------------------------------- high-level calls
def explain_payment(r: RecordResult, **kw: Any) -> str:
    return complete(SYSTEM, [{"role": "user", "content": payment_prompt(r, kw.pop("do_mask", True))}], **kw)


def suggest_fix(p: dict[str, Any], examples: list[RecordResult], code: str, **kw: Any) -> str:
    return complete(SYSTEM, [{"role": "user", "content": pattern_prompt(p, examples, code, kw.pop("do_mask", True))}], max_tokens=1100, **kw)


def release_brief(sm: dict[str, Any], run: RunResult, **kw: Any) -> str:
    return complete(SYSTEM, [{"role": "user", "content": brief_prompt(run_context(sm, run, kw.pop("do_mask", True)))}], max_tokens=700, **kw)


def answer(question: str, history: list[dict[str, str]], sm: dict[str, Any], run: RunResult, **kw: Any) -> str:
    msgs = [m for m in history[-8:] if m["role"] in ("user", "assistant")] + [{"role": "user", "content": question}]
    return complete(ask_system(run_context(sm, run, kw.pop("do_mask", True))), msgs, **kw)


def draft_rule(description: str, **kw: Any) -> dict[str, str]:
    kw.pop("do_mask", None)
    return parse_rule(complete(SYSTEM, [{"role": "user", "content": rule_prompt(description)}], max_tokens=300, **kw))
