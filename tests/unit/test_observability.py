"""Alerts, debug logs, transcripts and redaction."""

import logging

import pytest

from sdlc_agent.observability import Alerter, FileSink, TranscriptWriter, WebhookSink, classify, debug_log
from sdlc_agent.orchestrator.events import EventLog
from sdlc_agent.tools.proc import mask
from sdlc_agent.tools.secret_scan import redact

GH = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"


# ---------------------------------------------------------------- redaction

def test_redact_removes_tokens_and_credential_values():
    text = f"token {GH} and pass" + 'word = "' + "Zq8!kP2#vR9x" + '" ok'
    out = redact(text)
    assert GH not in out and "Zq8!kP2#vR9x" not in out
    assert "[REDACTED:github-token]" in out and "[REDACTED:hardcoded-credential]" in out and out.endswith("ok")


def test_redact_removes_values_of_credential_env_vars(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_TOKEN", "plain-looking-value-123")
    assert redact("sent plain-looking-value-123 upstream") == "sent [REDACTED:MY_SERVICE_TOKEN] upstream"


def test_git_auth_header_is_masked_in_logs():
    arg = "http.extraHeader=Authorization: Basic eC1hY2Nlc3MtdG9rZW46c2VjcmV0"
    assert mask(arg) == "http.extraHeader=Authorization: Basic ***"


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("rec,expected", [
    ({"type": "phase", "phase": "failed"}, ("critical", "Run failed")),
    ({"type": "phase", "phase": "needs_clarification"}, ("warning", "Human input needed")),
    ({"type": "task.failed"}, ("error", "Task failed")),
    ({"type": "gate", "gate": "escalation", "approved": False}, ("error", "Escalation rejected")),
    ({"type": "gate", "gate": "commit", "approved": False}, ("warning", "Gate rejected")),
    ({"type": "gate", "gate": "commit", "approved": True}, None),
    ({"type": "task.done"}, None),
    ({"type": "warn"}, ("warning", "Warning")),
])
def test_classification(rec, expected):
    assert classify(rec) == expected


# ---------------------------------------------------------------- alerter

def test_events_become_alerts_with_filter_and_dedupe(tmp_path):
    alerter = Alerter([FileSink(tmp_path / "alerts.jsonl")], "error", {"run_id": "r1"})
    log = EventLog(tmp_path / "events.jsonl", "r1", quiet=True, alerter=alerter)
    log.emit("warn", "minor thing")                   # below min severity
    log.emit("task.failed", "T1 failed: boom", task="T1")
    log.emit("task.failed", "T1 failed: boom", task="T1")  # duplicate
    log.emit("phase", "run failed", phase="failed")
    assert [a["title"] for a in alerter.sent] == ["Task failed", "Run failed"]
    assert len((tmp_path / "alerts.jsonl").read_text().splitlines()) == 2


def test_webhook_receives_slack_style_payload(webhook):
    alerter = Alerter([WebhookSink(webhook.url)], "warning",
                      {"run_id": "r9", "requirement": "REQ-9", "hint": "sdlc debug -w ws"})
    alerter.alert("critical", "Run failed", f"leaked {GH}?")
    [post] = webhook.posts
    assert "Run failed" in post["text"] and "REQ-9" in post["text"] and "sdlc debug -w ws" in post["text"]
    assert GH not in post["text"]  # alerts are redacted too


def test_webhook_json_format(webhook):
    Alerter([WebhookSink(webhook.url, fmt="json")], "info", {"run_id": "r9"}).alert("info", "PR ready", "x")
    assert webhook.posts[0]["title"] == "PR ready" and webhook.posts[0]["run_id"] == "r9"


def test_broken_webhook_never_breaks_the_run_and_never_logs_the_url(webhook, caplog):
    webhook.fail = True
    sink = WebhookSink(webhook.url, retries=1)
    with caplog.at_level(logging.WARNING):
        Alerter([sink], "warning", {"run_id": "r"}).alert("error", "Task failed", "x")  # must not raise
    assert "alert sink webhook(127.0.0.1) failed" in caplog.text
    assert "abc123secretpath" not in caplog.text


def test_alerter_reads_webhook_from_config(monkeypatch, tmp_path, webhook):
    monkeypatch.setenv("SDLC_ALERT_WEBHOOK", webhook.url)
    monkeypatch.setenv("SDLC_ALERT_MIN_SEVERITY", "error")
    alerter = Alerter.from_env(tmp_path / "a.jsonl", {"run_id": "r"})
    assert [s.name for s in alerter.sinks] == ["file", "webhook(127.0.0.1)"]
    alerter.alert("warning", "ignored", "x")
    alerter.alert("error", "Task failed", "x")
    assert len(webhook.posts) == 1


# ---------------------------------------------------------------- debug log and transcripts

def test_debug_log_captures_and_redacts_then_detaches(tmp_path):
    path = tmp_path / "debug.log"
    logger = logging.getLogger("sdlc_agent.test")
    with debug_log(path):
        logger.debug("calling with %s", GH)
    logger.debug("after the block")
    text = path.read_text()
    assert "calling with [REDACTED:github-token]" in text and GH not in text
    assert "after the block" not in text


def test_transcripts_are_redacted_and_never_overwritten(tmp_path):
    w = TranscriptWriter(tmp_path / "llm")
    a = w.write("coder.T1", 1, "sys", f"prompt with {GH}", "answer")
    b = w.write("coder.T1", 1, "sys", "repair prompt", "answer 2")
    assert a != b and GH not in a.read_text() and "repair prompt" in b.read_text()
