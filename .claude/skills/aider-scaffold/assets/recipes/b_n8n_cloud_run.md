# Recipe — scenario B deploy unit: n8n on Cloud Run with Cloud SQL, secrets, scheduler

/add deploy/n8n/service.yaml deploy/n8n/cloudsql.sh deploy/n8n/secrets.sh deploy/n8n/deploy_n8n.sh deploy/n8n/import_workflows.sh deploy/n8n/scheduler.sh
/read-only CONVENTIONS.md .env.example

From discovery/scenario_B.md (n8n docs + Google codelab, 2026-10): Knative Service manifest with a PINNED n8nio/n8n image,
--port 5678 = N8N_PORT, N8N_PROTOCOL=https, N8N_HOST/N8N_WEBHOOK_URL/N8N_EDITOR_BASE_URL = deterministic run.app URL,
N8N_ENDPOINT_HEALTH=health, "sleep 5; n8n start", cpu-throttling false, minScale 0 / maxScale 1, Cloud SQL Postgres 17
(db-f1-micro) via the cloudsql-instances annotation, N8N_ENCRYPTION_KEY + DB password from Secret Manager,
EXECUTIONS_MODE=regular, N8N_CONCURRENCY_PRODUCTION_LIMIT=1, EXECUTIONS_DATA_MAX_AGE=2160, env access for $env allowed.
Scripts (create-or-update, DRYRUN=1 prints commands): secrets.sh (three secrets, SAs n8n-run / n8n-bq, key to a gitignored
file), cloudsql.sh, deploy_n8n.sh (render + `gcloud run services replace`), import_workflows.sh (public REST API, PUT by stable
id, credential placeholder remap from workflows/credentials.map.json), scheduler.sh (Cloud Scheduler → webhook with
X-Delivery-Token, created paused; `enable` after the dry run). Refuse :latest images and placeholders.
