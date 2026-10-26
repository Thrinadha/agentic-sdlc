# Change Request

Change number: TBD
Window: TBD
Version: 0.1.0

## Summary
Release **0.1.0** (from no previous release): URL shortener service.

Let users turn long URLs into short links that redirect reliably and show how often and from where they are used.

## Changes
| PR | Branch | Size | Link |
|---|---|---|---|
| REQ-101 - URL shortener service | REQ-101-url-shortener-service | minor | .sdlc/prs/REQ-101-url-shortener-service.md |

Files: `README.md`, `api/openapi.yaml`, `app/__init__.py`, `app/analytics.py`, `app/api.py`, `app/cache.py`, `app/config.py`, `app/db.py`, `app/main.py`, `app/models.py`, `app/repository.py`, `app/schemas.py`, `app/service.py`, `app/shortcode.py`, `db/schema.sql`, `docs/adr/0001-short-code-generation.md`, `docs/adr/0002-redirects-caching-and-analytics.md`, `docs/scalability.md`, `pyproject.toml`, `tests/conftest.py`, `tests/helpers.py`, `tests/integration/test_cache_invalidation.py`, `tests/integration/test_links_api.py`, `tests/integration/test_redirect_analytics.py`, `tests/unit/test_cache.py`, `tests/unit/test_service.py`, `tests/unit/test_shortcode.py`

## Risk and Impact
- Analytics query differences between SQLite (tests) and PostgreSQL (production) can hide bugs; the same ORM queries are used, and a PostgreSQL CI job is the follow-up.
- In-process cache on several instances serves a deleted link for up to CACHE_TTL_SECONDS on other instances until Redis is introduced.
- Clicks recorded in background tasks can be lost if an instance crashes mid-request; acceptable for v1, removed by the queue.
- No authentication: anyone with network access to the API can delete links (internal API behind the gateway).

**Risk level:** Medium

## Test Evidence
| Check | Result | Summary |
|---|---|---|
| syntax | ✅ Passed | all Python files compile |
| lint | ✅ Passed | ruff: no issues |
| unsafe-code | ✅ Passed | no unsafe patterns |
| security | ✅ Passed | bandit: no medium/high issues |
| dependencies | ⏭️ Skipped | set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ✅ Passed | 6 operations match api/openapi.yaml |
| tests | ✅ Passed | 44 passed |
| secrets | ✅ Passed | no secrets found |

Run `20261025-224922-736a4c`; review verdict: approve_with_comments

## Implementation Plan
1. Merge the approved PR(s) to `main`
2. Tag `0.1.0` and build the release artifact from the tag
3. Deploy to staging; run the smoke tests (health check + create/resolve/stats)
4. Deploy to production behind the load balancer (rolling, one instance at a time)
5. Monitor error rate, p95 latency and 5xx for 30 minutes

## Backout Plan
Redeploy the previous tag `n/a`. Schema changes are additive, so the previous version runs against the new schema. If data must be reverted, restore from the pre-deploy backup.

## Approvals
- [ ] Engineering lead
- [ ] Change advisory board
