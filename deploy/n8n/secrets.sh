#!/usr/bin/env bash
# secrets.sh — the three n8n secrets and the two service accounts. Create-or-add-version; never echoes a secret value.
#   n8n-encryption-key   (openssl rand -base64 42)  — pinned forever: losing it makes every stored credential unreadable
#   n8n-db-password      (openssl rand -base64 24)
#   n8n-webhook-token    (openssl rand -hex 32)      — shared header X-Delivery-Token between the function / Scheduler and the webhook
# SAs: n8n-run (cloudsql.client, secretAccessor on the three secrets); n8n-bq (bigquery.jobUser + dataset dataEditor) whose JSON key
# becomes the n8n Google Service Account credential — n8n has no keyless path (B-G10). The key is written to a gitignored file.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${DATASET:=hubspot}" "${BQ_LOCATION:=EU}"
DRYRUN="${DRYRUN:-0}"; [[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }; run() { if [[ "$DRYRUN" == 1 ]]; then printf '  $'; printf ' %q' "$@"; echo; else "$@"; fi; }
ensure_secret() {  # name generator-command
  if [[ "$DRYRUN" == 1 ]]; then echo "  (secret $1: create if missing with: $2)"; return; fi
  if ! gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1; then
    eval "$2" | tr -d '\n' | gcloud secrets create "$1" --project "$PROJECT" --replication-policy automatic --data-file=-; echo "created $1"
  else echo "exists $1"; fi
}
ensure_sa() { if [[ "$DRYRUN" == 1 ]] || ! gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1; then run gcloud iam service-accounts create "$1" --project "$PROJECT" --display-name "$2"; fi; }
ensure_secret n8n-encryption-key "openssl rand -base64 42"
ensure_secret n8n-db-password    "openssl rand -base64 24"
ensure_secret n8n-webhook-token  "openssl rand -hex 32"
ensure_sa n8n-run "n8n Cloud Run runtime"; ensure_sa n8n-bq "n8n BigQuery credential (key)"
RUN_SA="n8n-run@${PROJECT}.iam.gserviceaccount.com"; BQ_SA="n8n-bq@${PROJECT}.iam.gserviceaccount.com"
run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$RUN_SA" --role roles/cloudsql.client --condition=None
for s in n8n-encryption-key n8n-db-password n8n-webhook-token; do run gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" --member "serviceAccount:$RUN_SA" --role roles/secretmanager.secretAccessor; done
run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$BQ_SA" --role roles/bigquery.jobUser --condition=None
run bq --project_id="$PROJECT" --location="$BQ_LOCATION" query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO \"serviceAccount:${BQ_SA}\""
KEY="$HERE/.secrets/n8n-bq.key.json"; mkdir -p "$HERE/.secrets"
if [[ "$DRYRUN" == 1 ]]; then echo "  (would create a key for $BQ_SA at $KEY — gitignored; import it as the n8n Google Service Account credential)"
elif [[ ! -f "$KEY" ]]; then gcloud iam service-accounts keys create "$KEY" --iam-account "$BQ_SA" --project "$PROJECT"; chmod 600 "$KEY"; echo "key written to $KEY (gitignored)"; fi
echo "next: deploy/n8n/cloudsql.sh → deploy/n8n/deploy_n8n.sh → deploy/n8n/import_workflows.sh (B1 delivery tail; the function posts to it)"
