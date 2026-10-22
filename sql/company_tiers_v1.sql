-- company_tiers_v1.sql — pass 2b: the company object by foreign-key resolution, over the L2 tiers (lane Q, BigQuery-native).
-- Applied by sql/apply.sh after deal_tiers_v1.sql when SYNC_COMPANIES_TABLE is set (the sync's Companies asset); the notebook
-- notebooks/company_tiers.ipynb applies the same rendered file from Python (lane N) after its dry run passed.
-- The CTE chain lives in sql/company_tiers_body.sql (spliced at the marker) so the dry run and the views are one SQL text; this file only
-- names the sources and the sinks. Placeholders: ${PROJECT} ${DATASET} ${SYNC_DATASET} ${SYNC_COMPANIES_TABLE} ${SYNC_COMPANY_ID_COLUMN}
-- ${ARR_PROJECT} ${ARR_DATASET}. Nothing here writes into the sync tables: every derived column lives in ${DATASET}.

-- the Companies asset of the sync (Data Hub sync: id/name; DTS connector: hs_object_id/name — SYNC_COMPANY_ID_COLUMN names it)
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.companies_synced_v1` AS
SELECT CAST(${SYNC_COMPANY_ID_COLUMN} AS STRING) AS company_id, CAST(name AS STRING) AS company_name
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_COMPANIES_TABLE}`
WHERE ${SYNC_COMPANY_ID_COLUMN} IS NOT NULL;

-- the deal input every surface shares: the L2 tier per deal (deal_tiers_v1) with the deal's own customer, region and status
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.company_deal_input_v1` AS
SELECT t.deal_id, t.pipeline_id, t.dealstage_id, t.dealname, d.final_customer, d.sales_region, d.icalps_dealstatus,
       t.certainty_source, t.certainty, t.bin_index, t.tier, t.is_closed, t.is_closed_won, t.amount_kusd
FROM `${PROJECT}.${DATASET}.deal_tiers_v1` t
JOIN `${PROJECT}.${DATASET}.deals_synced_v1` d USING (deal_id)
QUALIFY ROW_NUMBER() OVER (PARTITION BY t.deal_id ORDER BY t.lastmodified DESC) = 1;   -- one row per deal even if the transfer appended

-- one row per deal: its company, how it was resolved, the key the rollup groups by
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.company_deals_v1` AS
WITH deal_source AS (SELECT * FROM `${PROJECT}.${DATASET}.company_deal_input_v1`),
-- @include company_tiers_body.sql
SELECT * FROM resolved;

-- the company object: one row per sales_region × company (entity_key) × tier, its deals nested — the live view
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.company_tiers_v1` AS
WITH deal_source AS (SELECT * FROM `${PROJECT}.${DATASET}.company_deal_input_v1`),
-- @include company_tiers_body.sql
SELECT * FROM rollup;

-- the snapshot the dashboards read (replaced by every refresh, sql/company_tiers_apply.sql) and its per-refresh slices
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.company_tiers` (
  refresh_ts TIMESTAMP NOT NULL, orchestrator STRING NOT NULL,
  sales_region STRING, entity_key STRING NOT NULL, tier STRING,
  company_id STRING, company_name STRING, resolver STRING,
  stages ARRAY<STRING>, dealstatuses ARRAY<STRING>, entities ARRAY<STRING>, pipelines ARRAY<STRING>, final_customers ARRAY<STRING>,
  n_deals INT64, max_certainty FLOAT64, avg_certainty FLOAT64,
  deals ARRAY<STRUCT<deal_id STRING, dealname STRING, deal_stage STRING, certainty FLOAT64, amount_kusd FLOAT64>>,
  years ARRAY<STRUCT<year INT64, pipeline_k FLOAT64, weighted_k FLOAT64>>,
  total_pipeline_k FLOAT64, amount_native_k FLOAT64, amount_kusd FLOAT64)
CLUSTER BY sales_region, entity_key;

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.company_tiers_history` (
  refresh_ts TIMESTAMP NOT NULL, orchestrator STRING NOT NULL,
  sales_region STRING, entity_key STRING NOT NULL, tier STRING,
  company_id STRING, company_name STRING, resolver STRING,
  stages ARRAY<STRING>, dealstatuses ARRAY<STRING>, entities ARRAY<STRING>, pipelines ARRAY<STRING>, final_customers ARRAY<STRING>,
  n_deals INT64, max_certainty FLOAT64, avg_certainty FLOAT64,
  deals ARRAY<STRUCT<deal_id STRING, dealname STRING, deal_stage STRING, certainty FLOAT64, amount_kusd FLOAT64>>,
  years ARRAY<STRUCT<year INT64, pipeline_k FLOAT64, weighted_k FLOAT64>>,
  total_pipeline_k FLOAT64, amount_native_k FLOAT64, amount_kusd FLOAT64)
PARTITION BY DATE(refresh_ts) CLUSTER BY sales_region, entity_key
OPTIONS (partition_expiration_days = 730);

-- one row per refresh, also on failure — the probe of lane N and the equality check of the workbook
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.company_tiers_refreshes` (
  refresh_ts TIMESTAMP NOT NULL, orchestrator STRING NOT NULL, status STRING NOT NULL, error STRING,
  n_rows INT64, n_companies INT64, n_unresolved INT64, n_deals INT64, duration_ms INT64)
PARTITION BY DATE(refresh_ts);

-- what every surface compares: rows, companies and deals per region, tier and resolver — live, and over the snapshot
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.company_tiers_summary_v1` AS
SELECT sales_region, tier, resolver, COUNT(*) AS rows_, COUNT(DISTINCT company_id) AS companies, SUM(n_deals) AS deals,
       ROUND(SUM(amount_kusd), 1) AS amount_kusd, ROUND(SUM(total_pipeline_k), 1) AS total_pipeline_k
FROM `${PROJECT}.${DATASET}.company_tiers_v1`
GROUP BY sales_region, tier, resolver;
