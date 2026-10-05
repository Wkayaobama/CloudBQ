#!/usr/bin/env bash
# deploy_job.sh — Cloud Run job for the write-back + Cloud Scheduler → jobs.run. Create-or-update everywhere.
#   writeback/deploy_job.sh            deploy (WRITEBACK_APPROVE stays 0 → dry executions)
#   writeback/deploy_job.sh execute    run once now and wait (dry unless WRITEBACK_APPROVE=1 was set on the job)
#   writeback/deploy_job.sh live       flip WRITEBACK_APPROVE=1 on the job (the gate)
#   DRYRUN=1 …                         print the commands
# Settings from ../.env: PROJECT REGION DATASET HUBSPOT_WRITE_TOKEN_VERSION (pinned Secret Manager version of hubspot-token-write)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${REGION:=europe-west6}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${JOB:=new-deals-writeback}" "${WRITEBACK_SCHEDULE:=30 5 * * 1}"
DRYRUN="${DRYRUN:-0}"
SA="new-deals-writeback@${PROJECT}.iam.gserviceaccount.com"; SCHED_SA="new-deals-scheduler@${PROJECT}.iam.gserviceaccount.com"
run() { if [[ "$DRYRUN" == 1 ]]; then printf '  $'; printf ' %q' "$@"; echo; else "$@"; fi; }
ensure_sa() { if [[ "$DRYRUN" == 1 ]] || ! gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1; then run gcloud iam service-accounts create "$1" --project "$PROJECT" --display-name "$2"; fi; }

case "${1:-deploy}" in
  deploy)
    : "${HUBSPOT_WRITE_TOKEN_VERSION:?pin a Secret Manager version of hubspot-token-write (not latest)}"
    ensure_sa new-deals-writeback "new deals write-back job"; ensure_sa new-deals-scheduler "scheduler invoker for jobs.run"
    run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser --condition=None
    run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""
    run gcloud secrets add-iam-policy-binding hubspot-token-write --project "$PROJECT" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor
    run gcloud run jobs deploy "$JOB" --project "$PROJECT" --region "$REGION" --source "$HERE" --service-account "$SA" \
      --tasks 1 --max-retries 2 --task-timeout 900s \
      --set-env-vars "BQ_PROJECT=${PROJECT},BQ_DATASET=${DATASET},WRITEBACK_APPROVE=${WRITEBACK_APPROVE:-0}" \
      --set-secrets "HUBSPOT_TOKEN=hubspot-token-write:${HUBSPOT_WRITE_TOKEN_VERSION}"
    run gcloud run jobs add-iam-policy-binding "$JOB" --project "$PROJECT" --region "$REGION" --member "serviceAccount:$SCHED_SA" --role roles/run.invoker
    URI="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB}:run"
    ARGS=(--project "$PROJECT" --location "$REGION" --schedule "$WRITEBACK_SCHEDULE" --time-zone "Europe/Zurich" --uri "$URI" --http-method POST --oauth-service-account-email "$SCHED_SA" --max-retry-attempts 3)
    if [[ "$DRYRUN" != 1 ]] && gcloud scheduler jobs describe "$JOB" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then run gcloud scheduler jobs update http "$JOB" "${ARGS[@]}"; else run gcloud scheduler jobs create http "$JOB" "${ARGS[@]}"; fi
    echo "dry execution now:  writeback/deploy_job.sh execute      (WRITEBACK_APPROVE=0 → rows logged with status DRY)"
    echo "go live:            writeback/deploy_job.sh live" ;;
  execute) run gcloud run jobs execute "$JOB" --project "$PROJECT" --region "$REGION" --wait ;;
  live)    run gcloud run jobs update "$JOB" --project "$PROJECT" --region "$REGION" --update-env-vars WRITEBACK_APPROVE=1 ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
