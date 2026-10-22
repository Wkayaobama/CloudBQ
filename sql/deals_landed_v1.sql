-- deals_landed_v1.sql — pass 3 phase 2, S2 + S7: the adapter over the raw root and the pure batch as a table function.
-- Rendered by sql/apply.sh (${PROJECT} ${DATASET} ${PORTAL_ID}). Both objects read deals_raw / labels_raw ONLY — never a *_synced_v1
-- view — so the function's service account needs no grant on the sync dataset.
--
-- S2  deals_landed_v1: one typed column per landed property. The JSON keys are the HubSpot property names for BOTH sources
--     (lane A lands the API strings, lane C lands TO_JSON of the sync table with the same names); typing happens once, here, with
--     SAFE_CAST so a malformed value reads NULL instead of failing the batch (deals_synced_v1.sql does the same for the sync).
--     name_key is computed here too: it is a pure function of the properties and both the batch and the duplicate horizon need it.
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deals_landed_v1` AS
SELECT
  run_ts, entity, orchestrator, mode, source, in_scope, fetched_at, deal_id, createdate, pipeline_id,
  JSON_VALUE(properties, '$.dealname')                                           AS dealname,
  JSON_VALUE(properties, '$.final_customer')                                     AS final_customer,
  IFNULL(SUBSTR(REGEXP_REPLACE(LOWER(COALESCE(NULLIF(TRIM(JSON_VALUE(properties, '$.final_customer')), ''),
                                             REGEXP_EXTRACT(JSON_VALUE(properties, '$.dealname'), r'^[^-/|(]*'))),
                               r'[^a-z0-9]', ''), 1, 40), '')                   AS name_key,       -- = main.py name_key()
  JSON_VALUE(properties, '$.sales_region')                                       AS sales_region,
  JSON_VALUE(properties, '$.dealstage')                                          AS dealstage_id,
  SAFE_CAST(JSON_VALUE(properties, '$.hs_deal_stage_probability') AS FLOAT64)    AS stage_probability,
  SAFE_CAST(JSON_VALUE(properties, '$.amount') AS FLOAT64)                       AS amount,
  SAFE_CAST(JSON_VALUE(properties, '$.amount_in_home_currency') AS FLOAT64)      AS amount_kusd,
  JSON_VALUE(properties, '$.deal_currency_code')                                 AS currency,
  SAFE_CAST(JSON_VALUE(properties, '$.closedate') AS TIMESTAMP)                  AS closedate,
  SAFE_CAST(JSON_VALUE(properties, '$.asp_in_usd_q2_2022_calculation') AS FLOAT64) AS asp_in_usd_q2_2022_calculation,
  SAFE_CAST(JSON_VALUE(properties, '$.tpm__k_y') AS FLOAT64)                     AS tpm__k_y,
  SAFE_CAST(JSON_VALUE(properties, '$.services_value_2026') AS FLOAT64)          AS services_value_2026,
  SAFE_CAST(JSON_VALUE(properties, '$.calculation___pipeline_2026__k__') AS FLOAT64) AS calculation___pipeline_2026__k__,
  JSON_VALUE(properties, '$.product_hierarchy')                                  AS product_hierarchy,
  JSON_VALUE(properties, '$.prod___product_name_new_')                           AS product,
  JSON_VALUE(properties, '$.application')                                        AS application,
  JSON_VALUE(properties, '$.hubspot_owner_id')                                   AS owner_id,
  JSON_VALUE(properties, '$.hs_object_source_label')                             AS source_label,
  JSON_VALUE(properties, '$.hs_object_source_detail_1')                          AS source_detail,  -- NULL on lane-C slices (data_gaps: source_detail_unavailable)
  JSON_VALUE(properties, '$.icalps_dealtype')                                    AS icalps_dealtype,
  JSON_VALUE(properties, '$.icalps_stage')                                       AS icalps_stage,
  JSON_VALUE(properties, '$.icalps_dealstatus')                                  AS icalps_dealstatus,
  SAFE_CAST(JSON_VALUE(properties, '$.num_contacted_notes') AS FLOAT64)          AS num_contacted_notes,
  SAFE_CAST(JSON_VALUE(properties, '$.notes_last_updated') AS TIMESTAMP)         AS notes_last_updated,
  JSON_VALUE(properties, '$.revenue_state')                                      AS revenue_state,
  JSON_VALUE(properties, '$.hs_created_by_user_id')                              AS created_by_user_id,
  SAFE_CAST(JSON_VALUE(properties, '$.hs_lastmodifieddate') AS TIMESTAMP)        AS lastmodified     -- NULL on slices landed before PROPS gained it
FROM `${PROJECT}.${DATASET}.deals_raw`;

-- S7  new_deals_batch_rows: the shaped, scored, de-duplicated batch of one run — pure, read-only, callable by anyone with read
--     access. Column list and order = hubspot.new_deals (the procedure MERGEs with INSERT ROW). The window: the slice's in-scope deals, one
--     row per deal (latest fetched_at), bounded to [p_window_start, run_ts) when p_window_start is given (lane A: the search already
--     applied its window, so the bound is a no-op; lane C: its 14-day lookback over the 90-day slice); NULL = the whole slice (an event). Duplicates (S6): every deal the root knows as of run_ts
--     (any entity, any orchestrator, in-scope or not, 90-day horizon), latest observation per deal_id — lane C's rule for both lanes
--     (decision D3); duplicate_of ordered by createdate. Labels: the slice's own labels_raw rows, label falling back to the id.
--     Debug a past run X without writing: SELECT * FROM `${PROJECT}.${DATASET}.new_deals_batch_rows`(X, 'SEALSQ', 'cloud-run-function', NULL)
CREATE OR REPLACE TABLE FUNCTION `${PROJECT}.${DATASET}.new_deals_batch_rows`(
  p_run_ts TIMESTAMP, p_entity STRING, p_orchestrator STRING, p_window_start TIMESTAMP)
AS
WITH win AS (
  SELECT * FROM `${PROJECT}.${DATASET}.deals_landed_v1`
  WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator AND in_scope
    AND (p_window_start IS NULL OR (createdate >= p_window_start AND createdate < p_run_ts))   -- NULL (an event, a debugger): the whole slice — an event deal created in run_ts's own second must not be dropped
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY fetched_at DESC) = 1   -- a doubled slice (delete-older failed, a paged search repeating a deal) must never reach the MERGE: one source row per deal
), horizon AS (
  SELECT deal_id, createdate, name_key
  FROM `${PROJECT}.${DATASET}.deals_landed_v1`
  WHERE run_ts <= p_run_ts AND createdate >= TIMESTAMP_SUB(p_run_ts, INTERVAL 90 DAY) AND createdate < p_run_ts
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY run_ts DESC, fetched_at DESC) = 1
), dups AS (
  SELECT w.deal_id, STRING_AGG(h.deal_id, ', ' ORDER BY h.createdate, h.deal_id) AS duplicate_of
  FROM win w JOIN horizon h ON h.name_key = w.name_key AND h.deal_id <> w.deal_id AND w.name_key <> ''
  GROUP BY w.deal_id
), labels AS (
  SELECT kind, id, ANY_VALUE(label) AS label FROM `${PROJECT}.${DATASET}.labels_raw`
  WHERE run_ts = p_run_ts AND entity = p_entity AND orchestrator = p_orchestrator
  GROUP BY kind, id
)
SELECT p_entity AS entity, w.deal_id, w.dealname, w.final_customer, w.name_key,
       w.createdate, w.created_by_user_id, w.source_label AS source,
       COALESCE(o.label, w.owner_id) AS owner, w.sales_region,
       COALESCE(p.label, w.pipeline_id) AS pipeline, w.pipeline_id, COALESCE(s.label, w.dealstage_id) AS stage,
       ROUND(IFNULL(w.stage_probability, 0) * 100, 1) AS probability_pct, IFNULL(w.amount, 0) AS amount, w.currency,
       IFNULL(w.amount_kusd, 0) AS amount_kusd, DATE(w.closedate) AS closedate,
       IFNULL(w.asp_in_usd_q2_2022_calculation, 0) AS arr_ky, w.product_hierarchy AS product_family, w.product, w.application,
       w.icalps_dealtype, w.icalps_stage,
       hs.score AS day1_hot_score, hs.hot AS day1_hot_flag,
       d.duplicate_of IS NOT NULL AS duplicate_suspect, d.duplicate_of,
       CONCAT('https://app.hubspot.com/go-to/${PORTAL_ID}/0-3/', w.deal_id) AS deal_url,
       p_run_ts AS first_seen_run, p_run_ts AS last_seen_run
FROM win w
LEFT JOIN dups d USING (deal_id)
LEFT JOIN labels o ON o.kind = 'owner' AND o.id = w.owner_id
LEFT JOIN labels p ON p.kind = 'pipeline' AND p.id = w.pipeline_id
LEFT JOIN labels s ON s.kind = 'stage' AND s.id = w.dealstage_id,
UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`(w.pipeline_id, w.stage_probability, w.closedate, w.calculation___pipeline_2026__k__,
        w.services_value_2026, w.asp_in_usd_q2_2022_calculation, w.tpm__k_y, w.product_hierarchy, w.num_contacted_notes,
        w.notes_last_updated, w.revenue_state, p_run_ts)]) AS hs;
