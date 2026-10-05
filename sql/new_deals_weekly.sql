-- Scenario C scheduled script: window → shape → duplicates → MERGE → history → run log → state, in ONE transaction.
-- Registered per entity by sql/scheduled_query.sh (${ENTITY}, ${PIPELINES} substituted); @run_time is BigQuery's parameter.
-- Idempotent: the batch is a pure function of (synced state, @run_time); replaying a run_time rewrites the same slices.
DECLARE entity STRING DEFAULT '${ENTITY}';
DECLARE pipelines ARRAY<STRING> DEFAULT ${PIPELINES};
DECLARE lookback_days INT64 DEFAULT 14;                        -- replaces the watermark search; MERGE absorbs the overlap
DECLARE run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(@run_time, SECOND);
DECLARE freshest TIMESTAMP;
DECLARE t0 TIMESTAMP DEFAULT CURRENT_TIMESTAMP();

-- freshness guard: never MERGE a stale sync (the sync is scheduled, never real-time)
SET freshest = (SELECT MAX(lastmodified) FROM `${PROJECT}.${DATASET}.deals_synced_v1`);
IF freshest IS NULL OR freshest < TIMESTAMP_SUB(run_ts, INTERVAL 36 HOUR) THEN
  INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs` (run_ts, entity, mode, dry_run, orchestrator, status, error, duration_ms)
  VALUES (run_ts, entity, 'window', FALSE, 'bigquery-scheduled-query', 'ABORTED', 'deals sync older than 36h', 0);
  RAISE USING MESSAGE = 'deals sync is older than 36h; aborting run';
END IF;

BEGIN TRANSACTION;

CREATE TEMP TABLE batch AS
WITH recent AS (
  SELECT *, SUBSTR(REGEXP_REPLACE(LOWER(COALESCE(NULLIF(TRIM(final_customer), ''), REGEXP_EXTRACT(dealname, r'^[^-/|(]*'))), r'[^a-z0-9]', ''), 1, 40) AS name_key
  FROM `${PROJECT}.${DATASET}.deals_synced_v1`
  WHERE createdate >= TIMESTAMP_SUB(run_ts, INTERVAL 90 DAY) AND createdate < run_ts     -- duplicate horizon = main.py recent_names(days=90)
), win AS (
  SELECT * FROM recent WHERE createdate >= TIMESTAMP_SUB(run_ts, INTERVAL lookback_days DAY) AND pipeline_id IN UNNEST(pipelines)
), dups AS (
  SELECT w.deal_id, STRING_AGG(r.deal_id, ', ' ORDER BY r.createdate) AS duplicate_of
  FROM win w JOIN recent r ON r.name_key = w.name_key AND r.deal_id <> w.deal_id AND w.name_key <> ''
  GROUP BY w.deal_id
)
SELECT entity, w.deal_id, w.dealname, w.final_customer, w.name_key,
       w.createdate, w.created_by_user_id, w.source,
       COALESCE(o.owner_name, w.owner_id) AS owner, w.sales_region,
       COALESCE(p.label, w.pipeline_id) AS pipeline, w.pipeline_id, COALESCE(s.label, w.dealstage_id) AS stage,
       ROUND(IFNULL(w.stage_probability, 0) * 100, 1) AS probability_pct, IFNULL(w.amount, 0) AS amount, w.currency,
       IFNULL(w.amount_kusd, 0) AS amount_kusd, DATE(w.closedate) AS closedate,
       IFNULL(w.asp_in_usd_q2_2022_calculation, 0) AS arr_ky, w.product_hierarchy AS product_family, w.product, w.application,
       w.icalps_dealtype, w.icalps_stage,
       hs.score AS day1_hot_score, hs.hot AS day1_hot_flag,
       d.duplicate_of IS NOT NULL AS duplicate_suspect, d.duplicate_of,
       CONCAT('https://app.hubspot.com/go-to/${PORTAL_ID}/0-3/', w.deal_id) AS deal_url,
       run_ts AS first_seen_run, run_ts AS last_seen_run
FROM win w
LEFT JOIN dups d USING (deal_id)
LEFT JOIN `${PROJECT}.${DATASET}.owners_synced_v1` o ON o.owner_id = w.owner_id
LEFT JOIN `${PROJECT}.${DATASET}.pipelines_synced_v1` p ON p.pipeline_id = w.pipeline_id
LEFT JOIN `${PROJECT}.${DATASET}.pipeline_stages_synced_v1` s ON s.stage_id = w.dealstage_id,
UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`(w.pipeline_id, w.stage_probability, w.closedate, w.calculation___pipeline_2026__k__,
        w.services_value_2026, w.asp_in_usd_q2_2022_calculation, w.tpm__k_y, w.product_hierarchy, w.num_contacted_notes,
        w.notes_last_updated, w.revenue_state, run_ts)]) AS hs;

-- L7: MERGE on deal_id; deal_id, first_seen_run and the day-1 score are never overwritten (same frozen set as main.py after G06)
MERGE `${PROJECT}.${DATASET}.new_deals` t USING batch s ON t.deal_id = s.deal_id
WHEN MATCHED THEN UPDATE SET
  entity = s.entity, dealname = s.dealname, final_customer = s.final_customer, name_key = s.name_key, createdate = s.createdate,
  created_by_user_id = s.created_by_user_id, source = s.source, owner = s.owner, sales_region = s.sales_region, pipeline = s.pipeline,
  pipeline_id = s.pipeline_id, stage = s.stage, probability_pct = s.probability_pct, amount = s.amount, currency = s.currency,
  amount_kusd = s.amount_kusd, closedate = s.closedate, arr_ky = s.arr_ky, product_family = s.product_family, product = s.product,
  application = s.application, icalps_dealtype = s.icalps_dealtype, icalps_stage = s.icalps_stage,
  duplicate_suspect = s.duplicate_suspect, duplicate_of = s.duplicate_of, deal_url = s.deal_url, last_seen_run = s.last_seen_run
WHEN NOT MATCHED THEN INSERT ROW;

-- L13: per-deal history slice (replay of the same run_ts replaces it) and one summary row
DELETE FROM `${PROJECT}.${DATASET}.new_deals_history` WHERE run_ts = run_ts AND entity = entity;
INSERT INTO `${PROJECT}.${DATASET}.new_deals_history`
SELECT run_ts, entity, 'bigquery-scheduled-query', * EXCEPT(entity) FROM batch;

DELETE FROM `${PROJECT}.${DATASET}.new_deals_runs` WHERE run_ts = run_ts AND entity = entity AND orchestrator = 'bigquery-scheduled-query';
INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs`
  (run_ts, entity, mode, dry_run, orchestrator, watermark_in, query_start, query_end, row_count, rows_written, duplicate_suspects, day1_hot, status, error, duration_ms)
SELECT run_ts, entity, 'window', FALSE, 'bigquery-scheduled-query',
       (SELECT watermark FROM `${PROJECT}.${DATASET}.report_state` WHERE report_id = CONCAT('NEW_DEALS_', entity, '_C')),
       TIMESTAMP_SUB(run_ts, INTERVAL lookback_days DAY), run_ts,
       COUNT(*), COUNT(*), COUNTIF(duplicate_suspect), COUNTIF(day1_hot_flag), 'OK', NULL,
       TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), t0, MILLISECOND)
FROM batch;

-- L8: state advances inside the same transaction as the MERGE (engine-enforced "only after"); C keeps its own report_id
MERGE `${PROJECT}.${DATASET}.report_state` t
USING (SELECT CONCAT('NEW_DEALS_', entity, '_C') AS report_id, run_ts AS watermark) s ON t.report_id = s.report_id
WHEN MATCHED THEN UPDATE SET watermark = s.watermark, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (s.report_id, s.watermark, CURRENT_TIMESTAMP());

COMMIT TRANSACTION;
