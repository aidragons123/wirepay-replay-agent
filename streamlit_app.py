"""
Agent 1 - REPLAY.  Recorded traffic from the running OLD system is fed into the NEW code,
and the new responses are compared with what the old system actually answered.

Run with:  streamlit run streamlit_app.py     (or `make ui`)
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wirepay_core import capture, ui  # noqa: E402
from wirepay_core.adapters import HttpAdapter  # noqa: E402
from wirepay_core.config import load_spec  # noqa: E402
from wirepay_core.engine import run_replay  # noqa: E402
from wirepay_core.generator import generate_requests  # noqa: E402
from wirepay_core.runtime import standin_adapters  # noqa: E402

st.set_page_config(page_title="Wire payments · Replay agent", page_icon="🔁", layout="wide")
ui.inject_css()

SAMPLE = ROOT / "data" / "sample_capture_1000.jsonl"


@st.cache_resource(show_spinner="Compiling the Java services (old → Java 8, new → Java 18)…")
def _standins(parity_fix: bool):
    return standin_adapters(ROOT, parity_fix)


@st.cache_data(show_spinner=False)
def _load_sample() -> list[dict]:
    return capture.load(SAMPLE)


ui.hero("Agent 1 · Replay",
        "Do yesterday's real payments come out the same in the new code?",
        "Every payment the old Java 8 system processed is recorded with its request and its response. "
        "This agent replays the requests through the new Java 18 / ISO 20022 code and compares the answers, "
        "rule by rule.")

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("1 · Recorded old traffic")
    source = st.radio("Source", ["Bundled sample day (1,000 payments)", "Upload a capture", "Generate a new day"],
                      label_visibility="collapsed")
    uploaded = None
    gen_n, gen_seed = 1000, 7
    if source == "Upload a capture":
        uploaded = st.file_uploader("JSONL or CSV", type=["jsonl", "json", "csv"],
                                    help="JSONL: one {\"request\":{…},\"response\":{…}} per line. "
                                         "CSV: columns req_<field> and resp_<field>.")
    elif source == "Generate a new day":
        gen_n = st.slider("Payments", 100, 5000, 1000, step=100)
        gen_seed = st.number_input("Random seed", 1, 9999, 7)
        st.caption("Simulates a production day by running the stand-in old service.")

    st.header("2 · New code under test")
    target = st.radio("Implementation", ["Stand-in · parity gaps present", "Stand-in · parity gaps fixed",
                                         "External HTTP endpoint"], label_visibility="collapsed")
    http_url, http_auth = "", ""
    if target == "External HTTP endpoint":
        http_url = st.text_input("URL", placeholder="https://wire-new.example/api/payments")
        http_auth = st.text_input("Authorization header (optional)", type="password")
    else:
        st.caption("The stand-in contains two deliberate gaps (fee rounding, same-day cut-off) so there is "
                   "something real to find. 'Fixed' shows what a clean migration looks like.")

    run_clicked = st.button("▶ Replay through new code", type="primary", width="stretch")

# ------------------------------------------------------------------ run
if run_clicked:
    try:
        spec = load_spec()
        if source == "Bundled sample day (1,000 payments)":
            if not SAMPLE.exists():
                st.error("Sample capture not found - run `make sample` first.")
                st.stop()
            records, label = _load_sample(), SAMPLE.name
        elif source == "Upload a capture":
            if uploaded is None:
                st.warning("Upload a capture file first.")
                st.stop()
            records, label = capture.parse_bytes(uploaded.getvalue(), uploaded.name), uploaded.name
        else:
            old_ad, _, _ = _standins(False)
            reqs, _ = generate_requests(gen_n, int(gen_seed), "2026-10-19")
            records = [{"request": q, "response": r} for q, r in zip(reqs, old_ad.run(reqs))]
            label = f"generated-{gen_n}-seed{int(gen_seed)}"

        problems = capture.validate(records)
        if problems:
            st.error("The capture has problems:\n\n- " + "\n- ".join(problems[:10]))
            st.stop()

        if target == "External HTTP endpoint":
            if not http_url:
                st.warning("Enter the endpoint URL.")
                st.stop()
            new_ad = HttpAdapter(http_url, {"Authorization": http_auth} if http_auth else {}, label="new (external)")
            notes: list[str] = []
        else:
            _, new_ad, notes = _standins(target.endswith("fixed"))

        with st.status("Replaying…", expanded=False) as status:
            run = run_replay(records, new_ad, spec, progress=lambda m: status.update(label=m), meta={"capture": label})
            status.update(label=f"Done — {run.counts['total']} payments compared", state="complete")
        st.session_state["replay_run"] = run
        st.session_state["replay_notes"] = notes
        st.session_state["replay_target"] = target
    except capture.CaptureError as e:
        st.error(f"Could not read the capture: {e}")
        st.stop()
    except Exception as e:  # surface adapter / build failures plainly
        st.error(f"Run failed: {e}")
        st.stop()

# ------------------------------------------------------------------ results
run = st.session_state.get("replay_run")
if run is None:
    ui.flow([("Record", "The old system's real requests and responses, captured every day."),
             ("Replay", "Each recorded request is sent to the new Java 18 code."),
             ("Compare", "14 mapping rules + 6 new-feature checks per payment."),
             ("Diagnose", "Differences are grouped into patterns, not a wall of rows.")])
    st.markdown('<div class="wp-note">Choose a source and a target in the sidebar, then press '
                '<b>Replay through new code</b>. The bundled day has 1,000 payments, including bad IBANs, '
                'long names, EUR bank holidays, half-cent fees and same-day payments.</div>', unsafe_allow_html=True)
else:
    for n in st.session_state.get("replay_notes", []):
        st.info(n)
    ui.render_run(run, key="replay", stem="replay-report")
