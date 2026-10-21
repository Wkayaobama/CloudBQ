# Recipe — pass 3 phase 1: the raw root, in shadow (deals_raw, labels_raw, data_gaps; landing in both lanes; backfill)

/add cloud_function_new_deals/bigquery_schema.sql cloud_function_new_deals/main.py cloud_function_new_deals/deploy.sh sql/land_raw.sql sql/new_deals_weekly.sql sql/scheduled_query.sh sql/backfill_raw.sh tests/test_main_offline.py docs/PASS3_RAW_ROOT.md
/read-only docs/PASS3_RAW_ROOT.md CONVENTIONS.md sql/deals_synced_v1.sql sql/deal_tiers_apply.sql

Both lanes reconstruct their outputs per run (new_deals_runs, new_deals_history) but never persist their inputs: the HubSpot search
result is consumed by shape() and discarded; lane C computes a TEMP table from a view over a full-refresh sync. Land the inputs —
the root every later stage is SQL over — without changing what any run computes or writes today (phase 1 = shadow).

1. bigquery_schema.sql (additive only): `deals_raw` (run_ts, entity, orchestrator, mode, source, deal_id, in_scope, createdate,
   pipeline_id, properties JSON, fetched_at; PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id, createdate; 730-day expiry),
   `labels_raw` (run_ts, entity, orchestrator, kind, id, label, fetched_at), and `ALTER TABLE new_deals_runs ADD COLUMN IF NOT EXISTS
   data_gaps ARRAY<STRING>`. Slice key = (run_ts, entity, orchestrator), as new_deals_history. deploy.sh `tables` renders the same file.
2. main.py: PROPS gains hs_lastmodifieddate (29). land_raw() lands EVERY deal the search returned (in_scope FALSE for the duplicate
   candidates) and land_labels() the pipeline/stage/owner maps, after the search and BEFORE shape(): load_table_from_json WRITE_APPEND
   first, THEN `DELETE … WHERE run_ts = @ts AND entity = @e AND orchestrator = @o AND fetched_at < @f` — never DELETE first (a failure
   between the two must not leave an empty slice), never a streaming insert (a buffer blocks the DELETE), never json.dumps() the
   properties (a string lands as a JSON scalar and JSON_VALUE reads NULL). Non-fatal: on error log ERROR, append `raw_landing_failed`
   to data_gaps, continue. Dry runs do not land. write_run() takes the gaps list as an ArrayQueryParameter. Event mode lands its one
   deal with mode = 'event' and names `event_no_window`; an empty warehouse twin map names `dedup_scope_batch_only`.
3. sql/land_raw.sql: the lane-C landing from the SYNC TABLE (HubSpot property names, TO_JSON(STRUCT(...)) of the same PROPS; the
   90-day set, one row per hs_object_id by hs_lastmodifieddate DESC as deal_tiers_apply.sql) and the labels from the three synced
   views; same load-then-delete-older order; plain DML outside any transaction (it cannot nest). Spliced into new_deals_weekly.sql at
   the marker `-- @include land_raw.sql` by scheduled_query.sh (sed `r`), after the freshness guard and before BEGIN TRANSACTION;
   the runs row carries data_gaps (['sync_stale'] on the ABORTED row; 'source_detail_unavailable' always; 'raw_backfilled_from_current_sync'
   when run_time is older than an hour). scheduled_query.sh now requires SYNC_DEALS_TABLE.
4. sql/backfill_raw.sh: the one-time 90-day landing per entity with orchestrator = 'backfill' at the cut-over run_ts (RUN_TS env),
   DRYRUN=1 renders and bq --dry_run's; prints the probe.
5. tests/test_main_offline.py: FakeBQ reads the raw tables' columns from the DDL, extracts array parameters, keeps one ordered call list
   and can fail the landing. Prove: landing precedes shaping and lands the whole search (in_scope per deal, DDL columns exactly);
   load first then delete-older with the same fetched_at; properties is the dict; dry does not land; a landing failure is non-fatal and
   named; the clean run's data_gaps is []; event mode lands one deal with mode = 'event'.
6. docs/PASS3_RAW_ROOT.md: the plan with the operator's decisions and the phase-1 acceptance SQL; architecture nodes; R54 and the L4/L13
   cells of docs/execution_surfaces.yaml; README; the timeline.

Behaviour change of a live run: two more tables are written and new_deals_runs gains an array column. Nothing else. Rollback: remove
the two calls in main.py and the `-- @include` line. Run `python3 tests/test_main_offline.py`, `bash -n` on every script,
`DRYRUN=1 PROJECT=ci-project ./cloud_function_new_deals/deploy.sh all` and the weekly/backfill renders.
