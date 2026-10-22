# Recipe — pass 3 phase 2: the single implementation over the root (adapter view, table function, procedure; lane C calls it)

/add sql/deals_landed_v1.sql sql/new_deals_batch.sql sql/new_deals_weekly.sql sql/apply.sh tests/test_pass3_sql.py docs/PASS3_RAW_ROOT.md
/read-only sql/land_raw.sql cloud_function_new_deals/main.py cloud_function_new_deals/bigquery_schema.sql scoring/hot_score_v1.sql CONVENTIONS.md

The root (phase 1) holds every run's inputs; the batch is still computed four ways (main.py, the weekly script, the n8n Code node,
the .mjs). Make it ONE SQL implementation over the root, callable by every lane, with the pure part separable from the write part.

1. sql/deals_landed_v1.sql — S2 the VIEW deals_landed_v1: one typed column per landed property (JSON_VALUE + SAFE_CAST; the JSON keys
   are the HubSpot property names for both sources), name_key computed once as main.py name_key() does; S7 the TABLE FUNCTION
   new_deals_batch_rows(run_ts, entity, orchestrator, window_start): window = the slice's in-scope deals created before run_ts and at
   or after window_start when given (lane C's 14-day lookback; NULL for lane A, whose search applied its own window); duplicates =
   lane C's rule over every deal the root knows as of run_ts (any entity, any orchestrator, in-scope or not, 90-day horizon, latest
   observation per deal_id), duplicate_of ordered by createdate (D3); labels from the slice's labels_raw with the id as fallback; the
   hot_score_v1 UDF with run_ts as "now"; column list and order = hubspot.new_deals. Both objects read deals_raw / labels_raw only.
2. sql/new_deals_batch.sql — S8 the PROCEDURE new_deals_batch(run_ts, entity, orchestrator, mode, advance_state, state_report_id,
   watermark_in, query_start, query_end, started_ms, gaps): validation and the lane-A lease check before anything; labels_missing and
   dedup_horizon_partial decided here; CREATE OR REPLACE TEMP TABLE batch from the table function; mode dry → one runs row
   (dry_run TRUE, rows_written 0), nothing else; otherwise ONE transaction: MERGE new_deals (frozen four untouched; WHEN MATCHED AND
   s.last_seen_run >= t.last_seen_run so an older slice never overwrites a newer observation) → history slice replaced (an event
   deletes only its own deal) → runs row replaced → report_state when advance_state (watermark = GREATEST, never rewinds); any error:
   ROLLBACK if open, a FAILED runs row with @@error.message, RAISE. Never a *_synced_v1 view.
3. sql/new_deals_weekly.sql — the lane-C script becomes: DECLAREs → freshness guard → gaps → landing (sql/land_raw.sql spliced,
   inside BEGIN … EXCEPTION → raw_landing_failed) → SET v_watermark_in → CALL new_deals_batch(…, TRUE, 'NEW_DEALS_<entity>_C', …,
   v_gaps). No transaction in the script. sql/apply.sh applies the two new files last.
4. tests/test_pass3_sql.py — what can be proved offline: the view types exactly main.PROPS (createdate/pipeline promoted); the table
   function's columns equal new_deals in order; the MERGE update list excludes the frozen four and covers every other column; the
   procedure and the view never name a sync view; the procedure's contract (parameters, dry branch, one transaction, exception path,
   GREATEST, lease, OR REPLACE temp table); every emitted data_gaps value is in the vocabulary and each lane's values are emitted;
   apply order and placeholders; tests/pass3_batch_vectors.sql is current. The EXECUTED check (first authenticated step, a dev dataset):
   `bq query < tests/pass3_batch_vectors.sql` lands the 15 vectors as a deals_raw slice, reads them through the view and the table
   function, compares score and flag, drops the slice — every row ok = TRUE.
5. docs/PASS3_RAW_ROOT.md — "Phase 2 as implemented"; architecture nodes; the L4–L8/L13 lane-C cells; README; timeline.

Behaviour change: lane C computes through the procedure (same rows: same name_key, same rule, same UDF, same frozen set, same
report_id) and its runs row carries labels_missing / dedup_horizon_partial when true; lane A is untouched until phase 3.
Rollback: re-register the previous script (`git show <prior>:sql/new_deals_weekly.sql` rendered through scheduled_query.sh).
Run `python3 tests/test_pass3_sql.py`, `DRYRUN=1 sql/apply.sh`, `DRYRUN=1 sql/scheduled_query.sh`.
