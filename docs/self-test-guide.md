# Self-test guide

A walk-through you (or an evaluator) can follow from a fresh clone. Each step says what to run, what you
should see, and which part of the assignment it proves. Windows PowerShell commands are shown; on
macOS/Linux use `source .venv/bin/activate` and the same `sdlc` commands.

Time: ~10 minutes for steps 1–6 (git is slow on some Windows machines; the full demo can take longer).

## 0. Setup
```powershell
git clone <repo-url> agentic-sdlc; cd agentic-sdlc
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[app,dev]"
sdlc doctor        # every line [OK] (INFO lines are optional features)  →  "ready"
sdlc config        # every setting, its value and source (secrets show only set / not set)
```

## 1. Automated tests (proves: correctness of the system itself)
```powershell
pytest tests/unit          # ~111 tests, < 1 minute
pytest tests/integration   # full scenarios + CLI end to end, several minutes
ruff check .
```
All green. What each suite proves: [testing.md](testing.md).

## 2. The mandatory use case, with you as the approver (proves: decomposition, orchestration, controlled autonomy, outputs)
```powershell
sdlc implement examples/requirements/url-shortener.md -w ws\url
```
You will be asked at each gate. Answer `y`:

| You see | What to check |
|---|---|
| `analysed requirement ... 9 acceptance criteria, 4 ambiguities` | requirement understanding; minor ambiguities resolved with documented defaults |
| **Gate A** with a task table, execution levels and a mermaid graph | task decomposition, dependencies, parallel levels (`T2, T6` and `T3, T5` run together) |
| `T3 ... (attempt 2)` after `tests: failed - 1 failed` and `routing failure to T3` | error handling and recovery: a real test failure is routed to the task that owns the faulty code (not the tester), fixed, re-validated |
| `security: passed`, `contract: passed - 6 operations match`, `tests: passed - 42 passed` | validation and guardrails |
| **Gate 1** with changed files, **secret scan result**, branch, commit message | human approval before anything is committed |
| **Gate 3** with the filled PR template | PR with real test results and exactly one Change Size |

Then:
```powershell
sdlc review  -w ws\url     # Gate 4: approve the proposed fix → re-validated, 44 tests
sdlc cr      -w ws\url     # change request draft
sdlc release -w ws\url     # merge gate + release gate → tag 0.1.0
git -C ws\url log --oneline --graph --all
```
Open `ws\url\.sdlc\runs\<run>\reports\summary.md`: the engineering summary (plan and rationale,
artifacts, risks and trade-offs, validation, assumptions and limitations, gate audit log).
Run the generated service: `cd ws\url; uvicorn app.main:create_app --factory` and try the README's curl calls.

**Try saying `n`** at Gate A in a new run: the run stops in phase `rejected` and nothing is written.

## 3. Brownfield (proves: codebase reasoning)
```powershell
sdlc implement examples/requirements/brownfield-bookmarks.md -w ws\bm --policy auto
```
Check `reports/impact.md` and the summary's *Codebase impact* section: the analyst names
`bookmarks/store.py` and the off-by-one root cause, the impacted API/test/doc files and the data flow.
Four tasks run in parallel. Existing tests are kept and still pass. `sdlc release -w ws\bm --policy auto`
tags `1.3.0` on top of the seed's `1.2.0`.

## 4. Ambiguous requirement (proves: ambiguity handling and human oversight)
```powershell
sdlc implement examples/requirements/ambiguous-notifications.md -w ws\amb --policy auto
```
Stops in phase `needs_clarification` before planning, writes `reports/clarification-request.md`, and
raises a *Human input needed* alert. Then answer interactively:
```powershell
sdlc resume -w ws\amb                  # type your answers, or Enter to accept each default
# or unattended:  sdlc resume -w ws\amb --policy auto --answers examples\requirements\ambiguous-notifications.answers.yaml
```

## 5. Failure, alerts, logs and debugging (proves: error handling, observability)
Optional webhook to see alerts arrive in Slack/Teams/Mattermost:
`.\scripts\setup-env.ps1 -Name SDLC_ALERT_WEBHOOK`, then `sdlc alerts --test`.
```powershell
sdlc implement examples/requirements/failing-calculator.md -w ws\fail --policy auto --debug
sdlc debug  -w ws\fail                         # what failed, why, the failing test output, the next step
sdlc logs   -w ws\fail --type task.retry,task.failed,gate
sdlc logs   -w ws\fail --task T1
sdlc logs   -w ws\fail --debug-log --grep pytest   # commands, exit codes, timings
sdlc alerts -w ws\fail                         # [critical] Run failed, [error] Escalation rejected ...
dir ws\fail\.sdlc\runs\*\llm                   # redacted LLM prompts/answers (because of --debug)
sdlc resume -w ws\fail                         # interactive: approve the escalation and type guidance
```
The coder's pre-written answer never fixes the bug, so recovery is exhausted after 3 attempts and the run
escalates. `-v` on any command prints the debug log to the console.

## 6. Security controls (proves: guardrails, risk control)
```powershell
sdlc audit -w ws\url                           # tamper-evident logs: "chain intact"
pytest tests/unit/test_security_controls.py -v # keys hidden from generated code, network blocked, injection, audit
```
Tamper test: open `ws\url\.sdlc\runs\<run>\events.jsonl` in an editor, change `APPROVED` to `REJECTED` on
any gate line, save, and run `sdlc audit -w ws\url` again. It reports `FAIL ... line N: content does not
match its hash`. The chain head is also in the commit message (`git -C ws\url log -1`, `Audit-Log-Head`).

Credential isolation, by hand:
```powershell
$env:ANTHROPIC_API_KEY = "placeholder-not-a-real-key"
sdlc validate -w ws\url     # generated tests run without it: the sandbox drops credentials
Remove-Item Env:ANTHROPIC_API_KEY
```
Read [security.md](security.md): threat model, 17 controls mapped to NIST 800-53 / OWASP LLM Top 10,
and the honest list of gaps.

## 7. Everything at once
```powershell
sdlc demo        # all four scenarios offline, outputs in examples/outputs/
```
Expected final lines:
```
greenfield-url-shortener        reviewed              as expected
brownfield-bookmarks            reviewed              as expected
ambiguous-notifications (no answers)  needs_clarification  as expected
ambiguous-notifications         reviewed              as expected
failure-recovery-exhausted      failed                as expected
```

## 8. With a real model (optional)
```powershell
.\scripts\setup-env.ps1 -Name SDLC_PROVIDER,ANTHROPIC_API_KEY     # or OPENAI_API_KEY + SDLC_MODEL
sdlc doctor
sdlc implement examples/requirements/url-shortener.md -w ws\live --debug
```
Output varies by model; every gate, check and guardrail is the same. Add `--record` to save the answers as
fixtures for offline replay. Write your own requirement as a Markdown file with the header used in
`examples/requirements/`.

## Questions an interviewer may ask, and where the answer is
| Question | Where |
|---|---|
| Why a planner-built DAG instead of a free agent loop? | [architecture.md → design decisions](architecture.md#key-design-decisions-and-trade-offs) |
| How do you know the right task gets the failure? | `Engine.route_failure`, `test_validation_failure_is_routed_to_the_owner_of_the_faulty_file` |
| What stops an agent from pushing bad code? | gates + blockers never auto-approved, [security.md](security.md) |
| What if the LLM returns garbage? | schema validation + repair prompt + retries (`test_llm.py`) |
| Is the demo faked? | in offline mode the agents' answers are pre-written fixtures; git, tests, checks, gates and routing run for real on them. The real provider path is tested end to end against a local OpenAI-compatible server (`test_live_provider_path.py`), and a live run with a real model works the same way |
| What would you do next for production? | [security.md → known gaps](security.md#known-gaps-and-what-production-would-add), [testing.md → limitations](testing.md#known-limitations-and-trade-offs) |
