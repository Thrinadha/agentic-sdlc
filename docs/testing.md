# Testing and validation

There are two things to validate: **the system** (does the orchestration behave correctly?) and **its
outputs** (is the generated code correct and of good quality?).

## 1. Validating the system itself

```bash
pytest tests/unit          # fast, no git or subprocess-heavy work
pytest tests/integration   # full scenario runs (minutes: real git, real generated test suites)
ruff check .
```

| Area | Tests | What they prove |
|---|---|---|
| Task graph | `test_dag.py` | cycles, unknown/self dependencies and duplicates are rejected; levels and ready set are correct |
| Engine | `test_engine.py` | independent tasks *really* run concurrently (a 3-way barrier deadlocks otherwise); a failure is routed to the owner of the faulty file, not to other tasks; a failing test routes to the module it imports; exhausted recovery escalates and a rejection fails the run; a crashing task retries, then its dependents are skipped; sandbox violations and write conflicts between parallel tasks fail the task; resume skips done tasks |
| Gates | `test_gates.py` | policy rules, default deny, blockers never auto-approved, clarify needs answers or `assume`, interactive override needs the word `override` and a reason |
| Guardrails | `test_guardrails.py` | path traversal / protected paths / oversize writes are refused; secrets are detected and never echoed; placeholders and env lookups are not flagged; unsafe code patterns |
| LLM layer | `test_llm.py` | JSON parsing with code fences inside content, repair prompt, retry with backoff, hard budget, replay fixtures per attempt, recording → replay round trip |
| Security controls | `test_security_controls.py` | generated tests cannot see API keys; outbound DNS/connections are blocked while loopback works; repo content is fenced as untrusted and cannot close the fence; injection phrases are flagged without flagging normal code; edited or deleted audit-log records are detected and resumed logs keep the chain; Bandit flags insecure code and passes clean code |
| Configuration | `test_config.py` | defaults, process env overrides, Windows user-scope fallback, invalid values name the variable, secrets never shown, flags win |
| Observability | `test_observability.py` | redaction of tokens and credential env values; git auth header masked; alert classification, severity filter and de-duplication; Slack and JSON webhook payloads received by a real local HTTP server; a broken webhook never breaks the run and never logs its URL; debug log is redacted and detached after the run; transcripts never overwritten |
| Real provider path | `tests/integration/test_live_provider_path.py` | the URL shortener runs end to end with `--provider openai` against a local OpenAI-compatible server: real HTTP requests, Bearer auth, JSON mode, response parsing, schema validation; a 429 is retried, a malformed answer gets a repair prompt, the planted bug is fixed on attempt 2, review runs; the API key appears in no log; Azure mode sends `api-version` and the `api-key` header; an unreachable endpoint fails cleanly with a diagnosis; `file://` endpoints are refused |
| CLI end to end | `tests/integration/test_cli.py` | failing run → alerts reach the webhook → `debug` names the failing test and next step → `logs`/`alerts`/`audit` → no secret in any log or transcript → `resume` retries with fresh attempts; brownfield driven by a human answering every gate; a human rejecting the plan stops the run; `config`, `doctor`, a clear error for bad settings, `alerts --test` |
| Review and reports | `test_review_and_reports.py` | commented-out code (>2 lines), duplication, leftovers, untested modules via the import graph, PR hygiene, template filling, semver bumps, ast route index |
| End to end | `tests/integration/test_scenarios.py` | each scenario reaches the expected phase; the URL shortener's planted bug is fixed on attempt 2; the brownfield fix is in place with existing tests kept; the ambiguous run stops, then resumes with answers; releases are tagged `0.1.0` and `1.3.0` |

CI (`.github/workflows/ci.yml`) runs lint and both test suites on Python 3.10–3.12, then `sdlc demo`.

## 2. Validating generated outputs

Every run's validator task executes, inside the target workspace:

| Check | Fails when |
|---|---|
| syntax | any Python file does not compile |
| lint | ruff reports issues (project config, else a safe default rule set) |
| unsafe-code | dangerous patterns (see architecture guardrails) |
| security | Bandit finds a medium/high severity issue in application code |
| dependencies | pip-audit finds a known vulnerability in a declared dependency (opt-in: `SDLC_DEPENDENCY_AUDIT=1`; on in CI) |
| contract | the operations in the OpenAPI file differ from the operations the app serves |
| tests | the generated test suite fails or has no tests |
| secrets | the secret scanner finds a credential |

Review adds checks that need judgment (per-acceptance-criterion coverage, reuse, patterns, missed
scenarios) and deterministic ones (commented-out code, duplication, leftovers, untested modules, PR
hygiene). Review fixes are applied only after Gate 4, and **the full validation suite runs again**; if
it fails, the fixes are reverted.

### Test strategy for generated code (what the tester agent is told)
- Every acceptance criterion has at least one test; every bug fix has a regression test that fails before it.
- Unit tests for pure logic with injected clocks/factories; integration tests through HTTP on a temp database.
- Deterministic: no network, no sleeps, no shared state.

### Verification steps for a reviewer of a run
1. Read `reports/summary.md`: normalized requirement, ambiguities, plan, timeline (parallel tasks and retries),
   artifacts, validation, review, gate audit log.
2. Open `reports/pr.md` and `reports/review.md`.
3. In the workspace: `pytest -q`, or `sdlc validate -w <workspace>`.
4. `events.jsonl` has every step, LLM call and gate decision with timestamps.

## Known limitations and trade-offs
- **Replay mode is deterministic by design.** The offline agents' answers are pre-written fixtures, not live
  model output. They prove the orchestration, gates and validation, and the provider code path is proven
  against a local OpenAI-compatible server, but neither proves how well a particular model performs. Live
  runs (`--provider anthropic|openai`) are supported; their output varies, and the same checks and gates apply.
  The Anthropic provider uses the official SDK and is exercised only in live runs.
- **Validation quality is bounded by the tests.** If the generated tests miss a behaviour, the checks can
  pass. The reviewer's per-criterion coverage table and the "missed scenarios" section mitigate this.
- **No load or performance testing.** Scalability claims (e.g. the URL shortener's caching and partitioning)
  are design-level and documented as such.
- **Tests run on SQLite.** Production targets PostgreSQL; a PostgreSQL CI job for generated apps is a follow-up.
- **Whole-file outputs.** Fine for small and medium files; very large brownfield files would need patch output.
- **Python-focused tooling.** The orchestrator is language-neutral, but the checks (pytest, ruff, ast index,
  FastAPI contract check) target Python projects.
- **Windows + antivirus** can make each git call take 1–2 s; a full demo then takes several minutes.
