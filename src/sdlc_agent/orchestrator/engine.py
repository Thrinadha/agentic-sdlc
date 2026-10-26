"""DAG execution engine.

* Runs every task whose dependencies are done, in parallel (thread pool).
* Each producing task writes files through the sandbox. A write to a file owned by a task that is not
  an ancestor is a conflict and fails the task (parallel tasks must not race on a file).
* A task that raises gets retried with the error as feedback, up to ``max_attempts``.
* The validator task runs the deterministic checks. On failure it **routes the failure back** to the
  task that owns the code at fault (cross-step coordination), re-runs that task with the failure as
  feedback, and validates again.
* When automatic recovery is exhausted, it escalates to a human gate. A human note becomes feedback
  for one more attempt; a rejection fails the run.
* State is checkpointed after every task, so a stopped run resumes where it left off.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from ..tools.code_index import index_module
from ..tools.workspace import GuardrailError, Workspace, max_files_per_task
from .dag import TaskGraph
from .events import EventLog
from .gates import Approver, GateRequest
from .models import RunState, Task, TaskOutput, TaskRecord, TaskStatus, ValidationReport

log = logging.getLogger(__name__)
ProduceFn = Callable[[Task, TaskRecord], TaskOutput]
ValidateFn = Callable[[], ValidationReport]


def _is_test(path: str) -> bool:
    return path.startswith("tests/") or "/tests/" in path or path.split("/")[-1].startswith(("test_", "conftest"))


class Engine:
    def __init__(self, state: RunState, ws: Workspace, produce: ProduceFn, validate: ValidateFn,
                 approver: Approver, events: EventLog, save: Callable[[], None],
                 max_attempts: int = 3, max_workers: int = 4):
        self.state = state
        self.ws = ws
        self.produce = produce
        self.validate = validate
        self.approver = approver
        self.events = events
        self._save = save
        self.max_attempts = max_attempts
        self.max_workers = max_workers
        self.graph = TaskGraph(state.plan.tasks)
        self._lock = threading.RLock()
        for t in state.plan.tasks:
            state.tasks.setdefault(t.id, TaskRecord(task=t))

    def save(self) -> None:
        with self._lock:
            self._save()

    # ------------------------------------------------------------------ main loop
    def run(self) -> bool:
        recs = self.state.tasks
        done = {tid for tid, r in recs.items() if r.status == TaskStatus.DONE}
        blocked: set[str] = {tid for tid, r in recs.items() if r.status in (TaskStatus.FAILED, TaskStatus.SKIPPED)}
        if done:
            self.events.emit("info", f"resuming: {len(done)} task(s) already done ({', '.join(sorted(done))})")
        levels = self.graph.levels()
        self.events.emit("info", "execution levels: " + " | ".join(", ".join(lv) for lv in levels))

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="task") as pool:
            running: dict[Future, str] = {}
            while True:
                for tid in self.graph.ready(done, set(running.values()), blocked):
                    running[pool.submit(self._execute, tid)] = tid
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in finished:
                    tid = running.pop(fut)
                    try:
                        ok = fut.result()
                    except Exception as e:  # noqa: BLE001 - a task crash must not kill the run loop
                        self._fail(tid, f"unexpected error: {e}")
                        ok = False
                    if ok:
                        done.add(tid)
                    else:
                        blocked.add(tid)
                        for desc in self._descendants(tid):
                            if recs[desc].status == TaskStatus.PENDING:
                                recs[desc].status = TaskStatus.SKIPPED
                                recs[desc].error = f"skipped: dependency {tid} failed"
                                blocked.add(desc)
                                self.events.emit("warn", f"{desc} skipped (depends on failed {tid})")
                    self.save()
        return all(r.status == TaskStatus.DONE for r in recs.values())

    def _descendants(self, tid: str) -> set[str]:
        out, stack = set(), self.graph.dependents(tid)
        while stack:
            cur = stack.pop()
            if cur not in out:
                out.add(cur)
                stack.extend(self.graph.dependents(cur))
        return out

    def _execute(self, tid: str) -> bool:
        task = self.graph.tasks[tid]
        return self._validate_task(task) if task.agent == "validator" else self._produce_with_retry(task)

    # ------------------------------------------------------------------ producing tasks
    def _produce_with_retry(self, task: Task, extra_feedback: str = "") -> bool:
        rec = self.state.tasks[task.id]
        if extra_feedback:
            rec.feedback.append(extra_feedback)
        while True:
            with self._lock:
                rec.status = TaskStatus.RUNNING
                rec.attempts += 1
                rec.started_at = rec.started_at or time.time()
                rec.runs.append([time.time(), time.time()])
            attempt_note = f" (attempt {rec.attempts})" if rec.attempts > 1 else ""
            self.events.emit("task.start", f"{task.id} [{task.agent}] {task.title}{attempt_note}",
                             task=task.id, agent=task.agent, attempt=rec.attempts)
            try:
                out = self.produce(task, rec)
                written = self._apply(task, out)
            except Exception as e:  # noqa: BLE001 - every failure becomes feedback for the next attempt
                rec.runs[-1][1] = time.time()
                rec.error = f"{type(e).__name__}: {e}"
                if rec.attempts >= self.max_attempts:
                    self._fail(task.id, rec.error)
                    return False
                rec.feedback.append(f"Previous attempt failed: {rec.error}")
                self.events.emit("task.retry", f"{task.id} failed ({rec.error[:120]}); retrying", task=task.id)
                continue
            with self._lock:
                rec.status = TaskStatus.DONE
                rec.finished_at = time.time()
                rec.runs[-1][1] = rec.finished_at
                rec.files = sorted(set(rec.files) | set(written))
                rec.notes = out.notes
                rec.error = ""
            self.events.emit("task.done", f"{task.id} wrote {len(written)} file(s): {', '.join(written)}",
                             task=task.id, files=written)
            return True

    def _apply(self, task: Task, out: TaskOutput) -> list[str]:
        limit = max_files_per_task()
        if len(out.files) > limit:
            raise GuardrailError(
                f"{len(out.files)} files exceeds the per-task limit of {limit} (SDLC_MAX_FILES_PER_TASK)")
        allowed_owners = self.graph.ancestors(task.id) | {task.id}
        with self._lock:
            for f in out.files:
                self.ws.resolve(f.path)  # path guardrail before anything is written
                owner = self.state.file_owner.get(f.path)
                if owner and owner not in allowed_owners and owner != "base":
                    raise GuardrailError(
                        f"write conflict: {f.path} belongs to {owner}, which is not a dependency of {task.id}")
            written = []
            for f in out.files:
                if f.action == "delete":
                    self.ws.delete(f.path)
                else:
                    self.ws.write(f.path, f.content)
                self.state.file_owner[f.path] = task.id
                written.append(f.path)
        return written

    def _fail(self, tid: str, error: str) -> None:
        rec = self.state.tasks[tid]
        with self._lock:
            rec.status = TaskStatus.FAILED
            rec.error = error
            rec.finished_at = time.time()
        self.events.emit("task.failed", f"{tid} failed: {error[:200]}", task=tid)

    # ------------------------------------------------------------------ validation + recovery
    def _validate_task(self, task: Task) -> bool:
        rec = self.state.tasks[task.id]
        rec.status = TaskStatus.RUNNING
        rec.started_at = rec.started_at or time.time()
        escalated = False
        while True:
            rec.attempts += 1
            self.events.emit("task.start", f"{task.id} [validator] {task.title} (round {rec.attempts})",
                             task=task.id, attempt=rec.attempts)
            rec.runs.append([time.time(), time.time()])
            report = self.validate()
            rec.runs[-1][1] = time.time()
            self.state.validation = report
            for c in report.checks:
                self.events.emit("validate", f"{c.name}: {c.status} - {c.summary}", check=c.name, status=c.status)
            if report.passed:
                rec.status = TaskStatus.DONE
                rec.finished_at = time.time()
                rec.notes = "; ".join(f"{c.name}={c.status}" for c in report.checks)
                self.events.emit("task.done", f"{task.id} all checks passed", task=task.id)
                return True

            feedback = self._feedback(report)
            owners = self.route_failure(report, task)
            retryable = [o for o in owners if self.state.tasks[o].attempts < self.max_attempts]
            if retryable:
                self.events.emit("task.retry", f"routing failure to {', '.join(retryable)} for a fix",
                                 owners=retryable)
                ok = True
                for owner in retryable:
                    ok = self._produce_with_retry(self.graph.tasks[owner], feedback) and ok
                if ok:
                    continue
            if escalated:
                self._fail(task.id, "validation failed after escalation")
                return False
            decision = self.approver.decide(GateRequest(
                gate="escalation",
                summary=f"Validation still failing after automatic retries (owners: {', '.join(owners) or 'none'})",
                body=feedback + "\n\nApprove to give the owning agent(s) one more attempt with your note as guidance.",
            ))
            self.state.decisions.append(decision)
            verdict = "approved" if decision.approved else "rejected"
            self.events.emit("gate", f"escalation -> {verdict} by {decision.by}",
                             gate="escalation", approved=decision.approved)
            if not decision.approved or not owners:
                self._fail(task.id, "validation failed; escalation rejected")
                return False
            escalated = True
            for owner in owners:
                self.state.tasks[owner].attempts = self.max_attempts - 1
                self._produce_with_retry(self.graph.tasks[owner], f"Human guidance: {decision.note or 'try again'}")

    @staticmethod
    def _feedback(report: ValidationReport) -> str:
        parts = []
        for c in report.checks:
            if c.status == "failed":
                parts.append(f"### {c.name}: {c.summary}\n{c.details[-3500:]}")
        return "Validation failed. Fix the root cause.\n\n" + "\n\n".join(parts)

    def route_failure(self, report: ValidationReport, validator: Task) -> list[str]:
        """Work out which producing task(s) own the code at fault.

        1. Non-test files named in the failure output -> their owners (e.g. a traceback into app code,
           a lint error, an unsafe pattern).
        2. Only test files named -> the modules those tests import -> their owners (an assertion fails
           in the test, but the code under test is what is wrong). A test that cannot even be collected
           is the tester's problem.
        3. Contract mismatch -> the owners of files that declare routes.
        4. Fallback: the validator's direct coder dependencies.
        """
        owners = self.state.file_owner
        text = "\n".join(c.details + "\n" + c.summary for c in report.checks if c.status == "failed")
        text = text.replace("\\", "/")
        mentioned = {p for p in owners if re.search(rf"(?<![\w.]){re.escape(p)}\b", text)}
        app_files = {p for p in mentioned if not _is_test(p) and p.endswith(".py")}
        test_files = {p for p in mentioned if _is_test(p)}
        result: set[str] = set()

        if app_files:
            result = {owners[p] for p in app_files}
        elif test_files:
            collection_error = re.search(r"ERROR collecting|ImportError while importing|SyntaxError", text)
            if collection_error:
                result = {owners[p] for p in test_files}
            else:
                for tf in test_files:
                    for mod in index_module(tf, self.ws.read(tf)).imports:
                        path = mod.replace(".", "/") + ".py"
                        if path in owners and not _is_test(path):
                            result.add(owners[path])
        contract = report.get("contract")
        if not result and contract and contract.status == "failed":
            for p, owner in owners.items():
                if p.endswith(".py") and not _is_test(p) and self.ws.exists(p) and re.search(
                        r"@\w+\.(get|post|put|patch|delete)\(", self.ws.read(p)):
                    result.add(owner)
        if not result:
            result = {d for d in validator.depends_on if self.graph.tasks[d].agent == "coder"}
        log.debug("route_failure: app files %s, test files %s -> owners %s",
                  sorted(app_files), sorted(test_files), sorted(result))
        return sorted(r for r in result if r in self.graph.tasks and self.graph.tasks[r].agent != "validator"
                      and r != "base")
