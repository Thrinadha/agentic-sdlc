# Coding standards

The Planner, the Coder and the Reviewer all read this file. The Reviewer checks every PR against it.

## Structure
- Layered: `api` (HTTP, validation, status codes) → `service` (business rules) → `repository` (persistence).
  Route handlers contain no business logic and no SQL.
- One responsibility per module. Shared logic lives in one place and is imported, never copied.
- An app factory (`create_app()`) builds the application; no work at import time.

## Code
- Python ≥ 3.10, type hints on public functions, docstrings on modules and public functions.
- No commented-out code, no leftover `TODO`/`FIXME`, no `print` debugging (use `logging`).
- Errors: domain exceptions in the service layer, mapped to HTTP status codes in one place in the API layer.
- Input is validated at the boundary (pydantic models). Never trust client input in SQL. Use the ORM or
  bound parameters only.

## Configuration and secrets
- All configuration comes from environment variables with safe defaults, read in one `config` module.
- No credentials, tokens or real hostnames in code, tests or docs. The secret scan blocks the commit.

## API
- The OpenAPI contract in `api/openapi.yaml` is the source of truth; the contract check fails if the app
  and the contract disagree.
- Versioned paths (`/api/v1/...`). Errors return `{"detail": "..."}` with the correct status code.
- Changes are backward compatible unless the PR is marked **Major**.

## Tests
- Every acceptance criterion has a test. Every bug fix has a regression test that fails before the fix.
- Unit tests for pure logic; integration tests through the HTTP API against a temporary database.
- Deterministic: no network, no sleeps, no shared state between tests.

## Documentation
- README: run, configure, test. Architecture decisions as ADRs in `docs/adr/`.
- Docs change in the same PR as the behaviour they describe.

## Pull requests
- Title `<REQ-ID> - <description>`; body is `standards/pr_template.md` filled in.
- Exactly one Change Size box ticked: Major (breaking), Minor (new backward-compatible capability), Patch (fix).
