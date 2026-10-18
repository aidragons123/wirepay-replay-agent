"""Altair charts. One restrained palette; every series is also distinguishable by label, never by colour alone."""
from __future__ import annotations

from collections import Counter
from typing import Any

import altair as alt
import pandas as pd

from .engine import RunResult

MATCH, EXPLAINED, BAD = "#1B8A5A", "#4F6D8F", "#C8372D"
INK, MUTED, LINE = "#16203A", "#6B7790", "#DDE3EC"
VERDICT_ORDER = ["Exact match", "Explained difference", "Mismatch"]
VERDICT_SCALE = alt.Scale(domain=VERDICT_ORDER, range=[MATCH, EXPLAINED, BAD])
LABEL = {"MATCH": "Exact match", "EXPECTED_DIFFERENCE": "Explained difference", "MISMATCH": "Mismatch"}


def _style(ch: alt.Chart | alt.LayerChart, height) -> alt.Chart:
    return (ch.properties(height=height).configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor="#EEF1F6", domainColor=LINE, tickColor=LINE,
                            labelFontSize=12, titleFontSize=12)
            .configure_legend(labelColor=INK, titleColor=MUTED, orient="bottom", symbolType="square", labelFontSize=12))


def rules_chart(run: RunResult) -> alt.Chart | None:
    rows = [{"rule": f"{r['id']} {r['title']}", "kind": k, "count": r[key]}
            for r in run.rule_report if r["kind"] == "mapping rule"
            for k, key in (("Explained difference", "expected"), ("Mismatch", "mismatch")) if r[key]]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    ch = alt.Chart(df).mark_bar(cornerRadiusEnd=2, height=16).encode(
        y=alt.Y("rule:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
        x=alt.X("count:Q", title="Payments", axis=alt.Axis(tickMinStep=1)),
        color=alt.Color("kind:N", scale=alt.Scale(domain=["Explained difference", "Mismatch"], range=[EXPLAINED, BAD]), title=None),
        tooltip=["rule", "kind", "count"])
    return _style(ch, alt.Step(34))


def breakdown_chart(run: RunResult, dim: str) -> alt.Chart:
    """Verdict mix per currency / charge bearer / old decision."""
    def key(r) -> str:
        if dim == "Currency":
            return str(r.request.get("currency") or "(missing)")
        if dim == "Charge bearer":
            return str(r.request.get("chargeBearer") or "SHA")
        return str(r.old_response.get("status") or "?")
    cnt: Counter = Counter((key(r), LABEL[r.verdict]) for r in run.results)
    df = pd.DataFrame([{"group": g, "verdict": v, "count": n} for (g, v), n in cnt.items()])
    ch = alt.Chart(df).mark_bar(cornerRadiusEnd=2, height=18).encode(
        y=alt.Y("group:N", title=None, sort="-x"),
        x=alt.X("count:Q", title="Payments", stack="zero"),
        color=alt.Color("verdict:N", scale=VERDICT_SCALE, title=None, sort=VERDICT_ORDER),
        order=alt.Order("verdict:N", sort="ascending"),
        tooltip=["group", "verdict", "count"])
    return _style(ch, alt.Step(30))


def trend_chart(runs: list[dict[str, Any]], gate_min: float | None = None) -> alt.Chart | None:
    """Parity over time. Each point is one run; a red point failed its gate."""
    pts = [r for r in runs if r["counts"]["total"] >= 10][::-1][-30:]
    if len(pts) < 1:
        return None
    df = pd.DataFrame([{"when": r["created_at"], "label": r["label"], "parity": r["counts"]["parity_pct"],
                        "mismatches": r["counts"]["mismatch"], "gate": "GO" if r["gate"]["passed"] else "NO-GO"} for r in pts])
    df["when"] = pd.to_datetime(df["when"]).dt.tz_localize(None)
    base = alt.Chart(df).encode(x=alt.X("when:T", title=None, axis=alt.Axis(format="%d %b %H:%M", labelOverlap=True)))
    ysc = alt.Y("parity:Q", title="Parity %", scale=alt.Scale(domain=[max(0, min(df["parity"].min(), gate_min or 100) - 3), 100.5]))
    line = base.mark_line(color="#9AA6BC", strokeWidth=2).encode(y=ysc)
    dots = base.mark_point(filled=True, size=110, opacity=1).encode(
        y=ysc, color=alt.Color("gate:N", scale=alt.Scale(domain=["GO", "NO-GO"], range=[MATCH, BAD]), title="Release gate"),
        shape=alt.Shape("gate:N", scale=alt.Scale(domain=["GO", "NO-GO"], range=["circle", "diamond"]), legend=None),
        tooltip=["label", "parity", "mismatches", "gate", alt.Tooltip("when:T", format="%d %b %Y %H:%M")])
    layers = [line, dots]
    if gate_min is not None:
        layers.insert(0, alt.Chart(pd.DataFrame({"y": [gate_min]})).mark_rule(strokeDash=[4, 4], color=MUTED).encode(y=alt.Y("y:Q", scale=alt.Scale(domain=[max(0, min(df["parity"].min(), gate_min) - 3), 100.5]))))
    return _style(alt.layer(*layers), 230)


def compare_chart(label_a: str, a: dict, label_b: str, b: dict) -> alt.Chart:
    rows = []
    for label, c in ((label_a, a), (label_b, b)):
        for key, v in (("match", "Exact match"), ("expected", "Explained difference"), ("mismatch", "Mismatch")):
            rows.append({"run": label, "verdict": v, "count": c[key]})
    ch = alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadiusEnd=2, size=28).encode(
        y=alt.Y("run:N", title=None, sort="ascending"),
        x=alt.X("count:Q", title="Payments", stack="zero"),
        color=alt.Color("verdict:N", scale=VERDICT_SCALE, title=None, sort=VERDICT_ORDER),
        order=alt.Order("verdict:N", sort="ascending"), tooltip=["run", "verdict", "count"])
    return _style(ch, alt.Step(56))
