---
name: ch-kafka-pipeline
description: Generate the full self-managed ClickHouse ingestion stack for a topic produced by this repo's news_process.py — Kafka engine source table, MergeTree storage table, and the Materialized View that bridges them. Use when the user asks for "Kafka pipeline", "ingest from Kafka", "MV from Kafka", "consume world-news topic in ClickHouse", or similar. For ClickHouse Cloud, suggest ch-clickpipes instead.
---

# ch-kafka-pipeline

## What this skill does

Emits the three-table pattern ClickHouse uses for streaming ingestion:

1. **Kafka engine source table** — a thin view over the Kafka topic. Does not store data.
2. **MergeTree storage table** — the durable destination (use `ch-schema-ddl` to derive its DDL).
3. **Materialized View** — selects from the Kafka table and inserts into the MergeTree.

## When invoked

1. Ask which record type — `click`, `session`, or `user` — unless stated.
2. Ask which `schemaType` the producer is using — `json` (PlainJSONSerializer or schema-registry-JSON), `avro` (Confluent Schema Registry Avro), or `protobuf`. This determines the Kafka engine `format` setting.
3. Read connection details from the matching `news_config_*.yml` and `news_secret_TEMPLATE.yml`:
   - `Kafka.bootstrap.servers`
   - `Kafka.security.protocol` / `sasl.mechanisms` / `sasl.username` / `sasl.password` (only if present in news_secret.yml)
   - `SchemaRegistry.url` (when format is Avro or Protobuf with SR)
   - `General.clickTopic` / `sessionTopic` / `userTopic`
4. Generate the three statements. Use `ch-schema-ddl` conventions for the MergeTree.

## Format mapping

| Producer config             | ClickHouse Kafka format    |
|-----------------------------|-----------------------------|
| `PlainJSONSerializer` (no SR) | `JSONEachRow`               |
| `JSONSerializer` (SR JSON)   | `JSONEachRow` (schema is registered but each record is still JSON on the wire) |
| `AvroSerializer` (SR Avro)   | `AvroConfluent` (set `format_avro_schema_registry_url`) |
| `ProtobufSerializer` (SR PB) | `Protobuf` with `format_schema = 'msg.proto:MessageName'` — the registry-aware `ProtobufConfluent` format is newer; prefer it on CH 24.x+ |

## Template

```sql
-- 1) Kafka engine source
CREATE TABLE world_news_clicks_kafka
(
    timestamp       Int64,
    recordType      LowCardinality(String),
    url             String,
    -- ...all fields from the producer schema...
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list      = '{{ bootstrap.servers }}',
    kafka_topic_list       = '{{ clickTopic }}',
    kafka_group_name       = 'clickhouse-world-news-clicks',
    kafka_format           = '{{ format }}',
    kafka_num_consumers    = 1,
    kafka_max_block_size   = 65536
    -- For SASL_SSL (Confluent Cloud), use the security/sasl variants on
    -- the Kafka engine via named-collection-style config, NOT inline.
    -- Document the named collection in /etc/clickhouse-server/config.d/.
;

-- 2) Storage (run the ch-schema-ddl skill for this)
CREATE TABLE world_news_clicks ( ... ) ENGINE = MergeTree ...;

-- 3) MV
CREATE MATERIALIZED VIEW world_news_clicks_mv TO world_news_clicks AS
SELECT * FROM world_news_clicks_kafka;
```

## SASL_SSL (Confluent Cloud)

If `news_secret.yml` declares `security.protocol: SASL_SSL`, **do not** inline credentials in the Kafka engine settings — they leak into `system.tables`. Instead, write the credentials into a named collection in a server-side config file:

```xml
<!-- /etc/clickhouse-server/config.d/kafka.xml -->
<clickhouse>
    <named_collections>
        <confluent_cloud>
            <kafka_broker_list>{{ bootstrap.servers }}</kafka_broker_list>
            <kafka_security_protocol>SASL_SSL</kafka_security_protocol>
            <kafka_sasl_mechanism>PLAIN</kafka_sasl_mechanism>
            <kafka_sasl_username>{{ api_key }}</kafka_sasl_username>
            <kafka_sasl_password>{{ api_secret }}</kafka_sasl_password>
        </confluent_cloud>
    </named_collections>
</clickhouse>
```

And reference it from the Kafka engine table with `SETTINGS named_collection = 'confluent_cloud', kafka_topic_list = '...', kafka_group_name = '...', kafka_format = '...';`.

For ClickHouse Cloud or a managed environment where you cannot edit server configs, suggest the user switch to **ClickPipes** (`ch-clickpipes` skill).

## Schema Registry (Avro / Protobuf)

When format is `AvroConfluent`:
- Set the session-level setting `SET format_avro_schema_registry_url = '{{ SchemaRegistry.url }}'` before the MV runs, or configure it server-side under `<format_avro_schema_registry_url>` in `config.xml`.
- The Kafka engine table column list must still match the Avro schema (CH validates).

When format is `Protobuf`:
- Provide the matching `.proto` file via `format_schema = 'click.proto:Click'` and place the file under `format_schemas/` in the CH data dir.
- Or use `ProtobufConfluent` on newer CH versions, which fetches the schema from SR using `format_protobuf_schema_registry_url`.

## Important

- The Kafka engine table is a "pull" — once you create the MV, consumption starts. Run `DROP TABLE ... ON CLUSTER ...` or `DETACH TABLE` on the Kafka table to pause without losing the offset.
- For per-state flag columns (session), they are `UInt8` 0/1 today (the producer emits `int(t in s.statesVisited)`). If `news_process.py:220` is ever changed to emit `bool`, the CH column type must move to `Bool`.
- `statesVisited` is an array — ensure the Kafka format actually carries it (JSONEachRow does; AvroConfluent does via the array type; Protobuf does via `repeated`).
- One MV per topic is enough — don't fan out unless you need different transformations into different storage tables.

## Related

- For Cloud-managed ingestion, see `ch-clickpipes`.
- For querying the resulting tables, see `ch-query-clickstream`.
