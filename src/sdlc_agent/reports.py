"""Deterministic renderers: plan, PR body, review report, engineering summary, CR and release notes.

These are templates over the run state, not LLM output, so every number and link in them is real.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .orchestrator.dag import TaskGraph
from .orchestrator.models import ReviewResult, RunState, ValidationReport

ICON = {"passed": "✅ Passed", "failed": "❌ Failed", "skipped": "⏭️ Skipped"}


def _ts(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "-"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    def esc(s: object) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ------------------------------------------------------------------ plan


def render_plan(state: RunState, heading: str = "##", standalone: bool = True) -> str:
    """The plan. ``standalone`` adds a title and the risks/trade-offs (the summary has its own section)."""
    plan = state.plan
    graph = TaskGraph(plan.tasks)
    rows = [[t.id, t.agent, t.title, ", ".join(t.depends_on) or "-", ", ".join(t.outputs) or "-"]
            for t in plan.tasks]
    levels = "\n".join(f"{i + 1}. {', '.join(lv)}" + (" *(parallel)*" if len(lv) > 1 else "")
                       for i, lv in enumerate(graph.levels()))
    out = f"""**Rationale:** {plan.rationale}

**Change size:** {plan.change_size} ({plan.change_size_reason})

{heading} Tasks
{_table(["Task", "Agent", "Title", "Depends on", "Outputs"], rows)}

{heading} Execution order (tasks on one level run in parallel)
{levels}

```mermaid
{graph.to_mermaid()}
```
"""
    if standalone:
        out = (f"# Plan: {state.requirement_id} {state.spec.title}\n\n{out}\n"
               f"{heading} Risks\n{_bullets(plan.risks)}\n\n{heading} Trade-offs\n{_bullets(plan.tradeoffs)}\n")
    return out


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- none"


# ------------------------------------------------------------------ validation


def render_validation(v: ValidationReport | None) -> str:
    if not v:
        return "_not run_"
    return _table(["Check", "Result", "Summary"], [[c.name, ICON[c.status], c.summary] for c in v.checks])


# ------------------------------------------------------------------ PR


def fill_template(template: str, sections: dict[str, str], ticks: set[str], inline: dict[str, str]) -> str:
    """Fill a PR/CR template without changing its structure.

    ``sections``: heading -> content that replaces the ``<!-- ... -->`` placeholder in that section.
    ``ticks``: checkbox labels to tick. ``inline``: ``Label:`` -> value for ``Label: <!-- ... -->`` lines.
    """
    out, current = [], ""
    for line in template.splitlines():
        h = re.match(r"^##+\s+(.*)$", line)
        if h:
            current = h.group(1).strip()
        for label, value in inline.items():
            if line.startswith(f"{label}:") and "<!--" in line:
                line = f"{label}: {value}"
        if line.strip().startswith("<!--") and line.strip().endswith("-->") and current in sections:
            line = sections[current]
        box = re.match(r"^(\s*)- \[ \] (.*)$", line)
        if box:
            label = re.sub(r"\*\*", "", box.group(2)).split(" - ")[0].strip()
            if label in ticks:
                line = f"{box.group(1)}- [x] {box.group(2)}"
        out.append(line)
    return "\n".join(out) + "\n"


def changes_table(files: dict[str, str], state: RunState) -> str:
    rows = []
    for path, status in sorted(files.items()):
        owner = state.file_owner.get(path, "")
        task = state.tasks.get(owner)
        rows.append([f"`{path}`", status, f"{owner} {task.task.title}" if task else owner or "-"])
    return _table(["File", "Change", "Task"], rows)


def render_pr(state: RunState, template: str, changed: dict[str, str], title: str) -> str:
    spec, plan, v = state.spec, state.plan, state.validation
    tests = v.get("tests") if v else None
    steps = "\n".join(f"{i}. {t.title} ({t.agent})" for i, t in enumerate(plan.tasks, start=1))
    description = f"""Implements {state.requirement_id}

**Summary**
{spec.problem_statement}

**Changes**
{changes_table(changed, state)}

**How it works**
{steps}

**Acceptance criteria**
{_bullets([f"{a.id}: {a.text}" for a in spec.acceptance_criteria])}
"""
    if spec.assumptions or state.clarifications:
        description += "\n### Additional Notes\n**Assumptions / clarifications**\n" + _bullets(
            spec.assumptions + [f"{k}: {v}" for k, v in state.clarifications.items()]) + "\n"
    validate = f"""1. `pip install -e .[app,dev]`
2. `python -m pytest -q` from the repository root
3. Review the API contract in `api/openapi.yaml` (if present) against the endpoints

**Tested run:** `{state.run_id}` (log: `.sdlc/runs/{state.run_id}/events.jsonl`)
{render_validation(v)}"""
    impact = "\n".join(f"- {r}" for r in (plan.risks[:4] or ["Low: isolated change"]))
    tested_rows = [[c.name, ICON[c.status] + (f" - {c.summary}" if c.summary else "")] for c in (v.checks if v else [])]
    tested = _table(["Test", "Result"], tested_rows)
    ticks = {plan.change_size.capitalize()}
    if v:
        if tests and tests.status == "passed":
            ticks |= {"Unit tests", "Integration tests"} if any("integration" in p for p in changed) else {"Unit tests"}
        for name, label in (("contract", "Contract check"), ("lint", "Lint / static analysis"),
                            ("secrets", "Secret scan")):
            c = v.get(name)
            if c and c.status == "passed":
                ticks.add(label)
    if any(p.endswith(".md") for p in changed):
        ticks.add("Documentation updated")
    if v and v.passed:
        ticks |= {"Code follows the project coding standards", "Tests added for new behaviour and bug fixes",
                  "No secrets or credentials in the change"}
    return fill_template(template, {
        "Description": description.strip(),
        "How to Validate Change": validate,
        "Potential Impact": impact,
        "How Has This Been Tested": tested,
    }, ticks, {"Ticket #": state.requirement_id}) + f"\n<!-- title: {title} -->\n"


# ------------------------------------------------------------------ review


def render_review(state: RunState, review: ReviewResult, title: str, applied: str) -> str:
    cov = "\n".join(
        f"  {'✔' if c.status == 'done' else '~' if c.status == 'partial' else '✖'} {c.criterion_id} "
        f"{c.status}{' - ' + c.evidence if c.evidence else ''}" for c in review.coverage) or "  (none)"
    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(review.findings, key=lambda f: order[f.severity])
    rows = [[f.severity.upper(), f.check, (f"{f.file}:{f.line}" if f.line else f.file) or "-", f.message,
             f.suggestion, f.source] for f in findings]
    return f"""# Review: {title}

**Verdict:** {review.verdict.replace('_', ' ')}

{review.summary}

## Story coverage
```
{cov}
```

## Findings (most important first)
{_table(["Severity", "Check", "Location", "Problem", "Suggested fix", "Source"], rows) if rows else "None."}

## Missed scenarios
{_bullets(review.missed_scenarios)}

## Fixes
{applied}
"""


# ------------------------------------------------------------------ summary


def render_timeline(state: RunState) -> str:
    """One row per attempt, so a re-run requested by the validator shows as its own step."""
    runs = [(r, i + 1, start, end) for r in state.tasks.values() for i, (start, end) in enumerate(r.runs)]
    if not runs:
        return "_no tasks ran_"
    t0 = min(start for _, _, start, _ in runs)
    rows = []
    for r, attempt, start, end in sorted(runs, key=lambda x: (x[2], x[0].task.id)):
        overlap = sorted({o.task.id for o, _, s, e in runs if o is not r and s < end and e > start})
        why = ""
        if attempt > 1:
            why = "re-run with validation feedback" if r.task.agent != "validator" else "re-validation"
        rows.append([r.task.id, r.task.agent, str(attempt), f"+{start - t0:.2f}s", f"{end - start:.2f}s",
                     ", ".join(overlap) or "-", why])
    note = ("\n\n*Durations are short with the offline provider (no model latency); with a live model each "
            "agent step takes seconds to minutes and the parallel levels save that time.*"
            if state.provider == "mock" else "")
    return _table(["Task", "Agent", "Attempt", "Start", "Duration", "Overlapped with", "Why"], rows) + note


def render_summary(state: RunState, events: list[dict], extra: dict[str, str] | None = None) -> str:
    spec, plan = state.spec, state.plan
    extra = extra or {}
    sections = [f"# Engineering summary: {state.requirement_id} {spec.title if spec else ''}",
                _table(["Field", "Value"], [
                    ["Run", f"`{state.run_id}`"], ["Scenario", state.scenario], ["Provider", state.provider],
                    ["Phase", state.phase.value], ["Branch", f"`{state.branch}`" if state.branch else "-"],
                    ["Commit", f"`{state.commit[:10]}`" if state.commit else "-"], ["LLM calls", str(state.llm_calls)],
                ])]
    number = iter(range(1, 100))

    def h(title: str) -> str:
        return f"## {next(number)}. {title}\n"

    if spec:
        sections.append(f"""{h("Requirement (normalized)")}**Kind:** {spec.kind}
**Intent:** {spec.intent}

{spec.problem_statement}

**Acceptance criteria**
{_bullets([f"{a.id}: {a.text}" for a in spec.acceptance_criteria])}

**Non-functional**
{_bullets(spec.non_functional)}

**Out of scope**
{_bullets(spec.out_of_scope)}""")
        amb = [[a.id, a.severity, a.question, state.clarifications.get(a.id, a.assumption)] for a in spec.ambiguities]
        sections.append(h("Ambiguities and how they were resolved")
                        + (_table(["Id", "Severity", "Question", "Resolution"], amb) if amb else "None found.")
                        + ("\n\n**Assumptions**\n" + _bullets(spec.assumptions) if spec.assumptions else ""))
    if state.impact:
        imp = state.impact
        sections.append(f"""{h("Codebase impact (brownfield)")}{imp.summary}

**Architecture today:** {imp.architecture}

{_table(["Path", "Kind", "Change", "Risk"], [[f"`{i.path}`", i.kind, i.change, i.risk] for i in imp.impacted])}

**Data flows**
{_bullets(imp.data_flows)}

**Test gaps found**
{_bullets(imp.test_gaps)}""")
    if plan:
        sections.append(h("Implementation plan and rationale") + render_plan(state, "###", standalone=False))
        recovery = [e["message"] for e in events if e["type"] in ("task.retry", "task.failed")]
        sections.append(h("Orchestration timeline") + render_timeline(state)
                        + "\n\n**Recovery events**\n" + _bullets(recovery))
        files = sorted(state.file_owner.items())
        sections.append(h("Generated artifacts") + _table(
            ["File", "Produced by"], [[f"`{p}`", o] for p, o in files if o != "base"]))
    sections.append(h("Validation") + render_validation(state.validation))
    if state.review:
        r = state.review
        sections.append(h("Review") + f"**Verdict:** {r.verdict}. {r.summary}\n\n"
                        + _bullets([f"[{f.severity}] {f.check}: {f.message}" for f in r.findings]))
    if plan:
        sections.append(h("Risks and trade-offs") + "**Risks**\n" + _bullets(plan.risks)
                        + "\n\n**Trade-offs**\n" + _bullets(plan.tradeoffs))
    if state.warnings:
        sections.append(h("Security warnings") + _bullets(state.warnings))
    approvers = {d.by.split(":")[0] for d in state.decisions}
    who = ("Approvals here were given by the written gate policy (`--policy auto`, used for this unattended "
           "run). Interactively, a human answers each gate; blockers are never auto-approved."
           if approvers == {"policy"} else "")
    sections.append(h("Human oversight (gate audit log)") + _table(
        ["Gate", "Decision", "By", "When", "Note"],
        [[d.gate, "approved" if d.approved else "rejected", d.by, _ts(d.at), d.note] for d in state.decisions])
        + (f"\n\n{who}" if who else ""))
    sections.append(h("Assumptions and limitations") + _bullets(
        (spec.assumptions if spec else []) + [
            "Generated code is validated by tests, lint, an unsafe-pattern scan, a contract check and a secret "
            "scan; it is not load tested here. Scalability claims are design-level.",
            "With the mock provider the agents' answers are pre-written fixtures, not live model output; "
            "the orchestration, "
            "gates, git operations and all validation run for real.",
        ]))
    for title, body in extra.items():
        sections.append(f"## {title}\n{body}")
    return "\n\n".join(sections) + "\n"


# ------------------------------------------------------------------ CR / release


def render_cr(state: RunState, template: str, version_from: str | None, version_to: str,
              prs: list[dict], changed: list[str]) -> str:
    plan = state.plan
    pr_rows = [[p["title"], p["branch"], p["change_size"], p.get("url") or p["path"]] for p in prs]
    v = state.validation
    return fill_template(template, {
        "Summary": f"Release **{version_to}** (from {version_from or 'no previous release'}): {state.spec.title}.\n\n"
                   f"{state.spec.intent}",
        "Changes": _table(["PR", "Branch", "Size", "Link"], pr_rows) + "\n\nFiles: " + ", ".join(
            f"`{c}`" for c in changed[:30]) + (" ..." if len(changed) > 30 else ""),
        "Risk and Impact": _bullets(plan.risks) + "\n\n**Risk level:** "
                           + {"major": "High", "minor": "Medium"}.get(plan.change_size, "Low"),
        "Test Evidence": render_validation(v) + f"\n\nRun `{state.run_id}`; review verdict: "
                         + (state.review.verdict if state.review else "not reviewed"),
        "Implementation Plan": "1. Merge the approved PR(s) to `main`\n"
                               f"2. Tag `{version_to}` and build the release artifact from the tag\n"
                               "3. Deploy to staging; run the smoke tests (health check + create/resolve/stats)\n"
                               "4. Deploy to production behind the load balancer (rolling, one instance at a time)\n"
                               "5. Monitor error rate, p95 latency and 5xx for 30 minutes",
        "Backout Plan": f"Redeploy the previous tag `{version_from or 'n/a'}`. Schema changes are additive, so "
                        "the previous version runs against the new schema. If data must be reverted, restore "
                        "from the pre-deploy backup.",
    }, set(), {"Change number": "TBD", "Window": "TBD", "Version": version_to})


def render_release_notes(version: str, previous: str | None, prs: list[dict]) -> str:
    rows = [[p["title"], p["change_size"], p["branch"]] for p in prs]
    return f"""# Release {version}

Previous release: {previous or 'none'}

{_table(["Change", "Size", "Branch"], rows)}

Version rule: the highest Change Size ticked across merged PRs (major > minor > patch) is applied once
to the previous tag.
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
