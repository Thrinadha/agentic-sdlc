"""Structured, tamper-evident run log (JSONL) plus a readable console line for each event.

Each record carries ``prev`` (the previous record's hash) and ``hash`` (SHA-256 over the record), so
editing, deleting or reordering any line breaks the chain from that point on. The chain head is written
into each commit message (``Audit-Log-Head``), which anchors the log in git history: rewriting the log
and recomputing the chain would no longer match the commit. ``verify_log`` checks a log file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
log = logging.getLogger(__name__)

_ICONS = {
    "phase": "==>",
    "task.start": " ->",
    "task.done": " ok",
    "task.failed": " !!",
    "task.retry": " ↻ ",
    "validate": " ✓?",
    "gate": "[G]",
    "llm": "  ·",
    "warn": " ⚠ ",
    "error": " ✖ ",
    "info": "  i",
}


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class EventLog:
    def __init__(self, path: Path | None, run_id: str, quiet: bool = False, alerter=None):
        self.path = path
        self.run_id = run_id
        self.quiet = quiet
        self.alerter = alerter  # observability.Alerter: turns events that need attention into alerts
        self.t0 = time.time()
        self._lock = threading.Lock()
        self.head = GENESIS
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            records = self.read()
            if records:  # resuming: continue the existing chain
                self.head = records[-1].get("hash", GENESIS)

    def emit(self, kind: str, message: str, **data: Any) -> None:
        with self._lock:
            rec = {"ts": round(time.time(), 3), "run_id": self.run_id, "type": kind, "message": message,
                   **data, "prev": self.head}
            rec["hash"] = _digest(rec)
            self.head = rec["hash"]
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
            if not self.quiet and kind != "llm":
                elapsed = time.time() - self.t0
                icon = _ICONS.get(kind, "   ")
                console(f"[{elapsed:6.1f}s] {icon} {message}")
        log.debug("event %s: %s %s", kind, message, {k: v for k, v in data.items() if k != "error"} or "")
        if self.alerter is not None:  # outside the lock: a slow webhook must not stall other tasks
            self.alerter.observe(rec)

    def read(self) -> list[dict]:
        if not self.path or not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]


def verify_log(path: Path) -> tuple[bool, str]:
    """(ok, message). Fails at the first record whose hash or link to its predecessor is wrong."""
    prev = GENESIS
    lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for n, line in enumerate(lines, start=1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return False, f"line {n}: not valid JSON"
        if rec.get("prev") != prev:
            return False, f"line {n}: chain broken (a record before it was changed, removed or reordered)"
        if rec.get("hash") != _digest(rec):
            return False, f"line {n}: content does not match its hash (record was edited)"
        prev = rec["hash"]
    return True, f"{len(lines)} records, chain intact, head {prev[:16]}"


def console(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:  # legacy Windows consoles
        print(msg.encode("ascii", "replace").decode(), flush=True)
    sys.stdout.flush()
