# agentic-sdlc

**An agentic software engineering system that turns a requirement into a reviewable engineering outcome:**
a normalized spec, a dependency graph of tasks, code, an API contract, tests and docs, a validated commit,
a pull request, a code review, a change request and a tagged release.

Eight specialised agents do the work. A deterministic orchestrator schedules them as a task graph, runs
independent tasks in parallel, routes failures back to the agent responsible, and **stops at human approval
gates**. Works with Claude, OpenAI, Azure OpenAI or a local model, and also runs fully offline.

```
requirement.md
   │  RequirementAnalyst ── blocking ambiguity? ──▶ [Gate 0: clarify]   stops and asks a human
   │  CodebaseAnalyst      brownfield: ast index of the repo → impact map (files, APIs, data flows, risks)
   │  Planner ──▶ task DAG (validated: no cycles, one validator, no parallel writes) ──▶ [Gate A: plan]
   ▼
 Engine: every task whose dependencies are done runs in parallel   architect ∥ coder ∥ tester ∥ doc writer
   │  validator: syntax · lint · unsafe code · Bandit · dependency audit · API contract · tests · secrets
   │             generated code runs sandboxed: no credentials, no outbound network
   │  failure ──▶ routed to the task that owns the faulty code ──▶ re-run with the error ──▶ [Escalation gate]
   ▼
 [Gate 1: commit] ─▶ [Gate 3: PR] ─▶ Reviewer agent + static checks ─▶ [Gate 4: fixes, re-validated]
   ─▶ change request ─▶ [merge gate] ─▶ [release gate] ─▶ semver tag
```

---

## For reviewers: how this meets the brief

| Evaluation criterion | Where to look | What you will see |
|---|---|---|
| **End-to-end workflow completeness** | [greenfield summary](examples/outputs/greenfield-url-shortener/summary.md), [PR](examples/outputs/greenfield-url-shortener/pr.md), [review](examples/outputs/greenfield-url-shortener/review.md), [CR](examples/outputs/greenfield-url-shortener/cr.md), [release notes](examples/outputs/greenfield-url-shortener/release-notes-0.1.0.md) | requirement → spec → plan → code/tests/docs → validation → commit → PR → review (fix applied after Gate 4 and re-validated) → CR → merge → tag `0.1.0` |
| **System design and architecture** | [docs/architecture.md](docs/architecture.md), [`src/sdlc_agent/`](src/sdlc_agent/) | typed agent contracts, provider-neutral LLM layer, DAG engine, gates, tools, resumable state machine; design decisions with trade-offs |
| **Task decomposition and orchestration** | [plan](examples/outputs/greenfield-url-shortener/plan.md), [engine.py](src/sdlc_agent/orchestrator/engine.py), summary §5 *Orchestration timeline* | contract-first DAG in parallel levels; tasks overlap in time; a real test failure is **routed to the coder who owns the faulty file** (not the tester), fixed, re-validated |
| **Quality and realism of outputs** | [generated URL shortener](examples/outputs/greenfield-url-shortener/workspace/) ([service](examples/outputs/greenfield-url-shortener/workspace/app/service.py), [API](examples/outputs/greenfield-url-shortener/workspace/app/api.py), [OpenAPI](examples/outputs/greenfield-url-shortener/workspace/api/openapi.yaml), [schema](examples/outputs/greenfield-url-shortener/workspace/db/schema.sql), [tests](examples/outputs/greenfield-url-shortener/workspace/tests/), [ADRs](examples/outputs/greenfield-url-shortener/workspace/docs/adr/), [scalability](examples/outputs/greenfield-url-shortener/workspace/docs/scalability.md)) | layered FastAPI + SQLAlchemy service, 6 endpoints matching the contract, 44 passing unit + integration tests, ADRs with alternatives, scaling and failure-mode analysis |
| **Validation and risk management** | [docs/testing.md](docs/testing.md), [docs/security.md](docs/security.md), summary §7–§9 | 8 checks on every run; blockers can never be auto-approved; sandboxed execution; prompt-injection fencing; tamper-evident audit log; risks, trade-offs and an honest gaps list |
| **Clarity and defensibility** | [docs/requirements-coverage.md](docs/requirements-coverage.md) | every requirement of the brief → implementation → evidence (a test or an output file) |

**Controlled autonomy:** agents run unattended *between* gates; a human (or, in CI, a written policy) decides
*at* gates. See [gates.py](src/sdlc_agent/orchestrator/gates.py) and the test
[`test_brownfield_lifecycle_with_a_human_at_every_gate`](tests/integration/test_cli.py).

## What is real and what is replayed

So that anyone can run the system without an API key, the default **mock provider** replays
**pre-written agent answers** from [`fixtures/`](fixtures/). These were written as reference answers for the
four example scenarios; they are **not** captured from a live model, and the code you see under
`fixtures/<scenario>/files/` is the content those answers contain.

Everything that happens *to* those answers is the real system, identical in offline and live mode:

| Real in every run | Proof |
|---|---|
| Scheduling the task graph, parallel execution, file ownership | `test_independent_tasks_really_run_in_parallel` (a barrier that deadlocks unless tasks run concurrently) |
| Writing files through the sandbox; git branches, commits, merges, tags | `test_scenarios.py`, the workspaces' git history |
| Running the generated project's own test suite, lint, Bandit, contract and secret checks | the URL shortener's first coder answer contains a real bug; the real test suite catches it |
| Routing the failure to the responsible task, re-running it with the error, re-validating | `test_validation_failure_is_routed_to_the_owner_of_the_faulty_file` |
| Gates, blockers, escalation, resume, audit log, alerts | `test_gates.py`, `test_cli.py` |
| The **live provider path**: HTTP, auth, JSON mode, parsing, schema validation, retry on 429, repair of a malformed answer | [`test_live_provider_path.py`](tests/integration/test_live_provider_path.py) runs the whole URL-shortener flow through the real OpenAI-compatible provider against a local endpoint |

With a real provider (`--provider anthropic|openai`) the agents generate the answers for **any** requirement,
and the same checks and gates apply. `--record` saves a live run as new fixtures.

---

## Quick start (offline, no API key)

Requires Python 3.10+ and git.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e ".[app,dev]"

sdlc doctor        # checks Python, git, packages, config, sandbox  →  "ready"
sdlc demo          # the four scenarios end to end; outputs in examples/outputs/
pytest             # 134 tests: unit, end-to-end scenarios, CLI, live provider path
```

Step-by-step evaluation, with what each step proves: **[docs/self-test-guide.md](docs/self-test-guide.md)**.

## Example scenarios

| Scenario | Requirement | Demonstrates | Output |
|---|---|---|---|
| **Greenfield (mandatory)** | [*"Build a scalable URL shortener service with APIs, persistence, and analytics."*](examples/requirements/url-shortener.md) | 9 testable acceptance criteria, 4 ambiguities resolved with documented defaults; 7-task DAG in 5 levels; real test failure → routed to the coder → fixed; review fix via Gate 4; release `0.1.0` | [outputs](examples/outputs/greenfield-url-shortener/) |
| **Brownfield** | [fix a paging bug + add a tag filter to an existing API](examples/requirements/brownfield-bookmarks.md) | ast index + impact analysis that finds the off-by-one root cause and the test gap that hid it; 4 tasks in parallel; regression tests; existing tests kept; `1.2.0 → 1.3.0` | [outputs](examples/outputs/brownfield-bookmarks/), [impact](examples/outputs/brownfield-bookmarks/impact.md) |
| **Ambiguous** | [*"Users should get notified about things that matter to them, and it should be fast."*](examples/requirements/ambiguous-notifications.md) | 3 blocking ambiguities → run stops before planning with a [clarification request](examples/outputs/ambiguous-notifications/1-stopped-for-clarification/clarification-request.md) → resumes with answers → refined spec → full delivery | [stopped](examples/outputs/ambiguous-notifications/1-stopped-for-clarification/), [completed](examples/outputs/ambiguous-notifications/2-completed/) |
| **Failure / recovery** | [a fix the coder never gets right](examples/requirements/failing-calculator.md) | retries with feedback exhausted → escalation gate → alerts → [debug report](examples/outputs/failure-recovery-exhausted/debug.md) with the failing test and next step → `sdlc resume` | [outputs](examples/outputs/failure-recovery-exhausted/) |

Each run produces an **engineering summary** (`summary.md`): normalized requirement, ambiguities and
resolutions, codebase impact (brownfield), implementation plan and rationale, orchestration timeline,
generated artifacts, validation results, review, risks and trade-offs, the gate audit log, and assumptions
and limitations.

## Run it yourself, as the approver

```bash
sdlc implement examples/requirements/url-shortener.md -w ws/url   # asks you at every gate (y/n)
sdlc review  -w ws/url        # reviewer agent + static checks against standards/; Gate 4 for fixes
sdlc cr      -w ws/url        # change request draft from standards/cr_template.md
sdlc release -w ws/url        # merge gate + release gate → semver tag from the PR's Change Size box
sdlc resume  -w ws/url        # continue a stopped or failed run (state is checkpointed after every task)
```
Unattended (CI): `--policy auto` with rules in [`policies/auto.yaml`](policies/auto.yaml). Failing checks,
secret findings and bad PR hygiene are blockers that no policy can approve.

Write your own requirement as Markdown with a small header (see [`examples/requirements/`](examples/requirements/))
and run it with a real provider.

## Use a real model (any provider)

| Provider | Setup |
|---|---|
| Claude | `pip install -e ".[anthropic]"`, `ANTHROPIC_API_KEY`, `--provider anthropic` (default model `claude-opus-5-5`; override with `SDLC_MODEL`) |
| OpenAI | `OPENAI_API_KEY`, `SDLC_MODEL=<model id>`, `--provider openai` |
| Azure OpenAI | `--provider openai`, `SDLC_OPENAI_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment>`, `SDLC_OPENAI_API_VERSION`, `OPENAI_API_KEY` |
| Ollama / vLLM / LM Studio | `--provider openai`, `SDLC_OPENAI_BASE_URL=http://localhost:11434/v1`, `SDLC_MODEL=<local model>` |

Adding a provider means implementing one method, `LLMProvider.complete` ([llm/base.py](src/sdlc_agent/llm/base.py)).
Every answer is validated against the agent's pydantic schema; invalid output gets a repair prompt, and
transient errors get exponential backoff. A per-run call budget caps cost.

## Logs, debugging and alerts

```bash
sdlc debug  -w <ws>                 # what failed, why (failing test output, task errors), and the next step
sdlc logs   -w <ws> --task T3       # filter the event log: --type task.failed,gate  --grep  --tail  --json
sdlc logs   -w <ws> --debug-log     # commands, exit codes, timings, LLM calls (secrets redacted)
sdlc alerts -w <ws>                 # alerts raised by a run;  sdlc alerts --test  sends a test alert
sdlc audit  -w <ws>                 # verify the tamper-evident (hash-chained) event logs
sdlc implement ... --debug          # also save redacted LLM prompts and answers;  -v  prints debug logs
```
Alerts (run failed, task failed, escalation, gate rejected, human input needed, security warnings) go to
`alerts.jsonl` and, when `SDLC_ALERT_WEBHOOK` is set, to Slack, Teams, Mattermost or any JSON webhook.

## Configuration

Every setting is an environment variable with a safe default; command-line flags win. Values come from the
process environment and, on Windows, from the **user** environment, so secrets never live in files.
`sdlc config` lists every setting and its source (secrets only as *set* / *not set*);
[`.env.example`](.env.example) documents them; [`scripts/setup-env.ps1`](scripts/setup-env.ps1) sets them
for your user with secrets typed hidden. In GitHub Actions, credentials are repository **secrets** and other
settings repository **variables** ([ci.yml](.github/workflows/ci.yml)).

## Security, in brief

Generated code is treated as untrusted: it runs in subprocesses with an allowlisted environment (no API keys
or tokens) and a loopback-only network guard. Agents can only write inside the workspace (no `..`, `.git`,
CI workflows). Repository content is fenced as untrusted data in every prompt, and injection phrases are
flagged at the plan gate. The secret scan blocks commits. Event logs are hash-chained and their head is
anchored in each commit. Details, a NIST SP 800-53 / OWASP LLM Top 10 mapping and the known gaps:
[docs/security.md](docs/security.md).

## Testing

134 automated tests ([docs/testing.md](docs/testing.md)):
- **unit:** DAG validation, parallel execution, failure routing, escalation, gates and blockers, sandbox,
  secret scan, LLM repair/retry/budget, config, alerts, redaction, review checks, templates, semver
- **end to end:** each scenario through the real workflow; the CLI driven by a human answering every
  gate; a failure that alerts a webhook and is diagnosed and resumed; the live provider path including
  Azure mode and an unreachable endpoint

CI runs lint, the tests on Python 3.10–3.12, Bandit and pip-audit on the system itself, and the demo.

## Limitations (honest)

- Offline examples use pre-written agent answers (above). Output quality with a live model depends on the model.
- The network guard runs in-process; production would run validation in a container without network.
- Tooling targets Python projects (pytest, ruff, ast index, FastAPI contract check); the orchestrator is language-neutral.
- Agents return whole files; very large brownfield files would need patch-style edits.
- No load testing: the URL shortener's scalability is argued in design docs, not measured.

More: [testing.md → limitations](docs/testing.md#known-limitations-and-trade-offs),
[security.md → gaps](docs/security.md#known-gaps-and-what-production-would-add).

## Documentation

| Document | Contents |
|---|---|
| [docs/self-test-guide.md](docs/self-test-guide.md) | step-by-step evaluation, what each step proves |
| [docs/requirements-coverage.md](docs/requirements-coverage.md) | every requirement of the brief → implementation → evidence |
| [docs/architecture.md](docs/architecture.md) | components, agents, control flow, engine internals, design decisions and trade-offs |
| [docs/testing.md](docs/testing.md) | how correctness and output quality are validated; limitations |
| [docs/security.md](docs/security.md) | threat model, controls, known gaps |
| [AGENTS.md](AGENTS.md) | instructions for coding agents that drive or develop this system |
| [standards/](standards/) | coding standards the reviewer enforces; PR and CR templates |

## Repository layout

```
src/sdlc_agent/
  orchestrator/   models (typed contracts) · dag · engine · gates · events (hash-chained log)
  agents/         role agents and prompt builder; prompts/ holds one role prompt per agent
  llm/            provider interface · mock replay + recording · Anthropic · OpenAI-compatible
  tools/          sandbox · workspace · git · test runner · static/security checks · secret scan ·
                  code index · review checks · prompt-injection scan · GitHub
  workflow.py     implement / review / change request / release state machines
  config.py       every setting as an environment variable
  observability.py, diagnostics.py   debug logs, transcripts, alerts, `sdlc debug` / `logs`
  reports.py      plan, PR, review, summary, CR and release-note renderers
  cli.py          the `sdlc` command
fixtures/         pre-written agent answers per scenario (offline replay)
examples/         requirements, the brownfield seed app, committed sample outputs
policies/         gate policies for unattended runs
standards/        coding standards, PR and CR templates
tests/            unit, end-to-end, CLI and live-provider-path tests
```
