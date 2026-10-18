"""The application shell shared by both agents: navigation, history, comparison, rules, settings.

Each agent supplies only its brand and a `workbench(ctx)` page (where a run is configured and started).
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from . import charts, ui
from .adapters import Adapter, HttpAdapter
from .brand import Agent
from .config import load_spec
from .diffing import compare_runs
from .engine import RunResult
from .gate import Gate, evaluate
from .runtime import standin_adapters
from .store import Store

NEW_KINDS = {"standin_gaps": "Bundled stand-in, with its two planted gaps", "standin_fixed": "Bundled stand-in, gaps fixed",
             "http": "External HTTP endpoint"}
OLD_KINDS = {"standin": "Bundled stand-in (Java 8 target)", "http": "External HTTP endpoint"}


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    except ValueError:
        return iso


@st.cache_resource(show_spinner=False)
def _store() -> Store:
    try:
        s = Store()
        probe = s.home / ".probe"
        probe.write_text("x")
        probe.unlink()
        return s
    except OSError:                                    # read-only checkout: keep history for this session only
        return Store(tempfile.mkdtemp(prefix="wirepay-"))


@st.cache_resource(show_spinner=False, max_entries=6)
def _load(home: str, run_id: str):
    return Store(home).load_run(run_id)


class Ctx:
    """What a workbench page needs from the shell."""

    def __init__(self, agent: Agent, root: Path):
        self.agent, self.root, self.store = agent, root, _store()
        self.pages: dict[str, Any] = {}

    # ---- settings / adapters
    @property
    def settings(self) -> dict[str, Any]:
        return self.store.load_settings()

    def gate(self) -> Gate:
        return Gate(**self.settings["gate"])

    def spec(self):
        return load_spec(extra_rules=self.store.load_custom_rules())

    @st.cache_resource(show_spinner="Compiling the Java services (old → Java 8, new → Java 18)…")
    def _standins(_self, root: str, parity_fix: bool):
        return standin_adapters(Path(root), parity_fix)

    def standins(self, parity_fix: bool):
        return self._standins(str(self.root), parity_fix)

    def adapters(self) -> tuple[Adapter, Adapter, list[str]]:
        s = self.settings
        s_old, s_new, notes = self.standins(s["new"]["kind"] == "standin_fixed")
        old, new = s_old, s_new
        if s["old"]["kind"] == "http":
            if not s["old"]["url"]:
                raise ValueError("The old endpoint URL is empty. Add it in Settings.")
            auth = st.session_state.get("auth_old", "")
            old = HttpAdapter(s["old"]["url"], {"Authorization": auth} if auth else {}, timeout=int(s["old"]["timeout"]), label="old (external)")
        if s["new"]["kind"] == "http":
            if not s["new"]["url"]:
                raise ValueError("The new endpoint URL is empty. Add it in Settings.")
            auth = st.session_state.get("auth_new", "")
            new = HttpAdapter(s["new"]["url"], {"Authorization": auth} if auth else {}, timeout=int(s["new"]["timeout"]), label="new (external)")
        return old, new, notes

    # ---- runs
    def execute(self, runner: Callable[[Callable[[str], None], Callable[[str, int, int], None]], RunResult]) -> RunResult:
        bar = st.progress(0.0, text="Starting…")
        words = {"old": "Old service", "new": "New service"}

        def on_count(phase: str, done: int, total: int) -> None:
            bar.progress(min(1.0, done / max(total, 1)), text=f"{words.get(phase, phase)}: {done:,} of {total:,} payments")

        def say(msg: str) -> None:
            bar.progress(1.0, text=msg)

        try:
            return runner(say, on_count)
        finally:
            bar.empty()

    def record(self, run: RunResult, label: str = "", notes: str = "", source: str = "", kind: str | None = None) -> str:
        rid = self.store.save_run(run, self.agent.key, label, notes, kind, source, self.gate())
        st.session_state["current_id"] = rid
        return rid

    def current(self) -> tuple[dict[str, Any], RunResult] | None:
        rid = st.session_state.get("current_id")
        runs = self.store.list_runs()
        if not runs:
            return None
        if not rid or not any(r["id"] == rid for r in runs):
            rid = runs[0]["id"]
            st.session_state["current_id"] = rid
        return _load(str(self.store.home), rid)

    def picker(self, side: str) -> None:
        """Choose the service under test right on the run page; the choice is saved to settings."""
        s = self.settings
        kinds = NEW_KINDS if side == "new" else OLD_KINDS
        cur = s[side]["kind"]
        pick = st.selectbox("Implementation", list(kinds), index=list(kinds).index(cur), format_func=kinds.get, key=f"pk_{side}",
                            label_visibility="collapsed")
        changed = pick != cur
        s[side]["kind"] = pick
        if pick == "http":
            url = st.text_input("Endpoint URL", s[side]["url"], key=f"pk_{side}_url", placeholder=f"https://wire-{side}.example/api/payments")
            auth = st.text_input("Authorization header (optional)", st.session_state.get(f"auth_{side}", ""), type="password", key=f"pk_{side}_auth",
                                 help="Kept for this browser session only. Never saved.")
            st.session_state[f"auth_{side}"] = auth
            changed = changed or url.strip() != s[side]["url"]
            s[side]["url"] = url.strip()
        elif pick == "standin_gaps":
            st.caption("This stand-in has two deliberate gaps (fee rounding and the same-day cut-off), so there is something real to find.")
        elif pick == "standin_fixed":
            st.caption("The same stand-in with both gaps fixed. A clean migration should look like this: no mismatches.")
        if changed:
            self.store.save_settings(s)

    def go(self, page: str) -> None:
        st.switch_page(self.pages[page])


def run_app(agent: Agent, root: Path, workbench: Callable[[Ctx], None], quick_start: Callable[[Ctx], None] | None = None) -> None:
    st.set_page_config(page_title=agent.name, page_icon=agent.glyph, layout="wide", initial_sidebar_state="expanded")
    ui.inject_css(agent)
    ctx = Ctx(agent, root)
    store = ctx.store

    # ------------------------------------------------------------------ pages
    def p_workbench() -> None:
        workbench(ctx)

    def run_picker(key: str) -> tuple[dict, RunResult] | None:
        runs = store.list_runs()
        if not runs:
            return None
        ids = [r["id"] for r in runs]
        cur = st.session_state.get("current_id")
        idx = ids.index(cur) if cur in ids else 0
        sel = st.selectbox("Run", ids[:60], index=min(idx, 59) if idx < 60 else 0, key=key, label_visibility="collapsed",
                           format_func=lambda i: next(f"{'★ ' if r['pinned'] else ''}{r['label']}  ·  {fmt_time(r['created_at'])}  ·  "
                                                      f"{'GO' if r['gate']['passed'] else 'NO-GO'}" for r in runs if r["id"] == i))
        st.session_state["current_id"] = sel
        return _load(str(store.home), sel)

    def no_runs() -> None:
        ui.page_header("Nothing to show yet", "Results appear here after your first run.")
        ui.empty_state("No runs yet", f"Start one from “{agent.run_page_title}”. Every run is saved to history automatically, "
                                      "so you can reopen it, compare it with another run, and download its reports.")
        st.write("")
        c1, c2, _ = st.columns([1, 1.3, 2])
        if c1.button(agent.run_page_title, type="primary", width="stretch"):
            ctx.go("run")
        if quick_start and c2.button("Try the bundled sample", width="stretch"):
            quick_start(ctx)
            st.rerun()

    def p_overview() -> None:
        picked = run_picker("ov_pick")
        if not picked:
            return no_runs()
        sm, run = picked
        ui.page_header(sm["label"], f"{fmt_time(sm['created_at'])} · {sm['kind'].replace('-', ' ')} · {sm['counts']['total']:,} payments"
                       + (f" · {sm['source']}" if sm["source"] else ""))
        if sm.get("notes"):
            st.caption(sm["notes"])
        ui.gate_banner(sm["gate"]["passed"], sm["gate"]["reasons"], sm["gate"], sm["counts"])
        base = None
        bid = ctx.settings.get("baseline_id")
        if bid and bid != sm["id"] and any(r["id"] == bid for r in store.list_runs()):
            base = next(r for r in store.list_runs() if r["id"] == bid)["counts"]
        ui.kpi_tiles(sm["counts"], base)
        st.write("")
        t1, t2, t3 = st.tabs(["Where it differs", f"Mismatch patterns ({len(run.patterns)})", "Run details"])
        with t1:
            if sm["counts"]["mismatch"] + sm["counts"]["expected"] == 0:
                st.success("All payments match exactly.")
            a, b = st.columns(2)
            with a:
                st.markdown("**Differences by rule**")
                ch = charts.rules_chart(run)
                st.altair_chart(ch, width="stretch") if ch else st.caption("No rule shows a difference.")
            with b:
                dim = st.segmented_control("Split verdicts by", ["Currency", "Charge bearer", "Old decision"], default="Currency", key="ov_dim")
                st.altair_chart(charts.breakdown_chart(run, dim or "Currency"), width="stretch")
        with t2:
            ui.patterns_view(run.patterns, sm["counts"]["mismatch"])
            if run.patterns:
                if st.button("Open the affected payments", key="ov_open"):
                    st.session_state["pay_filter"] = ["MISMATCH"]
                    ctx.go("payments")
        with t3:
            c1, c2, c3 = st.columns(3)
            c1.metric("Duration", f"{sm['duration']:.1f} s")
            c2.metric("Throughput", f"{sm['counts']['total'] / max(sm['duration'], 1e-9):,.0f} / s")
            c3.metric("Input fingerprint", sm["fingerprint"])
            ui.trace_table(run)
            st.caption(f"Old: {sm.get('old') or 'recorded traffic'} · New: {sm.get('new') or '—'}")
            ui.downloads(run, f"{agent.key}-{sm['id']}", "ov")
            with st.expander("Rename, annotate or set as baseline"):
                nl = st.text_input("Name", sm["label"], key=f"nm_{sm['id']}")
                nn = st.text_area("Notes", sm.get("notes", ""), key=f"nt_{sm['id']}", height=80)
                x, y, z = st.columns(3)
                if x.button("Save changes", key=f"sv_{sm['id']}"):
                    store.update(sm["id"], label=nl, notes=nn)
                    st.rerun()
                if y.button("Use as baseline", key=f"bs_{sm['id']}", help="Later runs show their change against this one."):
                    s = ctx.settings
                    s["baseline_id"] = sm["id"]
                    store.save_settings(s)
                    st.rerun()
                if z.button("Unpin" if sm["pinned"] else "Pin to top", key=f"pn_{sm['id']}"):
                    store.update(sm["id"], pinned=not sm["pinned"])
                    st.rerun()

    def p_payments() -> None:
        picked = run_picker("pay_pick")
        if not picked:
            return no_runs()
        sm, run = picked
        ui.page_header("Payments", f"Every payment in “{sm['label']}”. Select a row to see old and new side by side.")
        f1, f2, f3, f4 = st.columns([2, 1.4, 1.2, 1.4])
        order = ["MISMATCH", "EXPECTED_DIFFERENCE", "MATCH"]
        show = f1.multiselect("Verdict", order, default=st.session_state.pop("pay_filter", ["MISMATCH", "EXPECTED_DIFFERENCE"]),
                              format_func=lambda v: ui.VERDICT[v][1], key="pay_show")
        query = f2.text_input("Payment id contains", key="pay_q").strip().upper()
        rule_ids = sorted({c.rule_id for r in run.results for c in r.checks if c.status != "MATCH"})
        rule = f3.selectbox("Rule", ["Any"] + rule_ids, key="pay_rule")
        ccys = sorted({str(r.request.get("currency") or "") for r in run.results})
        ccy = f4.selectbox("Currency", ["Any"] + ccys, key="pay_ccy")
        rows = [r for r in run.results if r.verdict in show and query in r.request_id.upper()
                and (rule == "Any" or any(c.rule_id == rule and c.status != "MATCH" for c in r.checks))
                and (ccy == "Any" or str(r.request.get("currency") or "") == ccy)]
        st.caption(f"{len(rows):,} of {len(run.results):,} payments")
        if not rows:
            ui.empty_state("No payments match these filters", "Widen the verdict selection or clear the search box.")
            return
        shown = rows[:3000]
        df = ui.results_df(shown)
        ev = st.dataframe(df, hide_index=True, width="stretch", height=330, on_select="rerun", selection_mode="single-row",
                          key="pay_table", column_config={"Why": st.column_config.TextColumn("Why", width="large")})
        st.download_button("Download this list as CSV", df.to_csv(index=False), "payments.csv", "text/csv")
        sel = ev.selection.rows
        r = shown[sel[0]] if sel else shown[0]
        if not sel:
            st.caption("Showing the first payment. Select a row to inspect another.")
        st.divider()
        ui.inspector(r, "pay")

    def p_history() -> None:
        runs = store.list_runs()
        ui.page_header("Run history", "Every run is saved. Reopen one, compare two, or watch parity move over time.")
        if not runs:
            return no_runs()
        ch = charts.trend_chart(runs, ctx.gate().min_parity_pct)
        if ch is not None:
            st.markdown("**Parity over time**")
            st.altair_chart(ch, width="stretch")
        f1, f2, f3 = st.columns([2, 1.2, 1.2])
        q = f1.text_input("Search by name or note", key="h_q").strip().lower()
        gate_f = f2.selectbox("Release gate", ["All", "GO", "NO-GO"], key="h_g")
        kinds = sorted({r["kind"] for r in runs})
        kind_f = f3.selectbox("Kind", ["All"] + kinds, key="h_k")
        rows = [r for r in runs if (not q or q in (r["label"] + r.get("notes", "")).lower())
                and (gate_f == "All" or ("GO" if r["gate"]["passed"] else "NO-GO") == gate_f) and (kind_f == "All" or r["kind"] == kind_f)]
        rows.sort(key=lambda r: (not r["pinned"], ))   # pinned first, stable otherwise (already newest first)
        df = pd.DataFrame([{"": "★" if r["pinned"] else "", "Name": r["label"], "When": fmt_time(r["created_at"]),
                            "Kind": r["kind"], "Payments": r["counts"]["total"], "Mismatches": r["counts"]["mismatch"],
                            "Parity %": r["counts"]["parity_pct"], "Gate": "GO" if r["gate"]["passed"] else "NO-GO",
                            "Patterns": r["patterns"], "Seconds": r["duration"], "Inputs": r["fingerprint"]} for r in rows])
        st.caption("Select one run to open it, or two to compare them.")
        ev = st.dataframe(df, hide_index=True, width="stretch", height=min(420, 38 + 35 * max(len(df), 1)), on_select="rerun",
                          selection_mode="multi-row", key="h_table")
        picked = [rows[i] for i in ev.selection.rows]
        a, b, c, d, e = st.columns(5)
        if a.button("Open", disabled=len(picked) != 1, type="primary", width="stretch"):
            st.session_state["current_id"] = picked[0]["id"]
            ctx.go("overview")
        if b.button("Compare two", disabled=len(picked) != 2, width="stretch"):
            older, newer = sorted(picked, key=lambda r: r["created_at"])
            st.session_state["cmp_a"], st.session_state["cmp_b"] = older["id"], newer["id"]
            ctx.go("compare")
        if c.button("Set as baseline", disabled=len(picked) != 1, width="stretch"):
            s = ctx.settings
            s["baseline_id"] = picked[0]["id"]
            store.save_settings(s)
            st.toast("Baseline set. Later runs show their change against it.")
        if d.button("Pin / unpin", disabled=not picked, width="stretch"):
            for r in picked:
                store.update(r["id"], pinned=not r["pinned"])
            st.rerun()
        if e.button("Delete", disabled=not picked, width="stretch"):
            st.session_state["confirm_delete"] = [r["id"] for r in picked]
        if st.session_state.get("confirm_delete"):
            ids = st.session_state["confirm_delete"]
            st.warning(f"Delete {len(ids)} run(s)? This cannot be undone.")
            y, n, _ = st.columns([1, 1, 4])
            if y.button("Yes, delete", type="primary"):
                for i in ids:
                    store.delete(i)
                st.session_state.pop("confirm_delete")
                st.rerun()
            if n.button("Cancel"):
                st.session_state.pop("confirm_delete")
                st.rerun()

    def p_compare() -> None:
        runs = store.list_runs()
        ui.page_header("Compare runs", "See what a code change did: which payments were fixed, which broke, which patterns went away.")
        if len(runs) < 2:
            ui.empty_state("You need two runs", "Run the same inputs before and after a code change, then compare them here.")
            return
        ids = [r["id"] for r in runs]
        by = {r["id"]: r for r in runs}
        fmt = lambda i: f"{by[i]['label']}  ·  {fmt_time(by[i]['created_at'])}  ·  {by[i]['counts']['mismatch']} mismatches"
        bid = ctx.settings.get("baseline_id")
        da = st.session_state.get("cmp_a") or (bid if bid in by else ids[1])
        db = st.session_state.get("cmp_b") or ids[0]
        c1, c2 = st.columns(2)
        ia = c1.selectbox("Before (A)", ids, index=ids.index(da) if da in ids else 1, format_func=fmt, key="cmp_a_sel")
        ib = c2.selectbox("After (B)", ids, index=ids.index(db) if db in ids else 0, format_func=fmt, key="cmp_b_sel")
        if ia == ib:
            st.info("Pick two different runs.")
            return
        (sa, ra), (sb, rb) = _load(str(store.home), ia), _load(str(store.home), ib)
        same = sa["fingerprint"] == sb["fingerprint"]
        diff = compare_runs(ra, rb, same)
        if same:
            st.success("Same payments in both runs, so this is a like-for-like comparison.")
        else:
            st.warning(f"The runs do not use identical payments ({diff.coverage_pct}% overlap). Payment-level movement below only covers the shared ones.")
        better = sb["counts"]["mismatch"] < sa["counts"]["mismatch"]
        worse = sb["counts"]["mismatch"] > sa["counts"]["mismatch"]
        st.markdown(f"### {'Improved' if better else 'Worse' if worse else 'No change in mismatches'}")
        st.write(diff.headline)
        st.altair_chart(charts.compare_chart("A · before", sa["counts"], "B · after", sb["counts"]), width="stretch")
        k = pd.DataFrame([{"Measure": x["label"], "A": x["a"], "B": x["b"], "Change": x["delta"],
                           "": "better" if x["better"] else "worse" if x["better"] is False else ""} for x in diff.kpis])
        st.dataframe(k, hide_index=True, width="stretch")
        t1, t2, t3 = st.tabs(["Payments that moved", "Patterns", "Rules"])
        with t1:
            m = diff.movement
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Fixed", len(m["fixed"]))
            a2.metric("Regressed", len(m["regressed"]))
            a3.metric("Still failing", len(m["still_failing"]))
            a4.metric("Other verdict changes", len(m["changed"]))
            for key, title in (("regressed", "Regressed (was fine, now mismatching)"), ("fixed", "Fixed"), ("still_failing", "Still failing")):
                if m[key]:
                    with st.expander(f"{title} — {len(m[key])}", expanded=key == "regressed"):
                        st.write(", ".join(m[key][:300]) + (" …" if len(m[key]) > 300 else ""))
        with t2:
            for key, title in (("new", "New patterns"), ("persisting", "Still present"), ("resolved", "Resolved")):
                items = diff.patterns[key]
                st.markdown(f"**{title}** ({len(items)})")
                for p in items:
                    extra = f" (was {p['count_a']})" if "count_a" in p else ""
                    st.markdown(f"- {ui.CATEGORY_LABEL.get(p['category'], p['category'])}: {p['count']} payment(s){extra}, rules {', '.join(p['rules'])}")
        with t3:
            sym = {"UNTESTED": "– not exercised", "INVALIDATED": "✕ invalidated", "VALIDATED": "✓ validated"}
            st.dataframe(pd.DataFrame([{"Rule": r["id"], "What it checks": r["title"], "A": sym[r["a_status"]], "B": sym[r["b_status"]],
                                        "Mismatches A": r["a_mismatch"], "Mismatches B": r["b_mismatch"], "Change": r["change"]} for r in diff.rules]),
                         hide_index=True, width="stretch", height=36 + 35 * len(diff.rules))

    def p_rules() -> None:
        ui.page_header("Rules", "What “the same” means. Each rule is one thing the migration has to preserve.")
        spec = ctx.spec()
        t1, t2, t3 = st.tabs(["Latest results", "Rule library", "Add your own rule"])
        with t1:
            picked = run_picker("ru_pick")
            if picked:
                sm, run = picked
                st.dataframe(ui.rules_df(run.rule_report), hide_index=True, width="stretch", height=36 + 35 * len(run.rule_report))
                st.caption("M-rules must be preserved from old to new. N-rules cover the new features: they either explain a difference "
                           "or check that the new behaviour is correct.")
            else:
                ui.empty_state("No runs yet", "Rule results appear after a run.")
        with t2:
            st.markdown("**Field mapping rules**")
            st.dataframe(pd.DataFrame([{"Rule": r["id"] + (" (custom)" if r.get("custom") else ""), "What it checks": r["title"], "How compared": r["compare"],
                                        "Applies when": r["applies"].replace("_", " "), "Old field": r["old_ref"], "New field": r["new_ref"]}
                                       for r in spec.mapping_rules]), hide_index=True, width="stretch", height=36 + 35 * len(spec.mapping_rules))
            st.markdown("**New features it knows about**")
            st.dataframe(pd.DataFrame([{"Id": f["id"], "Feature": f["title"], "Role": "explains a difference" if f["kind"] == "explains" else "verified on every payment", "Detail": f["note"]}
                                       for f in spec.new_features]), hide_index=True, width="stretch")
            c1, c2, c3 = st.columns(3)
            c1.markdown("**Decisions**")
            c1.json(spec.decision_map)
            c2.markdown("**Reason codes**")
            c2.json(spec.reason_code_map)
            c3.markdown("**Charge bearers**")
            c3.json(spec.charge_bearer_map)
        with t3:
            st.write("Add a field the migration must also preserve. It is checked on every payment in later runs, with no code change.")
            fields = ["payment_id", "amount", "currency", "fee", "settlement_date", "debtor_name", "creditor_name", "debtor_account",
                      "creditor_account", "creditor_bic", "charge_bearer", "remittance"]
            with st.form("add_rule", clear_on_submit=True):
                a, b = st.columns(2)
                title = a.text_input("What it checks", placeholder="Remittance text is carried over")
                field = b.selectbox("Field", fields)
                c, d = st.columns(2)
                how = c.selectbox("How to compare", ["exact", "decimal", "date", "name", "bearer"],
                                  help="exact: identical text · decimal: same number · date: same day · name: allows the new 140-character limit · bearer: via the charge-bearer map")
                when = d.selectbox("Applies when", ["both_accepted", "both_rejected", "always"])
                if st.form_submit_button("Add rule", type="primary"):
                    if not title.strip():
                        st.error("Give the rule a name.")
                    else:
                        custom = store.load_custom_rules()
                        rid = f"C-{len(custom) + 1:03d}"
                        custom.append({"id": rid, "title": title.strip(), "field": field, "compare": how, "applies": when,
                                       "old_ref": field, "new_ref": field})
                        store.save_custom_rules(custom)
                        st.success(f"Added {rid}. It applies from the next run.")
            custom = store.load_custom_rules()
            if custom:
                st.markdown("**Your rules**")
                for r in custom:
                    x, y = st.columns([5, 1])
                    x.write(f"**{r['id']}** · {r['title']} — {r['field']}, {r['compare']}, {r['applies'].replace('_', ' ')}")
                    if y.button("Remove", key=f"rm_{r['id']}"):
                        store.save_custom_rules([c for c in custom if c["id"] != r["id"]])
                        st.rerun()

    def p_settings() -> None:
        ui.page_header("Settings", "Release gate, which services to test, and how history is kept.")
        s = ctx.settings
        t1, t2, t3 = st.tabs(["Release gate", "Services under test", "History and data"])
        with t1:
            st.write("A run is GO only when it stays within both limits. The limits are saved with every run, so old results keep the gate they were judged by.")
            with st.form("gate"):
                a, b = st.columns(2)
                mm = a.number_input("Most mismatches allowed", 0, 100000, int(s["gate"]["max_mismatches"]))
                pp = b.number_input("Lowest parity allowed (%)", 0.0, 100.0, float(s["gate"]["min_parity_pct"]), step=0.5)
                if st.form_submit_button("Save gate", type="primary"):
                    s["gate"] = Gate(int(mm), float(pp)).as_dict()
                    store.save_settings(s)
                    st.success("Saved. It applies to runs you start from now on.")
        with t2:
            dual = agent.key == "dualrun"
            with st.form("env"):
                if dual:
                    st.markdown("**Old service**")
                    ok = st.radio("Old", list(OLD_KINDS), format_func=OLD_KINDS.get, index=list(OLD_KINDS).index(s["old"]["kind"]), label_visibility="collapsed")
                    ou = st.text_input("Old endpoint URL", s["old"]["url"], placeholder="https://wire-old.example/api/payments")
                    oa = st.text_input("Old Authorization header", st.session_state.get("auth_old", ""), type="password",
                                       help="Kept for this browser session only. Never written to disk.")
                else:
                    ok, ou, oa = "standin", "", ""
                    st.caption("The old service is never called by this agent. Its answers come from the recorded traffic you replay.")
                st.markdown("**New service**")
                nk = st.radio("New", list(NEW_KINDS), format_func=NEW_KINDS.get, index=list(NEW_KINDS).index(s["new"]["kind"]), label_visibility="collapsed")
                nu = st.text_input("New endpoint URL", s["new"]["url"], placeholder="https://wire-new.example/api/payments")
                na = st.text_input("New Authorization header", st.session_state.get("auth_new", ""), type="password",
                                   help="Kept for this browser session only. Never written to disk.")
                to = st.number_input("Request timeout (seconds)", 1, 300, int(s["new"]["timeout"]))
                if st.form_submit_button("Save services", type="primary"):
                    if dual:
                        s["old"] = {"kind": ok, "url": ou.strip(), "timeout": int(to)}
                        st.session_state["auth_old"] = oa
                    s["new"] = {"kind": nk, "url": nu.strip(), "timeout": int(to)}
                    st.session_state["auth_new"] = na
                    store.save_settings(s)
                    st.success("Saved.")
            if dual:
                st.warning("Sending requests to a live production payment service creates real payments. Point the old side at a test or shadow environment.")
        with t3:
            runs = store.list_runs()
            a, b, c = st.columns(3)
            a.metric("Saved runs", len(runs))
            b.metric("Disk used", f"{store.disk_bytes() / 1_048_576:.1f} MB")
            c.metric("Stored in", str(store.home.name))
            st.caption("On Streamlit Community Cloud, saved runs are lost whenever the app restarts or sleeps. Download a history bundle "
                       "before that happens and upload it again afterwards.")
            x, y = st.columns(2)
            x.download_button("Download history bundle", store.export_bundle(), f"{agent.key}-history.zip", "application/zip", width="stretch")
            up = y.file_uploader("Restore a history bundle", type=["zip"], label_visibility="collapsed")
            if up is not None and st.button("Restore runs from this bundle"):
                try:
                    n = store.import_bundle(up.getvalue())
                    st.success(f"Restored {n} run(s).")
                except Exception as exc:  # corrupt zip
                    st.error(f"That file is not a valid history bundle: {exc}")
            with st.expander("Clear all history"):
                if st.button("Delete every saved run", type="primary"):
                    st.toast(f"Deleted {store.clear()} run(s).")
                    st.rerun()
            st.divider()
            st.markdown("**What this is not**")
            st.markdown("- The bundled services are stand-ins, not your code. They compile for Java 8 and 18 but run on whatever JVM is installed.\n"
                        "- pacs.008 is checked structurally, not against the full XSD.\n- Diagnosis is rule-based; no AI model is called.")

    # ------------------------------------------------------------------ navigation
    P = st.Page
    ctx.pages = {
        "run": P(p_workbench, title=agent.run_page_title, icon=":material/play_circle:", url_path="run", default=True),
        "overview": P(p_overview, title="Overview", icon=":material/space_dashboard:", url_path="overview"),
        "payments": P(p_payments, title="Payments", icon=":material/receipt_long:", url_path="payments"),
        "history": P(p_history, title="Run history", icon=":material/history:", url_path="history"),
        "compare": P(p_compare, title="Compare runs", icon=":material/compare_arrows:", url_path="compare"),
        "rules": P(p_rules, title="Rules", icon=":material/rule:", url_path="rules"),
        "settings": P(p_settings, title="Settings", icon=":material/tune:", url_path="settings"),
    }
    g = ctx.pages
    nav = st.navigation({"Run": [g["run"]], "Analyse": [g["overview"], g["payments"]], "History": [g["history"], g["compare"]],
                         "Configure": [g["rules"], g["settings"]]})

    with st.sidebar:
        s = ctx.settings
        runs = store.list_runs()
        new_desc = NEW_KINDS[s["new"]["kind"]]
        old_line = f"<div><span class='dim'>Old</span> {OLD_KINDS[s['old']['kind']]}</div>" if agent.key == "dualrun" else \
            "<div><span class='dim'>Old</span> Recorded traffic</div>"
        st.markdown(f"<div class='sb-card'><b>Environment</b>{old_line}<div><span class='dim'>New</span> {new_desc}</div></div>", unsafe_allow_html=True)
        if runs:
            r = runs[0]
            ok = r["gate"]["passed"]
            st.markdown(f"<div class='sb-card'><b>Latest run</b><div>{ui.esc(r['label'])}</div>"
                        f"<div class='dim'>{fmt_time(r['created_at'])}</div>"
                        f"<div style='margin-top:.35rem'><span class='sb-gate' style='background:{'#E6F4EC' if ok else '#FBE9E7'};"
                        f"color:{'#0E4D31' if ok else '#7C1F19'}'>{'GO' if ok else 'NO-GO'}</span> "
                        f"&nbsp;{r['counts']['mismatch']} mismatches · {r['counts']['parity_pct']}% parity</div></div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='sb-card'><b>No runs yet</b><div class='dim'>Your first run will appear here.</div></div>", unsafe_allow_html=True)
    nav.run()
