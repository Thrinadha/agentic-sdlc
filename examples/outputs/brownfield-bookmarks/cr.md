# Change Request

Change number: TBD
Window: TBD
Version: 1.3.0

## Summary
Release **1.3.0** (from 1.2.0): Fix bookmark paging and add tag filter.

Users can page through all of their bookmarks and narrow the list to one tag.

## Changes
| PR | Branch | Size | Link |
|---|---|---|---|
| REQ-202 - Fix bookmark paging and add tag filter | REQ-202-fix-bookmark-paging-and-add-tag-filter | minor | .sdlc/prs/REQ-202-fix-bookmark-paging-and-add-tag-filter.md |

Files: `bookmarks/api.py`, `bookmarks/store.py`, `docs/api.md`, `tests/test_pagination.py`, `tests/test_tag_filter.py`

## Risk and Impact
- Clients that compensated for the missing item per page will now see one more item per page (correct behaviour, noted in docs changelog).
- Linear tag filtering over the in-memory store; acceptable at current size, needs an index with a database.

**Risk level:** Medium

## Test Evidence
| Check | Result | Summary |
|---|---|---|
| syntax | ✅ Passed | all Python files compile |
| lint | ✅ Passed | ruff: no issues |
| unsafe-code | ✅ Passed | no unsafe patterns |
| security | ✅ Passed | bandit: no medium/high issues |
| dependencies | ⏭️ Skipped | set SDLC_DEPENDENCY_AUDIT=1 to audit |
| contract | ⏭️ Skipped | no API contract declared |
| tests | ✅ Passed | 17 passed |
| secrets | ✅ Passed | no secrets found |

Run `20261025-225054-c09277`; review verdict: approve_with_comments

## Implementation Plan
1. Merge the approved PR(s) to `main`
2. Tag `1.3.0` and build the release artifact from the tag
3. Deploy to staging; run the smoke tests (health check + create/resolve/stats)
4. Deploy to production behind the load balancer (rolling, one instance at a time)
5. Monitor error rate, p95 latency and 5xx for 30 minutes

## Backout Plan
Redeploy the previous tag `1.2.0`. Schema changes are additive, so the previous version runs against the new schema. If data must be reverted, restore from the pre-deploy backup.

## Approvals
- [ ] Engineering lead
- [ ] Change advisory board
