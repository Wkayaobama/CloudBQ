# Scenario A — Cloud Run function (gcloud, Scheduler OIDC, Secret Manager, BigQuery MERGE)

Discovery audit of `/home/user/CloudBQ/cloud_function_new_deals/{main.py, deploy.sh, bigquery_schema.sql, README.md}`
(branch `claude/cloud-run-bigquery-pipeline-e94ziy`, commit `3480059`), checked against the user's risk table and
against current Google Cloud documentation (fetched 2026-10-05; the docs now live under `docs.cloud.google.com`,
every `cloud.google.com/...` URL 301-redirects there). No repository file was changed.

Environment facts used: gcloud 530.0.0 / bq 2.1.19 installed (no auth); `bash -n deploy.sh` passes; `python3 -m
py_compile main.py` passes on Python 3.11.15; the pure functions of `main.py` were exercised offline with stubbed
`requests`/`functions_framework` (results quoted inline).

---

## 0. Headline

The code is small and its idempotency *model* is right (immutable `createdate`, half-open window with overlap,
MERGE on `deal_id`, watermark after MERGE). The *deployment* in the repo lags the user's own risk table: none of
the four "fixed" items (canonical `gcloud run deploy --function`, `roles/run.invoker`, `--max-instances 1
--concurrency 1`, double-quoted DCL principal) is in `deploy.sh`; the shell script still deploys with
`gcloud functions deploy --gen2`, never grants invoker to the service account, sets no concurrency limits, and
runs `bigquery_schema.sql` with a literal `your_project`. Three main.py defects break idempotency or the gate:
a shared `WRITE_TRUNCATE` staging table used by both entities, a dry-run path that skips BigQuery reads (so the
gate rehearses a different window and no warehouse de-duplication), and `day1_*` columns that are overwritten on
every re-observation. Two items in the brief turned out **not** to be defects: `first_seen_run` is already
excluded from the MERGE update list, and the ISO-8601 strings sent to `load_table_from_json` are accepted by
BigQuery as TIMESTAMP/DATE.

First-deploy expectation after the rewrite: one IAM iteration is still likely (Cloud Build service-account
permissions on projects created after 2024-05-03), which the rewritten `deploy.sh` pre-empts.

---

## 1. Documentation checks (the eight questions)

### 1.1 `gcloud run deploy NAME --function ENTRYPOINT --source .` vs `gcloud functions deploy --gen2`

Current canonical form (docs: https://docs.cloud.google.com/run/docs/deploy-functions):

```
gcloud run deploy FUNCTION \
    --source . \
    --function FUNCTION_ENTRYPOINT \
    --base-image BASE_IMAGE \
    --region REGION
```

`--base-image` is **required** on this path (the page lists `nodejs24, python314, go127, java25, dotnet10,
ruby40, php85` as examples; `python312` is still a valid base image). The same page: *"If you have existing
functions and need to use the gcloud functions deploy command, the Cloud Functions v2 API, or the
google_cloudfunctions2_function Terraform configuration for backward compatibility, see Deploy functions with the
gcloud functions deploy command."* — so `gcloud functions deploy --gen2` (deploy.sh:21) is **supported, not
deprecated**, but it is the compatibility path. gcloud 530's own help confirms the `--gen2` flag is live.

Differences that matter here (https://docs.cloud.google.com/run/docs/functions/comparison): functions created via
the Cloud Functions v2 API get **two** endpoints (`run.app` **and** `cloudfunctions.net`); functions created with
`gcloud run deploy --function` get only `run.app`. deploy.sh:25 reads `serviceConfig.uri` (the `cloudfunctions.net`
URL) and uses it as both Scheduler URI and OIDC audience. After migrating to the canonical form that attribute
does not exist; the URL must come from `gcloud run services describe FN --format 'value(status.url)'`.
Deployment IAM also differs: the canonical path needs Cloud Run Source Developer + Cloud Build + Artifact Registry
(https://docs.cloud.google.com/run/docs/deploying-source-code), and on projects created after **2024-05-03** the
default compute SA no longer has Editor, so Cloud Build needs `roles/run.builder` granted explicitly:

```
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/run.builder
```

Verdict: rewrite deploy.sh in canonical form; the user's risk-table statement is correct and *not yet applied*.

### 1.2 `add-invoker-policy-binding` vs `gcloud run services add-iam-policy-binding --role roles/run.invoker`

gcloud 530 help and https://docs.cloud.google.com/sdk/gcloud/reference/functions/add-invoker-policy-binding:
*"For Cloud Functions (2nd gen), this adds the Cloud Run Invoker binding to the IAM policy of the specified
function's underlying Cloud Run service."* So both commands produce the same binding for a v2-API function. For a
service created with `gcloud run deploy --function` the Cloud Run form is the one documented
(https://docs.cloud.google.com/run/docs/triggering/using-scheduler):

```
gcloud run services add-iam-policy-binding SERVICE \
   --member=serviceAccount:SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com \
   --role=roles/run.invoker
```

**deploy.sh contains neither command** (lines 7–10 grant only BigQuery roles). Cloud Scheduler docs
(https://docs.cloud.google.com/scheduler/docs/http-target-auth): *"you must grant the Cloud Run Invoker
(roles/run.invoker) IAM role to the service account"*; the job would fail with 403 on its first Monday.
The same page: the Cloud Scheduler service agent needs `roles/cloudscheduler.serviceAgent`, granted automatically
unless the API was enabled before 2019-03-19.

### 1.3 `--max-instances 1` and `--concurrency 1` for a Scheduler retry overlapping a slow attempt

Facts:

- Cloud Run request timeout (https://docs.cloud.google.com/run/docs/configuring/request-timeout): default 300 s,
  max 3600 s; at timeout *"the network connection to the service will be closed and an error 504 is returned"*
  but *"the container instance that served the request is not terminated. The container or code might keep
  processing the terminated request."*
- functions-framework (Python) runs gunicorn with `workers = WORKERS or 1`, `threads = THREADS or cpu_count*4`
  (https://raw.githubusercontent.com/GoogleCloudPlatform/functions-framework-python/main/src/functions_framework/_http/gunicorn.py).
  So one instance has ≥ 4 worker threads regardless of Cloud Run's `--concurrency`.
- Scheduler retry (https://docs.cloud.google.com/scheduler/docs/reference/rest/v1/projects.locations.jobs):
  `attemptDeadline` for HTTP targets must be in **[15 s, 30 min]** (default 3 min); retries start after
  `minBackoffDuration` (default 5 s), doubling `maxDoublings` (5) times.
- At the max-instances limit (https://docs.cloud.google.com/run/docs/about-instance-autoscaling): *"Requests will
  pend for up to 3.5 times average startup time of container instances of this service, or 10 seconds, whichever
  is greater"*, then **429**; and *"Cloud Run might, for a short period of time, create more instances than are
  specified in the maximum instances setting"* (traffic surges, deployments).

Consequences for the current config (`--timeout 540s`, `--attempt-deadline 600s`, 3 retries):

1. Scheduler's deadline (600 s) is longer than Cloud Run's (540 s), so the 504 arrives first; Scheduler retries
   5 s later. Cloud Run has already released the request slot, so with `--concurrency 1` the retry is routed to the
   **same** idle-looking instance, where the orphaned thread of attempt 1 may still be running the MERGE or the
   watermark write. `--max-instances 1 --concurrency 1` does **not** serialize this case. Only an application-level
   lease (a `lock_until` column in `report_state`, acquired with a single atomic `UPDATE ... WHERE lock_until IS
   NULL OR lock_until < CURRENT_TIMESTAMP()`) or a deadline budget inside the function does.
2. The two entity jobs fire in the same minute (deploy.sh:29). With `--concurrency 1 --max-instances 1` the second
   request pends ≤ max(3.5 × avg startup, 10 s) — a cold start of this function is ~3–6 s, so roughly 10–20 s —
   then gets 429, Scheduler retries after 5 s, 10 s, 20 s, and gives up after 3 attempts. If the SEALSQ run takes
   longer than ~1 min (HubSpot paging + two BigQuery jobs can), **the ICALPS job fails for the week**. Offsetting
   the schedules (`0 7` / `20 7`) or dropping the global serialization in favour of per-entity staging tables
   removes this.
3. Max-instances can be exceeded briefly during a deploy; a deploy at 07:00 Monday is the only realistic overlap.

Verdict: keep `--max-instances 1 --concurrency 1` as defence in depth, but the race is closed by (a) per-run
staging tables, (b) a lease row, (c) offset schedules. See G03/G04.

### 1.4 Secret Manager `:latest` vs pinned version

https://docs.cloud.google.com/run/docs/configuring/services/secrets: *"Environment variables are resolved at
instance startup time, so if you use this method, Google recommends that you pin the secret to a particular version
instead of using latest as the version."* Volume-mounted secrets, by contrast, are fetched *"with the latest
version"* on every read. deploy.sh:24 uses `HUBSPOT_TOKEN=hubspot-token:latest` as an env var. Because the service
scales to zero between weekly runs, each Monday's instance is fresh and picks up whatever is `latest` — the
practical risk is a rotation while an instance is warm (same hour) and the lack of a reviewable pin. The rewrite
captures the version number printed by `gcloud secrets versions add` and passes `hubspot-token:N`; rotation is a
`make secret` + `make deploy`.

### 1.5 BigQuery DCL `GRANT` quoting of `serviceAccount:` principals

https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-control-language shows the principal as a
string literal — all examples use double quotes:

```
GRANT `roles/bigquery.dataViewer` ON SCHEMA `myProject`.myDataset
TO "user:raha@example-pet-store.com", "user:sasha@example-pet-store.com"
```

But the lexical rules (https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/lexical) state: *"Both
string and bytes literals must be quoted, either with single ( ' ) or double ( " ) quotation marks"*. deploy.sh:9

```
bq --project_id=$PROJECT query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO 'serviceAccount:${SA}'"
```

is therefore **valid GoogleSQL as written**; the risk-table claim "principal must be double-quoted" is not
supported by the documentation (a skeptic can refute or confirm with one `bq query --dry_run`). The more likely
cause of a past failure is ordering: the GRANT runs at step 1, before the dataset is guaranteed to exist (step 3
creates only tables, never the dataset). The rewrite creates the dataset `IF NOT EXISTS` first and keeps double
quotes to match the documented examples.

### 1.6 Scheduler `--attempt-deadline` max and OIDC audience

- `attemptDeadline` HTTP range **[15 s, 30 min]**, default 3 min (REST reference above). `600s` is legal.
- `--oidc-token-audience`: *"If not specified, the URI specified in target will be used"* (gcloud 530 help and
  reference). http-target-auth adds: *"if ... your function expects arguments in form of URL parameters (for
  example, my_function?key=value) you must ensure the OIDC Audience (aud) field does not contain the URL
  parameters."* deploy.sh:30 passes `--oidc-token-audience "$URL"` explicitly while the URI carries `?entity=` —
  **correct**. Cloud Run accepts by default an audience equal to the service's `run.app` URL
  (https://docs.cloud.google.com/run/docs/configuring/custom-audiences); a v2-API function also accepts its
  `cloudfunctions.net` URL. After the canonical rewrite the audience must be the `run.app` URL, so the Scheduler
  jobs must be **updated**, which the current `create ... || true` (deploy.sh:31) never does.

### 1.7 main.py — line-by-line findings

| Line(s) | Finding | Status |
|---|---|---|
| 22–27 | `logging.basicConfig(level=INFO)` → plain-text lines; Cloud Logging gets no severity/structured fields. | gap (G14) |
| 29 | `PORTAL_ID` default `9201667` hard-coded (and in deploy.sh:23). Acceptable for a deal URL, but CONVENTIONS says ids come from `.env`. | low |
| 49–68 | `hot_score`: exercised offline → `(88.9, True)` for a Lattice-like row, `(None, None)` for ICALPS; sigmoid at zero features 0.15. `datetime.fromisoformat(cd.replace("Z","+00:00"))` handles `.123Z` on Python ≥ 3.11 (runtime 3.12). | ok |
| 73–83 | HubSpot search: `limit: 200` is the documented max; one `sorts` rule (the only one allowed); ISO-8601 filter values are accepted (HubSpot's guide examples use epoch ms, ISO strings also work for datetime properties); hard cap **10,000 results per query** (https://developers.hubspot.com/docs/api-reference/2026-03/crm/search-the-crm.md) — a deep replay silently stops at 10k; search is rate-limited to 5 req/s and *"it may take a few moments for newly created or updated CRM objects to appear in search results"* — the 5-minute overlap absorbs this. No 429/5xx retry. | note / G15 |
| 107–111 | `read_watermark`: default `now - FIRST_RUN_DAYS` when no row; `.replace(tzinfo=utc)` harmless on an already-aware value. | ok |
| 113–118 | `write_watermark`: unconditional MERGE to `run_ts`, even when zero deals — correct (no deals ≠ no progress). Needed for replay (README:12). | ok |
| 120–130 | `merge_rows`: **shared** `new_deals_staging` with `WRITE_TRUNCATE`; two concurrent runs (SEALSQ + ICALPS at the same minute, or a retry overlapping an orphan) truncate each other's rows between load and MERGE; the loser still advances its watermark → rows lost until a manual replay. | **gap G03** |
| 124 | `load_table_from_json(... schema=new_deals.schema)`: row values `createdate` `"2026-09-21T10:13:50.123Z"`, `first_seen_run` `"2026-10-05T07:00:00+00:00"`, `closedate` `"2026-12-31"` — all accepted: JSON loads accept `T` separator, `Z` or UTC offset, ≤ 6 fractional digits; DATE must be `YYYY-MM-DD` (https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-json, "Data types"). | **not a gap** |
| 126 | Update list excludes `deal_id` **and `first_seen_run`** → first_seen_run is preserved. The brief's claim "first_seen_run overwritten" is refuted. But `day1_hot_score`, `day1_hot_flag`, `duplicate_*` **are** overwritten on every re-observation (overlap window, or event-mode write followed by the weekly window) → "day-1" drifts to "latest". | **gap G06** |
| 132–136 | `recent_names`: declares `@e` but the SQL never references it; `{days}` is f-string-interpolated instead. If BigQuery rejects an unused parameter the `except` swallows it, logs a warning and returns `{}` — warehouse de-duplication silently off on every run; if BigQuery ignores it, it is dead code. Either way remove it. Also the dict comprehension keeps **one** deal_id per key, so when the current deal is itself in the warehouse (any re-observation) the twin can be masked — reproduced offline. | **gap G07** |
| 139–141 | `name_key` → `latticekeystonec0asic`, `latticesemiconductorcorp` — note the two differ when `final_customer` is set on one twin and not the other; the duplicate rule is a heuristic, documented as such (README:33). | note |
| 143–165 | `shape`: 31 keys match the 31 schema columns exactly (checked). `owner` falls back to the raw id. | ok |
| 172–177 | `dry` → `client = None` → no watermark read (uses `now - FIRST_RUN_DAYS`), `known = {}`. The dry payload is **not** a rehearsal of the live run (different window, no warehouse de-dup), although README:38 and the risk table make `dry_run=1` the gate. BigQuery reads are side-effect-free; the gate should block writes only. | **gap G05** |
| 179–182 | Event mode: the service is `--no-allow-unauthenticated`; a HubSpot workflow webhook cannot present a Google OIDC token → the path README:23 promises is unreachable as deployed. If `entity` is omitted/wrong the deal is silently dropped with HTTP 200. | **gap G08** |
| 188 | `others = [d for d in found if d not in deals]` — O(n·m) dict equality; correct (same objects), just wasteful; use an id set. | low G16 |
| 196 | watermark advanced only in window mode and only after MERGE — correct. | ok |
| 200–203 | Delivery webhook: failure is logged and reported in the payload but the run still returns 200 and the watermark is already advanced → the XLSX/email for that week is lost unless replayed. Acceptable for A (n8n/B owns delivery), state it. | note L9 |

### 1.8 deploy.sh and bigquery_schema.sql placeholders, region

- `PROJECT=your_project` (deploy.sh:4) with no fail-loud check; CONVENTIONS.md requires `.env` + loud failure.
- `bq query ... < bigquery_schema.sql` (deploy.sh:18) executes a file whose identifiers are literally
  `your_project.hubspot.*` (schema:2,5,17–18) — `$PROJECT`/`$DATASET` are **never substituted**; step 3 fails with
  `Not found: Project your_project` (or, if someone edits only deploy.sh, creates tables in the wrong place).
- Nothing creates the dataset; GRANT (step 1) precedes tables (step 3).
- No `gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
  secretmanager.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com`.
- `gcloud iam service-accounts create ... || true` and `gcloud scheduler jobs create ... || true` hide real
  errors and make the second run a no-op (jobs never updated). `gcloud secrets versions add` runs on **every**
  re-run (a new version per run; harmless but noisy).
- Scheduler jobs are created **enabled**; the dry-run gate is printed as an `echo` afterwards (deploy.sh:33).
- Region `europe-west6`: listed for Cloud Run (Tier 2 pricing, "Low CO2";
  https://docs.cloud.google.com/run/docs/locations), Cloud Scheduler
  (https://docs.cloud.google.com/scheduler/docs/locations) and Cloud Build
  (https://docs.cloud.google.com/build/docs/locations). The region choice is fine; Tier 2 costs slightly more
  than e.g. `europe-west1` — negligible at one run a week.
- No `.gcloudignore`; the source upload includes `n8n_NewDeals_Delivery.json`, README and deploy.sh (harmless).

---

## 2. Gaps (testable claims)

| id | sev | claim | evidence | fix |
|---|---|---|---|---|
| G01 | high | `deploy.sh` step 3 cannot succeed: the SQL it pipes to `bq` names `your_project.hubspot` literally. | deploy.sh:18; bigquery_schema.sql:2,5,17,18 | `${PROJECT}`/`${DATASET}` placeholders rendered with `envsubst`; `CREATE SCHEMA IF NOT EXISTS` first. |
| G02 | high | The function SA is never granted `roles/run.invoker`; both Scheduler jobs get 403 on first fire. | deploy.sh:7–10, 20–31; http-target-auth doc | `gcloud run services add-iam-policy-binding $FN --member serviceAccount:$SA --role roles/run.invoker`. |
| G03 | high | Shared `new_deals_staging` + `WRITE_TRUNCATE` loses one entity's rows when the two jobs (same minute) or a retry and an orphaned attempt overlap; the loser still advances its watermark. | main.py:123–130, deploy.sh:29 (identical schedule), no concurrency flags in deploy.sh:21–24 | Per-run staging table `new_deals_staging_${entity}_${run_ts}` with `expires` (DROP after MERGE); schedules offset. |
| G04 | medium | `--max-instances 1 --concurrency 1` does not serialize a Scheduler retry after a 504 (orphan thread keeps running inside the same gunicorn process) and makes the same-minute second job fail with 429 after 3 retries whenever the first run exceeds ~1 min. | request-timeout doc; functions-framework gunicorn `threads=cpu*4`; autoscaling doc (pend ≤ max(3.5×startup,10 s) then 429); Scheduler minBackoff 5 s | `report_state.lock_until` lease acquired by one atomic UPDATE; deadline budget inside the function (stop before 540 s); offset schedules `0 7` / `20 7`. |
| G05 | high | `dry_run=1` does not rehearse the live run: it skips the watermark read (uses now−7d) and warehouse de-dup (`known={}`), so the gate's payload differs from Monday's. | main.py:176–177, 184; README:38 | Always build the BigQuery client; `dry` guards `merge_rows`, `write_watermark` and the delivery POST only. |
| G06 | medium | `day1_hot_score`/`day1_hot_flag` are overwritten on re-observation (5-min overlap; event write then weekly window), so "day-1" becomes "latest". | main.py:126 excludes only `deal_id`, `first_seen_run` | Exclude `day1_*` from the UPDATE list (optionally add `latest_hot_score`). |
| G07 | medium | `recent_names` declares `@e` unused and keeps one deal per key: either BigQuery rejects the call (→ `{}` every run, warehouse de-dup silently off) or it is dead code; and the current deal can mask its own twin. | main.py:133–136, 151; offline reproduction | Drop the parameter; return `key → [deal_ids]`; exclude `did` when flagging. Probe: `bq query --parameter=e::x '<same SQL>'`. |
| G08 | medium | Event mode is unreachable: HubSpot workflow webhooks cannot send Google OIDC tokens to a `--no-allow-unauthenticated` service; README promises near-real-time. | deploy.sh:22; README:23–24; main.py:179 | Declare out of scope for A (keep code), or relay through n8n (B) / a public ingress validating HubSpot v3 signatures. |
| G09 | medium | `deploy.sh` is neither idempotent nor fail-loud: `|| true` hides SA/Scheduler errors, Scheduler jobs are never updated (URL change on canonical migration breaks them), placeholder project id passes, no API enablement, no `roles/run.builder` for the Cloud Build SA (projects after 2024-05-03). | deploy.sh:4,8,13–14,31; deploying-source-code doc | Rewrite: `.env` check, `services enable`, create-or-update for every resource, builder role. |
| G10 | medium | Deploy form is the compatibility path (`gcloud functions deploy --gen2`), not the canonical `gcloud run deploy --function --base-image`; the URL it reads (`serviceConfig.uri`, cloudfunctions.net) will not exist after migration. | deploy.sh:21–25; deploy-functions and comparison docs | Canonical deploy; URL from `gcloud run services describe --format 'value(status.url)'`. |
| G11 | low | `hubspot-token:latest` is resolved at instance start; docs recommend pinning. Weekly scale-to-zero makes the exposure small. | deploy.sh:24; secrets doc | Pin to the version number returned by `versions add`; `make secret` prints it. |
| G12 | low | Single-quoted DCL principal is valid GoogleSQL; the risk-table "must be double-quoted" is unsupported. The step-order (GRANT before dataset exists) is the plausible past failure. | lexical doc; deploy.sh:9 vs :18 | Create dataset first; keep double quotes to match docs. |
| G13 | low | No per-run audit record (only `report_state.updated_at`, row `last_seen_run`, 30-day logs). | bigquery_schema.sql | `new_deals_runs` table written at the end of every run (and on failure). |
| G14 | low | Plain-text logs without `severity`; no `run_id` correlation. | main.py:27 | JSON lines (`{"severity","message","entity","run_ts"}`) — Cloud Run parses them. |
| G15 | low | No in-process retry on HubSpot 429/5xx; 10k-result cap on deep replays. | main.py:81; HubSpot search guide | `requests` Retry adapter; chunked replay in `make replay`. |
| G16 | low | `others` built with list membership on dicts (O(n·m)). | main.py:188 | id set. |
| G17 | low | Scheduler jobs are enabled at creation, before any dry run. | deploy.sh:29–31 | Create then `gcloud scheduler jobs pause`; `make enable` after `make dry` passes. |

Refuted / verified-OK items from the brief: TIMESTAMP/DATE string parsing in `load_table_from_json` (accepted),
`first_seen_run` overwritten (not overwritten), DCL double-quote requirement (single quotes are legal).
Unverifiable here (no BigQuery auth): whether BigQuery rejects an unused named parameter — G07 is worded so that
either outcome leads to the same fix.

---

## 3. Lane cells for Scenario A (fixed layer list)

| id | layer | mechanism in A | idempotent |
|---|---|---|---|
| L0 | Code acquisition & deploy unit | `git clone` of CloudBQ; deploy unit = `cloud_function_new_deals/` uploaded by `gcloud run deploy new-deals-report --source . --function new_deals_report --base-image python312 --region europe-west6` (Cloud Build in-region, Artifact Registry). | yes (same source → new revision, same URL) |
| L1 | Identity to BigQuery | Dedicated SA `new-deals-fn@` as the revision identity; ADC inside the container; `roles/bigquery.jobUser` on project + `GRANT roles/bigquery.dataEditor ON SCHEMA` dataset. | yes (bindings are set-like) |
| L2 | Secrets (HubSpot token) | Secret Manager `hubspot-token`, `roles/secretmanager.secretAccessor` for the SA, injected as env `HUBSPOT_TOKEN` via `--set-secrets hubspot-token:N` (pinned). | conditional (version pinned; `latest` resolves at instance start) |
| L3 | Trigger & schedule | Two Cloud Scheduler HTTP jobs (`0 7 * * 1` / `20 7 * * 1`, Europe/Zurich), GET `${URL}?entity=…`, OIDC SA token with `aud=${URL}`, attempt-deadline 600 s, 3 retries; created paused, resumed after the gate. | yes (create-or-update) |
| L4 | Extraction window | `read_watermark` (`report_state`, `NEW_DEALS_{entity}`; default now−7d) → HubSpot `/crm/v3/objects/deals/search` with `createdate GTE watermark−5min, LT run_ts`, 200/page, sorted ascending. | yes (createdate immutable; half-open window) |
| L5 | Scoring arithmetic | `hot_score()` in Python: fixed `W`, `BIAS`, `THRESHOLD`, `CR`, `MAXC`; deterministic for a given row and `run_ts`; covered by `tests/test_hot_score.py` vectors shared with the JS scorer. | yes (pure function) |
| L6 | Shaping & duplicate flag | `shape()`: 31 columns, `name_key`, in-batch twins across all pipelines + warehouse twins (`recent_names`, 90 d, all entities). | conditional (warehouse de-dup only once G07 is fixed and in dry mode once G05 is fixed) |
| L7 | Load → MERGE | `load_table_from_json` into a per-run staging table, `MERGE new_deals ON deal_id` (UPDATE excludes `deal_id, first_seen_run, day1_*`), DROP staging. | yes after G03/G06 (today: no, shared staging) |
| L8 | Watermark advance | `MERGE report_state` to `run_ts` after a successful MERGE, window mode only; lease `lock_until` released. | yes (monotonic in practice; explicit rewind for replay) |
| L9 | Delivery (XLSX/email) | Function POSTs the payload to `DELIVERY_WEBHOOK_URL` (n8n webhook → XLSX → email). Failure is logged, not retried; BigQuery remains the truth. | conditional (n8n endpoint reachable; otherwise re-send from `new_deals_last_7d`) |
| L10 | Write-back to HubSpot | None in A (read-only token). Scenario C's remote JS does it; A exposes the view it reads. | n/a (not performed) |
| L11 | Dry-run gate | `make dry` → `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL?entity=SEALSQ&dry_run=1"` for both entities; asserts `rows_written == 0`; same window and de-dup as live after G05. | yes (reads only) |
| L12 | Replay / backfill | `make replay ENTITY=SEALSQ FROM=2026-09-01T00:00:00Z`: `UPDATE report_state SET watermark=…` then invoke; windows chunked below HubSpot's 10k cap. | yes (MERGE on deal_id) |
| L13 | Audit trail | `new_deals_runs` row per run (run_ts, entity, mode, window, counts, duration, status, error) + Cloud Logging JSON lines; Scheduler job history. | yes (append; one row per run_ts) |
| L14 | Access control | SA: jobUser (project), dataEditor (dataset), secretAccessor (one secret), run.invoker (one service); humans: run.invoker for dry runs, dataViewer on the dataset/view for Breeze & BI; HubSpot private app scopes `crm.objects.deals.read, crm.schemas.deals.read, crm.objects.owners.read`. | yes |
| L15 | Concurrency & retry safety | `--max-instances 1 --concurrency 1` as defence; `report_state.lock_until` lease; per-run staging; attempt-deadline > function timeout; schedules offset; retries 3 with 5 s min backoff. | yes after G03/G04 (today: no) |
| L16 | Observability | Cloud Logging (JSON lines with severity, entity, run_ts), Cloud Run request logs/metrics, Scheduler job status, `new_deals_runs` probe via `bq query`. | yes |
| L17 | Cost & scale-to-zero | Scale to zero between runs (min-instances 0), 512 Mi, CPU throttled; ~1–2 min compute/week; BigQuery: tiny MERGE scans; Scheduler 3 free jobs; Tier-2 region pricing. | yes |

Parity words (for the cross-scenario YAML): the layers that stay **Parallel** across A/B/C are L4 (window on
immutable `createdate` from the same watermark table), L5 (same constants, same vectors), L7 (MERGE on `deal_id`),
L8 (watermark table), L11 (dry gate) and L12 (replay by rewinding the watermark) — provided every orchestrator
reads and writes `hubspot.report_state` / `hubspot.new_deals` and nothing local.

---

## 4. Building-block tree for finishing A

```
CloudBQ/
│   .env.example                              new    PROJECT, REGION, DATASET, FN, SA, SECRET_VERSION, DELIVERY_WEBHOOK_URL, PORTAL_ID
├───cloud_function_new_deals/
│   │   main.py                               modify G03 G05 G06 G07 G14 G15 G16 + lease + run audit; imports scoring.py
│   │   scoring.py                            new    hot_score + constants extracted (same arithmetic everywhere)
│   │   deploy.sh                             modify canonical gcloud run deploy --function; IAM; secrets pinned; schema render; jobs paused
│   │   bigquery_schema.sql                   modify ${PROJECT}/${DATASET} placeholders; CREATE SCHEMA; report_state.lock_until; new_deals_runs
│   │   Makefile                              new    check-env enable-apis iam secret tables deploy invoker dry enable pause replay logs probe
│   │   .gcloudignore                         new    tests/, docs, README, n8n json out of the source upload
│   │   requirements.txt                      existing
│   │   requirements-dev.txt                  new    pytest
│   │   README.md                             modify canonical commands, gate sequence, event mode marked out of scope
│   │   n8n_NewDeals_Delivery.json            existing (scenario B owns it)
│   └───tests/
│           conftest.py                       new    stubs requests/functions_framework; env fixtures
│           test_hot_score.py                 new    vectors from tests/vectors/hot_score_v1.json
│           test_shape.py                     new    dup rules, 31-column contract, sort order
│           vectors/hot_score_v1.json         new    shared with hot_deals_score.js (scenario C)
├───.github/workflows/ci.yml                  new (optional)  bash -n, py_compile, pytest; no deploy without WIF
└───docs/
        RUNBOOK_A.md                          new    first deploy, IAM iterations, gate, replay, pitfalls (this report distilled)
        architecture.yaml                     modify add scenario A nodes/layers for the tree visualizer
```

Recipes (one per block) are listed in the structured summary; each is self-contained for
`aider --message` with the files to `/add`, and each ends with the commit trailer `Recipe: <path>`.

### 4.1 Sketch of the rewritten deploy.sh (core)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f ../.env ] && set -a && . ../.env && set +a
for v in PROJECT REGION DATASET FN SA_NAME; do
  [[ -n "${!v:-}" && "${!v}" != your_* ]] || { echo "set $v in .env (placeholder found)"; exit 2; }
done
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
PN=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com --project "$PROJECT"

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" --display-name "new deals report function"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${PN}-compute@developer.gserviceaccount.com" --role roles/run.builder >/dev/null

bq --project_id="$PROJECT" query --use_legacy_sql=false \
  "CREATE SCHEMA IF NOT EXISTS \`${PROJECT}.${DATASET}\` OPTIONS(location='EU')"
bq --project_id="$PROJECT" query --use_legacy_sql=false \
  "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""
PROJECT="$PROJECT" DATASET="$DATASET" envsubst '${PROJECT} ${DATASET}' < bigquery_schema.sql | \
  bq --project_id="$PROJECT" query --use_legacy_sql=false

if ! gcloud secrets describe hubspot-token --project "$PROJECT" >/dev/null 2>&1; then
  printf '%s' "$HUBSPOT_TOKEN" | gcloud secrets create hubspot-token --project "$PROJECT" --data-file=-
fi
SECRET_VERSION=${SECRET_VERSION:-$(gcloud secrets versions list hubspot-token --project "$PROJECT" --filter state=enabled --format 'value(name)' --limit 1)}
gcloud secrets add-iam-policy-binding hubspot-token --project "$PROJECT" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null

gcloud run deploy "$FN" --project "$PROJECT" --region "$REGION" --source . \
  --function new_deals_report --base-image python312 \
  --no-allow-unauthenticated --service-account "$SA" \
  --timeout 540 --memory 512Mi --max-instances 1 --concurrency 1 \
  --set-env-vars "^|^BQ_PROJECT=$PROJECT|BQ_DATASET=$DATASET|OVERLAP_MINUTES=5|FIRST_RUN_DAYS=7|PORTAL_ID=${PORTAL_ID}|DELIVERY_WEBHOOK_URL=${DELIVERY_WEBHOOK_URL:-}" \
  --set-secrets "HUBSPOT_TOKEN=hubspot-token:${SECRET_VERSION}"
gcloud run services add-iam-policy-binding "$FN" --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:$SA" --role roles/run.invoker >/dev/null
URL=$(gcloud run services describe "$FN" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')

declare -A AT=([SEALSQ]="0 7 * * 1" [ICALPS]="20 7 * * 1")
for E in SEALSQ ICALPS; do
  ARGS=(--project "$PROJECT" --location "$REGION" --schedule "${AT[$E]}" --time-zone Europe/Zurich
        --uri "${URL}?entity=${E}" --http-method GET --oidc-service-account-email "$SA" --oidc-token-audience "$URL"
        --attempt-deadline 600s --max-retry-attempts 3)
  if gcloud scheduler jobs describe "new-deals-$E" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "new-deals-$E" "${ARGS[@]}"
  else
    gcloud scheduler jobs create http "new-deals-$E" "${ARGS[@]}" && gcloud scheduler jobs pause "new-deals-$E" --project "$PROJECT" --location "$REGION"
  fi
done
echo "URL=$URL  → make dry, then make enable"
```

### 4.2 Sketch of the main.py changes (per-run staging, lease, gate)

```python
def merge_rows(client, rows, entity, run_ts):
    if not rows: return 0
    from google.cloud import bigquery
    tmp = table(f"new_deals_staging_{entity.lower()}_{run_ts:%Y%m%d%H%M%S}")
    schema = client.get_table(table("new_deals")).schema
    client.load_table_from_json(rows, tmp, job_config=bigquery.LoadJobConfig(
        write_disposition="WRITE_TRUNCATE", autodetect=False, schema=schema)).result()
    cols = [f.name for f in schema]
    frozen = {"deal_id", "first_seen_run", "day1_hot_score", "day1_hot_flag"}
    upd = ", ".join(f"{c} = s.{c}" for c in cols if c not in frozen)
    try:
        client.query(f"""MERGE `{table('new_deals')}` t USING `{tmp}` s ON t.deal_id = s.deal_id
            WHEN MATCHED THEN UPDATE SET {upd}
            WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.'+c for c in cols)})""").result()
    finally:
        client.delete_table(tmp, not_found_ok=True)
    return len(rows)

def acquire_lease(client, entity, run_ts, minutes=12):
    from google.cloud import bigquery
    job = client.query(f"""UPDATE `{table('report_state')}` SET lock_until = TIMESTAMP_ADD(@ts, INTERVAL {minutes} MINUTE)
        WHERE report_id = @rid AND (lock_until IS NULL OR lock_until < @ts)""",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("rid", "STRING", f"NEW_DEALS_{entity}"),
            bigquery.ScalarQueryParameter("ts", "TIMESTAMP", run_ts)]))
    job.result(); return job.num_dml_affected_rows == 1   # a missing row (first run) is inserted by the caller first
```

The gate becomes: `client = bq()` always; `if not dry: written = merge_rows(...); write_watermark(...)`; the
delivery POST stays behind `not dry`. In dry mode the payload gains `"dry_run": true`.

### 4.3 Makefile targets (the gate order)

```
check-env → enable-apis → iam → secret → tables → deploy → invoker → dry (both entities, asserts rows_written==0 and dry_run==true) → enable
pause | replay ENTITY= FROM= | logs | probe (bq query report_state, new_deals_runs, new_deals_last_7d counts)
```

---

## 5. Open questions (with the default the plan proceeds under)

1. Does dataset `hubspot` already exist in `$PROJECT` (the HubSpot sync dataset) and in which location (EU)? → default: exists, EU; `CREATE SCHEMA IF NOT EXISTS` is a no-op.
2. Was the project created after 2024-05-03 (Cloud Build needs `roles/run.builder`)? → default: grant it regardless; the binding is idempotent.
3. Keep event mode in A? → default: keep the code path, mark "not deployed" in README; a relay belongs to B.
4. Accept offsetting ICALPS to 07:20 Europe/Zurich? → default: yes.
5. Pin the secret version (redeploy on rotation) or keep `latest`? → default: pin.
6. `amount_kusd` holds `amount_in_home_currency` as stored (USD, not kUSD?) — name vs unit? → default: keep the column, document the unit from a live probe.
7. Should warehouse de-duplication look at the full HubSpot `deals` sync table rather than only `new_deals` (90 d)? → default: `new_deals` only in A; note as a BigQuery-side improvement for C.
8. Who runs the first deploy (Owner in Cloud Shell)? → default: project Owner, Cloud Shell, from the clone.

## 6. Sources

- https://docs.cloud.google.com/run/docs/deploy-functions
- https://docs.cloud.google.com/run/docs/functions/comparison
- https://docs.cloud.google.com/functions/docs/deploy
- https://docs.cloud.google.com/sdk/gcloud/reference/functions/add-invoker-policy-binding
- https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy
- https://docs.cloud.google.com/run/docs/triggering/using-scheduler
- https://docs.cloud.google.com/scheduler/docs/http-target-auth
- https://docs.cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http
- https://docs.cloud.google.com/scheduler/docs/reference/rest/v1/projects.locations.jobs
- https://docs.cloud.google.com/scheduler/docs/locations
- https://docs.cloud.google.com/run/docs/about-instance-autoscaling
- https://docs.cloud.google.com/run/docs/configuring/max-instances
- https://docs.cloud.google.com/run/docs/configuring/request-timeout
- https://docs.cloud.google.com/run/docs/configuring/services/secrets
- https://docs.cloud.google.com/run/docs/configuring/custom-audiences
- https://docs.cloud.google.com/run/docs/deploying-source-code
- https://docs.cloud.google.com/run/docs/locations
- https://docs.cloud.google.com/build/docs/locations
- https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-control-language
- https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/lexical
- https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-json
- https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-types
- https://raw.githubusercontent.com/GoogleCloudPlatform/functions-framework-python/main/src/functions_framework/_http/gunicorn.py
- https://developers.hubspot.com/docs/api-reference/2026-03/crm/search-the-crm.md
