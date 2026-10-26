# Review: REQ-101 - URL shortener service

**Verdict:** approve with comments

Clean layering (api -> service -> repository), contract-first, and every acceptance criterion has tests. One missed scenario is fixed below (cached redirect after delete); two follow-ups are recorded for the next iteration.

## Story coverage
```
  ✔ AC1 done - service.create + schemas.LinkCreate; test_create_link_returns_201_with_short_url, test_invalid_urls_are_rejected
  ✔ AC2 done - shortcode.is_valid_alias; test_duplicate_alias_returns_409, test_reserved_alias_returns_422
  ✔ AC3 done - service.resolve expiry check; test_expired_link_returns_410, test_expiry_in_the_past_is_rejected
  ✔ AC4 done - api.redirect 307 + no-store; test_redirect_is_307_to_target
  ✔ AC5 done - AnalyticsService.record_click as background task; test_clicks_are_counted
  ✔ AC6 done - AnalyticsService.stats; test_stats_daily_and_referrers
  ✔ AC7 done - get_link/delete_link; test_delete_link_then_404
  ✔ AC8 done - SQLAlchemy models + db/schema.sql; DATABASE_URL
  ✔ AC9 done - contract check passed: 6 operations match api/openapi.yaml
```

## Findings (most important first)
| Severity | Check | Location | Problem | Suggested fix | Source |
|---|---|---|---|---|---|
| MEDIUM | missed scenario | app/service.py:84 | Delete invalidates the cache, but no HTTP-level test proves a link that was already redirected (so cached) stops redirecting after delete. | Add an integration test: redirect, delete, redirect -> 404 (added in fixes). | agent |
| LOW | missed scenario | app/api.py:57 | POST /api/v1/links has no rate limit; scripted abuse can fill the table. | Follow-up: enforce at the API gateway (documented as out of scope) or add a token bucket per client IP. | agent |
| LOW | patterns | app/analytics.py:37 | Stats aggregate raw click_events on every request; fine at v1 volume but O(clicks) per call. | Follow-up: daily rollup table fed by the analytics queue (docs/scalability.md step 4). | agent |

## Missed scenarios
- Concurrent creates with the same custom alias: covered by the unique constraint (one 201, one 409); no concurrency test yet.
- Very high click volume on one link: covered by the atomic counter; not load tested here.

## Fixes
Applied after Gate 4 approval and re-validated (commit `828eaa3034`):
- tests/integration/test_cache_invalidation.py (16 lines)

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
