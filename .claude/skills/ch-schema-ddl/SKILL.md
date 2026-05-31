---
name: ch-schema-ddl
description: Generate a ClickHouse CREATE TABLE (MergeTree) for one of the click/session/user record types in this repo, deriving the column list and types from the matching .asvc (Avro) or .proto (Protobuf) file. Use when the user asks for "ClickHouse DDL", "CH table", "create table for clicks/sessions/users", or "translate this schema to ClickHouse".
---

# ch-schema-ddl

## What this skill does

Translates one of the producer-side schema files in this repo into a ClickHouse `CREATE TABLE` DDL. The repo carries two parallel sources of truth:

- `click.asvc`, `session.asvc`, `user.asvc` — Avro schemas used when the producer runs with `schemaType: avro`.
- `click.proto`, `session.proto`, `user.proto` — Protobuf schemas used when the producer runs with `schemaType: protobuf`.

Either one can be the input. Prefer `.proto` if both exist and match — protobuf carries the explicit per-state flag fields that Avro silently drops.

## When invoked

1. Ask which record type — `click`, `session`, or `user` — unless the user already said.
2. Ask which source schema to read from — `.proto` (recommended) or `.asvc`. If they don't care, use `.proto`.
3. Read the schema file from the repo root.
4. Emit a `CREATE TABLE` statement using the type mapping below.
5. Pick a sensible `ORDER BY` and `PARTITION BY` (see "Defaults" below). State the choice and offer alternatives.

## Type mapping

| Avro             | Protobuf             | ClickHouse              | Notes |
|------------------|----------------------|--------------------------|-------|
| `long`           | `int64`              | `Int64`                  | For `timestamp`, also offer `DateTime64(3)` via `toDateTime(timestamp)` materialized column |
| `int`            | `int32`              | `Int32` or `UInt8`       | Use `UInt8` for the per-state 0/1 flag fields on `session` and for `isSubscriber` |
| `string`         | `string`             | `String`                 | Wrap in `LowCardinality(String)` for fields with bounded cardinality — see below |
| `double`         | `double`             | `Float64`                | |
| `array<string>`  | `repeated string`    | `Array(String)`          | `statesVisited` |
| `boolean`        | `bool`               | `Bool`                   | |

### LowCardinality candidates

These fields have small, stable value sets — wrap them as `LowCardinality(String)`:

- `recordType`, `statuscode`, `state`, `campaign`, `channel`, `contentId`, `gender`, `age`, `country_code`, `timezone`

Leave as plain `String`:

- `url`, `useragent`, `subContentId`, `place_name`, `uid` (high cardinality)

## Defaults

| Record   | ORDER BY                              | PARTITION BY                          |
|----------|---------------------------------------|---------------------------------------|
| click    | `(toDate(toDateTime(timestamp)), sid, timestamp)` | `toYYYYMM(toDateTime(timestamp))` |
| session  | `(toDate(toDateTime(timestamp)), sid)`            | `toYYYYMM(toDateTime(timestamp))` |
| user     | `(uid, version)`                                  | `toYYYYMM(toDateTime(timestamp))` |

Always include `timestamp Int64` as a column even when the ORDER BY uses `toDateTime(timestamp)` — keep the raw value, add a materialized `event_time DateTime64(3) MATERIALIZED toDateTime64(timestamp, 3)` if helpful.

## Output template

```sql
CREATE TABLE world_news_clicks
(
    timestamp       Int64,
    event_time      DateTime64(3) MATERIALIZED toDateTime64(timestamp, 3),
    recordType      LowCardinality(String),
    url             String,
    -- ...one row per field, snake_case or camelCase per the schema's field names...
    statesVisited   Array(String),
    sid             Int64,
    uid             String,
    -- ...etc
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (toDate(event_time), sid, timestamp);
```

## Important

- Field names: emit them exactly as they appear in the source schema (mix of camelCase and snake_case is intentional in this repo — `recordType`, `place_name`, etc).
- For `session`, include all seven per-state flag columns (`home`, `content`, `clickbait`, `subscribe`, `plusContent`, `affiliateLink`, `exitSession`) as `UInt8`. The Avro schema omits these but the Protobuf schema declares them — that's why `.proto` is the recommended source.
- Do not invent fields the source doesn't have, and do not drop fields the source does have.

## Related

- After generating DDL, the user often wants the matching Kafka ingestion pipeline — point them at the `ch-kafka-pipeline` skill.
- For Confluent Cloud → ClickHouse Cloud, suggest `ch-clickpipes` instead of self-managed Kafka engine tables.
