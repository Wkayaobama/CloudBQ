-- State + sink for the create-date layer. Rendered by deploy.sh with envsubst: ${PROJECT} ${DATASET} ${BQ_LOCATION}.
-- Idempotent: every statement is IF NOT EXISTS / OR REPLACE / ADD COLUMN IF NOT EXISTS, so `deploy.sh tables` can be re-run.
CREATE SCHEMA IF NOT EXISTS `${PROJECT}.${DATASET}` OPTIONS (location = '${BQ_LOCATION}');

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.report_state` (
  report_id STRING NOT NULL, watermark TIMESTAMP NOT NULL, updated_at TIMESTAMP,
  lock_until TIMESTAMP            -- lease: one run per report_id at a time (acquired by an atomic UPDATE, released after the MERGE)
);
ALTER TABLE `${PROJECT}.${DATASET}.report_state` ADD COLUMN IF NOT EXISTS lock_until TIMESTAMP;

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.new_deals` (
  entity STRING, deal_id STRING NOT NULL, dealname STRING, final_customer STRING, name_key STRING,
  createdate TIMESTAMP, created_by_user_id STRING, source STRING, owner STRING, sales_region STRING,
  pipeline STRING, pipeline_id STRING, stage STRING, probability_pct FLOAT64, amount FLOAT64, currency STRING, amount_kusd FLOAT64,
  closedate DATE, arr_ky FLOAT64, product_family STRING, product STRING, application STRING, icalps_dealtype STRING, icalps_stage STRING,
  day1_hot_score FLOAT64, day1_hot_flag BOOL, duplicate_suspect BOOL, duplicate_of STRING, deal_url STRING,
  first_seen_run TIMESTAMP, last_seen_run TIMESTAMP)
PARTITION BY DATE(createdate) CLUSTER BY entity, deal_id;

-- One row per run (window or event, dry or live), written last; the audit trail every scenario shares (layer L13).
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.new_deals_runs` (
  run_ts TIMESTAMP NOT NULL, entity STRING, mode STRING, dry_run BOOL, orchestrator STRING,
  watermark_in TIMESTAMP, query_start TIMESTAMP, query_end TIMESTAMP,
  row_count INT64, rows_written INT64, duplicate_suspects INT64, day1_hot INT64,
  status STRING, error STRING, duration_ms INT64)
PARTITION BY DATE(run_ts) CLUSTER BY entity;

-- Per-deal history: how every deal scored on each run (every lane writes it; a replayed run_ts replaces its slice) — layer L13.
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.new_deals_history` (
  run_ts TIMESTAMP NOT NULL, entity STRING, orchestrator STRING, deal_id STRING NOT NULL, dealname STRING, final_customer STRING,
  name_key STRING, createdate TIMESTAMP, created_by_user_id STRING, source STRING, owner STRING, sales_region STRING,
  pipeline STRING, pipeline_id STRING, stage STRING, probability_pct FLOAT64, amount FLOAT64, currency STRING, amount_kusd FLOAT64,
  closedate DATE, arr_ky FLOAT64, product_family STRING, product STRING, application STRING, icalps_dealtype STRING, icalps_stage STRING,
  day1_hot_score FLOAT64, day1_hot_flag BOOL, duplicate_suspect BOOL, duplicate_of STRING, deal_url STRING,
  first_seen_run TIMESTAMP, last_seen_run TIMESTAMP)
PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id
OPTIONS (partition_expiration_days = 730);

-- Per-run staging tables are created by the function as `${DATASET}.new_deals_staging_<entity>_<run_ts>` and dropped after the MERGE;
-- the service account needs bigquery.dataEditor on the dataset (deploy.sh grants it).

-- Weekly view used by the delivery step / Breeze consumption (new deals created in the last 7 days, newest first)
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.new_deals_last_7d` AS
SELECT * EXCEPT(name_key) FROM `${PROJECT}.${DATASET}.new_deals`
WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY entity, amount_kusd DESC, createdate DESC;
