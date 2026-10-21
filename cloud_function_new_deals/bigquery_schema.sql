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

-- One row per run (window or event; live runs only — a dry run writes no row until decision D1 takes effect in pass 3 phase 3), written
-- last; the audit trail every scenario shares (layer L13).
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

-- Pass 3 — the raw root (layers L4 + L13): what each run computed from, landed as delivered and keyed like new_deals_history
-- (run_ts, entity, orchestrator). Lane A lands the HubSpot search result (in-scope deals and the out-of-scope duplicate candidates),
-- lane C lands its 90-day set from the sync table with the same HubSpot property names. The adapter view (pass 3 phase 2) types the
-- JSON once; nothing in `properties` is typed (createdate and pipeline_id are promoted copies). Re-landing the same key replaces the
-- slice (load first, then delete older rows of the key; an event landing deletes only its own deal's older rows).
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.deals_raw` (
  run_ts TIMESTAMP NOT NULL, entity STRING NOT NULL, orchestrator STRING NOT NULL,
  mode STRING NOT NULL,                 -- window | event | dry
  source STRING NOT NULL,               -- hubspot_api | dts_sync
  deal_id STRING NOT NULL,
  in_scope BOOL NOT NULL,               -- TRUE: the entity's pipelines; FALSE: duplicate candidate from another pipeline ("others")
  createdate TIMESTAMP, pipeline_id STRING,   -- promoted so the window and duplicate predicates are typed columns (no pruning: partitioned by run_ts)
  properties JSON NOT NULL,             -- the PROPS as the source delivered them (HubSpot strings for the API, the sync's typed values for DTS)
  fetched_at TIMESTAMP NOT NULL)
PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id, createdate
OPTIONS (partition_expiration_days = 730);

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.labels_raw` (
  run_ts TIMESTAMP NOT NULL, entity STRING NOT NULL, orchestrator STRING NOT NULL,
  kind STRING NOT NULL,                 -- pipeline | stage | owner
  id STRING NOT NULL, label STRING, fetched_at TIMESTAMP NOT NULL)
PARTITION BY DATE(run_ts) CLUSTER BY kind, id
OPTIONS (partition_expiration_days = 730);

-- data_gaps: what a run could not read or compute (sync_stale, labels_missing, dedup_horizon_partial, dedup_scope_batch_only,
-- raw_landing_failed, raw_slice_replaced, raw_backfilled_from_current_sync, source_detail_unavailable, event_no_window)
ALTER TABLE `${PROJECT}.${DATASET}.new_deals_runs` ADD COLUMN IF NOT EXISTS data_gaps ARRAY<STRING>;

-- Per-run staging tables are created by the function as `${DATASET}.new_deals_staging_<entity>_<run_ts>` and dropped after the MERGE;
-- the service account needs bigquery.dataEditor on the dataset (deploy.sh grants it).

-- Weekly view used by the delivery step / Breeze consumption (new deals created in the last 7 days, newest first)
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.new_deals_last_7d` AS
SELECT * EXCEPT(name_key) FROM `${PROJECT}.${DATASET}.new_deals`
WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY entity, amount_kusd DESC, createdate DESC;
