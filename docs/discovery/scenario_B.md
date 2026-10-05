# Scenario B — n8n on Cloud Run + workflow JSON (discovery report)

Date: 2026-10-05 · Analyst: discovery sub-agent (Scenario B) · Repos read: `/home/user/CloudBQ` (branch `claude/cloud-run-bigquery-pipeline-e94ziy`), `/home/user/IC-DBT-BQ`, `/home/user/wkayaobama/mir-load`, `/home/user/wkayaobama/wkayaobama-skills`. No repository file was changed.

Scope: how to run n8n on Google Cloud Run the way n8n and Google currently document it, what the n8n BigQuery and HubSpot nodes can and cannot do, and what it costs — then two JSON scenarios mapped onto the fixed layer list L0–L17:

- **B1 — n8n delivers only.** The Cloud Run function (`cloud_function_new_deals/main.py`) keeps extraction, scoring, MERGE and watermark; it POSTs the payload to the n8n webhook; n8n builds the XLSX and emails it. This is what `cloud_function_new_deals/n8n_NewDeals_Delivery.json` already does.
- **B2 — n8n owns the whole pipeline.** Schedule/webhook trigger → HubSpot search → Code node hot score (port of `hot_score()`) → BigQuery MERGE → watermark → XLSX → email. The function is retired.

Every claim below has either a `file:line` in the repos or a URL. Where a fact could not be verified from a primary source it is marked **[unverified]**.

---

## 0 · Evidence inventory

### 0.1 Repo facts used

| Fact | Evidence |
|---|---|
| Idempotency model: immutable `createdate`, half-open window `[watermark − overlap, run_ts)`, MERGE on `deal_id`, watermark advances only after MERGE | `main.py:7-11`, `main.py:184-196`, `README.md:64-69` |
| Hot score v1 constants and arithmetic (`W`, `BIAS`, `THRESHOLD`, `CR`, `MAXC`, `log1p`, logistic) | `main.py:41-68` |
| HubSpot search body: `createdate GTE/LT` ISO strings, `properties`, sort ASC, `limit 200`, `after` paging | `main.py:73-83` |
| Pipelines and owners lookups (label maps) | `main.py:86-99` |
| BigQuery: parameterised watermark read/MERGE, staging load job `WRITE_TRUNCATE` then MERGE, 90-day `recent_names` | `main.py:107-136` |
| Shaping, `name_key`, duplicate rule, row contract | `main.py:139-165`, `README.md:82-89` |
| Delivery: `requests.post(url, json=payload, timeout=30)`, failure only logged, no auth header, no retry | `main.py:200-203` |
| Dry-run gate `?dry_run=1` (no BigQuery client at all) | `main.py:173-177` |
| Deploy: gen2 function, Secret Manager `hubspot-token:latest`, `--no-allow-unauthenticated`, Scheduler OIDC `0 7 * * 1` Europe/Zurich, 3 retries | `deploy.sh:21-31` |
| Tables and view | `bigquery_schema.sql` |
| n8n delivery JSON: Webhook (`POST /new-deals`, `responseMode: onReceived`, **no authentication**) → Split Out `body.rows` → Code (column order) → Convert to File XLSX → Email Send (SMTP placeholders `n8n@example.com`, `sales-ops@example.com`, credential id `REPLACE_WITH_CREDENTIAL_ID`), `active: false`, timezone Europe/Zurich | `n8n_NewDeals_Delivery.json:5-10, 23, 39, 52-58, 71-93, 142-146` |
| Project conventions: shared truth in BigQuery (never in an n8n static variable), no secrets in git, same arithmetic everywhere with offline test vectors, gate before live | `CONVENTIONS.md` |

### 0.2 Primary sources (fetched 2026-10-05)

- n8n docs — Deploy to Google Cloud Run (easy mode / durable mode, exact `gcloud` commands, caveats): https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/deploy-to-google-cloud-run.md
- Google codelab "Deploying and Running n8n on Google Cloud Run": https://codelabs.developers.google.com/n8n-cloud-run
- Google Cloud blog "Deploy n8n on Cloud Run": https://cloud.google.com/blog/topics/developers-practitioners/deploy-n8n-on-cloud-run
- n8n env vars — deployment: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/deployment.md
- n8n env vars — endpoints (`N8N_ENDPOINT_HEALTH`, `WEBHOOK_URL` deprecated → `N8N_WEBHOOK_URL`): https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/endpoints.md
- n8n env vars — database: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/database.md
- n8n env vars — executions: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/executions.md
- n8n durable scheduler (2.36+): https://docs.n8n.io/deploy/host-n8n/configure-n8n/durable-scheduler.md and https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/scheduler.md
- n8n task runners (Code node): https://docs.n8n.io/deploy/host-n8n/configure-n8n/set-up-task-runners.md
- n8n Code node modules: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/configuration-examples/enable-modules-in-code-node.md
- n8n SSRF protection: https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/ssrf-protection.md
- n8n Server CLI (import/export/publish): https://docs.n8n.io/deploy/host-n8n/configure-n8n/use-the-command-line.md
- n8n export/import: https://docs.n8n.io/build/manage-workflows/export-and-import.md
- n8n public API (availability: "Self-hosted: All editions"), authentication: https://docs.n8n.io/connect/n8n-api.md , https://docs.n8n.io/connect/n8n-api/authentication.md
- n8n error handling: https://docs.n8n.io/build/flow-logic/handle-errors-gracefully.md
- n8n `$getWorkflowStaticData`: https://docs.n8n.io/build/code-in-n8n/cookbook/built-in-methods-and-variables-examples/getworkflowstaticdata.md
- n8n Google BigQuery node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.googlebigquery.md ; source of the Execute Query operation: https://raw.githubusercontent.com/n8n-io/n8n/master/packages/nodes-base/nodes/Google/BigQuery/v2/actions/database/executeQuery.operation.ts
- n8n HubSpot node: https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.hubspot.md ; credentials: https://docs.n8n.io/integrations/builtin/credentials/hubspot.md ; source: https://raw.githubusercontent.com/n8n-io/n8n/master/packages/nodes-base/nodes/Hubspot/V2/HubspotV2.node.ts , `.../V2/DealDescription.ts`, `.../V2/GenericFunctions.ts`, `.../Hubspot.node.ts`
- n8n Google service-account credential: https://docs.n8n.io/integrations/builtin/credentials/google/service-account.md
- n8n Webhook node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook.md ; Convert to File: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.converttofile.md ; Code node: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.code.md
- n8n license (Sustainable Use / Community License) and FAQ: https://docs.n8n.io/n8n-community-license/community-license.md , https://docs.n8n.io/n8n-community-license/community-license/license-faq.md
- n8n community: "Google Cloud Run Instance (minScale)?" (cron does not fire at minScale 0; 10–30 s cold start; 15-min lingering): https://community.n8n.io/t/google-cloud-run-instance-minscale/269677
- Cloud Run min instances: https://docs.cloud.google.com/run/docs/configuring/min-instances ; CPU allocation / billing modes: https://docs.cloud.google.com/run/docs/configuring/cpu-allocation ; pricing: https://cloud.google.com/run/pricing ; IAP on Cloud Run: https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run
- Cloud SQL pricing: https://cloud.google.com/sql/pricing
- HubSpot CRM search API (200/page, 10,000 cap, 5 req/s, operators, 5 groups × 6 filters): https://developers.hubspot.com/docs/api/crm/search ; timestamp format FAQ (epoch ms or ISO 8601): https://developers.hubspot.com/docs/faq/how-should-timestamps-be-formatted-for-hubspots-apis
- Community guides (secondary; used only for cost datapoints and the two-step URL pattern): https://github.com/datawranglerai/self-host-n8n-on-gcr (README), https://www.blog.brightcoding.dev/2025/12/22/the-ultimate-guide-self-host-n8n-on-google-cloud-run-for-%245-month-instead-of-%24240+-year

---

## 1 · Running n8n on Cloud Run — what is current

### 1.1 Image, port, protocol, URLs

- **Image.** `n8nio/n8n` (Docker Hub; also `docker.n8n.io/n8nio/n8n`). n8n's docs say the current stable is **2.41.7** (beta 2.42.3) at fetch time. Pin the tag (or digest) in the deploy unit; `:latest` moves and changes node `typeVersion` defaults and env-var names (`WEBHOOK_URL` is "Deprecated from n8n 2.35.0; alias of `N8N_WEBHOOK_URL`").
- **Port.** Cloud Run injects `PORT` and routes traffic to the container port given by `--port`. n8n listens on `N8N_PORT` (default `5678`) and ignores `PORT`. Both n8n's docs and the Google codelab therefore pass `--port=5678` and `N8N_PORT=5678` so that the two agree. The alternative (used by community images) is a `startup.sh` that exports `N8N_PORT=$PORT` so the image also works when Cloud Run picks the port. Either is fine; the recipe below does both (explicit `--port=5678`, and a shim so a forgotten flag does not produce a silent "container failed to listen" failure).
- **Protocol and public URLs.** `N8N_PROTOCOL=https` (Cloud Run terminates TLS). `N8N_HOST`, `N8N_WEBHOOK_URL` (`WEBHOOK_URL` still accepted) and `N8N_EDITOR_BASE_URL` must be the `*.run.app` URL — which is only known after the first deploy. n8n's docs do it in two steps:

```sh
# step 1: deploy (URL unknown) … step 2: learn the URL and update
SERVICE_URL=$(gcloud run services describe n8n --region=$REGION --format='value(status.url)')
gcloud run services update n8n --region=$REGION \
  --update-env-vars="N8N_HOST=${SERVICE_URL#https://},N8N_WEBHOOK_URL=$SERVICE_URL,N8N_EDITOR_BASE_URL=$SERVICE_URL"
```

  Without `N8N_WEBHOOK_URL` the editor shows `http://localhost:5678/webhook/...` as the production URL and OAuth callbacks break. Cloud Run's deterministic URL (`https://n8n-<project-number>.<region>.run.app`) can be computed up-front to make this one step.
- **Health check path.** "Google Cloud Run reserves `/healthz` for its own health checks. Since n8n uses this path by default, it can conflict and cause connection issues in the workflow canvas." → `N8N_ENDPOINT_HEALTH=health` (n8n docs). `QUEUE_HEALTH_CHECK_ACTIVE=true` is set in all official examples.
- **Startup delay.** Official examples override the command: `--command=/bin/sh --args="-c,sleep 5;n8n start"` to avoid a race with the Cloud SQL connector at start.
- **CPU allocation.** All official examples pass `--no-cpu-throttling` (instance-based billing: "CPU for the entire container instance lifecycle"). With the default request-based billing, "CPU is only allocated during request processing", so anything n8n does after it has answered a request — a webhook with *Respond: Immediately*, the in-memory Schedule Trigger, DB housekeeping — is starved.

### 1.2 Secrets

- `N8N_ENCRYPTION_KEY` — "Provide a custom key used to encrypt credentials in the n8n database"; default is a random key n8n generates and writes to `~/.n8n/config`. On Cloud Run that file is on the ephemeral filesystem; if the key is not pinned, **every new instance generates a new key and all stored credentials become undecryptable**. Official recipe: `openssl rand -base64 42 > my-encryption-key && gcloud secrets create n8n-encryption-key --data-file=my-encryption-key` and `--set-secrets=N8N_ENCRYPTION_KEY=n8n-encryption-key:latest`.
- `DB_POSTGRESDB_PASSWORD` — same mechanism (`--set-secrets=DB_POSTGRESDB_PASSWORD=n8n-db-password:latest`). Every n8n variable also accepts a `_FILE` suffix if you prefer Secret Manager volume mounts.
- **HubSpot token and BigQuery key are not Cloud Run secrets in n8n's model.** Workflow nodes read *n8n credentials*, which live in the n8n database encrypted with `N8N_ENCRYPTION_KEY`. The community edition has no runtime Secret Manager provider ("External secrets" is a licensed feature — the env-var page lists only timing variables; the provider list is on the Enterprise feature page) **[edition status unverified from a primary page in this session]**. So the HubSpot private-app token is *copied* from Secret Manager into an n8n "HubSpot App Token" credential (via the UI or `n8n import:credentials` from a JSON generated at deploy time). This is a material divergence from Scenario A's `--set-secrets HUBSPOT_TOKEN=hubspot-token:latest` (deploy.sh:24).

### 1.3 Persistence: Cloud SQL vs SQLite

- `DB_TYPE` is `sqlite` by default. The SQLite file lives under `N8N_USER_FOLDER/.n8n/database.sqlite` — on Cloud Run that is the instance's in-memory filesystem. n8n's own Cloud Run page ("Easy mode"): "n8n's data is in-memory so this is only recommended for demo purposes. **Anytime this Cloud Run service scales to zero or is redeployed, the n8n data will be lost.**" and even with `--scaling=1` it "does not prevent data loss completely, such as whenever the Cloud Run service is re-deployed/updated." What is lost: users, workflows, credentials, execution history and the auto-generated encryption key. Cloud Run's GCS volume mounts (FUSE) are not a fix: SQLite needs POSIX locking that FUSE does not provide, and n8n documents WAL-related losses on non-local storage. **SQLite is unacceptable for anything that must survive a Monday 07:00 run.**
- Durable mode: `DB_TYPE=postgresdb`, `DB_POSTGRESDB_HOST=/cloudsql/$PROJECT_ID:$REGION:n8n-db` (Unix socket mounted by `--add-cloudsql-instances=$PROJECT_ID:$REGION:n8n-db`), `DB_POSTGRESDB_PORT=5432`, `DB_POSTGRESDB_DATABASE=n8n`, `DB_POSTGRESDB_USER=n8n-user`, `DB_POSTGRESDB_SCHEMA=public`; service account needs `roles/cloudsql.client`. n8n's docs create the instance with `--database-version=POSTGRES_17 --tier=db-f1-micro --storage-size=10GB --availability-type=ZONAL --no-backup --storage-type=HDD`; the codelab uses `db-g1-small` and `POSTGRES_15`. `DB_POSTGRESDB_POOL_SIZE` defaults to 2 — fine for one instance.
- Cloud SQL is the one component that never scales to zero; see §1.6.

### 1.4 Execution mode, concurrency, Code node

- `EXECUTIONS_MODE` = `regular` (default) or `queue`. Queue mode needs Redis (Memorystore) and separate worker services with `min-instances=1`; the community README prices it at roughly £55–80/month. For two runs a week, regular mode on one instance (`--max-instances=1`) is the right shape; n8n is not designed for several main instances sharing one DB without a licence (multi-main is Enterprise).
- `N8N_CONCURRENCY_PRODUCTION_LIMIT` (default `-1` = unlimited) caps concurrent production executions on the instance; `1` serialises them — the n8n equivalent of the function's `--max-instances 1 --concurrency 1` watermark-race fix.
- `EXECUTIONS_TIMEOUT` (`-1`), `EXECUTIONS_TIMEOUT_MAX` (`3600`), execution data pruning `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE=336` hours, `EXECUTIONS_DATA_PRUNE_MAX_COUNT=10000`.
- Code node: JavaScript runs in a *task runner* (internal mode by default; `N8N_RUNNERS_ENABLED` is on in 2.x). `Math`, `Date`, Luxon (`$now`), `JSON` are available; "Code nodes cannot access the file system or make HTTP requests"; built-in/npm modules only via `NODE_FUNCTION_ALLOW_BUILTIN` / `NODE_FUNCTION_ALLOW_EXTERNAL` (set on the runner). The `hot_score()` port needs only `Math.log1p`, `Math.exp`, `Date` — no modules.

### 1.5 Scale-to-zero vs schedule triggers

- The Schedule Trigger is an in-process timer. Community thread (Feb 2026): "n8n's internal Cron Trigger nodes **won't fire** if the instance is scaled to zero, because there's no active server running to keep track of the schedule"; "The UI can easily take 10 to 30+ seconds to load if the container is asleep. Webhooks will also be delayed by that same startup time."
- The **durable scheduler** (n8n 2.36+, `N8N_SCHEDULER_ENABLED=true`, `N8N_USE_WORKFLOW_PUBLICATION_SERVICE=true`) stores upcoming runs in the database "so a restart doesn't drop them", with `N8N_SCHEDULER_MISFIRE_GRACE=60` seconds and a per-trigger misfire policy (discard backlog or catch up). It fixes *restarts*, not *sleep*: nobody polls the queue while the service is at zero instances, so a Monday 07:00 run on a sleeping instance fires only when something else wakes it — and then only if the misfire policy says catch-up.
- Two viable designs:
  1. **`--min-instances=1 --no-cpu-throttling` + Schedule Trigger (+ durable scheduler).** Always-on; ~$53/month compute (§1.6).
  2. **`--min-instances=0` + Cloud Scheduler → n8n Webhook trigger.** Cloud Scheduler is the clock (same `0 7 * * 1` Europe/Zurich, retries, OIDC or header auth), n8n wakes on the request. Compute ≈ $0. This keeps the same trigger layer as Scenario A (deploy.sh:28-32) and is the design recommended below for B2.

### 1.6 Cost (Tier-1 region list prices, 730 h/month; Zurich `europe-west6` is Tier 2, roughly +20 %)

| Component | Config | Monthly |
|---|---|---|
| Cloud SQL PostgreSQL | `db-f1-micro` (shared core, 0.6 GiB, **not covered by the Cloud SQL SLA**) $0.0105/h + 10 GiB HDD $0.000123288/GiB·h | ≈ $7.67 + $0.90 = **$8.6** |
| Cloud SQL PostgreSQL | `db-g1-small` (1.7 GiB) $0.035/h + 10 GiB HDD | ≈ **$26.5** |
| Cloud Run, always on | `--min-instances=1 --no-cpu-throttling`, 1 vCPU/2 GiB: $0.000018/vCPU·s, $0.000002/GiB·s → $47.3 + $10.5, minus free tier (240 000 vCPU·s, 450 000 GiB·s) | ≈ **$52.6** |
| Cloud Run, warm but throttled | `--min-instances=1` request-based: idle $0.0000025/vCPU·s and /GiB·s → $6.6 + $13.1 (idle min-instance time is *not* in the free tier) | ≈ **$19.7** — but CPU is throttled between requests, so the in-memory scheduler is unreliable; not recommended |
| Cloud Run, scale-to-zero | 2 runs/week ≈ 9/month × (~60 s active + ~15 min lingering) ≈ 8 640 s → $0.19 before free tier | ≈ **$0–2** incl. editor sessions |
| Cloud Scheduler | 3 jobs free per billing account, then $0.10/job/month | $0 |
| Secret Manager | $0.06/active version/month beyond 6 free; 10 000 access ops free | $0 |

Order of magnitude: **B2 scale-to-zero ≈ $9–11/month; B2 always-on ≈ $61–80/month; Scenario A ≈ <$1/month** (two function invocations a week, two Scheduler jobs, one secret). Secondary datapoints agree: datawranglerai README "£2–£12/month (regular mode, min-instances=0)", brightcoding "£2-12/month", community thread "15 mins lingering costs made Cloud Run less economical than DigitalOcean" for always-on.

### 1.7 Licence

n8n's **Sustainable Use License** (docs call it the Community License): "You may use or modify the software only for your own internal business purposes or for non-commercial or personal use." Explicitly allowed example in the FAQ: "Using n8n to sync the data you control as a company, for example from a CRM to an internal database." Not allowed: white-labelling, hosting n8n for others for money, letting external users build workflows. Files with `.ee.` in the name are under the n8n Enterprise License. Running this pipeline (HubSpot → BigQuery → internal weekly email) is squarely internal business use; no licence key needed. Contact for doubt: license@n8n.io.

### 1.8 Node capabilities that decide B2

**Google BigQuery node** (`n8n-nodes-base.googleBigQuery` v2): operations **Execute Query** and **Insert**.
- Execute Query runs `jobs.insert` then `getQueryResults` with polling — any Standard SQL statement, including **MERGE and other DML** (it is not restricted to SELECT). Options from source: `defaultDataset`, `dryRun`, `includeSchema`, `location`, `maximumBytesBilled`, `maxResults` (1000), `timeoutMs` (10000), `rawOutput`, `useLegacySql`, `returnAsNumbers`, and **`queryParameters` → named parameters, STRING type only** (source comment: "the only supported type here is `STRING`"; "Arrays, dates and struct types … are not yet supported"). So `@rid` works as-is; `@ts` must be cast in SQL (`TIMESTAMP(@ts)`); an array of rows must travel as one JSON string and be unpacked with `JSON_QUERY_ARRAY(PARSE_JSON(@rows_json))`.
- Insert uses `tabledata.insertAll` (streaming). Rows sit in the streaming buffer for a while, during which DML/TRUNCATE touching them fails — so `main.py:124`'s `WRITE_TRUNCATE` staging-table pattern does not port one-to-one. The MERGE-from-inline-JSON pattern (§3.4) avoids the staging table entirely and is one atomic statement.
- Credentials: Google **Service Account** (JSON key: `client_email` + `private_key`) or OAuth2. There is **no Application-Default-Credentials / Workload-Identity option**: the Cloud Run runtime service account cannot be used by the node. Divergence from A's keyless SA (deploy.sh:5-10, 22).

**HubSpot node** (`n8n-nodes-base.hubspot`, default `typeVersion` 2.2; V2 serves 2, 2.1, 2.2). Deal operations: Create, Delete, Get, Get All, Get Recently Created, Get Recently Modified, **Search**, Update.
- Search → `POST /crm/v3/objects/deals/search`. Filter groups (max **3** in the node; the API allows 5×6), operators exactly `CONTAINS_TOKEN, EQ, GT, GTE, HAS_PROPERTY, LT, LTE, NEQ, NOT_HAS_PROPERTY` (no `BETWEEN`/`IN`, but `GTE`+`LT` on `createdate` is what main.py uses), `additionalFields.properties` **is** sent (`Object.assign(body, additionalFields)`), `sortBy` (default `createdate`) + `direction` (default `DESCENDING`; set ASCENDING), `returnAll` pages with `body.after = responseData.paging.next.after` at `body.limit || 100` (so 100 per page, not 200 → twice the calls; the search limit is 5 req/s per account and 10 000 results per query — both far above a weekly window). Date values are passed through as strings; HubSpot accepts epoch ms or ISO 8601 for datetime properties (HubSpot FAQ), and main.py already sends `%Y-%m-%dT%H:%M:%S.000Z`. **Conclusion: the native HubSpot node can do the createdate-window search; no HTTP Request node needed for the search.**
- There is **no pipelines or owners operation** → two HTTP Request nodes (`GET /crm/v3/pipelines/deals`, `GET /crm/v3/owners?limit=100` with `after` pagination) using the same HubSpot App Token credential (HTTP Request "predefined credential" support for `hubspotAppToken` **[unverified in this session; fallback is a Header Auth credential with `Authorization: Bearer`]**).
- Update → `PATCH /crm/v3/objects/deals/{id}` one item at a time; the batch endpoint (`/crm/v3/objects/deals/batch/update`) requires an HTTP Request node. Relevant to L10 only.
- Credential types: **Service Key / App Token (recommended, private app)**, OAuth2; the legacy API key is deprecated; Developer API key is for the HubSpot Trigger node. Scopes documented for the node include `crm.objects.deals.read`, `crm.schemas.deals.read`, `crm.objects.owners.read` — the same three the function uses (README.md:75).

**Webhook node**: authentication None / Basic / Header / JWT; respond Immediately / When Last Node Finishes / Respond to Webhook node; production path `/webhook/<path>` (configurable via `N8N_ENDPOINT_WEBHOOK`), test path `/webhook-test/`; options IP allowlist, raw body, ignore bots. `N8N_PAYLOAD_SIZE_MAX` 16 MiB.

**Convert to File → XLSX**: File Name, Header Row, Sheet Name, Compression, Put Output File in Field — matches the JSON's `convertToFile` v1.1 node.

**Deploying JSON (L0)**: `n8n import:workflow --input=file.json` (and `--separate` for a directory), `n8n import:credentials --input=…`, `n8n publish:workflow --id=…` ("operate on your n8n database. If you execute them while n8n is running, the changes don't take effect until you restart n8n"; importing an existing ID overwrites). There is no `docker exec` on Cloud Run, so run the CLI as a **Cloud Run Job** with the same image and DB/secret env, or use the **public REST API** (`POST /api/v1/workflows`, header `X-N8N-API-KEY`, "Self-hosted: All editions"). Exported JSON carries credential *ids and names* that must be remapped on the target (the current JSON has `REPLACE_WITH_CREDENTIAL_ID`, `n8n_NewDeals_Delivery.json:90`).

---

## 2 · B1 — n8n delivers only (the JSON that exists)

### 2.1 Flow as written

```
Cloud Scheduler ──OIDC──▶ new-deals-report (gen2, main.py)
                            │ HubSpot search → shape → hot score → MERGE → watermark
                            └─ requests.post(DELIVERY_WEBHOOK_URL, payload, timeout=30)   main.py:200-203
                                   ▼
          n8n  Webhook POST /webhook/new-deals  (responseMode onReceived, auth None)   json:5-19
             → Split Out body.rows                                                       json:23
             → Code "Shape columns" (26-column order)                                    json:39
             → Convert to File XLSX  NEW_DEALS_<ENTITY>_<yyyy-mm-dd>.xlsx                json:52-58
             → Email Send (SMTP) subject "<report_id> — N new deal(s), M duplicate suspect(s)", text body, attachment json:71-78
```

### 2.2 Findings (each testable)

1. **Unauthenticated webhook.** The node has no `authentication` parameter (→ None) and the function sends no auth header. With `--allow-unauthenticated` on n8n (as in every official recipe) the URL `https://<svc>.run.app/webhook/new-deals` accepts any POST: a forged payload produces a forged "new deals" email to sales-ops. *Test:* `curl -X POST $URL/webhook/new-deals -d '{"report_id":"X","run_timestamp":"2026-10-05T07:00:00","rows":[...]}'` → email arrives. *Fix:* Header Auth credential on the Webhook node (`X-Delivery-Token`), the function reads `DELIVERY_WEBHOOK_TOKEN` from Secret Manager and sends it (`main.py:202`); or make the n8n service private and have the function fetch an OIDC token (`google.oauth2.id_token.fetch_id_token`) — but then the editor needs IAP (§4, L14).
2. **Delivery is fire-and-forget after the state change.** `main.py:196` advances the watermark, then `main.py:202` POSTs with `timeout=30` and `main.py:203` only logs a failure. A cold n8n on Cloud Run (community: 10–30+ s; `sleep 5` is in the official start command; Cloud SQL connector adds to it) can exceed 30 s → `delivery_error` in the function's response, but BigQuery already holds the rows and the watermark has moved, so the next run's window is empty and **that week's email is never sent**. *Test:* set `--min-instances=0`, leave n8n idle > 15 min, trigger the function, read `delivery_error` in the response. *Fix (three options, cheapest first):* retry with backoff (3 × 20 s) in the function; or make n8n read the week from BigQuery (`new_deals_last_7d` view, `bigquery_schema.sql:50-53`) instead of trusting the payload — then any re-trigger of the n8n webhook re-sends the same report (idempotent delivery); or `--min-instances=1`.
3. **Zero-row weeks produce no email.** Split Out on an empty `body.rows` emits zero items; downstream nodes do not run; nobody is told "0 new deals". The function still returns 200 with `row_count: 0`. *Test:* POST `{"rows":[],"row_count":0,...}` → no email. *Fix:* IF node on `body.row_count > 0` with a text-only email on the false branch (or "Always Output Data" on Split Out plus a guard in the Code node).
4. **Respond Immediately + request-based billing starves the execution.** With `responseMode: onReceived` n8n answers `200 Workflow got started` and then builds the XLSX and sends the email *after* the response — exactly the "background work" Cloud Run throttles under request-based billing. Official recipes avoid this with `--no-cpu-throttling`. *Test:* deploy with default `--cpu-throttling` and watch the execution hang in "running". *Fix:* `--no-cpu-throttling` (instance-based billing) or `responseMode: lastNode` so the function's 30 s request covers the work (but then the function waits for SMTP).
5. **Placeholders.** `fromEmail n8n@example.com`, `toEmail sales-ops@example.com`, SMTP credential `REPLACE_WITH_CREDENTIAL_ID`, `active: false`. The workflow cannot execute until an SMTP credential exists and is referenced; recipients belong in `.env`/n8n variables, not in the JSON.
6. **`$('Webhook: new-deals').item.json.body…`** relies on paired-item tracking through Split Out → Code (`runOnceForAllItems` returns `$input.all().map(...)` which preserves pairing by index). Fine in `executionOrder: v1`; note it as a parity condition for the Code node (any `return` that drops pairing breaks the Email expressions).

### 2.3 B1 verdict

B1 keeps every idempotency property of A (L4–L8 are untouched) and adds one non-idempotent step: delivery. It is the cheapest way to get a formatted XLSX e-mail. The pipeline's correctness does not depend on n8n at all — BigQuery is the truth — so the n8n service may scale to zero as long as finding 2 is fixed (retry or deliver-from-BigQuery) and finding 1 is fixed before the URL exists.

---

## 3 · B2 — n8n owns the whole pipeline

### 3.1 Node graph (`workflows/NEW_DEALS_FULL.json`)

```
[Trigger]  Webhook POST /webhook/new-deals-run?entity=SEALSQ|ICALPS&dry_run=0|1   (Header Auth)   ← Cloud Scheduler (2 jobs)
           — alternative: Schedule Trigger 0 7 * * 1 Europe/Zurich (needs min-instances=1)
 1  Set "Params"            entity, dry_run, run_ts = $now.toUTC().startOf('second'), OVERLAP_MINUTES, FIRST_RUN_DAYS, PORTAL_ID, BQ project/dataset (from n8n Variables / env)
 2  BigQuery ExecuteQuery   SELECT watermark FROM `…report_state` WHERE report_id=@rid          params: rid (STRING)
 3  Code "Window"           start = watermark ?? run_ts − FIRST_RUN_DAYS; query_start = start − OVERLAP; query_end = run_ts (ISO .000Z)
 4  HubSpot Deal→Search     filterGroups[ createdate GTE {{query_start}}, createdate LT {{query_end}} ], properties = PROPS (29), sort createdate ASC, Return All
 5  HTTP Request            GET /crm/v3/pipelines/deals                      (label maps)
 6  HTTP Request            GET /crm/v3/owners?limit=100 (+after)            (owner names)
 7  BigQuery ExecuteQuery   SELECT deal_id, name_key FROM `…new_deals` WHERE createdate >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)   (recent_names; continue on fail → {})
 8  Code "Shape + score"    port of name_key(), shape(), hot_score() → rows[] sorted by (−amount_kusd, deal_id); split deals vs others by ENTITIES[entity].pipelines
 9  IF dry_run == 1 ──true──▶ 13 (payload only, nothing written)
10  BigQuery ExecuteQuery   MERGE `…new_deals` t USING (SELECT … FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@rows_json))) r) s ON t.deal_id=s.deal_id …   params: rows_json (STRING)
11  BigQuery ExecuteQuery   MERGE `…report_state` … USING (SELECT @rid AS report_id, TIMESTAMP(@ts) AS watermark)   params: rid, ts (STRING)   ← only reached if 10 succeeded
12  Code "Payload"          report_id, run_timestamp, window{…}, row_count, rows_written, duplicate_suspects, day1_hot[], currency_note, rows[]  (same contract as README.md:82-86)
13  Split Out rows → Code "Shape columns" → Convert to File XLSX → Email Send      (= the B1 tail, unchanged)
14  Respond to Webhook      200 + payload summary  (so Cloud Scheduler sees success/failure)
Settings: executionOrder v1, timezone Europe/Zurich, Error Workflow → NEW_DEALS_ERRORS (Error Trigger → email), saveDataSuccessExecution all
```

Two entities: one workflow, `entity` from the query string, two Cloud Scheduler jobs — same shape as deploy.sh:28-32 (and the same OIDC service account can be reused if the service is private; otherwise `--headers X-Delivery-Token=…`).

### 3.2 Where idempotency must be re-implemented (and how)

| A's mechanism (main.py) | B2 re-implementation | Residual risk |
|---|---|---|
| Watermark read with fallback (`:107-111`) | Node 2 + Code node 3 (`rows[0]?.watermark ?? run_ts − FIRST_RUN_DAYS`). BigQuery returns TIMESTAMP as a string; parse with `new Date()` | none if the Code node handles the empty result |
| Half-open window with overlap (`:184-186`) | Code node 3 computes `query_start/query_end` once and all later nodes reference *that* item (`$('Window').first().json`) — never `$now` again | a second `$now` anywhere re-opens the race |
| Exact search, paging (`:73-83`) | HubSpot node Search with Return All; `properties` listed; ASC sort | node pages at 100 not 200; 3-filter-group cap irrelevant |
| MERGE on `deal_id` after `WRITE_TRUNCATE` load (`:120-130`) | Single MERGE statement with the rows inlined as a JSON STRING parameter (§3.4) — **more** atomic than A (no staging table, no two-step) | 1 MB query-text limit is irrelevant for weekly volumes; the JSON travels as a parameter, not query text |
| Watermark advance only after MERGE (`:196`) | Node 11 wired *after* node 10; node 10 "On Error: Stop Workflow" (default) and "Retry On Fail" | if the instance dies between 10 and 11 the next run re-MERGEs the same window — safe by design |
| Dry run (`:173-177, 194`) | IF node 9; the BigQuery *read* nodes still run (A skips the client entirely); Execute Query `dryRun` option is a different thing (query validation) | dry run reads state but writes nothing — acceptable; document it |
| `--max-instances 1 --concurrency 1` (user's fix) | `--max-instances=1` **and** `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`; Webhook "Respond: When Last Node Finishes"/Respond-to-Webhook so Scheduler retries only on real failure; Cloud Run `--timeout 900` ≥ Scheduler `--attempt-deadline 900s` | without the concurrency limit a Scheduler retry overlapping a slow attempt runs two executions in one n8n process |
| Replay (`README.md:68`) | identical: `UPDATE report_state SET watermark=…` in BigQuery, then hit the webhook | Parallel |
| Event mode (`:179-182`) | not ported in B2 v1 (HubSpot workflow webhook → second webhook path; MERGE dedupes) | optional |

What B2 must **not** do: keep the watermark in `$getWorkflowStaticData` (n8n: "may behave unreliably under high-frequency workflow executions", not written on manual runs) or in n8n Data Tables — CONVENTIONS.md forbids local/orchestrator-private state; the watermark stays in `hubspot.report_state` so A, B and C read the same truth.

### 3.3 What is lost versus A

1. **Keyless identity.** A runs as a Cloud Run service account with `bigquery.jobUser` + dataset `dataEditor` (deploy.sh:8-10) — no key. B2's BigQuery node needs a **service-account JSON key** stored (encrypted) in Cloud SQL. Key creation may be blocked by the `iam.disableServiceAccountKeyCreation` org policy; rotation is manual. Keyless alternative: an HTTP Request node to `http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token` (header `Metadata-Flavor: Google`) then raw `jobs.query` calls — loses the BigQuery node, and n8n's SSRF protection (if enabled, `N8N_SSRF_PROTECTION_ENABLED`, off by default) blocks `169.254.0.0/16` by default.
2. **Secret Manager as the single source of the HubSpot token.** The token becomes an n8n credential (copied at deploy time). Rotation = Secret Manager version + credential re-import.
3. **Code review surface.** `hot_score()` becomes a JavaScript string inside a JSON field (`jsCode`). Diffs are unreadable and the constants are duplicated (CONVENTIONS: "a change to one copy is a change to all"). Mitigation: keep `workflows/src/hot_score.js` as a real file, have `workflows/src/build_workflow.py` inject it into the JSON, and test it with the same vectors as `main.py` (`tests/vectors/hot_score_vectors.json`, generated from the Python).
4. **Arithmetic parity details.** Python `round(s, 1)` is banker's rounding; JS `Math.round(s*10)/10` rounds half away from zero → a score ending in exactly `.x5` differs by 0.1 (`main.py:68`). `(d - datetime(...)).days` is floor division; JS needs `Math.floor(ms/86_400_000)`. `_num()` treats `''`/`None`/non-numeric as `0.0` (`main.py:45-47`); JS `Number('')` is `0` but `Number(null)` is `0` and `Number(undefined)` is `NaN` → write an explicit `num()` helper. Test vectors must include a `.x5` boundary and a missing-field case.
5. **A single deploy unit.** A is `gcloud run deploy --function` of one directory. B2 is: image pin + Cloud SQL + two secrets + service + two credentials + workflow import + publish + Scheduler. Version drift: `n8nio/n8n:latest` changes node `typeVersion` defaults and env-var names; pin the image.
6. **Always-on database.** Cloud SQL `db-f1-micro` runs 24×7 for a job that runs twice a week; it needs Postgres maintenance windows and n8n schema migrations on upgrade (n8n migrates on start; downgrade is not supported).
7. **Observability shape.** A: one structured log line per run (`main.py:204`) in Cloud Logging, Scheduler job status. B2: n8n execution list (pruned at 336 h / 10 000), n8n stdout in Cloud Logging, `N8N_METRICS=true` for Prometheus if wanted; execution data lives in Cloud SQL.
8. **Access control surface.** A has no UI; B2 exposes an editor with owner/email login on a public URL unless IAP is added (and IAP intercepts *all* ingress including the Scheduler's webhook calls — the IAP service agent needs `run.invoker`, Scheduler would need an IAP-accepted identity; "Services relying on their own authentication … might fail due to IAP intercepting and replacing caller identity").

### 3.4 Code snippets

**hot_score port (`workflows/src/hot_score.js`, injected into node 8)**

```js
// Same constants as main.py:41-43 (fitted 2026-10-01). Change here = change there; tests/vectors covers both.
const W = { stage_prob: 2.0712, proximity_2026: 1.2399, missing_2026_field: -0.4136, pipeline_conversion: 1.0918,
            arr_points: 4.9843, engagement: 1.3018, recency: 0.0, not_in_forecast: 1.5620 };
const BIAS = -6.4788, THRESHOLD = 45.0;
const CR = { '12096408': 84 / 730, '13772279': 51 / 303 };
const CRMAX = Math.max(...Object.values(CR)), MAXC = 223;
const num = v => { if (v === null || v === undefined || v === '') return 0; const n = Number(v); return Number.isFinite(n) ? n : 0; };
const days = (a, b) => Math.floor((a - b) / 86400000);                     // Python timedelta.days semantics
const round1 = s => { const x = s * 10, f = Math.floor(x), d = x - f;        // Python round(): half to even
  const r = d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1); return r / 10; };

function hotScore(p, now) {
  if (!(p.pipeline in CR)) return [null, null];
  const arr = num(p.asp_in_usd_q2_2022_calculation) || num(p.tpm__k_y) || num(p.services_value_2026);
  const pts = p.product_hierarchy === 'PKI' ? (arr < 20 ? 0.5 : arr <= 50 ? 1 : 2)
                                            : (arr < 100 ? 0.5 : arr <= 500 ? 1 : arr <= 1000 ? 2 : 3);
  let prox = 0;
  if (p.closedate) { const d = new Date(p.closedate);
    prox = d.getUTCFullYear() <= 2026 ? 1 : Math.max(0, 1 - days(d, Date.UTC(2026, 11, 31)) / 730); }
  const hw = p.pipeline === '12096408';
  const missing = (hw ? !num(p.calculation___pipeline_2026__k__) : !num(p.services_value_2026)) ? 1 : 0;
  let rec = 0;
  if (p.notes_last_updated) { const dd = days(now, new Date(p.notes_last_updated)); rec = dd <= 90 ? 1 : dd <= 180 ? 0.5 : 0; }
  const f = { stage_prob: num(p.hs_deal_stage_probability), proximity_2026: prox, missing_2026_field: missing,
    pipeline_conversion: CR[p.pipeline] / CRMAX, arr_points: pts / 3,
    engagement: Math.log1p(num(p.num_contacted_notes)) / Math.log1p(MAXC), recency: rec,
    not_in_forecast: ['Forecast', 'BIBA'].includes(p.revenue_state) ? 0 : 1 };
  const z = Object.keys(W).reduce((s, k) => s + W[k] * f[k], 0) + BIAS;
  const s = 100 / (1 + Math.exp(-z));
  return [round1(s), s >= THRESHOLD];
}
```

**MERGE with inline JSON source (node 10; `rows_json` is `={{ JSON.stringify($('Shape + score').first().json.rows) }}`)**

```sql
MERGE `${PROJECT}.${DATASET}.new_deals` t
USING (
  SELECT JSON_VALUE(r,'$.entity') entity, JSON_VALUE(r,'$.deal_id') deal_id, JSON_VALUE(r,'$.dealname') dealname,
         JSON_VALUE(r,'$.final_customer') final_customer, JSON_VALUE(r,'$.name_key') name_key,
         TIMESTAMP(JSON_VALUE(r,'$.createdate')) createdate, JSON_VALUE(r,'$.created_by_user_id') created_by_user_id,
         JSON_VALUE(r,'$.source') source, JSON_VALUE(r,'$.owner') owner, JSON_VALUE(r,'$.sales_region') sales_region,
         JSON_VALUE(r,'$.pipeline') pipeline, JSON_VALUE(r,'$.pipeline_id') pipeline_id, JSON_VALUE(r,'$.stage') stage,
         SAFE_CAST(JSON_VALUE(r,'$.probability_pct') AS FLOAT64) probability_pct, SAFE_CAST(JSON_VALUE(r,'$.amount') AS FLOAT64) amount,
         JSON_VALUE(r,'$.currency') currency, SAFE_CAST(JSON_VALUE(r,'$.amount_kusd') AS FLOAT64) amount_kusd,
         SAFE_CAST(JSON_VALUE(r,'$.closedate') AS DATE) closedate, SAFE_CAST(JSON_VALUE(r,'$.arr_ky') AS FLOAT64) arr_ky,
         JSON_VALUE(r,'$.product_family') product_family, JSON_VALUE(r,'$.product') product, JSON_VALUE(r,'$.application') application,
         JSON_VALUE(r,'$.icalps_dealtype') icalps_dealtype, JSON_VALUE(r,'$.icalps_stage') icalps_stage,
         SAFE_CAST(JSON_VALUE(r,'$.day1_hot_score') AS FLOAT64) day1_hot_score, SAFE_CAST(JSON_VALUE(r,'$.day1_hot_flag') AS BOOL) day1_hot_flag,
         SAFE_CAST(JSON_VALUE(r,'$.duplicate_suspect') AS BOOL) duplicate_suspect, JSON_VALUE(r,'$.duplicate_of') duplicate_of,
         JSON_VALUE(r,'$.deal_url') deal_url, TIMESTAMP(JSON_VALUE(r,'$.first_seen_run')) first_seen_run, TIMESTAMP(JSON_VALUE(r,'$.last_seen_run')) last_seen_run
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@rows_json))) r
) s ON t.deal_id = s.deal_id
WHEN MATCHED THEN UPDATE SET entity=s.entity, dealname=s.dealname, /* … every column except deal_id, first_seen_run … */ last_seen_run=s.last_seen_run
WHEN NOT MATCHED THEN INSERT (entity, deal_id, /* … all columns … */ last_seen_run) VALUES (s.entity, s.deal_id, /* … */ s.last_seen_run);
```

Column list is `bigquery_schema.sql:39-44`; the update set excludes `deal_id, first_seen_run` exactly as `main.py:126`. The build script should generate this SQL from the schema file so the three copies (Python, SQL, JSON) cannot drift.

**Watermark (node 11)**

```sql
MERGE `${PROJECT}.${DATASET}.report_state` t
USING (SELECT @rid AS report_id, TIMESTAMP(@ts) AS watermark) s ON t.report_id = s.report_id
WHEN MATCHED THEN UPDATE SET watermark = s.watermark, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (report_id, watermark, updated_at) VALUES (s.report_id, s.watermark, CURRENT_TIMESTAMP());
```

**Cloud Run service (`deploy/n8n/service.yaml`, Knative form so `gcloud run services replace` is idempotent)**

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: n8n
  annotations:
    run.googleapis.com/ingress: all
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "0"        # "1" for the Schedule-Trigger variant
        autoscaling.knative.dev/maxScale: "1"        # n8n regular mode: one main instance
        run.googleapis.com/cpu-throttling: "false"   # instance-based billing; n8n does work after responding
        run.googleapis.com/cloudsql-instances: ${PROJECT}:${REGION}:n8n-db
        run.googleapis.com/startup-cpu-boost: "true"
    spec:
      serviceAccountName: n8n-run@${PROJECT}.iam.gserviceaccount.com
      containerConcurrency: 80
      timeoutSeconds: 900
      containers:
        - image: docker.io/n8nio/n8n:2.41.7          # pinned; bump deliberately
          command: ["/bin/sh", "-c", "sleep 5; n8n start"]
          ports: [{ name: http1, containerPort: 5678 }]
          resources: { limits: { cpu: "1", memory: 2Gi } }
          env:
            - { name: N8N_PORT, value: "5678" }
            - { name: N8N_PROTOCOL, value: https }
            - { name: N8N_HOST, value: n8n-${PROJECT_NUMBER}.${REGION}.run.app }
            - { name: N8N_WEBHOOK_URL, value: https://n8n-${PROJECT_NUMBER}.${REGION}.run.app }
            - { name: N8N_EDITOR_BASE_URL, value: https://n8n-${PROJECT_NUMBER}.${REGION}.run.app }
            - { name: N8N_ENDPOINT_HEALTH, value: health }
            - { name: QUEUE_HEALTH_CHECK_ACTIVE, value: "true" }
            - { name: DB_TYPE, value: postgresdb }
            - { name: DB_POSTGRESDB_HOST, value: /cloudsql/${PROJECT}:${REGION}:n8n-db }
            - { name: DB_POSTGRESDB_PORT, value: "5432" }
            - { name: DB_POSTGRESDB_DATABASE, value: n8n }
            - { name: DB_POSTGRESDB_USER, value: n8n-user }
            - { name: DB_POSTGRESDB_SCHEMA, value: public }
            - { name: DB_POSTGRESDB_PASSWORD, valueFrom: { secretKeyRef: { name: n8n-db-password, key: latest } } }
            - { name: N8N_ENCRYPTION_KEY, valueFrom: { secretKeyRef: { name: n8n-encryption-key, key: latest } } }
            - { name: GENERIC_TIMEZONE, value: Europe/Zurich }
            - { name: EXECUTIONS_MODE, value: regular }
            - { name: N8N_CONCURRENCY_PRODUCTION_LIMIT, value: "1" }
            - { name: EXECUTIONS_DATA_MAX_AGE, value: "2160" }   # 90 days of execution history in Cloud SQL
            - { name: N8N_DIAGNOSTICS_ENABLED, value: "false" }
            - { name: N8N_HIRING_BANNER_ENABLED, value: "false" }
          startupProbe: { httpGet: { path: /health, port: 5678 }, initialDelaySeconds: 10, periodSeconds: 5, failureThreshold: 24 }
```

**Scheduler → webhook (two jobs, same clock as deploy.sh:28-32)**

```sh
for ENTITY in SEALSQ ICALPS; do
  gcloud scheduler jobs create http n8n-new-deals-$ENTITY --project $PROJECT --location $REGION \
    --schedule "0 7 * * 1" --time-zone "Europe/Zurich" \
    --uri "${N8N_URL}/webhook/new-deals-run?entity=${ENTITY}" --http-method POST \
    --headers "X-Delivery-Token=$(gcloud secrets versions access latest --secret n8n-webhook-token)" \
    --attempt-deadline 900s --max-retry-attempts 3 || true
done
```

**Workflow import as a Cloud Run Job (no `docker exec` on Cloud Run)**

```sh
gcloud run jobs deploy n8n-import --image docker.io/n8nio/n8n:2.41.7 --region $REGION \
  --service-account n8n-run@$PROJECT.iam.gserviceaccount.com --set-cloudsql-instances $PROJECT:$REGION:n8n-db \
  --set-env-vars "DB_TYPE=postgresdb,DB_POSTGRESDB_HOST=/cloudsql/$PROJECT:$REGION:n8n-db,DB_POSTGRESDB_DATABASE=n8n,DB_POSTGRESDB_USER=n8n-user" \
  --set-secrets "DB_POSTGRESDB_PASSWORD=n8n-db-password:latest,N8N_ENCRYPTION_KEY=n8n-encryption-key:latest" \
  --command /bin/sh --args "-c,n8n import:credentials --input=/tmp/creds.json && n8n import:workflow --input=/tmp/NEW_DEALS_FULL.json && n8n publish:workflow --id=NEW_DEALS_FULL"
# the JSON files reach /tmp via a GCS volume mount (--add-volume/--add-volume-mount) or are baked into a thin derived image.
# Alternative without a Job: POST /api/v1/workflows with X-N8N-API-KEY (public API is on all self-hosted editions).
```

Import overwrites a workflow with the same `id` — give the workflows stable ids (`NEW_DEALS_DELIVERY`, `NEW_DEALS_FULL`) so re-import is idempotent. `publish:workflow` edits the DB; n8n picks it up on the next start (the Job runs while the service is at zero instances, or you restart the service by deploying the same revision).

---

## 4 · Lane cells — Scenario B at every layer

Parity words are relative to Scenario A at the same layer (Parallel = same mechanism and result; Conditional = same result under the stated condition; Divergent = different mechanism, remediation makes it equivalent).

| Layer | B1 (n8n delivers) | B2 (n8n owns pipeline) | Idempotent? | Parity vs A |
|---|---|---|---|---|
| **L0** Code acquisition & deploy unit | `gcloud run deploy --function` for main.py (as A) **plus** n8n service (pinned image `n8nio/n8n:2.41.7`, `service.yaml` applied with `gcloud run services replace`), Cloud SQL, 2 secrets, and the workflow JSON imported by a Cloud Run Job (`n8n import:workflow`) or the public API | same minus the function; `NEW_DEALS_FULL.json` built by `build_workflow.py` from `src/hot_score.js` + `bigquery_schema.sql` | conditional: `services replace` and import-by-stable-id are idempotent; `n8n publish:workflow` needs a restart to take effect | Divergent — one directory vs image+DB+JSON; remediation: `deploy_n8n.sh` as the single entry point, image pin, stable workflow ids |
| **L1** Identity to BigQuery | A's SA (keyless) — B1 never touches BigQuery from n8n | Google Service Account **JSON key** in an n8n credential (no ADC/Workload Identity in n8n); SA `n8n-bq@…` with `bigquery.jobUser` + dataset `dataEditor` (same DCL as deploy.sh:9) | yes (credential import by id) | B1 Parallel; B2 Divergent — key vs keyless; remediation: dedicated SA, key rotation script, or metadata-token HTTP path (loses the node) |
| **L2** Secrets (HubSpot token) | Secret Manager → function env (as A); n8n holds only `N8N_ENCRYPTION_KEY`, DB password and the webhook token | HubSpot token copied from Secret Manager into an n8n "HubSpot App Token" credential (encrypted with `N8N_ENCRYPTION_KEY` in Cloud SQL); External Secrets provider is licensed | yes (import by id); rotation = new SM version + re-import | B1 Parallel; B2 Divergent — remediation: `secrets.sh` generates the credential JSON from SM at deploy time, never by hand |
| **L3** Trigger & schedule | Cloud Scheduler → function (OIDC) as A; function → n8n webhook | Cloud Scheduler → n8n webhook with Header Auth, `0 7 * * 1` Europe/Zurich, 3 retries, `attempt-deadline 900s` (or Schedule Trigger + `minScale 1` + durable scheduler) | yes; Scheduler retry re-runs the same idempotent window | B1 Parallel; B2 Conditional — same clock when the webhook variant is chosen; Schedule-Trigger variant is Divergent (sleeps at zero) |
| **L4** Extraction window | in function (A) | BigQuery node reads `report_state` (@rid STRING); Code node computes `[watermark − 5 min, run_ts)` once; HubSpot node Search `createdate GTE/LT`, 29 properties, ASC, Return All (100/page) | yes — createdate immutable, window computed once | B1 Parallel; B2 Conditional — same rows iff `query_end` is taken from the Window node and not re-evaluated |
| **L5** Scoring arithmetic | in function (A) | Code node JS port (`Math.log1p`, logistic), constants duplicated; `round1()` emulates Python half-to-even; test vectors shared | yes (pure function) | Divergent (two languages) — remediation: `tests/vectors/hot_score_vectors.json` run against both; `.x5` and missing-field cases included |
| **L6** Shaping & duplicate flag | in function (A); B1 only re-orders 26 columns (`json:39`) | Code node ports `name_key()` regexes, in-batch twins across pipelines, 90-day `recent_names` BigQuery read (continue-on-fail → `{}` as `main.py:136`) | yes | B1 Parallel; B2 Conditional — same flags iff `recent_names` read succeeds on both (A also degrades silently) |
| **L7** Load → MERGE | in function (A) | one BigQuery Execute Query: MERGE with `UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@rows_json)))` as source (no staging table; node params are STRING-only so timestamps are cast in SQL); Insert (streaming) is **not** used | yes — MERGE on `deal_id`; single statement | Divergent mechanism (load job + MERGE vs inline MERGE), same table state — remediation: SQL generated from `bigquery_schema.sql` |
| **L8** Watermark advance | in function (A) | second Execute Query MERGE on `report_state` with `TIMESTAMP(@ts)`; wired after L7 with Stop-on-error | yes — only after successful MERGE | Parallel (same table, same SQL, same ordering) |
| **L9** Delivery (XLSX/email) | Webhook → Split Out → Code → Convert to File XLSX → Email Send (SMTP); fixes: Header Auth, zero-row branch, env-driven recipients, `--no-cpu-throttling` or respond-when-finished | same tail inside the full workflow | **no** — an email is not idempotent; re-trigger re-sends. Make it harmless: deliver from `new_deals_last_7d` so a re-send is the same report | Parallel between B1 and B2 (identical nodes); vs A: A has no delivery of its own — this layer *is* n8n in both A and B |
| **L10** Write-back to HubSpot | not in scope (A has none) | HubSpot node Deal→Update per item (`PATCH`), or HTTP Request to `batch/update`; Code node skips rows whose value already matches (CONVENTIONS) | conditional: PATCH of equal values is a no-op; skip logic keeps the audit clean | Divergent vs A (A: none) and vs C's remote-JS batch PATCH — remediation: same skip rule and same property names |
| **L11** Dry-run gate | `?dry_run=1` on the function (A); n8n not called when dry (`main.py:201`) | `?dry_run=1` on the webhook → IF node bypasses MERGE, watermark and email; reads still happen; manual editor execution is the n8n-native rehearsal | yes (writes nothing) | B1 Parallel; B2 Conditional — same "nothing written" result; A additionally skips reads |
| **L12** Replay / backfill | `UPDATE report_state SET watermark=…` then trigger (A) | identical SQL, then hit the webhook with `?entity=` | yes | Parallel |
| **L13** Audit trail | BigQuery `first_seen_run/last_seen_run` (A) + n8n execution record of the delivery (pruned 336 h/10k by default) | BigQuery rows + n8n execution per run in Cloud SQL (`EXECUTIONS_DATA_MAX_AGE=2160` for 90 days) + Cloud Logging stdout | yes (append-only) | Conditional — same BigQuery evidence; the n8n execution log is extra and only as durable as its pruning setting |
| **L14** Access control | function private (OIDC) as A; n8n editor public URL + owner login + 2FA; webhook Header Auth | same; optional IAP on Cloud Run (`gcloud run services update n8n --iap`) secures the editor on `run.app` but intercepts the Scheduler's webhook calls too | n/a | Divergent — A has no UI and uses IAM only; remediation: Header Auth on webhooks, strong owner credentials or IAP + Scheduler with an IAP-accepted identity |
| **L15** Concurrency & retry safety | function `--max-instances 1 --concurrency 1` (A); n8n side only delivers | `maxScale 1` + `N8N_CONCURRENCY_PRODUCTION_LIMIT=1` + respond-when-finished + Cloud Run `timeout 900` ≥ Scheduler deadline; node-level Retry On Fail on HubSpot/BigQuery nodes; Error Workflow | yes when all four are set | Conditional — same single-writer guarantee only with the concurrency limit *and* respond-when-finished |
| **L16** Observability | function log line (A) + n8n Executions list + Cloud Logging | n8n Executions (success/error, per-node data), stdout JSON logs in Cloud Logging, `N8N_METRICS=true` optional, Error Workflow email | n/a | Divergent — remediation: Error Workflow that posts the failure (entity, window, node) and a log-based alert on `n8n` stderr |
| **L17** Cost & scale-to-zero | A ≈ <$1 + Cloud SQL $8.6 + Cloud Run ≈ $0 (scale-to-zero OK because BigQuery is the truth) ≈ **$9–11/month** | webhook variant ≈ **$9–11/month**; Schedule-Trigger variant (`minScale 1`, `--no-cpu-throttling`) ≈ **$61–80/month**; queue mode ≈ +£55–80 (not needed) | n/a | Divergent — A has no always-on component; remediation: Cloud Scheduler→webhook keeps n8n at zero; Cloud SQL `db-f1-micro` is the floor |

---

## 5 · Gaps (testable claims)

| id | sev | claim | evidence | fix |
|---|---|---|---|---|
| B-G01 | high | A Schedule Trigger in n8n on Cloud Run with `min-instances=0` does not fire at Monday 07:00; the durable scheduler does not change this because no instance is awake to poll. | community thread 269677 ("won't fire if the instance is scaled to zero"); durable-scheduler doc: database-backed queue, misfire grace 60 s, requires a running main | B2 uses Cloud Scheduler → Webhook (same clock as deploy.sh:28-32) and keeps `minScale 0`; or `minScale 1 --no-cpu-throttling` (+≈$53/mo) |
| B-G02 | high | n8n with the default `DB_TYPE=sqlite` on Cloud Run loses workflows, credentials and the auto-generated encryption key at every scale-to-zero or redeploy. | n8n Cloud Run doc "Easy mode": "Anytime this Cloud Run service scales to zero or is redeployed, the n8n data will be lost"; `N8N_ENCRYPTION_KEY` default "Random key generated by n8n" | `DB_TYPE=postgresdb` on Cloud SQL via `--add-cloudsql-instances`; `N8N_ENCRYPTION_KEY` from Secret Manager |
| B-G03 | high | The B1 webhook accepts unauthenticated POSTs: the node has no `authentication` and the function sends no header; anyone with the URL can email a forged report. | `n8n_NewDeals_Delivery.json:5-10` (no auth), `main.py:202` (`requests.post(url, json=payload)`), n8n recipes use `--allow-unauthenticated` | Header Auth on the Webhook node; `DELIVERY_WEBHOOK_TOKEN` secret in the function; Scheduler passes the same header in B2 |
| B-G04 | high | B1 can lose a week's email: the watermark advances before delivery and a failed POST (cold start > 30 s) is only logged. | `main.py:196` then `:200-203`; cold start 10–30+ s (community), `sleep 5` in official start command | retry with backoff in the function, or n8n reads `new_deals_last_7d` instead of the payload (idempotent re-send), or `minScale 1` |
| B-G05 | medium | B1 sends nothing on a zero-row week (Split Out of empty `body.rows` → 0 items → no email). | `json:23` Split Out, no branch | IF on `body.row_count` with a text-only email on the empty branch |
| B-G06 | high | B2 reintroduces the watermark race A fixed: a Scheduler retry after a Cloud Run 504 (default 300 s) runs a second execution concurrently inside the single n8n instance. | `N8N_CONCURRENCY_PRODUCTION_LIMIT` default `-1`; Cloud Run default timeout 300 s; Scheduler retries on non-2xx | `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`, `timeoutSeconds 900`, Scheduler `--attempt-deadline 900s`, Webhook responds when last node finishes |
| B-G07 | medium | With Cloud Run request-based billing (default `--cpu-throttling`) an n8n webhook that responds immediately has its remaining nodes CPU-throttled → stalled XLSX/email. | CPU-allocation doc: "CPU is only allocated during request processing"; `json:8` `responseMode: onReceived` | `run.googleapis.com/cpu-throttling: "false"` (as every official recipe) or respond-when-finished |
| B-G08 | medium | The BigQuery node's named parameters are STRING-only; TIMESTAMP/BOOL/arrays cannot be passed as typed parameters. | `executeQuery.operation.ts` lines 304-312 ("the only supported type here is STRING"; "Arrays, dates and struct types … not yet supported") | cast in SQL (`TIMESTAMP(@ts)`), pass the row set as one JSON string and `UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@rows_json)))` |
| B-G09 | medium | The BigQuery node's Insert is a streaming insert; a staging table fed by it cannot be truncated/DML-ed while rows are in the streaming buffer, so `main.py:124` (`WRITE_TRUNCATE` load + MERGE) does not port one-to-one. | node source uses `tabledata.insertAll`; BigQuery streaming-buffer DML restriction (BigQuery docs) **[restriction text not re-fetched this session]** | no staging table: single MERGE with inline JSON source (§3.4) — also atomic |
| B-G10 | high | n8n has no ADC/Workload-Identity credential: BigQuery access from n8n requires a service-account JSON key stored in Cloud SQL (encrypted), and the HubSpot token is copied out of Secret Manager into an n8n credential. | Google service-account credential doc (email + private key only); external-secrets env page lists only timing vars (provider is a licensed feature) | dedicated `n8n-bq` SA with the same two roles, key rotation in `secrets.sh`; or metadata-server token via HTTP Request (check `N8N_SSRF_PROTECTION_ENABLED`, default off, blocks 169.254.0.0/16 when on) |
| B-G11 | medium | A JS port of `hot_score()` differs from Python at `.x5` rounding (`round()` half-to-even vs `Math.round` half-up) and in `.days` floor semantics unless emulated. | `main.py:68` `round(s, 1)`; `:58, :63` `.days` | `round1()` and `days()` helpers in `hot_score.js`; vectors with a `.x5` case and negative/positive day deltas |
| B-G12 | medium | The n8n HubSpot node has no pipelines/owners operations, and Search pages at 100 (not 200) and caps filter groups at 3. | `HubspotV2.node.ts` deal search (`body.limit \|\| 100` in `hubspotApiRequestAllItems`, "You can only have 3 filter groups"); operation list in docs | two HTTP Request nodes for `/crm/v3/pipelines/deals` and `/crm/v3/owners`; one filter group suffices; 5 req/s limit still far away |
| B-G13 | medium | `n8nio/n8n:latest` drifts: env names (`WEBHOOK_URL` deprecated since 2.35.0 → `N8N_WEBHOOK_URL`) and node `typeVersion` defaults change; the JSON pins `webhook 2, splitOut 1, code 2, convertToFile 1.1, emailSend 2.1`. | endpoints env page; `Hubspot.node.ts` `defaultVersion: 2.2`; n8n doc "current stable 2.41.7" | pin `docker.io/n8nio/n8n:2.41.7` (or digest) in `service.yaml`; bump deliberately with a test run |
| B-G14 | medium | n8n's default health path `/healthz` collides with Cloud Run's reserved path and breaks the canvas connection. | n8n Cloud Run doc caveat | `N8N_ENDPOINT_HEALTH=health`, `QUEUE_HEALTH_CHECK_ACTIVE=true`, startup probe on `/health` |
| B-G15 | low | Workflow JSON cannot be imported with `docker exec` on Cloud Run; credential ids in the JSON must be remapped. | Server CLI doc (`docker exec -u node …` pattern); `json:90` `REPLACE_WITH_CREDENTIAL_ID` | Cloud Run Job running `n8n import:credentials && n8n import:workflow && n8n publish:workflow`, stable ids; or public API |
| B-G16 | medium | Securing the n8n editor with IAP on Cloud Run intercepts *all* ingress including the Scheduler's webhook calls. | IAP-on-Cloud-Run doc: "secure traffic … from all ingress paths, including default run.app URLs"; "Services relying on their own authentication … might fail" | choose: public service + webhook Header Auth + owner 2FA (recommended), or IAP and give Scheduler an identity in `iap.httpsResourceAccessor` **[Scheduler-through-IAP path unverified]** |
| B-G17 | low | n8n's execution history is pruned at 336 h / 10 000 executions by default — too short to be the audit trail. | executions env page | BigQuery rows are the audit (Parallel with A); set `EXECUTIONS_DATA_MAX_AGE=2160` for 90 days of per-node evidence |
| B-G18 | low | Shared-core Cloud SQL tiers are outside the Cloud SQL SLA. | Cloud SQL pricing: "Shared CPU machine types (db-f1-micro and db-g1-small) are not covered by the Cloud SQL SLA" | acceptable for a weekly internal job; BigQuery remains the truth; document in the runbook |

---

## 6 · Building blocks (CloudBQ)

All paths relative to `/home/user/CloudBQ`. Status: existing · modify · new. Each block is one aider recipe (one commit), per `.claude/skills/aider-scaffold/SKILL.md`.

| path | kind | status | role | idempotency note |
|---|---|---|---|---|
| `cloud_function_new_deals/n8n_NewDeals_Delivery.json` | file | existing | B1 source of truth today; becomes the seed of `workflows/NEW_DEALS_DELIVERY.json` | re-import by stable id overwrites |
| `cloud_function_new_deals/main.py` | file | modify | send `X-Delivery-Token` header and retry the delivery POST 3× with backoff; keep everything else | delivery retry is safe: MERGE and watermark already done; n8n re-send is the same report |
| `cloud_function_new_deals/deploy.sh` | file | modify | create `n8n-webhook-token` secret, grant accessor, `--set-secrets DELIVERY_WEBHOOK_TOKEN=n8n-webhook-token:latest` | `create \|\| versions add` pattern as for `hubspot-token` |
| `deploy/n8n/.env.example` | file | new | `PROJECT PROJECT_NUMBER REGION DATASET N8N_IMAGE=docker.io/n8nio/n8n:2.41.7 SQL_TIER=db-f1-micro MIN_SCALE=0 MAIL_FROM MAIL_TO` | scripts fail loudly on missing/placeholder values |
| `deploy/n8n/Dockerfile` + `deploy/n8n/startup.sh` | file | new | optional thin image: pins the upstream tag, maps `PORT`→`N8N_PORT`, `sleep 5`, `exec /docker-entrypoint.sh` | rebuild is reproducible from the pinned tag |
| `deploy/n8n/service.yaml` | file | new | Knative Service manifest (§3.4) with `${VAR}` placeholders rendered by `envsubst` | `gcloud run services replace` is declarative/idempotent |
| `deploy/n8n/cloudsql.sh` | file | new | Cloud SQL Postgres 17 `db-f1-micro` HDD 10 GB zonal, db `n8n`, user `n8n-user`, password → Secret Manager | every step `describe \|\| create` |
| `deploy/n8n/secrets.sh` | file | new | `n8n-encryption-key` (openssl rand 42), `n8n-db-password`, `n8n-webhook-token`; SA `n8n-run` (`cloudsql.client`, `secretmanager.secretAccessor`); SA `n8n-bq` (`bigquery.jobUser` + dataset `dataEditor`) + key → generates `credentials.import.json` (BigQuery SA, HubSpot App Token from `hubspot-token`, SMTP, Header Auth) into a gitignored path | create-or-add-version; key rotation = new key + re-import |
| `deploy/n8n/deploy_n8n.sh` | file | new | `envsubst < service.yaml \| gcloud run services replace -`; prints URL; `--dry-run` renders only | declarative |
| `deploy/n8n/import_workflows.sh` | file | new | Cloud Run Job (same image, DB env, secrets) running `n8n import:credentials`, `n8n import:workflow --separate --input=workflows/`, `n8n publish:workflow`; `--dry-run` prints the command | stable ids → overwrite in place |
| `deploy/n8n/scheduler.sh` | file | new | two Scheduler jobs → `/webhook/new-deals-run?entity=…` with Header Auth, `0 7 * * 1` Europe/Zurich, 3 retries, 900 s deadline; `--pause` creates them paused until the dry run passes | `create \|\| update` |
| `workflows/NEW_DEALS_DELIVERY.json` | file | new | B1 JSON hardened: stable id, Header Auth, zero-row IF branch, recipients from `$vars`/env, `responseMode lastNode` | import by id |
| `workflows/NEW_DEALS_FULL.json` | file | new | B2 graph (§3.1); generated by `build_workflow.py` — do not hand-edit the `jsCode` fields | import by id |
| `workflows/NEW_DEALS_ERRORS.json` | file | new | Error Trigger → Email with workflow, node, message, execution URL | n/a |
| `workflows/src/hot_score.js` | file | new | the JS port (§3.4) exported for Node tests and injected into the Code node | pure function |
| `workflows/src/shape.js` | file | new | `nameKey()`, `shape()` port (`main.py:139-165`) | pure function |
| `workflows/src/build_workflow.py` | file | new | reads `workflows/templates/NEW_DEALS_FULL.template.json`, injects `src/*.js`, generates the MERGE SQL from `bigquery_schema.sql`, validates node `typeVersion`s against a pinned list, writes `NEW_DEALS_FULL.json` | deterministic output; `--check` exits 1 on drift |
| `tests/vectors/hot_score_vectors.json` + `tests/test_hot_score_parity.py` | file | new | vectors generated from `main.py:hot_score` (incl. `.x5` boundary, missing fields, PKI vs non-PKI, closedate > 2026, recency bands); pytest runs Python and `node -e` on `hot_score.js` and compares | shared by Scenarios A/B/C |
| `docs/scenario_B.md` | file | new | this analysis condensed into a runbook: order of scripts, dry-run gate, replay, cost table, what is lost vs A | docs only |

Second host (`/home/user/IC-DBT-BQ`): the reusable pieces are `build_workflow.py`'s "inject code files into n8n JSON + validate typeVersions" and the Cloud Run Job import pattern; neither is needed by the dlt loader today, so no block is proposed there for Scenario B.

---

## 7 · Open questions (with the default assumed)

1. **Which B2 trigger variant?** Default: Cloud Scheduler → Webhook with `minScale 0` (same clock as A, ≈ $9–11/month). The Schedule-Trigger/always-on variant is documented but not scaffolded.
2. **Service-account key policy.** Default: the project allows SA key creation; `n8n-bq` key lives only in the n8n credential store. If `iam.disableServiceAccountKeyCreation` is enforced, fall back to the metadata-token HTTP path and drop the BigQuery node.
3. **Does the HTTP Request node accept the `hubspotAppToken` predefined credential?** Default: yes (n8n exposes most app credentials to HTTP Request); fallback is a Header Auth credential carrying `Authorization: Bearer <token>`.
4. **IAP for the editor?** Default: no IAP; public URL + owner password + 2FA + webhook Header Auth. Revisit if the org requires SSO (Enterprise) or IAP.
5. **SMTP provider.** Default: an SMTP credential (Workspace relay or SendGrid); Gmail node via OAuth is the alternative the n8n Cloud Run doc describes.
6. **Zurich region.** Default: `europe-west6` for data residency (Tier 2 prices, ≈ +20 %); `europe-west1` if cost wins.
7. **Should B1 deliver from the BigQuery view instead of the payload?** Default: yes — it makes delivery idempotent and lets A, B2 and C share one delivery workflow reading `new_deals_last_7d`.
8. **Event mode (HubSpot workflow webhook, `main.py:179-182`) in B2?** Default: not in v1.

## 8 · Verdict for the synthesis

- B1 is a legitimate tail for Scenario A: it adds no state and no idempotency debt once B-G03/B-G04/B-G05 are fixed. It is the only place n8n should be *required* in the plan.
- B2 can reach the same end state (same tables, same watermark semantics, same clock) and is idempotent by construction *if* L4, L7, L8, L15 are built as specified — but it pays for it with an always-on Cloud SQL, a service-account key, a copied secret, a JS/Python double of the scorer, and a deploy unit with seven moving parts. Its one genuine advantage over A is the inline-JSON MERGE (single atomic statement) and the editor's per-node execution data for debugging.
- Layers Parallel with A under B2: L8, L12 (and L9 is shared infrastructure). Conditional: L3, L4, L6, L11, L13, L15. Divergent: L0, L1, L2, L5, L7, L10, L14, L16, L17.
