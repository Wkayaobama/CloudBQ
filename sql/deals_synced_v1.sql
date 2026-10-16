-- Adapter views over the HubSpot → BigQuery sync (scenario C, layer L4). The connector decides the raw names and types;
-- these views are the single place that knows them, so every downstream object reads stable names.
-- ${SYNC_DATASET}.${SYNC_DEALS_TABLE} / ${SYNC_OWNERS_TABLE} are filled from .env after the first transfer run
-- (Google DTS HubSpot connector: native tables per asset; HubSpot Data Hub sync: external tables in hubspot_data_set_<hubId>).
-- SAFE_CAST tolerates either typing. Deals outside the five known pipelines pass through and are filtered downstream.
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deals_synced_v1` AS
SELECT
  CAST(hs_object_id AS STRING)                                   AS deal_id,
  CAST(pipeline AS STRING)                                       AS pipeline_id,
  CAST(dealstage AS STRING)                                      AS dealstage_id,
  CAST(dealname AS STRING)                                       AS dealname,
  CAST(final_customer AS STRING)                                 AS final_customer,
  CAST(sales_region AS STRING)                                   AS sales_region,
  CAST(deal_currency_code AS STRING)                             AS currency,
  CAST(product_hierarchy AS STRING)                              AS product_hierarchy,
  CAST(prod___product_name_new_ AS STRING)                       AS product,
  CAST(application AS STRING)                                    AS application,
  CAST(icalps_dealtype AS STRING)                                AS icalps_dealtype,
  CAST(icalps_stage AS STRING)                                   AS icalps_stage,
  CAST(icalps_dealstatus AS STRING)                              AS icalps_dealstatus,
  CAST(revenue_state AS STRING)                                  AS revenue_state,
  CAST(hs_object_source_label AS STRING)                         AS source,
  CAST(hs_created_by_user_id AS STRING)                          AS created_by_user_id,
  CAST(hubspot_owner_id AS STRING)                               AS owner_id,
  SAFE_CAST(createdate AS TIMESTAMP)                             AS createdate,
  SAFE_CAST(closedate AS TIMESTAMP)                              AS closedate,
  SAFE_CAST(notes_last_updated AS TIMESTAMP)                     AS notes_last_updated,
  SAFE_CAST(hs_lastmodifieddate AS TIMESTAMP)                    AS lastmodified,
  SAFE_CAST(hs_deal_stage_probability AS FLOAT64)                AS stage_probability,
  SAFE_CAST(amount AS FLOAT64)                                   AS amount,
  SAFE_CAST(amount_in_home_currency AS FLOAT64)                  AS amount_kusd,
  SAFE_CAST(asp_in_usd_q2_2022_calculation AS FLOAT64)           AS asp_in_usd_q2_2022_calculation,
  SAFE_CAST(tpm__k_y AS FLOAT64)                                 AS tpm__k_y,
  SAFE_CAST(services_value_2026 AS FLOAT64)                      AS services_value_2026,
  SAFE_CAST(calculation___pipeline_2026__k__ AS FLOAT64)         AS calculation___pipeline_2026__k__,
  SAFE_CAST(num_contacted_notes AS FLOAT64)                      AS num_contacted_notes,
  SAFE_CAST(icalps_oppocertainty AS FLOAT64)                     AS icalps_oppocertainty,   -- Icalps users' certainty (pass 2, L2 tiers)
  SAFE_CAST(hs_is_closed AS BOOL)                                AS is_closed,
  SAFE_CAST(hs_is_closed_won AS BOOL)                            AS is_closed_won
  -- the written-back properties (hot_score_v1 / hot_flag_v1) are NOT selected here: they exist in the synced table only after
  -- bootstrap_property.sh and a later sync, and a view that names a missing column fails to create. The write-back compares
  -- against writeback_log instead (sql/hot_deals_v1.sql).
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_DEALS_TABLE}`
WHERE hs_object_id IS NOT NULL;

CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.owners_synced_v1` AS
SELECT CAST(id AS STRING) AS owner_id,
       NULLIF(TRIM(CONCAT(IFNULL(CAST(firstName AS STRING), ''), ' ', IFNULL(CAST(lastName AS STRING), ''))), '') AS owner_name,
       CAST(email AS STRING) AS owner_email
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_OWNERS_TABLE}`;

-- pipeline and stage labels are not a sync asset: sql/refresh_pipeline_labels.sh loads them from GET /crm/v3/pipelines/deals
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.pipeline_labels` (
  pipeline_id STRING NOT NULL, pipeline_label STRING, stage_id STRING, stage_label STRING, stage_probability FLOAT64, refreshed_at TIMESTAMP);
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.pipelines_synced_v1` AS
SELECT DISTINCT pipeline_id, pipeline_label AS label FROM `${PROJECT}.${DATASET}.pipeline_labels`;
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.pipeline_stages_synced_v1` AS
SELECT stage_id, stage_label AS label, pipeline_id FROM `${PROJECT}.${DATASET}.pipeline_labels` WHERE stage_id IS NOT NULL;
