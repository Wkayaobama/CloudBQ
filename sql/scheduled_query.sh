#!/usr/bin/env bash
# scheduled_query.sh — register or update one BigQuery scheduled query per entity running sql/new_deals_weekly.sql.
#   sql/scheduled_query.sh                 create-or-update both; schedule "every monday 04:00" (UTC — scheduled queries ignore DST:
#                                          04:00 UTC is 05:00/06:00 Europe/Zurich, always before the 05:30-Zurich write-back and A's 07:00)
#   DISABLE_SCHEDULE=1 sql/scheduled_query.sh   register without auto-scheduling (the gate: run one backfill by hand first)
#   DRYRUN=1 sql/scheduled_query.sh        render the two scripts, run `bq query --dry_run` on each (syntax + bytes), register nothing
# Settings from ../.env: PROJECT DATASET BQ_LOCATION PORTAL_ID SQL_SA_NAME (default new-deals-sql)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${PORTAL_ID:=9201667}" "${SQL_SA_NAME:=new-deals-sql}" "${SCHEDULE_UTC:=every monday 04:00}" "${SYNC_DATASET:?}"
[[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
DRYRUN="${DRYRUN:-0}"; SA="${SQL_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
declare -A PIPES=([SEALSQ]="['12096408','13772279','705868909','934982230']" [ICALPS]="['766126206']")

render() { sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${PORTAL_ID}/$PORTAL_ID/g" -e "s/\${ENTITY}/$1/g" -e "s/\${PIPELINES}/${PIPES[$1]}/g" "$HERE/new_deals_weekly.sql"; }

if [[ "$DRYRUN" != 1 ]]; then
  gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || gcloud iam service-accounts create "$SQL_SA_NAME" --project "$PROJECT" --display-name "new deals scheduled queries"
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser --condition=None >/dev/null
  bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""
  bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${PROJECT}.${SYNC_DATASET}\` TO \"serviceAccount:${SA}\""   # the script reads the synced tables
fi
for E in SEALSQ ICALPS; do
  Q=$(render "$E"); NAME="new-deals-$E-C"
  grep -q '\${' <<<"$Q" && { echo "unrendered placeholder for $E" >&2; exit 2; }
  if [[ "$DRYRUN" == 1 ]]; then
    echo "── $NAME: $(wc -l <<<"$Q") lines; bq query --dry_run:"
    bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false --dry_run --parameter="run_time:TIMESTAMP:$(date -u +%FT%TZ)" <<<"$Q" || echo "   (dry_run needs credentials; rendered script saved to /tmp/new_deals_weekly_$E.sql)"; printf '%s\n' "$Q" > "/tmp/new_deals_weekly_$E.sql"; continue
  fi
  EXISTING=$(bq ls --transfer_config --transfer_location="$BQ_LOCATION" --project_id="$PROJECT" --format=json 2>/dev/null \
             | python3 -c 'import sys,json; d=json.load(sys.stdin) or []; print(next((c["name"] for c in d if c.get("displayName")==sys.argv[1]),""))' "$NAME")
  PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.stdin.read()}))' <<<"$Q")
  if [[ -z "$EXISTING" ]]; then
    bq mk --transfer_config --project_id="$PROJECT" --location="$BQ_LOCATION" --data_source=scheduled_query --display_name="$NAME" \
       --schedule="$SCHEDULE_UTC" --service_account_name="$SA" --params="$PARAMS" ${DISABLE_SCHEDULE:+--no_auto_scheduling}
  else
    bq update --transfer_config --params="$PARAMS" --schedule="$SCHEDULE_UTC" --service_account_name="$SA" "$EXISTING"
  fi
done
cat <<TXT
manual run (the C gate — writes to the real tables, so use a dev dataset first if you need a no-write rehearsal):
  bq mk --transfer_run --run_time=\$(date -u +%FT%TZ) <transfer_config_resource_name>
replay a week:
  bq mk --transfer_run --start_time=2026-09-28T04:00:00Z --end_time=2026-10-05T04:00:00Z <transfer_config_resource_name>
TXT
