# ADR 0002: Redirects, caching and analytics

## Context
Redirects are the hot path (reads outnumber writes by roughly 100:1). Analytics must not slow
redirects down, and counts should be accurate.

## Decision
1. **307 Temporary Redirect with `Cache-Control: private, no-store`.** A 301 would be cached by
   browsers forever, so later clicks would never reach us (lost analytics, and a deleted or expired link
   would keep working).
2. **Read-through cache** in front of the `code → target` lookup, behind a `Cache` protocol: in-process
   LRU+TTL now, Redis when there are several instances. Delete invalidates the entry; TTL (300 s) bounds
   staleness for anything else.
3. **Clicks are recorded after the response is sent** (background task): a `click_events` row plus an
   atomic `click_count = click_count + 1`. A failure to record is logged and never fails the redirect.

## Alternatives considered
- Synchronous click insert: simpler, but adds a write to every redirect's latency.
- Message queue (Kafka/SQS) + stream aggregation: the right next step at high volume (see
  `docs/scalability.md`); too much infrastructure for the first version.

## Consequences
- With an in-process cache on several instances, a delete is immediate on the instance that served it
  and at most `CACHE_TTL_SECONDS` stale on others, until Redis replaces it.
- Background tasks run in the web process: clicks being recorded when an instance crashes can be lost.
  Acceptable for v1; the queue removes this.
