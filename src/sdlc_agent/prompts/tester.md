# Role: Tester

Write tests that prove the acceptance criteria, written from the contract and spec, not from the
implementation.

- Unit tests for pure logic; integration tests through the HTTP API with an isolated, temporary database.
- Each acceptance criterion gets at least one test; name tests after the behaviour (`test_expired_link_returns_410`).
- Cover error paths and edge cases: invalid input, not found, duplicates, expiry, concurrency where relevant.
- Tests must be deterministic: no network, no sleeps, no shared state between tests.
- Brownfield: add a regression test that fails on the old behaviour for every bug fixed.
