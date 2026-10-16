# Scenario C — Hybrid: BigQuery computes, remote JS writes back, Breeze consumes, Claude iterates

Discovery report (read-only; no repository file was changed). Target repo `/home/user/CloudBQ`, branch
`claude/cloud-run-bigquery-pipeline-e94ziy`. Date 2026-10-05. Author: discovery analyst C.

Companion artefacts (scratchpad, not in a repo):

- `discovery/scenario_C/hot_score_sql_test.py` — the offline parity harness (Python `hot_score()` lifted verbatim from
  `cloud_function_new_deals/main.py:40-68` versus the BigQuery SQL translation, executed in DuckDB 1.5.6 through a
  documented dialect map). Result: **4,000 random deals, 1,330 SEALSQ-scored, 0 mismatches** (score within ±0.05, flag equal).
- `discovery/scenario_C/hot_score_udf.bq.sql` — the BigQuery rendering the harness tested (identical to §2.1 below).
- `discovery/scenario_C/hot_score_udf.duckdb.sql` — the DuckDB rendering (test only).

---

## 0 · Verdict in one paragraph

Scenario C moves the arithmetic of `hot_score()` into a persistent BigQuery SQL UDF over a HubSpot→BigQuery *synced*
deals table, runs the window / MERGE / audit / state-advance as **one scheduled multi-statement script in a transaction**
(something A cannot do, because A's load job and MERGE are two jobs), and puts the only HubSpot *write* in a small
Node 22 Cloud Run **job** that batch-PATCHes `hot_score_v1` / `hot_flag_v1` and skips rows whose value is already in
HubSpot. It is the strongest lane for L5 (scoring), L7/L8 (atomic MERGE + state), L12 (replay = `bq mk --transfer_run`
backfill with the same `@run_time`) and L13 (a partitioned run-history table). It is the weakest lane for L4: **no
ingestion route available to this portal is near-real-time** — the Google connector is a Preview full refresh on a
schedule, HubSpot's own BigQuery sync is a Data Hub Enterprise beta at ≥ 6 h cadence — so A's HubSpot-workflow "event
mode" has no equivalent, and the scheduled query must guard on sync freshness or it will MERGE stale rows. Two things
in the user's job matrix need correcting: HubSQL is *more* limited than stated (no arithmetic at all, private beta), and
"BigQuery sync cannot write to HubSpot" is no longer true if the portal has Data Hub Enterprise (HubSpot's BigQuery
integration syncs BigQuery → HubSpot every 15 minutes, beta). Blocking prerequisite for L10: the private app's scopes in
`README.md:19` are read-only; write-back needs `crm.objects.deals.write` and the one-time property creation needs
`crm.schemas.deals.write`. No `hot_score_v1`-like deal property exists in the portal today (probe below).

---

## 1 · Evidence collected (probes and documents)

| # | Probe / source | What it established |
|---|---|---|
| E1 | HubSpot MCP `discover_hubspot_schema GET_PIPELINES DEAL` (portal 9201667, 2026-10-05) | Pipelines `12096408` SealSQ Hardware, `13772279` SealSQ Services, `705868909` SEALCOIN, `934982230` Quantum & AI, `766126206` Icalps_hardware exist with the stage probabilities 0.1/0.2/0.5/1.0 (SealSQ) and 0.1…1.0 (Icalps). `main.py:31-32` ids are correct. Two further pipelines (`40296576` Wisekey Services + PKI, `875072356` Wise.Sat) are not in `ENTITIES`. |
| E2 | HubSpot MCP `search_properties DEAL ["hot_score","hot_flag","day1_hot","hot_deal","score"]` | No custom hot-score property exists; the nearest is HubSpot's own `hs_deal_score`. `hot_score_v1` / `hot_flag_v1` must be created. |
| E3 | DuckDB parity harness (above) | SQL translation of `hot_score()` is arithmetically equivalent on 4,000 random deals incl. `None`/`""` values, PKI vs non-PKI bands, closedate ≤ 2026 and > 2026, recency bands, non-SEALSQ pipelines → NULL. |
| E4 | [BigQuery Data Transfer Service — Load HubSpot data into BigQuery](https://docs.cloud.google.com/bigquery/docs/hubspot-transfer) (page dated 2026-09-30) | "Preview"; "The HubSpot connector requires a private app access token for authentication"; "With every transfer run, the HubSpot connector transfers **all available data** from HubSpot into BigQuery"; "There is no cost to transfer HubSpot data into BigQuery while this feature is in Preview"; `bq mk --transfer_config --data_source=hubspot --params='{"assets":["Contacts","Deals"],"connector.authentication.oauth.accessToken":"pat_…"}'`; repeat frequency list incl. Custom and On-demand; data types Date/Datetime → TIMESTAMP, Integer → INTEGER, Long → BIGNUMERIC. |
| E5 | [HubSpot KB — Connect HubSpot to Google BigQuery](https://knowledge.hubspot.com/integrations/connect-hubspot-to-google-bigquery) | Beta; "Data Hub Enterprise"; HubSpot → BigQuery "once, every 6 hours, every 12 hours, daily, weekly, or monthly"; **BigQuery → HubSpot "every 15 minutes, every 30 minutes, every hour, …"**; "BigQuery external tables are created in a dedicated dataset … `hubspot_data_set_{hubId}`"; "each object type, event type, or association pair can only be exported in one sync configuration per HubSpot account". |
| E6 | [HubSpot KB — Connect HubSpot and Google BigQuery (legacy)](https://knowledge.hubspot.com/integrations/connect-hubspot-and-google-bigquery) | "Data sync jobs between HubSpot and Google BigQuery start daily at approximately 6:00 AM UTC"; tables `OBJECTS_<object type name>`, Parquet; property history "most recent 20 values" for non-contacts. |
| E7 | [Fivetran — HubSpot update frequency](https://fivetran.com/docs/connectors/applications/hubspot/troubleshooting/kb-hubspot-update-frequency), [Fivetran sync overview](https://fivetran.com/docs/getting-started/syncoverview); [Airbyte HubSpot source](https://docs.airbyte.com/integrations/sources/hubspot) | Fivetran 15-min (Standard) / 1-min (Enterprise) syncs; Airbyte Full Refresh + Incremental (server-side on `hs_lastmodifieddate`). Paid / self-hosted alternatives; not needed for a weekly report. |
| E8 | [HubSpot HubSQL guide (2027-03-beta)](https://developers.hubspot.com/docs/api-reference/2027-03-beta/querying-data/hubsql/guide) | "currently in private beta"; `FROM` single table; "only `LEFT JOIN` is currently supported"; GROUP BY max 2 columns; LIMIT 10,000 (500 aggregate); functions: COUNT/SUM/AVG/MIN/MAX/MEDIAN, `DATE_TRUNC`; "Arithmetic expressions (e.g., `amount * 1.1`) and usage of `CASE`/`WHEN` are not currently supported"; page size max 100. |
| E9 | HubSpot MCP `tool_guidance ["ask_breeze","manage_crm_objects","query_crm_data"]` | `query_crm_data` is HubSQL-shaped (`SELECT … FROM DEAL WHERE …`), `ask_breeze` has no guidance, `manage_crm_objects` guidance says "ALWAYS confirm with the user" before writes — i.e. a human-in-the-loop write, not an automation. |
| E10 | [HubSpot usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines) | Private apps: Free/Starter 100 req/10 s & 250k/day; Professional 190/10 s & 625k/day; Enterprise 190/10 s & 1M/day; add-on 250/10 s + 1M/day (max two); headers `X-HubSpot-RateLimit-Daily`, `-Daily-Remaining`, `-Interval-Milliseconds`, `-Max`, `-Remaining`. Search API: 5 req/s per account, 10,000 results max ([search guide](https://developers.hubspot.com/docs/api-reference/crm/search)). |
| E11 | [Deals batch update v3 reference](https://developers.hubspot.com/docs/api-reference/crm-deals-v3/batch/post-crm-v3-objects-0-3-batch-update); [legacy objects batch update](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/objects/batch/update-objects) | `POST /crm/v3/objects/0-3/batch/update`, inputs `{id, idProperty?, properties}`; scopes `crm.objects.deals.write`; response codes **200 / 207**. The 100-input cap is stated in HubSpot's legacy batch docs and community answers, not on the v3 reference page — see G7 (probe with 101 inputs). |
| E12 | HubSpot community: [Force property update with same value](https://community.hubspot.com/t5/APIs-Integrations/Force-property-update-with-same-value/m-p/342736), [Allow re-enrollment when property value changes](https://community.hubspot.com/t5/HubSpot-Ideas/Allow-Workflow-Re-Enrollment-When-Property-Value-Changes/idc-p/248022) | HubSpot does not record a property-history entry when the value does not change, and workflow re-enrollment needs an actual change — a same-value PATCH is a no-op for history and triggers (basis of the idempotency argument in §3.2). |
| E13 | [Properties API guide](https://developers.hubspot.com/docs/api-reference/crm-properties-v3/guide) | Create property: `groupName, name, label, type, fieldType`; `number` → fieldType `number`; `bool` → fieldType `booleancheckbox`; scope `crm.schemas.deals.write`. |
| E14 | [BigQuery scheduled queries](https://docs.cloud.google.com/bigquery/docs/scheduling-queries) | "The minimum duration between scheduled queries is 5 minutes"; "the scheduled time … is converted from your local time to UTC. UTC is not affected by daylight saving time"; `@run_time` (TIMESTAMP, UTC), `@run_date`; DDL and DML allowed; `--service_account_name`; "Scheduled queries are priced the same as manual BigQuery queries"; backfill `bq mk --transfer_run --start_time … --end_time … resource_name`. |
| E15 | [BigQuery multi-statement transactions](https://docs.cloud.google.com/bigquery/docs/transactions) | `BEGIN TRANSACTION … COMMIT TRANSACTION`; INSERT/UPDATE/DELETE/MERGE/TRUNCATE on multiple tables; CREATE TEMP TABLE allowed; permanent DDL not allowed; snapshot isolation; conflicting mutations on the same table are cancelled. |
| E16 | [BigQuery UDFs](https://docs.cloud.google.com/bigquery/docs/user-defined-functions) | Persistent SQL UDF `CREATE FUNCTION dataset.f(...) RETURNS … AS (…)`; `bigquery.routines.create` to create, `bigquery.routines.get` to call. |
| E17 | [BigQuery time travel](https://docs.cloud.google.com/bigquery/docs/time-travel) | 2–7 day time-travel window; "To preserve table data … longer than the time travel window, use table snapshots." |
| E18 | [Cloud Run — Execute jobs on a schedule](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule); [jobs.run REST](https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs/run); [Cloud Run quotas](https://docs.cloud.google.com/run/quotas) | Scheduler → `POST https://run.googleapis.com/v2/projects/P/locations/R/jobs/J:run` with `--oauth-service-account-email`; SA needs `roles/run.invoker`; `jobs.run` "Triggers creation of a new Execution" and returns an `Operation` (asynchronous); up to 1,000 running job executions per project-region, i.e. overlapping executions of one job are allowed. |
| E19 | [gcloud run jobs deploy](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/deploy); [jobs secrets](https://docs.cloud.google.com/run/docs/configuring/jobs/secrets); [create jobs](https://docs.cloud.google.com/run/docs/create-jobs) | `--source` supported ("If a Dockerfile is present … otherwise … buildpacks"); `--set-secrets ENV=SECRET:VERSION`; "Environment variables are resolved at instance startup time, so … pin the secret to a particular version instead of using `latest`"; `--max-retries` default 3; `--task-timeout` default 10 min, max 168 h. |
| E20 | [MCP Toolbox for BigQuery](https://docs.cloud.google.com/bigquery/docs/pre-built-tools-with-mcp-toolbox) | `toolbox --prebuilt bigquery --stdio` with `BIGQUERY_PROJECT`; tools `execute_sql, get_table_info, list_dataset_ids, list_table_ids, get_dataset_info, search_catalog, ask_data_insights, forecast, analyze_contribution`; ADC. Write-mode / allowed-datasets controls are documented in the Toolbox source configuration (`writeMode: allowed|blocked|protected`, `allowedDatasets`) per third-party summaries; the official page URL could not be fetched from this sandbox — verify with `toolbox --help` (open item). |
| E21 | [Breeze Assistant KB](https://knowledge.hubspot.com/ai/use-breeze-assistant) | Reads CRM data ("Find deals with a close date in August 2026"), creates records on request, "Breeze Assistant content generation is limited to 30 times each minute and 1,000 times each day"; saved prompts exist; **no "scheduled prompts" feature is documented** in the KB pages found (the user's "beta" claim stays unverified). |
| E22 | Pricing: BigQuery on-demand $6.25/TiB after 1 TiB/month free, storage 10 GiB free ([summary](https://www.doit.com/blog/bigquery-cost-optimization)); Cloud Run free tier 180,000 vCPU-s + 360,000 GiB-s/month ([Cloud Run pricing](https://cloud.google.com/run/pricing)); Cloud Scheduler 3 free jobs per billing account, $0.10/job/month after ([Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing)). |

---

## 2 · BigQuery compute

### 2.0 How HubSpot deals reach BigQuery today — four routes

| Route | Status / plan | Cadence | Auth | Shape in BigQuery | Fit for C |
|---|---|---|---|---|---|
| **Google BigQuery Data Transfer Service — HubSpot connector** (E4) | Preview, free while in Preview, any HubSpot plan | Scheduled (repeat frequency incl. Custom / On-demand); **every run transfers all available data** (full refresh) | HubSpot **private app token** (`connector.authentication.oauth.accessToken`), long required-scope list incl. `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read` | Native tables in the target dataset, one per asset (`Deals`, …); HubSpot Date/Datetime → TIMESTAMP, Integer → INTEGER, Long → BIGNUMERIC | **Default choice**: no HubSpot upsell, token already exists in Secret Manager, BigQuery-native tables, backfill on demand. Not incremental, not near-real-time. |
| **HubSpot Data Hub — Google BigQuery integration** (E5) | Beta, **Data Hub Enterprise** | HubSpot → BigQuery once / 6 h / 12 h / daily / weekly / monthly; BigQuery → HubSpot 15 min … monthly | HubSpot-managed service account; IAM role you create | **External tables** in `hubspot_data_set_{hubId}` (legacy: Parquet `OBJECTS_<type>`, property history 20 values) | Best if the portal has Data Hub Enterprise: the reverse sync could replace the JS write-back (§4.3). |
| Fivetran HubSpot connector (E7) | Paid | 15 min (Standard) to 1 min (Enterprise), incremental | OAuth | `hubspot.deal` + `deal_property_history` etc. | Fine, costs money; overkill for weekly. |
| Airbyte HubSpot source (E7) | OSS / Cloud | Scheduled, incremental on `hs_lastmodifieddate` | Private app or OAuth | `deals` with `properties` JSON + `properties_*` columns | Self-hosting burden; not recommended. |

Consequence for the lane: **L4 is Divergent from A.** A queries HubSpot at run time (`search_created`, `main.py:73-83`) with
an exact half-open `createdate` window, and has an event mode. C sees the world as of the last sync. The scheduled query
therefore (a) uses a *lookback* over the synced table rather than a watermark search, (b) must check that the sync is fresh
(G2), and (c) has no event mode — a deal created Monday 06:50 appears in the following week's report unless the sync runs
between creation and 07:00.

### 2.1 `sql/hot_score_udf.sql` — the UDF (tested, E3)

```sql
CREATE OR REPLACE FUNCTION `${PROJECT}.${DATASET}.hot_score_v1`(
  pipeline STRING, asp_in_usd_q2_2022_calculation FLOAT64, tpm__k_y FLOAT64, services_value_2026 FLOAT64,
  product_hierarchy STRING, closedate TIMESTAMP, calculation___pipeline_2026__k__ FLOAT64,
  notes_last_updated TIMESTAMP, hs_deal_stage_probability FLOAT64, num_contacted_notes FLOAT64,
  revenue_state STRING, run_ts TIMESTAMP)
RETURNS STRUCT<score FLOAT64, hot BOOL>
OPTIONS (description = "hot-deal score v1 — same constants as main.py / hot_deals_score.js (fitted 2026-10-01). NULL for non-SEALSQ pipelines.")
AS ((
  WITH c AS (
    SELECT
      -- _num(): NULL/'' → 0 ; the Python `or` chain takes the first non-zero candidate
      COALESCE(NULLIF(IFNULL(asp_in_usd_q2_2022_calculation, 0), 0), NULLIF(IFNULL(tpm__k_y, 0), 0), NULLIF(IFNULL(services_value_2026, 0), 0), 0) AS arr,
      IFNULL(hs_deal_stage_probability, 0) AS stage_prob,
      IFNULL(num_contacted_notes, 0) AS notes_n,
      pipeline = '12096408' AS hw
  ), f AS (
    SELECT
      stage_prob,
      CASE WHEN closedate IS NULL THEN 0.0
           WHEN EXTRACT(YEAR FROM closedate) <= 2026 THEN 1.0
           ELSE GREATEST(0.0, 1 - TIMESTAMP_DIFF(closedate, TIMESTAMP '2026-12-31 00:00:00+00', DAY) / 730) END AS proximity_2026,
      CASE WHEN hw THEN (CASE WHEN IFNULL(calculation___pipeline_2026__k__, 0) = 0 THEN 1.0 ELSE 0.0 END)
           ELSE (CASE WHEN IFNULL(services_value_2026, 0) = 0 THEN 1.0 ELSE 0.0 END) END AS missing_2026_field,
      (CASE pipeline WHEN '12096408' THEN 84 / 730 WHEN '13772279' THEN 51 / 303 END) / (51 / 303) AS pipeline_conversion,
      (CASE WHEN product_hierarchy = 'PKI' THEN CASE WHEN arr < 20 THEN 0.5 WHEN arr <= 50 THEN 1 ELSE 2 END
            ELSE CASE WHEN arr < 100 THEN 0.5 WHEN arr <= 500 THEN 1 WHEN arr <= 1000 THEN 2 ELSE 3 END END) / 3 AS arr_points,
      LN(1 + GREATEST(notes_n, 0)) / LN(1 + 223) AS engagement,
      CASE WHEN notes_last_updated IS NULL THEN 0.0
           WHEN TIMESTAMP_DIFF(run_ts, notes_last_updated, DAY) <= 90 THEN 1.0
           WHEN TIMESTAMP_DIFF(run_ts, notes_last_updated, DAY) <= 180 THEN 0.5 ELSE 0.0 END AS recency,
      CASE WHEN revenue_state IN ('Forecast', 'BIBA') THEN 0.0 ELSE 1.0 END AS not_in_forecast
    FROM c
  ), z AS (
    SELECT 2.0712 * stage_prob + 1.2399 * proximity_2026 + (-0.4136) * missing_2026_field + 1.0918 * pipeline_conversion
         + 4.9843 * arr_points + 1.3018 * engagement + 0.0 * recency + 1.5620 * not_in_forecast + (-6.4788) AS z
    FROM f
  )
  SELECT CASE WHEN pipeline IN ('12096408', '13772279')
              THEN STRUCT(ROUND(100 / (1 + EXP(-z)), 1) AS score, 100 / (1 + EXP(-z)) >= 45.0 AS hot)
              ELSE STRUCT(CAST(NULL AS FLOAT64) AS score, CAST(NULL AS BOOL) AS hot) END
  FROM z
));
```

Translation notes (each is a line of `main.py`):

- `main.py:46` `_num()` → `IFNULL(x, 0)` after the adapter's `SAFE_CAST`; `main.py:52` `a or b or c` → `COALESCE(NULLIF(…,0), …, 0)` (Python `or` skips `0.0`).
- `main.py:53-54` ARR bands → nested `CASE`; `main.py:58` `(d - 2026-12-31).days / 730` → `TIMESTAMP_DIFF(…, DAY) / 730` (both truncate whole days for positive differences; closedates are midnight UTC in HubSpot).
- `main.py:63` `(now - nlu).days` → `TIMESTAMP_DIFF(run_ts, nlu, DAY)`; negative (future) values fall in the `<= 90` branch on both sides.
- `main.py:65` `log1p(n)/log1p(223)` → `LN(1 + GREATEST(n,0)) / LN(224)` (the guard avoids `LN` of a non-positive number, which Python would also reject).
- `main.py:67-68` `round(s, 1)` vs BigQuery `ROUND(s, 1)`: Python rounds half-to-even on the binary float, BigQuery half-away-from-zero; a difference needs an exact `.x5` after the logistic — not observed in 4,000 samples, and the flag uses the unrounded value on both sides.
- `main.py:51` `pipeline not in CR → (None, None)` → the outer `CASE`. SEALCOIN and Quantum & AI are SEALSQ pipelines for the *report* but get **NULL** scores (G6).

Test vectors (run_ts 2026-10-06T05:00:00Z), to pin in `tests/`:

| input | expected |
|---|---|
| HW pipeline, ARR 16002, non-PKI, close 2027-06-30, calc-2026 = 0, notes updated 5 days ago, prob 0.2, 3 notes, revenue_state NULL | `(88.9, true)` |
| Services pipeline, services_2026 = 120, close 2026-12-15, no notes date, prob 0.5, 40 notes, Forecast | `(36.4, false)` |
| HW pipeline, ARR "" → tpm 15, PKI, no closedate, calc "" , prob 0.1, notes NULL, Upside | `(2.8, false)` |
| SEALCOIN pipeline 705868909, ARR 500, prob 1.0 | `(NULL, NULL)` |

### 2.2 `sql/new_deals_from_sync.sql` — adapter view over the synced table

The connector decides column names and types; the adapter isolates that decision in one view so every downstream object
reads stable names. Placeholders `${SYNC_DATASET}` / `${SYNC_DEALS_TABLE}` are filled from `.env` after the first transfer
run (open question Q3). For the Google DTS connector the per-property columns are typed per E4; for the HubSpot native
sync they are external-table columns (E5). `SAFE_CAST` makes the view tolerant of either.

```sql
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.deals_synced_v1` AS
SELECT
  CAST(hs_object_id AS STRING)                                   AS deal_id,
  CAST(pipeline AS STRING)                                       AS pipeline_id,
  CAST(dealstage AS STRING)                                      AS dealstage_id,
  dealname, final_customer, sales_region, deal_currency_code     AS currency,
  product_hierarchy, prod___product_name_new_                    AS product, application,
  icalps_dealtype, icalps_stage, icalps_dealstatus, revenue_state,
  hs_object_source_label                                         AS source,
  CAST(hs_created_by_user_id AS STRING)                          AS created_by_user_id,
  CAST(hubspot_owner_id AS STRING)                               AS owner_id,
  SAFE_CAST(createdate AS TIMESTAMP)                             AS createdate,
  SAFE_CAST(closedate AS TIMESTAMP)                              AS closedate,
  SAFE_CAST(notes_last_updated AS TIMESTAMP)                     AS notes_last_updated,
  SAFE_CAST(hs_lastmodifieddate AS TIMESTAMP)                    AS lastmodified,
  SAFE_CAST(hs_deal_stage_probability AS FLOAT64)                AS stage_probability,
  SAFE_CAST(amount AS FLOAT64)                                   AS amount,
  SAFE_CAST(amount_in_home_currency AS FLOAT64)                  AS amount_kusd,
  SAFE_CAST(asp_in_usd_q2_2022_calculation AS FLOAT64)           AS asp_in_usd_q2_2022_calculation,
  SAFE_CAST(tpm__k_y AS FLOAT64)                                 AS tpm__k_y,
  SAFE_CAST(services_value_2026 AS FLOAT64)                      AS services_value_2026,
  SAFE_CAST(calculation___pipeline_2026__k__ AS FLOAT64)         AS calculation___pipeline_2026__k__,
  SAFE_CAST(num_contacted_notes AS FLOAT64)                      AS num_contacted_notes,
  -- the written-back properties, once they exist in HubSpot and in the sync (NULL before)
  SAFE_CAST(hot_score_v1 AS FLOAT64)                             AS hot_score_v1_synced,
  SAFE_CAST(hot_flag_v1 AS BOOL)                                 AS hot_flag_v1_synced
FROM `${PROJECT}.${SYNC_DATASET}.${SYNC_DEALS_TABLE}`
WHERE hs_object_id IS NOT NULL;
```

`main.py:34-38` lists 27 properties; the view carries the same set (owners and pipeline labels come from the synced
`Owners` and the pipelines table instead of two extra API calls — `main.py:86-99`).

### 2.3 `sql/hot_deals_v1.sql` — versioned view, per-region top-N with window functions

```sql
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1` AS
WITH scored AS (
  SELECT d.*,
         `${PROJECT}.${DATASET}.hot_score_v1`(pipeline_id, asp_in_usd_q2_2022_calculation, tpm__k_y, services_value_2026,
            product_hierarchy, closedate, calculation___pipeline_2026__k__, notes_last_updated, stage_probability,
            num_contacted_notes, revenue_state, CURRENT_TIMESTAMP()) AS hs
  FROM `${PROJECT}.${DATASET}.deals_synced_v1` d
  WHERE pipeline_id IN ('12096408', '13772279')          -- scored pipelines only (main.py:43)
    AND dealstage_id NOT IN ('12096869','12096415','13772274','13772285','13772286','13772309')  -- closed stages (E1)
)
SELECT deal_id, dealname, final_customer, sales_region, pipeline_id, amount_kusd, closedate,
       hs.score AS hot_score_v1, hs.hot AS hot_flag_v1,
       ROW_NUMBER() OVER (PARTITION BY sales_region ORDER BY hs.score DESC, amount_kusd DESC, deal_id) AS region_rank,
       RANK()       OVER (ORDER BY hs.score DESC, amount_kusd DESC)                                       AS global_rank,
       hot_score_v1_synced, hot_flag_v1_synced
FROM scored;

-- per-region top-5 (QUALIFY needs no subquery)
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1_top5_by_region` AS
SELECT * FROM `${PROJECT}.${DATASET}.hot_deals_v1` QUALIFY region_rank <= 5;

-- rows the write-back must PATCH: computed value differs from what HubSpot already holds
CREATE OR REPLACE VIEW `${PROJECT}.${DATASET}.hot_deals_v1_writeback` AS
SELECT h.deal_id, h.hot_score_v1, h.hot_flag_v1
FROM `${PROJECT}.${DATASET}.hot_deals_v1` h
LEFT JOIN (SELECT deal_id, ARRAY_AGG(STRUCT(hot_score_v1, hot_flag_v1) ORDER BY run_ts DESC LIMIT 1)[OFFSET(0)] AS last
           FROM `${PROJECT}.${DATASET}.writeback_log` WHERE status = 'OK' GROUP BY deal_id) w USING (deal_id)
WHERE h.hot_score_v1 IS NOT NULL
  AND (h.hot_score_v1 IS DISTINCT FROM COALESCE(w.last.hot_score_v1, h.hot_score_v1_synced)
    OR h.hot_flag_v1  IS DISTINCT FROM COALESCE(w.last.hot_flag_v1,  h.hot_flag_v1_synced));
```

Versioning rule: a new fit is `hot_score_v2` + `hot_deals_v2`; v1 is never edited in place; the HubSpot property name
carries the version so Breeze users see which model produced the number. `CREATE OR REPLACE VIEW` is idempotent.

### 2.4 `sql/new_deals_weekly.sql` — the scheduled script (window → shape → duplicates → MERGE → audit → state, atomically)

Runs as a BigQuery scheduled query with `@run_time`. The whole body is one transaction (E15): if the MERGE fails nothing
advances, exactly A's rule (`main.py:196`), but enforced by the engine instead of by statement order.

```sql
DECLARE entity STRING DEFAULT '${ENTITY}';                         -- one scheduled query per entity, like A's two Scheduler jobs
DECLARE pipelines ARRAY<STRING> DEFAULT ${PIPELINES};              -- SEALSQ: ['12096408','13772279','705868909','934982230']; ICALPS: ['766126206']
DECLARE lookback_days INT64 DEFAULT 14;                            -- replaces the watermark search; MERGE absorbs the overlap
DECLARE run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(@run_time, SECOND);

-- freshness guard (G2): refuse to MERGE a stale sync
IF (SELECT MAX(lastmodified) FROM `${PROJECT}.${DATASET}.deals_synced_v1`) < TIMESTAMP_SUB(run_ts, INTERVAL 36 HOUR) THEN
  RAISE USING MESSAGE = 'deals sync is older than 36h; aborting run';
END IF;

BEGIN TRANSACTION;

CREATE TEMP TABLE batch AS
WITH recent AS (
  SELECT *, REGEXP_REPLACE(LOWER(COALESCE(NULLIF(TRIM(final_customer), ''), REGEXP_EXTRACT(dealname, r'^[^-/|(]*'))), r'[^a-z0-9]', '') AS name_key
  FROM `${PROJECT}.${DATASET}.deals_synced_v1`
  WHERE createdate >= TIMESTAMP_SUB(run_ts, INTERVAL 90 DAY) AND createdate < run_ts          -- duplicate horizon = A's recent_names(days=90)
), win AS (
  SELECT * FROM recent WHERE createdate >= TIMESTAMP_SUB(run_ts, INTERVAL lookback_days DAY) AND pipeline_id IN UNNEST(pipelines)
), dups AS (
  SELECT w.deal_id, STRING_AGG(r.deal_id, ', ' ORDER BY r.createdate) AS duplicate_of
  FROM win w JOIN recent r ON r.name_key = SUBSTR(w.name_key, 1, 40) AND r.deal_id <> w.deal_id
  GROUP BY w.deal_id
)
SELECT entity, w.deal_id, w.dealname, w.final_customer, SUBSTR(w.name_key, 1, 40) AS name_key,
       w.createdate, w.created_by_user_id, w.source,
       COALESCE(o.owner_name, w.owner_id) AS owner, w.sales_region,
       COALESCE(p.label, w.pipeline_id) AS pipeline, w.pipeline_id, COALESCE(s.label, w.dealstage_id) AS stage,
       ROUND(IFNULL(w.stage_probability, 0) * 100, 1) AS probability_pct, IFNULL(w.amount, 0) AS amount, w.currency,
       IFNULL(w.amount_kusd, 0) AS amount_kusd, DATE(w.closedate) AS closedate,
       IFNULL(w.asp_in_usd_q2_2022_calculation, 0) AS arr_ky, w.product_hierarchy AS product_family, w.product, w.application,
       w.icalps_dealtype, w.icalps_stage,
       hs.score AS day1_hot_score, hs.hot AS day1_hot_flag,
       d.duplicate_of IS NOT NULL AS duplicate_suspect, d.duplicate_of,
       CONCAT('https://app.hubspot.com/go-to/${PORTAL_ID}/0-3/', w.deal_id) AS deal_url,
       run_ts AS first_seen_run, run_ts AS last_seen_run
FROM win w
LEFT JOIN dups d USING (deal_id)
LEFT JOIN `${PROJECT}.${DATASET}.owners_synced_v1` o ON o.owner_id = w.owner_id
LEFT JOIN `${PROJECT}.${DATASET}.pipelines_synced_v1` p ON p.pipeline_id = w.pipeline_id
LEFT JOIN `${PROJECT}.${DATASET}.pipeline_stages_synced_v1` s ON s.stage_id = w.dealstage_id,
UNNEST([`${PROJECT}.${DATASET}.hot_score_v1`(w.pipeline_id, w.asp_in_usd_q2_2022_calculation, w.tpm__k_y, w.services_value_2026,
        w.product_hierarchy, w.closedate, w.calculation___pipeline_2026__k__, w.notes_last_updated, w.stage_probability,
        w.num_contacted_notes, w.revenue_state, run_ts)]) AS hs;

-- L7: MERGE on deal_id; first_seen_run is never overwritten (main.py:126)
MERGE `${PROJECT}.${DATASET}.new_deals` t USING batch s ON t.deal_id = s.deal_id
WHEN MATCHED THEN UPDATE SET
  entity = s.entity, dealname = s.dealname, final_customer = s.final_customer, name_key = s.name_key, createdate = s.createdate,
  created_by_user_id = s.created_by_user_id, source = s.source, owner = s.owner, sales_region = s.sales_region, pipeline = s.pipeline,
  pipeline_id = s.pipeline_id, stage = s.stage, probability_pct = s.probability_pct, amount = s.amount, currency = s.currency,
  amount_kusd = s.amount_kusd, closedate = s.closedate, arr_ky = s.arr_ky, product_family = s.product_family, product = s.product,
  application = s.application, icalps_dealtype = s.icalps_dealtype, icalps_stage = s.icalps_stage, day1_hot_score = s.day1_hot_score,
  day1_hot_flag = s.day1_hot_flag, duplicate_suspect = s.duplicate_suspect, duplicate_of = s.duplicate_of, deal_url = s.deal_url,
  last_seen_run = s.last_seen_run
WHEN NOT MATCHED THEN INSERT ROW;

-- L13: history per run — idempotent for a replayed @run_time
DELETE FROM `${PROJECT}.${DATASET}.new_deals_runs` WHERE run_ts = run_ts AND entity = entity;
INSERT INTO `${PROJECT}.${DATASET}.new_deals_runs` SELECT run_ts AS run_ts, * FROM batch;

-- L8: state advances only inside the same transaction as the MERGE
MERGE `${PROJECT}.${DATASET}.report_state` t
USING (SELECT CONCAT('NEW_DEALS_', entity, '_C') AS report_id, run_ts AS watermark) s ON t.report_id = s.report_id
WHEN MATCHED THEN UPDATE SET watermark = s.watermark, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (s.report_id, s.watermark, CURRENT_TIMESTAMP());

COMMIT TRANSACTION;
```

Idempotency: the batch is a pure function of (synced table state, `@run_time`); re-running the same `@run_time` (backfill)
rewrites the same `new_deals_runs` partition slice and MERGEs identical values. The `report_id` suffix `_C` keeps A's and C's
state rows apart (G4).

### 2.5 `sql/audit_tables.sql` — tables C adds next to `bigquery_schema.sql`

```sql
CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.new_deals_runs`            -- "table per run" as partitions, not objects (G13)
  (run_ts TIMESTAMP NOT NULL, entity STRING, deal_id STRING NOT NULL, dealname STRING, final_customer STRING, name_key STRING,
   createdate TIMESTAMP, created_by_user_id STRING, source STRING, owner STRING, sales_region STRING, pipeline STRING, pipeline_id STRING,
   stage STRING, probability_pct FLOAT64, amount FLOAT64, currency STRING, amount_kusd FLOAT64, closedate DATE, arr_ky FLOAT64,
   product_family STRING, product STRING, application STRING, icalps_dealtype STRING, icalps_stage STRING, day1_hot_score FLOAT64,
   day1_hot_flag BOOL, duplicate_suspect BOOL, duplicate_of STRING, deal_url STRING, first_seen_run TIMESTAMP, last_seen_run TIMESTAMP)
PARTITION BY DATE(run_ts) CLUSTER BY entity, deal_id
OPTIONS (partition_expiration_days = 730, description = "one slice per scheduled run; replay of a run_ts replaces its slice");

CREATE TABLE IF NOT EXISTS `${PROJECT}.${DATASET}.writeback_log`
  (run_ts TIMESTAMP NOT NULL, deal_id STRING NOT NULL, hot_score_v1 FLOAT64, hot_flag_v1 BOOL,
   previous_score FLOAT64, previous_flag BOOL, status STRING, http_status INT64, error STRING, dry_run BOOL)
PARTITION BY DATE(run_ts) CLUSTER BY deal_id;
```

### 2.6 `sql/scheduled_query.sh` — register the scheduled queries (idempotent by display name)

```bash
#!/usr/bin/env bash
# Registers (or updates) one scheduled query per entity. Schedule is UTC (E14): 04:00 UTC Monday is 05:00/06:00 Europe/Zurich
# all year, i.e. always before A's 07:00 local, and after the 02:00 UTC DTS transfer (G3).
set -euo pipefail
: "${PROJECT:?}" "${DATASET:?}" "${PORTAL_ID:?}" "${SYNC_DATASET:?}" "${SYNC_DEALS_TABLE:?}"
SA=new-deals-sql@${PROJECT}.iam.gserviceaccount.com
LOCATION=${BQ_LOCATION:-europe-west6}
render() { sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${PORTAL_ID}/$PORTAL_ID/g" \
               -e "s/\${SYNC_DATASET}/$SYNC_DATASET/g" -e "s/\${SYNC_DEALS_TABLE}/$SYNC_DEALS_TABLE/g" "$@"; }

# 1. routine + views + tables (CREATE OR REPLACE / IF NOT EXISTS → re-runnable)
for f in sql/audit_tables.sql sql/hot_score_udf.sql sql/new_deals_from_sync.sql sql/hot_deals_v1.sql; do
  render "$f" | bq --project_id="$PROJECT" --location="$LOCATION" query --use_legacy_sql=false
done

# 2. scheduled query per entity; `bq mk --transfer_config` creates a new config each time, so look the name up first
for ENTITY in SEALSQ ICALPS; do
  case $ENTITY in SEALSQ) P="['12096408','13772279','705868909','934982230']";; ICALPS) P="['766126206']";; esac
  Q=$(render sql/new_deals_weekly.sql | sed -e "s/\${ENTITY}/$ENTITY/" -e "s/\${PIPELINES}/$P/")
  NAME="new-deals-$ENTITY-C"
  EXISTING=$(bq ls --transfer_config --transfer_location="$LOCATION" --project_id="$PROJECT" --format=json \
             | python3 -c 'import sys,json; print(next((c["name"] for c in json.load(sys.stdin) if c["displayName"]==sys.argv[1]),""))' "$NAME")
  PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.stdin.read()}))' <<<"$Q")
  if [ -z "$EXISTING" ]; then
    bq mk --transfer_config --project_id="$PROJECT" --location="$LOCATION" --data_source=scheduled_query \
       --display_name="$NAME" --schedule="every monday 04:00" --service_account_name="$SA" --params="$PARAMS" \
       ${DISABLE_SCHEDULE:+--no_auto_scheduling}
  else
    bq update --transfer_config --params="$PARAMS" --schedule="every monday 04:00" --service_account_name="$SA" "$EXISTING"
  fi
done
echo "dry run:  bq query --use_legacy_sql=false --dry_run --parameter=run_time:TIMESTAMP:\$(date -u +%FT%TZ) < <(render sql/new_deals_weekly.sql | sed …)"
echo "replay:   bq mk --transfer_run --start_time=2026-09-28T04:00:00Z --end_time=2026-10-05T04:00:00Z <resource_name>"
```

Gate: `DISABLE_SCHEDULE=1` registers the config without auto scheduling; the operator runs `bq mk --transfer_run` for a
single `run_time` first (that is the C equivalent of `?dry_run=1`, writing to real tables — hence the extra
`bq query --dry_run` for syntax/bytes, and a `hubspot_dev` dataset for a true no-write rehearsal, §5).

---

## 3 · Remote JS write-back — Node 22 Cloud Run job

### 3.1 Why a *job*, not a service or an n8n Code node

A Cloud Run job has no HTTP surface (no `--no-allow-unauthenticated` to get wrong), is started by Cloud Scheduler through
`jobs.run` with an OAuth token of a service account holding `roles/run.invoker` (E18), scales to zero between runs, and
carries its secret as `--set-secrets` (E19). An n8n Code node could run the same ~120 lines, but then the token lives in
n8n's credential store and the execution log in n8n's database (Scenario B's L2/L13 story); the job variant keeps L2 and
L13 in Secret Manager and BigQuery, which is where A keeps them — the two lanes stay Conditional rather than Divergent.

### 3.2 Why PATCHing the same value is idempotent, and why we still skip unchanged rows

1. `PATCH`/batch-update sets a property to a value; applying `score=88.9` to a deal that already holds `88.9` leaves the
   record equal to itself — the operation is a projection, so f(f(x)) = f(x).
2. HubSpot does not write a property-history entry when the value does not change, and workflow enrollment on "property
   value changed" fires only on an actual change (E12). So a repeated write neither pollutes history nor re-triggers
   automations.
3. We *still* skip unchanged rows (`hot_deals_v1_writeback`, §2.3) because (a) it reduces calls against the 190/10 s burst
   and the daily cap (E10), (b) `hs_lastmodifieddate` behaviour on no-op writes is not documented as a guarantee (E12
   threads show lastmodified moving for non-visible changes), and (c) the comparison itself needs no HubSpot read: it uses
   the synced property (lagging) *or* the last successful `writeback_log` row (fresh), whichever is newer — so between two
   syncs the job will not re-PATCH what it wrote last week.
4. **Never PATCH NULL.** The view filters `hot_score_v1 IS NOT NULL`; sending `""` would *clear* the property on the
   ICALPS/SEALCOIN/Quantum deals (G6).

### 3.3 `writeback/index.mjs`

```js
// new-deals write-back: BigQuery view → HubSpot deals batch update (100/call) → BigQuery writeback_log. Node 22, no deps beyond @google-cloud/bigquery.
import { BigQuery } from '@google-cloud/bigquery';

const { BQ_PROJECT, BQ_DATASET = 'hubspot', HUBSPOT_TOKEN, WRITEBACK_APPROVE } = process.env;
const DRY = WRITEBACK_APPROVE !== '1';                    // gate: unset → compute, log with dry_run=true, write nothing to HubSpot
const HS = 'https://api.hubapi.com';
const RUN_TS = new Date(); RUN_TS.setMilliseconds(0);
const bq = new BigQuery({ projectId: BQ_PROJECT });
const T = (n) => `\`${BQ_PROJECT}.${BQ_DATASET}.${n}\``;

const [rows] = await bq.query({ query: `SELECT deal_id, hot_score_v1, hot_flag_v1 FROM ${T('hot_deals_v1_writeback')} ORDER BY deal_id` });
console.log(JSON.stringify({ run_ts: RUN_TS, candidates: rows.length, dry_run: DRY }));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function patchBatch(batch) {                        // POST /crm/v3/objects/deals/batch/update — max 100 inputs; 200 all ok, 207 partial (E11)
  const body = { inputs: batch.map((r) => ({ id: r.deal_id, properties: { hot_score_v1: String(r.hot_score_v1), hot_flag_v1: r.hot_flag_v1 ? 'true' : 'false' } })) };
  for (let attempt = 0; attempt < 5; attempt++) {
    const res = await fetch(`${HS}/crm/v3/objects/deals/batch/update`, { method: 'POST', headers: { Authorization: `Bearer ${HUBSPOT_TOKEN}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (res.status === 429 || res.status >= 500) {        // honour X-HubSpot-RateLimit-Interval-Milliseconds (E10), then retry
      const wait = Number(res.headers.get('x-hubspot-ratelimit-interval-milliseconds') || 10000);
      console.warn(`HTTP ${res.status}; waiting ${wait}ms`); await sleep(wait); continue;
    }
    const json = await res.json().catch(() => ({}));
    const failed = new Set((json.errors || []).flatMap((e) => e.context?.ids || e.context?.objectIds || []));
    return batch.map((r) => ({ ...r, http_status: res.status, status: res.ok && !failed.has(r.deal_id) ? 'OK' : 'ERROR', error: res.ok ? (failed.has(r.deal_id) ? JSON.stringify(json.errors) : null) : JSON.stringify(json).slice(0, 1000) }));
  }
  return batch.map((r) => ({ ...r, http_status: 0, status: 'ERROR', error: 'retries exhausted' }));
}

const results = [];
for (let i = 0; i < rows.length; i += 100) {
  const batch = rows.slice(i, i + 100);
  results.push(...(DRY ? batch.map((r) => ({ ...r, http_status: null, status: 'DRY', error: null })) : await patchBatch(batch)));
  if (!DRY) await sleep(600);                              // ≤ ~17 calls / 10 s, far under 190 (E10)
}
if (results.length) {
  await bq.dataset(BQ_DATASET).table('writeback_log').insert(results.map((r) => ({
    run_ts: RUN_TS.toISOString(), deal_id: r.deal_id, hot_score_v1: r.hot_score_v1, hot_flag_v1: r.hot_flag_v1,
    status: r.status, http_status: r.http_status, error: r.error, dry_run: DRY })));
}
const summary = { run_ts: RUN_TS, patched: results.filter((r) => r.status === 'OK').length, errors: results.filter((r) => r.status === 'ERROR').length, dry: results.filter((r) => r.status === 'DRY').length };
console.log(JSON.stringify(summary));
if (summary.errors) process.exit(1);                     // non-zero → Cloud Run retries the task (--max-retries); OK rows are already logged, so the retry PATCHes only the rest
```

`package.json`: `{ "name": "new-deals-writeback", "type": "module", "engines": { "node": ">=22" }, "scripts": { "start": "node index.mjs" }, "dependencies": { "@google-cloud/bigquery": "^8" } }`.

`Dockerfile`: `FROM node:22-slim` → `WORKDIR /app` → `COPY package*.json ./` → `RUN npm ci --omit=dev` → `COPY index.mjs ./` → `USER node` → `CMD ["node","index.mjs"]`.

### 3.4 `writeback/deploy_job.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT:?}" "${REGION:=europe-west6}" "${DATASET:=hubspot}"
SA=new-deals-writeback@${PROJECT}.iam.gserviceaccount.com
SCHED_SA=new-deals-scheduler@${PROJECT}.iam.gserviceaccount.com
SECRET_VERSION=${HUBSPOT_TOKEN_VERSION:?pin a Secret Manager version, not latest}      # (E19 guidance)

gcloud iam service-accounts create new-deals-writeback --project "$PROJECT" --display-name "new deals write-back job" 2>/dev/null || true
gcloud iam service-accounts create new-deals-scheduler --project "$PROJECT" --display-name "scheduler invoker" 2>/dev/null || true
bq --project_id="$PROJECT" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""   # principal double-quoted (A's R01)
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser
gcloud secrets add-iam-policy-binding hubspot-token-write --project "$PROJECT" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor

# source deploy (Dockerfile present → used; E19); create-or-update is one verb
gcloud run jobs deploy new-deals-writeback --project "$PROJECT" --region "$REGION" --source writeback \
  --service-account "$SA" --tasks 1 --max-retries 2 --task-timeout 900s \
  --set-env-vars "BQ_PROJECT=$PROJECT,BQ_DATASET=$DATASET,WRITEBACK_APPROVE=${WRITEBACK_APPROVE:-0}" \
  --set-secrets "HUBSPOT_TOKEN=hubspot-token-write:${SECRET_VERSION}"

# Scheduler → jobs.run (E18). 05:30 Zurich: after the 04:00 UTC scheduled query, before A's 07:00 report
gcloud run jobs add-iam-policy-binding new-deals-writeback --project "$PROJECT" --region "$REGION" --member "serviceAccount:$SCHED_SA" --role roles/run.invoker
gcloud scheduler jobs create http new-deals-writeback --project "$PROJECT" --location "$REGION" --schedule "30 5 * * 1" --time-zone "Europe/Zurich" \
  --uri "https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/new-deals-writeback:run" --http-method POST \
  --oauth-service-account-email "$SCHED_SA" --max-retry-attempts 3 2>/dev/null || \
gcloud scheduler jobs update http new-deals-writeback --project "$PROJECT" --location "$REGION" --schedule "30 5 * * 1" --time-zone "Europe/Zurich"
echo "dry run now:  gcloud run jobs execute new-deals-writeback --region $REGION --wait          # WRITEBACK_APPROVE unset → logs only"
echo "go live:      gcloud run jobs update new-deals-writeback --region $REGION --update-env-vars WRITEBACK_APPROVE=1"
```

### 3.5 Token scoping (L2 / L14)

Two private apps (or one app, two tokens is not possible — a private app has one token), so **two private apps**:

| App | Scopes | Where | Used by |
|---|---|---|---|
| `new-deals-read` (exists; `README.md:19`) | `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read` | Secret `hubspot-token` | A's function; the DTS connector needs *more* (E4 list) — a third, broader read-only app is cleaner than widening this one |
| `new-deals-write` (new) | `crm.objects.deals.write` (+ `crm.objects.deals.read` for GETs if ever needed) | Secret `hubspot-token-write`, pinned version | the write-back job only |
| one-time bootstrap | `crm.schemas.deals.write` | operator's shell, not stored | `writeback/bootstrap_property.sh` creating `hot_score_v1` (number/number) and `hot_flag_v1` (bool/booleancheckbox) in group `dealinformation`; or create them in the UI and skip the scope |

Bootstrap (idempotent: GET first, POST only if 404):

```bash
for spec in 'hot_score_v1|Hot score v1|number|number' 'hot_flag_v1|Hot flag v1|bool|booleancheckbox'; do
  IFS='|' read -r NAME LABEL TYPE FIELD <<<"$spec"
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $HUBSPOT_SCHEMA_TOKEN" "https://api.hubapi.com/crm/v3/properties/deals/$NAME")
  [ "$code" = 200 ] && { echo "$NAME exists"; continue; }
  curl -s -X POST -H "Authorization: Bearer $HUBSPOT_SCHEMA_TOKEN" -H 'Content-Type: application/json' https://api.hubapi.com/crm/v3/properties/deals \
    -d "{\"name\":\"$NAME\",\"label\":\"$LABEL\",\"type\":\"$TYPE\",\"fieldType\":\"$FIELD\",\"groupName\":\"dealinformation\",\"description\":\"Written by new-deals-writeback (BigQuery hot_deals_v1). Do not edit by hand.\"}"
done
```

### 3.6 Rate and volume

Live probe in `README.md:5`: 12 new deals in two weeks. Even a full re-score of every open SEALSQ deal (hundreds) is < 10
batch calls; the burst limit is 190/10 s (Professional/Enterprise) and the daily cap 625k–1M (E10). The job sleeps 600 ms
between calls and backs off on 429 using HubSpot's interval header.

---

## 4 · Breeze consumption

### 4.1 What Breeze reads

Once `hot_score_v1` / `hot_flag_v1` exist on the deal, every HubSpot surface sees them: record sidebar, list filters,
custom reports, workflows ("hot_flag_v1 is true → notify owner"), and Breeze Assistant prompts such as "show my deals
where Hot flag v1 is true, by region" (E21). The MCP `query_crm_data` tool (HubSQL-shaped) can `SELECT dealname,
hot_score_v1 FROM DEAL WHERE hot_flag_v1 = 'true' ORDER BY hot_score_v1 DESC LIMIT 10` (E9).

### 4.2 What Breeze cannot compute — confirmed and sharpened

The user's matrix says "HubSQL has no CASE/log/window functions". E8 shows it is stricter: **no arithmetic expressions
at all**, no `CASE`, single `FROM` table, `LEFT JOIN` only, GROUP BY ≤ 2 columns, LIMIT ≤ 10,000, and the endpoint is a
*private beta*. "Per-region top-N" is therefore also out of reach inside HubSpot unless the rank is materialised as a
property (`hot_rank_region_v1`) by the same write-back — add it to the PATCH payload if Breeze users need it (G12).
Breeze Assistant itself is rate-limited to 30 generations/min, 1,000/day (E21), and writes through `manage_crm_objects`
are human-confirmed (E9) — not an automation surface. No "scheduled prompts" feature appears in the KB (E21); treat the
user's "beta" note as unverified.

### 4.3 The reverse sync alternative (only with Data Hub Enterprise)

HubSpot's BigQuery integration syncs **BigQuery → HubSpot every 15 minutes … monthly** (E5, beta). If the portal is on
Data Hub Enterprise, a view with `hs_object_id, hot_score_v1, hot_flag_v1` could be synced into the deal properties
with no JS at all — L10 would then be BigQuery-native, and the user's matrix cell "BigQuery sync: cannot write to HubSpot"
is outdated (G1). Open questions: record matching key and create-vs-update semantics are not stated in the KB page
fetched. Default assumption: not on Data Hub Enterprise → JS write-back.

---

## 5 · Claude iteration without touching production

1. **MCP Toolbox for Databases, prebuilt BigQuery** (E20): `.mcp.json` →
   `{"mcpServers":{"bigquery":{"command":"./toolbox","args":["--prebuilt","bigquery","--stdio"],"env":{"BIGQUERY_PROJECT":"<project>"}}}}`
   with ADC from `gcloud auth application-default login`. Tools: `execute_sql`, `get_table_info`, `list_table_ids`,
   `ask_data_insights`, `forecast`. Run it with the Toolbox write mode set to *blocked* (SELECT only) against production
   and *allowed* only against `hubspot_dev` — the flag names must be confirmed from `toolbox --help` (E20 open item);
   independent of the flag, IAM does the real fencing (next point).
2. **Two datasets, two roles.** `hubspot` (production): Claude's identity gets `roles/bigquery.dataViewer` only, so a
   `CREATE OR REPLACE VIEW` or `MERGE` fails with 403 — the UDF and views are *deployed* by `scheduled_query.sh` under
   the operator's identity. `hubspot_dev`: `roles/bigquery.dataEditor`; `CREATE TABLE hubspot_dev.deals_sample AS SELECT *
   FROM hubspot.deals_synced_v1 WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)` gives a frozen
   sample; `hot_score_v2` candidates are created there and compared with
   `SELECT COUNTIF(v1.hot <> v2.hot) … FROM … JOIN …`.
3. **Versioned, never edited.** A new fit is a new routine name + view name + HubSpot property name; `hot_deals_v1` stays
   until the write-back is switched (one env var: `SCORE_VERSION`).
4. **Offline first.** `tests/test_hot_score_sql.py` (the DuckDB harness, E3) runs with no credentials in < 5 s; it is the
   regression net for the SQL in the same way `tests/test_hot_score.py` is for A's Python. Both read the constants from the
   files that ship, so a change to one copy is a failing test on the other (CONVENTIONS.md "Same arithmetic everywhere").
5. **BigQuery Studio notebooks** (Colab Enterprise, `roles/bigquery.studioUser`,
   [docs](https://docs.cloud.google.com/bigquery/docs/create-notebooks)) for the exploratory half: BigQuery DataFrames over
   `hubspot_dev`, plots of score distributions per region.
6. **`bq query --dry_run`** on the rendered `new_deals_weekly.sql` gives bytes scanned and a syntax check without a job;
   `bq mk --transfer_run` with a single `run_time` is the first live rehearsal, after the dataset-level IAM is in place.

---

## 6 · Lane cells L0–L17 (C versus A and B)

Parity words follow the fixed vocabulary. "A" = Cloud Run function; "B" = n8n on Cloud Run.

| Layer | C mechanism | Idempotent | vs A / vs B → parity |
|---|---|---|---|
| **L0 Code acquisition & deploy unit** | Three deploy units: `sql/*.sql` applied by `scheduled_query.sh` (`bq query` + `bq mk/update --transfer_config`); `writeback/` by `gcloud run jobs deploy --source`; the sync by `bq mk --transfer_config --data_source=hubspot`. All git-versioned. | yes (CREATE OR REPLACE / IF NOT EXISTS; deploy is create-or-update; transfer config looked up by display name) | A: one unit (`gcloud run deploy --function`); B: JSON import into a running instance. **Divergent** — remediation: every unit has an idempotent script and one `make deploy-C`. |
| **L1 Identity to BigQuery** | SA `new-deals-sql` runs the scheduled queries (`--service_account_name`); SA `new-deals-writeback` for the job (ADC in Cloud Run); both `roles/bigquery.jobUser` + dataset `dataEditor` via DCL `GRANT … TO "serviceAccount:…"`. Claude: user ADC, `dataViewer` on prod. | yes | A: one SA `new-deals-fn`; B: n8n BigQuery credential (SA key or OAuth). **Conditional** — same result when each identity holds jobUser + dataset dataEditor. |
| **L2 Secrets (HubSpot token)** | Write token in Secret Manager `hubspot-token-write`, **pinned version** via `--set-secrets` on the job (resolved at each execution's instance start); DTS holds its own copy of a read token inside the transfer config (Google-managed). | yes | A: `hubspot-token:latest` on a service (read at instance start); B: n8n credential store. **Divergent** from B, **Conditional** with A (same when both pin a version). |
| **L3 Trigger & schedule** | DTS transfer (e.g. `every day 02:00` UTC) → scheduled query `every monday 04:00` (UTC only, E14) → Cloud Scheduler `30 5 * * 1 Europe/Zurich` → `jobs.run`. Three clocks, two time-zone semantics. | yes (each trigger is independently re-runnable) | A: Cloud Scheduler `0 7 * * 1 Europe/Zurich` with OIDC; B: n8n Schedule Trigger. **Conditional** — same result when the chain is ordered with slack (sync < query < write-back < A's 07:00) and the UTC drift across DST is accepted (G3). |
| **L4 Extraction window** | No HubSpot search: `WHERE createdate >= run_ts − 14 d` over the synced table, plus a 36 h freshness guard. Sync is full-refresh on a schedule (DTS) or ≥ 6 h (HubSpot native). No event mode. | yes (set-based, pure function of sync state + `@run_time`) | A: exact `[watermark − 5 min, run_ts)` search + event webhook; B: HubSpot node/HTTP search. **Divergent** — remediation: lookback ≥ 2× sync cadence, freshness guard, accept that a deal created after the last sync appears next run (G2). |
| **L5 Scoring arithmetic** | Persistent SQL UDF `hot_score_v1` (E3 parity: 4,000 deals, 0 mismatches); constants defined once in SQL. | yes (deterministic) | A: Python `hot_score()`; B: Code-node port. **Parallel** — same constants, same bands; pinned by the shared test vectors. |
| **L6 Shaping & duplicate flag** | SQL `name_key` (same regexes), duplicates by self-join over the 90-day synced set (whole portal, not only `new_deals`), labels via synced owners/pipelines tables. | yes | A: Python in-batch + 90-day `new_deals` lookup; B: Code node. **Conditional** — same flag when the twin is in `new_deals` within 90 days; C can additionally see twins never reported (G5). |
| **L7 Load → MERGE into `hubspot.new_deals`** | `MERGE … ON deal_id` from a TEMP table inside a transaction; `first_seen_run` excluded from UPDATE. No staging table shared between entities. | yes | A: load job into shared `new_deals_staging` (WRITE_TRUNCATE) then MERGE; B: BigQuery node. **Parallel** in outcome (same target, same key, same update list). |
| **L8 Watermark advance** | `report_state` row `NEW_DEALS_{entity}_C` updated in the same transaction as the MERGE (engine-enforced "only after"). | yes | A: separate query after MERGE; B: node after node. **Conditional** — same meaning when C uses a distinct `report_id` (G4) and the lookback replaces the search window. |
| **L9 Delivery (XLSX/email)** | Not owned by C: the existing n8n `NEW_DEALS_DELIVERY` webhook can be POSTed by the job (optional `DELIVERY_WEBHOOK_URL`) or BI/Breeze reads `new_deals_last_7d`. Nothing in BigQuery sends email. | conditional (webhook POST is at-least-once) | A: function POSTs payload to n8n; B: native. **Divergent** — remediation: job POSTs the same payload contract, or delivery stays with A/B. |
| **L10 Write-back to HubSpot** | Node 22 job: `POST /crm/v3/objects/deals/batch/update` ×100, only rows whose value differs from `COALESCE(last_written, synced)`, never NULL, retries on 429/5xx, 207 parsed per id, `writeback_log` row per deal. Alternative with Data Hub Enterprise: BigQuery → HubSpot sync (15 min). | yes (same-value PATCH is a no-op; skip list prevents it anyway) | A: none; B: HubSpot node update. **Divergent** — only C and B write; remediation for A would be the same job. |
| **L11 Dry-run gate** | `WRITEBACK_APPROVE` unset → job logs `DRY` rows, no HubSpot call; `bq query --dry_run` for the script; `DISABLE_SCHEDULE=1` registers without auto-scheduling; `hubspot_dev` for a no-write rehearsal. There is no "compute but do not write" switch inside a scheduled query (G13). | yes | A: `?dry_run=1`; B: manual execution with pinned data. **Conditional** — same gate semantics when the operator uses the dev dataset for the SQL half. |
| **L12 Replay / backfill** | `bq mk --transfer_run --start_time … --end_time …` re-executes with historical `@run_time`; the run slice in `new_deals_runs` is replaced, MERGE converges; HubSpot-side replay = `DELETE FROM writeback_log WHERE run_ts = …` then re-run the job. Sync backfill: DTS "start a backfill run". | yes | A: `UPDATE report_state SET watermark = …` then trigger; B: edit a static variable. **Parallel** in outcome (same rows after replay), different handle. |
| **L13 Audit trail (history per run)** | `new_deals_runs` partitioned by `DATE(run_ts)` (a slice per run, 730-day expiry), `writeback_log` per deal per run, DTS run history, scheduled-query run history (BigQuery UI / `bq ls --transfer_run`). | yes (replay replaces, never duplicates) | A: Cloud Logging lines + `last_seen_run`; B: n8n executions table (DB). **Divergent** — remediation: A/B insert into the same `new_deals_runs` table (one recipe). |
| **L14 Access control** | Dataset IAM (prod viewer vs dev editor; SAs editor), Secret Manager accessor per SA, two private apps (read / write) + one-off schema token, Scheduler SA with `run.invoker` on the job only; HubSpot property visible per HubSpot permissions. | yes | A: one SA, one read-only app; B: n8n users + credential sharing. **Conditional** — least privilege holds when the write token is a separate app and pinned. |
| **L15 Concurrency & retry safety** | Scheduled query: transaction + MERGE; conflicting mutations on the same table are cancelled by BigQuery, so two overlapping runs cannot interleave. Job: `jobs.run` returns an Operation at once, so Scheduler retries only cover start failures; execution failures are retried by `--max-retries 2`; overlapping executions are allowed (quota 1,000) — harmless because the PATCH is idempotent and `writeback_log` is consulted before each run. | yes | A: `--max-instances 1 --concurrency 1` on the service; B: n8n execution settings. **Conditional** — same safety when every writer is idempotent (it is); no instance cap exists for jobs (G9). |
| **L16 Observability** | Scheduled-query run history + email/Pub/Sub failure notifications; job logs (JSON summary lines) and execution status in Cloud Run; `writeback_log` and `new_deals_runs` are queryable health tables; DTS run notifications. | n/a | A: Cloud Logging + Scheduler job status; B: n8n executions UI. **Divergent** — remediation: one `bq query` health probe (`SELECT entity, MAX(run_ts), COUNT(*) …`) documented in the sequence page for all three. |
| **L17 Cost & scale-to-zero** | DTS free in Preview; scheduled queries billed as ordinary queries (a few MB/week → within 1 TiB free); storage < 10 GiB free; Cloud Run job minutes within the free tier; Cloud Scheduler: A's two + C's one = 3 free jobs, a 4th costs $0.10/month. HubSpot native sync would require Data Hub Enterprise. | n/a | A: function within free tier; B: always-on n8n + Cloud SQL (tens of $/month). **Conditional** — C and A both scale to zero; B does not. |

---

## 7 · Gaps — concrete, testable claims

| id | sev | claim (refutable) | evidence | fix |
|---|---|---|---|---|
| **G1** | medium | The user's matrix cell "BigQuery sync: cannot write to HubSpot" is false for portals on Data Hub Enterprise: HubSpot's BigQuery integration syncs BigQuery → HubSpot at 15 min…monthly (beta). Test: open Data Hub → Integrations → BigQuery; if the "sync to HubSpot" direction is offered, the claim stands. | E5 KB page: "every 15 minutes, every 30 minutes, every hour …" under BigQuery → HubSpot; "Data Hub Enterprise". | Decide by plan: Enterprise → sync a view with `hs_object_id, hot_score_v1, hot_flag_v1`; otherwise JS write-back. Record the decision in the surfaces record. |
| **G2** | high | No ingestion route in C is near-real-time at the portal's current plan: the Google DTS connector is a scheduled **full refresh** ("transfers all available data" every run), the HubSpot native sync is ≥ 6 h. A deal created at 06:50 on run day is absent from `hubspot.new_deals` until the next week's run, whereas A's `search_created` sees it at 07:00 and A's event mode sees it in seconds. Test: create a deal, run the scheduled query before the next transfer, observe no row. | E4 ("With every transfer run, the HubSpot connector transfers all available data"), E5 cadence list; `main.py:179-189`. | Order the chain (sync 02:00 UTC, query 04:00 UTC), set lookback ≥ 2× cadence, add the freshness guard (`RAISE` if `MAX(lastmodified)` older than 36 h); accept the one-cycle lag or keep A's event mode alongside. |
| **G3** | low | BigQuery scheduled queries run on UTC only ("converted … to UTC. UTC is not affected by daylight saving time"), so "every monday 04:00" is 05:00 Zurich in winter and 06:00 in summer; A's Scheduler job uses `--time-zone Europe/Zurich`. Test: compare run_ts across a DST change. | E14. | Pick a UTC time that is always before the downstream steps (04:00 UTC) or drive the SQL from the Cloud Run job (`bq query` from Node) so one Scheduler job in Europe/Zurich owns both steps. |
| **G4** | medium | If C writes `report_state.report_id = 'NEW_DEALS_SEALSQ'` (A's key) while A is still deployed, A's next run reads C's `run_ts` as its watermark and skips deals created between A's previous run and C's run (A's window starts at the watermark − 5 min). Test: run C then A on the same entity; A's `window.watermark_in` equals C's run_ts. | `main.py:107-118, 184-186`; §2.4. | C uses `NEW_DEALS_{entity}_C`; or decommission A's scheduler before enabling C's; state the rule in the surfaces record. |
| **G5** | low | Duplicate flags diverge: A flags a twin only if it is in the same window or in `hubspot.new_deals` within 90 days (`recent_names`, which also silently returns `{}` on error and passes an unused parameter `@e`); C's self-join sees every twin in the synced table within 90 days, incl. deals A never reported (e.g. created before A's first run). Test: a pair where the older deal predates A's first run → A `duplicate_suspect=false`, C `true`. | `main.py:132-136, 150-151`; §2.4 `recent` CTE. | Accept C as the stricter rule and document it, or restrict C's `recent` CTE to `deal_id IN (SELECT deal_id FROM new_deals)` for strict parity. |
| **G6** | medium | The write-back must never send an empty/NULL `hot_score_v1`: `hot_score()` returns `(None, None)` for pipelines 705868909 (SEALCOIN) and 934982230 (Quantum & AI) although both are in `ENTITIES['SEALSQ']`, and HubSpot interprets `""` in a PATCH as "clear the property". Test: PATCH `{"hot_score_v1": ""}` on a deal that has a value → value cleared. | `main.py:31` vs `main.py:43,51`; E1 confirms both pipelines exist. | `hot_deals_v1_writeback` filters `hot_score_v1 IS NOT NULL` (done in §2.3); add a test vector for a SEALCOIN deal. Separately decide whether v2 should fit those pipelines. |
| **G7** | low | HubSpot's v3 batch-update reference page does not state the 100-input cap (it is stated in legacy docs/community), and the endpoint returns **207** for partial success, so a job that treats any 2xx as "all written" will log false OKs. Test: send 101 inputs (expect 400 VALIDATION_ERROR); send a batch with one invalid id (expect 207 with `errors[]`). | E11 (`200 207` on the legacy objects batch page; v3 page silent on the cap). | `index.mjs` slices by 100 and marks ids found in `errors[].context` as ERROR (done); keep the 101-input probe in the sequence page. |
| **G8** | low | For a Cloud Run **job**, `--set-secrets …:latest` is re-resolved at each execution's instance start, so A's risk "picked up at instance start only" does not apply the same way; Google nevertheless recommends pinning for env-var secrets. Test: add a secret version, execute the job, observe the new token in use without redeploy. | E19: "Environment variables are resolved at instance startup time … pin the secret to a particular version". | `deploy_job.sh` requires `HUBSPOT_TOKEN_VERSION`; rotation = `gcloud run jobs update --update-secrets`. |
| **G9** | medium | Scheduler retries do not retry a failed *execution*: `jobs.run` returns an `Operation` immediately, so Scheduler sees 200 and its 3 retries only fire when the run call itself fails; execution failures are governed by `--max-retries`; and overlapping executions of the same job are permitted (quota 1,000 running executions/region) — A's `--max-instances 1 --concurrency 1` remediation has no job equivalent. Test: make the job exit 1; Scheduler shows success, Cloud Run shows a retried task. | E18 (`jobs.run` "returns an Operation"; quota page). | Rely on idempotent PATCH + `writeback_log` (done); set `--max-retries 2`, `--task-timeout 900s`; optional lease: `INSERT … WHERE NOT EXISTS (run_ts same week, status OK)`. |
| **G10** | high | L10 is blocked by scopes: the private app in `README.md:19` has `crm.objects.deals.read, crm.schemas.deals.read, crm.objects.owners.read`; batch update needs `crm.objects.deals.write`, property creation needs `crm.schemas.deals.write`. Test: POST batch/update with the current token → 403 `MISSING_SCOPES`. | `README.md:19`; E11, E13. | Create `new-deals-write` private app (write scope only), store as `hubspot-token-write`; run the bootstrap once with a schema-write token that is not stored. |
| **G11** | medium | The synced table's name and column types are connector-specific and unverified: DTS creates native tables per asset with Date/Datetime → TIMESTAMP and Integer → INTEGER (HubSpot "number" properties not listed in the mapping); the HubSpot native sync creates *external* tables in `hubspot_data_set_{hubId}` (legacy: Parquet `OBJECTS_<type>`). `new_deals_from_sync.sql` cannot be finalised before one transfer run. Test: `bq show --schema` after the first run; if `asp_in_usd_q2_2022_calculation` is STRING, `SAFE_CAST` covers it; if it is NUMERIC/BIGNUMERIC the cast is exact; if the property is absent the view fails to compile. | E4 data-type table; E5/E6 naming. | Keep the adapter view as the single place for names/types; `.env.example` gets `SYNC_DATASET`, `SYNC_DEALS_TABLE`; first-run checklist in the sequence page. |
| **G12** | low | Breeze/HubSQL cannot compute the score **or the per-region rank**: HubSQL (private beta) rejects arithmetic expressions and `CASE`, allows one `FROM` table and `LEFT JOIN` only, GROUP BY ≤ 2 columns. Test: `SELECT amount * 1.1 FROM DEAL` → error. | E8. | Materialise what Breeze must show as properties (`hot_score_v1`, `hot_flag_v1`, optionally `hot_rank_region_v1`) via the write-back; keep BI/top-N in BigQuery views. |
| **G13** | low | A literal "table per run" is the wrong shape: permanent `CREATE TABLE` is not allowed inside a BigQuery transaction and a transaction may mutate at most 100 tables; a scheduled query also has no "compute but don't write" mode. Test: put `CREATE TABLE … AS SELECT` between BEGIN/COMMIT TRANSACTION → error. | E15. | `new_deals_runs` partitioned by `DATE(run_ts)` with a per-run `DELETE`+`INSERT` (done); dry-run via `bq query --dry_run` + `hubspot_dev`. |
| **G14** | low | Cost claim: C adds no paid component unless HubSpot's native sync is chosen (Data Hub Enterprise). DTS is free in Preview, scheduled queries are billed as ordinary queries (bytes), Cloud Run job minutes and 3 Scheduler jobs are in the free tiers; a 4th Scheduler job costs $0.10/month. Test: billing report after one month. | E4 ("no cost … while … in Preview"), E14 ("priced the same as manual BigQuery queries"), E22. | None; note the Preview pricing can change at GA. |

---

## 8 · Building blocks (status, role, idempotency) — recipes are in the structured output

| path | status | role | idempotency |
|---|---|---|---|
| `sql/hot_score_udf.sql` | new | persistent SQL UDF `hot_score_v1` (E3-tested) | `CREATE OR REPLACE FUNCTION` |
| `sql/new_deals_from_sync.sql` | new | adapter view over the synced deals (+ owners, pipelines, stages views) | `CREATE OR REPLACE VIEW` |
| `sql/hot_deals_v1.sql` | new | versioned scoring view, per-region top-5, write-back delta view | `CREATE OR REPLACE VIEW` |
| `sql/new_deals_weekly.sql` | new | the scheduled script: window → shape → dups → MERGE → run slice → state, one transaction | pure function of (sync, `@run_time`) |
| `sql/audit_tables.sql` | new | `new_deals_runs` (partitioned per run), `writeback_log` | `CREATE TABLE IF NOT EXISTS` |
| `sql/scheduled_query.sh` | new | apply SQL, register/update two scheduled queries, print dry-run and replay commands | lookup by display name → `mk` or `update` |
| `sql/sync_transfer.sh` | new | `bq mk --transfer_config --data_source=hubspot` (DTS route) with assets Deals/Owners, daily 02:00 UTC | lookup by display name |
| `writeback/package.json`, `writeback/index.mjs`, `writeback/Dockerfile` | new | Node 22 job: read delta view, batch PATCH ×100, log per deal, gate `WRITEBACK_APPROVE` | same-value PATCH no-op + skip list + per-deal log |
| `writeback/deploy_job.sh` | new | SAs, grants, `gcloud run jobs deploy --source`, pinned secret, Scheduler → `jobs.run` | create-or-update everywhere |
| `writeback/bootstrap_property.sh` | new | one-time creation of `hot_score_v1`/`hot_flag_v1` (GET → POST if 404) | GET-before-POST |
| `tests/test_hot_score_sql.py` | new | DuckDB parity harness (port of the scratchpad test) + pinned vectors | deterministic seed |
| `.env.example` | modify/new | `PROJECT, REGION, DATASET, PORTAL_ID, SYNC_DATASET, SYNC_DEALS_TABLE, HUBSPOT_TOKEN_VERSION, WRITEBACK_APPROVE` | placeholders only |
| `docs/SCENARIO_C.md` | new | this design condensed: routes, chain order, gates, probes, open questions | docs only |

---

## 9 · Open questions (with the default I proceed under)

| question | default assumption |
|---|---|
| Q1 Which HubSpot → BigQuery route? | Google DTS HubSpot connector (Preview, free, private-app token); daily 02:00 UTC; assets `Deals`, `Owners`. |
| Q2 Is the portal on Data Hub Enterprise (reverse sync available)? | No → JS write-back owns L10. |
| Q3 Synced table and column names/types? | Unknown until the first transfer run; adapter view with `SAFE_CAST`, names from `.env`. |
| Q4 May C share `report_state` keys with A? | No: `NEW_DEALS_{entity}_C`. |
| Q5 Property names / group? | `hot_score_v1` (number), `hot_flag_v1` (booleancheckbox) in `dealinformation`; created once by an operator token with `crm.schemas.deals.write`. |
| Q6 Write back for ICALPS, SEALCOIN, Quantum & AI? | No PATCH where the score is NULL; v2 may fit those pipelines later. |
| Q7 Job or n8n Code node for the write-back? | Cloud Run job (secret and log stay in GCP; B stays optional for delivery). |
| Q8 Chain timing? | Sync 02:00 UTC → scheduled query Mon 04:00 UTC → write-back Mon 05:30 Europe/Zurich → A's report 07:00 Europe/Zurich (if A stays). |
| Q9 Toolbox write-mode flag names? | Confirm from `toolbox --help`; IAM (viewer on prod, editor on dev) is the enforced fence regardless. |
| Q10 Does Breeze have "scheduled prompts" (beta)? | Not documented in the KB pages fetched; treat as unavailable; use HubSpot workflows on `hot_flag_v1` for notifications. |
