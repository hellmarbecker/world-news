---
name: ch-query-clickstream
description: Write analytical SQL queries (funnels, conversion, retention, attribution, session shape) against the ClickHouse tables that consume this repo's click/session/user topics. Use when the user asks for a "funnel query", "conversion rate", "session analysis", "user journey", "drop-off", "retention", or any ClickHouse SQL over the world_news_* tables. Knows the schema produced by news_process.py.
---

# ch-query-clickstream

## What this skill does

Crafts ClickHouse analytical SQL over the tables produced by `news_process.py`. Knows the field shape from the producer-side schemas (`click.asvc` / `.proto`, `session.asvc` / `.proto`, `user.asvc` / `.proto`) and the state machine in `news_config.yml`.

## Schema cheat sheet

Use the column list from `ch-schema-ddl` if the user has it; otherwise infer from these reference shapes.

### `world_news_clicks` (per-event)

Primary fields:
- `timestamp Int64`, `event_time DateTime64(3)` (materialized)
- `sid Int64`, `uid String`
- `state LowCardinality(String)` — one of `home`, `content`, `clickbait`, `subscribe`, `plusContent`, `affiliateLink`, `exitSession`
- `statesVisited Array(String)` — cumulative ordered path through the session
- `contentId LowCardinality(String)`, `subContentId String`
- `campaign`, `channel`, `gender`, `age`, `country_code`, `timezone` — segmentation dims
- `isSubscriber UInt8`
- `url String`, `useragent String`, `statuscode LowCardinality(String)`

### `world_news_sessions` (one row per closed session)

Same identity + segmentation columns as clicks, plus:
- `statesVisited Array(String)` — unordered set of states touched
- Per-state flag columns: `home`, `content`, `clickbait`, `subscribe`, `plusContent`, `affiliateLink`, `exitSession` (each `UInt8` 0/1)

### `world_news_users` (slowly changing dimension)

- `uid String`, `version Int64`, `timestamp Int64` (= `updatedTime`)
- `isSubscriber UInt8`, `gender`, `age`, `place_name`, `country_code`, `timezone`, `latitude`, `longitude`

## Query patterns

### Funnel: home → content → plusContent → subscribe → checkout (exit)

The simulated funnel uses `state` transitions. `windowFunnel` is the canonical CH tool:

```sql
SELECT
    level,
    count() AS sessions_at_level
FROM (
    SELECT
        sid,
        windowFunnel(3600)(
            event_time,
            state = 'home',
            state = 'content',
            state = 'plusContent',
            state = 'subscribe'
        ) AS level
    FROM world_news_clicks
    WHERE event_time >= now() - INTERVAL 7 DAY
    GROUP BY sid
)
GROUP BY level
ORDER BY level;
```

### Conversion rate by campaign

Sessions that hit `subscribe` divided by total sessions, per campaign. Uses the `session` table because the per-state flags are pre-pivoted there:

```sql
SELECT
    campaign,
    count() AS sessions,
    sum(subscribe) AS subscribed,
    subscribed / sessions AS conversion_rate
FROM world_news_sessions
WHERE event_time >= now() - INTERVAL 7 DAY
GROUP BY campaign
ORDER BY conversion_rate DESC;
```

### Daily active subscribers (DAU)

```sql
SELECT
    toDate(event_time) AS day,
    uniqExact(uid) AS dau_subscribers
FROM world_news_clicks
WHERE isSubscriber = 1
  AND event_time >= today() - 30
GROUP BY day
ORDER BY day;
```

### Affiliate-link click-through by content category

```sql
SELECT
    contentId,
    countIf(state = 'affiliateLink') AS affiliate_clicks,
    count() AS total_clicks,
    affiliate_clicks / total_clicks AS ctr
FROM world_news_clicks
WHERE event_time >= now() - INTERVAL 1 DAY
GROUP BY contentId
ORDER BY ctr DESC;
```

### State-transition matrix (observed)

Mirrors the simulated transition probabilities so you can sanity-check the producer:

```sql
WITH transitions AS (
    SELECT
        sid,
        state AS to_state,
        lagInFrame(state) OVER (PARTITION BY sid ORDER BY event_time) AS from_state
    FROM world_news_clicks
)
SELECT
    from_state,
    to_state,
    count() AS n,
    n / sum(n) OVER (PARTITION BY from_state) AS p
FROM transitions
WHERE from_state IS NOT NULL
GROUP BY from_state, to_state
ORDER BY from_state, p DESC;
```

## ClickHouse idioms to prefer

- `uniqExact()` over `count(DISTINCT)` — same answer, faster on CH.
- `quantile()` / `quantileTDigest()` for percentiles, not `percentile_cont`.
- `arrayJoin(statesVisited)` to flatten the path array.
- `sequenceMatch('(?1)(?2)')` for ordered state sequence checks; `sequenceCount` for counts.
- `windowFunnel(window_seconds)(timestamp, cond1, cond2, ...)` for funnels.
- `retention([cond1, cond2, ...])` for cohort retention.
- For session-level aggregations from the click table, prefer `GROUP BY sid` over `argMax` joins — usually cheaper.

## Important

- The repo emits both clicks and sessions to the same topic by default (`clickTopic == sessionTopic` in `news_config.yml`). If the user's ClickHouse ingestion split them by `recordType`, queries should filter `WHERE recordType = 'click'` / `'session'` explicitly.
- The `statesVisited` semantics differ between record types: ordered list in clicks, unordered set in sessions. Be precise in queries that traverse it.
- `timestamp` is seconds since epoch on the click record (`int(time.time())`) and seconds since epoch on the session record (= `startTime`). Both fit in `Int64`; expose `event_time DateTime64(3)` via a materialized column for ergonomic time filters.

## Related

- For the table DDL, use `ch-schema-ddl`.
- For ingestion setup, use `ch-kafka-pipeline` (self-managed) or `ch-clickpipes` (CH Cloud).
