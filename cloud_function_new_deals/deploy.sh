#!/usr/bin/env bash
# deploy.sh — one script is the execution surface for scenario A (Cloud Run function + Cloud Scheduler → BigQuery).
#
#   deploy.sh <step>      steps, in order:  check-env enable-apis iam tables secret deploy invoker  → dry →  enable
#   deploy.sh all         runs check-env … invoker (everything up to, not including, the gate)
#   deploy.sh dry         GATE: ?dry_run=1 for both entities; asserts rows_written == 0; nothing is written
#   deploy.sh enable      resumes the two Scheduler jobs (created paused) — only after `dry` passed
#   deploy.sh pause | run ENTITY | replay ENTITY FROM_ISO | probe | status | logs | url
#   DRYRUN=1 deploy.sh … prints every gcloud/bq command instead of running it (offline rehearsal of the sequence)
#
# Settings come from ../.env (see ../.env.example); placeholders are refused. Secrets never pass through this file
# except HUBSPOT_TOKEN when `secret` creates or rotates the Secret Manager secret.
# Every step is create-or-update, so re-running a step is safe (enable/pause check the job state first; `secret` adds a Secret
# Manager version per run; `run` moves the watermark — `replay` repeats a window). Documented in docs/PASS1_SEQUENCE.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; # shellcheck disable=SC1091
  . "$ROOT/.env"; set +a; }

: "${REGION:=europe-west6}" "${BQ_LOCATION:=EU}" "${DATASET:=hubspot}" "${FN:=new-deals-report}" "${SA_NAME:=new-deals-fn}" "${PORTAL_ID:=9201667}"
: "${SCHEDULE_SEALSQ:=0 7 * * 1}" "${SCHEDULE_ICALPS:=20 7 * * 1}" "${DELIVERY_WEBHOOK_URL:=}" "${SECRET_VERSION:=}"
DRYRUN="${DRYRUN:-0}"

die()  { echo "deploy.sh: $*" >&2; exit 2; }
say()  { printf '\n\033[1m── %s\033[0m\n' "$*"; }
run()  { if [[ "$DRYRUN" == 1 ]]; then printf '  $'; printf ' %q' "$@"; echo; else "$@"; fi; }
cap()  { if [[ "$DRYRUN" == 1 ]]; then { printf '  $'; printf ' %q' "$@"; echo; } >&2; echo "<${1##*/}-output>"; else "$@"; fi; }
sa()   { echo "${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"; }
url()  { cap gcloud run services describe "$FN" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'; }

check_env() {
  say "check-env"
  for v in PROJECT REGION DATASET FN SA_NAME BQ_LOCATION; do
    local val="${!v:-}"
    [[ -n "$val" ]] || die "$v is unset — copy .env.example to .env and fill it"
    [[ "$val" != your-* && "$val" != your_* && "$val" != "<"*">" ]] || die "$v still holds the template placeholder ($val)"
  done
  if [[ -f "$ROOT/.env" ]] && grep -Eq '^[[:space:]]*(export[[:space:]]+)?HUBSPOT_TOKEN=.+' "$ROOT/.env"; then
    die "HUBSPOT_TOKEN belongs in the shell for the secret step only, never in .env"
  fi
  command -v gcloud >/dev/null || die "gcloud not found"; command -v bq >/dev/null || die "bq not found"
  echo "  project=$PROJECT region=$REGION dataset=$DATASET fn=$FN sa=$(sa) schedules: SEALSQ '$SCHEDULE_SEALSQ' ICALPS '$SCHEDULE_ICALPS' (Europe/Zurich)"
}

enable_apis() {
  say "enable-apis"
  run gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com --project "$PROJECT"
}

iam() {
  say "iam — runtime service account, BigQuery roles, Cloud Build builder role"
  if [[ "$DRYRUN" == 1 ]] || ! gcloud iam service-accounts describe "$(sa)" --project "$PROJECT" >/dev/null 2>&1; then
    run gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" --display-name "new deals report function"
  fi
  run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$(sa)" --role roles/bigquery.jobUser --condition=None
  # organizations created after 2024-05-03 (iam.automaticIamGrantsForDefaultServiceAccounts): the default compute SA has no Editor grant; Cloud Build needs run.builder for --source deploys
  local pn; pn=$(cap gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
  run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:${pn}-compute@developer.gserviceaccount.com" --role roles/run.builder --condition=None
}

tables() {
  say "tables — dataset, report_state, new_deals, new_deals_runs, view; dataEditor grant"
  local rendered
  if command -v envsubst >/dev/null; then
    rendered=$(PROJECT="$PROJECT" DATASET="$DATASET" BQ_LOCATION="$BQ_LOCATION" envsubst '${PROJECT} ${DATASET} ${BQ_LOCATION}' < "$HERE/bigquery_schema.sql")
  else
    rendered=$(sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${BQ_LOCATION}/$BQ_LOCATION/g" "$HERE/bigquery_schema.sql")
  fi
  grep -q '\${' <<<"$rendered" && die "unrendered placeholder in bigquery_schema.sql"
  if [[ "$DRYRUN" == 1 ]]; then echo "  $ bq --project_id=$PROJECT query --use_legacy_sql=false --location=$BQ_LOCATION < bigquery_schema.sql (rendered, $(wc -l <<<"$rendered") lines)"
  else bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false <<<"$rendered"; fi
  # DCL: principal double-quoted (single quotes are also legal GoogleSQL; the quoting was never the failure — the dataset not existing was)
  run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false \
    "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:$(sa)\""
}

secret() {
  say "secret — hubspot-token in Secret Manager (create or add a version), accessor for the SA"
  if [[ "$DRYRUN" == 1 ]]; then echo "  (needs HUBSPOT_TOKEN in the environment; create || versions add)"; else
    [[ -n "${HUBSPOT_TOKEN:-}" ]] || die "HUBSPOT_TOKEN must be set in the environment for this step (not in .env)"
    if gcloud secrets describe hubspot-token --project "$PROJECT" >/dev/null 2>&1; then
      printf '%s' "$HUBSPOT_TOKEN" | gcloud secrets versions add hubspot-token --project "$PROJECT" --data-file=-
    else
      printf '%s' "$HUBSPOT_TOKEN" | gcloud secrets create hubspot-token --project "$PROJECT" --replication-policy automatic --data-file=-
    fi
  fi
  run gcloud secrets add-iam-policy-binding hubspot-token --project "$PROJECT" --member "serviceAccount:$(sa)" --role roles/secretmanager.secretAccessor
  echo "  pin this version in .env SECRET_VERSION: $(cap gcloud secrets versions list hubspot-token --project "$PROJECT" --filter 'state=enabled' --sort-by '~createTime' --format 'value(name.basename())' --limit 1)"
}

secret_version() {
  if [[ -n "$SECRET_VERSION" ]]; then echo "$SECRET_VERSION"; return; fi
  cap gcloud secrets versions list hubspot-token --project "$PROJECT" --filter 'state=enabled' --sort-by '~createTime' --format 'value(name.basename())' --limit 1
}

deploy() {
  say "deploy — canonical Cloud Run function deploy (source build), private, one instance, one request at a time"
  local ver; ver=$(secret_version)
  local env="^|^BQ_PROJECT=${PROJECT}|BQ_DATASET=${DATASET}|OVERLAP_MINUTES=5|FIRST_RUN_DAYS=7|PORTAL_ID=${PORTAL_ID}|DELIVERY_WEBHOOK_URL=${DELIVERY_WEBHOOK_URL}|ORCHESTRATOR=cloud-run-function"
  local secrets="HUBSPOT_TOKEN=hubspot-token:${ver}"
  [[ -n "${DELIVERY_WEBHOOK_TOKEN_SECRET:-}" ]] && secrets+=",DELIVERY_WEBHOOK_TOKEN=${DELIVERY_WEBHOOK_TOKEN_SECRET}:${DELIVERY_WEBHOOK_TOKEN_VERSION:-latest}"
  run gcloud run deploy "$FN" --project "$PROJECT" --region "$REGION" --source "$HERE" \
    --function new_deals_report --base-image python312 \
    --no-allow-unauthenticated --service-account "$(sa)" \
    --timeout 540 --memory 512Mi --max-instances 1 --concurrency 1 \
    --set-env-vars "$env" --set-secrets "$secrets"
  echo "  URL: $(url)"
}

invoker() {
  say "invoker — the SA may invoke the private service (Cloud Scheduler OIDC); then the two Scheduler jobs, created PAUSED"
  run gcloud run services add-iam-policy-binding "$FN" --project "$PROJECT" --region "$REGION" --member "serviceAccount:$(sa)" --role roles/run.invoker
  local u; u=$(url)
  for e in SEALSQ ICALPS; do
    local sched; [[ $e == SEALSQ ]] && sched="$SCHEDULE_SEALSQ" || sched="$SCHEDULE_ICALPS"
    local args=(--project "$PROJECT" --location "$REGION" --schedule "$sched" --time-zone "Europe/Zurich"
                --uri "${u}?entity=${e}" --http-method GET --oidc-service-account-email "$(sa)" --oidc-token-audience "$u"
                --attempt-deadline 600s --max-retry-attempts 3)
    if [[ "$DRYRUN" != 1 ]] && gcloud scheduler jobs describe "new-deals-$e" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
      run gcloud scheduler jobs update http "new-deals-$e" "${args[@]}"
    else
      run gcloud scheduler jobs create http "new-deals-$e" "${args[@]}"
      run gcloud scheduler jobs pause "new-deals-$e" --project "$PROJECT" --location "$REGION"
    fi
  done
  echo "  next: deploy.sh dry   (then deploy.sh enable)"
}

invoke() {  # invoke ENTITY [extra query]
  local u; u=$(url)
  # a user's gcloud ID token is accepted by Cloud Run as is; a service account's (Workbench, a VM) must carry the service URL as audience
  local acct; acct=$(cap gcloud auth list --filter status:ACTIVE --format 'value(account)')
  local tok
  if [[ "$acct" == *.gserviceaccount.com ]]; then tok=$(cap gcloud auth print-identity-token --audiences "$u"); else tok=$(cap gcloud auth print-identity-token); fi
  if [[ "$DRYRUN" == 1 ]]; then echo "  $ curl -sSf -H 'Authorization: Bearer <id-token>' '${u}?entity=$1${2:-}'" >&2; echo '{"rows_written": 0, "row_count": 0, "duplicate_suspects": 0, "day1_hot": [], "dry_run": true, "window": {"mode": "window", "watermark_in": "<wm>", "query_end": "<run_ts>"}}'
  else curl -sSf -H "Authorization: Bearer $tok" "${u}?entity=$1${2:-}"; fi   # -f: HTTP 403 (no invoker) or 409 (lease held) fails the step instead of passing as a payload
}

dry() {
  say "dry — the gate: compute everything for both entities, write nothing"
  local ok=1
  for e in SEALSQ ICALPS; do
    local out; out=$(invoke "$e" "&dry_run=1")
    python3 -c '
import json, sys
e = sys.argv[1]; p = json.loads(sys.argv[2]); w = p.get("window", {})
print("  %s: rows=%s written=%s dup=%s hot=%s window=%s -> %s" % (e, p.get("row_count"), p.get("rows_written"), p.get("duplicate_suspects"), len(p.get("day1_hot", [])), w.get("watermark_in", "?"), w.get("query_end", "?")))
assert p.get("rows_written") == 0, "dry run wrote rows"
assert p.get("dry_run") is True, "payload not marked dry_run"
' "$e" "$out" || ok=0
  done
  [[ $ok == 1 ]] || die "dry run failed — do not enable the schedulers"
  echo "  dry run passed for both entities. Next: deploy.sh run SEALSQ (first live run), deploy.sh probe, deploy.sh enable"
}

job_state() { cap gcloud scheduler jobs describe "new-deals-$1" --project "$PROJECT" --location "$REGION" --format 'value(state)'; }
enable() {  # idempotent: the API refuses to resume a job that is not PAUSED, so only those are resumed
  say "enable — resume the Scheduler jobs"
  for e in SEALSQ ICALPS; do
    if [[ "$DRYRUN" == 1 || "$(job_state "$e")" == PAUSED ]]; then run gcloud scheduler jobs resume "new-deals-$e" --project "$PROJECT" --location "$REGION"; else echo "  new-deals-$e: already enabled"; fi
  done
}
pause() {   # idempotent: only an ENABLED job can be paused
  say "pause — pause the Scheduler jobs"
  for e in SEALSQ ICALPS; do
    if [[ "$DRYRUN" == 1 || "$(job_state "$e")" == ENABLED ]]; then run gcloud scheduler jobs pause "new-deals-$e" --project "$PROJECT" --location "$REGION"; else echo "  new-deals-$e: not enabled (state: $(job_state "$e"))"; fi
  done
}
live()   { say "run — one live window run for ${1:?ENTITY}"; invoke "$1" | python3 -c 'import json,sys; p=json.load(sys.stdin); assert "error" not in p and "rows_written" in p, p.get("error", "payload without rows_written: the run did not succeed"); print(json.dumps({k:p[k] for k in ("report_id","run_timestamp","window","row_count","rows_written","duplicate_suspects","day1_hot") if k in p}, indent=1))'; }

replay() {  # replay ENTITY FROM_ISO — rewind the watermark, then run; MERGE on deal_id keeps it idempotent
  local e="${1:?ENTITY}" from="${2:?FROM_ISO e.g. 2026-09-01T00:00:00Z}"
  say "replay — rewind NEW_DEALS_$e to $from and run"
  run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false \
    "UPDATE \`${PROJECT}.${DATASET}.report_state\` SET watermark = TIMESTAMP '${from}', updated_at = CURRENT_TIMESTAMP() WHERE report_id = 'NEW_DEALS_${e}'"
  live "$e"
}

probe() {
  say "probe — what landed (run from any surface; identical result is the equality check)"
  run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false \
    "SELECT entity, COUNT(*) n, COUNTIF(day1_hot_flag) hot, COUNTIF(duplicate_suspect) dup, MIN(createdate) oldest, MAX(createdate) newest FROM \`${PROJECT}.${DATASET}.new_deals\` GROUP BY entity ORDER BY entity"
  run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false \
    "SELECT run_ts, entity, mode, dry_run, orchestrator, row_count, rows_written, status FROM \`${PROJECT}.${DATASET}.new_deals_runs\` ORDER BY run_ts DESC LIMIT 10"
}
status() {
  say "status — watermarks and leases"
  run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false \
    "SELECT report_id, watermark, lock_until, updated_at FROM \`${PROJECT}.${DATASET}.report_state\` ORDER BY report_id"
  for e in SEALSQ ICALPS; do run gcloud scheduler jobs describe "new-deals-$e" --project "$PROJECT" --location "$REGION" --format 'value(name,state,schedule,lastAttemptTime,status.code)'; done
}
logs() { say "logs — last run"; run gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$FN" --project "$PROJECT" --limit 50 --format 'value(timestamp,severity,textPayload,jsonPayload.message)'; }

case "${1:-}" in
  check-env) check_env ;;
  enable-apis) check_env; enable_apis ;;
  iam) check_env; iam ;;
  tables) check_env; tables ;;
  secret) check_env; secret ;;
  deploy) check_env; deploy ;;
  invoker) check_env; invoker ;;
  all) check_env; enable_apis; iam; tables; secret; deploy; invoker ;;
  dry) check_env; dry ;;
  enable) check_env; enable ;;
  pause) check_env; pause ;;
  run) check_env; live "${2:-}" ;;
  replay) check_env; replay "${2:-}" "${3:-}" ;;
  probe) check_env; probe ;;
  status) check_env; status ;;
  logs) check_env; logs ;;
  url) check_env; url ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
