---
name: ch-clickpipes
description: Generate a ClickPipes (Confluent Cloud → ClickHouse Cloud) configuration for ingesting one of this repo's topics, including the broker + SASL credential template and the column mapping derived from the producer schema. Use when the user asks for "ClickPipes config", "Confluent → CH Cloud", "managed ingestion", or is running ClickHouse Cloud and wants to consume from this generator.
---

# ch-clickpipes

## What this skill does

Produces:

1. A **ClickPipes source connection** description (the Kafka broker / auth / topic block).
2. A **destination MergeTree DDL** matching the source schema (delegate to `ch-schema-ddl`).
3. A **column mapping** — explicit even when names are identical, because ClickPipes UI requires it.
4. Notes on format selection (JSONEachRow vs AvroConfluent vs Protobuf).

This is the managed-ingestion alternative to `ch-kafka-pipeline`. Use it when the target is **ClickHouse Cloud** (no access to server configs / Kafka engine tables) or when the user explicitly says "ClickPipes."

## When invoked

1. Ask which record type — `click`, `session`, or `user`.
2. Ask which schema format the producer is using:
   - `json` (no SR) → ClickPipes format = **JSONEachRow**
   - `json` (with SR) → still JSONEachRow on the wire; SR is producer-side only
   - `avro` (SR) → **AvroConfluent**, requires SR URL + credentials in ClickPipes
   - `protobuf` (SR) → **Protobuf** (some ClickPipes versions; otherwise convert producer to JSON for this consumer)
3. Pull connection details from `news_secret.yml` (template at `news_secret_TEMPLATE.yml`):
   - `Kafka.bootstrap.servers` → ClickPipes broker
   - `Kafka.sasl.username` / `sasl.password` → ClickPipes credentials (API key / secret)
   - `Kafka.security.protocol = SASL_SSL`, `sasl.mechanisms = PLAIN`
   - `SchemaRegistry.url` (and any basic-auth in the URL) → SR connection (only if format is AvroConfluent or Protobuf)
4. Topic from `General.{click,session,user}Topic` in the matching `news_config_*.yml`.
5. Generate the configuration blob.

## Output shape

ClickPipes is configured via the ClickHouse Cloud UI, but you can describe the configuration as a structured block the user fills in. Emit it as:

```
ClickPipes pipeline: world-news-clicks

Source (Confluent Cloud)
    Brokers:           {{ bootstrap.servers }}
    Security:          SASL_SSL / PLAIN
    API Key:           {{ sasl.username }}
    API Secret:        {{ sasl.password }}      # treat as secret, do not paste into git
    Topic:             {{ General.clickTopic }}
    Consumer group:    clickpipes-world-news-clicks-{{ env }}
    Starting offset:   earliest                  # or latest, depending on backfill needs
    Data format:       {{ JSONEachRow | AvroConfluent | Protobuf }}

Schema Registry (only if format != JSONEachRow)
    URL:               {{ SchemaRegistry.url }}     # strip basic auth, move to API key/secret fields
    API Key:           <derived from URL or separate secret>
    API Secret:        <derived from URL or separate secret>

Destination (ClickHouse Cloud)
    Service:           <user picks>
    Database:          default
    Table:             world_news_clicks            # create via ch-schema-ddl
    Engine:            MergeTree
    Ordering key:      see ch-schema-ddl defaults

Column mapping (source field → destination column)
    timestamp          → timestamp        (Int64)
    recordType         → recordType       (LowCardinality(String))
    url                → url              (String)
    ...one row per field from the schema, in declaration order...
```

## Important

- **Never paste real credentials into the generated output.** Use placeholder tokens (`{{ sasl.password }}`) and tell the user to fill them in via the ClickHouse Cloud UI or a secret store.
- `news_secret.yml` is in `.gitignore`. If the user pastes secrets from it into chat, flag the leak before continuing.
- For `session` records, include all seven per-state flag columns (`home`, `content`, `clickbait`, `subscribe`, `plusContent`, `affiliateLink`, `exitSession`) when the producer is using protobuf. JSON / Avro paths in this repo currently emit them only if the producer dict includes them — verify against the matching schema file in the repo.
- ClickPipes Protobuf support has been gated by version — if unsure, ask the user which CH Cloud tier they're on, and fall back to suggesting AvroConfluent or JSONEachRow.
- Consumer-group names should be unique per environment (dev / staging / prod). Don't hardcode.

## Related

- For self-managed CH (Kafka engine tables + MV), use `ch-kafka-pipeline`.
- For just the destination table DDL, use `ch-schema-ddl`.
- For querying the resulting data, use `ch-query-clickstream`.
