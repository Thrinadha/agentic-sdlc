"""Run the workspace's test suite in an isolated subprocess (no credentials, no network)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .. import config
from ..orchestrator.models import CheckResult
from .proc import run_logged
from .sandbox import safe_env

_SUMMARY = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def run_pytest(root: Path, timeout: int | None = None) -> CheckResult:
    timeout = timeout or config.get_int("SDLC_TEST_TIMEOUT")
    if not any(root.rglob("test_*.py")):
        return CheckResult(name="tests", status="failed", summary="no tests found")
    try:
        proc = run_logged(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rf"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=safe_env(root),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name="tests", status="failed", summary=f"timed out after {timeout}s (SDLC_TEST_TIMEOUT)")
    out = (proc.stdout + "\n" + proc.stderr).strip()
    counts: dict[str, int] = {}
    for n, kind in _SUMMARY.findall(out.splitlines()[-1] if out else ""):
        counts[kind.rstrip("s") if kind.startswith("error") else kind] = int(n)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items()) or "no summary line"
    status = "passed" if proc.returncode == 0 else "failed"
    return CheckResult(name="tests", status=status, summary=summary, details=_tail(out, 6000))


def _tail(text: str, n: int) -> str:
    return text if len(text) <= n else "...\n" + text[-n:]
