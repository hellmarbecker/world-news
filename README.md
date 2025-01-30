# world-news

## world-news: Data generator for a publisher

This simulates data for a news outlet. It has free and premium content, a subscribe page, clickbait (multi-page content), and affiliate outlinks.

The state machine is controlled by a transition matrix, this implementation does not use an external library.

While the possible states are always the same, different transition matrices can exist (to model the compelling switching event.) The entire configuration is in YAML format and is held in `news_config.yml`.

The transition matrices are organized as a dictionary, there should be an entry with key `"default"`.

For secure Kafka (Confluent Cloud), you should create a file `news_secret.yml` in the main directory, which contains the bootstrap address and credentials for Confluent Cloud, like so:

    Kafka:
        bootstrap.servers: "<bootstrap server>"
        security.protocol: "SASL_SSL"
        sasl.mechanisms: "PLAIN"
        sasl.username: "<API Key>"
        sasl.password: "<Secret>"
        
Settings in this section correspond directly with Kafka consumer properties.
        
This file is automatically included if it is present. Do not check secrets into Github.
    
### Dependencies

Python packages:
- Faker
- confluent_kafka
- scipy
- mergedeep

### Time envelope

The `timeEnvelope` setting must be an array of 24 values, each between 0 and 1000. These are relative data generation frequencies per hour of day. Frequency values will be interpolated using cubic splines, which is what `scipy` is used for.

### Components of the news data generator

#### `news_process.py`

The generator script proper. It writes its result to Kafka, or in developer mode to standard output.

Invocation: `python3 news_process.py [-h] [-d] [-q] -f CONFIG [-n]`

where

```
-d - debug mode, create rich logging output to stderr
-q - quiet mode, don't write anything to stderr (usually it writes a '.' per click and a ':' per session)
-f CONFIG - config file, this is required
-n - write to stdout instead of Kafka, for testing. Kafka options are ignored
```

`news_process.py` handles the following signals:
- `SIGHUP` triggers a configuration reread. Typically you would update `news_dynamic.yml` and then send `SIGHUP` to switch mode
- `SIGUSR1` is ignored and can be used as a heartbeat.

#### `news_config.yml`

State values and transition matrices. This is a YAML file and has two subfiles that can be included:

- `news_secret.yml` is for sensitive options such as Kafka API keys or passwords, overrides settings in main config file
- `news_dynamic.yml` contains the mode (default or special, you can define more)

#### `news_simulator.sh`

Driver script, handles mode selection.

#### `admin.crontab`

Crontab for the default user (`admin` on Debian.) This will cause a drop in conversion rates 1x per week for a few hours. Install using `crontab -e`.

