"""The CLI end to end, the way a person uses it.

* a failing run: recovery is exhausted, the escalation is rejected, alerts reach a (local) webhook,
  `sdlc debug` / `logs` / `alerts` / `audit` explain it, and `sdlc resume` retries with fresh attempts
* the brownfield flow driven interactively: a human answers every gate at the terminal
* `sdlc config` and `sdlc doctor`
"""

import builtins
import json

from sdlc_agent.cli import main
from sdlc_agent.tools.git_tool import Git
from sdlc_agent.workflow import PROJECT_ROOT, latest_run_id

REQS = PROJECT_ROOT / "examples" / "requirements"
FAKE_TOKEN = "ghp_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8"


def test_failure_is_alerted_debuggable_and_resumable(tmp_path, monkeypatch, webhook, capsys):
    monkeypatch.setenv("SDLC_ALERT_WEBHOOK", webhook.url)
    req = tmp_path / "failing.md"  # the scenario requirement plus a secret that must never be logged
    req.write_text((REQS / "failing-calculator.md").read_text(encoding="utf-8")
                   + f"\nInternal note: deploy token {FAKE_TOKEN}\n", encoding="utf-8")
    ws = tmp_path / "ws"

    assert main(["implement", str(req), "-w", str(ws), "--policy", "auto", "--debug"]) == 1
    run_dir = ws / ".sdlc" / "runs" / latest_run_id(ws)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "failed" and state["tasks"]["T1"]["attempts"] == 3

    titles = [p["text"] for p in webhook.posts]
    assert any("Escalation rejected" in t for t in titles)
    assert any("Run failed" in t for t in titles)
    assert all("sdlc debug -w" in t for t in titles)

    capsys.readouterr()
    assert main(["debug", "-w", str(ws)]) == 0
    report = capsys.readouterr().out
    assert "Phase: **failed**" in report
    assert "| T1 | coder | done | 3 |" in report and "| T3 | validator | failed |" in report
    assert "test_divide_by_zero_raises_value_error" in report and "sdlc resume" in report
    assert (run_dir / "reports" / "debug.md").exists()

    assert main(["logs", "-w", str(ws), "--type", "task.retry,task.failed"]) == 0
    assert "routing failure to T1" in capsys.readouterr().out
    assert main(["logs", "-w", str(ws), "--debug-log", "--grep", "pytest"]) == 0
    assert "rc=1" in capsys.readouterr().out
    assert main(["alerts", "-w", str(ws)]) == 0
    assert "[critical] Run failed" in capsys.readouterr().out
    assert main(["audit", "-w", str(ws)]) == 0

    transcripts = list((run_dir / "llm").glob("*.txt"))
    assert transcripts, "--debug must save LLM transcripts"
    for f in [*transcripts, run_dir / "debug.log", run_dir / "events.jsonl", run_dir / "alerts.jsonl"]:
        assert FAKE_TOKEN not in f.read_text(encoding="utf-8"), f"secret leaked into {f.name}"
    assert any("[REDACTED:github-token]" in f.read_text(encoding="utf-8") for f in transcripts)

    # The fixture never fixes the bug, so resuming fails again, but only after T1 got fresh attempts.
    retries_before = (run_dir / "events.jsonl").read_text(encoding="utf-8").count("routing failure to T1")
    assert main(["resume", "-w", str(ws), "--policy", "auto"]) == 1
    events_text = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert events_text.count("routing failure to T1") > retries_before
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["tasks"]["T1"]["attempts"] == 3 and state["tasks"]["T2"]["attempts"] == 1
    assert any("resuming after failure" in json.loads(x)["message"]
               for x in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines())


def test_brownfield_lifecycle_with_a_human_at_every_gate(tmp_path, monkeypatch, capsys):
    prompts: list[str] = []

    def human(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    monkeypatch.setattr(builtins, "input", human)
    ws = tmp_path / "ws"
    req = str(REQS / "brownfield-bookmarks.md")
    assert main(["implement", req, "-w", str(ws)]) == 0           # plan, commit, PR gates
    assert main(["review", "-w", str(ws)]) == 0
    assert main(["cr", "-w", str(ws)]) == 0
    assert main(["release", "-w", str(ws)]) == 0                  # merge and release gates
    assert len(prompts) == 5 and all("Approve?" in p for p in prompts)
    assert Git(ws).latest_semver_tag() == "1.3.0"
    assert main(["validate", "-w", str(ws)]) == 0
    assert main(["audit", "-w", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "Gate A: approve the plan" in out and "Gate 1: commit the change" in out


def test_a_human_rejecting_the_plan_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")
    ws = tmp_path / "ws"
    assert main(["implement", str(REQS / "url-shortener.md"), "-w", str(ws)]) == 1
    state = json.loads(next((ws / ".sdlc" / "runs").glob("*/state.json")).read_text(encoding="utf-8"))
    assert state["phase"] == "rejected" and not (ws / "app").exists()


def test_config_and_doctor(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SDLC_WORKSPACES_DIR", str(tmp_path / "w"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "k" * 30)
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "SDLC_WORKSPACES_DIR" in out and "k" * 30 not in out
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[OK  ] sandbox network guard" in out and "ready" in out
    monkeypatch.setenv("SDLC_MAX_ATTEMPTS", "zero")
    assert main(["config"]) == 1
    assert main(["doctor"]) == 1


def test_bad_configuration_is_a_clear_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SDLC_PROVIDER", "gpt")
    assert main(["implement", str(REQS / "url-shortener.md"), "-w", str(tmp_path / "ws")]) == 2
    assert "SDLC_PROVIDER='gpt' is not one of" in capsys.readouterr().out


def test_alert_test_command(monkeypatch, webhook, capsys):
    monkeypatch.setenv("SDLC_ALERT_WEBHOOK", webhook.url)
    assert main(["alerts", "--test"]) == 0
    assert "webhook(127.0.0.1)" in capsys.readouterr().out and "Test alert" in webhook.posts[0]["text"]
