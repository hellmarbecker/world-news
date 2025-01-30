CREATE TABLE `world-news-raw` (
  `kafka.key` STRING,
  `payload` STRING
) WITH
  'connector' = 'kafka',
  'topic' = 'world-news',
  'properties.group.id' = 'flinkDemoGroup',
  'scan.startup.mode' = 'earliest-offset',
  'properties.bootstrap.servers' = 'BOOTSTRAP_SERVER',
  'properties.security.protocol' = 'SASL_SSL',
  'properties.sasl.mechanism' = 'PLAIN',
  'properties.sasl.jaas.config' = 'org.apache.kafka.common.security.plain.PlainLoginModule required username="API_KEY" password="API_SECRET";',  
  'key.format' = 'csv',
  'key.fields' = 'kafka.key',
  'value.format' = 'raw'  
)
