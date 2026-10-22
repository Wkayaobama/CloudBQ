-- Scenario C scheduled script (pass 3 phase 2): freshness guard → land the root (sql/land_raw.sql) → CALL new_deals_batch.
-- Registered per entity by sql/scheduled_query.sh (${ENTITY}, ${PIPELINES} substituted); @run_time is BigQuery's parameter.
-- The batch itself — window → shape → score → duplicates → MERGE → history → run log → state, in ONE transaction — is the stored
-- procedure sql/new_deals_batch.sql over the root (sql/deals_landed_v1.sql); this script only lands and calls. Idempotent: the batch
-- is a pure function of (root slice, run_ts); replaying a run_time re-lands the slice (raw_slice_replaced) and rewrites the same rows.
DECLARE v_entity STRING DEFAULT '${ENTITY}';          -- v_ prefix: a column with the same name would shadow the variable
DECLARE v_pipelines ARRAY<STRING> DEFAULT ${PIPELINES};
DECLARE v_lookback_days INT64 DEFAULT 14;                        -- replaces the watermark search; MERGE absorbs the overlap
DECLARE v_run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(@run_time, SECOND);
DECLARE v_orchestrator STRING DEFAULT 'bigquery-scheduled-query';
DECLARE v_mode STRING DEFAULT 'window';
DECLARE v_freshest TIMESTAMP;
DECLARE v_watermark_in TIMESTAMP;
DECLARE v_t0 TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE v_landed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE v_gaps ARRAY<STRING> DEFAULT ['source_detail_unavailable'];

-- freshness guard: never MERGE a stale sync (the sync is scheduled, never real-time)
SET v_freshest = (SELECT MAX(lastmodified) FROM `${PROJECT}.${DATASET}.deals_synced_v1`);
IF v_freshest IS NULL OR v_freshest < TIMESTAMP_SUB(v_run_ts, INTERVAL 36 HOUR) THEN
  INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs` (run_ts, entity, mode, dry_run, orchestrator, status, error, duration_ms, data_gaps)
  VALUES (v_run_ts, v_entity, v_mode, FALSE, v_orchestrator, 'ABORTED', 'deals sync older than 36h', 0, ['sync_stale']);
  RAISE USING MESSAGE = 'deals sync is older than 36h; aborting run';
END IF;

-- a transfer run started with a past run_time reads the sync as of now (full refresh): name it
IF v_run_ts < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR) THEN
  SET v_gaps = ARRAY_CONCAT(v_gaps, ['raw_backfilled_from_current_sync']);
END IF;

-- pass 3 root: land the inputs (plain DML, outside any transaction) — sql/land_raw.sql is spliced here by scheduled_query.sh.
-- A landing error is named (raw_landing_failed) and the batch still runs from whatever slice exists; a plain BEGIN…END is not a transaction.
BEGIN
-- @include land_raw.sql
EXCEPTION WHEN ERROR THEN
  SET v_gaps = ARRAY_CONCAT(v_gaps, ['raw_landing_failed']);
END;

-- S8: the one write path (sql/new_deals_batch.sql). advance_state = TRUE on C's own report_id (never A's); the procedure checks
-- A's lease first, opens its own transaction, and writes the runs row (OK or FAILED) — this script writes nothing else.
SET v_watermark_in = (SELECT watermark FROM `${PROJECT}.${DATASET}.report_state` WHERE report_id = CONCAT('NEW_DEALS_', v_entity, '_C'));
CALL `${PROJECT}.${DATASET}.new_deals_batch`(
  v_run_ts, v_entity, v_orchestrator, v_mode,
  TRUE, CONCAT('NEW_DEALS_', v_entity, '_C'),
  v_watermark_in, TIMESTAMP_SUB(v_run_ts, INTERVAL v_lookback_days DAY), v_run_ts,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND), v_gaps);
