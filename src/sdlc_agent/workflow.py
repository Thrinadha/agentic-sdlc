"""The SDLC flows: implement -> review -> change request -> release.

Each flow is a resumable state machine over ``RunState``. Every phase checkpoints to
``<workspace>/.sdlc/runs/<run-id>/state.json`` and every gate decision is recorded.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from . import config
from .agents.base import files_block, untrusted
from .agents.roles import CodebaseAnalyst, Planner, Producer, RequirementAnalyst, Reviewer
from .llm.base import Budget, StructuredLLM
from .llm.registry import get_provider
from .observability import Alerter, TranscriptWriter, debug_log
from .orchestrator.dag import PlanError, TaskGraph
from .orchestrator.engine import Engine
from .orchestrator.events import EventLog
from .orchestrator.gates import Approver, GateRequest
from .orchestrator.models import (
    CheckResult,
    GateDecision,
    Phase,
    RunState,
    Task,
    TaskRecord,
    TaskStatus,
    ValidationReport,
)
from .reports import (
    render_cr,
    render_plan,
    render_pr,
    render_release_notes,
    render_review,
    render_summary,
    render_validation,
    write,
)
from .requirement import load_requirement
from .tools import github, injection_scan, review_checks
from .tools.code_index import build_index, render_index
from .tools.git_tool import Git, bump
from .tools.secret_scan import scan_files
from .tools.static_checks import (
    compile_check,
    contract_check,
    dependency_audit_check,
    lint_check,
    security_check,
    unsafe_code_check,
)
from .tools.test_runner import run_pytest
from .tools.workspace import TEXT_SUFFIXES, Workspace

PROJECT_ROOT = Path(config.raw("SDLC_HOME") or Path(__file__).resolve().parents[2])
SIZE_ORDER = {"patch": 0, "minor": 1, "major": 2}
log = logging.getLogger(__name__)


class Settings:
    """Run settings. Anything not passed explicitly (e.g. by a CLI flag) comes from ``config``."""

    def __init__(self, provider: str | None = None, record: bool = False, max_llm_calls: int | None = None,
                 max_attempts: int | None = None, workers: int | None = None, quiet: bool = False,
                 debug: bool | None = None):
        self.provider = provider or config.get("SDLC_PROVIDER")
        self.record = record
        self.max_llm_calls = max_llm_calls or config.get_int("SDLC_MAX_LLM_CALLS")
        self.max_attempts = max_attempts or config.get_int("SDLC_MAX_ATTEMPTS")
        self.workers = workers or config.get_int("SDLC_WORKERS")
        self.quiet = quiet
        self.debug = config.get_bool("SDLC_DEBUG") if debug is None else debug


# ====================================================================== helpers


def runs_dir(workspace: Path) -> Path:
    return workspace / ".sdlc" / "runs"


def latest_run_id(workspace: Path) -> str:
    d = runs_dir(workspace)
    runs = sorted(d.glob("*/state.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    if not runs:
        raise FileNotFoundError(f"no runs found in {d}")
    return runs[-1].parent.name


def standards_text() -> str:
    return (PROJECT_ROOT / "standards" / "coding-standards.md").read_text(encoding="utf-8")


def discover_app_factory(ws: Workspace) -> tuple[str | None, str | None]:
    contract = next((p for p in ws.files({".yaml", ".yml"}) if re.search(r"openapi", p.split("/")[-1])), None)
    factory = None
    for rel in ws.files({".py"}):
        if rel.endswith("main.py") and "def create_app" in ws.read(rel):
            factory = rel[:-3].replace("/", ".") + ":create_app"
            break
    return contract, factory


def run_validation(ws: Workspace, git: Git | None = None) -> ValidationReport:
    contract, factory = discover_app_factory(ws)
    findings = scan_files(ws.snapshot(ws.files(TEXT_SUFFIXES), max_bytes=10_000_000))
    secrets = CheckResult(
        name="secrets",
        status="failed" if findings else "passed",
        summary=f"{len(findings)} finding(s)" if findings else "no secrets found",
        details="\n".join(str(f) for f in findings),
    )
    return ValidationReport(checks=[
        compile_check(ws.root), lint_check(ws.root), unsafe_code_check(ws), security_check(ws.root),
        dependency_audit_check(ws.root), contract_check(ws.root, contract, factory), run_pytest(ws.root), secrets,
    ])


# ====================================================================== the run


class Run:
    """One requirement being implemented in one workspace."""

    def __init__(self, state: RunState, approver: Approver, settings: Settings):
        self.state = state
        self.settings = settings
        self.approver = approver
        self.workspace = Path(state.workspace)
        self.ws = Workspace(self.workspace)
        self.git = Git(self.workspace)
        self.dir = runs_dir(self.workspace) / state.run_id
        self.reports = self.dir / "reports"
        self.alerter = Alerter.from_env(self.dir / "alerts.jsonl", context={
            "run_id": state.run_id, "requirement": state.requirement_id,
            "hint": f"sdlc debug -w {self.workspace} --run {state.run_id}"})
        self.events = EventLog(self.dir / "events.jsonl", state.run_id, quiet=settings.quiet, alerter=self.alerter)
        self.req = load_requirement(Path(state.requirement_path))
        provider = get_provider(settings.provider, PROJECT_ROOT / "fixtures", record=settings.record)
        self.budget = Budget(settings.max_llm_calls)
        self.budget.used = state.llm_calls
        transcripts = TranscriptWriter(self.dir / "llm") if settings.debug else None
        self.llm = StructuredLLM(provider, self.budget, on_call=self._on_llm, transcripts=transcripts)

    # -- construction --------------------------------------------------------
    @classmethod
    def new(cls, requirement: Path, workspace: Path, approver: Approver, settings: Settings) -> Run:
        req = load_requirement(requirement)
        run_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        state = RunState(run_id=run_id, requirement_id=req.id, requirement_path=str(req.path),
                         scenario=req.scenario, workspace=str(workspace.resolve()), provider=settings.provider,
                         created_at=time.time())
        run = cls(state, approver, settings)
        run.save()
        return run

    @classmethod
    def load(cls, workspace: Path, run_id: str | None, approver: Approver, settings: Settings) -> Run:
        run_id = run_id or latest_run_id(workspace)
        state = RunState.model_validate_json((runs_dir(workspace) / run_id / "state.json").read_text(encoding="utf-8"))
        settings.provider = state.provider if settings.provider == "mock" else settings.provider
        return cls(state, approver, settings)

    def save(self) -> None:
        self.state.llm_calls = self.budget.used
        write(self.dir / "state.json", self.state.model_dump_json(indent=1))

    def _on_llm(self, **kw) -> None:
        self.events.emit("llm", f"{kw.get('agent')} {kw.get('key')} {kw.get('outcome')}", **kw)

    def phase(self, p: Phase, msg: str) -> None:
        self.state.phase = p
        self.events.emit("phase", msg, phase=p.value)
        self.save()

    def gate(self, req: GateRequest) -> GateDecision:
        d = self.approver.decide(req)
        self.state.decisions.append(d)
        self.events.emit("gate", f"{req.title} -> {'APPROVED' if d.approved else 'REJECTED'} by {d.by}"
                         + (f" ({d.note})" if d.note else ""), gate=req.gate, approved=d.approved)
        self.save()
        return d

    # ================================================================== implement
    def implement(self) -> RunState:
        with debug_log(self.dir / "debug.log"):
            log.info("implement run=%s requirement=%s provider=%s phase=%s", self.state.run_id,
                     self.state.requirement_id, self.settings.provider, self.state.phase.value)
            try:
                self._recover_if_failed()
                self._implement()
            except Exception as e:
                log.exception("run failed")
                self.state.error = f"{type(e).__name__}: {e}"
                self.phase(Phase.FAILED, f"run failed: {self.state.error}")
                raise
            finally:
                self.write_summary()
        return self.state

    def _recover_if_failed(self) -> None:
        """`sdlc resume` after a failure: go back to the last phase that completed and retry from there.

        Failed and skipped tasks get a fresh set of attempts; their earlier feedback is kept, so the agent
        sees why the previous attempts failed (plus any human guidance given at the escalation gate).
        """
        s = self.state
        if s.phase != Phase.FAILED:
            return
        if s.spec is None:
            target = Phase.NEW
        elif s.plan is None:
            target = Phase.CLARIFIED
        elif any(r.status != TaskStatus.DONE for r in s.tasks.values()):
            target = Phase.PLAN_APPROVED
            for r in s.tasks.values():
                if r.status != TaskStatus.DONE:
                    r.status, r.attempts, r.error = TaskStatus.PENDING, 0, ""
                elif r.attempts >= self.settings.max_attempts:
                    r.attempts = 0  # done, but used up its retries fixing what validation found: give it new ones
        else:
            target = Phase.EXECUTED
        s.error = ""
        self.phase(target, f"resuming after failure from phase {target.value}")

    def _implement(self) -> None:
        s = self.state
        if s.phase == Phase.NEW:
            self._setup_workspace()
            s.spec = RequirementAnalyst(self.llm, s.scenario).analyze(self.req.body)
            self.phase(Phase.ANALYZED, f"analysed requirement: {s.spec.title} [{s.spec.kind}], "
                       f"{len(s.spec.acceptance_criteria)} acceptance criteria, {len(s.spec.ambiguities)} ambiguities")

        if s.phase in (Phase.ANALYZED, Phase.NEEDS_CLARIFICATION) and not self._clarify():
            return

        if s.phase == Phase.CLARIFIED:
            if s.spec.kind != "greenfield" and self.ws.files({".py"}):
                index = build_index(self.ws)
                suspicious = injection_scan.scan(self.ws.snapshot(self.ws.files(TEXT_SUFFIXES), max_bytes=10_000_000))
                for hit in suspicious:
                    s.warnings.append(f"possible prompt injection in repository content: {hit}")
                    self.events.emit("warn", f"possible prompt injection: {hit}")
                source = files_block(self.ws.snapshot([m["path"] for m in index["modules"]]))
                s.impact = CodebaseAnalyst(self.llm, s.scenario).analyze(s.spec, render_index(index), source)
                write(self.reports / "impact.md", "\n".join(
                    [f"# Impact analysis\n\n{s.impact.summary}\n", render_index(index)]))
                self.phase(Phase.IMPACT_ANALYZED, f"impact analysis: {len(s.impact.impacted)} impacted item(s)")
            else:
                self.phase(Phase.IMPACT_ANALYZED, "greenfield: no existing code to analyse")

        if s.phase == Phase.IMPACT_ANALYZED:
            s.plan = Planner(self.llm, s.scenario).plan(s.spec, s.impact, standards_text())
            self._check_plan()
            write(self.reports / "plan.md", render_plan(s))
            levels = TaskGraph(s.plan.tasks).levels()
            self.phase(Phase.PLANNED, f"planned {len(s.plan.tasks)} tasks in {len(levels)} levels "
                       f"(max parallel {max(len(lv) for lv in levels)}), change size {s.plan.change_size}")

        if s.phase == Phase.PLANNED:
            warnings = "".join(f"\n- {w}" for w in s.warnings)
            body = render_plan(s) + (f"\n## Warnings (review before approving)\n{warnings}\n" if warnings else "")
            d = self.gate(GateRequest(gate="plan", summary=f"{len(s.plan.tasks)} tasks, change size "
                                      f"{s.plan.change_size}" + (f", {len(s.warnings)} WARNING(S)" if warnings else ""),
                                      body=body))
            if not d.approved:
                self.phase(Phase.REJECTED, "plan rejected")
                return
            self.phase(Phase.PLAN_APPROVED, "plan approved, executing")

        if s.phase == Phase.PLAN_APPROVED:
            engine = Engine(s, self.ws, self._produce, lambda: run_validation(self.ws, self.git), self.approver,
                            self.events, self.save, max_attempts=self.settings.max_attempts,
                            max_workers=self.settings.workers)
            ok = engine.run()
            self.save()
            if not ok:
                failed = [t for t, r in s.tasks.items() if r.status.value != "done"]
                s.error = f"tasks not completed: {', '.join(failed)}"
                self.phase(Phase.FAILED, f"execution failed ({s.error})")
                return
            self.phase(Phase.EXECUTED, "all tasks done and validated")

        if s.phase == Phase.EXECUTED and not self._commit():
            return
        if s.phase == Phase.COMMITTED:
            self._raise_pr()

    # -- setup -------------------------------------------------------------------
    def _setup_workspace(self) -> None:
        s, git = self.state, self.git
        fresh = not git.is_repo()
        if fresh and self.req.seed:
            seed = (PROJECT_ROOT / self.req.seed).resolve()
            for p in seed.rglob("*"):
                rel = p.relative_to(seed)
                if p.is_file() and not any(part in ("__pycache__", ".pytest_cache") for part in rel.parts):
                    (self.workspace / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, self.workspace / rel)
        if fresh:
            git.init()
            git.ensure_ignored(".sdlc/", "__pycache__/", "*.pyc", ".pytest_cache/", "*.db", ".venv/")
            # Bootstrapping a new repository is the one commit made directly on main.
            git.commit_all("Initial import" if self.req.seed else "Initialize repository", allow_protected=True)
            if self.req.seed_version:
                git.tag(self.req.seed_version, f"Release {self.req.seed_version}")
        for rel in self.ws.files():
            s.file_owner.setdefault(rel, "base")
        s.base_commit = git.head()
        s.branch = self.req.branch
        git.checkout_new(s.branch, "main")
        self.events.emit("info", f"workspace {self.workspace} on branch {s.branch} (base {s.base_commit[:8]})")

    # -- clarify -----------------------------------------------------------------
    def _clarify(self) -> bool:
        s = self.state
        blocking = s.spec.blocking()
        if not blocking:
            s.spec.assumptions += [f"{a.id}: {a.assumption}" for a in s.spec.ambiguities
                                   if a.assumption and a.id not in " ".join(s.spec.assumptions)]
            self.phase(Phase.CLARIFIED, f"no blocking ambiguities ({len(s.spec.ambiguities)} minor, defaults applied)")
            return True
        d = self.gate(GateRequest(
            gate="clarify", summary=f"{len(blocking)} blocking ambiguit{'y' if len(blocking) == 1 else 'ies'}",
            questions=blocking))
        if not d.approved:
            write(self.reports / "clarification-request.md", self._clarification_request(blocking))
            self.phase(Phase.NEEDS_CLARIFICATION, "stopped: a human must answer the blocking questions "
                       f"(see {self.reports / 'clarification-request.md'})")
            return False
        s.clarifications = d.answers
        s.spec = RequirementAnalyst(self.llm, s.scenario).refine(self.req.body, s.spec, d.answers)
        if s.spec.blocking():
            raise RuntimeError("refined spec still has blocking ambiguities")
        self.phase(Phase.CLARIFIED, f"clarified {len(d.answers)} question(s); spec refined")
        return True

    def _clarification_request(self, blocking) -> str:
        lines = [f"# Clarification needed: {self.req.id} {self.req.title}", "",
                 "The run stopped before planning because these questions change the architecture or API.",
                 "Answer them in a YAML file (`<id>: <answer>`) and rerun with `--answers <file>`, or run",
                 "interactively.", ""]
        for a in blocking:
            lines += [f"## {a.id}: {a.question}", f"- Why it matters: {a.why_it_matters}",
                      f"- Default if you accept it: {a.assumption}", ""]
        return "\n".join(lines)

    # -- plan checks -------------------------------------------------------------
    def _check_plan(self) -> None:
        tasks = self.state.plan.tasks
        graph = TaskGraph(tasks)  # cycles, unknown deps
        validators = [t for t in tasks if t.agent == "validator"]
        if len(validators) != 1:
            raise PlanError("plan must have exactly one validator task")
        producers = {t.id for t in tasks if t.agent != "validator"}
        missing = producers - graph.ancestors(validators[0].id)
        if missing:
            raise PlanError(f"validator does not depend on: {', '.join(sorted(missing))}")
        for lv in graph.levels():  # parallel tasks must not write the same file
            seen: dict[str, str] = {}
            for tid in lv:
                for out in graph.tasks[tid].outputs:
                    if out in seen:
                        raise PlanError(f"{tid} and {seen[out]} run in parallel and both write {out}")
                    seen[out] = tid

    # -- produce (called by the engine, possibly in parallel) --------------------
    def _produce(self, task: Task, rec: TaskRecord) -> object:
        s = self.state
        graph = TaskGraph(s.plan.tasks)
        upstream = graph.ancestors(task.id)
        context_paths = sorted(p for p, o in s.file_owner.items() if o in upstream)
        if s.impact:
            context_paths += [i.path for i in s.impact.impacted if i.path not in context_paths]
        own = [p for p in task.outputs if self.ws.exists(p) and p not in context_paths]
        plan_lines = "\n".join(f"- {t.id} [{t.agent}] {t.title} (depends on: {', '.join(t.depends_on) or '-'}; "
                               f"outputs: {', '.join(t.outputs)})" for t in s.plan.tasks)
        sections = {
            "Requirement spec": s.spec.model_dump_json(indent=1),
            "Plan": plan_lines,
            "Your task": task.model_dump_json(indent=1),
            "Impact analysis": s.impact.model_dump_json(indent=1) if s.impact else "",
            "Files from earlier tasks and impacted files": files_block(self.ws.snapshot(context_paths)),
            "Current content of your output files": files_block(self.ws.snapshot(own)),
            "Coding standards": standards_text(),
            "Feedback from validation / previous attempts": "\n\n".join(rec.feedback[-3:]),
        }
        return Producer(task.agent, self.llm, s.scenario).run(task.id, sections, rec.attempts)

    # -- commit (Gate 1) ---------------------------------------------------------
    def _commit(self) -> bool:
        s = self.state
        changed = self.git.status_files()
        findings = scan_files({p: self.ws.read(p) for p in changed if self.ws.exists(p)})
        blockers = [f"secret: {f}" for f in findings]
        if s.validation and not s.validation.passed:
            blockers.append("validation has failing checks")
        message = f"{s.requirement_id} - {s.spec.title}"
        body = "\n".join([
            f"Branch: {s.branch}", f"Commit message: {message}", "",
            f"Changed files ({len(changed)}):", *(f"  {p}" for p in changed), "",
            f"Secret scan: {'CLEAN' if not findings else f'{len(findings)} finding(s)'}",
            *(f"  {f}" for f in findings), "", "Validation:", render_validation(s.validation),
        ])
        d = self.gate(GateRequest(gate="commit", summary=f"{len(changed)} file(s) on {s.branch}",
                                  body=body, blockers=blockers))
        if not d.approved:
            self.events.emit("warn", "commit not approved; the run can be resumed with `sdlc resume`")
            return False
        # Anchoring the audit-log head in git makes later edits to the log detectable.
        s.commit = self.git.commit_all(f"{message}\n\nRun: {s.run_id}\nAudit-Log-Head: {self.events.head}")
        self.phase(Phase.COMMITTED, f"committed {s.commit[:10]} on {s.branch}")
        return True

    # -- PR (Gate 3) -------------------------------------------------------------
    def _raise_pr(self) -> None:
        s = self.state
        title = f"{s.requirement_id} - {s.spec.title}"
        changed = self._changed_since_base()
        template = (PROJECT_ROOT / "standards" / "pr_template.md").read_text(encoding="utf-8")
        body = render_pr(s, template, changed, title)
        hygiene = review_checks.pr_hygiene(title, body, s.requirement_id)
        blockers = [f"{f.check}: {f.message}" for f in hygiene if f.severity == "high"]
        d = self.gate(GateRequest(gate="pr", summary=title, body=body, blockers=blockers))
        if not d.approved:
            return
        url = ""
        if github.configured():
            github.push_branch(self.git, s.branch)
            url = github.open_pr(s.branch, title, body)
            self.events.emit("info", f"opened GitHub PR {url}")
        pr_dir = self.workspace / ".sdlc" / "prs"
        write(pr_dir / f"{s.branch}.md", body)
        write(pr_dir / f"{s.branch}.json", json.dumps({
            "title": title, "branch": s.branch, "run_id": s.run_id, "change_size": _ticked_size(body),
            "status": "open", "url": url, "path": f".sdlc/prs/{s.branch}.md"}, indent=1))
        write(self.reports / "pr.md", f"# {title}\n\n{body}")
        self.phase(Phase.PR_READY, f"PR ready: {url or pr_dir / (s.branch + '.md')}")

    def _changed_since_base(self) -> dict[str, str]:
        out = self.git.run("diff", "--name-status", f"{self.state.base_commit}..{self.state.branch}")
        codes = {"A": "added", "M": "modified", "D": "deleted"}
        return {line.split("\t")[-1]: codes.get(line[0], line[0]) for line in out.splitlines() if line.strip()}

    # ================================================================== review
    def review(self) -> RunState:
        with debug_log(self.dir / "debug.log"):
            log.info("review run=%s", self.state.run_id)
            try:
                return self._review()
            except Exception as e:
                log.exception("review failed")
                self.events.emit("error", f"review failed: {type(e).__name__}: {e}")
                raise

    def _review(self) -> RunState:
        s = self.state
        if s.phase not in (Phase.PR_READY, Phase.REVIEWED):
            raise RuntimeError(f"nothing to review: run is in phase {s.phase.value}")
        self.git.checkout(s.branch)
        changed = self._changed_since_base()
        changed_text = {p: self.ws.read(p) for p in changed if self.ws.exists(p)}
        all_text = self.ws.snapshot(self.ws.files(TEXT_SUFFIXES), max_bytes=10_000_000)
        title = f"{s.requirement_id} - {s.spec.title}"
        pr_body = (self.workspace / ".sdlc" / "prs" / f"{s.branch}.md").read_text(encoding="utf-8")
        static = [
            *review_checks.commented_out_code(changed_text), *review_checks.duplicated_blocks(all_text),
            *review_checks.leftovers(changed_text), *review_checks.untested_modules(changed_text, all_text),
            *review_checks.pr_hygiene(title, pr_body, s.requirement_id),
            *(review_checks.Finding(severity="high", check="secrets", file=f.file, line=f.line,
                                    message=f"possible secret ({f.rule})", source="static")
              for f in scan_files(changed_text)),
        ]
        self.events.emit("phase", f"review: {len(static)} deterministic finding(s); asking the reviewer agent")
        diff = self.git.run("diff", f"{s.base_commit}..{s.branch}")
        review = Reviewer(self.llm, s.scenario).review({
            "Requirement spec": s.spec.model_dump_json(indent=1),
            "Coding standards": standards_text(),
            "PR": f"{title}\n\n{pr_body}",
            "Deterministic findings": "\n".join(f"[{f.severity}] {f.check} {f.file}:{f.line} {f.message}"
                                                for f in static) or "none",
            "Diff": untrusted(diff[:150_000]),
            "Existing (unchanged) modules you may suggest reusing":
                "\n".join(p for p in self.ws.files({".py"}) if p not in changed),
        })
        review.findings = [*static, *review.findings]
        if any(f.severity == "high" for f in review.findings):
            review.verdict = "changes_needed"
        applied = "No fixes proposed."
        if review.fixes:
            applied = self._apply_review_fixes(review)
        s.review = review
        write(self.reports / "review.md", render_review(s, review, title, applied))
        self.phase(Phase.REVIEWED, f"review verdict: {review.verdict} ({len(review.findings)} finding(s))")
        self.write_summary()
        return s

    def _apply_review_fixes(self, review) -> str:
        s = self.state
        body = "\n".join(f"- {f.path} ({len(f.content.splitlines())} lines)" for f in review.fixes)
        d = self.gate(GateRequest(gate="review_fixes", summary=f"{len(review.fixes)} proposed fix(es)",
                                  body="Findings:\n" + "\n".join(f"- [{f.severity}] {f.check}: {f.message}"
                                                                 for f in review.findings) + "\n\nFixes:\n" + body))
        if not d.approved:
            return "Proposed fixes were not approved (Gate 4); findings left for the author."
        for f in review.fixes:
            self.ws.write(f.path, f.content)
            s.file_owner.setdefault(f.path, "review")
        report = run_validation(self.ws, self.git)
        for c in report.checks:
            self.events.emit("validate", f"after fixes - {c.name}: {c.status} - {c.summary}")
        if not report.passed:
            self.git.run("checkout", "--", ".")
            self.git.run("clean", "-fdq", "-e", ".sdlc")
            return "Fixes were approved but broke validation, so they were reverted:\n\n" + render_validation(report)
        s.validation = report
        s.commit = self.git.commit_all(f"{s.requirement_id} - Address review comments\n\nRun: {s.run_id}")
        self.events.emit("info", f"review fixes committed {s.commit[:10]}")
        return (f"Applied after Gate 4 approval and re-validated (commit `{s.commit[:10]}`):\n"
                + body + "\n\n" + render_validation(report))

    # ================================================================== summary
    def write_summary(self) -> Path:
        self.save()
        return write(self.reports / "summary.md", render_summary(self.state, self.events.read()))


# ====================================================================== CR + release (workspace level)


def _ticked_size(body: str) -> str:
    section = body.split("## Change Size", 1)[-1].split("\n## ", 1)[0]
    ticked = re.findall(r"- \[x\] \*\*(Major|Minor|Patch)\*\*", section, re.I)
    if len(ticked) != 1:
        raise ValueError(f"exactly one Change Size box must be ticked, found {len(ticked)}")
    return ticked[0].lower()


def _prs(workspace: Path, status: str) -> list[dict]:
    d = workspace / ".sdlc" / "prs"
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        meta = json.loads(p.read_text(encoding="utf-8"))
        if meta["status"] == status:
            meta["change_size"] = _ticked_size((workspace / meta["path"]).read_text(encoding="utf-8"))
            out.append(meta)
    return out


def next_version(git: Git, prs: list[dict]) -> tuple[str | None, str]:
    last = git.latest_semver_tag()
    size = max((p["change_size"] for p in prs), key=SIZE_ORDER.__getitem__)
    return last, bump(last, size)


def change_request(workspace: Path, approver: Approver, settings: Settings, run_id: str | None = None) -> Path:
    run = Run.load(workspace, run_id, approver, settings)
    prs = _prs(workspace, "open") or _prs(workspace, "merged")
    if not prs:
        raise RuntimeError("no PRs found; run `sdlc implement` first")
    last, version = next_version(run.git, prs)
    changed = sorted(run._changed_since_base())
    template = (PROJECT_ROOT / "standards" / "cr_template.md").read_text(encoding="utf-8")
    cr = render_cr(run.state, template, last, version, prs, changed)
    path = write(run.reports / "cr.md", cr)
    run.events.emit("phase", f"change request drafted for {version}: {path}")
    return path


def release(workspace: Path, approver: Approver, settings: Settings) -> Path | None:
    sdlc_dir = workspace / ".sdlc"
    alerter = Alerter.from_env(sdlc_dir / "release-alerts.jsonl",
                               context={"run_id": "release", "hint": f"sdlc logs -w {workspace} --release"})
    events = EventLog(sdlc_dir / "release-events.jsonl", "release", quiet=settings.quiet, alerter=alerter)
    with debug_log(sdlc_dir / "release-debug.log"):
        try:
            return _release(Git(workspace), workspace, approver, events)
        except Exception as e:
            log.exception("release failed")
            events.emit("error", f"release failed: {type(e).__name__}: {e}")
            raise


def _release(git: Git, workspace: Path, approver: Approver, events: EventLog) -> Path | None:
    def decide(req: GateRequest) -> bool:
        d = approver.decide(req)
        events.emit("gate", f"{req.gate} {req.summary} -> {'APPROVED' if d.approved else 'REJECTED'} by {d.by}"
                    + (f" ({d.note})" if d.note else ""), gate=req.gate, approved=d.approved, by=d.by, note=d.note)
        return d.approved

    prs = _prs(workspace, "open")
    if not prs:
        raise RuntimeError("no open PRs to release")
    merged = []
    for pr in prs:
        if not decide(GateRequest(gate="merge", summary=pr["title"],
                                  body=f"Merge `{pr['branch']}` into `main` (size: {pr['change_size']})")):
            continue
        sha = git.merge_no_ff(pr["branch"], f"Merge {pr['branch']}: {pr['title']}")
        pr.update(status="merged", merge_commit=sha)
        write(workspace / ".sdlc" / "prs" / f"{pr['branch']}.json", json.dumps(pr, indent=1))
        merged.append(pr)
        events.emit("info", f"merged {pr['branch']} ({sha[:10]})")
    if not merged:
        return None
    last, version = next_version(git, merged)
    notes = render_release_notes(version, last, merged)
    if not decide(GateRequest(gate="release", summary=f"tag {version} (previous {last or 'none'})", body=notes)):
        return None
    git.tag(version, f"Release {version}")
    path = write(workspace / ".sdlc" / "releases" / f"{version}.md", notes)
    events.emit("phase", f"released {version}: {path}")
    return path
