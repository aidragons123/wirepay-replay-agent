"""Replay Agent - recorded traffic from the running OLD system is fed to the NEW code and the answers are compared.

Run with:  streamlit run streamlit_app.py     (or `make ui`)
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wirepay_core import capture, ui  # noqa: E402
from wirepay_core.brand import PARITY_REPLAY as AGENT  # noqa: E402
from wirepay_core.engine import run_replay  # noqa: E402
from wirepay_core.generator import generate_requests  # noqa: E402
from wirepay_core.shell import Ctx, run_app  # noqa: E402

SAMPLE = ROOT / "data" / "sample_capture_1000.jsonl"
SOURCES = ["Sample day (1,000 payments)", "Upload a capture", "Generate a day"]


@st.cache_data(show_spinner=False)
def _sample() -> list[dict]:
    return capture.load(SAMPLE)


def execute(ctx: Ctx, records: list[dict], source: str, label: str, notes: str) -> None:
    problems = capture.validate(records)
    if problems:
        st.error("The capture has problems, so nothing was run:\n\n- " + "\n- ".join(problems[:8]))
        return
    try:
        _, new, notes_ = ctx.adapters()
        spec = ctx.spec()
        run = ctx.execute(lambda say, on_count: run_replay(records, new, spec, progress=say, meta={"capture": source}, on_count=on_count))
    except Exception as exc:  # adapter / build failure: say what happened, keep the page usable
        st.error(f"The replay failed: {exc}")
        return
    ctx.record(run, label, notes, source=source, kind="replay")
    for n in notes_:
        st.toast(n)
    ctx.go("overview")


def quick_start(ctx: Ctx) -> None:
    execute(ctx, _sample(), SAMPLE.name, "Sample day", "Bundled sample capture")


def workbench(ctx: Ctx) -> None:
    ui.page_header(AGENT.run_page_title, AGENT.run_page_hint)
    left, right = st.columns([1.6, 1], gap="large")
    records, source, ready = [], "", False
    with left:
        with st.container(border=True):
            st.markdown("#### 1. Recorded old traffic")
            st.caption("What the old system really received and answered. It is never called again.")
            src = st.radio("Source", SOURCES, horizontal=True, label_visibility="collapsed")
            if src == SOURCES[0]:
                records, source, ready = _sample() if SAMPLE.exists() else [], SAMPLE.name, SAMPLE.exists()
                st.info("One recorded day from the bundled stand-in old service, with bad IBANs, long names, EUR bank holidays, half-cent fees and same-day payments mixed in.")
            elif src == SOURCES[1]:
                up = st.file_uploader("JSONL or CSV", type=["jsonl", "json", "csv"], help="JSONL: one {\"request\":…, \"response\":…} per line. CSV: columns req_<field> and resp_<field>.")
                if up is not None:
                    try:
                        records, source, ready = capture.parse_bytes(up.getvalue(), up.name), up.name, True
                        st.success(f"{len(records):,} recorded payments read from {up.name}.")
                    except capture.CaptureError as exc:
                        st.error(f"Could not read that file: {exc}")
                else:
                    st.caption("Each record needs the request and the response the old system gave.")
            else:
                a, b = st.columns(2)
                n = a.slider("Payments", 100, 5000, 1000, step=100)
                seed = b.number_input("Random seed", 1, 9999, 7)
                ready, source = True, f"generated-{n}-seed{int(seed)}"
                st.caption("Simulates a production day by running the bundled stand-in old service.")
        with st.container(border=True):
            st.markdown("#### 2. New code under test")
            ctx.picker("new")
        with st.container(border=True):
            st.markdown("#### 3. Name it")
            label = st.text_input("Run name", placeholder="Release 2.4 candidate", help="Shown in history. Leave empty to use the date.")
            notes = st.text_area("Notes (optional)", height=70, placeholder="What changed since the last run?")
    with right:
        gate = ctx.gate()
        with st.container(border=True):
            st.markdown("#### What will happen")
            st.markdown("1. Each recorded request goes to the new code.\n2. Its answer is compared with what the old system really said, on 14 mapping rules and 8 new-feature checks.\n"
                        "3. Differences are grouped into patterns.\n4. The run is saved to history and judged against the release gate.")
            st.caption(f"Release gate: at most {gate.max_mismatches} mismatches, at least {gate.min_parity_pct}% parity. Change it in Settings.")
        go = st.button("Replay through the new code", type="primary", width="stretch", disabled=not ready)
    if go:
        if src == SOURCES[2]:
            old, _, _ = ctx.standins(False)
            reqs, _ = generate_requests(int(n), int(seed), "2026-10-19")
            records = [{"request": q, "response": r} for q, r in zip(reqs, old.run(reqs))]
        execute(ctx, records, source, label.strip(), notes.strip())


run_app(AGENT, ROOT, workbench, quick_start)
