# Scalability and operations

## Load profile (design target)
| | Assumption | Consequence |
|---|---|---|
| Writes | ~100 links/s peak | one PostgreSQL primary is plenty |
| Redirects | ~10k/s peak, 100:1 read/write | cache + read replicas; stateless app instances |
| Storage | 100M links × ~500 B ≈ 50 GB; clicks dominate | partition `click_events` by month, retention policy |

## Architecture as it grows
```
clients ─▶ CDN / LB ─▶ N stateless app instances ─▶ Redis (code → target)
                               │                    └▶ PostgreSQL primary (+ read replicas)
                               └─ click events ─▶ queue (Kafka/SQS) ─▶ aggregator ─▶ daily rollups
```

1. **Stateless app tier** behind a load balancer; scale on CPU / p95 latency.
2. **Cache**: swap `TTLCache` for a Redis implementation of the `Cache` protocol. Hit rate should
   exceed 90% (link popularity is heavy-tailed).
3. **Database**: unique index on `code` serves lookups; read replicas for metadata/stats; the redirect path
   reads the primary only on a cache miss.
4. **Analytics**: move `record_click` from a background task to a queue producer; an aggregator writes
   per-day rollups. Stats then read rollups instead of scanning `click_events`.
5. **ID generation** needs no coordination (random codes, ADR 0001), so it scales with the app tier.

## Failure modes
| Failure | Effect | Mitigation |
|---|---|---|
| Cache down | all lookups hit the DB | the cache is optional on the read path; alert on hit rate |
| DB primary down | creates fail; cached redirects keep working | managed failover; redirects degrade gracefully |
| Click recording fails | undercounted analytics only | logged; redirect unaffected; queue with retries later |
| Hot link (viral) | one key hammered | cache absorbs it; CDN for the 307 is not used (would break analytics) |

## What to monitor
Redirect p95/p99 latency, 5xx rate, cache hit rate, DB connections, click-recording errors,
`links` growth, `click_events` partition size.

## Not in v1 (deliberately)
Authentication and per-user link ownership, rate limiting (expected at the API gateway), malicious-URL
screening, custom domains, link editing.
