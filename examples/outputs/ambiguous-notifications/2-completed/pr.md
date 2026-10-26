# REQ-303 - In-app order notifications with user preferences

## Description
Implements REQ-303

**Summary**
Build a notification service that ingests order lifecycle events (order_shipped, order_delivered, order_cancelled) from the order system, idempotently by event_id, and delivers a notification to the user's in-app inbox unless the user has opted out of that event type. Users list their notifications (optionally unread only), mark them read, and manage per-channel, per-event-type preferences. Delivery goes through a channel abstraction so email can be added next quarter without API changes.

**Changes**
| File | Change | Task |
|---|---|---|
| `README.md` | added | T6 README |
| `api/openapi.yaml` | added | T1 API contract and channel/delivery ADR |
| `docs/adr/0001-channels-and-delivery.md` | added | T1 API contract and channel/delivery ADR |
| `notify/__init__.py` | added | T2 Domain, store, channels and dispatcher |
| `notify/api.py` | added | T3 HTTP API and app factory |
| `notify/channels.py` | added | T2 Domain, store, channels and dispatcher |
| `notify/dispatcher.py` | added | T2 Domain, store, channels and dispatcher |
| `notify/main.py` | added | T3 HTTP API and app factory |
| `notify/models.py` | added | T2 Domain, store, channels and dispatcher |
| `notify/store.py` | added | T2 Domain, store, channels and dispatcher |
| `pyproject.toml` | added | T2 Domain, store, channels and dispatcher |
| `tests/test_api.py` | added | T5 Integration tests from the contract |
| `tests/test_dispatcher.py` | added | T4 Dispatcher unit tests |

**How it works**
1. API contract and channel/delivery ADR (architect)
2. Domain, store, channels and dispatcher (coder)
3. Integration tests from the contract (tester)
4. README (doc_writer)
5. HTTP API and app factory (coder)
6. Dispatcher unit tests (tester)
7. Validate (validator)

**Acceptance criteria**
- AC1: POST /api/v1/events accepts order_shipped, order_delivered and order_cancelled events and returns 202 with the channels delivered to; other types return 422.
- AC2: The same event_id is processed at most once per successful delivery (duplicates return duplicate=true and create nothing).
- AC3: GET /api/v1/users/{user_id}/notifications lists the user's notifications newest first, with ?unread=true filtering; users never see others' notifications.
- AC4: POST /api/v1/users/{user_id}/notifications/{id}/read marks one read; 404 for unknown ids or another user's notification.
- AC5: GET/PUT /api/v1/users/{user_id}/preferences read and change per-event-type opt-ins for in_app (default all on; partial updates keep other values); opted-out events are not delivered.
- AC6: A failing channel does not block other channels; if all fail the API returns 503 and the event can be retried.
- AC7: A notification is in the inbox within 2 s p95 of ingestion (synchronous in-app delivery).

### Additional Notes
**Assumptions / clarifications**
- Q1 answered: order_shipped, order_delivered, order_cancelled from the order system
- Q2 answered: in-app only for v1; email next quarter without API change
- Q3 answered: visible within 2 s p95
- Q4 default accepted: per channel, per event type, all on by default
- Q5 default accepted: idempotent by event_id
- Q1: Order lifecycle events from the order system: order_shipped, order_delivered, order_cancelled.
- Q2: In-app inbox only for v1. Email comes next quarter, so adding a channel must not change the API.
- Q3: A notification must be visible in the user's inbox within 2 seconds of the event (p95).

Ticket #: REQ-303

## How to Validate Change
1. `pip install -e .[app,dev]`
2. `python -m pytest -q` from the repository root
3. Review the API contract in `api/openapi.yaml` (if present) against the endpoints

**Tested run:** `20261025-225153-a73ad3` (log: `.sdlc/runs/20261025-225153-a73ad3/events.jsonl`)
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

## Potential Impact
- In-memory state is lost on restart and limits the service to one instance; acceptable for v1, replaced by a database-backed store.
- Synchronous fan-out is fine for in-app delivery; adding email without a queue would put provider latency on the ingest path.
- The 2 s p95 target is met by design but not load tested in this run.

## Change Size
- [ ] **Major** - breaking change to API or behaviour
- [x] **Minor** - new backward-compatible capability
- [ ] **Patch** - fix or small tweak
- [ ] Documentation change

## How Has This Been Tested
- [x] Unit tests
- [ ] Integration tests
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
| tests | ✅ Passed - 15 passed |
| secrets | ✅ Passed - no secrets found |

## Checklist
- [x] Code follows the project coding standards
- [x] Tests added for new behaviour and bug fixes
- [x] Documentation updated
- [x] No secrets or credentials in the change

## Reviewer
- [ ] Reviewed and approved by a human

<!-- title: REQ-303 - In-app order notifications with user preferences -->
