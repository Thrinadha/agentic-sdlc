# REQ-101 - URL shortener service

## Description
Implements REQ-101

**Summary**
Build an HTTP service that creates short codes for long URLs, redirects short codes to their targets with low latency, persists links durably, and records click analytics (counts over time and referrers). The design must scale horizontally for a read-heavy workload, and the code must be structured so the cache and analytics pipeline can be swapped for distributed versions without changing the API.

**Changes**
| File | Change | Task |
|---|---|---|
| `README.md` | added | T6 README and scalability/operations guide |
| `api/openapi.yaml` | added | T1 API contract, data model and ADRs |
| `app/__init__.py` | added | T2 Core: config, persistence, short codes, cache |
| `app/analytics.py` | added | T3 Service, analytics and HTTP API |
| `app/api.py` | added | T3 Service, analytics and HTTP API |
| `app/cache.py` | added | T2 Core: config, persistence, short codes, cache |
| `app/config.py` | added | T2 Core: config, persistence, short codes, cache |
| `app/db.py` | added | T2 Core: config, persistence, short codes, cache |
| `app/main.py` | added | T3 Service, analytics and HTTP API |
| `app/models.py` | added | T2 Core: config, persistence, short codes, cache |
| `app/repository.py` | added | T3 Service, analytics and HTTP API |
| `app/schemas.py` | added | T3 Service, analytics and HTTP API |
| `app/service.py` | added | T3 Service, analytics and HTTP API |
| `app/shortcode.py` | added | T2 Core: config, persistence, short codes, cache |
| `db/schema.sql` | added | T1 API contract, data model and ADRs |
| `docs/adr/0001-short-code-generation.md` | added | T1 API contract, data model and ADRs |
| `docs/adr/0002-redirects-caching-and-analytics.md` | added | T1 API contract, data model and ADRs |
| `docs/scalability.md` | added | T6 README and scalability/operations guide |
| `pyproject.toml` | added | T2 Core: config, persistence, short codes, cache |
| `tests/conftest.py` | added | T5 Integration tests from the contract |
| `tests/helpers.py` | added | T5 Integration tests from the contract |
| `tests/integration/test_links_api.py` | added | T5 Integration tests from the contract |
| `tests/integration/test_redirect_analytics.py` | added | T5 Integration tests from the contract |
| `tests/unit/test_cache.py` | added | T4 Unit tests for codes, cache and service rules |
| `tests/unit/test_service.py` | added | T4 Unit tests for codes, cache and service rules |
| `tests/unit/test_shortcode.py` | added | T4 Unit tests for codes, cache and service rules |

**How it works**
1. API contract, data model and ADRs (architect)
2. Core: config, persistence, short codes, cache (coder)
3. README and scalability/operations guide (doc_writer)
4. Service, analytics and HTTP API (coder)
5. Integration tests from the contract (tester)
6. Unit tests for codes, cache and service rules (tester)
7. Validate: tests, lint, unsafe code, contract, secrets (validator)

**Acceptance criteria**
- AC1: POST /api/v1/links creates a short link for an http(s) URL and returns 201 with code and short_url; invalid URLs return 422.
- AC2: Optional custom alias: used as the code if valid and free; 409 if already taken; reserved words rejected with 422.
- AC3: Optional expiry: GET /{code} returns 410 after expires_at; expiry in the past is rejected at creation.
- AC4: GET /{code} returns 307 to the target URL; unknown or deleted codes return 404.
- AC5: Every redirect is recorded (timestamp, referrer, user agent) without adding latency to the redirect.
- AC6: GET /api/v1/links/{code}/stats returns total clicks, last click, daily counts and top referrers.
- AC7: GET and DELETE /api/v1/links/{code} return metadata and deactivate a link.
- AC8: Links and clicks persist in a relational database (PostgreSQL in production, SQLite locally).
- AC9: The API is described by an OpenAPI contract that the implementation matches exactly.

### Additional Notes
**Assumptions / clarifications**
- Q1: No: every create returns a new code.
- Q2: 307 with Cache-Control: no-store, so analytics stay accurate.
- Q3: Raw events with daily aggregation over the last 30 days; monthly partitions and retention at scale.
- Q4: Auth is out of scope for v1; the API is internal behind the gateway.

Ticket #: REQ-101

## How to Validate Change
1. `pip install -e .[app,dev]`
2. `python -m pytest -q` from the repository root
3. Review the API contract in `api/openapi.yaml` (if present) against the endpoints

**Tested run:** `20261025-224922-736a4c` (log: `.sdlc/runs/20261025-224922-736a4c/events.jsonl`)
| Check | Result | Summary |
|---|---|---|
| syntax | ✅ Passed | all Python files compile |
| lint | ✅ Passed | ruff: no issues |
| unsafe-code | ✅ Passed | no unsafe patterns |
| security | ✅ Passed | bandit: no medium/high issues |
| dependencies | ⏭️ Skipped | set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ✅ Passed | 6 operations match api/openapi.yaml |
| tests | ✅ Passed | 42 passed |
| secrets | ✅ Passed | no secrets found |

## Potential Impact
- Analytics query differences between SQLite (tests) and PostgreSQL (production) can hide bugs; the same ORM queries are used, and a PostgreSQL CI job is the follow-up.
- In-process cache on several instances serves a deleted link for up to CACHE_TTL_SECONDS on other instances until Redis is introduced.
- Clicks recorded in background tasks can be lost if an instance crashes mid-request; acceptable for v1, removed by the queue.
- No authentication: anyone with network access to the API can delete links (internal API behind the gateway).

## Change Size
- [ ] **Major** - breaking change to API or behaviour
- [x] **Minor** - new backward-compatible capability
- [ ] **Patch** - fix or small tweak
- [ ] Documentation change

## How Has This Been Tested
- [x] Unit tests
- [x] Integration tests
- [x] Contract check
- [x] Lint / static analysis
- [x] Secret scan

| Test | Result |
|---|---|
| syntax | ✅ Passed - all Python files compile |
| lint | ✅ Passed - ruff: no issues |
| unsafe-code | ✅ Passed - no unsafe patterns |
| security | ✅ Passed - bandit: no medium/high issues |
| dependencies | ⏭️ Skipped - set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ✅ Passed - 6 operations match api/openapi.yaml |
| tests | ✅ Passed - 42 passed |
| secrets | ✅ Passed - no secrets found |

## Checklist
- [x] Code follows the project coding standards
- [x] Tests added for new behaviour and bug fixes
- [x] Documentation updated
- [x] No secrets or credentials in the change

## Reviewer
- [ ] Reviewed and approved by a human

<!-- title: REQ-101 - URL shortener service -->
