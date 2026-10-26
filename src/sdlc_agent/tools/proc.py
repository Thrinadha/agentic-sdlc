"""``subprocess.run`` with debug logging: command, exit code, duration and output tail of every call."""

from __future__ import annotations

import logging
import re
import subprocess
import time

log = logging.getLogger(__name__)
_AUTH_ARG = re.compile(r"(?i)(extraheader=authorization:\s*\w+\s+)\S+")


def mask(arg: str) -> str:
    return _AUTH_ARG.sub(r"\1***", str(arg))


def run_logged(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    shown = " ".join(mask(a) for a in cmd)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, **kwargs)  # noqa: S603 - argument list, never a shell string
    except subprocess.TimeoutExpired:
        log.debug("TIMEOUT after %.1fs: %s", time.time() - t0, shown)
        raise
    level = logging.DEBUG
    log.log(level, "rc=%s in %.2fs: %s", proc.returncode, time.time() - t0, shown)
    if proc.returncode != 0 and kwargs.get("capture_output"):
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
        log.debug("output tail:\n%s", tail)
    return proc
