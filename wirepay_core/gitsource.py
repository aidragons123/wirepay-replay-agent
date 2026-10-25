"""Build a service straight from a Git repository, branch, tag or commit.

    spec = GitSpec(repo="https://github.com/acme/wire.git", ref="feature/iso20022", main_class="com.acme.Main")
    built = prepare(spec, work_root)           # clone/fetch -> checkout -> compile
    adapter = built.adapter("new")             # same batch protocol as the bundled stand-ins

The old side and the new side are two independent specs, so they can be two branches of one repo,
two tags, two commits, or two different repositories. Nothing is ever pushed.

Compilation is plain `javac` over the sources (optionally preceded by your own build command, e.g.
`mvn -q package`, with the resulting classes/jar given as the classpath). The entry class must speak
the one-JSON-per-line batch protocol the stand-ins use; for anything else, deploy the branch and use
the HTTP option instead.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import javabuild
from .adapters import SubprocessAdapter


class GitError(RuntimeError):
    pass


_REF_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]*$")
_REPO_OK = re.compile(r"^(https://|ssh://|git@|file://|/)[^\s]+$")


class GitAdapter(SubprocessAdapter):
    def describe(self) -> str:
        return self.label


@dataclass
class GitSpec:
    repo: str
    ref: str = "main"                 # branch, tag or commit SHA
    src: str = ""                     # folder holding the .java files; "" = autodetect
    main_class: str = ""              # class with main() that speaks the batch protocol
    release: int = 17                 # javac --release level
    build_cmd: str = ""               # optional, run in the repo root before compiling
    classpath: str = ""               # optional, relative to the repo root; used instead of compiling (jar or classes dir)
    token: str = field(default="", repr=False)   # https access token for private repos; never persisted


@dataclass
class GitBuild:
    spec: GitSpec
    sha: str
    subject: str
    out: Path
    note: str = ""

    @property
    def short(self) -> str:
        return self.sha[:7]

    def label(self, side: str) -> str:
        name = self.spec.repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        return f"{side} (git: {name}@{self.spec.ref} · {self.short})"

    def adapter(self, side: str) -> SubprocessAdapter:
        return GitAdapter(self.out, self.spec.main_class, label=self.label(side))


def validate(spec: GitSpec) -> None:
    if not _REPO_OK.match(spec.repo.strip()):
        raise GitError("Repository must be an https://, ssh://, git@ or local absolute path (file://) address.")
    if not _REF_OK.match(spec.ref.strip()) or ".." in spec.ref:
        raise GitError("Branch, tag or commit contains characters that are not allowed.")
    if not spec.main_class.strip():
        raise GitError("Add the main class that speaks the batch protocol, e.g. com.acme.wire.Main.")
    if spec.src and (Path(spec.src).is_absolute() or ".." in Path(spec.src).parts):
        raise GitError("Source folder must be a relative path inside the repository.")


def _git(args: list[str], cwd: Path | None, token: str = "", timeout: int = 180) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file:https:ssh"}
    pre: list[str] = []
    if token:
        import base64
        pre = ["-c", "http.extraHeader=Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()]
    try:
        p = subprocess.run(["git", *pre, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as e:
        raise GitError("git is not installed on this machine.") from e
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from e
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip().replace(token, "***") if token else (p.stderr or p.stdout).strip()
        raise GitError(f"git {args[0]} failed: {msg[-600:]}")
    return p.stdout


def list_refs(repo: str, token: str = "") -> list[str]:
    """Branch and tag names of a remote, for the picker."""
    if not _REPO_OK.match(repo.strip()):
        raise GitError("Enter a valid repository address first.")
    out = _git(["ls-remote", "--heads", "--tags", "--", repo.strip()], None, token, timeout=60)
    names = []
    for line in out.splitlines():
        ref = line.split("\t")[-1]
        if ref.endswith("^{}"):
            continue
        names.append(ref.replace("refs/heads/", "").replace("refs/tags/", ""))
    return sorted(set(names))


def _checkout(spec: GitSpec, work_root: Path) -> tuple[Path, str, str]:
    key = hashlib.sha1(spec.repo.strip().encode()).hexdigest()[:10]
    clone = work_root / "git" / key
    clone.parent.mkdir(parents=True, exist_ok=True)
    if not (clone / ".git").exists():
        _git(["clone", "--quiet", "--no-checkout", "--", spec.repo.strip(), str(clone)], None, spec.token)
    else:
        _git(["fetch", "--quiet", "--tags", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"], clone, spec.token)
    ref = spec.ref.strip()
    for cand in (f"origin/{ref}", ref):                    # a branch tracks origin; a tag or SHA is used as is
        try:
            sha = _git(["rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}"], clone).strip()
            break
        except GitError:
            sha = ""
    if not sha:
        try:                                               # a commit that is not reachable from a fetched branch
            _git(["fetch", "--quiet", "origin", ref], clone, spec.token)
            sha = _git(["rev-parse", "FETCH_HEAD^{commit}"], clone).strip()
        except GitError:
            raise GitError(f"'{ref}' was not found in {spec.repo}. Check the branch, tag or commit.") from None
    subject = _git(["log", "-1", "--format=%s", sha], clone).strip()
    return clone, sha, subject


def prepare(spec: GitSpec, work_root: Path, side: str = "new") -> GitBuild:
    """Check out the ref into a private clone and compile it. Re-uses an earlier build of the same commit."""
    validate(spec)
    clone, sha, subject = _checkout(spec, work_root)
    wt = work_root / "git" / f"{side}-{sha[:12]}"
    out = work_root / "git" / f"{side}-{sha[:12]}-out"
    stamp_key = f"{spec.src}|{spec.release}|{spec.build_cmd}|{spec.classpath}"
    stamp = out / ".built"
    if stamp.exists() and stamp.read_text() == stamp_key:
        return GitBuild(spec, sha, subject, out / ("cp" if spec.classpath else "classes"))
    if wt.exists():
        subprocess.run(["rm", "-rf", str(wt)], check=False)
    _git(["worktree", "prune"], clone)
    _git(["worktree", "add", "--quiet", "--detach", str(wt), sha], clone)
    if spec.build_cmd.strip():
        try:
            p = subprocess.run(shlex.split(spec.build_cmd), cwd=wt, capture_output=True, text=True, timeout=600)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise GitError(f"Build command failed to run: {e}") from e
        if p.returncode != 0:
            raise GitError(f"Build command failed:\n{(p.stdout + p.stderr)[-1500:]}")
    out.mkdir(parents=True, exist_ok=True)
    if spec.classpath:
        cp = (wt / spec.classpath).resolve()
        if wt.resolve() not in cp.parents and cp != wt.resolve():
            raise GitError("Classpath must stay inside the repository.")
        if not cp.exists():
            raise GitError(f"Classpath '{spec.classpath}' does not exist after the build.")
        keep = out / "cp"                                  # copy so the worktree can be replaced later
        subprocess.run(["rm", "-rf", str(keep)], check=False)
        subprocess.run(["cp", "-r", str(cp), str(keep)], check=True)
        stamp.write_text(stamp_key)
        return GitBuild(spec, sha, subject, keep)
    src_dir = _find_src(wt, spec.src)
    files = [str(p) for p in src_dir.rglob("*.java")]
    if not files:
        raise GitError(f"No .java files under '{src_dir.relative_to(wt)}'. Set the source folder.")
    major = javabuild.javac_major()
    if major is None:
        raise GitError("javac not found - a JDK is required to build from Git.")
    release = min(spec.release, major)
    classes = out / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    flags = ["-source", "1.8", "-target", "1.8"] if major == 8 else ["--release", str(release)]
    p = subprocess.run(["javac", "-nowarn", "-encoding", "UTF-8", *flags, "-d", str(classes), *files],
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise GitError(f"javac failed for {spec.ref}:\n{p.stderr[-1500:]}")
    stamp.write_text(stamp_key)
    note = f"JDK {major} installed; compiled for Java {release} instead of {spec.release}." if release < spec.release else ""
    return GitBuild(spec, sha, subject, classes, note)


def _find_src(root: Path, src: str) -> Path:
    if src:
        d = root / src
        if not d.is_dir():
            raise GitError(f"Source folder '{src}' does not exist in this commit.")
        return d
    for guess in ("src/main/java", "src", "."):
        d = root / guess
        if d.is_dir() and any(d.rglob("*.java")):
            return d
    return root
