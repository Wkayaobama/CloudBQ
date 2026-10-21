#!/usr/bin/env bash
# scheduled_query.sh — register or update one BigQuery scheduled query per entity running sql/new_deals_weekly.sql.
#   sql/scheduled_query.sh                 create-or-update both; schedules SEALSQ "every monday 03:53", ICALPS "every monday 04:23" (UTC — scheduled queries ignore DST:
#                                          per-entity, off the hour: SEALSQ 03:53 UTC, ICALPS 04:23 UTC — two scripts in one minute would be
#                                          cancelled as conflicting transactions, and an on-the-hour schedule can trigger twice; both before A's 07:00 Zurich)
#   DISABLE_SCHEDULE=1 sql/scheduled_query.sh   register without auto-scheduling (the gate: run one backfill by hand first)
#   DRYRUN=1 sql/scheduled_query.sh        render the two scripts, run `bq query --dry_run` on each (syntax + bytes), register nothing
# Settings from ../.env: PROJECT DATASET BQ_LOCATION PORTAL_ID SQL_SA_NAME (default new-deals-sql) SYNC_DATASET SYNC_DEALS_TABLE
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${PORTAL_ID:=9201667}" "${SQL_SA_NAME:=new-deals-sql}" "${SCHEDULE_UTC_SEALSQ:=every monday 03:53}" "${SCHEDULE_UTC_ICALPS:=every monday 04:23}" "${SYNC_DATASET:?}" "${SYNC_DEALS_TABLE:?set SYNC_DEALS_TABLE in .env (the landing reads the sync table directly)}"
[[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
DRYRUN="${DRYRUN:-0}"; SA="${SQL_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
declare -A PIPES=([SEALSQ]="['12096408','13772279','705868909','934982230']" [ICALPS]="['766126206']")
declare -A SCHED=([SEALSQ]="$SCHEDULE_UTC_SEALSQ" [ICALPS]="$SCHEDULE_UTC_ICALPS")   # never the same minute, never on the hour
for E in SEALSQ ICALPS; do [[ "${SCHED[$E]}" != *:00 ]] || { echo "SCHEDULE_UTC_$E is on the hour (${SCHED[$E]}): BigQuery may trigger it twice — use e.g. 03:53" >&2; exit 2; }; done
[[ "${SCHED[SEALSQ]}" != "${SCHED[ICALPS]}" ]] || { echo "the two entities share a schedule minute: their transactions would cancel each other" >&2; exit 2; }

# render: splice sql/land_raw.sql at its marker (sed `r` appends the file after the marker line), then substitute the placeholders
render() { sed -e "/^-- @include land_raw.sql[[:space:]]*$/r $HERE/land_raw.sql" "$HERE/new_deals_weekly.sql" \
           | sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${PORTAL_ID}/$PORTAL_ID/g" -e "s/\${ENTITY}/$1/g" -e "s/\${PIPELINES}/${PIPES[$1]}/g" \
                 -e "s/\${SYNC_DATASET}/$SYNC_DATASET/g" -e "s/\${SYNC_DEALS_TABLE}/$SYNC_DEALS_TABLE/g"; }

if [[ "$DRYRUN" != 1 ]]; then
  gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 || gcloud iam service-accounts create "$SQL_SA_NAME" --project "$PROJECT" --display-name "new deals scheduled queries"
  gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/bigquery.jobUser --condition=None >/dev/null
  bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${SA}\""
  bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${PROJECT}.${SYNC_DATASET}\` TO \"serviceAccount:${SA}\""   # the script reads the synced tables
  # the script's runs row names data_gaps and the landing writes deals_raw: both come from `deploy.sh tables` — refuse to register ahead of it
  bq --project_id="$PROJECT" show --schema "${PROJECT}:${DATASET}.new_deals_runs" | grep -q '"name": *"data_gaps"' || { echo "new_deals_runs has no data_gaps column — run cloud_function_new_deals/deploy.sh tables first" >&2; exit 2; }
  bq --project_id="$PROJECT" show "${PROJECT}:${DATASET}.deals_raw" >/dev/null 2>&1 || { echo "deals_raw does not exist — run cloud_function_new_deals/deploy.sh tables first" >&2; exit 2; }
fi
for E in SEALSQ ICALPS; do
  Q=$(render "$E"); NAME="new-deals-$E-C"
  grep -q '\${' <<<"$Q" && { echo "unrendered placeholder for $E" >&2; exit 2; }
  grep -q "INSERT INTO \`$PROJECT.$DATASET.deals_raw\`" <<<"$Q" || { echo "sql/land_raw.sql was not spliced for $E (marker or path drifted) — refusing to register a script without the landing" >&2; exit 2; }
  if [[ "$DRYRUN" == 1 ]]; then
    echo "── $NAME: $(wc -l <<<"$Q") lines; bq query --dry_run:"
    if ! out=$(bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false --dry_run --parameter="run_time:TIMESTAMP:$(date -u +%FT%TZ)" <<<"$Q" 2>&1); then
      if grep -qiE "credential|authoriz|auth |login|active account" <<<"$out"; then echo "   (dry_run needs credentials; rendered script saved to /tmp/new_deals_weekly_$E.sql)"
      else echo "$out" >&2; echo "   bq --dry_run rejected the rendered script for $E" >&2; exit 1; fi
    else echo "$out"; fi
    printf '%s\n' "$Q" > "/tmp/new_deals_weekly_$E.sql"; continue
  fi
  EXISTING=$(bq ls --transfer_config --transfer_location="$BQ_LOCATION" --project_id="$PROJECT" --format=json 2>/dev/null \
             | python3 -c 'import sys,json; d=json.load(sys.stdin) or []; print(next((c["name"] for c in d if c.get("displayName")==sys.argv[1]),""))' "$NAME")
  PARAMS=$(python3 -c 'import json,sys; print(json.dumps({"query": sys.stdin.read()}))' <<<"$Q")
  if [[ -z "$EXISTING" ]]; then
    bq mk --transfer_config --project_id="$PROJECT" --location="$BQ_LOCATION" --data_source=scheduled_query --display_name="$NAME" \
       --schedule="${SCHED[$E]}" --service_account_name="$SA" --params="$PARAMS" ${DISABLE_SCHEDULE:+--no_auto_scheduling}
  else
    bq update --transfer_config --params="$PARAMS" --schedule="${SCHED[$E]}" --service_account_name="$SA" "$EXISTING"
  fi
done
cat <<TXT
manual run (the C gate — writes to the real tables, so use a dev dataset first if you need a no-write rehearsal):
  bq mk --transfer_run --run_time=\$(date -u +%FT%TZ) <transfer_config_resource_name>
replay a week:
  bq mk --transfer_run --start_time=2026-09-28T04:00:00Z --end_time=2026-10-05T04:00:00Z <transfer_config_resource_name>
TXT
