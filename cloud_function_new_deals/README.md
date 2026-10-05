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

**Files.** `main.py` (function), `requirements.txt`, `bigquery_schema.sql` (state + sink + `new_deals_last_7d` view), `deploy.sh`
(service account, Secret Manager token, tables, gen2 deploy, two Scheduler jobs Mon 07:00 Europe/Zurich), `n8n_NewDeals_Delivery.json`
(webhook → XLSX → email; set its URL as `DELIVERY_WEBHOOK_URL`).

**Scopes for the private app.** `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read`.

**Two trigger modes.**
1. Scheduled window (default): Cloud Scheduler → `GET …?entity=SEALSQ` and `…?entity=ICALPS`. Weekly matches the other reports; daily works too (watermark adapts).
2. Event (optional, near-real-time): a HubSpot workflow "deal created" → webhook action → `POST {"objectId": "{{deal id}}", "mode": "event", "entity": "SEALSQ"}`.
   Writes the single deal into the same table without touching the watermark; the weekly window run still covers it (MERGE dedupes).

**Payload contract (also POSTed to the delivery webhook).**
`report_id, run_timestamp, window{mode, watermark_in, query_start, query_end}, row_count, rows_written, duplicate_suspects, day1_hot[], currency_note, rows[]`
Row columns: `entity, deal_id, dealname, final_customer, owner, sales_region, pipeline, stage, probability_pct, amount, currency, amount_kusd,
closedate, arr_ky, product_family, product, application, icalps_dealtype, icalps_stage, source (CRM_UI | INTEGRATION…), createdate,
day1_hot_score, day1_hot_flag, duplicate_suspect, duplicate_of, deal_url`. Amounts: SEALSQ `amount_kusd` (USD home currency as stored); ICALPS `amount` in EUR.

**Duplicate rule.** `name_key` = final_customer (else first token of dealname), lower-cased alphanumerics. A deal is a suspect when another deal with
the same key was created in the same window in any pipeline, or exists in `new_deals` within 90 days. It is a flag for review, not an action.

**How it composes.** `new_deals_last_7d` sits next to `sealsq_hot_deals_v1` and `sealsq_top5_weekly_v1` in BigQuery: same dataset, same cadence,
same idempotency rules; Breeze and BI read the views, n8n delivers, Claude iterates.

**Test before scheduling.**
`curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?entity=SEALSQ&dry_run=1"` → full payload, nothing written.
