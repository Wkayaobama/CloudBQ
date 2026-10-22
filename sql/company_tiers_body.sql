-- company_tiers_body.sql — the company object by foreign-key resolution, as CTEs over a `deal_source` the including statement defines.
-- Included (sed `r` at the marker `-- @include company_tiers_body.sql`) by sql/company_tiers_v1.sql, where deal_source is the sync
-- (deal_tiers_v1 ⋈ deals_synced_v1), and by notebooks/company_tiers.ipynb, where deal_source is UNNEST(@deals_payload) — the lab's
-- snapshot as a query parameter, so the dry run computes the same rows and writes nothing. deal_source must expose:
--   deal_id STRING, pipeline_id STRING, dealstage_id STRING, dealname STRING, final_customer STRING, sales_region STRING,
--   icalps_dealstatus STRING, certainty_source STRING, certainty FLOAT64, bin_index INT64, tier STRING, is_closed BOOL,
--   is_closed_won BOOL, amount_kusd FLOAT64
-- The chain: labelled (pipeline/stage labels) → arr (the ARR dashboard staging: entity, the primary company association, the yearly
-- figures) → in_status (the icalps_dealstatus rule) → three resolvers → resolved (one row per deal, its company) → rollup (one row per
-- sales_region × company × tier, the deals nested). Placeholders: ${PROJECT} ${DATASET} ${ARR_PROJECT} ${ARR_DATASET}.
labelled AS (
  SELECT d.*,
         COALESCE(p.label, d.pipeline_id)   AS pipeline,
         COALESCE(st.label, d.dealstage_id) AS deal_stage,
         COALESCE(NULLIF(TRIM(d.sales_region), ''), '(no region)') AS region,
         NULLIF(TRIM(d.icalps_dealstatus), '') AS dealstatus,
         REGEXP_REPLACE(LOWER(TRIM(COALESCE(d.icalps_dealstatus, ''))), r'[_-]+', ' ') AS dealstatus_norm   -- 'In Progress' = 'in_progress' = 'In-progress'
  FROM deal_source d
  LEFT JOIN `${PROJECT}.${DATASET}.pipelines_synced_v1` p        ON p.pipeline_id = d.pipeline_id
  LEFT JOIN `${PROJECT}.${DATASET}.pipeline_stages_synced_v1` st ON st.stage_id = d.dealstage_id
),
arr AS (
  SELECT CAST(deal_id AS STRING) AS deal_id, CAST(entity AS STRING) AS entity, CAST(company_ids AS STRING) AS company_ids,
         CAST(final_customer AS STRING) AS arr_final_customer, SAFE_CAST(amount AS FLOAT64) AS amount_native_k,
         SAFE_CAST(pipeline_2026_k AS FLOAT64) AS pipeline_2026_k, SAFE_CAST(pipeline_2027_k AS FLOAT64) AS pipeline_2027_k,
         SAFE_CAST(pipeline_2028_k AS FLOAT64) AS pipeline_2028_k, SAFE_CAST(pipeline_2029_k AS FLOAT64) AS pipeline_2029_k,
         SAFE_CAST(weighted_2026_k AS FLOAT64) AS weighted_2026_k, SAFE_CAST(weighted_2027_k AS FLOAT64) AS weighted_2027_k,
         SAFE_CAST(weighted_2028_k AS FLOAT64) AS weighted_2028_k, SAFE_CAST(weighted_2029_k AS FLOAT64) AS weighted_2029_k
  FROM `${ARR_PROJECT}.${ARR_DATASET}.stg_deals`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY CAST(deal_id AS STRING) ORDER BY deal_id) = 1
),
in_status AS (
  SELECT l.*, a.* EXCEPT (deal_id),
         COALESCE(NULLIF(TRIM(l.final_customer), ''), NULLIF(TRIM(a.arr_final_customer), '')) AS fc,
         -- the icalps_dealstatus rule: an Icalps deal counts only while "In Progress"; every other pipeline carries no status (or the same word)
         CASE WHEN l.pipeline_id = '766126206' THEN l.dealstatus_norm = 'in progress'
              ELSE l.dealstatus_norm IN ('', 'in progress') END AS status_ok
  FROM labelled l
  LEFT JOIN arr a USING (deal_id)
),
companies AS (
  SELECT company_id, company_name, LOWER(TRIM(company_name)) AS name_norm
  FROM `${PROJECT}.${DATASET}.companies_synced_v1`
  WHERE COALESCE(company_name, '') != ''
),
-- resolver 1: the deal's own primary company association (exact, the foreign key HubSpot holds)
primary_assoc AS (
  SELECT deal_id, SPLIT(company_ids, ';')[SAFE_OFFSET(0)] AS company_id
  FROM in_status
  WHERE COALESCE(company_ids, '') != ''
),
-- resolver 2: the ARR clinic's final-customer → portal company map
clinic_map AS (
  SELECT LOWER(TRIM(CAST(final_customer AS STRING))) AS fc_norm,
         ANY_VALUE(CAST(portal_company_id AS STRING))   AS company_id,
         ANY_VALUE(CAST(portal_company_name AS STRING)) AS company_name
  FROM `${ARR_PROJECT}.${ARR_DATASET}.rec_three_layer`
  WHERE COALESCE(CAST(final_customer AS STRING), '') != '' AND COALESCE(CAST(portal_company_id AS STRING), '') != ''
  GROUP BY fc_norm
),
-- resolver 3: an exact match of the final customer on the company name (one company per normalised name)
companies_norm AS (
  SELECT name_norm, ANY_VALUE(company_id) AS company_id, ANY_VALUE(company_name) AS company_name
  FROM companies
  GROUP BY name_norm
),
resolved AS (
  SELECT d.* EXCEPT (dealstatus_norm, arr_final_customer),
         COALESCE(p.company_id, c.company_id, n.company_id)            AS company_id,
         COALESCE(cn.company_name, c.company_name, n.company_name)     AS company_name,
         CASE WHEN p.company_id IS NOT NULL THEN '1_primary_assoc'
              WHEN c.company_id IS NOT NULL THEN '2_clinic_fc_map'
              WHEN n.company_id IS NOT NULL THEN '3_direct_company_name'
              WHEN COALESCE(d.fc, '') != '' THEN '4_unresolved_fc'
              ELSE '5_no_fc_or_company' END                             AS resolver,
         COALESCE(p.company_id, c.company_id, n.company_id,
                  IF(COALESCE(d.fc, '') != '', CONCAT('fc:', LOWER(TRIM(d.fc))), CONCAT('deal:', d.deal_id))) AS entity_key
  FROM in_status d
  LEFT JOIN primary_assoc p  ON p.deal_id = d.deal_id
  LEFT JOIN companies cn     ON cn.company_id = p.company_id
  LEFT JOIN clinic_map c     ON p.company_id IS NULL AND LOWER(TRIM(d.fc)) = c.fc_norm
  LEFT JOIN companies_norm n ON p.company_id IS NULL AND c.company_id IS NULL AND LOWER(TRIM(d.fc)) = n.name_norm
),
rollup AS (
  SELECT region AS sales_region, entity_key, tier,
         ANY_VALUE(company_id)   AS company_id,
         ANY_VALUE(company_name) AS company_name,
         ANY_VALUE(resolver)     AS resolver,
         ARRAY_AGG(DISTINCT deal_stage IGNORE NULLS ORDER BY deal_stage) AS stages,
         ARRAY_AGG(DISTINCT dealstatus IGNORE NULLS ORDER BY dealstatus) AS dealstatuses,
         ARRAY_AGG(DISTINCT entity IGNORE NULLS ORDER BY entity)         AS entities,
         ARRAY_AGG(DISTINCT pipeline IGNORE NULLS ORDER BY pipeline)     AS pipelines,
         ARRAY_AGG(DISTINCT fc IGNORE NULLS ORDER BY fc)                 AS final_customers,
         COUNT(DISTINCT deal_id)    AS n_deals,
         MAX(certainty)             AS max_certainty,
         ROUND(AVG(certainty), 3)   AS avg_certainty,
         ARRAY_AGG(STRUCT(deal_id, dealname, deal_stage, certainty, amount_kusd) ORDER BY amount_kusd DESC, deal_id) AS deals,
         ARRAY<STRUCT<year INT64, pipeline_k FLOAT64, weighted_k FLOAT64>>[
           (2026, SUM(pipeline_2026_k), SUM(weighted_2026_k)), (2027, SUM(pipeline_2027_k), SUM(weighted_2027_k)),
           (2028, SUM(pipeline_2028_k), SUM(weighted_2028_k)), (2029, SUM(pipeline_2029_k), SUM(weighted_2029_k))] AS years,
         SUM(COALESCE(pipeline_2026_k, 0) + COALESCE(pipeline_2027_k, 0) + COALESCE(pipeline_2028_k, 0) + COALESCE(pipeline_2029_k, 0)) AS total_pipeline_k,
         SUM(amount_native_k) AS amount_native_k,
         SUM(amount_kusd)     AS amount_kusd
  FROM resolved
  WHERE status_ok
  GROUP BY sales_region, entity_key, tier
)
