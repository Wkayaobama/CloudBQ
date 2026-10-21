-- new_deals_batch.sql — pass 3 phase 2, S8: the ONE write path of the new-deals pipeline, as a stored procedure. Rendered by sql/apply.sh.
-- Every lane calls it after landing its root slice (deals_raw / labels_raw for (p_run_ts, p_entity, p_orchestrator)):
--   lane C  CALL new_deals_batch(run_ts, entity, 'bigquery-scheduled-query', 'window', TRUE,  'NEW_DEALS_<entity>_C', NULL, run_ts − 14 d, run_ts, 0, gaps)
--   lane A  CALL new_deals_batch(run_ts, entity, 'cloud-run-function',       mode,     FALSE, NULL, watermark_in, qstart, run_ts, started_ms, gaps)
--           (the lease and the NEW_DEALS_<entity> watermark stay in the function: write_watermark() after the CALL, as before)
-- Contract (docs/PASS3_RAW_ROOT.md §3 S8):
--   • reads deals_landed_v1 / labels_raw only (through new_deals_batch_rows) — never a *_synced_v1 view;
--   • mode 'window' | 'event': one transaction — MERGE new_deals (the four frozen columns untouched; an older slice never overwrites a
--     newer observation: WHEN MATCHED AND s.last_seen_run >= t.last_seen_run) → history slice (replaced) → runs row (replaced) →
--     report_state when p_advance_state (watermark = GREATEST, never rewinds) — after checking no lane-A run holds the entity's lease;
--   • mode 'dry' (decision D1): no MERGE, no history, no state; ONE runs row with dry_run = TRUE and rows_written = 0;
--   • any error: ROLLBACK (if a transaction is open), a FAILED runs row with the message, then RAISE — a failed run keeps its audit row;
--   • a caller never wraps the CALL in a transaction of its own (transactions do not nest); the TEMP table is per call (OR REPLACE).
-- data_gaps: p_gaps from the caller, plus labels_missing (no labels slice for the key) and dedup_horizon_partial (the root's oldest
-- createdate is younger than 90 days) decided here.
CREATE OR REPLACE PROCEDURE `${PROJECT}.${DATASET}.new_deals_batch`(
  p_run_ts TIMESTAMP, p_entity STRING, p_orchestrator STRING, p_mode STRING,
  p_advance_state BOOL, p_state_report_id STRING,
  p_watermark_in TIMESTAMP, p_query_start TIMESTAMP, p_query_end TIMESTAMP, p_started_ms INT64, p_gaps ARRAY<STRING>)
BEGIN
  DECLARE v_t0 TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
  DECLARE v_gaps ARRAY<STRING> DEFAULT IFNULL(p_gaps, []);
  DECLARE v_in_txn BOOL DEFAULT FALSE;
  DECLARE v_lock TIMESTAMP;
  DECLARE v_oldest TIMESTAMP;
  BEGIN
    IF p_mode NOT IN ('window', 'event', 'dry') THEN RAISE USING MESSAGE = 'new_deals_batch: mode must be window | event | dry'; END IF;
    IF p_advance_state AND p_state_report_id IS NULL THEN RAISE USING MESSAGE = 'new_deals_batch: advance_state needs a state_report_id'; END IF;
    IF p_advance_state THEN   -- a fallback caller must not collide with a live lane-A run of the same entity (L15)
      SET v_lock = (SELECT lock_until FROM `${PROJECT}.${DATASET}.report_state` WHERE report_id = CONCAT('NEW_DEALS_', p_entity));
      IF v_lock IS NOT NULL AND v_lock > CURRENT_TIMESTAMP() THEN
        RAISE USING MESSAGE = CONCAT('new_deals_batch: a lane-A run holds the lease for ', p_entity, ' until ', CAST(v_lock AS STRING));
      END IF;
    END IF;
    IF 'labels_missing' NOT IN UNNEST(v_gaps)
       AND NOT EXISTS (SELECT 1 FROM `${PROJECT}.${DATASET}.labels_raw` WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator) THEN
      SET v_gaps = ARRAY_CONCAT(v_gaps, ['labels_missing']);   -- the caller may have named it already (lane C's landing)
    END IF;
    SET v_oldest = (SELECT MIN(createdate) FROM `${PROJECT}.${DATASET}.deals_raw` WHERE run_ts <= p_run_ts);
    IF v_oldest IS NULL OR v_oldest > TIMESTAMP_SUB(p_run_ts, INTERVAL 90 DAY) THEN
      SET v_gaps = ARRAY_CONCAT(v_gaps, ['dedup_horizon_partial']);
    END IF;

    CREATE OR REPLACE TEMP TABLE batch AS
    SELECT * FROM `${PROJECT}.${DATASET}.new_deals_batch_rows`(p_run_ts, p_entity, p_orchestrator, p_query_start);

    IF p_mode = 'dry' THEN
      DELETE FROM `${PROJECT}.${DATASET}.new_deals_runs` WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator AND dry_run;
      INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs`
        (run_ts, entity, mode, dry_run, orchestrator, watermark_in, query_start, query_end, row_count, rows_written, duplicate_suspects, day1_hot, status, error, duration_ms, data_gaps)
      SELECT p_run_ts, p_entity, 'dry', TRUE, p_orchestrator, p_watermark_in, p_query_start, p_query_end,
             COUNT(*), 0, COUNTIF(duplicate_suspect), COUNTIF(day1_hot_flag), 'OK', NULL,
             IFNULL(p_started_ms, 0) + TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND), v_gaps
      FROM batch;
    ELSE
      BEGIN TRANSACTION;
      SET v_in_txn = TRUE;

      -- L7: MERGE on deal_id; deal_id, first_seen_run, day1_hot_score, day1_hot_flag are never overwritten (G06); an older slice
      -- (a replayed run_time, a late retry) never overwrites a newer observation
      MERGE `${PROJECT}.${DATASET}.new_deals` t USING batch s ON t.deal_id = s.deal_id
      WHEN MATCHED AND s.last_seen_run >= IFNULL(t.last_seen_run, TIMESTAMP '1970-01-01') THEN UPDATE SET
        entity = s.entity, dealname = s.dealname, final_customer = s.final_customer, name_key = s.name_key, createdate = s.createdate,
        created_by_user_id = s.created_by_user_id, source = s.source, owner = s.owner, sales_region = s.sales_region, pipeline = s.pipeline,
        pipeline_id = s.pipeline_id, stage = s.stage, probability_pct = s.probability_pct, amount = s.amount, currency = s.currency,
        amount_kusd = s.amount_kusd, closedate = s.closedate, arr_ky = s.arr_ky, product_family = s.product_family, product = s.product,
        application = s.application, icalps_dealtype = s.icalps_dealtype, icalps_stage = s.icalps_stage,
        duplicate_suspect = s.duplicate_suspect, duplicate_of = s.duplicate_of, deal_url = s.deal_url, last_seen_run = s.last_seen_run
      WHEN NOT MATCHED THEN INSERT ROW;

      -- L13: the per-deal history slice (replaced for the same key) and the one summary row (replaced for the same key)
      DELETE FROM `${PROJECT}.${DATASET}.new_deals_history`
      WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator
        AND (p_mode <> 'event' OR deal_id IN (SELECT deal_id FROM batch));   -- an event slice is one deal: two events in one second never erase each other
      INSERT INTO `${PROJECT}.${DATASET}.new_deals_history`
      SELECT p_run_ts, entity, p_orchestrator, * EXCEPT(entity) FROM batch;

      DELETE FROM `${PROJECT}.${DATASET}.new_deals_runs` WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator;
      INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs`
        (run_ts, entity, mode, dry_run, orchestrator, watermark_in, query_start, query_end, row_count, rows_written, duplicate_suspects, day1_hot, status, error, duration_ms, data_gaps)
      SELECT p_run_ts, p_entity, p_mode, FALSE, p_orchestrator, p_watermark_in, p_query_start, p_query_end,
             COUNT(*), COUNT(*), COUNTIF(duplicate_suspect), COUNTIF(day1_hot_flag), 'OK', NULL,
             IFNULL(p_started_ms, 0) + TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND), v_gaps
      FROM batch;

      -- L8: state advances inside the same transaction as the MERGE (engine-enforced "only after"); GREATEST: a replay never rewinds
      IF p_advance_state THEN
        MERGE `${PROJECT}.${DATASET}.report_state` t
        USING (SELECT p_state_report_id AS report_id, p_run_ts AS watermark) s ON t.report_id = s.report_id
        WHEN MATCHED THEN UPDATE SET watermark = GREATEST(t.watermark, s.watermark), updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (s.report_id, s.watermark, CURRENT_TIMESTAMP());
      END IF;

      COMMIT TRANSACTION;
      SET v_in_txn = FALSE;
    END IF;
  EXCEPTION WHEN ERROR THEN
    IF v_in_txn THEN ROLLBACK TRANSACTION; END IF;
    INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs`
      (run_ts, entity, mode, dry_run, orchestrator, watermark_in, query_start, query_end, row_count, rows_written, status, error, duration_ms, data_gaps)
    VALUES (p_run_ts, p_entity, p_mode, p_mode = 'dry', p_orchestrator, p_watermark_in, p_query_start, p_query_end, 0, 0, 'FAILED',
            SUBSTR(@@error.message, 1, 1000), IFNULL(p_started_ms, 0) + TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), v_t0, MILLISECOND), v_gaps);
    RAISE;
  END;
END;
