#!/usr/bin/env bash
# cloudsql.sh — Cloud SQL Postgres for n8n (the durable store Cloud Run lacks). Every step is describe || create.
# db-f1-micro is the cost floor (≈ $9/month, outside the Cloud SQL SLA — acceptable: BigQuery stays the truth).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${REGION:=europe-west6}" "${SQL_TIER:=db-f1-micro}" "${SQL_INSTANCE:=n8n-db}"
DRYRUN="${DRYRUN:-0}"; [[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }; run() { if [[ "$DRYRUN" == 1 ]]; then printf '  $'; printf ' %q' "$@"; echo; else "$@"; fi; }
run gcloud services enable sqladmin.googleapis.com --project "$PROJECT"
if [[ "$DRYRUN" == 1 ]] || ! gcloud sql instances describe "$SQL_INSTANCE" --project "$PROJECT" >/dev/null 2>&1; then
  run gcloud sql instances create "$SQL_INSTANCE" --project "$PROJECT" --region "$REGION" --database-version POSTGRES_17 \
    --tier "$SQL_TIER" --storage-size 10GB --storage-type HDD --availability-type ZONAL --no-backup
fi
if [[ "$DRYRUN" == 1 ]] || ! gcloud sql databases describe n8n --instance "$SQL_INSTANCE" --project "$PROJECT" >/dev/null 2>&1; then
  run gcloud sql databases create n8n --instance "$SQL_INSTANCE" --project "$PROJECT"
fi
if [[ "$DRYRUN" == 1 ]]; then echo "  (would create user n8n-user with the password from Secret Manager n8n-db-password — not read in dry mode)"
elif ! gcloud sql users list --instance "$SQL_INSTANCE" --project "$PROJECT" --format 'value(name)' | grep -qx n8n-user; then
  gcloud secrets versions access latest --secret n8n-db-password --project "$PROJECT" >/dev/null 2>&1 || { echo "run deploy/n8n/secrets.sh first (creates n8n-db-password)"; exit 2; }
  PWFILE=$(mktemp); chmod 600 "$PWFILE"; trap 'rm -f "$PWFILE"' EXIT
  gcloud secrets versions access latest --secret n8n-db-password --project "$PROJECT" > "$PWFILE"
  gcloud sql users create n8n-user --instance "$SQL_INSTANCE" --project "$PROJECT" --password "$(cat "$PWFILE")"   # value never echoed
fi
echo "connection name: ${PROJECT}:${REGION}:${SQL_INSTANCE}"
