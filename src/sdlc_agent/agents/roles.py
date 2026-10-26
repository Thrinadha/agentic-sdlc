"""The agents. Each one is a role prompt (``prompts/<name>.md``) plus a typed output contract.

Deterministic work (running tests, scanning, git, versioning, rendering reports) is done by tools,
not agents. LLMs are used only where judgment is needed.
"""

from __future__ import annotations

from ..orchestrator.models import (
    ImpactAnalysis,
    Plan,
    RequirementSpec,
    ReviewResult,
    TaskOutput,
)
from .base import Agent


class RequirementAnalyst(Agent):
    name = "requirement_analyst"
    schema = RequirementSpec

    def analyze(self, requirement: str) -> RequirementSpec:
        return self.ask("requirement_analyst", {"Requirement": requirement})

    def refine(self, requirement: str, spec: RequirementSpec, answers: dict[str, str]) -> RequirementSpec:
        qa = "\n".join(f"- [{a.id}] {a.question}\n  answer: {answers.get(a.id, a.assumption)}"
                       for a in spec.ambiguities)
        return self.ask("requirement_analyst.refine", {
            "Requirement": requirement,
            "Your first analysis": spec.model_dump_json(indent=1),
            "Answers from the human": qa,
            "Instruction": "Produce the final spec with the answers applied. Clear the ambiguities they resolve; "
                           "move accepted defaults into 'assumptions'.",
        })


class CodebaseAnalyst(Agent):
    name = "codebase_analyst"
    schema = ImpactAnalysis

    def analyze(self, spec: RequirementSpec, index_text: str, files: str) -> ImpactAnalysis:
        return self.ask("codebase_analyst", {
            "Requirement spec": spec.model_dump_json(indent=1),
            "Codebase index (generated with ast)": index_text,
            "Source files": files,
        })


class Planner(Agent):
    name = "planner"
    schema = Plan

    def plan(self, spec: RequirementSpec, impact: ImpactAnalysis | None, standards: str) -> Plan:
        return self.ask("planner", {
            "Requirement spec": spec.model_dump_json(indent=1),
            "Impact analysis (brownfield)": impact.model_dump_json(indent=1) if impact else "",
            "Coding standards": standards,
        })


class Producer(Agent):
    """Architect, coder, tester and doc writer share one contract: a task in, file changes out."""

    schema = TaskOutput

    def __init__(self, name: str, llm, scenario: str):
        super().__init__(llm, scenario)
        self.name = name

    def run(self, task_id: str, sections: dict[str, str], attempt: int) -> TaskOutput:
        return self.ask(f"{self.name}.{task_id}", sections, attempt=attempt)


class Reviewer(Agent):
    name = "reviewer"
    schema = ReviewResult

    def review(self, sections: dict[str, str], attempt: int = 1) -> ReviewResult:
        return self.ask("reviewer", sections, attempt=attempt)
