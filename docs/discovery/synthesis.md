# CloudBQ — synthesis of the three scenarios into the lane workbook (2026-10-05, commit 9e7e18a)

Deliverables

- `scratchpad/discovery/execution_surfaces.final.yaml` — the complete `docs/execution_surfaces.yaml` (18 layers, 13 steps, 46 remediation rows, 7 equality checks, exact parity vocabulary).
- `scratchpad/discovery/execution_surfaces.final.xlsx` — built with `build_surfaces_xlsx.py --verify`: `verify: OK`; Layers {Parallel 4, Conditional 4, Divergent 10}, Pipeline steps {Parallel 2, Conditional 5, Divergent 6}.

Nothing has run against GCP. Every "verified" cell names an offline test or a `DRYRUN=1` rehearsal that exists in the repo, or says "not yet — first authenticated run".

## The parallel lane (Parallel across A/B/C)

| Layer | Why it is the same on every surface |
|---|---|
| L5 scoring | One constants file (`scoring/hot_score_v1.constants.json`), three ports (`main.py`, `scoring/hot_score_v1.mjs` / `workflows/src/shape_score.js`, `scoring/hot_score_v1.sql`), one vector set (`tests/hot_score_vectors.json/.sql`). `tests/test_hot_score.py`: 15 vectors, JS raw score within 1e-9, flags equal; SQL UDF 0/4,000 mismatches offline (DuckDB), `bq` check pending. |
| L7 MERGE | Same target `hubspot.new_deals`, same key `deal_id`, same frozen set (`deal_id, first_seen_run, day1_hot_score, day1_hot_flag`), same insert. The MERGE source differs (per-run staging / inline JSON / TEMP table) but none is shared or persistent. Proven offline for A (`test_main_offline.py`) and B2 (`test_n8n_code.py`); C's UPDATE list read against the schema. |
| L8 watermark | One row in `hubspot.report_state`, `watermark = run_ts` only after a successful MERGE, never on dry/event/failed runs. C uses key `NEW_DEALS_<entity>_C` so it can coexist with A (C-G4). |
| L13 audit | All three write `new_deals_runs` (orchestrator = cloud-run-function / n8n / bigquery-scheduled-query) and `new_deals_history`; C adds `writeback_log`. One `deploy.sh probe` reads them all. |

This lane is what delivers the idempotent outcome whichever orchestrator runs: a second identical run on any surface changes no counts and no day-1 score (equality check "after a second identical run").

## Why the others are not Parallel

- **Conditional** — L3 (same result only while A and B2 read the same `SCHEDULE_*` from `.env` and C's UTC chain keeps its slack; C-G3 DST drift), L6 (A == B2 row-for-row; C's self-join over the synced table flags twins A never reported, C-G5), L11 (A/B2 rehearse Monday's window with zero writes; C's scheduled script has no compute-only mode — dry run = `bq --dry_run` + a `hubspot_dev` dataset; the job half matches A's flag model), L12 (A/B2 rewind one state row; C re-executes `run_time` slices whose 14-day lookback must cover the gap — same rows, different mechanism, so the rule says Conditional even though the user's seed expected Parallel).
- **Divergent** — L0 deploy unit, L1 identity (A/C keyless, B2 needs an SA key), L2 secrets (one pinned version vs copies inside n8n and the transfer config), L4 extraction (live `createdate` search vs scheduled snapshot + lookback, C-G2), L9 delivery (webhook tail / in-workflow / none), L10 write-back (only C's job), L14 access (IAM-only vs public URL + header secret), L15 concurrency (lease + cap / n8n limit / transaction + idempotent PATCH), L16 observability, L17 cost. Each row names the file that makes them equivalent.

## Recommendation

**A as the production orchestrator, B1 as its delivery tail, C's compute views and write-back job as the Breeze-facing extension. B2 only if the n8n editor must be the operating surface.** In terms of the four jobs:

1. *Arithmetic* — identical everywhere (L5 Parallel); no scenario wins on the score itself. C adds what only BigQuery can do (per-region top-5, window functions) as versioned views over the synced table — keep that.
2. *Idempotent schedule* — A has the strongest guarantee set: exact half-open `createdate` window, lease row (409 on overlap), per-run staging, watermark after MERGE, paused-until-dry Scheduler jobs, keyless identity, `< $1/month`. B2 reaches the same table state but re-implements window/scorer/MERGE/watermark in JSON, has no lease (R46), needs an SA key and a token copy in Cloud SQL, and costs ≈ $9–11/month for the database floor. C's extraction is a daily full-refresh sync with one-cycle lag and no event mode (R32), so it should not own the weekly "new deals" window while A exists.
3. *Write-back* — exists only in C (`writeback/index.mjs`: batch PATCH ×100, 207 parsing, value-idempotent, never NULL, `WRITEBACK_APPROVE` gate) and it reads BigQuery views, so one deployment serves whichever orchestrator filled `new_deals`. Blocked until the write-scoped private app exists (R35).
4. *Audit* — shared tables (L13 Parallel); A and B2 both write them, C adds `writeback_log`. B's n8n execution log and C's transfer-run history are additive, not the record.

B1 (`workflows/NEW_DEALS_DELIVERY.json`, Header Auth, zero-row branch, respond-when-done) is the cheapest way to turn A's payload into XLSX + e-mail; next iteration should deliver from `new_deals_last_7d` so a re-send is the same report from any scenario.

## Open items that gate the first authenticated run

- **R44 (new, blocking for A and B2):** `main.py write_history()` and B2's "History slice" node write `hubspot.new_deals_history`, but `deploy.sh tables` renders only `bigquery_schema.sql`, which does not create that table. Run `sql/apply.sh` (or the rendered `sql/audit_tables.sql`) before `deploy.sh run`; proposed code change (awaiting consent): render `audit_tables.sql` in `deploy.sh tables` or move the DDL into `bigquery_schema.sql`.
- **R45 (new, C):** no script enables `bigquerydatatransfer.googleapis.com`.
- **R46 (new, B2):** B2 never acquires the `lock_until` lease — do not run A and B2 live on the same `report_id` concurrently.
- **R35 (C):** write-scoped private app + one-off property creation (`writeback/bootstrap_property.sh`).
- **R36 (C):** synced table/column names unknown until the first DTS run; `.env SYNC_*` and `sql/deals_synced_v1.sql` absorb them.
- **R41 (A/C):** decide strict vs stricter duplicate rule in C.

Sequence to run next (scenario A, from `cloud_function_new_deals/`): `deploy.sh check-env → enable-apis → iam → tables` + `sql/apply.sh` (R44) `→ secret → deploy → invoker → dry → run SEALSQ → run ICALPS → probe → status → enable`; paste the dated `probe`/`status` output into the Overview verdict and `docs/EXECUTION_SURFACES.md`.

## Open questions carried into the workbook (defaults assumed)

See `StructuredOutput.open_questions`: dataset location (EU), event mode kept but not deployed in A, ICALPS at 07:20, secret pinned, B2 trigger = Scheduler → webhook at minScale 0, no IAP, SMTP credential, DTS connector as the C ingestion route, portal not on Data Hub Enterprise, `hot_score_v1`/`hot_flag_v1` property names, no PATCH for unscored pipelines, C keeps its own `report_state` key, A stays deployed alongside C until C's first run is probed.
