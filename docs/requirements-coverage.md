# Assignment requirements coverage

Every requirement of the assignment, where it is implemented, and the evidence (a test or an output you
can open). Sample outputs are in [`examples/outputs/`](../examples/outputs/).

## Scope
| Requirement | Covered by | Evidence |
|---|---|---|
| Greenfield: new feature/system | URL shortener, notification service | `examples/outputs/greenfield-url-shortener/`, `test_greenfield_url_shortener_full_lifecycle` |
| Brownfield: enhancement, refactoring, bug fix | bookmarks API: paging bug fix + tag filter on an existing codebase | `examples/outputs/brownfield-bookmarks/`, `test_brownfield_fix_and_enhancement` |
| Test and documentation improvements | brownfield adds regression tests for an untested path and updates `docs/api.md`; requirement kinds `tests` / `docs` are supported | brownfield `impact.md` (test gaps), `test_pagination.py` |
| Well-defined and ambiguous requirements | ambiguity detection with blocking/minor severity | `examples/outputs/ambiguous-notifications/`, `test_ambiguous_requirement_stops_then_resumes_with_answers` |

## Core requirements
| # | Requirement | Implementation | Evidence |
|---|---|---|---|
| 1 | Interpret intent, identify ambiguities | `RequirementAnalyst` → `RequirementSpec` (intent, problem statement, testable acceptance criteria, NFRs, out of scope, ambiguities with severity, default and why it matters) | summary §1–2 of each scenario |
| 1 | Normalize into an engineering problem | same; refined after clarification (`requirement_analyst.refine`) | ambiguous `2-completed/summary.md` |
| 2 | Structured, actionable tasks | `Planner` → `Plan` (task id, owner agent, description, acceptance, outputs) | `plan.md` |
| 2 | Dependencies and execution sequence | `TaskGraph`: validated DAG, topological levels, mermaid graph; plan checks (one validator, no parallel write of the same file) | `test_dag.py`, `plan.md` |
| 3 | Impacted services, modules, APIs, data flows | `code_index` (ast: modules, imports, routes, classes) + `CodebaseAnalyst` → `ImpactAnalysis` with risk per file | brownfield `impact.md`, summary §3 |
| 3 | System-level understanding | architecture description, data flows, test gaps, regression risks | brownfield summary §3 |
| 4 | Coordinated multi-step workflow | phase state machine (`workflow.py`) + DAG engine (`engine.py`) | `events.jsonl` of any run |
| 4 | Sequencing and dependency management | ready-set scheduling; dependents of failed tasks skipped | `test_a_crashing_task_is_retried_then_its_dependents_are_skipped` |
| 4 | **Cross-step coordination, not just sequential** | real parallelism (thread pool), contract-first shared artifacts, file ownership, failure routing to the owning task | `test_independent_tasks_really_run_in_parallel`, `test_validation_failure_is_routed_to_the_owner_of_the_faulty_file`, summary §5 "ran in parallel with" |
| 4 | Error handling and recovery | retries with feedback, transient backoff, JSON repair, escalation gate, checkpoint + resume (also after failure) | `test_engine.py`, `test_llm.py`, `test_failure_is_alerted_debuggable_and_resumable` |
| 5 | Production-quality code | URL shortener: layered FastAPI + SQLAlchemy, cache protocol, async analytics, input validation, config from env | `examples/outputs/greenfield-url-shortener/workspace/app/` |
| 5 | API contracts / schemas | OpenAPI 3.1 + SQL schema; contract check holds the app to the contract | `api/openapi.yaml`, `db/schema.sql`, `contract: passed` |
| 5 | Unit and integration tests | generated `tests/unit` and `tests/integration` (44 tests for the URL shortener) | `workspace/tests/` |
| 5 | Supporting documentation | README, ADRs, scalability/operations guide, API docs | `workspace/README.md`, `docs/adr/`, `docs/scalability.md` |
| 6 | Risks, trade-offs, failure scenarios | plan risks/trade-offs, ADR alternatives, scalability failure-modes table, review missed scenarios | `plan.md`, `docs/adr/*`, `review.md` |
| 6 | Validation approach | 8 deterministic checks per run; review re-validates fixes; test strategy given to the tester | [testing.md](testing.md) |
| 6 | Guardrails | sandbox, credential isolation, network guard, secret scan, Bandit, pip-audit, budgets, prompt-injection fencing, protected branches | [security.md](security.md), `test_guardrails.py`, `test_security_controls.py` |
| 7 | Agents execute independently across steps | 8 agent roles; engine runs them without intervention between gates | any run log |
| 7 | Humans provide oversight, validation, approval | gates: clarify, plan, commit, PR, review fixes, escalation, merge, release; blockers never auto-approved; audit log | `test_gates.py`, `test_brownfield_lifecycle_with_a_human_at_every_gate`, summary §10 |
| 8 | Implementation plan and rationale | summary §4 | `summary.md` |
| 8 | Generated artifacts | summary §6 | `summary.md` |
| 8 | Risks, trade-offs, validation approach | summary §7, §9 | `summary.md` |
| 8 | Assumptions and limitations | summary §2, §11 | `summary.md` |

## Deliverables
| Deliverable | Where |
|---|---|
| 1. Working prototype, accepts a requirement, structured output, URL shortener included | `sdlc implement <file>`; `sdlc demo` |
| 2. Architecture overview: components, execution model, control flow, decisions | [architecture.md](architecture.md) |
| 3. Example scenarios: greenfield, brownfield, ambiguous (each with decomposition, orchestration, validation) | [`examples/outputs/`](../examples/outputs/) + a failure scenario |
| 4. Setup instructions | [README](../README.md#quick-start-offline-no-api-key), [self-test-guide.md](self-test-guide.md) |
| 5. Testing approach, limitations, trade-offs | [testing.md](testing.md) |

## Mandatory use case: URL shortener
| Must | Evidence |
|---|---|
| Analyze and decompose | 9 acceptance criteria, 4 ambiguities with defaults, 7-task DAG in 5 levels |
| Design the architecture | OpenAPI contract, schema, ADR 0001 (code generation), ADR 0002 (redirects/cache/analytics), `docs/scalability.md` (load profile, growth path, failure modes, monitoring) |
| Generate code, APIs, tests | `app/` (10 modules), 6 endpoints, 44 passing tests (unit + integration) |
| Trade-offs and validation strategy | plan trade-offs, ADR alternatives tables, validation table, review with per-criterion coverage |

## Beyond the brief
Alerts (file + Slack/Teams/Mattermost webhook), `sdlc debug` / `logs` / `audit` / `doctor` / `config`,
redacted debug logs and LLM transcripts, tamper-evident audit log, any-provider support (Claude, OpenAI,
Azure OpenAI, Ollama), offline replay with recording, CI with secrets/variables and a manual live-model job.
