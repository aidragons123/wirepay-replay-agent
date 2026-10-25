"""Shared Streamlit components for both agents (imported lazily - Streamlit is not needed for the CLI)."""
from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from typing import Any

import pandas as pd
import streamlit as st

from . import report
from .brand import Agent
from . import explain
from .compare import RecordResult
from .engine import RunResult

INK, MUTED, LINE, CANVAS = "#16203A", "#667289", "#DDE3EC", "#F4F6FA"
GREEN, GREEN_BG = "#177A4F", "#E6F4EC"
SLATE, SLATE_BG = "#44607F", "#E8EEF5"
RED, RED_BG = "#B8322A", "#FBE9E7"

VERDICT = {   # icon + word + colour, so meaning never depends on colour alone
    "MATCH": ("✓", "Exact match", GREEN, GREEN_BG),
    "EXPECTED_DIFFERENCE": ("≈", "Explained difference", SLATE, SLATE_BG),
    "MISMATCH": ("✕", "Mismatch", RED, RED_BG),
}
RULE_STATUS = {"VALIDATED": "✓ Validated", "INVALIDATED": "✕ Invalidated", "UNTESTED": "– Not exercised"}
CATEGORY_LABEL = {
    "IMPLEMENTATION_DEFECT": "Implementation defect", "ROUNDING_MODE": "Rounding mode",
    "REASON_CODE": "Reason-code mapping", "NEW_FEATURE_DEFECT": "New feature misbehaves",
    "UNEXPLAINED": "Unexplained difference", "EXPECTED_ENHANCEMENT": "Expected (new feature)",
}


def esc(s: Any) -> str:
    return html.escape(str(s))


def css(agent: Agent) -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root {{ --accent:{agent.accent}; --accent-soft:{agent.accent_soft}; --ink:{INK}; --muted:{MUTED}; --line:{LINE}; }}
html, body, .stApp, .stMarkdown, p, label, input, textarea, button {{ font-family:'IBM Plex Sans',system-ui,sans-serif; }}
.stApp {{ background:{CANVAS}; }}
#MainMenu, footer, [data-testid="stDecoration"] {{ visibility:hidden; }}
.block-container {{ padding:2.6rem 2.4rem 4rem; max-width:1280px; }}
h1,h2,h3 {{ color:var(--ink); letter-spacing:-.01em; }}

/* sidebar */
[data-testid="stSidebar"] {{ background:{agent.sidebar}; }}
[data-testid="stSidebar"] * {{ color:#D6DEEF; }}
[data-testid="stSidebarNav"]::before {{ content:"{agent.glyph}  {agent.name}"; display:block; padding:1.1rem 1.2rem .5rem;
   font-weight:700; font-size:1.25rem; color:#fff; letter-spacing:-.01em; }}
[data-testid="stSidebarNav"] a {{ border-radius:8px; margin:1px 8px; padding:.3rem .7rem; }}
[data-testid="stSidebarNav"] a:hover {{ background:{agent.sidebar_raised}; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background:{agent.sidebar_raised}; box-shadow:inset 3px 0 0 #fff; }}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{ color:#fff; font-weight:600; }}
[data-testid="stSidebarNavSeparator"] {{ display:none; }}
.sb-card {{ background:{agent.sidebar_raised}; border-radius:10px; padding:.75rem .9rem; margin:.4rem .6rem; font-size:.84rem; line-height:1.45; }}
.sb-card b {{ color:#fff; }} .sb-card .dim {{ color:#9FB0D0; }}
.sb-gate {{ display:inline-block; padding:.12rem .55rem; border-radius:999px; font-weight:700; font-size:.74rem; }}

/* page header */
.pg-head {{ margin-bottom:1.1rem; }}
.pg-head h1 {{ font-size:1.65rem; font-weight:700; margin:0 0 .15rem; padding:0; }}
.pg-head p {{ margin:0; color:var(--muted); font-size:.95rem; max-width:62ch; line-height:1.5; }}

/* release gate: the one loud element */
.gate {{ display:flex; align-items:center; gap:1.2rem; border-radius:14px; padding:1.1rem 1.5rem; margin:.2rem 0 1rem; border:1px solid; }}
.gate .big {{ font-size:2.1rem; font-weight:700; letter-spacing:-.02em; line-height:1; min-width:6.2rem; }}
.gate .why {{ font-size:.95rem; line-height:1.5; }} .gate .why b {{ font-weight:600; }}
.gate.go {{ background:{GREEN_BG}; border-color:#A9D8BF; color:#0E4D31; }}
.gate.nogo {{ background:{RED_BG}; border-color:#EDB5AE; color:#7C1F19; }}

/* tiles */
.tile {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:.85rem 1rem .75rem; height:100%; }}
.tile .v {{ font-size:1.75rem; font-weight:600; color:var(--ink); line-height:1.15; }}
.tile .l {{ font-size:.84rem; color:var(--muted); margin-top:.1rem; }}
.tile .d {{ font-size:.8rem; margin-top:.25rem; font-weight:500; }}
.tile.bad .v {{ color:{RED}; }}
.tile.good .v {{ color:{GREEN}; }}
.tile .s {{ font-size:.76rem; color:var(--muted); margin-top:.15rem; }}
.sbar {{ display:flex; height:16px; border-radius:8px; overflow:hidden; background:#E6E9ED; margin:.2rem 0 .35rem; }}
.sbar span {{ display:block; height:100%; }}
.slegend {{ display:flex; gap:1.1rem; flex-wrap:wrap; font-size:.84rem; color:var(--muted); margin-bottom:.8rem; }}
.slegend i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:.35rem; vertical-align:-1px; }}
.d.up {{ color:{GREEN}; }} .d.down {{ color:{RED}; }} .d.flat {{ color:var(--muted); }}

.chip {{ display:inline-block; padding:.12rem .6rem; border-radius:999px; font-size:.78rem; font-weight:600; border:1px solid; white-space:nowrap; }}
.panel {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:1rem 1.2rem; }}
.empty {{ background:#fff; border:1px dashed #B9C3D3; border-radius:12px; padding:2rem 2rem; text-align:left; max-width:640px; }}
.empty h3 {{ margin:0 0 .3rem; font-size:1.15rem; }} .empty p {{ margin:0; color:var(--muted); line-height:1.55; }}
.step {{ display:inline-block; padding:.28rem .7rem; margin:0 .25rem .35rem 0; border-radius:8px; font-size:.84rem; font-weight:600; border:1px solid var(--line); background:#fff; color:var(--muted); }}
.step.done {{ background:{GREEN_BG}; border-color:#A9D8BF; color:#0E4D31; }}
.step.fail {{ background:{RED_BG}; border-color:#EDB5AE; color:#7C1F19; }}
.step.paused {{ background:#FFF3DC; border-color:#E0922F; color:#7A4A07; }}
.step.restored {{ background:#F1F3F6; border-style:dashed; color:#7B8798; }}
.step.now {{ background:var(--accent-soft); border-color:var(--accent); color:var(--accent); }}

/* primary buttons carry the agent's accent */
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{ background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }}
.stButton > button, .stDownloadButton > button {{ border-radius:8px; }}
[data-testid="stSidebar"] .stButton > button {{ background:transparent; border-color:#47598A; color:#fff; }}
div[data-baseweb="tab-list"] {{ gap:.4rem; }}
@media (max-width:760px) {{ .block-container {{ padding:1.6rem 1rem 3rem; }} .gate {{ flex-direction:column; align-items:flex-start; gap:.4rem; }} }}
</style>
"""


def inject_css(agent: Agent) -> None:
    st.markdown(css(agent), unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="pg-head"><h1>{esc(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def chip(verdict: str) -> str:
    icon, label, fg, bg = VERDICT[verdict]
    return f'<span class="chip" style="background:{bg};color:{fg};border-color:{fg}55">{icon} {label}</span>'


def empty_state(title: str, text: str) -> None:
    st.markdown(f'<div class="empty"><h3>{esc(title)}</h3><p>{esc(text)}</p></div>', unsafe_allow_html=True)


def gate_banner(passed: bool, reasons: list[str], thresholds: dict, counts: dict) -> None:
    if passed:
        why = (f"<b>Safe to release on this evidence.</b> {counts['mismatch']} mismatches and {counts['parity_pct']}% parity, "
               f"within the gate of at most {thresholds['max_mismatches']} mismatches and at least {thresholds['min_parity_pct']}% parity.")
    else:
        why = "<b>Not ready.</b> " + " ".join(esc(r[:1].upper() + r[1:]) + "." for r in reasons)
    st.markdown(f'<div class="gate {"go" if passed else "nogo"}"><div class="big">{"GO" if passed else "NO-GO"}</div>'
                f'<div class="why">{why}</div></div>', unsafe_allow_html=True)


def _delta(new: float, old: float | None, good_up: bool | None, fmt: str = "{:+g}") -> str:
    if old is None:
        return ""
    d = new - old
    if d == 0 or good_up is None:
        cls = "flat"
    else:
        cls = "up" if (d > 0) == good_up else "down"
    arrow = "▲" if d > 0 else "▼" if d < 0 else "•"
    return f'<div class="d {cls}">{arrow} {fmt.format(round(d, 2))} vs baseline</div>' if d else '<div class="d flat">• same as baseline</div>'


def kpi_tiles(counts: dict[str, Any], base: dict[str, Any] | None = None) -> None:
    b = base or {}
    spec = [("Payments compared", counts["total"], "total", None, ""),
            ("Exact match", counts["match"], "match", True, ""),
            ("Explained differences", counts["expected"], "expected", None, ""),
            ("Mismatches", counts["mismatch"], "mismatch", False, "bad" if counts["mismatch"] else ""),
            ("Parity", f"{counts['parity_pct']}%", "parity_pct", True, "")]
    for col, (label, val, key, good_up, cls) in zip(st.columns(len(spec)), spec):
        d = _delta(counts[key], b.get(key), good_up) if base else ""
        col.markdown(f'<div class="tile {cls}"><div class="v">{val}</div><div class="l">{label}</div>{d}</div>', unsafe_allow_html=True)


def scorecard(m: dict[str, Any], base: dict[str, Any] | None = None) -> None:
    """Success / failure / error rates as one stacked bar plus four tiles. Buckets add up to 100%."""
    if not m["total"]:
        return
    parts = [("Exact match", m["match_pct"], GREEN), ("Explained difference", m["explained_pct"], "#4F6D8F"),
             ("Failure", m["failure_pct"], RED), ("Error", m["error_pct"], "#E0922F")]
    bar = "".join(f'<span style="width:{p}%;background:{c}" title="{n}: {p}%"></span>' for n, p, c in parts if p)
    leg = "".join(f'<span><i style="background:{c}"></i>{n} {p}%</span>' for n, p, c in parts)
    st.markdown(f'<div class="sbar">{bar}</div><div class="slegend">{leg}</div>', unsafe_allow_html=True)
    b = base or {}
    tiles = [("Success rate", f"{m['success_pct']}%", f"{m['success']:,} of {m['total']:,} payments", "good", "success_pct", True),
             ("Failure rate", f"{m['failure_pct']}%", f"{m['failure']:,} unexplained mismatches", "bad" if m["failure"] else "", "failure_pct", False),
             ("Error rate", f"{m['error_pct']}%", f"{m['error']:,} with no usable answer", "bad" if m["error"] else "", "error_pct", False),
             ("Explained", f"{m['explained_pct']}%", f"{m['explained']:,} expected changes", "", "explained_pct", None)]
    for col, (label, val, sub, cls, key, good_up) in zip(st.columns(4), tiles):
        d = _delta(m[key], b.get(key), good_up) if base and key in b else ""
        col.markdown(f'<div class="tile {cls}"><div class="v">{val}</div><div class="l">{label}</div>'
                     f'<div class="s">{sub}</div>{d}</div>', unsafe_allow_html=True)
    st.caption(f"Accepted — old service {m['old_accept_pct']}% · new service {m['new_accept_pct']}%   |   "
               f"Rejected — old {m['old_reject_pct']}% · new {m['new_reject_pct']}% · "
               f"held at the fraud step (new only) {m['new_pending_pct']}%.  "
               "Error = a service gave no accepted/rejected answer or its pacs.008 would not parse.")


def pretty_xml(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError:
        return xml


def rules_df(rule_report: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Rule": r["id"] + (" (custom)" if r.get("custom") else ""), "What it checks": r["title"],
        "Old field": r["old_ref"], "New field": r["new_ref"], "Checked": r["checked"], "Match": r["match"],
        "Explained": r["expected"], "Mismatch": r["mismatch"],
        "Failure %": round(100 * r["mismatch"] / r["checked"], 1) if r["checked"] else 0.0, "Result": RULE_STATUS[r["status"]]} for r in rule_report])


def results_df(results: list[RecordResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        icon, label, _, _ = VERDICT[r.verdict]
        bad = r.mismatches or r.expected
        rows.append({"Payment": r.request_id, "Verdict": f"{icon} {label}", "Currency": r.request.get("currency", ""),
                     "Amount": r.request.get("amount", ""), "Old": r.old_response.get("status", ""),
                     "New": r.new_response.get("status", ""), "Rules": ", ".join(sorted({c.rule_id for c in bad})),
                     "Why": " | ".join(c.explanation for c in bad)[:240]})
    return pd.DataFrame(rows)


def checks_df(r: RecordResult) -> pd.DataFrame:
    sym = {"MATCH": "✓ Match", "EXPECTED": "≈ Explained", "MISMATCH": "✕ Mismatch"}
    return pd.DataFrame([{"Rule": c.rule_id, "Check": c.title, "Old": c.old, "New": c.new, "Result": sym[c.status], "Why": c.explanation}
                         for c in r.checks])


def workflow_stepper(history: list[dict[str, Any]]) -> None:
    """One chip per step: green done, grey dashed restored (not re-run), amber paused, red failed or rejected."""
    if not history:
        return
    cls = {"DONE": "done", "RESTORED": "restored", "PAUSED": "paused", "FAILED": "fail"}
    parts = []
    for i, h in enumerate(history):
        state, status = h.get("state", "?"), h.get("status", "")
        c = "fail" if state == "REJECTED" else cls.get(status, "")
        tip = esc(h.get("detail", ""))
        label = esc(state.replace("_", " ").title()) + (f" · {esc(status.lower())}" if status and status != "DONE" else "")
        parts.append(f'<span class="step {c}" title="{tip}">{label}</span>' + ("<span style='color:#9AA6BC'>›</span> " if i < len(history) - 1 else ""))
    st.markdown("".join(parts), unsafe_allow_html=True)
    if history and history[-1].get("status") == "PAUSED":
        st.caption("Paused. Send the payment again with resumeFrom=FRAUD_CHECK and fraudDecision=RELEASE or BLOCK to continue from this step.")
    if any(h.get("status") == "RESTORED" for h in history):
        st.caption("Dashed steps were finished before the pause and are not run again.")


def inspector(r: RecordResult, key: str, extra=None) -> None:
    """Everything about ONE payment: verdict, why, side-by-side responses, workflow, pacs.008."""
    st.markdown(f"#### {esc(r.request_id)} &nbsp; {chip(r.verdict)}", unsafe_allow_html=True)
    for c in r.mismatches + r.expected:
        (st.error if c.status == "MISMATCH" else st.info)(f"**{c.rule_id} · {c.title}** — {c.explanation}"
                                                           + (f"\n\nSuggested fix: {c.fix}" if c.fix else ""))
    if r.verdict == "MATCH":
        st.success("Every applicable rule agrees between old and new.")
    if extra:
        extra()
    left, right = st.columns(2)
    with left:
        st.markdown("**Old response**")
        st.json(r.old_response, expanded=2)
    with right:
        st.markdown("**New response**")
        st.json({k: v for k, v in r.new_response.items() if k != "pacs008"}, expanded=2)
    st.markdown("**Rule by rule**")
    st.dataframe(checks_df(r), hide_index=True, width="stretch", column_config={"Why": st.column_config.TextColumn("Why", width="large")})
    wf = (r.new_response.get("workflow") or {}).get("history") or []
    if wf:
        st.markdown("**New workflow path**")
        workflow_stepper(wf)
        code = r.old_response.get("errorCode")
        if code and r.old_response.get("status") == "REJECTED":
            stage = explain.OLD_STAGE.get(code, "")
            st.caption(f"Old code, no workflow: it ran the checks in order and stopped at "
                       f"{stage.replace('_', ' ').lower() or 'an unknown step'} ({code}). Nothing was stored about how far it got.")
    xml = r.new_response.get("pacs008")
    with st.expander("Request sent to both"):
        st.json(r.request, expanded=2)
    if xml:
        with st.expander("ISO 20022 pacs.008 message from the new code"):
            st.download_button("Download XML", xml, f"{r.request_id}.pacs008.xml", "application/xml", key=f"{key}_xml")
            st.code(pretty_xml(xml), language="xml")


def patterns_view(patterns: list[dict[str, Any]], mismatches: int, extra=None) -> None:
    if not patterns:
        st.success("No mismatches. Every difference between old and new is a documented, independently verified one.")
        return
    st.caption(f"{mismatches} mismatching payment(s) collapse into {len(patterns)} pattern(s). Fix the pattern, not the payments.")
    for p in patterns:
        with st.container(border=True):
            st.markdown(f"**{p['pattern_id']} · {CATEGORY_LABEL.get(p['category'], p['category'])}** &nbsp; "
                        f"<span class='chip' style='background:{RED_BG};color:{RED};border-color:{RED}55'>{p['count']} payments</span> "
                        f"&nbsp; rules {', '.join(p['rules'])}", unsafe_allow_html=True)
            st.write(p["explanation"])
            if p["fix"]:
                st.markdown(f"**Suggested fix:** {p['fix']}")
            st.caption("Examples: " + ", ".join(p["examples"][:6]))
            if extra:
                extra(p)


def trace_table(run: RunResult) -> None:
    st.dataframe(pd.DataFrame([{"Step": s.name, "Seconds": round(s.seconds, 3), "Detail": s.detail} for s in run.trace]),
                 hide_index=True, width="stretch")


def downloads(run: RunResult, stem: str, key: str) -> None:
    a, b, c = st.columns(3)
    a.download_button("Download HTML report", report.to_html(run), f"{stem}.html", "text/html", width="stretch", key=f"{key}_h")
    b.download_button("Download CSV", report.to_csv(run), f"{stem}.csv", "text/csv", width="stretch", key=f"{key}_c")
    c.download_button("Download JSON", report.to_json(run), f"{stem}.json", "application/json", width="stretch", key=f"{key}_j")
