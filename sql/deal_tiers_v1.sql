-- deal_tiers_v1.sql — L2 classification (pass 2): likelihood tiers from the certainty each pipeline actually records.
-- Lane Q of pass 2 (BigQuery-native). Replace ${PROJECT} ${DATASET}; sql/apply.sh applies it after deals_synced_v1.sql.
-- Edges and labels mirror scoring/deal_tiers_v1.constants.json (tests/test_deal_tiers.py keeps them equal).
-- Certainty is a FRACTION (0–1): HubSpot stores hs_deal_stage_probability and icalps_oppocertainty that way, so the operator's
-- "50 % / 75 % / 90 %" are the edges 0.5 / 0.75 / 0.9. RANGE_BUCKET(x, [0.5, 0.75, 0.9]) is numpy.digitize(x, [0.5, 0.75, 0.9]):
-- 0 below 0.5, 1 in [0.5, 0.75), 2 in [0.75, 0.9), 3 at or above 0.9; NULL stays NULL (the notebook proves it per deal, lane N).
-- Source per pipeline: Icalps users type IcAlps_OppoCertainty (99.9 % filled); every other pipeline has only the stage probability.

CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deal_certainty_v1` AS
SELECT deal_id, pipeline_id, dealstage_id, dealname, owner_id, amount_kusd, createdate, closedate, lastmodified, is_closed, is_closed_won,
       CASE WHEN pipeline_id = '766126206' THEN 'icalps_oppocertainty' ELSE 'hs_deal_stage_probability' END AS certainty_source,
       CASE WHEN pipeline_id = '766126206' THEN icalps_oppocertainty ELSE stage_probability END          AS certainty
FROM `${PROJECT}.${DATASET}.deals_synced_v1`;

CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deal_tiers_v1` AS
SELECT c.*,
       RANGE_BUCKET(certainty, [0.5, 0.75, 0.9]) AS bin_index,
       CASE WHEN is_closed_won THEN 'Closed_won'
            WHEN is_closed     THEN 'Closed_lost'
            WHEN is_closed IS NULL OR is_closed_won IS NULL THEN NULL   -- unknown closed state (unexpected connector typing): never tier it
            WHEN certainty IS NULL THEN NULL
            ELSE ['Tier4_pipeline', 'Tier3_opportunity', 'Tier2_opportunity', 'Tier1_opportunity'][OFFSET(RANGE_BUCKET(certainty, [0.5, 0.75, 0.9]))]
       END AS tier
FROM `${PROJECT}.${DATASET}.deal_certainty_v1` c;

-- gold: one row per deal, the tier it holds now and when it last changed (written by sql/deal_tiers_apply.sql — the scheduled MERGE —
-- or by the webhook lane for one deal at a time; the lab notebook writes deal_tiers_lab, never this table)
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.deal_tiers` (
  deal_id STRING NOT NULL, pipeline_id STRING, certainty_source STRING, certainty FLOAT64, bin_index INT64, tier STRING, is_closed BOOL,
  previous_tier STRING, retired_at TIMESTAMP, first_tiered_at TIMESTAMP, last_changed_at TIMESTAMP, computed_at TIMESTAMP, orchestrator STRING)
CLUSTER BY pipeline_id, tier;
ALTER TABLE `${PROJECT}.${DATASET}.deal_tiers` ADD COLUMN IF NOT EXISTS retired_at TIMESTAMP;   -- tier NULL + retired_at: certainty cleared or deal gone from the sync

-- audit: one row per deal per run in which its tier or certainty changed (layer L13 of pass 1 applies here too)
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.deal_tiers_history` (
  run_ts TIMESTAMP NOT NULL, deal_id STRING NOT NULL, pipeline_id STRING, certainty_source STRING, certainty FLOAT64, bin_index INT64,
  tier STRING, previous_tier STRING, orchestrator STRING)
PARTITION BY DATE(run_ts) CLUSTER BY pipeline_id, deal_id
OPTIONS (partition_expiration_days = 730);

-- what every surface compares: counts and amounts per pipeline and tier (live view) and the same over the gold table
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deal_tiers_summary_v1` AS
SELECT pipeline_id, tier, COUNT(*) AS deals, ROUND(SUM(amount_kusd), 1) AS amount_kusd, MIN(certainty) AS certainty_min, MAX(certainty) AS certainty_max
FROM `${PROJECT}.${DATASET}.deal_tiers_v1` GROUP BY pipeline_id, tier;
