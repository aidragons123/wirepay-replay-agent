"""Turn an agent.yaml into ready-to-use OLD / NEW adapters (building the bundled stand-ins on demand)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import javabuild
from .adapters import Adapter, SubprocessAdapter, from_config

OLD_MAIN = "com.bank.wire.legacy.Main"
NEW_MAIN = "com.bank.wire.modern.Main"


def standin_adapters(root: Path, parity_fix: bool = False) -> tuple[Adapter, Adapter, list[str]]:
    """Compile (if needed) and wrap the bundled stand-in services. Old = Java 8 target, new = Java 18 target."""
    java_root, build_root = root / "java", root / "build"
    old_b = javabuild.build("old", java_root, build_root, 8)
    new_b = javabuild.build("new", java_root, build_root, 18)
    notes = [n for n in (old_b.note, new_b.note) if n]
    old = SubprocessAdapter(old_b.out_dir, OLD_MAIN, label="old (stand-in, Java 8 target)")
    new = SubprocessAdapter(new_b.out_dir, NEW_MAIN, label="new (stand-in, Java 18 target)",
                            jvm_args=["-Dwirepay.parityFix=true"] if parity_fix else [])
    return old, new, notes


def adapters_from_config(cfg: dict[str, Any], root: Path) -> tuple[Adapter, Adapter, list[str]]:
    old_cfg, new_cfg = cfg.get("old", {"type": "standin"}), cfg.get("new", {"type": "standin"})
    notes: list[str] = []
    s_old = s_new = None
    if old_cfg.get("type", "standin") == "standin" or new_cfg.get("type", "standin") == "standin":
        s_old, s_new, notes = standin_adapters(root, bool(new_cfg.get("parity_fix", False)))
    old = s_old if old_cfg.get("type", "standin") == "standin" else from_config(old_cfg, "old", root)
    new = s_new if new_cfg.get("type", "standin") == "standin" else from_config(new_cfg, "new", root)
    return old, new, notes  # type: ignore[return-value]
