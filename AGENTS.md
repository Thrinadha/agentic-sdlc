# Instructions for coding agents

This repository is an agentic SDLC system. If you are a coding agent (Claude Code, Copilot, Cursor, ...)
asked to deliver a requirement with it, drive the CLI. Do not hand-edit generated workspaces.

## Flow
1. Write the requirement as `examples/requirements/<name>.md` with a header:
   ```yaml
   ---
   id: REQ-123          # letters-digits
   title: Short title
   scenario: <name>     # fixture folder for replay; any name for live providers
   seed: <optional path to an existing codebase to copy in (brownfield)>
   ---
   ```
2. `sdlc implement <file> --provider <anthropic|openai>`: stop and show the human each gate. Never answer a
   gate for them. Blocking ambiguities must be answered by the human.
3. `sdlc review -w <workspace>` → show the verdict and findings; the human approves fixes (Gate 4).
4. `sdlc cr -w <workspace>` → draft only; do not submit it anywhere.
5. `sdlc release -w <workspace>` only when the human asks.

## Rules
- Never use `--policy auto` on a real repository unless the human says so; it approves gates unattended.
- Never override a blocker (failing check, secret finding) yourself.
- Never put credentials in requirements, code or commands; providers read keys from environment variables.
- Do not push to `main`. GitHub integration is optional (`GITHUB_TOKEN`, `SDLC_GITHUB_REPO`).

## Developing this repository
- `pip install -e ".[app,dev]"`, then `ruff check .` and `pytest` before every change.
- Agents return typed models (`src/sdlc_agent/orchestrator/models.py`); change a contract and its tests together.
- New provider: implement `LLMProvider.complete` in `src/sdlc_agent/llm/` and register it in `registry.py`.
- New scenario for offline replay: run it live with `--record`, review the fixtures, commit them under `fixtures/`.
