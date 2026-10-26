# Sample outputs

Produced by `sdlc demo` (offline mock provider, unattended `--policy auto`). Regenerate with `sdlc demo`.
Local paths are replaced by `<workspace>`, `<repo>`, `<tmp>` and `<home>`.

| Folder | Scenario | Final phase |
|---|---|---|
| [greenfield-url-shortener/](greenfield-url-shortener/) | mandatory use case | `reviewed`, released `0.1.0` |
| [brownfield-bookmarks/](brownfield-bookmarks/) | bug fix + enhancement on an existing API | `reviewed`, released `1.3.0` |
| [ambiguous-notifications/1-stopped-for-clarification/](ambiguous-notifications/1-stopped-for-clarification/) | ambiguous requirement, no answers yet | `needs_clarification` |
| [ambiguous-notifications/2-completed/](ambiguous-notifications/2-completed/) | same run, resumed with answers | `reviewed`, released `0.1.0` |
| [failure-recovery-exhausted/](failure-recovery-exhausted/) | recovery exhausted, escalation rejected | `failed` (expected) |

## Files in each folder

| File | What it is |
|---|---|
| `summary.md` | **start here**: the engineering summary (requirement, ambiguities, impact, plan and rationale, orchestration timeline, artifacts, validation, review, risks and trade-offs, gate audit log, assumptions and limitations) |
| `plan.md` | the task DAG shown at the plan gate |
| `impact.md` | brownfield only: codebase index and impact analysis |
| `clarification-request.md` | ambiguous only: the questions a human must answer |
| `pr.md` | the filled PR template with real validation results |
| `review.md` | review verdict, per-criterion coverage, findings, missed scenarios, fixes applied |
| `cr.md` | change request draft |
| `release-notes-*.md` | release notes and version |
| `debug.md` | `sdlc debug` report: failures, last feedback, failed checks, next step |
| `events.jsonl` | the hash-chained event log (every step, LLM call and gate decision) |
| `alerts.jsonl` | alerts raised by the run |
| `workspace/` | the resulting repository content (generated code, contract, tests, docs) |

The full run state (`state.json`) and the raw debug log (`debug.log`) are not committed; they are written
to `<workspace>/.sdlc/runs/<run-id>/` when you run `sdlc demo` or `sdlc implement` yourself.
