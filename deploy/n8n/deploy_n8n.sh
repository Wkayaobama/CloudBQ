#!/usr/bin/env bash
# deploy_n8n.sh — render service.yaml and apply it declaratively (gcloud run services replace). Idempotent.
#   deploy/n8n/deploy_n8n.sh           apply; prints the service URL
#   DRYRUN=1 deploy/n8n/deploy_n8n.sh  render only (writes /tmp/n8n.service.yaml, checks no placeholder survives)
# Settings from ../../.env: PROJECT REGION DATASET PORTAL_ID N8N_IMAGE (pinned tag) MIN_SCALE (0) MAIL_FROM MAIL_TO
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
[[ -f "$ROOT/.env" ]] && { set -a; . "$ROOT/.env"; set +a; }
: "${PROJECT:?}" "${REGION:=europe-west6}" "${DATASET:=hubspot}" "${PORTAL_ID:=9201667}" "${N8N_IMAGE:=docker.io/n8nio/n8n:2.41.7}" "${MIN_SCALE:=0}" "${MAIL_FROM:=n8n@example.com}" "${MAIL_TO:=sales-ops@example.com}"
DRYRUN="${DRYRUN:-0}"; [[ "$PROJECT" != your-* ]] || { echo "PROJECT holds a placeholder" >&2; exit 2; }
[[ "$N8N_IMAGE" != *:latest ]] || { echo "pin N8N_IMAGE to a tag or digest, not :latest (env-var names and node versions drift)"; exit 2; }
PN=$([[ "$DRYRUN" == 1 ]] && echo 000000000000 || gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
sed -e "s#\${PROJECT_NUMBER}#$PN#g" -e "s#\${PROJECT}#$PROJECT#g" -e "s#\${REGION}#$REGION#g" -e "s#\${N8N_IMAGE}#$N8N_IMAGE#g" -e "s#\${MIN_SCALE}#$MIN_SCALE#g" \
    -e "s#\${MAIL_FROM}#$MAIL_FROM#g" -e "s#\${MAIL_TO}#$MAIL_TO#g" -e "s#\${DATASET}#$DATASET#g" -e "s#\${PORTAL_ID}#$PORTAL_ID#g" "$HERE/service.yaml" > /tmp/n8n.service.yaml
grep -q '\${' /tmp/n8n.service.yaml && { echo "unrendered placeholder:"; grep -n '\${' /tmp/n8n.service.yaml; exit 2; }
if [[ "$DRYRUN" == 1 ]]; then echo "rendered /tmp/n8n.service.yaml ($(wc -l < /tmp/n8n.service.yaml) lines); image $N8N_IMAGE; minScale $MIN_SCALE"; exit 0; fi
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com --project "$PROJECT"
gcloud run services replace /tmp/n8n.service.yaml --project "$PROJECT" --region "$REGION"
gcloud run services add-iam-policy-binding n8n --project "$PROJECT" --region "$REGION" --member allUsers --role roles/run.invoker   # editor login + webhooks; Header Auth protects the webhook
echo "URL: $(gcloud run services describe n8n --project "$PROJECT" --region "$REGION" --format 'value(status.url)')  (first visit creates the owner account; enable 2FA)"
