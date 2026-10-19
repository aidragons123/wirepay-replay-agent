"""Streamlit pieces for the AI analyst. The rules decide verdicts; these only add explanations."""
from __future__ import annotations

import os
from typing import Any, Callable

import streamlit as st

from . import ai


def _secret() -> str:
    try:
        return str(st.secrets.get("ANTHROPIC_API_KEY", ""))
    except Exception:                                  # no secrets file configured
        return ""


def api_key() -> str:
    return st.session_state.get("ai_key") or _secret() or os.environ.get("ANTHROPIC_API_KEY", "")


def _workspace(saved: str = "") -> str:
    try:
        sec = str(st.secrets.get("ANTHROPIC_WORKSPACE_ID", ""))
    except Exception:
        sec = ""
    return (saved or sec or os.environ.get("ANTHROPIC_WORKSPACE_ID", "")).strip()


def options(ctx) -> dict[str, Any]:
    s = ctx.settings.get("ai", {})
    return {"model": s.get("model") or ai.DEFAULT_MODEL, "do_mask": bool(s.get("mask", True)),
            "workspace_id": _workspace(s.get("workspace_id", ""))}


def ready() -> bool:
    return bool(api_key()) or ai._backend is not None


def _cache() -> dict[str, str]:
    return st.session_state.setdefault("ai_cache", {})


def _need_key() -> None:
    st.info("The AI analyst needs an Anthropic API key. Add it under Settings, AI assistant. Everything else works without it.")


def _answer_box(text: str, model: str) -> None:
    with st.container(border=True):
        st.markdown(text)
        st.caption(f"Written by Claude ({model}). The verdict and the gate come from the rules, not from the AI.")


def _generate(key: str, label: str, fn: Callable[[], str], model: str, button_key: str, primary: bool = False) -> None:
    """One button + cached result. Re-asking replaces the cached answer."""
    cache = _cache()
    c1, c2 = st.columns([1, 3])
    clicked = c1.button(label if key not in cache else "Ask again", key=button_key, type="primary" if primary and key not in cache else "secondary")
    if clicked:
        try:
            with st.spinner("Claude is reading the results…"):
                cache[key] = fn()
        except ai.AIError as exc:
            st.error(str(exc))
    if key in cache:
        _answer_box(cache[key], model)


# ------------------------------------------------------------------ per feature
def payment_explain(ctx, sm: dict, r) -> None:
    if not ready():
        return _need_key()
    o = options(ctx)
    _generate(f"pay:{sm['id']}:{r.request_id}", "Explain with AI",
              lambda: ai.explain_payment(r, api_key=api_key(), **o), o["model"], f"ai_pay_{r.request_id}")


def pattern_fix(ctx, sm: dict, run, p: dict) -> None:
    if not ready():
        return _need_key()
    o = options(ctx)
    code = ai.new_service_code(ctx.root)
    with st.expander("Code sent to Claude with this request"):
        if code:
            st.caption("The bundled new service, with all comments removed so the model finds the cause from the logic. "
                       "Paste your own code to replace it.")
        mine = st.text_area("Your new-service code (optional)", key=f"ai_code_{p['pattern_id']}", height=120,
                            placeholder="Paste the method that handles this rule. Leave empty to use the bundled code." if code else
                            "Paste the code that handles this rule. Without it the answer describes the change in words.")
    use = mine.strip() or code
    ex_ids = set(p["examples"])
    examples = [r for r in run.results if r.request_id in ex_ids][:3]
    _generate(f"fix:{sm['id']}:{p['pattern_id']}:{bool(mine.strip())}", "Suggest a fix with AI",
              lambda: ai.suggest_fix(p, examples, use, api_key=api_key(), **o), o["model"], f"ai_fix_{p['pattern_id']}")


def brief(ctx, sm: dict, run) -> None:
    if not ready():
        return _need_key()
    o = options(ctx)
    _generate(f"brief:{sm['id']}", "Write the release brief", lambda: ai.release_brief(sm, run, api_key=api_key(), **o),
              o["model"], "ai_brief", primary=True)


def ask(ctx, sm: dict, run) -> None:
    if not ready():
        return _need_key()
    o = options(ctx)
    hist = st.session_state.setdefault("ai_chat", {}).setdefault(sm["id"], [])
    if not hist:
        st.caption("Try: “Which rule causes most of the failures?”  ·  “Are the IBAN differences a problem?”  ·  “What should I fix first?”")
    for m in hist:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    q = st.chat_input("Ask about this run")
    if q:
        with st.chat_message("user"):
            st.markdown(q)
        try:
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    a = ai.answer(q, hist, sm, run, api_key=api_key(), **o)
                st.markdown(a)
            hist += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        except ai.AIError as exc:
            st.error(str(exc))
    if hist and st.button("Clear conversation", key="ai_clear"):
        hist.clear()
        st.rerun()
    st.caption(f"Answers come from this run's facts and are written by Claude ({o['model']}). They never change a verdict.")


def rule_from_text(ctx) -> None:
    st.markdown("**Describe a rule in plain English**")
    if not ready():
        return _need_key()
    o = options(ctx)
    text = st.text_input("Requirement", key="ai_rule_text", placeholder="The remittance text must be carried over unchanged for accepted payments")
    if st.button("Draft the rule with AI", key="ai_rule_go", disabled=not text.strip()):
        try:
            with st.spinner("Drafting…"):
                st.session_state["ai_rule_draft"] = ai.draft_rule(text, api_key=api_key(), model=o["model"], workspace_id=o["workspace_id"])
        except ai.AIError as exc:
            st.session_state.pop("ai_rule_draft", None)
            st.error(str(exc))
    d = st.session_state.get("ai_rule_draft")
    if d:
        with st.container(border=True):
            st.markdown(f"**{d['title']}**")
            st.caption(f"Field `{d['field']}` · compared as `{d['compare']}` · applies when {d['applies'].replace('_', ' ')}")
            a, b, _ = st.columns([1, 1, 3])
            if a.button("Add this rule", type="primary", key="ai_rule_add"):
                custom = ctx.store.load_custom_rules()
                rid = f"C-{len(custom) + 1:03d}"
                custom.append({"id": rid, **d, "old_ref": d["field"], "new_ref": d["field"]})
                ctx.store.save_custom_rules(custom)
                st.session_state.pop("ai_rule_draft")
                st.success(f"Added {rid}. It applies from the next run.")
            if b.button("Discard", key="ai_rule_no"):
                st.session_state.pop("ai_rule_draft")
                st.rerun()
        st.caption("Drafted by Claude and checked against the fields and comparisons the engine supports. Review it before adding.")


def settings_panel(ctx) -> None:
    s = ctx.settings
    ai_s = s.get("ai", {"model": "", "mask": True})
    st.write("Claude explains results, suggests fixes, writes the release brief and drafts rules. The rule engine still decides every "
             "verdict and the gate; the AI cannot change them.")
    with st.form("ai_form"):
        key = st.text_input("Anthropic API key", st.session_state.get("ai_key", ""), type="password",
                            help="Kept for this browser session only. On Streamlit Cloud you can instead add ANTHROPIC_API_KEY under the app's Secrets.")
        model = st.text_input("Model", ai_s.get("model", ""), placeholder=ai.DEFAULT_MODEL, help="Leave empty for the default.")
        wsid = st.text_input("Workspace ID (only if your key is not tied to a workspace)", ai_s.get("workspace_id", ""),
                             placeholder="wrkspc_…", help="Needed when the Console key was created for the whole organization. "
                             "Find it in the Claude Console under Workspaces. Not a secret like the key, but keep it private.")
        mk = st.toggle("Hide account numbers (IBANs) before sending", value=bool(ai_s.get("mask", True)),
                       help="Replaces each IBAN with its first four and last two characters. Names and amounts are still sent.")
        if st.form_submit_button("Save", type="primary"):
            st.session_state["ai_key"] = key.strip()
            s["ai"] = {"model": model.strip(), "mask": mk, "workspace_id": wsid.strip()}
            ctx.store.save_settings(s)
            st.success("Saved.")
    src = "session key" if st.session_state.get("ai_key") else "app secret" if _secret() else "environment" if os.environ.get("ANTHROPIC_API_KEY") else ""
    st.caption(f"Status: {'ready, using the ' + src if ready() and src else 'no API key set'}.")
    if ready() and st.button("Test the connection"):
        try:
            with st.spinner("Calling the model…"):
                o = options(ctx)
                ai.complete("Reply with the single word OK.", [{"role": "user", "content": "ping"}], api_key=api_key(),
                            model=o["model"], max_tokens=10, workspace_id=o["workspace_id"])
            st.success("Connected.")
        except ai.AIError as exc:
            st.error(str(exc))
    st.warning("What is sent to Anthropic: the facts of the payment or run you ask about (requests, responses, rule results) and, "
               "for fix suggestions, the new-service code. Use this only with data you are allowed to share, such as test data.")
