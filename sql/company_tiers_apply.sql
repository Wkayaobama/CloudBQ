-- company_tiers_apply.sql — the scheduled refresh of pass 2b (lane Q): company_tiers_v1 (live over the sync) → company_tiers (the
-- snapshot the dashboards read) + company_tiers_history (one slice per refresh, like the raw root of pass 3) + company_tiers_refreshes.
-- Registered by sql/company_tiers_schedule.sh after the daily HubSpot → BigQuery transfer (02:00 UTC), off the hour; @run_time is
-- BigQuery's parameter (manual run: bq query --parameter="run_time:TIMESTAMP:$(date -u +%FT%TZ)" < rendered script, or the notebook).
-- Idempotent: replaying a run_time rewrites the same slice; the snapshot is replaced inside one transaction, so a reader never sees it
-- half-written. Guards: the 36 h freshness guard of the sync and a row-count guard (a half-empty transfer must not replace the snapshot).
-- Any error: ROLLBACK, a FAILED refreshes row with the message, RAISE.
DECLARE v_run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(@run_time, SECOND);
DECLARE v_orchestrator STRING DEFAULT 'bigquery-scheduled-query';
DECLARE v_t0 TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE v_freshest TIMESTAMP;
DECLARE v_batch_rows INT64;
DECLARE v_current_rows INT64;
DECLARE v_in_txn BOOL DEFAULT FALSE;

BEGIN
  SET v_freshest = (SELECT MAX(lastmodified) FROM `${PROJECT}.${DATASET}.deals_synced_v1`);
  IF v_freshest IS NULL OR v_freshest < TIMESTAMP_SUB(v_run_ts, INTERVAL 36 HOUR) THEN
    RAISE USING MESSAGE = 'deals sync is older than 36h; aborting the company refresh';
  END IF;

  CREATE OR REPLACE TEMP TABLE batch AS SELECT * FROM `${PROJECT}.${DATASET}.company_tiers_v1`;

  SET v_batch_rows = (SELECT COUNT(*) FROM batch);
  SET v_current_rows = (SELECT COUNT(*) FROM `${PROJECT}.${DATASET}.company_tiers`);
  IF v_current_rows > 0 AND v_batch_rows < v_current_rows / 2 THEN
    RAISE USING MESSAGE = 'the live view holds fewer than half of the snapshot rows; aborting the company refresh';
  END IF;

  BEGIN TRANSACTION;
  SET v_in_txn = TRUE;

  DELETE FROM `${PROJECT}.${DATASET}.company_tiers` WHERE TRUE;
  INSERT INTO `${PROJECT}.${DATASET}.company_tiers`
    (refresh_ts, orchestrator, sales_region, entity_key, tier, company_id, company_name, resolver, stages, dealstatuses, entities, pipelines,
     final_customers, n_deals, max_certainty, avg_certainty, deals, years, total_pipeline_k, amount_native_k, amount_kusd)
  SELECT v_run_ts, v_orchestrator, sales_region, entity_key, tier, company_id, company_name, resolver, stages, dealstatuses, entities, pipelines,
         final_customers, n_deals, max_certainty, avg_certainty, deals, years, total_pipeline_k, amount_native_k, amount_kusd
  FROM batch;

  DELETE FROM `${PROJECT}.${DATASET}.company_tiers_history` WHERE refresh_ts = v_run_ts AND orchestrator = v_orchestrator;
  INSERT INTO `${PROJECT}.${DATASET}.company_tiers_history`
    (refresh_ts, orchestrator, sales_region, entity_key, tier, company_id, company_name, resolver, stages, dealstatuses, entities, pipelines,
     final_customers, n_deals, max_certainty, avg_certainty, deals, years, total_pipeline_k, amount_native_k, amount_kusd)
  SELECT v_run_ts, v_orchestrator, sales_region, entity_key, tier, company_id, company_name, resolver, stages, dealstatuses, entities, pipelines,
         final_customers, n_deals, max_certainty, avg_certainty, deals, years, total_pipeline_k, amount_native_k, amount_kusd
  FROM batch;

  DELETE FROM `${PROJECT}.${DATASET}.company_tiers_refreshes` WHERE refresh_ts = v_run_ts AND orchestrator = v_orchestrator;
  INSERT INTO `${PROJECT}.${DATASET}.company_tiers_refreshes` (refresh_ts, orchestrator, status, error, n_rows, n_companies, n_unresolved, n_deals, duration_ms)
  SELECT v_run_ts, v_orchestrator, 'OK', NULL, COUNT(*), COUNT(DISTINCT company_id), COUNTIF(resolver NOT IN ('1_primary_assoc', '2_clinic_fc_map', '3_direct_company_name')),
         SUM(n_deals), TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND)   -- inside a transaction CURRENT_TIMESTAMP() is its start
  FROM batch;

  COMMIT TRANSACTION;
  SET v_in_txn = FALSE;
EXCEPTION WHEN ERROR THEN
  IF v_in_txn THEN
    BEGIN ROLLBACK TRANSACTION; EXCEPTION WHEN ERROR THEN END;
  END IF;
  INSERT INTO `${PROJECT}.${DATASET}.company_tiers_refreshes` (refresh_ts, orchestrator, status, error, n_rows, n_companies, n_unresolved, n_deals, duration_ms)
  VALUES (v_run_ts, v_orchestrator, 'FAILED', SUBSTR(@@error.message, 1, 1000), 0, 0, 0, 0, TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND));
  RAISE;
END;
