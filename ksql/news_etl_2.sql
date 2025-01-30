-- Transform to AVRO
-- This creates a schema registry entry

CREATE OR REPLACE STREAM `world-news-avro` WITH (
  KAFKA_TOPIC='world-news-avro',
  PARTITIONS=6,
  KEY_FORMAT='KAFKA',
  VALUE_FORMAT='AVRO' ) AS
SELECT
  `sid_key`,
  `sid`,
  `timestamp`,
  `recordType`,
  `url`,
  `useragent`,
  `statuscode`,
  `state`,
  `uid`,
  `isSubscriber`,
  `campaign`,
  `channel`,
  `contentId`,
  `subContentId`,
  `gender`,
  `age`,
  `latitude`,
  `longitude`,
  `place_name`,
  `country_code`,
  `timezone`
FROM `world-news-cooked`;

-- Sessionize in ksqlDB using a SESSION window. Because of the EMIT FINAL clause this has to be a TABLE.

CREATE OR REPLACE TABLE `world-news-sessions` WITH (
  KAFKA_TOPIC='world-news-sessions',
  PARTITIONS=6,
  KEY_FORMAT='KAFKA',
  VALUE_FORMAT='JSON' ) AS
SELECT
  `sid_key`,
  MAX(`sid`) AS `sid`,
  MIN(`timestamp`) AS `session_start_time`,
  MAX(`timestamp`) AS `session_end_time`,
  MAX(`useragent`) AS `useragent`,
  COLLECT_LIST(`state`) AS `statesVisited`,
  MAX(`uid`) AS `uid`,
  MAX(`campaign`) AS `campaign`,
  MAX(`channel`) AS `channel`,
  MAX(`gender`) AS `gender`,
  MAX(`age`) AS `age`,
  MAX(`latitude`) AS `latitude`,
  MAX(`longitude`) AS `longitude`,
  MAX(`place_name`) AS `place_name`,
  MAX(`country_code`) AS `country_code`,
  MAX(`timezone`) AS `timezone`,
  COUNT(*) AS `session_depth`
FROM `world-news-cooked`
WINDOW SESSION (30 MINUTES)
GROUP BY `sid_key`
EMIT FINAL;

-- Session changelog

CREATE OR REPLACE TABLE `world-news-sessions-changes` WITH (
  KAFKA_TOPIC='world-news-sessions-changes',
  PARTITIONS=6,
  KEY_FORMAT='KAFKA',
  VALUE_FORMAT='JSON' ) AS
SELECT
  `sid`,
  MIN(`timestamp`) AS session_start_time,
  MAX(`timestamp`) AS session_end_time,
  MAX(`useragent`) AS `useragent`,
  COLLECT_LIST(`state`) AS `statesVisited`,
  MAX(`uid`) AS `uid`,
  MAX(`campaign`) AS `campaign`,
  MAX(`channel`) AS `channel`,
  MAX(`gender`) AS `gender`,
  MAX(`age`) AS `age`,
  MAX(`latitude`) AS `latitude`,
  MAX(`longitude`) AS `longitude`,
  MAX(`place_name`) AS `place_name`,
  MAX(`country_code`) AS `country_code`,
  MAX(`timezone`) AS `timezone`,
  COUNT(*) AS session_depth
FROM `world-news-cooked`
WINDOW SESSION (30 MINUTES)
GROUP BY `sid`
EMIT CHANGES;
