# Pass 3 — the raw root: a run_ts-keyed landing table that makes every run reconstructible

Scope: CloudBQ new-deals pipeline, lanes A (Cloud Run function) and C (BigQuery scheduled script). Branch claude/cloud-run-bigquery-pipeline-e94ziy.
Status: **all three phases implemented — phase 1 (136c77e + follow-ups 7370537, recipe `a_raw_root.md`), phase 2 (bf473ba, recipe
`c_raw_batch.md`), phase 3 (this commit, recipe `a_hand_off.md`). What remains is authenticated: the executed checks of §5 and the
first live runs.**
The plan below was revised after an adversarial review (platform critic, semantics critic, cross-examiner; 5 high and 7 medium findings
folded in) and approved by the operator on 2026-10-21. Line references point at the code as it stood before phase 1 (fb9ee7d) where a
section explains a defect, and at the current files where it describes the implementation.

## Decisions taken (operator, 2026-10-21)

| | Decision | Consequence |
|---|---|---|
| D1 | **(a) confirmed** — from phase 3 a dry run lands its raw slice with `mode = 'dry'`, renders the payload from the table function, writes one `new_deals_runs` row (`dry_run = TRUE`, `rows_written = 0`), no history slice, no MERGE, no state | the convention becomes "writes nothing to the sink or the state"; phase 1 keeps today's dry semantics (no landing) |
| D2 | **as recommended** — the API extractor (lane A) is the root writer and stays: HubSpot's API is what the write-back needs; lane C (BigQuery) becomes the executor of the main transformation (the single SQL implementation of phase 2) and remains a fallback caller with `advance_state = TRUE` on `NEW_DEALS_<entity>_C` | the two state rows remain by design; the procedure's lease check keeps a fallback run from colliding with a live lane-A run |
| D3 | **as recommended** — lane C's duplicate rule over the root for both lanes; one-time 90-day backfill at cut-over (`sql/backfill_raw.sh`, orchestrator `backfill`) | `duplicate_*` are not frozen; the string changes on the next re-observation |
| D4 | **as recommended** — the procedure writes the runs row; the function amends it only on delivery failure; the payload is rendered from the tables (phase 3) | `docs/execution_surfaces.yaml` L13 updated in phase 3 |
| D5 | **as recommended** — `data_gaps ARRAY<STRING>` on `new_deals_runs`, column in phase 1, filled from phase 1 where the function or the script already knows the gap | vocabulary: sync_stale, labels_missing, dedup_horizon_partial, dedup_scope_batch_only, raw_landing_failed, raw_slice_replaced, raw_backfilled_from_current_sync, source_detail_unavailable, event_no_window — emitted in phase 1: event_no_window, dedup_scope_batch_only, raw_landing_failed, raw_slice_replaced (A); sync_stale, source_detail_unavailable, raw_backfilled_from_current_sync, raw_slice_replaced, labels_missing, raw_landing_failed (C); dedup_horizon_partial is decided by the phase-2 procedure |
| D6 | **n8n B2 retired** (with D4, phase 3); B1 (delivery tail) unchanged | footprint listed in §4 D6 |

## Phase 1 as implemented (what differs from the plan text below, and why)

- `labels_raw` gained `fetched_at`: the load-first-then-delete-older order needs it for every table it protects.
- Lane C lands in the same order as lane A (INSERT first, then `DELETE … AND fetched_at < v_landed_at`), not DELETE-then-INSERT as §2
  first wrote: a failure between the two statements must never leave an empty slice.
- `fetched_at` keeps microseconds in both lanes so "older than" is strict between two landings of one key.
- The landing SQL is one file, `sql/land_raw.sql`, spliced into `sql/new_deals_weekly.sql` at `-- @include land_raw.sql` by
  `sql/scheduled_query.sh` (sed `r`) and reused by `sql/backfill_raw.sh`; `scheduled_query.sh` now requires `SYNC_DEALS_TABLE` in `.env`.
- The lane-C runs row always names `source_detail_unavailable` (hs_object_source_detail_1 is not landed until the first transfer
  confirms the column) and names `raw_backfilled_from_current_sync` when the transfer's run_time is older than an hour; the ABORTED
  row names `sync_stale`.
- Lane A names `event_no_window` on event runs and `dedup_scope_batch_only` when the warehouse twin map is empty (recent_names failed
  or the warehouse is empty); `raw_landing_failed` when either landing raised — the run continues (phase-1 shadow).
- Lane A names `raw_slice_replaced` when its delete-older removed rows of the same key (the predecessor is then recoverable by time
  travel only); lane C does the same through `@@row_count` in `sql/land_raw.sql`, and names `labels_missing` when it landed no label.
- Review follow-ups (semantics critic, 2026-10-21): the four landing jobs are time-boxed (`LAND_TIMEOUT_S`, default 90 s) so a slow
  landing becomes `raw_landing_failed` inside the 540 s request instead of a killed request with the lease left set; an event
  landing scopes its delete-older to its own deal (two events of one entity in the same second share the slice key); `write_run()`
  retries without `data_gaps` and logs at ERROR when the table predates `deploy.sh tables`, so the audit row is never lost;
  `deploy.sh deploy` applies `tables` first.
- Review follow-ups (platform critic, 2026-10-21): lane C's landing is wrapped in a plain `BEGIN … EXCEPTION WHEN ERROR` block so a
  landing error names `raw_landing_failed` instead of killing the run before its transaction (the shadow contract now holds for both
  lanes); `in_scope` is `IFNULL(… IN UNNEST(…), FALSE)` (IN is NULL for a NULL pipeline, the column is NOT NULL); `TO_JSON(…,
  stringify_wide_numbers => TRUE)` so a NUMERIC the JSON cannot hold losslessly lands as a string instead of throwing; owners with a
  NULL id are skipped; an empty labels landing names `labels_missing`; `scheduled_query.sh` refuses to register a script in which the
  landing was not spliced and, on the live path, a dataset where `deploy.sh tables` has not run; `DRYRUN=1` on both scripts fails on
  a real `bq --dry_run` error and only tolerates missing credentials.
- Offline proofs: `tests/test_main_offline.py` (18 tests, 11 for the root; the clean run's `data_gaps = []` holds once the warehouse
  has name_key rows — on an empty warehouse the first run names `dedup_scope_batch_only`).

Acceptance after the first live run (SQL, lane A and lane C):

```sql
-- every history row has its raw row (expected: 0)
SELECT COUNT(*) FROM `${PROJECT}.${DATASET}.new_deals_history` h
LEFT JOIN `${PROJECT}.${DATASET}.deals_raw` r USING (run_ts, entity, orchestrator, deal_id)
WHERE r.deal_id IS NULL AND h.run_ts >= TIMESTAMP '<cut-over run_ts>';
-- the JSON carries the property names (expected: 0 for every orchestrator)
SELECT orchestrator, COUNTIF(JSON_VALUE(properties, '$.pipeline') IS NULL) FROM `${PROJECT}.${DATASET}.deals_raw` GROUP BY 1;
-- raw slices with no OK runs row: expected = failed or undelivered runs only (orphan slices are kept by design); the backfill slices
-- have no runs row by design, hence the orchestrator filter
SELECT r.run_ts, r.entity, r.orchestrator, COUNT(*) n, ANY_VALUE(u.status) status
FROM `${PROJECT}.${DATASET}.deals_raw` r LEFT JOIN `${PROJECT}.${DATASET}.new_deals_runs` u USING (run_ts, entity, orchestrator)
WHERE r.orchestrator != 'backfill'
GROUP BY 1, 2, 3 HAVING status IS NULL OR status != 'OK';
-- what each run could not read or compute
SELECT run_ts, entity, orchestrator, status, data_gaps FROM `${PROJECT}.${DATASET}.new_deals_runs` ORDER BY run_ts DESC LIMIT 20;
```

## Phase 2 as implemented

- `sql/deals_landed_v1.sql`: the VIEW `deals_landed_v1` (S2) and the TABLE FUNCTION `new_deals_batch_rows(run_ts, entity, orchestrator,
  window_start)` (S7). The fourth parameter is new against §3: lane C's 14-day lookback is a run parameter (recorded as
  `new_deals_runs.query_start`), so the pure batch takes it explicitly; lane A passes its query_start too (a no-op bound, since the
  search applied it) and a debugger passes NULL or the value from the runs row. `name_key` is computed in the view, once.
- `sql/new_deals_batch.sql`: the PROCEDURE `new_deals_batch` (S8) with an eleventh parameter, `gaps ARRAY<STRING>`, the caller's
  data_gaps so far; the procedure adds `labels_missing` (if not already named) and `dedup_horizon_partial`. An event run's history
  DELETE is scoped to the batch's own deals (two events of one entity in the same second share the key). `CREATE OR REPLACE TEMP TABLE`
  so two CALLs in one script never collide.
- `sql/new_deals_weekly.sql`: DECLAREs → freshness guard → gaps → landing inside `BEGIN … EXCEPTION` → `SET v_watermark_in` → CALL.
  The script holds no transaction any more; "before `BEGIN TRANSACTION`" in the phase-1 notes above now reads "before the CALL".
- `sql/apply.sh` applies the two new files last; `sql/scheduled_query.sh` is unchanged (it renders and registers whatever the script is).
- Verification, honestly stated (§5): offline, `tests/test_pass3_sql.py` proves structure (view ⇔ PROPS, column order ⇔ new_deals,
  frozen set, no sync view, the contract, the vocabulary, apply order) and `DRYRUN=1 sql/apply.sh` / `DRYRUN=1 sql/scheduled_query.sh`
  prove rendering. A `bq --dry_run` cannot execute a CALL, so the first AUTHENTICATED step is `tests/pass3_batch_vectors.sql` in a dev
  dataset (15 vectors landed, read through the view and the table function, compared, dropped — every row ok = TRUE), then one transfer
  run in the dev dataset compared with the previous script's rows for the same run_time (same deal_ids, same day1_hot_score, same
  duplicate_of).
- Lane A is untouched by phase 2: it still shapes in Python and lands in shadow.
- Review follow-ups (platform critic, 2026-10-21): the table function's window keeps one row per deal (`QUALIFY … ORDER BY fetched_at
  DESC`) — a doubled slice (a delete-older that failed after its INSERT, a paged search repeating a deal) would otherwise abort the
  MERGE ("multiple rows from the source match one row") or insert the deal twice; the procedure's guards are NULL-safe (`NOT IN` and
  `IF` treat NULL as false), it RAISEs when the caller named `raw_landing_failed` and no slice exists (an OK run with 0 rows would
  otherwise advance C's watermark), the handler's ROLLBACK is wrapped so an engine-cancelled transaction cannot hide the FAILED row,
  and `duration_ms` is documented as ending at `BEGIN TRANSACTION` (inside a transaction `CURRENT_TIMESTAMP()` is its start). The two
  lane-C transfer configs are now scheduled per entity and off the hour (SEALSQ 03:53 UTC, ICALPS 04:23 UTC; `scheduled_query.sh`
  refuses a shared minute or an on-the-hour schedule): two scripts in one minute would be cancelled as conflicting transactions, and
  BigQuery may trigger an on-the-hour schedule twice. Pre-existing hazard, surfaced by the review. Unconfirmed until a dev dataset
  runs them: strict-mode resolution of the TEMP table inside the procedure (fallback `OPTIONS(strict_mode=FALSE)`).
- Review follow-ups (semantics critic, 2026-10-21): the window's `[window_start, run_ts)` bound applies only when a window start is
  given — an event passes NULL and keeps a deal created in run_ts's own second (shape() had no createdate predicate in event mode);
  `rows_written` is the MERGE's own `@@row_count` (the older-slice guard may skip rows, so `COUNT(*)` overstated); the
  `dedup_horizon_partial` test reads the window the rule reads and is a heuristic (full when the oldest landed deal of the last 90 days
  is at least 83 days old); the structure tests pin the UDF's 12 arguments positionally against `scoring/hot_score_v1.sql` and every
  element of every gaps literal; `python3 tests/test_pass3_sql.py --write` regenerates the vectors SQL (plain runs only check).
  Known, by design or pre-existing: `probability_pct` rounds half away from zero in SQL and half-to-even in Python on exact binary ties
  (HubSpot probabilities are whole percents); `SAFE_CAST` is stricter than Python's `_num()` (`" 12 "`, `"1_000"`) and the UDF scores a
  malformed closedate as proximity 0 where Python raised — HubSpot never delivers such strings; `name_key` stores `''` where the old
  lane-C script stored NULL (dealname NULL and no customer) — the duplicate guard excludes both; `STRING_AGG` orders twins by createdate
  then deal_id (D3); a deleted HubSpot deal stays a twin candidate for 90 days in the root where the sync's full refresh dropped it.

## Phase 3 as implemented

- `cloud_function_new_deals/main.py`: lease → search → land (fatal now; `raw_landing_failed` named on the FAILED row) → `CALL
  new_deals_batch(@run_ts, @entity, @orchestrator, @mode, FALSE, NULL, @watermark_in, @query_start, @query_end, @started_ms,
  @gaps)` → `write_watermark` (window mode, after the CALL, releases the lease) → payload rendered from the history slice the procedure
  wrote → delivery → on failure `UPDATE new_deals_runs SET status = 'OK_DELIVERY_FAILED'`. On an exception the function writes the
  FAILED row only if the procedure did not (one `SELECT COUNT(*)` on the key), releases the lease, re-raises. Dry (D1): lands with
  `mode = 'dry'`, CALLs with `mode = 'dry'`, no lease, no watermark, no delivery, payload from the table function. Removed:
  `merge_rows()`, `write_history()`, `recent_names()`, the per-run staging table, `dedup_scope_batch_only`. Kept as test oracles:
  `shape()`, `hot_score()`, `name_key()`. New env: `CALL_TIMEOUT_S` (300 s).
- `tests/test_main_offline.py` (20 tests): the FakeBQ answers the CALL (and marks that a runs row exists), serves the history slice and
  the table-function rows from `main.shape()` typed as the client returns them, answers the runs-row read, and can fail the landing,
  the CALL (with or without a row) or the read-back. The oracle is the Python shaper; the SQL batch is
  proved by `tests/test_pass3_sql.py` offline and by `tests/pass3_batch_vectors.sql` once credentials exist.
- n8n B2 retired (D6): `workflows/NEW_DEALS_FULL.json`, `workflows/src/shape_score.js`, `workflows/src/node_code.template.js`,
  `deploy/n8n/scheduler.sh`, `tests/test_n8n_code.py`, `scoring/hot_score_v1.mjs` deleted; `build_workflow.py` builds the delivery and
  error workflows only; `tests/test_hot_score.py` drops the JS parity check; `scoring/README.md` names the UDF as THE implementation.
  B1 (the delivery tail) is unchanged. The discovery report `docs/discovery/scenario_B.md` keeps B2's design for the record, and the
  B cells of `docs/execution_surfaces.yaml` are marked retired rather than rewritten.
- S9 deviation: the payload's rows come from `new_deals_history` (dry: the table function) and its `data_gaps` are the function's own
  list; the procedure's `labels_missing` / `dedup_horizon_partial` are on the runs row only, not in the delivered payload.
- The implemented test names differ from the §5 plan: test_live_lands_before_the_call_and_advances_the_watermark_after_it,
  test_call_carries_the_window_the_gaps_and_advance_state_false, test_dry_lands_calls_with_mode_dry_and_touches_no_sink_or_state,
  test_call_failure_releases_the_lease_and_writes_no_second_failed_row, test_failure_before_the_call_writes_the_failed_row_here,
  test_event_mode_calls_with_mode_event_and_never_touches_state, test_delivery_failure_amends_the_runs_row,
  test_landing_failure_fails_the_run_names_it_and_releases_the_lease, test_labels_only_failure_fails_the_run_after_the_deals_slice_landed.
- `deploy.sh routines` (new; run by `deploy` and `all` before the function deploy) creates the UDF, the view, the table function and the
  procedure without lane C's `SYNC_*` settings — `sql/apply.sh` refuses to run without them (R36) and would otherwise be the only path.
- Review follow-ups (semantics critic, 2026-10-21): the read-back of the rows happens BEFORE the watermark advances, so a transient
  read error keeps the window replayable; a failure after the CALL amends the procedure's OK row to FAILED (a report that was never
  delivered must not read as a clean run) instead of adding none; the payload's `rows_written` and `data_gaps` come from the runs row
  the procedure wrote (its `labels_missing` / `dedup_horizon_partial` join the function's own list); an event reads only its own deal
  and the procedure never replaces another event's runs row (two events in one second share the key); both landing deletes are scoped
  by mode, so a dry landing in the same second never deletes a live slice; the CALL passes literal NULLs for a missing window (never a
  NULL-valued query parameter) and cancels its job on timeout; the budgets fit Cloud Run's 540 s: 4 × LAND_TIMEOUT_S (45) +
  CALL_TIMEOUT_S (240) + 3 delivery tries × 30 s + 20 s = 530 s. The `_jsonable` rendering is pinned by typed fake rows.
- Rollback: the previous commit (the Python path is one commit behind).

Operator sequence for the cut-over: `cloud_function_new_deals/deploy.sh tables` (adds the two tables and the column; safe to re-run),
`sql/apply.sh` (the UDF, the views, the table function, the procedure — the function CALLs the procedure from this deploy on, so apply
BEFORE `deploy.sh deploy`), the vectors check above in a dev dataset, `deploy.sh deploy`, `deploy.sh dry` (now lands + CALLs with mode
dry: one runs row per entity, rows_written 0), `sql/scheduled_query.sh` (re-registers the two scripts: landing + CALL),
`RUN_TS=<cut-over> sql/backfill_raw.sh` (one invocation lands both entities; append ICALPS for one), then the acceptance SQL after the first live run of each lane.

## 0 · The claim being fixed, and why the fix is one table (plus its small companion)

Both lanes reconstruct their OUTPUTS per run: new_deals_runs has one row per run, also on failure (main.py:185-199, :302);
new_deals_history holds one slice per (run_ts, entity, orchestrator), replaced on replay (main.py:176-183; new_deals_weekly.sql:66-68).
Neither persists its INPUTS:

- lane A: `found = hs.search_created(qstart, run_ts)` (main.py:279) is consumed by shape() (:283) and discarded. Six of the eleven
  hot-score inputs are columns of no table (tpm__k_y, services_value_2026, calculation___pipeline_2026__k__, num_contacted_notes,
  notes_last_updated, revenue_state — read at main.py:73-87, absent from bigquery_schema.sql:11-17 and :29-35);
- lane C: deals_synced_v1 is a VIEW (sql/deals_synced_v1.sql:6) over a DTS table that is a full refresh on every run
  (sql/sync_transfer.sh:2-3); the batch is a TEMP table (new_deals_weekly.sql:21);
- the duplicate set survives as a comma-joined string (main.py:236); labels are live-API strings (main.py:266); the delivery payload is
  built from memory (main.py:290-293).

So `day1_hot_score`, `duplicate_of`, the label strings and the delivered report of a past run cannot be recomputed from BigQuery. An
orchestrator sequences nodes; it does not persist the node that is missing. The missing node is the ROOT: a run_ts-keyed copy of what
each run computed from. With it:

1. every downstream stage is SQL over the root (lane C already is that over the sync, new_deals_weekly.sql:21-52);
2. the function stops shaping and scoring; one SQL implementation remains, the other live copies are retired (today four:
   main.py:70-89 + :212-238; scoring/hot_score_v1.sql + the script; workflows/src/shape_score.js injected by workflows/src/build_workflow.py:65;
   scoring/hot_score_v1.mjs); "same arithmetic everywhere" (CONVENTIONS.md) is then one implementation plus the vectors;
3. debugging is `SELECT … FROM deals_raw WHERE run_ts = X`, then a read-only re-run of the pure part with the same run_ts (§3).

One table because the three defects (score, duplicates, labels/payload not reconstructible) have one cause: inputs never landed.
Two tables in practice — deals_raw and labels_raw — because labels come from other endpoints and change independently.

What this plan does NOT claim: that landing makes the first weeks reconstructible (reconstructibility starts at cut-over; §5 has a
one-time backfill for the duplicate horizon only), or that a re-landed slice keeps its predecessor (§1, time travel).

## 1 · Shape of the root

```sql
-- bigquery_schema.sql (additive; every statement IF NOT EXISTS / ADD COLUMN IF NOT EXISTS, the file's convention)
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.deals_raw` (
  run_ts       TIMESTAMP NOT NULL,   -- the run that landed this slice (= history.run_ts, runs.run_ts), second-truncated
  entity       STRING    NOT NULL,   -- SEALSQ | ICALPS
  orchestrator STRING    NOT NULL,   -- cloud-run-function | bigquery-scheduled-query | backfill
  mode         STRING    NOT NULL,   -- window | event | dry
  source       STRING    NOT NULL,   -- hubspot_api | dts_sync
  deal_id      STRING    NOT NULL,
  in_scope     BOOL      NOT NULL,   -- TRUE: the entity's pipelines; FALSE: duplicate candidate from another pipeline ("others")
  createdate   TIMESTAMP,            -- promoted so the window and duplicate predicates are typed columns, not JSON casts
  pipeline_id  STRING,               -- promoted for the entity filter   (no pruning on either: the table is partitioned by run_ts)
  properties   JSON      NOT NULL,   -- the PROPS as the source delivered them; typed once, in the adapter view (§3 S2)
  fetched_at   TIMESTAMP NOT NULL)
PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id, createdate
OPTIONS (partition_expiration_days = 730);     -- same horizon as new_deals_history

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.labels_raw` (
  run_ts TIMESTAMP NOT NULL, entity STRING NOT NULL, orchestrator STRING NOT NULL,
  kind STRING NOT NULL,                -- pipeline | stage | owner
  id STRING NOT NULL, label STRING, fetched_at TIMESTAMP NOT NULL)
PARTITION BY DATE(run_ts) CLUSTER BY kind, id
OPTIONS (partition_expiration_days = 730);

ALTER TABLE `${PROJECT}.${DATASET}.new_deals_runs` ADD COLUMN IF NOT EXISTS data_gaps ARRAY<STRING>;
```

Slice key = (run_ts, entity, orchestrator), as for new_deals_history. Re-landing the same key replaces the slice. Two consequences
stated plainly: (1) the replaced landing is recoverable with `FOR SYSTEM_TIME AS OF` for the dataset's time-travel window only
(7 days by default), after which the replay's inputs are the only inputs — such runs carry `raw_slice_replaced` in data_gaps;
(2) `deploy.sh replay` does NOT replace a slice: it rewinds the watermark and opens a NEW run_ts (deploy.sh:173-179, main.py:257), so it
ADDS a slice; only a manual CALL or a transfer run with a past run_time (sql/scheduled_query.sh:43-45) re-lands an existing key.

Why JSON for the properties rather than typed columns: lane A's values arrive as HubSpot strings, lane C's as the sync's typed values
(numbers, ISO timestamps); the PROPS set changes (28 in code before phase 1, 29 in two docs — PROPS is 29 since phase 1, §3 S2); with JSON a new property
needs no DDL and old slices stay readable; typing happens once, in the adapter view, where deals_synced_v1.sql:7-39 already SAFE_CASTs.
The JSON keys are the HubSpot property names for BOTH sources (§2 lane C lands from the sync TABLE, not from the renamed view).
Rejected: 28 typed columns (every PROPS change is a migration plus a view change; "as delivered" is lost at the first cast).

Size: lane A lands the window (tens of rows a week) plus the out-of-scope candidates; lane C lands its 90-day set (a few hundred rows);
kilobytes per run, megabytes per year. The per-run DELETE+INSERT costs nothing measurable.

## 2 · Who writes the root (per lane) — landing is deliberately NOT transactional with the batch

A failed batch must leave its inputs queryable, and the batch's own transaction cannot nest inside another (BigQuery refuses nested
transactions), so landing is plain DML that runs BEFORE the batch, idempotent through the slice key.

Lane A (main.py), window and event modes, after the lease (main.py:274-277) and the search (:279):
```
found = hs.search_created(qstart, run_ts)                                 # unchanged (event mode: the one GET, :269)
land_raw(client, found, in_scope_ids, entity, run_ts, mode, "hubspot_api")   # NEW
land_labels(client, pl, st, owners, entity, run_ts)                        # NEW (pl, st, owners from :266)
```
- land_raw loads first (load_table_from_json, WRITE_APPEND, the pattern of :182-183) and THEN deletes older rows of the same key
  (`… AND fetched_at < @fetched_at`), so a failure between the two jobs never leaves an empty slice.
- The row's `properties` is the dict `d["properties"]` itself, never `json.dumps(...)`: the client serialises the row and the column
  arrives as an inline JSON object; a pre-serialised string would land as a JSON string scalar and every JSON_VALUE would read NULL.
  Never `insert_rows_json` for deals_raw (a streaming buffer blocks the slice DELETE, the reason recorded at main.py:192).
- `others` (main.py:281) land with in_scope = FALSE.
- Phase 1 (shadow): landing is non-fatal — on error log ERROR, append `raw_landing_failed` to data_gaps, continue — so the shadow
  cannot fail a run that passes today. Phase 3 makes it fatal (no root, no batch).
- Dry runs do not land in phase 1; what dry does from phase 3 on is decision D1.

Lane C (new_deals_weekly.sql → the scheduled caller), after the freshness guard and BEFORE `BEGIN TRANSACTION` (phase 1) /
before the CALL (phase 2), landing FROM THE SYNC TABLE with HubSpot names (not from deals_synced_v1, whose columns are renamed and typed).
The statements live in `sql/land_raw.sql` (spliced at `-- @include land_raw.sql`), INSERT first and DELETE-older second, as lane A:
```sql
INSERT INTO `${PROJECT}.${DATASET}.deals_raw` (run_ts, entity, orchestrator, mode, source, deal_id, in_scope, createdate, pipeline_id, properties, fetched_at)
SELECT v_run_ts, v_entity, v_orchestrator, v_mode, 'dts_sync',
       CAST(hs_object_id AS STRING), CAST(pipeline AS STRING) IN UNNEST(v_pipelines), SAFE_CAST(createdate AS TIMESTAMP), CAST(pipeline AS STRING),
       TO_JSON(STRUCT(dealname, createdate, final_customer, sales_region, pipeline, dealstage, hs_deal_stage_probability, amount,
                      amount_in_home_currency, deal_currency_code, closedate, asp_in_usd_q2_2022_calculation, tpm__k_y, services_value_2026,
                      calculation___pipeline_2026__k__, product_hierarchy, prod___product_name_new_, application, hubspot_owner_id,
                      hs_object_source_label, icalps_dealtype, icalps_stage, icalps_dealstatus, num_contacted_notes, notes_last_updated,
                      revenue_state, hs_created_by_user_id, hs_lastmodifieddate)),
       v_landed_at
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_DEALS_TABLE}`
WHERE hs_object_id IS NOT NULL
  AND SAFE_CAST(createdate AS TIMESTAMP) >= TIMESTAMP_SUB(v_run_ts, INTERVAL 90 DAY) AND SAFE_CAST(createdate AS TIMESTAMP) < v_run_ts
QUALIFY ROW_NUMBER() OVER (PARTITION BY hs_object_id ORDER BY SAFE_CAST(hs_lastmodifieddate AS TIMESTAMP) DESC) = 1;   -- the guard of deal_tiers_apply.sql:27
DELETE FROM `${PROJECT}.${DATASET}.deals_raw` WHERE run_ts = v_run_ts AND entity = v_entity AND orchestrator = v_orchestrator AND fetched_at < v_landed_at;

INSERT INTO `${PROJECT}.${DATASET}.labels_raw` (run_ts, entity, orchestrator, kind, id, label, fetched_at)
SELECT v_run_ts, v_entity, v_orchestrator, 'pipeline', pipeline_id, label, v_landed_at FROM `${PROJECT}.${DATASET}.pipelines_synced_v1`
UNION ALL SELECT v_run_ts, v_entity, v_orchestrator, 'stage', stage_id, label, v_landed_at FROM `${PROJECT}.${DATASET}.pipeline_stages_synced_v1`
UNION ALL SELECT v_run_ts, v_entity, v_orchestrator, 'owner', owner_id, owner_name, v_landed_at FROM `${PROJECT}.${DATASET}.owners_synced_v1`;
DELETE FROM `${PROJECT}.${DATASET}.labels_raw` WHERE run_ts = v_run_ts AND entity = v_entity AND orchestrator = v_orchestrator AND fetched_at < v_landed_at;
```
- hs_object_source_detail_1 is landed only once the first transfer confirms the column exists; until then it is NULL for lane C and
  named in data_gaps.
- The 90-day set is landed, not only the 14-day window, so the duplicate rule (§3 S6) is a pure function of the root.
- A transfer run started with a past run_time reads the sync as of now (full refresh), so the landed slice is "today's sync as of a
  past run_ts": the caller appends `raw_backfilled_from_current_sync` to data_gaps whenever v_run_ts < now − 1 h.

## 3 · The derived nodes — S1 → S9, all SQL over the root

```
S1 root        deals_raw(run_ts, entity, orchestrator), labels_raw(…)      landed as in §2
S2 adapter     VIEW deals_landed_v1                                         one typed column per property (list below); both sources
S3 window      S2 WHERE run_ts = @run_ts AND in_scope                       [watermark − overlap, run_ts) for A; 14-day lookback for C (unchanged)
S4 shaping     S3 ⋈ labels_raw(run_ts)                                      name_key as new_deals_weekly.sql:23; label = COALESCE(label, id)
S5 scoring     S4                                                            hot_score_v1 UDF with run_ts as "now" (:50-52)
S6 duplicates  S2, bounded (below)                                          lane C's rule (self-join, STRING_AGG ORDER BY createdate, :28-31)
S7 batch       TABLE FUNCTION new_deals_batch_rows(run_ts, entity, orchestrator, window_start) = S2…S6 — pure, read-only, callable by anyone
S8 write       PROCEDURE new_deals_batch(…) = INSERT history slice FROM S7 → MERGE new_deals → runs row → state (if asked); one transaction
S9 output      payload = SELECT FROM new_deals_history(run_ts) (as built: runs-row fields are not joined, see "Phase 3 as implemented"); delivery POSTs that
```

S2 — deals_landed_v1 exposes exactly: run_ts, entity, orchestrator, mode, source, in_scope, fetched_at, deal_id, createdate, pipeline_id
and the typed properties dealname, final_customer, sales_region, dealstage_id, stage_probability, amount, amount_kusd, currency,
closedate, asp_in_usd_q2_2022_calculation, tpm__k_y, services_value_2026, calculation___pipeline_2026__k__, product_hierarchy, product,
application, owner_id, source_label, source_detail, icalps_dealtype, icalps_stage, icalps_dealstatus, num_contacted_notes,
notes_last_updated, revenue_state, created_by_user_id, lastmodified (NULL for slices landed before PROPS gained hs_lastmodifieddate).
It is NOT "the same shape as deals_synced_v1": icalps_oppocertainty, is_closed, is_closed_won stay on deals_synced_v1 for the tiers pass.
PROPS gains hs_lastmodifieddate (29 — which also resolves the 28/29 doc drift in execution_surfaces.yaml:252 and scenario_B.md).

S6 — duplicates, bounded and ordered without lastmodified (lane-A slices have none before the PROPS change):
```sql
FROM deals_landed_v1
WHERE run_ts <= @run_ts AND createdate >= TIMESTAMP_SUB(@run_ts, INTERVAL 90 DAY) AND createdate < @run_ts   -- every entity, every orchestrator, in_scope not filtered
QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY run_ts DESC, fetched_at DESC) = 1
```
A one-time backfill (§5, phase 1) lands the 90-day set once per entity with orchestrator = 'backfill' at the cut-over run_ts, so S6
sees today's horizon from day one; until MIN(createdate) in deals_raw is older than 90 days, runs carry `dedup_horizon_partial`.

S7 — the pure part is a TABLE FUNCTION, so dry runs and debugging never write:
`SELECT * FROM new_deals_batch_rows(@run_ts, 'SEALSQ', 'cloud-run-function')` returns the shaped, scored, de-duplicated batch for X.

S8 — the procedure and its contract (every ambiguity from the review resolved here):
```
new_deals_batch(run_ts TIMESTAMP, entity STRING, orchestrator STRING, mode STRING,            -- window | event | dry
                advance_state BOOL, state_report_id STRING,                                   -- who owns report_state, if anyone
                watermark_in TIMESTAMP, query_start TIMESTAMP, query_end TIMESTAMP, started_ms INT64,   -- the runs-row window fields
                gaps ARRAY<STRING>)                                                                   -- the caller's data_gaps so far
```
- reads deals_landed_v1 and labels_raw ONLY — never deals_synced_v1 / owners_synced_v1 / pipelines_synced_v1 / pipeline_stages_synced_v1,
  so the function SA needs no grant on the sync dataset (deploy.sh:75-76 grants ${DATASET} only); a phase-2 check greps `_synced_v1`
  out of the body;
- one transaction: INSERT history slice (DELETE slice first) → MERGE new_deals with the frozen four unchanged (main.py:157;
  new_deals_weekly.sql:54) and the guard `WHEN MATCHED AND s.last_seen_run >= t.last_seen_run THEN UPDATE` so an older slice can never
  overwrite a newer observation → runs row with the passed window fields, status OK, data_gaps → state;
- state: when advance_state is TRUE, MERGE report_state for state_report_id with `watermark = GREATEST(t.watermark, s.watermark)` (a
  replayed run_time can never rewind) after checking `lock_until` of the entity's A row is not live (RAISE if a lane-A run holds the
  lease); when FALSE (lane A, event, dry) the procedure touches no state;
- RAISEs happen before BEGIN TRANSACTION or inside `EXCEPTION WHEN ERROR THEN ROLLBACK TRANSACTION; <runs row FAILED>; RAISE` so a
  failed run keeps its audit row, as today (new_deals_weekly.sql:14-16);
- mode = 'dry': no history slice, no MERGE, no state; one runs row with dry_run = TRUE, rows_written = 0 (deploy.sh:150 stays green);
- a caller never wraps CALL in a transaction of its own.

Callers:
- lane C scheduled query: landing (§2), then
  `CALL `${PROJECT}.${DATASET}.new_deals_batch`(v_run_ts, v_entity, 'bigquery-scheduled-query', 'window', TRUE, 'NEW_DEALS_${ENTITY}_C', v_watermark_in, <run_ts − 14 d>, v_run_ts, <elapsed ms>, v_gaps)`;
- lane A function: lease → search → land → `CALL … (run_ts, entity, 'cloud-run-function', mode, FALSE, NULL, watermark_in, qstart, run_ts, started_ms, gaps)`
  → write_watermark (main.py:154-157 today, :148-151 at fb9ee7d: advances NEW_DEALS_<entity> and releases the lease in one statement, unchanged) → deliver →
  on delivery failure `UPDATE new_deals_runs SET status = 'OK_DELIVERY_FAILED', error = @err WHERE run_ts = @ts AND entity = @e AND orchestrator = @o`
  (DML on a query-inserted row, safe per main.py:192); on exception: write_run FAILED (main.py:302 at fb9ee7d; as built, only when no runs row exists — runs_row_exists()) and release the lease, as today.
  So the lease and the watermark stay entirely in the function (§7 holds), and the offline order assertion becomes CALL → SET watermark.
- event mode: land the one deal (mode = 'event'), CALL with mode = 'event' and advance_state = FALSE; no state is touched, as today
  (main.py:288 `if not event`).

S9 — the delivery payload is rendered FROM new_deals_history(run_ts) ⋈ new_deals_runs(run_ts) (status and data_gaps included), so a
re-send is the same report; for dry runs it is rendered from S7 directly (no history slice exists).

Debugging a past run X: `SELECT * FROM deals_raw WHERE run_ts = X` (inputs), `SELECT * FROM new_deals_batch_rows(X, …)` (what the
rules make of them now), `SELECT * FROM new_deals_history WHERE run_ts = X` (what was written then). None of the three writes.

## 4 · Decisions for the operator (each changes the shape)

D1 · Dry gate. Today: "computes everything and writes nothing" (CONVENTIONS.md:6-7; tests/test_main_offline.py:96 asserts no loads;
    deploy.sh:150 asserts rows_written == 0; no audit row in dry mode, main.py:294-297, docs/PASS1_SEQUENCE.md:116).
    (a) RECOMMENDED: dry lands its raw slice with mode = 'dry', renders the payload from the table function, writes ONE runs row
        (dry_run = TRUE, rows_written = 0), NO history slice, NO MERGE, NO state. The rehearsal becomes visible in BigQuery; history
        keeps only live observations; new_deals_history needs no new column. Convention becomes "writes nothing to the sink or the
        state"; the offline test asserts "no MERGE, no UPDATE of report_state" instead of "no loads".
    (b) keep today's semantics exactly: dry computes in memory from the unlanded search — the Python shaper survives for dry only,
        which keeps two implementations alive.
D2 · Root writer per entity. RECOMMENDED: the API extractor (lane A) is the root writer; the DTS path remains for the tiers pass and as
    a fallback caller of the same procedure with advance_state = TRUE on NEW_DEALS_<entity>_C — the two state rows therefore remain by
    design (C's window is its lookback, :6, :27; its row is informational, :74), and the procedure's lease check prevents a fallback
    run colliding with a live lane-A run. Alternative: retire the DTS caller and the _C row once lane A lands reliably.
D3 · Duplicate rule and backfill. RECOMMENDED: lane C's rule over the root (S6) for both lanes; duplicate_* are not frozen, so the string
    changes only on the next re-observation; the one-time 90-day backfill from the sync at cut-over (orchestrator = 'backfill').
D4 · Payload from tables and the runs-row ownership above (the procedure writes the row; the function only amends it on delivery failure).
    RECOMMENDED: yes, phase 3; docs/execution_surfaces.yaml L13 updated.
D5 · data_gaps vocabulary: sync_stale, labels_missing, dedup_horizon_partial, dedup_scope_batch_only, raw_landing_failed,
    raw_slice_replaced, raw_backfilled_from_current_sync, source_detail_unavailable, event_no_window. RECOMMENDED: column in phase 1,
    filled from phase 1 where the function or the script already knows the gap (done: write_run() passes it as an ArrayQueryParameter,
    the lane-C script carries v_gaps); labels_missing and dedup_horizon_partial from the phase-2 procedure.
D6 · n8n B2 retirement (NEW — it was hidden in phase 3). Footprint: workflows/NEW_DEALS_FULL.json, workflows/src/shape_score.js +
    node_code.template.js, build_workflow.py build_full(), tests/test_n8n_code.py::test_code_node_matches_python_shape,
    docs/SCENARIOS.md §B and its recommendation, docs/PASS1_SEQUENCE.md "why no second loader", README.md:9, docs/EXECUTION_SURFACES.md,
    the B cells of docs/execution_surfaces.yaml, docs/architecture.yaml nodes. B1 (NEW_DEALS_DELIVERY.json: webhook → rows → XLSX →
    email) is unchanged and needs no BigQuery credential: the function renders the payload from the tables and POSTs it as today.
    scoring/hot_score_v1.mjs: retire with B2 (the write-back job reads the SQL view, not the .mjs — scoring/README.md:6 is drift);
    hot_score_vectors.json stays as the UDF's oracle. RECOMMENDED: yes, with D4.

## 5 · Phases (one recipe, one commit each; the loop of UNIVERSAL_WORKFLOW.md applies; rollback named per phase)

Phase 1 — the root, in shadow. IMPLEMENTED (recipe a_raw_root.md; see "Phase 1 as implemented" above).
  bigquery_schema.sql (+ deals_raw, labels_raw, data_gaps); PROPS + hs_lastmodifieddate; main.py land_raw/land_labels after the search,
  non-fatal, not in dry mode; sql/land_raw.sql spliced into new_deals_weekly.sql before BEGIN TRANSACTION; sql/backfill_raw.sh (the
  lane-C landing per entity with orchestrator = 'backfill'); deploy.sh tables renders the same file.
  Behaviour change: a live run now writes two more tables; nothing else. Rollback: remove the two calls and the `-- @include` line.
  Tests (offline, tests/test_main_offline.py): landing precedes shaping and lands the whole search; load first then delete-older;
  properties is the dict; dry does not land; landing failure non-fatal and named; clean run's data_gaps = [] (warehouse twins read);
  event mode lands one deal; plus the review follow-ups (strict replacement, labels-only failure, time-box, un-migrated runs table).
  Acceptance (SQL, after the first live run): the four probes above.
Phase 2 — the single implementation (lane C changes here). IMPLEMENTED (recipe c_raw_batch.md; see "Phase 2 as implemented" above).
  deals_landed_v1 (S2); new_deals_batch_rows (S7); new_deals_batch (S8) with the contract above; scheduled_query.sh registers the
  landing + CALL script; DRYRUN=1 validates what a dry run can validate (below); tests/pass3_batch_vectors.sql is the executed check. Rollback: re-register the previous script
  (bq update --params with the prior commit's rendering).
  Verification, honestly stated: a bq --dry_run of a CALL proves existence and signature only; a dry run stops at the first IF and
  cannot dry-run CREATE TEMP TABLE, and today's `DRYRUN=1 sql/scheduled_query.sh` therefore validates only the DECLAREs and the guard
  SET (new_deals_weekly.sql:4-12). So: (1) offline, syntax only — render the procedure body as a plain script with DECLAREs in place
  of parameters, the IF blocks stripped and the TEMP table rewritten as a WITH, and dry-run that; dry-run `CREATE OR REPLACE VIEW
  deals_landed_v1` and the table function as their own statements; (2) EXECUTED, in a dev dataset (DATASET=hubspot_dev, the rehearsal
  path scenario_C.md already names): load the 15 vectors of tests/hot_score_vectors.json as a deals_raw slice (synthetic deal_id = case
  id, createdate = run_ts − 1 day), SELECT from new_deals_batch_rows, compare day1_hot_score / day1_hot_flag to the expected values —
  the first authenticated step of phase 2, not an offline one; (3) parity for one lane-C run_ts: deals_landed_v1 vs deals_synced_v1.
Phase 3 — the hand-off (lane A changes here). IMPLEMENTED (recipe a_hand_off.md; see "Phase 3 as implemented" above).
  main.py CALLs the procedure after landing (landing fatal from now on); shape()/hot_score() become test oracles
  (tests/test_hot_score.py keeps main.py as the vector source); per-run staging and recent_names() removed; dry per D1; payload per D4;
  B2 per D6; docs: PASS3 sequence page, execution_surfaces.yaml rows (L4 extraction = the root; L13 audit = root + history + runs), the
  lane matrix re-verified, architecture nodes, tree, ledger.
  Tests: delete test_live_uses_per_run_staging_and_frozen_update_list and test_code_node_matches_python_shape; add
  test_landing_precedes_call, test_call_args (run_ts, entity, orchestrator, mode, advance_state = FALSE, window fields),
  test_watermark_after_call_and_lease_released, test_dry_lands_and_calls_with_mode_dry_no_watermark,
  test_failed_call_releases_lease_and_writes_failed_row, test_event_mode_calls_without_state; the FakeBQ gains a CALL branch.
  Rollback: the previous commit (the Python path is one commit behind).

## 6 · Permissions and platform checks (verified claims, and what the first authenticated run must confirm)

- roles/bigquery.dataEditor on the dataset (deploy.sh:76) includes bigquery.routines.*; with roles/bigquery.jobUser (deploy.sh:57;
  scheduled_query.sh:20) both SAs can CREATE and CALL the procedure and the table function. The function SA gets no new grant because
  the procedure never reads the sync dataset.
- JSON type, TO_JSON, JSON_VALUE, table functions and procedures with transactions are GA; DML and CREATE TEMP TABLE are allowed inside
  BEGIN…COMMIT, permanent DDL is not (scenario_C.md E15/G13); transactions cannot be nested; conflicting transactions are cancelled
  (hence the lease check in S8 for advance_state callers).
- The DuckDB harness (tests/test_hot_score_sql_duckdb.py:31-36) renders only the UDF body; it does not render views, table functions
  or the procedure. If it is extended to the adapter, BigQuery JSON_VALUE maps to DuckDB json_extract_string (DuckDB's json_value
  keeps the outer quotes).
- main.py's write helper was scalar-only (main.py:196 at fb9ee7d); phase 1 builds an ArrayQueryParameter for data_gaps in write_run().

## 7 · What stays exactly as it is

deploy.sh (identity, tables, secret, deploy, invoker, gates, probes), the lease (main.py:137-146 at fb9ee7d), the watermark-after-MERGE rule and
write_watermark (:148-151), the frozen four columns, the freshness guard, the n8n B1 delivery tail, the tiers pass and its views, the
hot-score constants and vectors.
