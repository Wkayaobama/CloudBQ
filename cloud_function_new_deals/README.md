# New-deals layer — createdate-driven Cloud Run function

**What it adds.** The stage/probability reports (top-5 bands, hot-deal score) cannot see a deal for weeks after creation: it enters at
Identified/Qualified with thin data. This layer reports every deal **created since the last successful run**, per entity, regardless of stage,
with its day-1 hot score and a cross-pipeline duplicate flag. Live probe 2026-09-21→10-05: 12 new deals, incl. *Lattice Keystone C0 ASIC*
(16,002 kUSD, Qualified 20%, day-1 score 81) entered twice (SealSQ Hardware + Icalps_hardware, 3 minutes apart, same owner).

**Idempotency (why it is safe to re-run).**
- `createdate` is immutable → the half-open window `[watermark − 5 min, run_ts)` is exact; the 5-minute overlap absorbs clock skew.
- Rows MERGE into `hubspot.new_deals` on `deal_id` → a re-run of the same window writes nothing new.
- The watermark (`hubspot.report_state`, one row per entity) advances **only after** a successful MERGE → a failed run leaves no gap.
- Replay: `UPDATE report_state SET watermark = TIMESTAMP '…' WHERE report_id = 'NEW_DEALS_SEALSQ'`, then trigger.
- First run with no watermark looks back `FIRST_RUN_DAYS` (7).

**Files.** `main.py` (function), `requirements.txt`, `bigquery_schema.sql` (state + sink + `new_deals_runs` + `new_deals_last_7d`
view, rendered with `${PROJECT}`/`${DATASET}`), `deploy.sh` (step runner: `check-env enable-apis iam tables secret deploy invoker | dry |
enable pause run replay probe status logs`; canonical `gcloud run deploy --function`; two Scheduler jobs Mon 07:00 / 07:20 Europe/Zurich
created paused), `.gcloudignore`, `n8n_NewDeals_Delivery.json` (original delivery flow; the hardened copy is `../workflows/NEW_DEALS_DELIVERY.json`).
The sequence with look commands: `../docs/PASS1_SEQUENCE.md`.

**Scheduler retries and concurrency.** `--max-instances 1 --concurrency 1` plus a per-entity lease (`report_state.lock_until`: an
overlapping run gets 409 and writes nothing), per-run staging tables, and the two entities 20 minutes apart. Dry mode reads the watermark
and the warehouse twins exactly like a live run and writes nothing (not even the audit row). `day1_hot_score`/`day1_hot_flag` are written
once and never overwritten by a re-observation or a replay. Every live run appends one row to `new_deals_runs` and its rows to
`new_deals_history`; logs are JSON lines with `severity`.

**Scopes for the private app.** `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read`.

**Two trigger modes.**
1. Scheduled window (default): Cloud Scheduler → `GET …?entity=SEALSQ` and `…?entity=ICALPS`. Weekly matches the other reports; daily works too (watermark adapts).
2. Event (code path only, **not deployed**): a HubSpot workflow "deal created" → webhook → `POST {"objectId": "{{deal id}}", "mode": "event", "entity": "SEALSQ"}`.
   Writes the single deal without touching the watermark. A HubSpot webhook cannot present a Google OIDC token to a private service, so this
   needs a relay (scenario B) before it can be used; the weekly window run covers every deal regardless.

**Payload contract (also POSTed to the delivery webhook, with `X-Delivery-Token` when `DELIVERY_WEBHOOK_TOKEN` is set).**
`report_id, run_timestamp, orchestrator, dry_run, window{mode, watermark_in, query_start, query_end}, row_count, rows_written, duplicate_suspects, day1_hot[], currency_note, rows[]`
Row columns: `entity, deal_id, dealname, final_customer, owner, sales_region, pipeline, stage, probability_pct, amount, currency, amount_kusd,
closedate, arr_ky, product_family, product, application, icalps_dealtype, icalps_stage, source (CRM_UI | INTEGRATION…), createdate,
day1_hot_score, day1_hot_flag, duplicate_suspect, duplicate_of, deal_url`. Amounts: SEALSQ `amount_kusd` (USD home currency as stored); ICALPS `amount` in EUR.

**Duplicate rule.** `name_key` = final_customer (else first token of dealname), lower-cased alphanumerics. A deal is a suspect when another deal with
the same key was created in the same window in any pipeline, or exists in `new_deals` within 90 days. It is a flag for review, not an action.

**How it composes.** `new_deals_last_7d` sits next to `sealsq_hot_deals_v1` and `sealsq_top5_weekly_v1` in BigQuery: same dataset, same cadence,
same idempotency rules; Breeze and BI read the views, n8n delivers, Claude iterates.

**Pass 3 phase 1 (the raw root).** A live run first lands the whole search result in `deals_raw` (one row per deal returned, `in_scope`
per deal, the properties as HubSpot delivered them — 29 requested — as JSON) and the pipeline/stage/owner maps in `labels_raw`, keyed by (run_ts, entity, orchestrator) like
`new_deals_history`; a landing failure (or a landing slower than `LAND_TIMEOUT_S`, default 90 s) is logged, named in `new_deals_runs.data_gaps`,
and never fails the run. `deploy.sh deploy` applies `tables` first: it adds the two tables and the `data_gaps` column (every statement
is `IF NOT EXISTS`); a runs table that still lacks the column gets its row without the gaps and an ERROR log.
Design and acceptance SQL: `../docs/PASS3_RAW_ROOT.md`.

**Test before scheduling.** `deploy.sh dry` runs `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?entity=…&dry_run=1"`
for both entities and asserts `rows_written == 0`; `deploy.sh enable` resumes the schedulers only after that. Offline, before any deploy:
`python3 ../tests/test_hot_score.py && python3 ../tests/test_main_offline.py`.
