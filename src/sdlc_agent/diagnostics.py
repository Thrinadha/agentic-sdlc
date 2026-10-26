"""`sdlc debug` and `sdlc logs`: find out what happened in a run and what to do next."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .orchestrator.events import verify_log
from .orchestrator.models import Phase, RunState, TaskStatus

NEXT_STEP = {
    Phase.NEEDS_CLARIFICATION: "Answer the questions in reports/clarification-request.md, then "
                               "`sdlc resume -w {ws} --run {run} --answers <answers.yaml>` (or resume interactively).",
    Phase.FAILED: "Fix the cause shown below (or give guidance at the escalation gate), then "
                  "`sdlc resume -w {ws} --run {run}`. Failed tasks restart with their earlier feedback.",
    Phase.REJECTED: "The plan was rejected. Adjust the requirement and start a new run with `sdlc implement`.",
    Phase.EXECUTED: "The commit gate was not approved. `sdlc resume -w {ws} --run {run}` asks again.",
    Phase.COMMITTED: "The PR gate was not approved. `sdlc resume -w {ws} --run {run}` asks again.",
    Phase.PR_READY: "`sdlc review -w {ws} --run {run}`",
    Phase.REVIEWED: "`sdlc cr -w {ws}` then `sdlc release -w {ws}`",
}


def _ts(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "-"


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def filter_events(events: list[dict], types: list[str] | None = None, task: str | None = None,
                  grep: str | None = None, tail: int | None = None) -> list[dict]:
    out = []
    for e in events:
        if types and e["type"] not in types and not any(e["type"].startswith(t + ".") for t in types):
            continue
        if task and e.get("task") != task and f"{task} " not in e["message"] and f"{task}[" not in e["message"]:
            continue
        if grep and grep.lower() not in json.dumps(e).lower():
            continue
        out.append(e)
    return out[-tail:] if tail else out


def format_event(e: dict) -> str:
    extra = {k: v for k, v in e.items() if k not in ("ts", "run_id", "type", "message", "prev", "hash")}
    tail = f"  {json.dumps(extra, default=str)}" if extra else ""
    return f"{_ts(e['ts'])}  {e['type']:<11} {e['message']}{tail}"


def debug_report(run_dir: Path, workspace: Path) -> str:
    state = RunState.model_validate_json((run_dir / "state.json").read_text(encoding="utf-8"))
    events = _jsonl(run_dir / "events.jsonl")
    alerts = _jsonl(run_dir / "alerts.jsonl")
    events_file = run_dir / "events.jsonl"
    log_ok, log_msg = verify_log(events_file) if events_file.exists() else (False, "missing")
    hint = NEXT_STEP.get(state.phase, "Nothing to do.").format(ws=workspace, run=state.run_id)
    lines = [f"# Debug report: run {state.run_id}", "",
             f"- Requirement: {state.requirement_id} ({state.scenario})",
             f"- Phase: **{state.phase.value}**" + (f"  \n- Error: `{state.error}`" if state.error else ""),
             f"- Provider: {state.provider}, LLM calls: {state.llm_calls}",
             f"- Branch: {state.branch or '-'}, commit: {state.commit[:10] or '-'}",
             f"- Audit log: {'intact' if log_ok else 'NOT VERIFIED'} ({log_msg})", "",
             f"**Next step:** {hint}", ""]

    problems = [r for r in state.tasks.values() if r.status != TaskStatus.DONE or r.attempts > 1]
    if problems:
        lines += ["## Tasks that failed, were skipped or needed retries", "",
                  "| Task | Agent | Status | Attempts | Error |", "|---|---|---|---|---|"]
        for r in problems:
            lines.append(f"| {r.task.id} | {r.task.agent} | {r.status.value} | {r.attempts} | "
                         f"{(r.error or '-').replace('|', '/')[:200]} |")
        for r in problems:
            if r.feedback:
                lines += ["", f"### {r.task.id}: last feedback given to the agent", "```",
                          r.feedback[-1][-2500:], "```"]

    if state.validation:
        failed = [c for c in state.validation.checks if c.status == "failed"]
        lines += ["", "## Latest validation", "",
                  " · ".join(f"{c.name}: {c.status}" for c in state.validation.checks)]
        for c in failed:
            lines += ["", f"### {c.name}: {c.summary}", "```", c.details[-3000:] or "(no details)", "```"]

    rejected = [d for d in state.decisions if not d.approved]
    if rejected:
        lines += ["", "## Gates that were not approved", ""]
        lines += [f"- {d.gate} by {d.by} at {_ts(d.at)}: {d.note or '-'}" for d in rejected]
    if state.warnings:
        lines += ["", "## Warnings", "", *(f"- {w}" for w in state.warnings)]
    if alerts:
        lines += ["", "## Alerts raised", "", *(f"- [{a['severity']}] {a['title']}: {a['message'][:200]}"
                                             for a in alerts)]
    trouble = filter_events(events, ["task", "warn", "error"])
    trouble = [e for e in trouble if e["type"] in ("task.retry", "task.failed", "warn", "error")]
    if trouble:
        lines += ["", "## Problem timeline", "", "```", *(format_event(e) for e in trouble[-30:]), "```"]

    llm_dir = run_dir / "llm"
    lines += ["", "## Where to look", "",
              f"- Events (tamper-evident): `{run_dir / 'events.jsonl'}`; filter with "
              f"`sdlc logs -w {workspace} --run {state.run_id} --task <id>` or `--type task.failed,gate`",
              f"- Debug log (commands, exit codes, timings, LLM calls): `{run_dir / 'debug.log'}`",
              f"- LLM prompts and answers: `{llm_dir}`" if llm_dir.exists()
              else "- LLM prompts and answers: rerun with `--debug` (or SDLC_DEBUG=1) to capture them",
              f"- State (resumable): `{run_dir / 'state.json'}`",
              f"- Reports: `{run_dir / 'reports'}`"]
    return "\n".join(lines) + "\n"
