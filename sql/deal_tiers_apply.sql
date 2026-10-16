-- deal_tiers_apply.sql — the scheduled MERGE of pass 2 (lane Q): deal_tiers_v1 (live over the sync) → deal_tiers (gold) + history.
-- Register after the daily HubSpot → BigQuery transfer (sql/sync_transfer.sh, 02:00 UTC), e.g. "every day 03:00" UTC; @run_time is
-- BigQuery's parameter (manual run: bq query --parameter="run_time:TIMESTAMP:$(date -u +%FT%TZ)" < rendered script).
-- Idempotent: a run without source changes updates computed_at only and writes no history row; replaying a run_time rewrites the
-- same history slice. Variables carry v_ (a column of the same name would shadow a bare name inside MERGE / INSERT … SELECT).
-- Retirement: a deal whose certainty was cleared (tier NULL in the view) or that left the sync (deleted / merged in HubSpot) keeps
-- its row with tier = NULL, previous_tier and retired_at set, and gets a history row — StackSync then clears deal_tier_v1 for a
-- still-existing deal. Two guards keep a stale or failed transfer from retiring everything: the 36 h freshness guard of pass 1 and
-- a row-count guard (the batch must hold at least half of the rows the gold table holds).
DECLARE v_run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(@run_time, SECOND);
DECLARE v_orchestrator STRING DEFAULT 'bigquery-scheduled-query';
DECLARE v_freshest TIMESTAMP;
DECLARE v_batch_rows INT64;
DECLARE v_gold_rows INT64;

-- freshness guard: never MERGE a stale sync (same rule as sql/new_deals_weekly.sql)
SET v_freshest = (SELECT MAX(lastmodified) FROM `${PROJECT}.${DATASET}.deals_synced_v1`);
IF v_freshest IS NULL OR v_freshest < TIMESTAMP_SUB(v_run_ts, INTERVAL 36 HOUR) THEN
  RAISE USING MESSAGE = 'deals sync is older than 36h; aborting the tier run';
END IF;

BEGIN TRANSACTION;

CREATE TEMP TABLE batch AS
SELECT deal_id, pipeline_id, certainty_source, certainty, bin_index, tier, is_closed
FROM `${PROJECT}.${DATASET}.deal_tiers_v1`
QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY lastmodified DESC) = 1;    -- one row per deal even if the transfer appended

-- row-count guard: a half-empty transfer would otherwise retire half the gold table
SET v_batch_rows = (SELECT COUNT(*) FROM batch);
SET v_gold_rows = (SELECT COUNT(*) FROM `${PROJECT}.${DATASET}.deal_tiers`);
IF v_gold_rows > 0 AND v_batch_rows < v_gold_rows / 2 THEN
  RAISE USING MESSAGE = 'synced deals are fewer than half of the gold rows; aborting the tier run';
END IF;

MERGE `${PROJECT}.${DATASET}.deal_tiers` t
USING batch b ON t.deal_id = b.deal_id
WHEN MATCHED AND (t.tier IS DISTINCT FROM b.tier OR t.certainty IS DISTINCT FROM b.certainty) THEN
  UPDATE SET previous_tier = t.tier, tier = b.tier, certainty = b.certainty, bin_index = b.bin_index, certainty_source = b.certainty_source,
             is_closed = b.is_closed, pipeline_id = b.pipeline_id, retired_at = IF(b.tier IS NULL, v_run_ts, NULL),
             last_changed_at = v_run_ts, computed_at = v_run_ts, orchestrator = v_orchestrator
WHEN MATCHED THEN
  UPDATE SET computed_at = v_run_ts
WHEN NOT MATCHED AND b.tier IS NOT NULL THEN                                        -- a deal is born into the gold table with its first tier
  INSERT (deal_id, pipeline_id, certainty_source, certainty, bin_index, tier, is_closed, previous_tier, retired_at, first_tiered_at, last_changed_at, computed_at, orchestrator)
  VALUES (b.deal_id, b.pipeline_id, b.certainty_source, b.certainty, b.bin_index, b.tier, b.is_closed, NULL, NULL, v_run_ts, v_run_ts, v_run_ts, v_orchestrator)
WHEN NOT MATCHED BY SOURCE AND t.tier IS NOT NULL THEN                              -- gone from the sync: deleted or merged in HubSpot
  UPDATE SET previous_tier = t.tier, tier = NULL, bin_index = NULL, retired_at = v_run_ts, last_changed_at = v_run_ts, computed_at = v_run_ts, orchestrator = v_orchestrator;

INSERT INTO `${PROJECT}.${DATASET}.deal_tiers_history` (run_ts, deal_id, pipeline_id, certainty_source, certainty, bin_index, tier, previous_tier, orchestrator)
SELECT v_run_ts, deal_id, pipeline_id, certainty_source, certainty, bin_index, tier, previous_tier, v_orchestrator
FROM `${PROJECT}.${DATASET}.deal_tiers`
WHERE last_changed_at = v_run_ts;                         -- new, changed and retired rows of this run only

COMMIT TRANSACTION;
