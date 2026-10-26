-- URL shortener schema (PostgreSQL). Applied before deploy; the app only creates tables in dev/test.

CREATE TABLE IF NOT EXISTS links (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(32)   NOT NULL UNIQUE,          -- unique index serves the redirect lookup
    target_url   VARCHAR(2048) NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ,
    is_active    BOOLEAN       NOT NULL DEFAULT TRUE,
    click_count  INTEGER       NOT NULL DEFAULT 0       -- denormalized counter for O(1) totals
);

CREATE TABLE IF NOT EXISTS click_events (
    id           BIGSERIAL PRIMARY KEY,
    link_id      BIGINT        NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    occurred_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    referrer     VARCHAR(512),
    user_agent   VARCHAR(512)
);

-- Stats queries filter by link and time range.
CREATE INDEX IF NOT EXISTS ix_click_events_link_time ON click_events (link_id, occurred_at);

-- At scale, click_events is partitioned by month (PARTITION BY RANGE (occurred_at)) and old
-- partitions are dropped after the retention period. See docs/scalability.md.
