-- land_raw.sql — the raw root for lane C (pass 3, layers L4 + L13): the 90-day set the batch computes from, landed from the SYNC TABLE
-- with HubSpot property names (never from the renamed adapter view), plus the labels the run resolves with. Included by
-- sql/new_deals_weekly.sql (marker `-- @include land_raw.sql`, spliced by scheduled_query.sh) and by sql/backfill_raw.sh.
-- Expects the variables v_run_ts, v_entity, v_pipelines, v_orchestrator, v_mode, v_landed_at and v_gaps (ARRAY<STRING>) to be DECLAREd
-- by the including script; a re-landing of an existing key appends raw_slice_replaced to v_gaps.
-- Plain DML outside any transaction: a failed batch must leave its inputs queryable, and a transaction cannot nest. Load first, then
-- delete older rows of the same (run_ts, entity, orchestrator) key, so a failure between the two statements never leaves an empty slice.
-- hs_object_source_detail_1 is not landed until the first transfer confirms the column (data_gaps: source_detail_unavailable).
INSERT INTO `${PROJECT}.${DATASET}.deals_raw`
  (run_ts, entity, orchestrator, mode, source, deal_id, in_scope, createdate, pipeline_id, properties, fetched_at)
SELECT v_run_ts, v_entity, v_orchestrator, v_mode, 'dts_sync',
       CAST(hs_object_id AS STRING), IFNULL(CAST(pipeline AS STRING) IN UNNEST(v_pipelines), FALSE),   -- IN is NULL for a NULL pipeline; in_scope is NOT NULL
       SAFE_CAST(createdate AS TIMESTAMP), CAST(pipeline AS STRING),
       TO_JSON(STRUCT(dealname, createdate, final_customer, sales_region, pipeline, dealstage, hs_deal_stage_probability, amount,
                      amount_in_home_currency, deal_currency_code, closedate, asp_in_usd_q2_2022_calculation, tpm__k_y, services_value_2026,
                      calculation___pipeline_2026__k__, product_hierarchy, prod___product_name_new_, application, hubspot_owner_id,
                      hs_object_source_label, icalps_dealtype, icalps_stage, icalps_dealstatus, num_contacted_notes, notes_last_updated,
                      revenue_state, hs_created_by_user_id, hs_lastmodifieddate), stringify_wide_numbers => TRUE),   -- a NUMERIC the JSON cannot hold losslessly lands as a string instead of throwing
       v_landed_at
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_DEALS_TABLE}`
WHERE hs_object_id IS NOT NULL
  AND SAFE_CAST(createdate AS TIMESTAMP) >= TIMESTAMP_SUB(v_run_ts, INTERVAL 90 DAY) AND SAFE_CAST(createdate AS TIMESTAMP) < v_run_ts
QUALIFY ROW_NUMBER() OVER (PARTITION BY hs_object_id ORDER BY SAFE_CAST(hs_lastmodifieddate AS TIMESTAMP) DESC) = 1;   -- one row per deal (deal_tiers_apply.sql:27)
DELETE FROM `${PROJECT}.${DATASET}.deals_raw`
WHERE run_ts = v_run_ts AND entity = v_entity AND orchestrator = v_orchestrator AND mode = v_mode AND fetched_at < v_landed_at;
IF @@row_count > 0 THEN SET v_gaps = ARRAY_CONCAT(v_gaps, ['raw_slice_replaced']); END IF;   -- the predecessor is recoverable by time travel only

INSERT INTO `${PROJECT}.${DATASET}.labels_raw` (run_ts, entity, orchestrator, kind, id, label, fetched_at)
SELECT v_run_ts, v_entity, v_orchestrator, 'pipeline', pipeline_id, label, v_landed_at FROM `${PROJECT}.${DATASET}.pipelines_synced_v1`
UNION ALL SELECT v_run_ts, v_entity, v_orchestrator, 'stage', stage_id, label, v_landed_at FROM `${PROJECT}.${DATASET}.pipeline_stages_synced_v1`
UNION ALL SELECT v_run_ts, v_entity, v_orchestrator, 'owner', owner_id, owner_name, v_landed_at FROM `${PROJECT}.${DATASET}.owners_synced_v1` WHERE owner_id IS NOT NULL;
IF @@row_count = 0 THEN SET v_gaps = ARRAY_CONCAT(v_gaps, ['labels_missing']); END IF;   -- pipeline_labels not loaded yet (sql/refresh_pipeline_labels.sh) and no owners
DELETE FROM `${PROJECT}.${DATASET}.labels_raw`
WHERE run_ts = v_run_ts AND entity = v_entity AND orchestrator = v_orchestrator AND fetched_at < v_landed_at;
