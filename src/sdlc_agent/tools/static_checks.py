"""Deterministic validation: syntax, lint, unsafe patterns, security analysis, dependency audit and API
contract conformance.

Every check that runs generated code does so in a sandboxed subprocess (``tools/sandbox.py``): no
credentials in its environment and no outbound network. The orchestrator never imports generated code.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from .. import config
from ..orchestrator.models import CheckResult
from .proc import run_logged
from .sandbox import safe_env
from .workspace import SKIP_DIRS, Workspace

UNSAFE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eval/exec", re.compile(r"(?<![\w.])(eval|exec)\s*\(")),
    ("os.system", re.compile(r"\bos\.system\s*\(")),
    ("shell=True", re.compile(r"shell\s*=\s*True")),
    ("pickle.loads", re.compile(r"\bpickle\.loads?\s*\(")),
    ("yaml.load without SafeLoader", re.compile(r"\byaml\.load\s*\((?![^)]*SafeLoader)")),
    ("TLS verification disabled", re.compile(r"verify\s*=\s*False")),
    ("SQL built with f-string", re.compile(r"""execute\(\s*f["']""")),
]


def _installed(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def compile_check(root: Path) -> CheckResult:
    proc = run_logged(
        [sys.executable, "-m", "compileall", "-q", "-x", r"[\\/](\.venv|\.git|\.sdlc)[\\/]", "."],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120, env=safe_env(root),
    )
    if proc.returncode == 0:
        return CheckResult(name="syntax", status="passed", summary="all Python files compile")
    return CheckResult(name="syntax", status="failed", summary="syntax errors", details=proc.stdout[-4000:])


def lint_check(root: Path) -> CheckResult:
    if not _installed("ruff"):
        return CheckResult(name="lint", status="skipped", summary="ruff not installed (pip install -e .[dev])")
    args = [sys.executable, "-m", "ruff", "check", "--output-format", "concise", "."]
    pyproject = root / "pyproject.toml"
    has_cfg = pyproject.exists() and "[tool.ruff" in pyproject.read_text(encoding="utf-8")
    if not has_cfg:
        args += ["--isolated", "--select", "E,F,W,B", "--line-length", "120"]
    proc = run_logged(args, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120,
                          env=safe_env(root))
    if proc.returncode == 0:
        return CheckResult(name="lint", status="passed", summary="ruff: no issues")
    issues = [line for line in proc.stdout.splitlines() if re.match(r"^\S+:\d+:\d+:", line)]
    return CheckResult(name="lint", status="failed", summary=f"ruff: {len(issues)} issue(s)",
                       details="\n".join(issues[:60]))


def unsafe_code_check(ws: Workspace) -> CheckResult:
    hits = []
    for rel in ws.files({".py"}):
        for i, line in enumerate(ws.read(rel).splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for name, rx in UNSAFE_PATTERNS:
                if rx.search(line):
                    hits.append(f"{rel}:{i} {name}")
    if not hits:
        return CheckResult(name="unsafe-code", status="passed", summary="no unsafe patterns")
    return CheckResult(name="unsafe-code", status="failed", summary=f"{len(hits)} unsafe pattern(s)",
                       details="\n".join(hits))


def security_check(root: Path) -> CheckResult:
    """Bandit static security analysis of application code (medium+ severity and confidence)."""
    if not _installed("bandit"):
        return CheckResult(name="security", status="skipped", summary="bandit not installed (pip install -e .[dev])")
    targets = sorted(p.name for p in root.iterdir()
                     if p.name not in SKIP_DIRS and p.name != "tests" and not p.name.startswith(".")
                     and (p.is_dir() or p.suffix == ".py"))
    if not targets:
        return CheckResult(name="security", status="skipped", summary="no application code")
    proc = run_logged(
        [sys.executable, "-m", "bandit", "-q", "-r", *targets, "-f", "json", "-ll", "-ii"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=180, env=safe_env(root),
    )
    try:
        results = json.loads(proc.stdout or "{}").get("results", [])
    except json.JSONDecodeError:
        return CheckResult(name="security", status="failed", summary="bandit did not run",
                           details=(proc.stderr or proc.stdout)[-3000:])
    if not results:
        return CheckResult(name="security", status="passed", summary="bandit: no medium/high issues")
    lines = [f"{r['filename'].replace(os.sep, '/').lstrip('./')}:{r['line_number']} {r['test_id']} "
             f"[{r['issue_severity'].lower()}] {r['issue_text']}" for r in results]
    return CheckResult(name="security", status="failed", summary=f"bandit: {len(results)} issue(s)",
                       details="\n".join(lines[:60]))


def _declared_dependencies(pyproject: Path) -> list[str]:
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    return re.findall(r"""["']([^"']+)["']""", m.group(1)) if m else []


def dependency_audit_check(root: Path) -> CheckResult:
    """Known vulnerabilities (OSV/PyPI advisories) in the dependencies the generated project declares.

    Needs network access, so it is opt-in: set ``SDLC_DEPENDENCY_AUDIT=1`` (CI does). The audit resolves
    published packages only; it never builds or runs the generated project.
    """
    if not config.get_bool("SDLC_DEPENDENCY_AUDIT"):
        return CheckResult(name="dependencies", status="skipped", summary="set SDLC_DEPENDENCY_AUDIT=1 to audit")
    if not _installed("pip_audit"):
        return CheckResult(name="dependencies", status="skipped", summary="pip-audit not installed")
    pyproject = root / "pyproject.toml"
    deps = _declared_dependencies(pyproject) if pyproject.exists() else []
    if not deps:
        return CheckResult(name="dependencies", status="skipped", summary="no declared dependencies")
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        req.write_text("\n".join(deps) + "\n", encoding="utf-8")
        try:
            proc = run_logged([sys.executable, "-m", "pip_audit", "-r", str(req), "-f", "json",
                                   "--progress-spinner", "off"],
                                  capture_output=True, text=True, encoding="utf-8", timeout=600)
        except subprocess.TimeoutExpired:
            return CheckResult(name="dependencies", status="skipped", summary="pip-audit timed out")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return CheckResult(name="dependencies", status="skipped", summary="pip-audit could not run (network?)",
                           details=proc.stderr[-2000:])
    vulns = [f"{d['name']} {d['version']}: {v['id']}" + (f" (fix: {', '.join(v['fix_versions'])})"
                                                         if v.get("fix_versions") else "")
             for d in data.get("dependencies", []) for v in d.get("vulns", [])]
    if not vulns:
        return CheckResult(name="dependencies", status="passed",
                           summary=f"pip-audit: no known vulnerabilities in {len(deps)} declared dependencies")
    return CheckResult(name="dependencies", status="failed", summary=f"pip-audit: {len(vulns)} vulnerability(ies)",
                       details="\n".join(vulns))


_ROUTES_SCRIPT = r"""
import importlib, json, sys
mod, fn = sys.argv[1].split(":")
app = getattr(importlib.import_module(mod), fn)()
spec = app.openapi()
print(json.dumps(sorted(f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m in ops)))
"""


def contract_check(root: Path, contract: str | None, app_factory: str | None) -> CheckResult:
    """Every operation in the OpenAPI contract is served by the app, and nothing undocumented is."""
    if not contract or not app_factory or not (root / contract).exists():
        return CheckResult(name="contract", status="skipped", summary="no API contract declared")
    try:
        spec = yaml.safe_load((root / contract).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return CheckResult(name="contract", status="failed", summary=f"{contract} is not valid YAML",
                           details=f"{contract}: {e}")
    declared = {f"{m.upper()} {p}" for p, ops in (spec.get("paths") or {}).items() for m in ops
                if m.lower() in {"get", "post", "put", "patch", "delete"}}
    # Run from a scratch directory: importing the app may create files (e.g. a SQLite database relative to
    # the working directory), and validation must not leave side effects in the workspace.
    with tempfile.TemporaryDirectory(prefix="sdlc-contract-") as scratch:
        proc = run_logged(
            [sys.executable, "-c", _ROUTES_SCRIPT, app_factory], cwd=scratch, capture_output=True, text=True,
            encoding="utf-8", timeout=60, env=safe_env(root),
        )
    if proc.returncode != 0:
        return CheckResult(name="contract", status="failed", summary="could not load the app",
                           details=proc.stderr[-3000:])
    served = set(json.loads(proc.stdout.strip().splitlines()[-1]))
    missing, extra = sorted(declared - served), sorted(served - declared)
    if not missing and not extra:
        return CheckResult(name="contract", status="passed",
                           summary=f"{len(declared)} operations match {contract}")
    details = "\n".join([*(f"in contract, not served: {x}" for x in missing),
                         *(f"served, not in contract: {x}" for x in extra)])
    return CheckResult(name="contract", status="failed", summary="app and contract disagree", details=details)
