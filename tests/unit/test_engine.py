"""Engine behaviour with fake agents: parallelism, recovery routing, escalation and guardrails."""

import threading
import time

import pytest

from sdlc_agent.orchestrator.engine import Engine
from sdlc_agent.orchestrator.events import EventLog
from sdlc_agent.orchestrator.gates import PolicyApprover
from sdlc_agent.orchestrator.models import (
    CheckResult,
    FileChange,
    Plan,
    RunState,
    Task,
    TaskOutput,
    TaskStatus,
    ValidationReport,
)
from sdlc_agent.tools.workspace import Workspace


def plan(*tasks: Task) -> Plan:
    return Plan(rationale="test", tasks=list(tasks), change_size="patch", change_size_reason="test")


def state(p: Plan) -> RunState:
    return RunState(run_id="r", requirement_id="REQ-1", requirement_path="x", scenario="s", workspace="w",
                    provider="fake", created_at=time.time(), plan=p)


def engine(tmp_path, p, produce, validate, approver=None, attempts=3):
    return Engine(state(p), Workspace(tmp_path), produce, validate, approver or PolicyApprover(),
                  EventLog(None, "r", quiet=True), save=lambda: None, max_attempts=attempts)


PASS = ValidationReport(checks=[CheckResult(name="tests", status="passed", summary="ok")])


def test_independent_tasks_really_run_in_parallel(tmp_path):
    barrier = threading.Barrier(3, timeout=5)  # deadlocks unless all three run at the same time

    def produce(task, rec):
        if task.id in ("B", "C", "D"):
            barrier.wait()
        return TaskOutput(files=[FileChange(path=f"{task.id}.txt", content=task.id)])

    p = plan(Task(id="A", title="a", agent="architect"),
             *(Task(id=x, title=x, agent="coder", depends_on=["A"]) for x in "BCD"),
             Task(id="V", title="v", agent="validator", depends_on=["B", "C", "D"]))
    e = engine(tmp_path, p, produce, lambda: PASS)
    assert e.run()
    recs = e.state.tasks
    assert all(r.status == TaskStatus.DONE for r in recs.values())
    # The barrier is the proof (it deadlocks unless B, C, D run at the same time). The recorded intervals must
    # also overlap; `<=` because Windows' wall clock ticks every ~15 ms, so start and end can be equal.
    assert max(recs[x].started_at for x in "BCD") <= min(recs[x].finished_at for x in "BCD")


def test_validation_failure_is_routed_to_the_owner_of_the_faulty_file(tmp_path):
    calls = []
    reports = iter([
        ValidationReport(checks=[CheckResult(name="tests", status="failed", summary="1 failed",
                                             details="app/core.py:12: in add\nE AssertionError")]),
        PASS,
    ])

    def produce(task, rec):
        calls.append((task.id, rec.attempts, list(rec.feedback)))
        path = {"CORE": "app/core.py", "UI": "app/ui.py", "TEST": "tests/test_core.py"}[task.id]
        return TaskOutput(files=[FileChange(path=path, content="x = 1\n")])

    p = plan(Task(id="CORE", title="core", agent="coder"), Task(id="UI", title="ui", agent="coder"),
             Task(id="TEST", title="t", agent="tester"),
             Task(id="V", title="v", agent="validator", depends_on=["CORE", "UI", "TEST"]))
    e = engine(tmp_path, p, produce, lambda: next(reports))
    assert e.run()
    reruns = [c for c in calls if c[1] == 2]
    assert [c[0] for c in reruns] == ["CORE"]  # only the owner of app/core.py, not UI or TEST
    assert "app/core.py:12" in reruns[0][2][-1]  # the failure output was passed as feedback


def test_assertion_in_a_test_routes_to_the_module_the_test_imports(tmp_path):
    ws = Workspace(tmp_path)
    p = plan(Task(id="LIB", title="lib", agent="coder"), Task(id="T", title="t", agent="tester"),
             Task(id="V", title="v", agent="validator", depends_on=["LIB", "T"]))
    e = engine(tmp_path, p, lambda *_: TaskOutput(files=[]), lambda: PASS)
    ws.write("app/lib.py", "def f():\n    return 1\n")
    ws.write("tests/test_lib.py", "from app.lib import f\n\ndef test_f():\n    assert f() == 2\n")
    e.state.file_owner.update({"app/lib.py": "LIB", "tests/test_lib.py": "T"})
    report = ValidationReport(checks=[CheckResult(
        name="tests", status="failed", summary="1 failed",
        details="tests/test_lib.py:4: in test_f\n    assert f() == 2\nE   assert 1 == 2")])
    assert e.route_failure(report, p.tasks[-1]) == ["LIB"]


def test_exhausted_recovery_escalates_and_a_rejection_fails_the_run(tmp_path):
    failing = ValidationReport(checks=[CheckResult(name="tests", status="failed", summary="1 failed",
                                                   details="app/x.py:1: boom")])

    def produce(task, rec):
        return TaskOutput(files=[FileChange(path="app/x.py", content="x = 1\n")])

    p = plan(Task(id="X", title="x", agent="coder"), Task(id="V", title="v", agent="validator", depends_on=["X"]))
    e = engine(tmp_path, p, produce, lambda: failing, approver=PolicyApprover({"escalation": "reject"}))
    assert not e.run()
    assert e.state.tasks["X"].attempts == 3
    assert e.state.tasks["V"].status == TaskStatus.FAILED
    assert [d.gate for d in e.state.decisions] == ["escalation"]


def test_a_crashing_task_is_retried_then_its_dependents_are_skipped(tmp_path):
    def produce(task, rec):
        raise RuntimeError("model returned garbage")

    p = plan(Task(id="A", title="a", agent="coder"), Task(id="B", title="b", agent="coder", depends_on=["A"]),
             Task(id="V", title="v", agent="validator", depends_on=["B"]))
    e = engine(tmp_path, p, produce, lambda: PASS, attempts=2)
    assert not e.run()
    assert e.state.tasks["A"].attempts == 2 and e.state.tasks["A"].status == TaskStatus.FAILED
    assert e.state.tasks["B"].status == TaskStatus.SKIPPED


@pytest.mark.parametrize("path", ["../outside.py", ".git/hooks/pre-commit"])
def test_sandbox_violations_fail_the_task(tmp_path, path):
    p = plan(Task(id="A", title="a", agent="coder"), Task(id="V", title="v", agent="validator", depends_on=["A"]))
    e = engine(tmp_path, p, lambda *_: TaskOutput(files=[FileChange(path=path, content="x")]), lambda: PASS,
               attempts=1)
    assert not e.run()
    assert "GuardrailError" in e.state.tasks["A"].error


def test_parallel_tasks_cannot_overwrite_each_others_files(tmp_path):
    def produce(task, rec):
        if task.id == "B":
            time.sleep(0.2)  # let A write first
        return TaskOutput(files=[FileChange(path="shared.py", content=task.id)])

    p = plan(Task(id="A", title="a", agent="coder"), Task(id="B", title="b", agent="coder"),
             Task(id="V", title="v", agent="validator", depends_on=["A", "B"]))
    e = engine(tmp_path, p, produce, lambda: PASS, attempts=1)
    assert not e.run()
    assert "write conflict" in e.state.tasks["B"].error


def test_resume_skips_tasks_that_are_already_done(tmp_path):
    calls = []

    def produce(task, rec):
        calls.append(task.id)
        return TaskOutput(files=[FileChange(path=f"{task.id}.txt", content="x")])

    p = plan(Task(id="A", title="a", agent="coder"), Task(id="B", title="b", agent="coder", depends_on=["A"]),
             Task(id="V", title="v", agent="validator", depends_on=["B"]))
    e = engine(tmp_path, p, produce, lambda: PASS)
    e.state.tasks["A"].status = TaskStatus.DONE
    assert e.run()
    assert calls == ["B"]
