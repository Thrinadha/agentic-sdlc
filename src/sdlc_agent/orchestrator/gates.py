"""Human approval gates: controlled autonomy.

Agents work on their own between gates. At each gate a human (or a written policy acting for one)
approves or rejects. Two rules hold no matter which approver is used:

* A gate with **blockers** (failed tests, secret-scan findings, ...) is never auto-approved.
  A human can override one interactively, but only by typing the word ``override``.
* Every decision is recorded (who, when, what was asked, any note) in the run's audit log.
"""

from __future__ import annotations

import getpass
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .events import console
from .models import Ambiguity, GateDecision

GATES = {
    "clarify": "Gate 0: clarify blocking ambiguities",
    "plan": "Gate A: approve the plan",
    "commit": "Gate 1: commit the change",
    "pr": "Gate 3: raise the PR",
    "review_fixes": "Gate 4: apply review fixes",
    "escalation": "Escalation: automatic recovery exhausted",
    "merge": "Merge: approve merging the PR",
    "release": "Release: tag the release",
}

DEFAULT_POLICY = {
    # What the "auto" approver does at each gate. Blockers always reject, whatever is written here.
    "clarify": "answers_or_stop",  # answers_or_stop | assume
    "plan": "approve",
    "commit": "approve",
    "pr": "approve",
    "review_fixes": "approve",
    "escalation": "reject",
    "merge": "approve",
    "release": "approve",
}


@dataclass
class GateRequest:
    gate: str
    summary: str
    body: str = ""
    blockers: list[str] = field(default_factory=list)
    questions: list[Ambiguity] = field(default_factory=list)

    @property
    def title(self) -> str:
        return GATES.get(self.gate, self.gate)


class Approver(ABC):
    @abstractmethod
    def decide(self, req: GateRequest) -> GateDecision: ...


class InteractiveApprover(Approver):
    """Asks the person at the terminal."""

    def __init__(self, input_fn=None, answers: dict[str, str] | None = None):
        # Resolved at call time, so tests (and wrappers) can replace builtins.input.
        self._input = input_fn or (lambda prompt: input(prompt))
        self.answers = answers or {}  # pre-filled clarification answers (--answers), still shown to the human

    def decide(self, req: GateRequest) -> GateDecision:
        console("")
        console("=" * 78)
        console(f"  {req.title}")
        console(f"  {req.summary}")
        console("=" * 78)
        if req.body:
            console(req.body.rstrip())
        user = _user()

        if req.gate == "clarify":
            answers: dict[str, str] = {}
            for q in req.questions:
                console(f"\n[{q.id}] {q.question}")
                if q.why_it_matters:
                    console(f"   why: {q.why_it_matters}")
                default = self.answers.get(q.id, q.assumption)
                console(f"   {'answer from --answers' if q.id in self.answers else 'default assumption'}: {default}")
                ans = self._input("   answer (Enter = accept the above, 'stop' = stop the run): ").strip()
                if ans.lower() == "stop":
                    return GateDecision(gate=req.gate, approved=False, by=user, at=time.time(),
                                        note="stopped at clarification")
                answers[q.id] = ans or default
            return GateDecision(gate=req.gate, approved=True, by=user, at=time.time(), answers=answers)

        if req.blockers:
            console("\nBLOCKERS (automatic approval is not possible):")
            for b in req.blockers:
                console(f"  - {b}")
            ans = self._input("\nType 'override' to approve anyway, anything else to reject: ").strip().lower()
            ok = ans == "override"
            note = self._input("Reason (recorded in the audit log): ").strip() if ok else "rejected: blockers"
            return GateDecision(gate=req.gate, approved=ok, by=user, at=time.time(), note=note)

        ans = self._input("\nApprove? [y]es / [n]o (optionally add a note after a space): ").strip()
        ok = ans[:1].lower() == "y"
        note = ans[1:].strip(" ,:-") if len(ans) > 1 and ans.lower() not in ("yes", "no") else ""
        return GateDecision(gate=req.gate, approved=ok, by=user, at=time.time(), note=note)


class PolicyApprover(Approver):
    """Non-interactive approver driven by a written policy (CI, demos, evaluation runs)."""

    def __init__(self, policy: dict | None = None, answers: dict[str, str] | None = None):
        self.policy = {**DEFAULT_POLICY, **(policy or {})}
        self.answers = answers or {}

    @classmethod
    def from_files(cls, policy_file: Path | None, answers_file: Path | None) -> PolicyApprover:
        policy = yaml.safe_load(policy_file.read_text(encoding="utf-8")) if policy_file else None
        answers = yaml.safe_load(answers_file.read_text(encoding="utf-8")) if answers_file else None
        return cls((policy or {}).get("gates", policy), {str(k): str(v) for k, v in (answers or {}).items()})

    def decide(self, req: GateRequest) -> GateDecision:
        rule = self.policy.get(req.gate, "reject")
        by = f"policy:{rule}"
        now = time.time()
        if req.blockers:
            return GateDecision(gate=req.gate, approved=False, by=by, at=now,
                                note="blocked: " + "; ".join(req.blockers))
        if req.gate == "clarify":
            missing = [q.id for q in req.questions if q.id not in self.answers]
            if not missing:
                return GateDecision(gate=req.gate, approved=True, by="policy:answers_file", at=now,
                                    answers={q.id: self.answers[q.id] for q in req.questions})
            if rule == "assume":
                return GateDecision(gate=req.gate, approved=True, by=by, at=now,
                                    note="proceeding on documented assumptions",
                                    answers={q.id: self.answers.get(q.id, q.assumption) for q in req.questions})
            return GateDecision(gate=req.gate, approved=False, by=by, at=now,
                                note=f"needs a human answer for: {', '.join(missing)}")
        return GateDecision(gate=req.gate, approved=rule == "approve", by=by, at=now)


def _user() -> str:
    try:
        return f"human:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 - getuser can fail in odd environments
        return "human"
