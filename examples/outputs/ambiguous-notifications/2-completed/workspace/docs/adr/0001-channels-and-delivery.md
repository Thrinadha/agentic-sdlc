# ADR 0001: Channels and delivery semantics

## Context
v1 delivers to an in-app inbox only; email follows next quarter (answer to Q2). Notifications must be
visible within 2 s p95 of the event (Q3). The order system may send the same event more than once.

## Decision
- A `Channel` protocol (`enabled_for`, `deliver`). The dispatcher fans out to enabled channels. Adding
  email means adding a channel class and a preference key, with no API change.
- Ingestion is idempotent by `event_id` (claim before delivery). If every enabled channel fails, the
  claim is released and the API returns 503, so the producer's retry is processed: at-least-once overall.
- Synchronous fan-out inside the ingest request. In-app delivery is an in-memory append, far inside the
  2 s budget.

## Alternatives considered
- Queue + workers now: needed once slow channels (email/SMS) exist; premature for an in-memory append.
- Exactly-once across channels: needs an outbox per channel; deferred with the email channel.

## Consequences
- State is in memory (single instance). `NotificationStore` is the only stateful class, so a
  database-backed store replaces it without touching the dispatcher or API.
- When email arrives, delivery moves to a queue so a slow provider cannot affect ingest latency.
