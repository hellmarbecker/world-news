# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A clickstream/session data generator that simulates traffic for a fictional news publisher (free + premium content, subscribe page, clickbait multi-page articles, affiliate outlinks). Output goes to Kafka (or stdout in dev mode) and is intended to feed downstream pipelines (ksqlDB, Flink, ClickHouse).

Sessions are driven by a Markov state machine whose transition matrix lives in YAML config — there is **no external state machine library**, the transitions are implemented directly in `news_process.py`.

## Common commands

Run the generator (writes to Kafka per `news_config.yml`):
```
python3 news_process.py -f news_config.yml
```

Dev mode — write JSON to stdout, ignore Kafka settings:
```
python3 news_process.py -f news_config.yml -n
```

Useful flags: `-d` debug logging to stderr, `-q` quiet (suppresses the per-click `.` / per-session `:` progress indicators).

Install deps:
```
pip3 install -r requirements.txt
```

Daemon-style control via `news_simulator.sh` (writes PID to `/tmp/news_simulator.pid`, logs to `/tmp/news_simulator.log`). The script assumes `BASE=~/world-news` — edit that line if running from a different path:
```
./news_simulator.sh start [profile]       # start, optionally setting a mode
./news_simulator.sh stop|restart|status
./news_simulator.sh switch <profile>      # rewrite news_dynamic.yml + SIGHUP
```

Switch modes on a running process without restart: edit `news_dynamic.yml` (one line, e.g. `Mode: special`) and `kill -HUP <pid>`.

## Architecture

### Config layering
`news_process.py` reads the file passed via `-f`, then merges in any files listed under top-level `IncludeOptional:` using `mergedeep.merge` — **later files override earlier ones**. The standard pattern is:
- `news_config*.yml` — committed defaults and the state transition matrices.
- `news_secret.yml` — Kafka bootstrap + SASL credentials and Schema Registry URL (gitignored; template at `news_secret_TEMPLATE.yml`).
- `news_dynamic.yml` — single `Mode:` key selecting which transition matrix and which `ModeConfig` block is active.

### State machine
- `StateMachine.States` is the list of possible page states. Index 0 (`home`) is always the initial state for a new session.
- `StateMachine.StateTransitionMatrix.<mode>` is a row-stochastic dict-of-dicts. Each row must sum to 1.0 (±1e-4), and the target-state set of each row must equal `States`. `checkConfig()` enforces both invariants and raises `GeneratorConfigError` on violation.
- **Exit states are implicit**: any state present in `States` but absent as a row key in the transition matrix terminates the session. `exitSession` is the conventional exit state, but adding more is just a matter of omitting them as row keys. The main loop catches the resulting `KeyError` on `advance()` and emits the session record there.
- `ModeConfig.<mode>` holds per-mode attribute distributions (`channel`, `campaign`, `gender`, `age`) and the `timeEnvelope`. Switching modes changes both the transition probabilities and these distributions.

### Time envelope
`timeEnvelope` is 24 integers (0–1000) representing relative traffic per hour of day. The code tiles the array 3× and fits a cubic spline (`scipy.interpolate.splrep`) so the wraparound at hour 23→0 is smooth. The current weight scales `random.uniform(minSleep, maxSleep)` by `1000.0 / weight`, so larger envelope values produce shorter sleeps and higher event rates.

### Main loop (`news_process.py:323` onward)
Each iteration: probabilistically create a new `Session` (capped by `maxSessions`); pick a random existing session, call `advance()`, and emit a `click` record; if `advance()` lands in an exit state the `KeyError` path emits the `session` record and drops the session. Users are interned in `allUsers` keyed by `uid` (format `u{padded-num}` with width derived from `maxUsers`); with probability `userChangeProbability` an existing user's `place` gets re-rolled and their `version` bumped (user records are currently created in memory but **not emitted** — `emitUser` exists but the call sites are commented out).

### Serialization
`srSerializer(config, item)` returns one of:
- `PlainJSONSerializer` (default) — plain JSON, no schema, used when `SchemaRegistry.enableSchemaRegistry` is false/missing.
- `AvroSerializer` or `JSONSerializer` from `confluent_kafka.schema_registry` — used when Schema Registry is enabled and `schemaType` is `avro` or `json`. Schema file paths per record type come from `SchemaRegistry.schemaFile.{click,session,user}`. The `.asvc` files in the repo root are the Avro schemas.
- `ProtobufSerializer` — used when `schemaType: protobuf`. For protobuf, `schemaFile` values use a `module:Class` format (e.g., `click_pb2:Click`) — the serializer dynamically imports the generated `*_pb2.py` module and derives the schema from the message class descriptor. A wrapper closure converts the emitted dict into the protobuf message via `google.protobuf.json_format.ParseDict` with `ignore_unknown_fields=True`. The `.proto` source files are at the repo root and the generated `*_pb2.py` files are committed.

Templates: `news_config_sr.yml` for Avro, `news_config_pb.yml` for protobuf.

Note: `session.proto` declares explicit `int32` fields for each state in `StateMachine.States` (home, content, clickbait, subscribe, plusContent, affiliateLink, exitSession), matching the per-state flags that `emitSession` adds at news_process.py:220. If `States` ever changes, `session.proto` must be updated and `*_pb2.py` regenerated (`protoc --python_out=. *.proto`).

### Signals
- `SIGHUP` — sets the `reconfigure` flag, breaks the inner loop, re-reads config. Existing sessions persist across the reload (only new ones see the new matrix/distributions); `maxSessions` increases take effect but does not prune already-open sessions.
- `SIGUSR1` — ignored; intended as a liveness probe via `kill -USR1`'s exit code (used by `news_simulator.sh status`).

### Downstream SQL
`ksql/` and `flink/` hold reference ETL queries against the emitted topics — not run by anything in this repo, kept as examples for consumers.

## Conventions and gotchas

- Probability dicts (transition rows, `channel`, `campaign`, etc.) are sampled by `selectAttr()` via cumulative sum — **values must sum to 1.0** or the last entry will be unreachable / `None` will be returned.
- `clickTopic` and `sessionTopic` can point to the same topic; records are distinguished by `recordType`.
- The producer flushes every 2000 messages (`msgCount` global). Don't expect immediate visibility for low-volume tests.
- Don't commit `news_secret.yml` — it's in `.gitignore` for a reason.
