"""Shared Streamlit building blocks for both agents (imported lazily - Streamlit is not needed for the CLI)."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import pandas as pd
import streamlit as st

from . import report
from .compare import RecordResult
from .engine import RunResult

NAVY, GREEN, BLUE, ORANGE, RED, MUTED = "#16233B", "#2E7D5B", "#3B6EA5", "#C97A2B", "#C0392B", "#6B7280"

VERDICT = {
    "MATCH": ("✅", "Match", GREEN, "#EAF5EF"),
    "EXPECTED_DIFFERENCE": ("🔷", "Expected difference", BLUE, "#EAF1F8"),
    "MISMATCH": ("❌", "Mismatch", RED, "#FBEAEA"),
}
RULE_STATUS = {"VALIDATED": "✅ Validated", "INVALIDATED": "❌ Invalidated", "UNTESTED": "◻️ Not exercised"}
CATEGORY_LABEL = {
    "IMPLEMENTATION_DEFECT": "Implementation defect",
    "ROUNDING_MODE": "Rounding mode",
    "REASON_CODE": "Reason-code mapping",
    "NEW_FEATURE_DEFECT": "New feature misbehaves",
    "UNEXPLAINED": "Unexplained difference",
    "EXPECTED_ENHANCEMENT": "Expected (new feature)",
}

CSS = f"""
<style>
.block-container {{ padding-top: 3.6rem; max-width: 1240px; }}
#MainMenu, footer {{ visibility: hidden; }}
.wp-hero {{ background:#fff; border:1px solid #e6e8eb; border-left:5px solid {NAVY}; border-radius:14px;
  padding:1.4rem 1.8rem; margin-bottom:1.1rem; box-shadow:0 2px 12px rgba(20,36,58,.06); }}
.wp-hero .tag {{ font:600 .72rem/1 ui-monospace,monospace; letter-spacing:.14em; color:{GREEN}; text-transform:uppercase; }}
.wp-hero h1 {{ margin:.35rem 0 .3rem; font-size:1.55rem; font-weight:800; color:{NAVY}; }}
.wp-hero p {{ margin:0; color:#4a5568; font-size:.95rem; line-height:1.5; }}
.wp-kpi {{ background:#fff; border:1px solid #eaecef; border-top:5px solid var(--accent); border-radius:14px;
  padding:.9rem 1.1rem .8rem; box-shadow:0 2px 10px rgba(20,36,58,.05); }}
.wp-kpi .v {{ font-size:1.9rem; font-weight:800; color:{NAVY}; line-height:1.1; }}
.wp-kpi .l {{ font-size:.82rem; color:{MUTED}; margin-top:.15rem; }}
.wp-pill {{ display:inline-block; padding:.28rem .75rem; border-radius:999px; font-weight:700; font-size:.78rem; }}
.wp-note {{ background:#f3f6fa; border:1px solid #e1e7ef; border-radius:10px; padding:.7rem 1rem; color:#33415c; font-size:.9rem; }}
.wp-flow {{ display:flex; gap:.6rem; flex-wrap:wrap; align-items:stretch; margin:.4rem 0 1rem; }}
.wp-step {{ flex:1 1 180px; background:#fff; border:1px solid #e6e8eb; border-radius:12px; padding:.8rem .95rem; }}
.wp-step b {{ color:{NAVY}; }} .wp-step span {{ color:{MUTED}; font-size:.85rem; display:block; margin-top:.2rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(tag: str, title: str, subtitle: str) -> None:
    st.markdown(f'<div class="wp-hero"><div class="tag">{tag}</div><h1>{title}</h1><p>{subtitle}</p></div>',
                unsafe_allow_html=True)


def flow(steps: list[tuple[str, str]]) -> None:
    html = "".join(f'<div class="wp-step"><b>{i}. {t}</b><span>{d}</span></div>' for i, (t, d) in enumerate(steps, 1))
    st.markdown(f'<div class="wp-flow">{html}</div>', unsafe_allow_html=True)


def pill(verdict: str) -> str:
    icon, label, fg, bg = VERDICT[verdict]
    return f'<span class="wp-pill" style="background:{bg};color:{fg};border:1px solid {fg}">{icon} {label}</span>'


def kpi_row(counts: dict[str, Any]) -> None:
    tiles = [("Payments compared", counts["total"], NAVY), ("Exact match", counts["match"], GREEN),
             ("Expected differences", counts["expected"], BLUE), ("Mismatches", counts["mismatch"], RED),
             ("Parity", f"{counts['parity_pct']}%", GREEN if counts["mismatch"] == 0 else ORANGE)]
    for col, (label, val, accent) in zip(st.columns(len(tiles)), tiles):
        col.markdown(f'<div class="wp-kpi" style="--accent:{accent}"><div class="v">{val}</div><div class="l">{label}</div></div>',
                     unsafe_allow_html=True)
    st.caption("Parity = exact matches + differences explained by a documented new feature. "
               "Expected differences are re-derived independently, never taken on trust from the new code.")


def pretty_xml(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
        ET.indent(root)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError:
        return xml


def rules_df(run: RunResult) -> pd.DataFrame:
    return pd.DataFrame([{
        "Rule": r["id"], "What it checks": r["title"], "Old field": r["old_ref"], "New field": r["new_ref"],
        "Checked": r["checked"], "Match": r["match"], "Expected": r["expected"], "Mismatch": r["mismatch"],
        "Verdict": RULE_STATUS[r["status"]]} for r in run.rule_report])


def results_df(results: list[RecordResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        icon, label, _, _ = VERDICT[r.verdict]
        rows.append({"Payment": r.request_id, "Verdict": f"{icon} {label}",
                     "Old": r.old_response.get("status", ""), "New": r.new_response.get("status", ""),
                     "Rules": ", ".join(sorted({c.rule_id for c in (r.mismatches or r.expected)})),
                     "Why": " | ".join(c.explanation for c in (r.mismatches or r.expected))[:240]})
    return pd.DataFrame(rows)


def checks_df(r: RecordResult) -> pd.DataFrame:
    rows = []
    for c in r.checks:
        rows.append({"Rule": c.rule_id, "Check": c.title, "Old": c.old, "New": c.new,
                     "Result": {"MATCH": "✅ Match", "EXPECTED": "🔷 Expected", "MISMATCH": "❌ Mismatch"}[c.status],
                     "Why": c.explanation})
    return pd.DataFrame(rows)


def inspector(r: RecordResult, key: str) -> None:
    """Side-by-side view of ONE payment: request, old response, new response, and the rule-by-rule result."""
    st.markdown(f"**{r.request_id}** &nbsp; {pill(r.verdict)}", unsafe_allow_html=True)
    for c in r.mismatches + r.expected:
        label = "❌" if c.status == "MISMATCH" else "🔷"
        st.markdown(f"{label} **{c.rule_id} · {c.title}** — {c.explanation}")
        if c.fix:
            st.caption(f"Suggested fix: {c.fix}")
    st.dataframe(checks_df(r), hide_index=True, width="stretch",
                 column_config={"Why": st.column_config.TextColumn("Why", width="large")})
    a, b, c = st.columns(3)
    a.markdown("**Request**")
    a.json(r.request, expanded=False)
    b.markdown("**Old response**")
    b.json(r.old_response, expanded=False)
    c.markdown("**New response**")
    c.json({k: v for k, v in r.new_response.items() if k != "pacs008"}, expanded=False)
    wf = (r.new_response.get("workflow") or {}).get("history") or []
    if wf:
        st.markdown("**New workflow audit trail**")
        st.dataframe(pd.DataFrame(wf).rename(columns=str.title), hide_index=True, width="stretch")
    xml = r.new_response.get("pacs008")
    if xml:
        with st.expander("ISO 20022 pacs.008 message produced by the new code"):
            st.code(pretty_xml(xml), language="xml")


def patterns_view(run: RunResult) -> None:
    if not run.patterns:
        st.success("No mismatches. Every difference between old and new is an explained, documented one.")
        return
    st.caption(f"{run.counts['mismatch']} mismatching payment(s) collapse into {len(run.patterns)} distinct pattern(s). "
               "Fix the pattern, not the payments.")
    for p in run.patterns:
        with st.container(border=True):
            st.markdown(f"**{p['pattern_id']} · {CATEGORY_LABEL.get(p['category'], p['category'])}** — "
                        f"{p['count']} payment(s) · rules {', '.join(p['rules'])}")
            st.write(p["explanation"])
            if p["fix"]:
                st.markdown(f"**Suggested fix:** {p['fix']}")
            st.caption("Examples: " + ", ".join(p["examples"]))


def trace_view(run: RunResult) -> None:
    st.dataframe(pd.DataFrame([{"Step": s.name, "Seconds": round(s.seconds, 3), "Detail": s.detail} for s in run.trace]),
                 hide_index=True, width="stretch")
    n, rep = run.counts["total"], run.meta.get("replay_seconds")
    if rep and n:
        st.caption(f"Throughput: {n / max(rep, 1e-9):,.0f} payments/second through the new code.")


def downloads(run: RunResult, stem: str) -> None:
    a, b, c = st.columns(3)
    a.download_button("⬇ HTML report", report.to_html(run), f"{stem}.html", "text/html", width="stretch")
    b.download_button("⬇ CSV (one row per payment)", report.to_csv(run), f"{stem}.csv", "text/csv", width="stretch")
    c.download_button("⬇ JSON (full detail)", report.to_json(run), f"{stem}.json", "application/json", width="stretch")


def render_run(run: RunResult, key: str, stem: str) -> None:
    """The full result view: KPIs, then rule-by-rule / patterns / payments / trace+export."""
    kpi_row(run.counts)
    t1, t2, t3, t4 = st.tabs(["Rule-by-rule verdict", "Mismatch patterns", "Payments", "Run trace & export"])
    with t1:
        st.dataframe(rules_df(run), hide_index=True, width="stretch", height=36 + 35 * len(run.rule_report))
        st.caption("Mapping rules (M-xxx) must be preserved from old to new. New-feature rules (N-xxx) either explain "
                   "an expected difference or verify that the new behaviour is actually correct.")
    with t2:
        patterns_view(run)
    with t3:
        show = st.multiselect("Show", ["MISMATCH", "EXPECTED_DIFFERENCE", "MATCH"], default=["MISMATCH", "EXPECTED_DIFFERENCE"],
                              format_func=lambda v: VERDICT[v][1], key=f"{key}_filter")
        query = st.text_input("Filter by payment id", key=f"{key}_q").strip().upper()
        rows = [r for r in run.results if r.verdict in show and query in r.request_id.upper()]
        st.caption(f"{len(rows)} payment(s)")
        if rows:
            st.dataframe(results_df(rows), hide_index=True, width="stretch", height=300,
                         column_config={"Why": st.column_config.TextColumn("Why", width="large")})
            pick = st.selectbox("Inspect a payment", [r.request_id for r in rows[:2000]], key=f"{key}_pick")
            inspector(next(r for r in rows if r.request_id == pick), key)
    with t4:
        trace_view(run)
        downloads(run, stem)
        st.json({k: v for k, v in run.meta.items()}, expanded=False)
