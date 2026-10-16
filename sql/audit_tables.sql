-- Scenario C's own audit table (layer L13). new_deals_runs and new_deals_history live in cloud_function_new_deals/bigquery_schema.sql
-- (deploy.sh tables / sql/apply.sh create them for every lane); writeback_log belongs to the write-back job only.
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.writeback_log` (
  run_ts TIMESTAMP NOT NULL, deal_id STRING NOT NULL, hot_score_v1 FLOAT64, hot_flag_v1 BOOL,
  previous_score FLOAT64, previous_flag BOOL, status STRING, http_status INT64, error STRING, dry_run BOOL)
PARTITION BY DATE(run_ts) CLUSTER BY deal_id
OPTIONS (description = "one row per deal per write-back run; status OK | ERROR | DRY");
