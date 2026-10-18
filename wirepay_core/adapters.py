"""How the agents talk to the OLD and NEW payment services.

SubprocessAdapter  - runs a Java main class that speaks the one-JSON-per-line batch protocol
                     (the bundled stand-ins do; wrap your own service the same way if you like).
HttpAdapter        - POSTs each request as JSON to a deployed endpoint and reads JSON back.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AdapterError(RuntimeError):
    pass


class Adapter:
    name = "adapter"

    def run(self, requests: list[dict[str, Any]], on_progress=None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


@dataclass
class SubprocessAdapter(Adapter):
    classpath: Path
    main_class: str
    java_bin: str = "java"
    jvm_args: list[str] = field(default_factory=list)
    label: str = "java"
    timeout: int = 300

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.label

    def run(self, requests: list[dict[str, Any]], on_progress=None) -> list[dict[str, Any]]:
        if not requests:
            return []
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
        cmd = [self.java_bin, "-Dfile.encoding=UTF-8", *self.jvm_args,
               "-cp", str(self.classpath), self.main_class]
        try:
            p = subprocess.run(cmd, input=payload.encode("utf-8"), capture_output=True, timeout=self.timeout)
        except FileNotFoundError as e:
            raise AdapterError(f"{self.java_bin!r} not found: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"{self.label} timed out after {self.timeout}s") from e
        if p.returncode != 0:
            raise AdapterError(f"{self.label} exited {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-800:]}")
        lines = [ln for ln in p.stdout.decode("utf-8").splitlines() if ln.strip()]
        if len(lines) != len(requests):
            raise AdapterError(f"{self.label} returned {len(lines)} responses for {len(requests)} requests")
        if on_progress:
            on_progress(len(requests), len(requests))
        return [json.loads(ln) for ln in lines]

    def describe(self) -> str:
        extra = f" {' '.join(self.jvm_args)}" if self.jvm_args else ""
        return f"{self.label}: {self.java_bin}{extra} -cp {self.classpath} {self.main_class}"


@dataclass
class HttpAdapter(Adapter):
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    workers: int = 8
    label: str = "http"

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.label

    def _one(self, req: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(req, ensure_ascii=False).encode("utf-8")
        h = {"Content-Type": "application/json", **self.headers}
        rq = urllib.request.Request(self.url, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(rq, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise AdapterError(f"{self.label} call failed for {req.get('requestId')}: {e}") from e

    def run(self, requests: list[dict[str, Any]], on_progress=None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for i, resp in enumerate(ex.map(self._one, requests), start=1):
                out.append(resp)
                if on_progress:
                    on_progress(i, len(requests))
        return out

    def describe(self) -> str:
        return f"{self.label}: POST {self.url}"


def from_config(cfg: dict[str, Any], default_label: str, root: Path) -> Adapter:
    """Build an adapter from an agent.yaml section."""
    kind = cfg.get("type", "subprocess")
    if kind == "http":
        return HttpAdapter(url=cfg["url"], headers=cfg.get("headers", {}),
                           timeout=cfg.get("timeout", 30), workers=cfg.get("workers", 8), label=default_label)
    return SubprocessAdapter(
        classpath=(root / cfg["classpath"]) if not Path(cfg["classpath"]).is_absolute() else Path(cfg["classpath"]),
        main_class=cfg["main_class"], java_bin=cfg.get("java_bin", "java"),
        jvm_args=list(cfg.get("jvm_args", [])), label=default_label)
