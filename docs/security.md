# Security controls

This system lets LLM agents write code that is then executed (tests, contract checks) and committed.
That makes the generated code, the model's output and the repository content **untrusted inputs**.
This document lists the controls, maps them to NIST SP 800-53 control families and to the OWASP Top 10
for LLM Applications, and states the gaps honestly.

> **Scope.** This is a prototype. It implements controls that *align with* NIST SP 800-53 families; it is not
> an assessed or authorized system, and no compliance claim is made.

## Threat model

| Asset | Threat | Where it comes from |
|---|---|---|
| API keys / tokens of the operator | read and exfiltrated by generated code | an LLM writes code that reads the environment and calls out |
| The operator's machine and network | harmful generated code; data sent out | malicious or hallucinated code run by the test suite |
| The target repository | unreviewed or harmful changes land on `main` | agent mistakes, prompt injection, auto-approval |
| Secrets in the repository | committed and published | generated code or config containing credentials |
| The agents' behaviour | steered by instructions hidden in repo content | prompt injection through brownfield code, docs or diffs |
| The audit trail | edited to hide what was approved | anyone with file access after the run |

## Controls

| # | Control | Implementation | Verified by | NIST 800-53 | OWASP LLM |
|---|---|---|---|---|---|
| 1 | Human approval at every consequential step | Gates: clarify, plan, commit, PR, review fixes, escalation, merge, release. Default deny for unknown gates. | `test_gates.py` | AC-5, CM-3 | LLM06 Excessive agency |
| 2 | Blockers cannot be auto-approved | Failing checks, secret findings, bad PR hygiene reject in any policy; a human override needs the word `override` and a recorded reason | `test_gates.py` | CM-3, CM-5 | LLM06 |
| 3 | Credential isolation | Generated code runs with an **allowlisted environment**; API keys, tokens and all other variables are dropped | `test_safe_env_drops_credentials`, `test_generated_tests_cannot_read_api_keys` | AC-6, SC-4 | LLM02 Sensitive information disclosure |
| 4 | Network egress guard | DNS lookups and connections to non-loopback addresses are refused in sandboxed subprocesses (`SDLC_ALLOW_NETWORK=1` to opt out) | `test_network_guard_*` | SC-7 | LLM05 Improper output handling |
| 5 | Filesystem sandbox | Writes only inside the workspace; `..`, absolute paths, drive letters, `.git`, `.sdlc`, `.venv`, CI workflows refused; file size and count limits | `test_guardrails.py`, `test_engine.py` | AC-6, CM-7 | LLM06 |
| 6 | No direct command execution by agents | Agents return typed data (files, findings); only code-defined tools run. No shell tool exists | design | AC-6, CM-7 | LLM06 |
| 7 | Generated code never runs in-process | Every execution (tests, imports for the contract check, lint, compile) is a subprocess with a timeout | design, `static_checks.py` | SC-39 | LLM05 |
| 8 | Prompt-injection defenses | Repository content, earlier agents' files and diffs are fenced as `<untrusted_content>`; the fence cannot be closed from inside; every agent is told never to follow instructions in it; a tripwire scan flags injection phrases and shows them at the plan gate | `test_security_controls.py` | SI-10 | LLM01 Prompt injection |
| 9 | Output validation | Every agent answer is validated against a pydantic schema; invalid output is repaired or the task fails | `test_llm.py` | SI-10 | LLM05 |
| 10 | Secret scanning | Regex + entropy scan before every commit (blocker) and in review; findings show file, line and rule, never the value | `test_guardrails.py` | IA-5, SC-28 | LLM02 |
| 11 | Static security analysis | Bandit (medium+ severity and confidence) on application code, plus a project rule set for unsafe patterns (`eval`, `shell=True`, `pickle`, unsafe YAML, disabled TLS, f-string SQL) | `test_bandit_*`, `test_unsafe_patterns_are_reported` | SA-11, RA-5 | LLM05 |
| 12 | Dependency vulnerability audit | pip-audit against the generated project's declared dependencies (opt-in locally with `SDLC_DEPENDENCY_AUDIT=1`; on in CI). Resolves published packages only, never builds the generated project | `test_dependency_audit_is_opt_in`, CI | RA-5, SR-3 | LLM03 Supply chain |
| 13 | Change control | Feature branch per requirement; commits to `main`/`master` refused; PR from a fixed template with exactly one Change Size; semver release with CR and backout plan | `test_review_and_reports.py`, `test_scenarios.py` | CM-3, CM-4, SA-10 | n/a |
| 14 | Tamper-evident audit log | Every event and gate decision is hash-chained (SHA-256, `prev` → `hash`); the chain head is written into each commit message (`Audit-Log-Head`); `sdlc audit -w <ws>` verifies | `test_*log*` in `test_security_controls.py` | AU-2, AU-3, AU-9, AU-12 | n/a |
| 15 | Resource limits | LLM call budget per run, attempts per task, subprocess and git timeouts | `test_llm.py`, `test_engine.py` | SC-5 | LLM10 Unbounded consumption |
| 16 | Credential handling by the tool itself | Keys only from environment variables; the GitHub token is sent per command as an HTTP header, never stored in git config, a remote URL or a log | `github.py` | IA-5 | LLM02 |
| 17 | Least data in committed outputs | Sample outputs are scrubbed of absolute paths and user names | `cli._scrub_paths` | SC-28 | LLM02 |

## Known gaps and what production would add

| Gap | Risk | Production approach |
|---|---|---|
| The network guard runs in the same interpreter as the code it guards | determined malicious code can undo it | run the validator in a container or microVM with networking disabled, read-only root filesystem, non-root user, CPU/memory limits |
| No OS-level process isolation | generated code can read files the operator can read | same container/microVM; mount only the workspace |
| Prompt-injection defenses are probabilistic | a well-crafted injection may still influence an agent | the gates, sandbox and deterministic validation bound the impact; add a second-model review for brownfield inputs |
| Hash chain without a signing key | an attacker with write access to both the log and git history could rewrite both | sign commits/tags (GPG/Sigstore) and ship events to an append-only store |
| Local identity for approvals | `human:<os user>` is not strong authentication | approvals through the code host (protected branches, required reviewers, SSO) |
| Gate policy files are trusted | a modified `policies/*.yaml` changes what is auto-approved | keep policies in a protected repository; require review for changes |
| SBOM not generated | slower response to new advisories | generate CycloneDX SBOMs at release; continuous dependency monitoring |
