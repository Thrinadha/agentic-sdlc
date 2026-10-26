# Change Request

Change number: TBD
Window: TBD
Version: 0.1.0

## Summary
Release **0.1.0** (from no previous release): In-app order notifications with user preferences.

Customers see order updates in their in-app inbox within seconds and can switch off the ones they don't want.

## Changes
| PR | Branch | Size | Link |
|---|---|---|---|
| REQ-303 - In-app order notifications with user preferences | REQ-303-user-notifications | minor | .sdlc/prs/REQ-303-user-notifications.md |

Files: `README.md`, `api/openapi.yaml`, `docs/adr/0001-channels-and-delivery.md`, `notify/__init__.py`, `notify/api.py`, `notify/channels.py`, `notify/dispatcher.py`, `notify/main.py`, `notify/models.py`, `notify/store.py`, `pyproject.toml`, `tests/test_api.py`, `tests/test_dispatcher.py`

## Risk and Impact
- In-memory state is lost on restart and limits the service to one instance; acceptable for v1, replaced by a database-backed store.
- Synchronous fan-out is fine for in-app delivery; adding email without a queue would put provider latency on the ingest path.
- The 2 s p95 target is met by design but not load tested in this run.

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
| tests | ✅ Passed | 15 passed |
| secrets | ✅ Passed | no secrets found |

Run `20261025-225153-a73ad3`; review verdict: approve_with_comments

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
