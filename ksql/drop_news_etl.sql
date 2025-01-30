TERMINATE ALL; -- kill all persistent queries
DROP TABLE IF EXISTS `world-news-sessions-changes` DELETE TOPIC;
DROP TABLE IF EXISTS `world-news-sessions` DELETE TOPIC;
DROP STREAM IF EXISTS `world-news-avro` DELETE TOPIC;
DROP STREAM IF EXISTS `world-news-de` DELETE TOPIC;
DROP STREAM IF EXISTS `world-news-cooked`; -- this shares a topic with world-news-clicks which is dropped in the next step
DROP STREAM IF EXISTS `world-news-clicks` DELETE TOPIC;
DROP STREAM IF EXISTS `world-news-raw`; -- do not drop the input topic!!
