-- Versioned scoring views (scenario C, layer L5/L6). v1 is never edited in place: a new fit is hot_score_v2 + hot_deals_v2.
-- Needs scoring/hot_score_v1.sql (the UDF) and sql/deals_synced_v1.sql applied first (sql/apply.sh does it in order).
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1` AS
WITH scored AS (
  SELECT d.*,
         `${PROJECT}.${DATASET}.hot_score_v1`(d.pipeline_id, d.stage_probability, d.closedate, d.calculation___pipeline_2026__k__,
            d.services_value_2026, d.asp_in_usd_q2_2022_calculation, d.tpm__k_y, d.product_hierarchy, d.num_contacted_notes,
            d.notes_last_updated, d.revenue_state, CURRENT_TIMESTAMP()) AS hs
  FROM `${PROJECT}.${DATASET}.deals_synced_v1` d
  LEFT JOIN `${PROJECT}.${DATASET}.pipeline_stages_synced_v1` st ON st.stage_id = d.dealstage_id
  WHERE d.pipeline_id IN ('12096408', '13772279')                                   -- scored pipelines only (main.py CR)
    AND NOT REGEXP_CONTAINS(LOWER(IFNULL(st.label, '')), r'closed')                -- open deals only; label from pipeline_labels
)
SELECT deal_id, dealname, final_customer, sales_region, pipeline_id, amount_kusd, closedate,
       hs.score AS hot_score_v1, hs.hot AS hot_flag_v1,
       ROW_NUMBER() OVER (PARTITION BY sales_region ORDER BY hs.score DESC, amount_kusd DESC, deal_id) AS region_rank,
       RANK()       OVER (ORDER BY hs.score DESC, amount_kusd DESC)                                       AS global_rank,
       hot_score_v1_synced, hot_flag_v1_synced
FROM scored;

-- per-region top-5: the arithmetic HubSQL cannot do (window functions)
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1_top5_by_region` AS
SELECT * FROM `${PROJECT}.${DATASET}.hot_deals_v1` QUALIFY region_rank <= 5;

-- rows the write-back must PATCH: the computed value differs from what HubSpot holds (last successful write-back, else the synced property).
-- Never a NULL score: sending "" would clear the property on unscored pipelines.
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1_writeback` AS
SELECT h.deal_id, h.hot_score_v1, h.hot_flag_v1,
       COALESCE(w.last.hot_score_v1, h.hot_score_v1_synced) AS previous_score,
       COALESCE(w.last.hot_flag_v1,  h.hot_flag_v1_synced)  AS previous_flag
FROM `${PROJECT}.${DATASET}.hot_deals_v1` h
LEFT JOIN (SELECT deal_id, ARRAY_AGG(STRUCT(hot_score_v1, hot_flag_v1) ORDER BY run_ts DESC LIMIT 1)[OFFSET(0)] AS last
           FROM `${PROJECT}.${DATASET}.writeback_log` WHERE status = 'OK' AND NOT dry_run GROUP BY deal_id) w USING (deal_id)
WHERE h.hot_score_v1 IS NOT NULL
  AND (h.hot_score_v1 IS DISTINCT FROM COALESCE(w.last.hot_score_v1, h.hot_score_v1_synced)
    OR h.hot_flag_v1  IS DISTINCT FROM COALESCE(w.last.hot_flag_v1,  h.hot_flag_v1_synced));
