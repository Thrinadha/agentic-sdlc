"""End-to-end runs of the example scenarios with the offline replay provider.

These run the real orchestrator, real git, the real test suites of the generated code and every
validation check. Only the agents' answers are replayed (pre-written fixtures).
"""

from pathlib import Path

from sdlc_agent.orchestrator.gates import PolicyApprover
from sdlc_agent.orchestrator.models import Phase, TaskStatus
from sdlc_agent.tools.git_tool import Git
from sdlc_agent.workflow import PROJECT_ROOT, Run, Settings, change_request, release

REQS = PROJECT_ROOT / "examples" / "requirements"
POLICY = PROJECT_ROOT / "policies" / "auto.yaml"


def auto(answers: Path | None = None) -> PolicyApprover:
    return PolicyApprover.from_files(POLICY, answers)


def settings() -> Settings:
    return Settings(provider="mock", quiet=True)


def test_greenfield_url_shortener_full_lifecycle(tmp_path):
    ws = tmp_path / "ws"
    state = Run.new(REQS / "url-shortener.md", ws, auto(), settings()).implement()
    assert state.phase == Phase.PR_READY
    assert state.validation.passed
    assert state.tasks["T3"].attempts == 2, "the analytics bug in attempt 1 must be caught and fixed"
    assert all(r.status == TaskStatus.DONE for r in state.tasks.values())
    assert [d.gate for d in state.decisions] == ["plan", "commit", "pr"]
    git = Git(ws)
    assert git.current_branch() == "REQ-101-url-shortener-service"
    assert not list(ws.glob("*.db")), "validation must not leave side-effect files in the workspace"

    reviewed = Run.load(ws, state.run_id, auto(), settings()).review()
    assert reviewed.review.verdict == "approve_with_comments"
    assert (ws / "tests/integration/test_cache_invalidation.py").exists()  # Gate 4 fix applied + validated

    cr = change_request(ws, auto(), settings(), state.run_id).read_text(encoding="utf-8")
    assert "Version: 0.1.0" in cr and "Backout Plan" in cr
    assert release(ws, auto(), settings()) is not None
    assert git.latest_semver_tag() == "0.1.0"


def test_brownfield_fix_and_enhancement(tmp_path):
    ws = tmp_path / "ws"
    state = Run.new(REQS / "brownfield-bookmarks.md", ws, auto(), settings()).implement()
    assert state.phase == Phase.PR_READY
    assert state.impact and any(i.path == "bookmarks/store.py" for i in state.impact.impacted)
    assert "start + size" in (ws / "bookmarks/store.py").read_text(encoding="utf-8")
    assert state.file_owner["tests/test_api.py"] == "base"  # existing tests kept and still run
    release(ws, auto(), settings())
    assert Git(ws).latest_semver_tag() == "1.3.0"


def test_ambiguous_requirement_stops_then_resumes_with_answers(tmp_path):
    ws = tmp_path / "ws"
    stopped = Run.new(REQS / "ambiguous-notifications.md", ws, auto(), settings()).implement()
    assert stopped.phase == Phase.NEEDS_CLARIFICATION
    assert stopped.plan is None and not any((ws / "notify").glob("*.py"))
    request = ws / ".sdlc" / "runs" / stopped.run_id / "reports" / "clarification-request.md"
    assert "Q1" in request.read_text(encoding="utf-8")

    resumed = Run.load(ws, stopped.run_id, auto(REQS / "ambiguous-notifications.answers.yaml"), settings())
    state = resumed.implement()
    assert state.phase == Phase.PR_READY
    assert state.clarifications["Q3"].startswith("A notification must be visible")
    assert not state.spec.blocking()
