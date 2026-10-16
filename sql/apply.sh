#!/usr/bin/env bash
# apply.sh — render and apply every SQL object of scenario C in dependency order (idempotent: OR REPLACE / IF NOT EXISTS).
#   sql/apply.sh            apply to ${PROJECT}.${DATASET}
#   DRYRUN=1 sql/apply.sh   render only; prints each statement's first line and checks no placeholder survives
# Settings from ../.env: PROJECT DATASET BQ_LOCATION PORTAL_ID SYNC_DATASET SYNC_DEALS_TABLE SYNC_OWNERS_TABLE
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?set PROJECT in .env}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${PORTAL_ID:=9201667}"
: "${SYNC_DATASET:?set SYNC_DATASET in .env (dataset the HubSpot→BigQuery sync writes to)}" "${SYNC_DEALS_TABLE:?}" "${SYNC_OWNERS_TABLE:?}"
DRYRUN="${DRYRUN:-0}"
for v in PROJECT SYNC_DATASET SYNC_DEALS_TABLE SYNC_OWNERS_TABLE; do [[ "${!v}" != your-* && "${!v}" != "<"*">" ]] || { echo "apply.sh: $v holds a placeholder (${!v})" >&2; exit 2; }; done

render() { sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${BQ_LOCATION}/$BQ_LOCATION/g" -e "s/\${PORTAL_ID}/$PORTAL_ID/g" \
               -e "s/\${SYNC_DATASET}/$SYNC_DATASET/g" -e "s/\${SYNC_DEALS_TABLE}/$SYNC_DEALS_TABLE/g" -e "s/\${SYNC_OWNERS_TABLE}/$SYNC_OWNERS_TABLE/g" "$1"; }

# order matters: tables (A's schema + audit) → UDF → adapter views → scoring views → pass-2 tier views + gold tables
FILES=("$ROOT/cloud_function_new_deals/bigquery_schema.sql" "$HERE/audit_tables.sql" "$ROOT/scoring/hot_score_v1.sql" "$HERE/deals_synced_v1.sql" "$HERE/hot_deals_v1.sql" "$HERE/deal_tiers_v1.sql")
for f in "${FILES[@]}"; do
  sql=$(render "$f")
  if grep -q '\${' <<<"$sql"; then echo "apply.sh: unrendered placeholder in $f:" >&2; grep -n '\${' <<<"$sql" >&2; exit 2; fi
  if [[ "$DRYRUN" == 1 ]]; then echo "── $(basename "$f"): $(grep -c -E '^(CREATE|ALTER)' <<<"$sql") DDL statement(s), $(wc -l <<<"$sql") lines (rendered OK)"
  else echo "── applying $(basename "$f")"; bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false <<<"$sql"; fi
done
echo "next: sql/refresh_pipeline_labels.sh (labels), sql/scheduled_query.sh (register the weekly script), bq query < tests/hot_score_vectors.sql (UDF parity)"
