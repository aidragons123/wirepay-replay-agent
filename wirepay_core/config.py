"""Spec + agent configuration loading."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent
DEFAULT_SPEC = PKG_DIR / "spec" / "mapping_rules.yaml"


@dataclass
class Spec:
    decision_map: dict[str, str]
    reason_code_map: dict[str, str]
    charge_bearer_map: dict[str, str]
    mapping_rules: list[dict[str, Any]]
    new_features: list[dict[str, Any]]
    path: Path = DEFAULT_SPEC

    def rule(self, rule_id: str) -> dict[str, Any] | None:
        return next((r for r in self.mapping_rules if r["id"] == rule_id), None)

    def feature(self, fid: str) -> dict[str, Any] | None:
        return next((f for f in self.new_features if f["id"] == fid), None)


REQUIRED_RULE_KEYS = {"id", "title", "field", "compare", "applies"}


def load_spec(path: str | Path | None = None, extra_rules: list[dict[str, Any]] | None = None) -> Spec:
    """Load the mapping spec. `extra_rules` are user-added (custom) rules appended after the built-in ones."""
    p = Path(path) if path else DEFAULT_SPEC
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    custom = []
    for r in extra_rules or []:
        missing = REQUIRED_RULE_KEYS - r.keys()
        if missing:
            raise ValueError(f"custom rule {r.get('id', '?')} is missing {sorted(missing)}")
        custom.append({**r, "custom": True})
    return Spec(
        decision_map=raw["decision_map"],
        reason_code_map=raw["reason_code_map"],
        charge_bearer_map=raw["charge_bearer_map"],
        mapping_rules=list(raw["mapping_rules"]) + custom,
        new_features=raw["new_features"],
        path=p,
    )


def load_agent_config(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
