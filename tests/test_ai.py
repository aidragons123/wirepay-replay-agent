"""The AI analyst: prompts carry the engine's facts, privacy masking works, drafts are validated. No network is used."""
import shutil
from pathlib import Path

import pytest

from wirepay_core import ai
from wirepay_core.config import load_spec
from wirepay_core.engine import run_dual
from wirepay_core.generator import generate_requests
from wirepay_core.runtime import standin_adapters
from wirepay_core.store import Store

ROOT = Path(__file__).resolve().parents[1]
needs_jdk = pytest.mark.skipif(shutil.which("javac") is None, reason="needs a JDK")


@pytest.fixture(autouse=True)
def stub():
    calls = []

    def backend(system, messages, model, max_tokens):
        calls.append({"system": system, "messages": messages, "model": model})
        return "STUB ANSWER"

    ai.set_backend(backend)
    yield calls
    ai.set_backend(None)


@pytest.fixture(scope="module")
def run():
    reqs, _ = generate_requests(300, 5, "2026-10-19")
    old, new, _ = standin_adapters(ROOT, False)
    return run_dual(reqs, old, new, load_spec())


def test_iban_masking_keeps_ends_only():
    assert ai.mask_text("DE89370400440532013000") == "DE89…00"
    assert ai.mask({"a": ["NL13ABNA0321166841"], "n": 5}) == {"a": ["NL13…41"], "n": 5}
    assert ai.mask("NL13ABNA0321166841", on=False) == "NL13ABNA0321166841"


def test_source_sent_to_the_model_has_no_annotations():
    code = ai.new_service_code(ROOT)
    assert "PARITY-GAP" not in code and "//" not in code.replace("http://", "")
    assert "RoundingMode" in code


def test_rule_drafts_are_validated():
    ok = ai.parse_rule('Here: {"title":"Remittance carried over","field":"remittance","compare":"exact","applies":"both_accepted"}')
    assert ok["field"] == "remittance"
    for bad in ('{"title":"x","field":"nonsense","compare":"exact","applies":"always"}', "no json here",
                '{"title":"x","field":"fee","compare":"fuzzy","applies":"always"}', '{"error":"too vague"}'):
        with pytest.raises(ai.AIError):
            ai.parse_rule(bad)


def test_no_key_and_no_backend_fails_with_direction():
    ai.set_backend(None)
    with pytest.raises(ai.AIError, match="API key"):
        ai.complete("s", [{"role": "user", "content": "q"}], api_key="")


@needs_jdk
def test_payment_prompt_carries_verdict_rules_and_masks_accounts(run, stub):
    r = run.by_verdict("MISMATCH")[0]
    assert ai.explain_payment(r, api_key="k", model="m", do_mask=True) == "STUB ANSWER"
    body = stub[0]["messages"][0]["content"]
    assert r.request_id in body and "MISMATCH" in body
    assert r.request["debtorAccount"] not in body and ai.mask_text(r.request["debtorAccount"]) in body
    assert "Never contradict" in stub[0]["system"] and stub[0]["model"] == "m"


@needs_jdk
def test_fix_prompt_includes_code_and_pattern(run, stub):
    p = run.patterns[0]
    ex = [r for r in run.results if r.request_id in set(p["examples"])]
    ai.suggest_fix(p, ex, ai.new_service_code(ROOT), api_key="k")
    body = stub[0]["messages"][0]["content"]
    assert p["pattern_id"] in body and "WirePaymentProcessor" in body and "PARITY-GAP" not in body


@needs_jdk
def test_brief_and_ask_use_run_facts_and_keep_history(run, stub, tmp_path):
    sm = Store(tmp_path).load_run(Store(tmp_path).save_run(run, "dualrun", "t"))[0]
    ai.release_brief(sm, run, api_key="k")
    assert "NO-GO" in stub[0]["messages"][0]["content"] or "false" in stub[0]["messages"][0]["content"]
    ai.answer("What first?", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], sm, run, api_key="k")
    assert [m["role"] for m in stub[1]["messages"]] == ["user", "assistant", "user"]
    assert "RUN FACTS" in stub[1]["system"] and run.patterns[0]["pattern_id"] in stub[1]["system"]


def test_api_errors_show_anthropic_message_and_fix(monkeypatch):
    import types

    import anthropic
    ai.set_backend(None)

    def boom(status, message):
        resp = types.SimpleNamespace(status_code=status, headers={}, request=None)
        err = anthropic.BadRequestError(message, response=resp, body={"type": "error", "error": {"message": message}})

        class Client:
            def __init__(self, **kw):
                self.messages = self

            def create(self, **kw):
                raise err

        monkeypatch.setattr(anthropic, "Anthropic", Client)

    boom(400, "Your credit balance is too low to access the Anthropic API.")
    with pytest.raises(ai.AIError) as e:
        ai.complete("s", [{"role": "user", "content": "q"}], api_key="k")
    assert "credit balance is too low" in str(e.value) and "Plans & Billing" in str(e.value) and "400" in str(e.value)


def test_workspace_id_is_sent_as_header_and_error_hint(monkeypatch):
    import types

    import anthropic
    ai.set_backend(None)
    seen = {}

    class Client:
        def __init__(self, **kw):
            seen.update(kw)
            self.messages = self

        def create(self, **kw):
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="OK")])

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    assert ai.complete("s", [{"role": "user", "content": "q"}], api_key="k", workspace_id=" wrkspc_123 ") == "OK"
    assert seen["default_headers"] == {"anthropic-workspace-id": "wrkspc_123"}
    ai.complete("s", [{"role": "user", "content": "q"}], api_key="k")
    assert seen["default_headers"] is None
    msg = ai._explain_status(types.SimpleNamespace(status_code=400, body={"error": {"message": "This API key is not scoped to a workspace"}}))
    assert "workspace ID" in msg
