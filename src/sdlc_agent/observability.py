"""Debug logging and alerting.

Debug log
    Every run writes ``.sdlc/runs/<id>/debug.log`` at DEBUG level: git and subprocess commands with exit
    codes and durations, LLM calls, routing decisions, gate requests. ``-v`` also prints it to the console.
    ``--debug`` additionally saves each LLM prompt and answer under ``.sdlc/runs/<id>/llm/``.
    Everything written passes through ``redact`` first, so secrets never reach a log file.

Alerts
    Events that need attention (run failed, task failed, a gate rejected, human input needed, security
    warnings) become alerts. Sinks:
      * ``alerts.jsonl`` in the run directory (always)
      * a webhook, when ``SDLC_ALERT_WEBHOOK`` is set: Slack/Teams/Mattermost-style ``{"text": ...}``
        (``SDLC_ALERT_FORMAT=slack``, default) or the raw alert JSON (``SDLC_ALERT_FORMAT=json``)
    ``SDLC_ALERT_MIN_SEVERITY`` = info | warning (default) | error | critical.
    A failing sink is logged and never breaks the run.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from . import config
from .http import http_open
from .tools.secret_scan import redact

log = logging.getLogger(__name__)
ROOT_LOGGER = "sdlc_agent"
SEVERITY = {"info": 0, "warning": 1, "error": 2, "critical": 3}
ICON = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}


# ====================================================================== logging


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


_FORMAT = "%(asctime)s %(levelname)-7s %(threadName)-10s %(name)s: %(message)s"


def setup_console(verbose: bool) -> None:
    """Console handler for the CLI: warnings by default, everything with ``-v``."""
    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(logging.DEBUG)
    if not any(getattr(h, "_sdlc_console", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._sdlc_console = True
        handler.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    for h in root.handlers:
        if getattr(h, "_sdlc_console", False):
            h.setLevel(logging.DEBUG if verbose else logging.WARNING)


@contextmanager
def debug_log(path: Path) -> Iterator[None]:
    """Write DEBUG logs of everything in this block to ``path`` (appending, so resumed runs keep history)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger(ROOT_LOGGER)
    root.setLevel(logging.DEBUG)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(RedactingFormatter(_FORMAT))
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


class TranscriptWriter:
    """Saves redacted LLM prompts and answers (``--debug``)."""

    def __init__(self, directory: Path):
        self.dir = directory
        self._lock = threading.Lock()

    def write(self, key: str, attempt: int, system: str, prompt: str, answer: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            path = self.dir / f"{key}.attempt{attempt}.txt"
            n = 2
            while path.exists():  # repairs / retries of the same key keep every exchange
                path = self.dir / f"{key}.attempt{attempt}.{n}.txt"
                n += 1
            path.write_text(redact(f"=== SYSTEM\n{system}\n\n=== PROMPT\n{prompt}\n\n=== ANSWER\n{answer}\n"),
                            encoding="utf-8")
        return path


# ====================================================================== alerts


def classify(rec: dict) -> tuple[str, str] | None:
    """(severity, title) for events that need attention, else None."""
    kind, phase = rec.get("type"), rec.get("phase")
    if kind == "phase" and phase == "failed":
        return "critical", "Run failed"
    if kind == "phase" and phase == "needs_clarification":
        return "warning", "Human input needed"
    if kind == "phase" and phase == "rejected":
        return "warning", "Plan rejected"
    if kind == "phase" and phase == "pr_ready":
        return "info", "PR ready for review"
    if kind == "task.failed":
        return "error", "Task failed"
    if kind == "gate" and rec.get("approved") is False:
        return ("error", "Escalation rejected") if rec.get("gate") == "escalation" else ("warning", "Gate rejected")
    if kind == "gate" and rec.get("gate") == "escalation":
        return "warning", "Escalation approved by a human"
    if kind in ("warn", "error"):
        return ("error" if kind == "error" else "warning"), "Warning"
    return None


class FileSink:
    name = "file"

    def __init__(self, path: Path):
        self.path = path

    def send(self, alert: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(alert) + "\n")


class WebhookSink:
    def __init__(self, url: str, fmt: str = "slack", timeout: float = 5.0, retries: int = 2):
        self.url = url
        self.fmt = fmt
        self.timeout = timeout
        self.retries = retries
        self.name = f"webhook({urlsplit(url).hostname})"  # never log the full URL: it is a credential

    def payload(self, alert: dict) -> dict:
        if self.fmt == "json":
            return alert
        text = (f"{ICON[alert['severity']]} *{alert['title']}* [{alert['severity']}] "
                f"{alert.get('requirement', '')} run `{alert['run_id']}`\n{alert['message']}")
        if alert.get("hint"):
            text += f"\nNext: `{alert['hint']}`"
        return {"text": text}

    def send(self, alert: dict) -> None:
        body = json.dumps(self.payload(alert)).encode()
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with http_open(req, timeout=self.timeout) as resp:
                    resp.read()
                return
            except Exception as e:  # noqa: BLE001 - retried, then reported by the Alerter
                last = e
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"{type(last).__name__}: {last}")


class Alerter:
    def __init__(self, sinks: list, min_severity: str = "warning", context: dict | None = None):
        self.sinks = sinks
        self.min = SEVERITY.get(min_severity, 1)
        self.context = context or {}
        self.sent: list[dict] = []
        self._seen: set[tuple] = set()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, alerts_file: Path, context: dict | None = None) -> Alerter:
        sinks: list = [FileSink(alerts_file)]
        url = config.raw("SDLC_ALERT_WEBHOOK")
        if url:
            sinks.append(WebhookSink(url, config.get("SDLC_ALERT_FORMAT")))
        return cls(sinks, config.get("SDLC_ALERT_MIN_SEVERITY"), context)

    def observe(self, rec: dict) -> None:
        verdict = classify(rec)
        if verdict is None:
            return
        severity, title = verdict
        self.alert(severity, title, rec.get("message", ""), ts=rec.get("ts"))

    def alert(self, severity: str, title: str, message: str, ts: float | None = None) -> dict | None:
        if SEVERITY[severity] < self.min:
            return None
        alert = {"ts": ts or round(time.time(), 3), "severity": severity, "title": title,
                 "message": redact(message[:2000]), **self.context}
        with self._lock:
            key = (severity, title, alert["message"])
            if key in self._seen:  # the same alert twice in one run is noise
                return None
            self._seen.add(key)
            self.sent.append(alert)
        for sink in self.sinks:
            try:
                sink.send(alert)
            except Exception as e:  # noqa: BLE001 - alerting must never break the run
                log.warning("alert sink %s failed: %s", sink.name, e)
        return alert
