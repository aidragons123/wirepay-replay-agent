"""Release gate: a run is GO or NO-GO against thresholds you set once and that are stored with every run."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Gate:
    max_mismatches: int = 0
    min_parity_pct: float = 100.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]

    @property
    def label(self) -> str:
        return "GO" if self.passed else "NO-GO"


def evaluate(counts: dict, gate: Gate) -> GateResult:
    reasons = []
    if counts["mismatch"] > gate.max_mismatches:
        reasons.append(f"{counts['mismatch']} mismatching payment(s); the gate allows {gate.max_mismatches}")
    if counts["parity_pct"] < gate.min_parity_pct:
        reasons.append(f"parity {counts['parity_pct']}% is below the required {gate.min_parity_pct}%")
    if not counts["total"]:
        reasons.append("no payments were compared")
    return GateResult(not reasons, reasons)
