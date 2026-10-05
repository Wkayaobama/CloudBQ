-- Audit tables shared by every scenario (layer L13). new_deals_runs (one summary row per run) lives in
-- cloud_function_new_deals/bigquery_schema.sql; these two add the per-deal history and the write-back log.
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.new_deals_history` (
  run_ts TIMESTAMP NOT NULL, entity STRING, orchestrator STRING, deal_id STRING NOT NULL, dealname STRING, final_customer STRING,
  name_key STRING, createdate TIMESTAMP, created_by_user_id STRING, source STRING, owner STRING, sales_region STRING,
  pipeline STRING, pipeline_id STRING, stage STRING, probability_pct FLOAT64, amount FLOAT64, currency STRING, amount_kusd FLOAT64,
  closedate DATE, arr_ky FLOAT64, product_family STRING, product STRING, application STRING, icalps_dealtype STRING, icalps_stage STRING,
  day1_hot_score FLOAT64, day1_hot_flag BOOL, duplicate_suspect BOOL, duplicate_of STRING, deal_url STRING,
  first_seen_run TIMESTAMP, last_seen_run TIMESTAMP)
PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id
OPTIONS (partition_expiration_days = 730, description = "one slice per run: how a deal scored on each run; a replay of a run_ts replaces its slice");

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.writeback_log` (
  run_ts TIMESTAMP NOT NULL, deal_id STRING NOT NULL, hot_score_v1 FLOAT64, hot_flag_v1 BOOL,
  previous_score FLOAT64, previous_flag BOOL, status STRING, http_status INT64, error STRING, dry_run BOOL)
PARTITION BY DATE(run_ts) CLUSTER BY deal_id
OPTIONS (description = "one row per deal per write-back run; status OK | ERROR | DRY");
