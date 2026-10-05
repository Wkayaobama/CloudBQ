#!/usr/bin/env bash
# sync_transfer.sh — HubSpot → BigQuery with the Google BigQuery Data Transfer Service HubSpot connector (Preview, free while
# in Preview; full refresh on every run). Creates or reports the transfer config for assets Deals + Owners, daily 02:00 UTC,
# so the Monday 04:00 UTC scheduled query reads a sync at most ~26 h old (freshness guard is 36 h).
# Needs a HubSpot private-app token with crm.objects.deals.read + crm.objects.owners.read in HUBSPOT_TOKEN (not stored here:
# the connector keeps its own copy inside the transfer config).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${BQ_LOCATION:=EU}" "${SYNC_DATASET:?}" "${HUBSPOT_TOKEN:?}" "${SYNC_SCHEDULE:=every day 02:00}"
NAME="hubspot-sync-deals-owners"
bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "CREATE SCHEMA IF NOT EXISTS \`${PROJECT}.${SYNC_DATASET}\` OPTIONS (location = '${BQ_LOCATION}')"
EXISTING=$(bq ls --transfer_config --transfer_location="$BQ_LOCATION" --project_id="$PROJECT" --format=json 2>/dev/null \
           | python3 -c 'import sys,json; d=json.load(sys.stdin) or []; print(next((c["name"] for c in d if c.get("displayName")==sys.argv[1]),""))' "$NAME")
if [[ -n "$EXISTING" ]]; then echo "transfer config exists: $EXISTING (update the token with: bq update --transfer_config --params=... $EXISTING)"; exit 0; fi
PARAMS=$(python3 -c 'import json,os; print(json.dumps({"assets": ["Deals", "Owners"], "connector.authentication.oauth.accessToken": os.environ["HUBSPOT_TOKEN"]}))')
bq mk --transfer_config --project_id="$PROJECT" --location="$BQ_LOCATION" --data_source=hubspot --target_dataset="$SYNC_DATASET" \
   --display_name="$NAME" --schedule="$SYNC_SCHEDULE" --params="$PARAMS"
echo "after the first run: bq ls ${PROJECT}:${SYNC_DATASET}  → put the deals/owners table names into .env SYNC_DEALS_TABLE / SYNC_OWNERS_TABLE, then sql/apply.sh"
