"""The real-provider code path, end to end, without an API key.

The workflow runs with ``--provider openai`` against a local OpenAI-compatible server (tests/fake_llm_server.py).
Everything on our side is production code: HTTP requests, auth headers, JSON-mode, response parsing,
schema validation, retry on 429, the repair prompt on a malformed answer, and the full workflow on the result.
"""

import json

import pytest
from fake_llm_server import FakeLLMServer

from sdlc_agent.cli import main
from sdlc_agent.orchestrator.gates import PolicyApprover
from sdlc_agent.orchestrator.models import Phase
from sdlc_agent.workflow import PROJECT_ROOT, Run, Settings, latest_run_id

REQS = PROJECT_ROOT / "examples" / "requirements"
POLICY = PROJECT_ROOT / "policies" / "auto.yaml"
KEY = "test-openai-key-" + "x" * 24


@pytest.fixture
def llm(monkeypatch):
    server = FakeLLMServer(PROJECT_ROOT / "fixtures", "url-shortener",
                           transient_once={"planner"}, malformed_once={"tester"})
    monkeypatch.setenv("SDLC_OPENAI_BASE_URL", server.base_url)
    monkeypatch.setenv("SDLC_MODEL", "fake-model-1")
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    yield server
    server.close()


def test_url_shortener_runs_end_to_end_through_the_http_provider(tmp_path, llm):
    ws = tmp_path / "ws"
    settings = Settings(provider="openai", quiet=True, debug=True)
    state = Run.new(REQS / "url-shortener.md", ws, PolicyApprover.from_files(POLICY, None), settings).implement()

    assert state.phase == Phase.PR_READY, state.error
    assert state.provider == "openai" and state.validation.passed
    assert state.tasks["T3"].attempts == 2  # real test failure → routed to the coder → fixed via the HTTP path

    sent = llm.requests
    assert all(r["path"] == "/v1/chat/completions" for r in sent)
    assert all(r["auth"] == f"Bearer {KEY}" and r["model"] == "fake-model-1" for r in sent)
    assert all(r["json_mode"] == {"type": "json_object"} for r in sent)
    keys = [r["key"] for r in sent]
    assert keys.count("planner") == 2, "429 on the first planner call must be retried"
    assert any(r["key"].startswith("tester.") and r["repair"] for r in sent), "malformed answer must get a repair"

    run_dir = ws / ".sdlc" / "runs" / state.run_id
    events = [json.loads(x) for x in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    outcomes = {e.get("outcome") for e in events if e["type"] == "llm"}
    assert {"ok", "transient", "repair"} <= outcomes
    for f in [run_dir / "debug.log", run_dir / "events.jsonl", *(run_dir / "llm").glob("*.txt")]:
        assert KEY not in f.read_text(encoding="utf-8"), f"API key leaked into {f.name}"

    reviewed = Run.load(ws, state.run_id, PolicyApprover.from_files(POLICY, None), settings).review()
    assert reviewed.review.verdict == "approve_with_comments"
    assert llm.requests[-1]["key"] == "reviewer"


def test_azure_openai_mode_uses_api_version_and_api_key_header(tmp_path, llm, monkeypatch, capsys):
    monkeypatch.setenv("SDLC_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.delenv("SDLC_MODEL")  # Azure: the deployment in the URL selects the model
    ws = tmp_path / "ws"
    assert main(["implement", str(REQS / "url-shortener.md"), "-w", str(ws), "--provider", "openai",
                 "--policy", "auto"]) == 0
    assert all(r["api_key"] == KEY and r["auth"] == "" and r["model"] is None for r in llm.requests)
    assert all(r["path"] == "/v1/chat/completions?api-version=2024-10-21" for r in llm.requests)
    state = json.loads((ws / ".sdlc" / "runs" / latest_run_id(ws) / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "pr_ready"


def test_endpoint_down_fails_cleanly_with_a_diagnosis(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SDLC_OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens on port 9
    monkeypatch.setenv("SDLC_MODEL", "m")
    monkeypatch.setenv("SDLC_MAX_LLM_CALLS", "4")
    ws = tmp_path / "ws"
    assert main(["implement", str(REQS / "url-shortener.md"), "-w", str(ws), "--provider", "openai",
                 "--policy", "auto"]) == 1
    out = capsys.readouterr().out
    assert "diagnose with: sdlc debug" in out
    state = json.loads((ws / ".sdlc" / "runs" / latest_run_id(ws) / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "failed" and ("TransientLLMError" in state["error"] or "Budget" in state["error"])


def test_file_urls_are_refused_for_the_endpoint(monkeypatch):
    from sdlc_agent.llm.openai_compat import OpenAICompatibleProvider

    monkeypatch.setenv("SDLC_OPENAI_BASE_URL", "file:///etc/passwd")
    monkeypatch.setenv("SDLC_MODEL", "m")
    with pytest.raises(ValueError, match="only http"):
        OpenAICompatibleProvider()
