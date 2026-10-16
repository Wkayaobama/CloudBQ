-- hot_score_v1.sql — BigQuery SQL port of hot_score() from cloud_function_new_deals/main.py (scenario C compute lane).
-- Replace ${PROJECT}. Returns NULLs for pipelines without a conversion rate, like the Python function.
-- Verify with tests/hot_score_vectors.sql (generated from tests/hot_score_vectors.json): every row must show ok = TRUE.
CREATE OR REPLACE FUNCTION `${PROJECT}.${DATASET}.hot_score_v1`(
  pipeline STRING, hs_deal_stage_probability FLOAT64, closedate TIMESTAMP,
  calculation___pipeline_2026__k__ FLOAT64, services_value_2026 FLOAT64,
  asp_in_usd_q2_2022_calculation FLOAT64, tpm__k_y FLOAT64, product_hierarchy STRING,
  num_contacted_notes FLOAT64, notes_last_updated TIMESTAMP, revenue_state STRING, run_ts TIMESTAMP)
RETURNS STRUCT<score FLOAT64, hot BOOL, raw FLOAT64>
AS ((
  WITH c AS (
    SELECT
      CASE pipeline WHEN '12096408' THEN 84/730 WHEN '13772279' THEN 51/303 END AS cr,
      GREATEST(84/730, 51/303) AS crmax,
      COALESCE(NULLIF(IFNULL(asp_in_usd_q2_2022_calculation, 0), 0), NULLIF(IFNULL(tpm__k_y, 0), 0), IFNULL(services_value_2026, 0)) AS arr
  ), f AS (
    SELECT
      cr,
      IFNULL(hs_deal_stage_probability, 0) AS stage_prob,
      CASE WHEN closedate IS NULL THEN 0
           WHEN EXTRACT(YEAR FROM closedate) <= 2026 THEN 1
           ELSE GREATEST(0, 1 - TIMESTAMP_DIFF(closedate, TIMESTAMP '2026-12-31 00:00:00+00', DAY) / 730) END AS proximity_2026,
      CASE WHEN pipeline = '12096408' THEN IF(IFNULL(calculation___pipeline_2026__k__, 0) = 0, 1, 0)
           ELSE IF(IFNULL(services_value_2026, 0) = 0, 1, 0) END AS missing_2026_field,
      cr / crmax AS pipeline_conversion,
      (CASE WHEN product_hierarchy = 'PKI'
            THEN CASE WHEN arr < 20 THEN 0.5 WHEN arr <= 50 THEN 1 ELSE 2 END
            ELSE CASE WHEN arr < 100 THEN 0.5 WHEN arr <= 500 THEN 1 WHEN arr <= 1000 THEN 2 ELSE 3 END END) / 3 AS arr_points,
      LN(1 + IFNULL(num_contacted_notes, 0)) / LN(1 + 223) AS engagement,
      CASE WHEN notes_last_updated IS NULL THEN 0
           WHEN TIMESTAMP_DIFF(run_ts, notes_last_updated, DAY) <= 90 THEN 1.0
           WHEN TIMESTAMP_DIFF(run_ts, notes_last_updated, DAY) <= 180 THEN 0.5 ELSE 0 END AS recency,
      IF(revenue_state IN ('Forecast', 'BIBA'), 0, 1) AS not_in_forecast
    FROM c
  ), z AS (
    SELECT cr,
      2.0712 * stage_prob + 1.2399 * proximity_2026 + (-0.4136) * missing_2026_field + 1.0918 * pipeline_conversion
      + 4.9843 * arr_points + 1.3018 * engagement + 0.0 * recency + 1.5620 * not_in_forecast + (-6.4788) AS z
    FROM f
  )
  SELECT IF(cr IS NULL, NULL, STRUCT(ROUND(100 / (1 + EXP(-z)), 1) AS score, 100 / (1 + EXP(-z)) >= 45.0 AS hot, 100 / (1 + EXP(-z)) AS raw))
  FROM z
));
