# Discovery: hot-deal scorer and remote-JS write-back patterns (Scenario C input)

Date: 2026-10-05. Searched read-only: `/home/user/CloudBQ` (branch `claude/cloud-run-bigquery-pipeline-e94ziy`),
`/home/user/wkayaobama/mir-load`, `/home/user/wkayaobama/wkayaobama-skills`, plus fresh depth-1 clones
`/home/user/wkayaobama/Hs-Logic` (HEAD d777b29, 2026-08-28) and `/home/user/wkayaobama/HubSpot-Ruler`
(HEAD e7e3f42, 2026-09-25). Also ran GitHub code search over `user:Wkayaobama` for `hot_deals_score` and `2.0712`.

## 1. Headline

- **`hot_deals_score.js` does not exist in any searched location.** Not on disk, not in either cloned repo,
  and GitHub code search over the user's repos returns only `CloudBQ/cloud_function_new_deals/main.py`.
  The constants (2.0712, 1.2399, -0.4136, 1.0918, 4.9843, 1.3018, 1.5620, -6.4788) appear nowhere else.
  Caveats: clones are depth-1 (history not searched); GitHub code search covers only repos the token can see.
- **The only executable scorer is the Python port in `main.py`** (`W`, `BIAS`, `THRESHOLD`, `CR`, `MAXC`, `hot_score()`),
  annotated "same constants as hot_deals_score.js, fitted 2026-10-01". Treat it as canonical for Scenario C.
- The CloudBQ README also names BigQuery views `sealsq_hot_deals_v1` and `sealsq_top5_weekly_v1`; their SQL is in no repo either.
- **No remote JS anywhere batch-writes to HubSpot deals.** `batch/update` matches zero files. The user's matrix cell
  "Remote JS: batch PATCH on deals" is a design intent, not existing code. The closest reusable JS is a single-record
  PATCH inside a HubSpot 2026.03 app-function (section 3a).
- **No scheduled/cron JS, no Cloud Run jobs, and exactly one n8n Code node** (a column projection, no HubSpot call).

## 2. Scorer summary (from `/home/user/CloudBQ/cloud_function_new_deals/main.py`, lines 40-72)

Scope: SEALSQ pipelines with a conversion rate only: `12096408` (SealSQ Hardware, `hw`) and `13772279`.
Pipelines `705868909`, `934982230` (SEALSQ) and `766126206` (ICALPS) return `(None, None)`.

Inputs (HubSpot deal properties, all in `PROPS`):

| Feature | Source properties | Normalisation |
|---|---|---|
| `stage_prob` | `hs_deal_stage_probability` | as-is (0..1) |
| `proximity_2026` | `closedate` | 1.0 if year <= 2026, else `max(0, 1 - days_after_2026-12-31 / 730)` |
| `missing_2026_field` | HW: `calculation___pipeline_2026__k__`; others: `services_value_2026` | 1.0 if empty/zero else 0.0 |
| `pipeline_conversion` | `pipeline` | `CR[pipeline] / max(CR)`; `CR = {12096408: 84/730 = 0.1151, 13772279: 51/303 = 0.1683}` so HW = 0.684, other = 1.0 |
| `arr_points` | `asp_in_usd_q2_2022_calculation` (label "ARR ($K/Y)"), fallback `tpm__k_y`, then `services_value_2026`; branch on `product_hierarchy == "PKI"` | PKI: <20 -> 0.5, <=50 -> 1, else 2. Non-PKI: <100 -> 0.5, <=500 -> 1, <=1000 -> 2, else 3. Divided by 3 |
| `engagement` | `num_contacted_notes` | `log1p(n) / log1p(223)` (`MAXC = 223`) |
| `recency` | `notes_last_updated` | 1.0 if <= 90 days, 0.5 if <= 180, else 0.0. **Weight is 0.0** (fitted out) |
| `not_in_forecast` | `revenue_state` | 0.0 if in ("Forecast", "BIBA") else 1.0 |

Weights `W`: stage_prob 2.0712, proximity_2026 1.2399, missing_2026_field -0.4136, pipeline_conversion 1.0918,
arr_points 4.9843, engagement 1.3018, recency 0.0, not_in_forecast 1.5620. `BIAS = -6.4788`.
`z = sum(W[k]*f[k]) + BIAS`; `score = 100 / (1 + exp(-z))`, rounded to 1 dp; `hot = score >= 45.0`.

Outputs: `day1_hot_score FLOAT64`, `day1_hot_flag BOOL` (columns in `hubspot.new_deals`, `bigquery_schema.sql`),
also in the function payload rows and as `day1_hot[]` (deal ids) at payload top level, and in the n8n `COLS` list.
**No HubSpot deal property for the score exists in any repo** (no property definition, no `crm.objects.deals.write`
scope on the CloudBQ token: `deploy.sh` grants `crm.objects.deals.read, crm.schemas.deals.read, crm.objects.owners.read`).
Golden vector from README: "Lattice Keystone C0 ASIC, 16,002 kUSD, Qualified 20%, day-1 score 81".

BigQuery portability: every term is plain SQL (`CASE`, `LN(1+x)`, `EXP`, `DATE_DIFF`, `SAFE_DIVIDE`); recency can be
dropped (weight 0). Property labels/semantics for the inputs are documented in
`HubSpot-Ruler/SEALSQ/SEALSQ_Property_Resource.md` (e.g. `revenue_state` values Pipeline/BIBA/Forecast;
`asp_in_usd_q2_2022_calculation` is a recycled field labelled "ARR ($K/Y)").

## 3. Remote-JS patterns that reach HubSpot (what exists, exactly)

### 3a. `HubSpot-Ruler/ui-extension/src/app/functions/updateDealProperties.js` (single-record PATCH)
- Runtime: HubSpot developer-platform **2026.03 app-function** (serverless, Node 18+, native `fetch`, no SDK).
  Invoked from a CRM card via `hubspot.serverless('update_deal_properties', {parameters:{dealId, properties}})`.
- Endpoint: `PATCH https://api.hubapi.com/crm/v3/objects/deals/{dealId}` with `{properties}`.
- Auth: `process.env.PRIVATE_APP_ACCESS_TOKEN`, auto-injected by the platform (`secretKeys: []`);
  scopes declared in `app-hsmeta.json` (`crm.objects.deals.write` etc.), `permittedUrls.fetch = ["https://api.hubapi.com"]`.
- Batching: none (one deal per call). Retry/429: none. Timeout: none set.
- Idempotency: PATCH same values is a no-op; the UI pre-computes a **diff of only-changed fields**
  (`cards/utils/propertyValue.ts`: `serializeForWrite` -> string wire format, `changed()` null/empty-normalised compare).
- Error handling: never throws; returns `{status:'SUCCESS', id, properties}` or
  `{status:'ERROR', message, detail (<=800 chars of body), httpStatus}`; body parsed defensively (`rawText` fallback).
- Payload rule: every property value stringified; `null`/`undefined` skipped; dates as epoch-ms UTC midnight strings.
- Trigger limitation (recorded in `hermes-agent/docs/ARCHITECTURE.md` section 5): **2026.03 serverless has no
  scheduled/cron invocation**; endpoint functions need Content Hub Enterprise and ship unauthenticated. So this
  pattern cannot by itself be the weekly L3 trigger.

### 3b. `HubSpot-Ruler/ui-extension/src/app/functions/createIcAlpsDeal.js` (POST + associations)
- `POST /crm/v3/objects/deals`; forces `pipeline=766126206`, `dealstage=1116419644`; optional `associations`
  block with HUBSPOT_DEFINED typeIds (deal->contact 3, deal->company 5). Same auth/error shape as 3a.
- Not idempotent (a retry creates a duplicate). Sibling files `createIcAlpsContact.js`, `createIcAlpsCompany.js`.

### 3c. `HubSpot-Ruler/hermes-agent/hubspot/workflow-custom-code/hermesTrigger.js` (workflow custom code -> external compute)
- HubSpot **workflow "Custom code" action** (Node 20, axios preloaded, 20 s / 128 MB, needs Ops/Data Hub Pro+).
- Does **not** write to HubSpot. Builds `{action, objectType, objectId, portalId, inputFields}`, signs
  `HMAC-SHA256(secret, "${timestamp}.${rawBody}")`, headers `X-Hermes-Timestamp` / `X-Hermes-Signature: sha256=...`,
  POSTs to `HERMES_BRIDGE_URL` with 10 s timeout, returns `callback({outputFields:{hermes_status, hermes_task_id}})`.
- Secrets as action env vars (`HERMES_WEBHOOK_SECRET`, `HERMES_BRIDGE_URL`). Fire-and-queue: bridge answers 2xx
  immediately; bridge verifies signature within a 5-minute replay window (`hermeslib/security.py`).

### 3d. `HubSpot-Ruler/hermes-agent/hubspot/workflow-action/hermes-trigger-hsmeta.json` (workflow-action component)
- Declarative `workflow-action` for the 2026.03 private app (no Ops Hub needed). HubSpot POSTs
  `{callbackId, origin.portalId, object, inputFields}` to `actionUrl`, signed **X-HubSpot-Signature v2**
  (hex SHA-256 of `clientSecret+method+URI+body`). Failure semantics HubSpot-managed: 4xx = failed,
  **5xx retried with exponential backoff up to 3 days, 429 honours Retry-After**.
- Async completion path noted: return `hs_execution_state=BLOCK` + `hs_expiration_duration`, then
  `POST /automation/v4/actions/callbacks/{callbackId}/complete` (scope `automation`).

### 3e. Non-JS write patterns worth porting (the user's JS has no retry/batch/idempotency code)
- `HubSpot-Ruler/hermes-agent/skills/revops/hubspot-crm/hs_api.py`: `PATCH /crm/v3/objects/{type}/{id}`;
  Bearer `HUBSPOT_PRIVATE_APP_TOKEN`; **429 -> one 10 s backoff, retry once, then surface; never loop**;
  guardrail: property updates only on explicit instruction, Notes/Tasks by default, no deletes.
- `mir-load/pipeline/library_files/uploader.py` `_retry`: retryable = 429 or 5xx or ConnectionError/Timeout;
  backoff schedule (1, 2, 4, 8, 16) s; honours `Retry-After` capped at 60 s; **idempotency via ledger keyed by
  legacy_id**; dry-run default behind `MRLOAD_APPROVE_*` gates; two-phase (upload, attach) with per-row status.
- `Hs-Logic/backend/app/routes/hubspot.py` suppression list: create static list then
  `PUT /crm/v3/lists/{id}/memberships/add` in **chunks of 100 with 120 ms spacing**; per-chunk added/errors counters;
  only `batch` endpoint anywhere is `POST /crm/v4/associations/deals/companies/batch/read` (a read).
- `CloudBQ/cloud_function_new_deals/main.py` `HubSpot` class: Bearer token from Secret Manager env; search
  paginated via `after`, `limit 200`, `createdate GTE/LT` window; `raise_for_status()`, no retry.
- Rate-limit facts recorded in `hermes-agent/docs/ARCHITECTURE.md` section 6: CRM search 5 req/s account-wide,
  200/page, 10,000-result ceiling; private app 190 req/10 s + 625k/day (Pro); `/crm/v3` paths still valid after the
  2026-03-30 date-based API versioning.

## 4. Scheduling, Cloud Run, n8n findings

| Looked for | Found |
|---|---|
| Scheduled/cron JS | None. Scheduling exists only as Cloud Scheduler HTTP jobs (`CloudBQ/deploy.sh`, `0 7 * * 1` Europe/Zurich, OIDC, 3 retries), a systemd timer (`hermes-scraper.timer`, 4x/day, Python), and `hermes cron create` (agent harness). |
| Cloud Run jobs | None. Only gen2 Cloud Functions (`gcloud functions deploy --gen2`) and a VM docker-compose guide for n8n (`CloudBQ/alternative/cloudcompute.md`). |
| n8n Code nodes | One: `CloudBQ/.../n8n_NewDeals_Delivery.json` node "Shape columns" (`$input.all().map(...)` projecting `COLS`). Workflow is webhook -> splitOut -> code -> convertToFile (XLSX) -> emailSend; timezone Europe/Zurich; no Schedule Trigger, no HubSpot node. |
| `crm/v3/objects/deals` | CloudBQ main.py (search/get), Hs-Logic (list/search, read-only), HubSpot-Ruler app-functions (POST/PATCH), mir-load client.py (search/create), mir-load tests mock. |
| `stage_prob` | Only as `hs_deal_stage_probability` reads (Hs-Logic deals tab; HubSpot-Ruler property catalogues). |

## 5. Implications for Scenario C lane cells (layer ids from the fixed list)

- **L5 Scoring arithmetic**: canonical = Python `hot_score()`; the JS original is missing. Port the formula to a
  BigQuery SQL view (all terms are SQL-expressible) and keep constants in one place. Parity vs Scenario A:
  Divergent -> remediation: shared constants + golden vector (score 81 for the Lattice Keystone deal).
- **L10 Write-back to HubSpot**: nothing reusable beyond a single-record PATCH pattern (3a). A scheduled remote-JS
  writer needs, none of which exist yet: a cron-capable runtime (HubSpot app-functions cannot be scheduled),
  a token with `crm.objects.deals.write`, new deal properties for score/flag, `POST /crm/v3/objects/deals/batch/update`
  (<=100 inputs), Retry-After-aware backoff (port `uploader.py._retry`), and an idempotency guard
  (compare-before-write as in `propertyValue.ts changed()`, or a run ledger keyed by deal_id + run_timestamp).
- **L2 Secrets**: four conventions in the user's code: Secret Manager `--set-secrets` (CloudBQ), platform-injected
  `PRIVATE_APP_ACCESS_TOKEN` (app-functions), custom-code action secrets as env vars (hermesTrigger.js),
  `.env` chmod 600 (hermes VPS). Hs-Logic docker-compose warns env vars must be allow-listed explicitly.
- **L3 Trigger**: HubSpot-side scheduling of JS is not available on 2026.03 serverless; workflow actions can call
  out (3c/3d) and HubSpot retries 5xx for up to 3 days, which doubles as L15 retry semantics for an event path.
- **L13 Audit trail**: existing patterns are mir-load's ledger (keyed by legacy_id, status per row) and hermes'
  inbox files with `task_id` frontmatter and `done/`/`failed/` directories; BigQuery `new_deals` already keeps
  `first_seen_run`/`last_seen_run`.
- **L15 Concurrency & retry**: two house styles: "retry once then surface, never loop" (hs_api.py) vs
  5-step exponential backoff with Retry-After (uploader.py). CloudBQ main.py has no retry at all.
- **L14 Access control**: app-functions scope list in `app-hsmeta.json`; CloudBQ token is read-only;
  hermes uses a separate minimal-scope private app for agent writes.

## 6. File inventory

| Repo | Path | Why it matters |
|---|---|---|
| CloudBQ | `cloud_function_new_deals/main.py` | Only scorer implementation (Python); HubSpot search client; BigQuery MERGE + watermark |
| CloudBQ | `cloud_function_new_deals/bigquery_schema.sql` | Output columns `day1_hot_score`, `day1_hot_flag`; `new_deals_last_7d` view |
| CloudBQ | `cloud_function_new_deals/n8n_NewDeals_Delivery.json` | The single n8n Code node; webhook-triggered delivery |
| CloudBQ | `cloud_function_new_deals/deploy.sh` | Scheduler/OIDC/Secret Manager; read-only HubSpot scopes |
| CloudBQ | `cloud_function_new_deals/README.md` | Golden vector; names of BigQuery views not in any repo |
| HubSpot-Ruler | `ui-extension/src/app/functions/updateDealProperties.js` | Single-record PATCH on deals, PRIVATE_APP_ACCESS_TOKEN, structured errors |
| HubSpot-Ruler | `ui-extension/src/app/functions/createIcAlpsDeal.js` | POST deal + associations; forced pipeline/stage |
| HubSpot-Ruler | `ui-extension/src/app/cards/utils/propertyValue.ts` | Wire-format stringification and changed-field diff |
| HubSpot-Ruler | `ui-extension/src/app/app-hsmeta.json` | Scopes incl. `crm.objects.deals.write`; permitted fetch URL |
| HubSpot-Ruler | `ui-extension/docs/ARCHITECTURE.md` | Serverless function shape; install/reauthorize gotchas; 2025.2 has no serverless |
| HubSpot-Ruler | `hermes-agent/hubspot/workflow-custom-code/hermesTrigger.js` | Workflow custom-code JS: HMAC-signed POST to external bridge |
| HubSpot-Ruler | `hermes-agent/hubspot/workflow-action/hermes-trigger-hsmeta.json` + `README.md` | workflow-action component; HubSpot retry semantics; v2 signature |
| HubSpot-Ruler | `hermes-agent/docs/ARCHITECTURE.md` | Rate limits, 429 policy, "serverless cannot be cron'd", async callback path |
| HubSpot-Ruler | `hermes-agent/skills/revops/hubspot-crm/hs_api.py` | PATCH with 429 retry-once; write guardrails |
| HubSpot-Ruler | `hermes-agent/provision/systemd/hermes-scraper.timer` | Only cron-like scheduler in the repo (Python target) |
| HubSpot-Ruler | `SEALSQ/SEALSQ_Property_Resource.md`, `SEALSQ/sealsq_property_set.json` | Labels/semantics of scorer input properties |
| Hs-Logic | `backend/app/routes/hubspot.py` | Read-only deals/search; chunk-100 + 120 ms list writes; 401/403 mapping |
| Hs-Logic | `backend/app/cache.py`, `docker-compose.yml` | Single-flight TTL cache; env allow-list warning |
| mir-load | `pipeline/library_files/uploader.py` | `_retry` backoff + Retry-After; ledger idempotency; dry-run gates |
| mir-load | `pipeline/library_files/client.py`, `deals.py` | Thin requests client; deal create idempotent via ledger `legacy_deal_id` |
| wkayaobama-skills | `skills/workflowps/INTEGRATIONS.md` | Only HubSpot mention: `HUBSPOT_API_KEY` Bearer env var for an xlwings dashboard; no JS |
