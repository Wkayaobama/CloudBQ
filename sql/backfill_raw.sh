#!/usr/bin/env bash
# backfill_raw.sh — one-time landing of the 90-day set into deals_raw / labels_raw with orchestrator = 'backfill' (pass 3 phase 1, D3):
# the duplicate horizon is full from the cut-over run instead of growing for 13 weeks. Lands from the sync table (sql/land_raw.sql).
#   sql/backfill_raw.sh                          both entities, run_ts = now (second-truncated)
#   RUN_TS=2026-10-27T04:00:00Z sql/backfill_raw.sh ICALPS     one entity at a given cut-over run_ts
#   DRYRUN=1 sql/backfill_raw.sh                 render, check placeholders, bq query --dry_run (syntax + bytes), execute nothing
# Settings from ../.env: PROJECT DATASET BQ_LOCATION SYNC_DATASET SYNC_DEALS_TABLE
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}" "${SYNC_DATASET:?}" "${SYNC_DEALS_TABLE:?}"
[[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
DRYRUN="${DRYRUN:-0}"; RUN_TS="${RUN_TS:-$(date -u +%FT%TZ)}"
declare -A PIPES=([SEALSQ]="['12096408','13772279','705868909','934982230']" [ICALPS]="['766126206']")
render() {
  { cat <<SQL
DECLARE v_entity STRING DEFAULT '$1';
DECLARE v_pipelines ARRAY<STRING> DEFAULT ${PIPES[$1]};
DECLARE v_run_ts TIMESTAMP DEFAULT TIMESTAMP_TRUNC(TIMESTAMP '$RUN_TS', SECOND);
DECLARE v_orchestrator STRING DEFAULT 'backfill';
DECLARE v_mode STRING DEFAULT 'window';
DECLARE v_landed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP();
DECLARE v_gaps ARRAY<STRING> DEFAULT [];
SQL
    cat "$HERE/land_raw.sql"
    cat <<'SQL'
SELECT 'backfill' AS step, v_entity AS entity, v_run_ts AS run_ts, v_gaps AS data_gaps;
SQL
  } | sed -e "s/\${PROJECT}/$PROJECT/g" -e "s/\${DATASET}/$DATASET/g" -e "s/\${SYNC_DATASET}/$SYNC_DATASET/g" -e "s/\${SYNC_DEALS_TABLE}/$SYNC_DEALS_TABLE/g"
}
for E in ${1:-SEALSQ ICALPS}; do
  [[ -n "${PIPES[$E]:-}" ]] || { echo "unknown entity $E" >&2; exit 2; }
  Q=$(render "$E")
  grep -q '\${' <<<"$Q" && { echo "unrendered placeholder for $E" >&2; exit 2; }
  if [[ "$DRYRUN" == 1 ]]; then
    echo "── backfill $E at $RUN_TS: $(wc -l <<<"$Q") lines; bq query --dry_run:"
    if ! out=$(bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false --dry_run <<<"$Q" 2>&1); then
      if grep -qiE "credential|authoriz|auth |login|active account" <<<"$out"; then echo "   (dry_run needs credentials; rendered script saved to /tmp/backfill_raw_$E.sql)"
      else echo "$out" >&2; echo "   bq --dry_run rejected the rendered script for $E" >&2; exit 1; fi
    else echo "$out"; fi
    printf '%s\n' "$Q" > "/tmp/backfill_raw_$E.sql"; continue
  fi
  echo "── backfill $E at $RUN_TS (orchestrator = backfill)"
  bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false <<<"$Q"
done
echo "probe: SELECT orchestrator, entity, COUNT(*) FROM \`$PROJECT.$DATASET.deals_raw\` WHERE run_ts = TIMESTAMP '$RUN_TS' GROUP BY 1, 2"
