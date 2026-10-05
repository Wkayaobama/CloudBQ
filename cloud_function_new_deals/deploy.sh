#!/usr/bin/env bash
# One-time deployment: Cloud Run function (gen2) + Secret Manager + two Cloud Scheduler jobs (SEALSQ, ICALPS)
set -euo pipefail
PROJECT=your_project; REGION=europe-west6; DATASET=hubspot; FN=new-deals-report
SA=new-deals-fn@${PROJECT}.iam.gserviceaccount.com

# 1. Service account + BigQuery rights
gcloud iam service-accounts create new-deals-fn --project $PROJECT --display-name "new deals report function" || true
bq --project_id=$PROJECT query --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`${PROJECT}.${DATASET}\` TO 'serviceAccount:${SA}'"
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:$SA --role roles/bigquery.jobUser

# 2. HubSpot private-app token in Secret Manager (scopes: crm.objects.deals.read, crm.schemas.deals.read, crm.objects.owners.read)
printf '%s' "$HUBSPOT_TOKEN" | gcloud secrets create hubspot-token --project $PROJECT --data-file=- || \
printf '%s' "$HUBSPOT_TOKEN" | gcloud secrets versions add hubspot-token --project $PROJECT --data-file=-
gcloud secrets add-iam-policy-binding hubspot-token --project $PROJECT --member serviceAccount:$SA --role roles/secretmanager.secretAccessor

# 3. Tables
bq --project_id=$PROJECT query --use_legacy_sql=false < bigquery_schema.sql

# 4. Function (private; Scheduler invokes with OIDC)
gcloud functions deploy $FN --gen2 --project $PROJECT --region $REGION --runtime python312 --entry-point new_deals_report \
  --trigger-http --no-allow-unauthenticated --service-account $SA --timeout 540s --memory 512Mi \
  --set-env-vars BQ_PROJECT=$PROJECT,BQ_DATASET=$DATASET,OVERLAP_MINUTES=5,FIRST_RUN_DAYS=7,PORTAL_ID=9201667,DELIVERY_WEBHOOK_URL=${DELIVERY_WEBHOOK_URL:-} \
  --set-secrets HUBSPOT_TOKEN=hubspot-token:latest
URL=$(gcloud functions describe $FN --gen2 --project $PROJECT --region $REGION --format 'value(serviceConfig.uri)')

# 5. Scheduler — Monday 07:00 Europe/Zurich, one job per entity (runs are independent, each with its own watermark)
for ENTITY in SEALSQ ICALPS; do
  gcloud scheduler jobs create http new-deals-$ENTITY --project $PROJECT --location $REGION --schedule "0 7 * * 1" --time-zone "Europe/Zurich" \
    --uri "${URL}?entity=${ENTITY}" --http-method GET --oidc-service-account-email $SA --oidc-token-audience "$URL" \
    --attempt-deadline 600s --max-retry-attempts 3 || true
done
echo "Dry run: curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \"${URL}?entity=SEALSQ&dry_run=1\""
