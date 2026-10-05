# Recipe — scenario A deploy unit in canonical, gated, re-runnable form

/add cloud_function_new_deals/deploy.sh cloud_function_new_deals/bigquery_schema.sql cloud_function_new_deals/.gcloudignore .env.example
/read-only cloud_function_new_deals/main.py CONVENTIONS.md

Rewrite deploy.sh as the single execution surface for scenario A: `deploy.sh <step>` with a case list
(check-env enable-apis iam tables secret deploy invoker | dry | enable pause run replay probe status logs url | all).
- Settings from ../.env (template .env.example); refuse placeholders (`your-*`, `<…>`) and missing values.
- Canonical deploy: `gcloud run deploy $FN --source cloud_function_new_deals --function new_deals_report --base-image python312
  --no-allow-unauthenticated --service-account $SA --timeout 540 --memory 512Mi --max-instances 1 --concurrency 1`,
  env via `^|^` delimiter, `--set-secrets HUBSPOT_TOKEN=hubspot-token:<pinned version>` (default: latest enabled version number).
- URL from `gcloud run services describe --format 'value(status.url)'` (the cloudfunctions.net URI does not exist on this path).
- IAM: SA create-if-missing, roles/bigquery.jobUser, roles/run.builder for the Cloud Build compute SA, roles/run.invoker on
  the service, roles/secretmanager.secretAccessor on the secret, DCL GRANT dataEditor with a double-quoted principal.
- Tables: render bigquery_schema.sql with envsubst (${PROJECT} ${DATASET} ${BQ_LOCATION}); CREATE SCHEMA IF NOT EXISTS first;
  add report_state.lock_until and new_deals_runs; all DDL idempotent.
- Scheduler: two HTTP jobs, SEALSQ `0 7 * * 1` and ICALPS `20 7 * * 1` Europe/Zurich (never the same minute), OIDC as the SA,
  attempt-deadline 600s, 3 retries, create-or-update, created PAUSED; `enable` resumes them only after `dry` passed.
- `dry`: curl both entities with `?dry_run=1`, assert rows_written == 0 and dry_run == true.
- `DRYRUN=1` prints every command instead of running it, so the whole sequence can be rehearsed offline (`bash -n` + `DRYRUN=1 ./deploy.sh all`).
- .gcloudignore keeps README, n8n JSON, deploy.sh, schema and .env files out of the source upload.
Do not change main.py in this step.
