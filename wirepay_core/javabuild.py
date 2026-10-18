"""Compile the stand-in Java services (old -> Java 8 target, new -> Java 18 target)."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class JavaBuildError(RuntimeError):
    pass


@dataclass
class BuildInfo:
    side: str
    out_dir: Path
    target: str          # e.g. "--release 8"
    note: str = ""       # set when the requested release could not be honoured
    rebuilt: bool = False


def javac_major() -> int | None:
    try:
        p = subprocess.run(["javac", "-version"], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"javac\s+(?:1\.)?(\d+)", p.stdout + p.stderr)
    return int(m.group(1)) if m else None


def _newest(src_dir: Path) -> float:
    return max((f.stat().st_mtime for f in src_dir.rglob("*.java")), default=0.0)


def build(side: str, java_root: Path, build_root: Path, wanted_release: int, force: bool = False) -> BuildInfo:
    """Compile java_root/<side>/src into build_root/<side>.

    The old side is compiled with --release 8, the new side with --release 18.
    If the installed JDK is older than 18 (e.g. a hosted environment that ships
    JDK 17) the new side falls back to the JDK's own level and says so in `note`.
    """
    major = javac_major()
    if major is None:
        raise JavaBuildError("javac not found - install a JDK (apt-get install default-jdk).")
    src = java_root / side / "src"
    if not any(src.rglob("*.java")):
        raise JavaBuildError(f"No Java sources found under {src}")
    out = build_root / side
    stamp = out / ".built"
    release = min(wanted_release, major)
    note = ""
    if release < wanted_release:
        note = f"JDK {major} installed; compiled the {side} side for Java {release} instead of {wanted_release}."
    if not force and stamp.exists() and stamp.stat().st_mtime >= _newest(src):
        return BuildInfo(side, out, f"--release {release}", note, rebuilt=False)

    out.mkdir(parents=True, exist_ok=True)
    sources = [str(p) for p in src.rglob("*.java")]
    if major == 8:
        flags = ["-source", "1.8", "-target", "1.8"]
    else:
        flags = ["--release", str(release)]
    cmd = ["javac", "-nowarn", "-encoding", "UTF-8", *flags, "-d", str(out), *sources]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        raise JavaBuildError(f"javac failed for {side}:\n{p.stderr[-2000:]}")
    stamp.write_text("ok")
    return BuildInfo(side, out, f"--release {release}", note, rebuilt=True)
