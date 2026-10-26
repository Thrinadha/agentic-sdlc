"""Typed contracts shared by agents, tools and the orchestrator.

Every agent returns one of these models. The LLM layer validates raw model output against them,
so a malformed response is caught at the boundary instead of deep inside a later step.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- requirement


class Ambiguity(BaseModel):
    id: str
    question: str
    severity: Literal["blocking", "minor"]
    why_it_matters: str = ""
    assumption: str = Field("", description="What we will do if nobody answers.")


class AcceptanceCriterion(BaseModel):
    id: str
    text: str


class RequirementSpec(BaseModel):
    """The normalized engineering problem produced by the RequirementAnalyst."""

    title: str
    kind: Literal["greenfield", "brownfield", "bugfix", "tests", "docs"]
    intent: str
    problem_statement: str
    acceptance_criteria: list[AcceptanceCriterion]
    non_functional: list[str] = []
    out_of_scope: list[str] = []
    ambiguities: list[Ambiguity] = []
    assumptions: list[str] = []

    def blocking(self) -> list[Ambiguity]:
        return [a for a in self.ambiguities if a.severity == "blocking"]


# ---------------------------------------------------------------- brownfield


class ImpactedItem(BaseModel):
    path: str
    kind: Literal["module", "api", "data", "test", "doc", "config"]
    change: str
    risk: Literal["low", "medium", "high"] = "low"


class ImpactAnalysis(BaseModel):
    summary: str
    architecture: str = Field("", description="How the existing system fits together.")
    impacted: list[ImpactedItem]
    data_flows: list[str] = []
    risks: list[str] = []
    test_gaps: list[str] = []


# ---------------------------------------------------------------- plan

AgentName = Literal["architect", "coder", "tester", "doc_writer", "validator"]


class Task(BaseModel):
    id: str
    title: str
    agent: AgentName
    depends_on: list[str] = []
    description: str = ""
    acceptance: str = Field("", description="How we know this task is done.")
    outputs: list[str] = Field([], description="Files this task is expected to produce or modify.")


class Plan(BaseModel):
    rationale: str
    tasks: list[Task]
    change_size: Literal["major", "minor", "patch"]
    change_size_reason: str
    risks: list[str] = []
    tradeoffs: list[str] = []


# ---------------------------------------------------------------- execution


class FileChange(BaseModel):
    path: str
    content: str = ""
    action: Literal["write", "delete"] = "write"


class TaskOutput(BaseModel):
    """What a producing agent (architect / coder / tester / doc writer) returns."""

    files: list[FileChange]
    notes: str = ""
    decisions: list[str] = []


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskRecord(BaseModel):
    """Runtime state of one task (persisted for resume)."""

    task: Task
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    files: list[str] = []
    notes: str = ""
    error: str = ""
    feedback: list[str] = []
    runs: list[list[float]] = Field([], description="[start, end] of every attempt, for the timeline")


class CheckResult(BaseModel):
    name: str
    status: Literal["passed", "failed", "skipped"]
    summary: str
    details: str = ""


class ValidationReport(BaseModel):
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.status != "failed" for c in self.checks)

    def get(self, name: str) -> CheckResult | None:
        return next((c for c in self.checks if c.name == name), None)


# ---------------------------------------------------------------- review


class Finding(BaseModel):
    severity: Literal["high", "medium", "low"]
    check: str
    file: str = ""
    line: int = 0
    message: str
    suggestion: str = ""
    source: Literal["static", "agent"] = "agent"


class CoverageItem(BaseModel):
    criterion_id: str
    status: Literal["done", "partial", "missing"]
    evidence: str = ""


class ReviewResult(BaseModel):
    verdict: Literal["approve", "approve_with_comments", "changes_needed"]
    summary: str
    coverage: list[CoverageItem] = []
    findings: list[Finding] = []
    missed_scenarios: list[str] = []
    fixes: list[FileChange] = Field([], description="Proposed file changes; applied only after Gate 4.")


# ---------------------------------------------------------------- gates


class GateDecision(BaseModel):
    gate: str
    approved: bool
    by: str
    at: float
    note: str = ""
    answers: dict[str, str] = {}


# ---------------------------------------------------------------- run


class Phase(str, Enum):
    NEW = "new"
    ANALYZED = "analyzed"
    NEEDS_CLARIFICATION = "needs_clarification"
    CLARIFIED = "clarified"
    IMPACT_ANALYZED = "impact_analyzed"
    PLANNED = "planned"
    PLAN_APPROVED = "plan_approved"
    EXECUTED = "executed"
    COMMITTED = "committed"
    PR_READY = "pr_ready"
    REVIEWED = "reviewed"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


class RunState(BaseModel):
    run_id: str
    requirement_id: str
    requirement_path: str
    scenario: str
    workspace: str
    provider: str
    phase: Phase = Phase.NEW
    created_at: float
    branch: str = ""
    base_commit: str = ""
    commit: str = ""
    spec: RequirementSpec | None = None
    clarifications: dict[str, str] = {}
    impact: ImpactAnalysis | None = None
    plan: Plan | None = None
    tasks: dict[str, TaskRecord] = {}
    file_owner: dict[str, str] = Field({}, description="path -> task id that last wrote it")
    validation: ValidationReport | None = None
    review: ReviewResult | None = None
    decisions: list[GateDecision] = []
    warnings: list[str] = []
    llm_calls: int = 0
    error: str = ""
