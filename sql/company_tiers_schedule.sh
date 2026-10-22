#!/usr/bin/env bash
# company_tiers_schedule.sh — register (or update) the daily refresh of the company snapshot: a BigQuery scheduled query running
# sql/company_tiers_apply.sql (pass 2b, lane Q), after the HubSpot → BigQuery transfer (02:00 UTC), off the hour.
#   sql/company_tiers_schedule.sh                 create-or-update; schedule SCHEDULE_UTC_COMPANY_TIERS (default "every day 03:37", UTC)
#   DISABLE_SCHEDULE=1 sql/company_tiers_schedule.sh   register without auto-scheduling (the gate: run one refresh by hand first)
#   DRYRUN=1 sql/company_tiers_schedule.sh        render, check placeholders, bq query --dry_run, register nothing
# Settings from ../.env: PROJECT DATASET BQ_LOCATION SQL_SA_NAME (default new-deals-sql) SYNC_DATASET; the view must exist (sql/apply.sh
# with SYNC_COMPANIES_TABLE set, or the notebook's ship cell) — the live path refuses to register ahead of it.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${SQL_SA_NAME:=new-deals-sql}" "${SCHEDULE_UTC_COMPANY_TIERS:=every day 03:37}" "${SYNC_DATASET:?}"
[[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
[[ "$SCHEDULE_UTC_COMPANY_TIERS" != *:00 ]] || { echo "SCHEDULE_UTC_COMPANY_TIERS is on the hour ($SCHEDULE_UTC_COMPANY_TIERS): BigQuery may trigger it twice — use e.g. 03:37" >&2; exit 2; }
DRYRUN="${DRYRUN:-0}"; SA="${SQL_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"; NAME="company-tiers-refresh"

Q=$(sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" "$HERE/company_tiers_apply.sql")
grep -q '\${' <<<"$Q" && { echo "unrendered placeholder in company_tiers_apply.sql" >&2; exit 2; }

if [[ "$DRYRUN" == 1 ]]; then
  echo "── $NAME: $(wc -l <<<"$Q") lines; schedule '$SCHEDULE_UTC_COMPANY_TIERS' (UTC); bq query --dry_run:"
  if ! out=$(bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false --dry_run --parameter="run_time:TIMESTAMP:$(date -u +%FT%TZ)" <<<"$Q" 2>&1); then
    if grep -qiE "credential|authoriz|auth |login|active account" <<<"$out"; then echo "   (dry_run needs credentials; rendered script saved to /tmp/company_tiers_apply.sql)"
    else echo "$out" >&2; echo "   bq --dry_run rejected the rendered script" >&2; exit 1; fi
  else echo "$out"; fi
  printf '%s\n' "$Q" > /tmp/company_tiers_apply.sql
  echo "next: sql/company_tiers_schedule.sh (DISABLE_SCHEDULE=1 first), one manual run, then without DISABLE_SCHEDULE"; exit 0
fi

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || gcloud iam service-accounts create "$SQL_SA_NAME" --project "$PROJECT" --display-name "new deals scheduled queries"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser --condition=None >/dev/null
bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""
bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${PROJECT}.${SYNC_DATASET}\` TO \"serviceAccount:${SA}\""
[[ -n "${ARR_DATASET:-}" ]] && bq --project_id="${ARR_PROJECT:-$PROJECT}" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${ARR_PROJECT:-$PROJECT}.${ARR_DATASET}\` TO \"serviceAccount:${SA}\""   # the view reads the ARR staging
bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.company_tiers_v1" >/dev/null 2>&1 || { echo "company_tiers_v1 does not exist — apply sql/company_tiers_v1.sql first (sql/apply.sh with SYNC_COMPANIES_TABLE, or the notebook)" >&2; exit 2; }
bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.company_tiers" >/dev/null 2>&1 || { echo "company_tiers does not exist — apply sql/company_tiers_v1.sql first" >&2; exit 2; }

EXISTING=$(bq ls --transfer_config --transfer_location="$BQ_LOCATION" --project_id="$PROJECT" --format=json 2>/dev/null \
           | python3 -c 'import sys,json; d=json.load(sys.stdin) or []; print(next((c["name"] for c in d if c.get("displayName")==sys.argv[1]),""))' "$NAME")
PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.stdin.read()}))' <<<"$Q")
# explicit on both paths: DISABLE_SCHEDULE=1 registers (or re-registers) paused; without it the config is (re-)enabled — the notebook's §7
NAS="--no_auto_scheduling=$([[ -n "${DISABLE_SCHEDULE:-}" ]] && echo true || echo false)"
if [[ -z "$EXISTING" ]]; then
  bq mk --transfer_config --project_id="$PROJECT" --location="$BQ_LOCATION" --data_source=scheduled_query --display_name="$NAME" \
     --schedule="$SCHEDULE_UTC_COMPANY_TIERS" --service_account_name="$SA" --params="$PARAMS" "$NAS"
else
  bq update --transfer_config --params="$PARAMS" --schedule="$SCHEDULE_UTC_COMPANY_TIERS" --service_account_name="$SA" "$NAS" "$EXISTING"
fi
cat <<TXT
manual refresh (writes the snapshot; the notebook's probe reads company_tiers_refreshes afterwards):
  bq mk --transfer_run --run_time=\$(date -u +%FT%TZ) <transfer_config_resource_name>
probe: SELECT refresh_ts, status, n_rows, n_companies, n_unresolved, n_deals, duration_ms FROM \`$PROJECT.$DATASET.company_tiers_refreshes\` ORDER BY refresh_ts DESC LIMIT 5
TXT
