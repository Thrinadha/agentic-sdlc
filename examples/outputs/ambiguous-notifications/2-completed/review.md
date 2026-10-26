# Review: REQ-303 - In-app order notifications with user preferences

**Verdict:** approve with comments

The clarified scope is implemented as specified; the channel abstraction keeps the API stable for email. One acceptance criterion (AC7, latency) is met by design but has no automated evidence, so it is marked partial.

## Story coverage
```
  ✔ AC1 done - test_event_lands_in_inbox, test_invalid_events_are_rejected
  ✔ AC2 done - test_duplicate_event_is_ignored, test_event_is_delivered_once
  ✔ AC3 done - test_inbox_is_newest_first_and_per_user, test_mark_read_and_unread_filter
  ✔ AC4 done - test_mark_read_unknown_or_other_users_notification_is_404
  ✔ AC5 done - test_preferences_default_on_and_can_be_changed, test_disabled_event_type_is_not_delivered
  ✔ AC6 done - test_one_failing_channel_does_not_block_others, test_total_failure_releases_event_for_retry
  ~ AC7 partial - synchronous in-memory delivery; no latency measurement
```

## Findings (most important first)
| Severity | Check | Location | Problem | Suggested fix | Source |
|---|---|---|---|---|---|
| MEDIUM | story coverage | notify/dispatcher.py:18 | AC7 (2 s p95) has no automated evidence. | Add a load test (e.g. locust/k6) in the staging pipeline that asserts p95 ingest-to-inbox < 2 s; tracked as a follow-up. | agent |
| LOW | missed scenario | notify/store.py:22 | Claimed event ids grow without bound in memory. | Keep claims for a dedupe window (e.g. 24 h) when moving to a persistent store. | agent |

## Missed scenarios
- Inbox growth per user is unbounded; pagination will be needed for heavy users.

## Fixes
No fixes proposed.
