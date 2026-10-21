# Recipe — pass 3 phase 3: the hand-off (the function lands and CALLs; dry per D1; payload from the tables; n8n B2 retired)

/add cloud_function_new_deals/main.py tests/test_main_offline.py workflows/src/build_workflow.py tests/test_hot_score.py scoring/README.md deploy/n8n/import_workflows.sh deploy/n8n/secrets.sh CONVENTIONS.md docs/SCENARIOS.md docs/PASS1_SEQUENCE.md cloud_function_new_deals/README.md docs/PASS3_RAW_ROOT.md
/read-only sql/new_deals_batch.sql sql/deals_landed_v1.sql sql/land_raw.sql cloud_function_new_deals/bigquery_schema.sql

Phase 2 made the batch one SQL implementation (sql/new_deals_batch.sql over the root) and lane C calls it. Hand lane A over: the
function extracts and lands; BigQuery computes. Retire every other copy of the arithmetic.

1. main.py request path: lease → search → land the whole result (deals_raw / labels_raw; a landing failure now FAILS the run and is
   named raw_landing_failed) → `CALL new_deals_batch(@run_ts, @entity, @orchestrator, @mode, FALSE, NULL, @watermark_in, @query_start,
   @query_end, @started_ms, @gaps)` (advance_state FALSE: the lease and NEW_DEALS_<entity> stay here; literal NULLs for a missing
   window; the job is cancelled on timeout) → read the rows back from the history slice and rows_written / data_gaps from the runs row
   (dry: from the table function; an event: its own deal only) → write_watermark (window mode, after the read-back, releases the lease)
   → delivery → on failure amend the runs row to OK_DELIVERY_FAILED. On an exception: amend the procedure's OK row to FAILED if it
   exists, else write the FAILED row here; release the lease; re-raise. Budgets: LAND_TIMEOUT_S 45 × 4 + CALL_TIMEOUT_S 240 + delivery
   3 × 30 + 20 < 540 s. Landing deletes are scoped by mode; the procedure never replaces another event's runs row. Dry (D1): land with mode = 'dry', CALL with mode = 'dry', no lease,
   no watermark, no delivery, rows_written 0. Remove merge_rows(), write_history(), recent_names(), the per-run staging table and
   dedup_scope_batch_only; keep shape() / hot_score() / name_key() as test oracles. deploy.sh gains `routines` (the UDF, the view, the
   table function, the procedure — no SYNC_* needed), run by `deploy` and `all` before the function deploy.
2. tests/test_main_offline.py: FakeBQ gains a CALL branch (marks that a runs row exists; fail_call), returns the history slice / the
   table-function rows from main.shape() (the oracle), answers the runs-row COUNT. Prove: contract == schema; dry lands with mode dry,
   CALLs with mode dry, no sink/state/lease/own row, payload from the table function; live lands BEFORE the CALL and advances the
   watermark AFTER it, no MERGE, no staging, payload from history; the CALL's parameters (window as timestamps, started_ms, gaps as an
   ArrayQueryParameter, FALSE, NULL); landing failure fatal + named + lease released; CALL failure → no second FAILED row + lease
   released; failure before the CALL → FAILED row here; 409; event mode CALLs with mode event and touches no state; delivery failure
   amends the runs row after the watermark; the phase-1 landing invariants; landing and CALL time-boxed; the FAILED row survives an
   un-migrated runs table; every table main.py names is created by the DDL or a routine.
3. Retire n8n B2 (D6): delete workflows/NEW_DEALS_FULL.json, workflows/src/shape_score.js, workflows/src/node_code.template.js,
   deploy/n8n/scheduler.sh, tests/test_n8n_code.py, scoring/hot_score_v1.mjs; build_workflow.py builds DELIVERY + ERRORS only;
   tests/test_hot_score.py drops the JS parity check; import_workflows.sh imports the two; scoring/README.md: two runtimes, the UDF is
   THE implementation, Python the oracle.
4. Docs: CONVENTIONS ("one implementation since pass 3"; "inputs land before anything is computed"), SCENARIOS §B, PASS1 "why no
   second loader", the function README, PASS3 "Phase 3 as implemented", the A and B cells of execution_surfaces.yaml, architecture
   nodes (removed files out, test node updated), README table row B, timeline.

Behaviour change of a live lane-A run: the same rows reach the same tables through the procedure; the lease, the watermark rule, the
frozen four and the delivery tail are unchanged; data_gaps no longer carries dedup_scope_batch_only (the duplicate horizon is the
root). Rollback: the previous commit (the Python path is one commit behind). Run `python3 tests/test_main_offline.py`,
`python3 -m pytest tests -q`, `python3 workflows/src/build_workflow.py --check`, `DRYRUN=1 PROJECT=ci-project ./cloud_function_new_deals/deploy.sh all`.
